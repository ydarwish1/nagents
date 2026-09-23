"""Run the grid: same tasks, every group size, full transcripts on disk.

Trial t uses the same task and the same trial seed at every group size, so
size comparisons are paired and the paired bootstrap in stats.py is licensed.

Crash safety: every trial cell is one JSON file, written the moment it
finishes. A killed run is continued with resume=True — finished cells are
reloaded from disk (never re-run, never re-billed) after the run directory's
manifest is checked against the current config. results.json can always be
rebuilt from the trial files alone with recompute(); it refuses incomplete
runs, so a partial grid can never masquerade as a result.
"""
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__
from .external import PendingAnswers
from .stats import error_overlap, independent_vote_accuracy, mean, seat_balanced, summarize
from .topologies import run_group

_VOLATILE_KEYS = ("started_at", "nagents_version")


def _stable_view(manifest: dict) -> dict:
    """The parts of a manifest that must match for a resume to be legal."""
    view = {k: v for k, v in manifest.items() if k not in _VOLATILE_KEYS}
    config = dict(view.get("config") or {})
    config.pop("workers", None)  # workers changes speed, never results
    view["config"] = config
    return view


def _cell_name(trial: int, size: int) -> str:
    return f"t{trial:04d}-n{size:02d}.json"


def _trial_stats(record: dict) -> dict:
    refusal = any(
        rnd.get("stop_reason") == "refusal"
        for agent in record["agents"]
        for rnd in agent["rounds"]
    )
    expected = str(record["expected"])
    return {
        "correct": 1 if record["correct"] else 0,
        "in": record["usage"]["input_tokens"],
        "out": record["usage"]["output_tokens"],
        "refusal": refusal,
        "unparsed": any(v == "" for v in record["votes"]),
        "any_correct": any(v == expected for v in record["votes"]),
        "round0": [agent["rounds"][0]["answer"] for agent in record["agents"]],
        "expected": expected,
    }


def _finalize(sizes: List[int], stats_by_size: dict, epsilon: float = 0.01, topology: str = None) -> dict:
    correct = {s: [st["correct"] for st in stats_by_size[s]] for s in sizes}
    out_tokens = {s: [st["out"] for st in stats_by_size[s]] for s in sizes}
    extras = {
        s: {
            "input_tokens_total": sum(st["in"] for st in stats_by_size[s]),
            "output_tokens_total": sum(st["out"] for st in stats_by_size[s]),
            "refusal_trials": sum(1 for st in stats_by_size[s] if st["refusal"]),
            "unparsed_vote_trials": sum(1 for st in stats_by_size[s] if st["unparsed"]),
            "best_of_n": round(mean([1 if st["any_correct"] else 0 for st in stats_by_size[s]]), 4),
        }
        for s in sizes
    }
    # Mistake overlap is read off the largest groups: every agent there answered
    # round 1 alone, and (in the nested design) they include every smaller group.
    largest = sizes[-1]
    overlap = error_overlap(
        [{"answers": st["round0"], "expected": st["expected"]} for st in stats_by_size[largest]]
        if largest >= 2 else []
    )
    p = overlap["solo_accuracy"]
    if p is None:  # no groups of 2+: fall back to size-1 accuracy
        p = mean(correct[sizes[0]]) if sizes[0] == 1 else None
    for s in sizes:
        extras[s]["independent_reference"] = (
            None if p is None else round(independent_vote_accuracy(p, s), 4)
        )
    results = summarize(sizes, correct, out_tokens, epsilon=epsilon, extras_by_size=extras)
    results["overlap"] = overlap
    # Independent voting only: debate groups change their answers after round 1,
    # so subsets of first-round answers say nothing about them.
    if topology == "independent" and largest >= 2:
        groups = [{"answers": st["round0"], "expected": st["expected"]} for st in stats_by_size[largest]]
        usable = [s for s in sizes if s <= min(len(g["answers"]) for g in groups)]
        balanced = seat_balanced(groups, usable)
        summary = summarize(usable, balanced["scores"], epsilon=epsilon)
        summary["seat_accuracy"] = balanced["seat_accuracy"]
        results["seat_balanced"] = summary
    return results


