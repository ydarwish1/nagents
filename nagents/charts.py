"""Dependency-free SVG charts for a finished run.

Two charts, written next to results.json under charts/:
- accuracy.svg — accuracy vs. group size with its 95% CI band, the
  "if mistakes were independent" reference, and the best-of-N ceiling.
- cost.svg — accuracy vs. tokens spent per question, one point per size.
"""
from pathlib import Path
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

from .report import cost_rows

W, H = 640, 420
PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 48, 78

INK = "#1f2328"
MUTED = "#6b7280"
GRID = "#e5e7eb"
MEASURED = "#2563eb"
BAND = "#bfdbfe"
REFERENCE = "#9ca3af"
CEILING = "#16a34a"
BALANCED = "#f59e0b"


def _scale(v, lo, hi, a, b):
    return a if hi == lo else a + (v - lo) * (b - a) / (hi - lo)


def _polyline(points: List[Tuple[float, float]], color: str, dash: Optional[str] = None, width=2.5):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"'
        f' stroke-linejoin="round" stroke-linecap="round"{extra}/>'
    )


def _nice_step(raw: float) -> float:
    """Round a tick step up to 1, 2 or 5 times a power of ten."""
    import math

    power = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * power:
            return m * power
    return 10 * power


def _frame(title: str, subtitle: str) -> List[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{PAD_L}" y="22" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="{PAD_L}" y="39" font-size="11.5" fill="{MUTED}">{escape(subtitle)}</text>',
    ]


def _y_axis(parts: List[str]) -> None:
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        y = _scale(tick, 0, 1, H - PAD_B, PAD_T)
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
        parts.append(
            f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end">{int(tick * 100)}%</text>'
        )
    parts.append(
        f'<text x="16" y="{(H - PAD_B + PAD_T) / 2:.0f}" font-size="11.5" fill="{MUTED}" '
        f'transform="rotate(-90 16 {(H - PAD_B + PAD_T) / 2:.0f})" text-anchor="middle">accuracy</text>'
    )


def _legend(parts: List[str], items: List[Tuple[str, str, Optional[str]]]) -> None:
    widths = [40 + 6.4 * len(label) for label, _, _ in items]
    rows: List[List[int]] = [[]]
    used = 0.0
    for i, w in enumerate(widths):
        if rows[-1] and PAD_L + used + w > W - 8:
            rows.append([])
            used = 0.0
        rows[-1].append(i)
        used += w
    ys = [H - 14] if len(rows) == 1 else [H - 26 + 18 * r for r in range(len(rows))]
    for row, y in zip(rows, ys):
        x = PAD_L
        for i in row:
            label, color, dash = items[i]
            extra = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(
                f'<line x1="{x}" x2="{x + 22}" y1="{y - 4}" y2="{y - 4}" stroke="{color}" '
                f'stroke-width="2.5"{extra}/>'
            )
            parts.append(f'<text x="{x + 28}" y="{y}" font-size="11.5" fill="{INK}">{escape(label)}</text>')
            x += widths[i]


def _subtitle(results: dict) -> str:
    m = results.get("manifest", {})
    return f"model {m.get('model')} · topology {m.get('topology')} · {m.get('trials')} trials per size"


def accuracy_svg(results: dict) -> str:
    rows = results["per_size"]
    sizes = [r["size"] for r in rows]
    x_lo, x_hi = min(sizes), max(sizes)
    if x_lo == x_hi:
        x_lo, x_hi = x_lo - 1, x_hi + 1

    def X(s):
        return _scale(s, x_lo, x_hi, PAD_L + 16, W - PAD_R - 16)

    def Y(v):
        return _scale(v, 0, 1, H - PAD_B, PAD_T)

    parts = _frame("Does adding agents help?", _subtitle(results))
    _y_axis(parts)
    for s in sizes:
        parts.append(
            f'<text x="{X(s):.1f}" y="{H - PAD_B + 18}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{s}</text>'
        )
    parts.append(
        f'<text x="{(PAD_L + W - PAD_R) / 2:.0f}" y="{H - PAD_B + 34}" font-size="11.5" '
        f'fill="{MUTED}" text-anchor="middle">agents in the group</text>'
    )

    upper = [(X(r["size"]), Y(r["ci95"][1])) for r in rows]
    lower = [(X(r["size"]), Y(r["ci95"][0])) for r in reversed(rows)]
    band = " ".join(f"{x:.1f},{y:.1f}" for x, y in upper + lower)
    parts.append(f'<polygon points="{band}" fill="{BAND}" opacity="0.7"/>')

    legend = [("measured (95% CI)", MEASURED, None)]
    if all(r.get("independent_reference") is not None for r in rows):
        parts.append(_polyline([(X(r["size"]), Y(r["independent_reference"])) for r in rows], REFERENCE, "6 5"))
        legend.append(("if mistakes were independent", REFERENCE, "6 5"))
    if all("best_of_n" in r for r in rows):
        parts.append(_polyline([(X(r["size"]), Y(r["best_of_n"])) for r in rows], CEILING, "2 4", width=2))
        legend.append(("someone was right", CEILING, "2 4"))

    balanced = (results.get("seat_balanced") or {}).get("per_size")
    if balanced:
        parts.append(_polyline([(X(r["size"]), Y(r["accuracy"])) for r in balanced], BALANCED, width=2))
        legend.append(("every seat counted equally", BALANCED, None))

    parts.append(_polyline([(X(r["size"]), Y(r["accuracy"])) for r in rows], MEASURED))
    for r in rows:
        parts.append(f'<circle cx="{X(r["size"]):.1f}" cy="{Y(r["accuracy"]):.1f}" r="4" fill="{MEASURED}"/>')

    sat = results.get("saturation_size_ci") or results.get("saturation_size")
    if sat is not None:
        parts.append(
            f'<line x1="{X(sat):.1f}" x2="{X(sat):.1f}" y1="{PAD_T}" y2="{H - PAD_B}" '
            f'stroke="{INK}" stroke-dasharray="3 3" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{X(sat) + 5:.1f}" y="{H - PAD_B - 8}" font-size="11" fill="{INK}">'
            f"gains stop at {sat}</text>"
        )
    _legend(parts, legend)
    parts.append("</svg>")
    return "\n".join(parts)


