"""Run the grid: same tasks, every group size, full transcripts on disk.

Trial t uses the same task and the same trial seed at every group size, so
size comparisons are paired and the paired bootstrap in stats.py is licensed.
"""
import json
import time
from pathlib import Path
from typing import List

from . import __version__
from .stats import summarize
from .topologies import run_group


def run_grid(
    model,
    tasks,
    sizes: List[int],
    topology: str,
    master_seed: int,
    out_dir: str,
    model_label: str = "mock",
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
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    correct_by_size = {s: [] for s in sizes}
    tokens_by_size = {s: [] for s in sizes}
    for t, task in enumerate(tasks):
        seed = f"{master_seed}:{t}"
        for size in sizes:
            record = run_group(model, task, size, topology, seed)
            record["trial"] = t
            record["expected"] = task.answer
            record["correct"] = record["final_answer"] == task.answer
            path = trials_dir / f"t{t:04d}-n{size:02d}.json"
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            correct_by_size[size].append(1 if record["correct"] else 0)
            tokens_by_size[size].append(record["usage"]["output_tokens"])

    results = summarize(sizes, correct_by_size, tokens_by_size)
    results["manifest"] = manifest
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
