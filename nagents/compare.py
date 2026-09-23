"""Compare two finished runs size by size (phase 3: debate vs. independent;
phase 2: one depth vs. another).

When both runs used the same tasks, the difference is paired per trial and
gets a paired bootstrap CI. Otherwise each run's accuracy is shown with its
own CI and the difference is marked unpaired.
"""
import json
from pathlib import Path

from .report import cost_rows
from .stats import bootstrap_ci, mean, paired_diff_ci


def _load(run_dir):
    run = Path(run_dir)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    correct = {}
    for s in manifest["sizes"]:
        correct[s] = []
        for t in range(manifest["trials"]):
            path = run / "trials" / f"t{t:04d}-n{s:02d}.json"
            correct[s].append(1 if json.loads(path.read_text(encoding="utf-8"))["correct"] else 0)
    return manifest, results, correct


def _label(manifest) -> str:
    return f"{manifest.get('topology')} / {manifest.get('model')}"


def compare(run_a, run_b, chart: str = None) -> str:
    ma, ra, ca = _load(run_a)
    mb, rb, cb = _load(run_b)
    paired = ma["task_ids"] == mb["task_ids"]
    shared = [s for s in ma["sizes"] if s in mb["sizes"]]
    if not shared:
        raise SystemExit("The two runs share no group sizes.")
    tok_a = {c["size"]: c["tokens_per_question"] for c in cost_rows(ra)["per_size"]}
    tok_b = {c["size"]: c["tokens_per_question"] for c in cost_rows(rb)["per_size"]}

    lines = [
        f"A = {run_a}  ({_label(ma)})",
        f"B = {run_b}  ({_label(mb)})",
        "Paired by trial: same tasks in both runs." if paired
        else "Not paired: the runs used different tasks, so differences are unpaired.",
        "",
        "| size | A accuracy | B accuracy | B - A | 95% CI | A tokens/q | B tokens/q | A acc per 1k tok | B acc per 1k tok |",
        "|-----:|-----:|-----:|-----:|:-----:|-----:|-----:|-----:|-----:|",
    ]
    for s in shared:
        acc_a, acc_b = mean(ca[s]), mean(cb[s])
        if paired:
            lo, hi = paired_diff_ci(ca[s], cb[s], seed=f"cmp:{s}")
        else:
            a_lo, a_hi = bootstrap_ci(ca[s], seed=f"cmpa:{s}")
            b_lo, b_hi = bootstrap_ci(cb[s], seed=f"cmpb:{s}")
            lo, hi = b_lo - a_hi, b_hi - a_lo  # conservative interval
        ta, tb = tok_a.get(s), tok_b.get(s)

        def per_k(acc, tok):
            return f"{acc / tok * 1000:.3f}" if tok else "-"

        lines.append(
            f"| {s} | {acc_a:.3f} | {acc_b:.3f} | {acc_b - acc_a:+.3f} | [{lo:+.3f}, {hi:+.3f}] "
            f"| {ta if ta is not None else '-'} | {tb if tb is not None else '-'} "
            f"| {per_k(acc_a, ta)} | {per_k(acc_b, tb)} |"
        )
    if chart:
        from .charts import compare_svg

        Path(chart).write_text(
            compare_svg([(f"A: {_label(ma)}", ra), (f"B: {_label(mb)}", rb)]), encoding="utf-8"
        )
    lines.append("")
    for name, res in (("A", ra), ("B", rb)):
        sat = res.get("saturation_size_ci")
        lines.append(
            f"{name}: gains stop at {sat} agents (paired-CI rule)." if sat is not None
            else f"{name}: no stopping point in the measured range (paired-CI rule)."
        )
    return "\n".join(lines)