def cost_svg(results: dict) -> Optional[str]:
    costs = cost_rows(results)["per_size"]
    if not costs:
        return None
    xs = [c["tokens_per_question"] for c in costs]
    step = _nice_step(max(xs) / 4 or 1)
    x_hi = step * max(1, -(-max(xs) * 1.05 // step))

    def X(v):
        return _scale(v, 0, x_hi, PAD_L + 8, W - PAD_R - 8)

    def Y(v):
        return _scale(v, 0, 1, H - PAD_B, PAD_T)

    parts = _frame("What each extra point of accuracy costs", _subtitle(results))
    _y_axis(parts)
    for i in range(int(round(x_hi / step)) + 1):
        v = step * i
        parts.append(
            f'<text x="{X(v):.1f}" y="{H - PAD_B + 18}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{v:,.0f}</text>'
        )
    parts.append(
        f'<text x="{(PAD_L + W - PAD_R) / 2:.0f}" y="{H - PAD_B + 34}" font-size="11.5" '
        f'fill="{MUTED}" text-anchor="middle">tokens spent per question (whole group)</text>'
    )
    parts.append(_polyline([(X(c["tokens_per_question"]), Y(c["accuracy"])) for c in costs], MEASURED))
    for c in costs:
        x, y = X(c["tokens_per_question"]), Y(c["accuracy"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{MEASURED}"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{y - 9:.1f}" font-size="11" fill="{INK}" '
            f'text-anchor="middle">{c["size"]}</text>'
        )
    _legend(parts, [("one point per group size, labeled by agents", MEASURED, None)])
    parts.append("</svg>")
    return "\n".join(parts)


SERIES = ["#2563eb", "#ea580c", "#7c3aed", "#0891b2"]


def compare_svg(
    runs: List[Tuple[str, dict]],
    title: str = "Accuracy by group size",
    subtitle: Optional[str] = None,
    references: bool = False,
    x_label: str = "agents in the group",
) -> str:
    """Several runs' accuracy curves on one chart (e.g. debate vs. independent).

    With `references`, each run's "if mistakes were independent" curve is drawn
    dashed in the run's colour, where the rows carry it.
    """
    sizes = sorted({r["size"] for _, res in runs for r in res["per_size"]})
    x_lo, x_hi = min(sizes), max(sizes)
    if x_lo == x_hi:
        x_lo, x_hi = x_lo - 1, x_hi + 1

    def X(s):
        return _scale(s, x_lo, x_hi, PAD_L + 16, W - PAD_R - 16)

    def Y(v):
        return _scale(v, 0, 1, H - PAD_B, PAD_T)

    trials = {res.get("manifest", {}).get("trials") for _, res in runs}
    if subtitle is None:
        subtitle = f"{'/'.join(str(t) for t in sorted(trials, key=str))} trials per size · shaded = 95% CI"
    parts = _frame(title, subtitle)
    _y_axis(parts)
    for s in sizes:
        parts.append(
            f'<text x="{X(s):.1f}" y="{H - PAD_B + 18}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{s}</text>'
        )
    parts.append(
        f'<text x="{(PAD_L + W - PAD_R) / 2:.0f}" y="{H - PAD_B + 34}" font-size="11.5" '
        f'fill="{MUTED}" text-anchor="middle">{x_label}</text>'
    )
    legend = []
    for i, (label, res) in enumerate(runs):
        color = SERIES[i % len(SERIES)]
        rows = res["per_size"]
        upper = [(X(r["size"]), Y(r["ci95"][1])) for r in rows]
        lower = [(X(r["size"]), Y(r["ci95"][0])) for r in reversed(rows)]
        band = " ".join(f"{x:.1f},{y:.1f}" for x, y in upper + lower)
        parts.append(f'<polygon points="{band}" fill="{color}" opacity="0.12"/>')
        parts.append(_polyline([(X(r["size"]), Y(r["accuracy"])) for r in rows], color))
        for r in rows:
            parts.append(f'<circle cx="{X(r["size"]):.1f}" cy="{Y(r["accuracy"]):.1f}" r="4" fill="{color}"/>')
        legend.append((label, color, None))
        if references and all(r.get("independent_reference") is not None for r in rows):
            parts.append(_polyline([(X(r["size"]), Y(r["independent_reference"])) for r in rows], color, "6 5", width=1.5))
    if references:
        legend.append(("dashed: if mistakes were independent", REFERENCE, "6 5"))
    _legend(parts, legend)
    parts.append("</svg>")
    return "\n".join(parts)


def write_charts(results: dict, run_dir) -> List[Path]:
    out = Path(run_dir) / "charts"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    path = out / "accuracy.svg"
    path.write_text(accuracy_svg(results), encoding="utf-8")
    written.append(path)
    cost = cost_svg(results)
    if cost:
        path = out / "cost.svg"
        path.write_text(cost, encoding="utf-8")
        written.append(path)
    return written
