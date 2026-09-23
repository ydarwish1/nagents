"""report.html: the run's charts, tables, and a link from every cell to its transcript.

Phase 4's bar is "a reader can click from any claim to the transcript behind
it". Every accuracy number is a count over trial cells, so the page ends with
the full trial x size grid, each cell linking to its JSON transcript.
"""
import json
from html import escape
from pathlib import Path

from .charts import accuracy_svg, cost_svg
from .report import cost_rows

CSS = """
:root { color-scheme: light; --ink:#1f2328; --muted:#6b7280; --line:#e5e7eb; --ok:#16a34a; --bad:#dc2626; }
* { box-sizing: border-box; }
body { margin:0; background:#fff; color:var(--ink); font:15px/1.5 -apple-system, Segoe UI, Helvetica, Arial, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 36px 0 8px; }
.meta { color: var(--muted); margin: 0 0 20px; }
.lead { font-size: 17px; }
svg { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: right; }
th:first-child, td:first-child { text-align: left; }
.scroll { overflow-x: auto; }
.grid td { text-align: center; padding: 2px 4px; }
.grid a { text-decoration: none; font-weight: 600; }
.ok { color: var(--ok); } .bad { color: var(--bad); }
"""


def _pct(x):
    return "–" if x is None else f"{x * 100:.1f}%"


def _headline(results: dict) -> str:
    rows = results["per_size"]
    first, last = rows[0], rows[-1]
    sat = results.get("saturation_size_ci")
    sat_point = results.get("saturation_size")
    text = (
        f"One agent was right {_pct(first['accuracy'])} of the time; "
        f"a group of {last['size']} voting was right {_pct(last['accuracy'])}. "
    )
    if sat is not None:
        text += f"The data rules out any real gain beyond {sat} agents."
    elif sat_point is not None:
        text += (
            f"The measured curve stops rising at {sat_point} agents, but there are not yet "
            "enough trials to rule out a small hidden gain."
        )
    else:
        text += "Accuracy was still rising at the largest group measured."
    return text


def render_html(results: dict, run_dir) -> str:
    run = Path(run_dir)
    m = results.get("manifest", {})
    rows = results["per_size"]
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width, initial-scale=1">',
        f"<title>nagents run report</title><style>{CSS}</style></head><body><main>",
        "<h1>Do more agents actually help?</h1>",
        f'<p class=meta>model {escape(str(m.get("model")))} · topology {escape(str(m.get("topology")))} '
        f'· {m.get("trials")} trials per size · seed {m.get("master_seed")} · nagents {escape(str(m.get("nagents_version")))}</p>',
        f"<p class=lead>{escape(_headline(results))}</p>",
        accuracy_svg(results),
    ]
    cost = cost_svg(results)
    if cost:
        parts.append("<h2>What it costs</h2>")
        parts.append(cost)

    parts.append("<h2>Numbers</h2><div class=scroll><table>")
    parts.append(
        "<tr><th>agents</th><th>accuracy</th><th>95% CI</th><th>if mistakes were independent</th>"
        "<th>someone was right</th><th>tokens / question</th></tr>"
    )
    costs = {c["size"]: c for c in cost_rows(results)["per_size"]}
    for r in rows:
        c = costs.get(r["size"], {})
        parts.append(
            f"<tr><td>{r['size']}</td><td>{_pct(r['accuracy'])}</td>"
            f"<td>{_pct(r['ci95'][0])} – {_pct(r['ci95'][1])}</td>"
            f"<td>{_pct(r.get('independent_reference'))}</td><td>{_pct(r.get('best_of_n'))}</td>"
            f"<td>{c.get('tokens_per_question', '–')}</td></tr>"
        )
    parts.append("</table></div>")

    overlap = results.get("overlap") or {}
    if overlap.get("solo_accuracy") is not None:
        corr = overlap.get("error_correlation")
        parts.append(
            "<h2>Shared mistakes</h2><p>"
            f"Across {overlap['pairs']} pairs of agents answering the same problem alone, "
            f"the error correlation was <b>{'–' if corr is None else f'{corr:+.2f}'}</b> "
            "(0 means mistakes are independent, 1 means agents are always wrong together). "
            f"When two agents were both wrong, they gave the same wrong number "
            f"<b>{_pct(overlap.get('same_wrong_answer_rate'))}</b> of the time. "
            "Voting only helps when mistakes don't line up.</p>"
        )

    parts.append(
        "<h2>Every trial</h2><p class=meta>Each cell is one task answered by one group. "
        "✓ = the vote was right. Click a cell for the full transcript.</p>"
    )
    sizes = [r["size"] for r in rows]
    parts.append("<div class=scroll><table class=grid><tr><th>trial</th>")
    parts.extend(f"<th>{s}</th>" for s in sizes)
    parts.append("</tr>")
    for t in range(m.get("trials", 0)):
        parts.append(f"<tr><td>{t}</td>")
        for s in sizes:
            name = f"t{t:04d}-n{s:02d}.json"
            path = run / "trials" / name
            if path.exists():
                ok = json.loads(path.read_text(encoding="utf-8")).get("correct")
                mark, cls = ("✓", "ok") if ok else ("✗", "bad")
                parts.append(f'<td><a class={cls} href="trials/{name}">{mark}</a></td>')
            else:
                parts.append("<td>·</td>")
        parts.append("</tr>")
    parts.append("</table></div></main></body></html>")
    return "\n".join(parts)


def write_html(results: dict, run_dir) -> Path:
    path = Path(run_dir) / "report.html"
    path.write_text(render_html(results, run_dir), encoding="utf-8")
    return path
