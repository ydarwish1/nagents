"""Answers from outside the process — e.g. Claude subagents instead of the API.

The run is a loop, driven by `nagents run --subagents`:

1. The grid runs as usual, but every call looks its reply up in
   `<run>/answers.jsonl`. A call with no stored reply is written to
   `<run>/pending.jsonl` and its trial cell is left unwritten.
2. `nagents batches <run>` splits the pending calls into batches for solver
   subagents. A batch never holds the same task twice, so one subagent never
   answers the same problem for two seats (that would fake agreement).
3. Each subagent answers its batch; `nagents ingest <run> <file>` stores the
   replies in answers.jsonl.
4. Rerun the same command with --resume. Finished cells are reused; cells
   whose calls are now answered get written. Debate needs one extra loop:
   round-2 prompts only exist once round-1 answers are in.

Every stored reply is keyed by a hash of exactly what the agent saw (system
prompt, prompt, task, seat, round), so a reply can never be reused for a
different question. Token counts are estimated from text length (the
subagent runtime does not report per-reply usage) and flagged as estimates.
"""
import hashlib
import json
from collections import Counter
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .models import ModelReply

ANSWERS_FILE = "answers.jsonl"
PENDING_FILE = "pending.jsonl"
BATCHES_FILE = "batches.json"


class PendingAnswers(Exception):
    """Raised by run_grid when some calls still need an outside answer."""

    def __init__(self, requests: int, cells: int, path: Path):
        super().__init__(f"{requests} call(s) need answers ({cells} trial cell(s) waiting)")
        self.requests = requests
        self.cells = cells
        self.path = path


