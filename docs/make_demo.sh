#!/usr/bin/env bash
# Rebuild the README's demo charts from the free mock model (no API, no subagents).
# Two runs with the same per-agent skill; only how often agents share a mistake differs.
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d)
common="--mock --suite chain --depth 8 --trials 200 --sizes 1,2,3,4,5,7,9 --seed 7"
python3 -m nagents run $common --out "$out/independent" >/dev/null 2>&1
python3 -m nagents run $common --mock-correlation 0.6 --out "$out/shared" >/dev/null 2>&1
python3 - "$out" <<'PY'
import json, sys
from pathlib import Path
from nagents.charts import compare_svg, cost_svg
out = Path(sys.argv[1])
a = json.loads((out / "independent/results.json").read_text())
b = json.loads((out / "shared/results.json").read_text())
img = Path("docs/img")
img.mkdir(parents=True, exist_ok=True)
(img / "demo-overlap.svg").write_text(compare_svg(
    [("mistakes independent", a), ("mistakes shared (correlation 0.6)", b)],
    "Same skill per agent. Only how often they share a mistake differs."))
(img / "demo-cost.svg").write_text(cost_svg(b))
PY
echo "demo runs in $out; charts in docs/img/"
