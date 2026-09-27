"""Rebuild the README's real-data charts from the committed study runs in study/.

    python3 docs/make_study_charts.py

The voting chart uses the seat-balanced curve (every agent seat counted
equally; see "Seat check" in the report) because in these runs the first
problem of each subagent batch was solved more carefully than the rest.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nagents.charts import compare_svg  # noqa: E402
from nagents.stats import independent_vote_accuracy  # noqa: E402


def load(name):
    return json.loads((ROOT / "study" / name / "results.json").read_text(encoding="utf-8"))


def balanced(res):
    """The seat-balanced curve, with the independence reference for its solo accuracy."""
    rows = [dict(r) for r in res["seat_balanced"]["per_size"]]
    p = rows[0]["accuracy"]
    for r in rows:
        r["independent_reference"] = round(independent_vote_accuracy(p, r["size"]), 4)
    return {"per_size": rows, "manifest": res["manifest"]}


img = ROOT / "docs" / "img"
m7, m8 = load("main-m7"), load("main-m8")
(img / "study-voting.svg").write_text(compare_svg(
    [("7-digit multiplication", balanced(m7)), ("8-digit multiplication", balanced(m8))],
    "Claude Haiku: majority vote of 1 to 9 agents",
    "40 problems per size, every seat counted equally · shaded = 95% CI",
    references=True,
), encoding="utf-8")

debate = load("debate-m7")
sizes = {r["size"] for r in debate["per_size"]}
plain = {"per_size": [r for r in m7["per_size"] if r["size"] in sizes], "manifest": m7["manifest"]}
(img / "study-debate.svg").write_text(compare_svg(
    [("vote on first answers", plain), ("see the others' answers, revise, then vote", debate)],
    "Does talking it over beat voting? (7-digit multiplication)",
    "Same 40 problems and same first answers in both · shaded = 95% CI",
), encoding="utf-8")

# One agent alone, by problem size: how far each model gets before it slips.
def solo(names):
    rows = []
    for digits, name in names:
        first = load(name)["seat_balanced"]["per_size"][0]
        rows.append({"size": digits, "accuracy": first["accuracy"], "ci95": first["ci95"]})
    return {"per_size": rows, "manifest": {}}


haiku = solo([(5, "pilot-m5"), (7, "main-m7"), (8, "main-m8"), (9, "pilot-m9")])
sonnet_runs = [(8, "sonnet-pilot-m8"), (10, "sonnet-pilot-m10"), (12, "sonnet-pilot-m12"),
               (16, "sonnet-pilot-m16"), (20, "sonnet-m20")]
sonnet = solo(sonnet_runs)
# GPT-6 at low effort, reached through the local proxy (not the OpenAI API).
# Past 12 digits Sol often declines to answer; a skipped problem is scored wrong.
sol = solo([(8, "gpt6sol-pilot-m8"), (12, "gpt6sol-pilot-m12"), (13, "gpt6sol-m13"),
            (14, "gpt6sol-pilot-m14"), (16, "gpt6sol-pilot-m16")])
luna = solo([(8, "gpt6luna-m8"), (12, "gpt6luna-pilot-m12"), (16, "gpt6luna-pilot-m16")])
(img / "study-models.svg").write_text(compare_svg(
    [("Claude Haiku", haiku), ("Claude Sonnet", sonnet),
     ("GPT-6 Sol (low)", sol), ("GPT-6 Luna (low)", luna)],
    "One agent alone: how big a multiplication before it slips?",
    "Share of problems one agent got right (10 to 40 problems per point) · shaded = 95% CI",
    x_label="digits in each number being multiplied",
), encoding="utf-8")

s20 = load("sonnet-m20")
(img / "study-voting.svg").write_text(compare_svg(
    [("Haiku, 7 digits", balanced(m7)), ("Haiku, 8 digits", balanced(m8)),
     ("Sonnet, 20 digits", balanced(s20))],
    "Majority vote of 1 to 9 agents",
    "40 problems per size, every seat counted equally · shaded = 95% CI",
    references=True,
), encoding="utf-8")
print("wrote docs/img/study-voting.svg, study-debate.svg and study-models.svg")