def request_key(system: str, prompt: str, meta: dict) -> str:
    payload = json.dumps(
        [system, prompt, meta["task_id"], meta["agent"], meta.get("round", 0)],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def load_answers(run_dir) -> Dict[str, dict]:
    path = Path(run_dir) / ANSWERS_FILE
    answers = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                answers[row["key"]] = row
    return answers


class ExternalModel:
    """Model whose replies are supplied from outside (answers.jsonl)."""

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.answers = load_answers(run_dir)
        self.pending: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cell_rounds: List[int] = []

    def begin_cell(self) -> None:
        self._cell_rounds = []

    def cell_pending(self) -> bool:
        return bool(self._cell_rounds)

    def complete(self, system: str, prompt: str, meta: dict) -> ModelReply:
        key = request_key(system, prompt, meta)
        row = self.answers.get(key)
        if row is not None:
            text = row["reply"]
            return ModelReply(
                text=text,
                input_tokens=row.get("input_tokens", _estimate_tokens(system + prompt)),
                output_tokens=row.get("output_tokens", _estimate_tokens(text)),
                stop_reason=row.get("stop_reason", "end_turn"),
            )
        rnd = meta.get("round", 0)
        with self._lock:
            # A later round built on a missing earlier answer is garbage — do
            # not ask anyone to answer it; it is rebuilt once the answer exists.
            earlier_missing = any(r < rnd for r in self._cell_rounds)
            self._cell_rounds.append(rnd)
            if not earlier_missing:
                self.pending.setdefault(
                    key,
                    {
                        "key": key,
                        "task_id": meta["task_id"],
                        "agent": meta["agent"],
                        "round": rnd,
                        "system": system,
                        "prompt": prompt,
                    },
                )
        return ModelReply(text="", stop_reason="pending")

    def write_pending(self) -> Path:
        path = self.run_dir / PENDING_FILE
        rows = sorted(self.pending.values(), key=lambda r: (r["round"], r["agent"], r["task_id"]))
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def clear_pending_file(self) -> None:
        path = self.run_dir / PENDING_FILE
        if path.exists():
            path.unlink()


def make_batches(run_dir, per_batch: int = 10) -> List[dict]:
    """Split pending calls into subagent batches and write batches.json.

    A batch never holds the same task twice, so no subagent ever answers one
    problem for two seats. Seats are spread across batches rather than one
    seat per batch: subagents differ in how careful they are, and a seat
    answered by a single subagent would make that seat (and the 1-agent
    group) only as good as that one subagent. Inside a batch the order is
    shuffled, since the first problem gets the most care.
    """
    if per_batch < 1:
        raise ValueError("per_batch must be at least 1")
    path = Path(run_dir) / PENDING_FILE
    if not path.exists():
        raise SystemExit(f"{path} not found — nothing is waiting for answers.")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_round: Dict[int, List[dict]] = {}
    for row in rows:
        by_round.setdefault(row["round"], []).append(row)
    batches = []
    for rnd, items in sorted(by_round.items()):
        items.sort(key=lambda r: r["agent"])  # stable: keeps task order within a seat
        seats_per_task = max(Counter(r["task_id"] for r in items).values())
        n_open = max(-(-len(items) // per_batch), seats_per_task)
        open_batches: List[List[dict]] = [[] for _ in range(n_open)]
        for j, row in enumerate(items):
            for k in range(len(open_batches)):
                batch = open_batches[(j + k) % len(open_batches)]
                if len(batch) < per_batch and all(r["task_id"] != row["task_id"] for r in batch):
                    batch.append(row)
                    break
            else:
                open_batches.append([row])
        for batch in open_batches:
            if not batch:
                continue
            # Solvers work the first problem in a batch more carefully than the
            # rest, so the order inside a batch must not follow the seat.
            batch.sort(key=lambda r: hashlib.sha256(r["key"].encode()).hexdigest())
            batches.append(
                {
                    "batch": f"b{len(batches):03d}",
                    "round": rnd,
                    "seats": sorted({r["agent"] for r in batch}),
                    "system": batch[0]["system"],
                    "items": [{"id": r["key"], "seat": r["agent"], "prompt": r["prompt"]} for r in batch],
                }
            )
    (Path(run_dir) / BATCHES_FILE).write_text(json.dumps(batches, indent=2), encoding="utf-8")
    return batches


def batch_prompt(batch: dict) -> str:
    """The exact message a solver subagent receives for one batch."""
    lines = [
        batch["system"],
        "",
        f"Below are {len(batch['items'])} separate problems. Solve each one on its own, "
        "doing all arithmetic yourself: no tools, no code, no calculator. "
        "Keep the working brief.",
        "",
        "Reply with one block per problem, in this exact format and nothing else:",
        "=== <problem id>",
        "<brief working>",
        "Answer: <number>",
        "",
    ]
    for item in batch["items"]:
        lines.append(f"--- problem id: {item['id']}")
        lines.append(item["prompt"])
        lines.append("")
    return "\n".join(lines)


_BLOCK = re.compile(r"^===\s*([0-9a-f]{24})\s*$", re.MULTILINE)


def parse_replies(text: str) -> Dict[str, str]:
    """Split a subagent's reply into {problem id: reply text}."""
    out = {}
    marks = list(_BLOCK.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = text[m.end():end].strip()
    return out


def ingest(run_dir, text: str, source: Optional[str] = None) -> dict:
    """Store replies for pending calls. Unknown ids are rejected, stored ones kept."""
    run = Path(run_dir)
    pending_path = run / PENDING_FILE
    if not pending_path.exists():
        raise SystemExit(f"{pending_path} not found — nothing is waiting for answers.")
    pending = {
        json.loads(l)["key"]: json.loads(l)
        for l in pending_path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    }
    existing = load_answers(run)
    replies = parse_replies(text)
    unknown = sorted(k for k in replies if k not in pending)
    added = 0
    with (run / ANSWERS_FILE).open("a", encoding="utf-8") as fh:
        for key, reply in replies.items():
            if key not in pending or key in existing:
                continue
            req = pending[key]
            row = {
                "key": key,
                "task_id": req["task_id"],
                "agent": req["agent"],
                "round": req["round"],
                "reply": reply,
                "input_tokens": _estimate_tokens(req["system"] + req["prompt"]),
                "output_tokens": _estimate_tokens(reply),
                "tokens_estimated": True,
            }
            if source:
                row["source"] = source
            fh.write(json.dumps(row) + "\n")
            added += 1
    return {"added": added, "unknown": unknown, "parsed": len(replies)}