def run_grid(
    model,
    tasks,
    sizes: List[int],
    topology: str,
    master_seed: int,
    out_dir: str,
    model_label: str = "mock",
    workers: int = 1,
    resume: bool = False,
    extra_config: Optional[dict] = None,
    progress: bool = True,
) -> dict:
    out = Path(out_dir)
    trials_dir = out / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "nagents_version": __version__,
        "model": model_label,
        "topology": topology,
        "sizes": list(sizes),
        "trials": len(tasks),
        "master_seed": master_seed,
        "task_ids": [t.task_id for t in tasks],
        "config": dict(extra_config or {}, workers=workers),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    manifest_path = out / "manifest.json"
    has_cells = next(trials_dir.iterdir(), None) is not None
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _stable_view(existing) != _stable_view(manifest):
            raise SystemExit(
                f"{out_dir} holds a run with a different config. "
                "Use a fresh --out, or rerun with the original settings."
            )
        manifest = existing  # keep the original record, incl. started_at
    elif has_cells:
        raise SystemExit(
            f"{out_dir}/trials has files but no manifest.json — use a fresh --out."
        )
    if has_cells and not resume:
        raise SystemExit(
            f"{out_dir} already has trial transcripts. "
            "Pass --resume to continue that run, or use a fresh --out."
        )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    external = hasattr(model, "cell_pending")  # answers supplied from outside
    stats_by_size = {s: [] for s in sizes}
    reused = 0
    waiting = 0
    for t, task in enumerate(tasks):
        seed = f"{master_seed}:{t}"
        for size in sizes:
            path = trials_dir / _cell_name(t, size)
            if resume and path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["task_id"] != task.task_id:
                    raise SystemExit(
                        f"{path} is for task {record['task_id']}, expected {task.task_id}."
                    )
                reused += 1
            else:
                if external:
                    model.begin_cell()
                record = run_group(model, task, size, topology, seed, workers=workers)
                if external and model.cell_pending():
                    waiting += 1  # never write a cell with a missing answer
                    continue
                record["trial"] = t
                record["expected"] = task.answer
                record["correct"] = record["final_answer"] == task.answer
                path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            stats_by_size[size].append(_trial_stats(record))
        if progress:
            print(f"[nagents] trial {t + 1}/{len(tasks)} done", file=sys.stderr, flush=True)

    if reused and progress:
        total_cells = len(tasks) * len(sizes)
        print(
            f"[nagents] resumed: reused {reused}/{total_cells} transcripts",
            file=sys.stderr,
            flush=True,
        )
    if external:
        if waiting:
            path = model.write_pending()
            raise PendingAnswers(len(model.pending), waiting, path)
        model.clear_pending_file()
    results = _finalize(sizes, stats_by_size, topology=manifest.get("topology"))
    results["manifest"] = manifest
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def recompute(out_dir: str) -> dict:
    """Rebuild results.json purely from manifest + trial transcripts on disk."""
    out = Path(out_dir)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    sizes = manifest["sizes"]
    trials_dir = out / "trials"
    missing = []
    stats_by_size = {s: [] for s in sizes}
    for t in range(manifest["trials"]):
        for size in sizes:
            path = trials_dir / _cell_name(t, size)
            if not path.exists():
                missing.append(path.name)
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            stats_by_size[size].append(_trial_stats(record))
    if missing:
        preview = ", ".join(missing[:5])
        raise SystemExit(
            f"{len(missing)} trial transcript(s) missing (e.g. {preview}). "
            "The run is incomplete — finish it first (nagents run ... --resume)."
        )
    results = _finalize(sizes, stats_by_size, topology=manifest.get("topology"))
    results["manifest"] = manifest
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
