"""Turn results.json into a small human-readable report."""

# Anthropic first-party rates, (input, output) $ per MTok. Cached 2026-08;
# re-check before quoting costs anywhere that matters.
PRICING_PER_MTOK = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _saturation_line(label: str, value, eps) -> str:
    if value is None:
        return f"Saturation ({label}): not reached in the measured range (epsilon={eps})."
    return f"Saturation ({label}): gains stop at size {value} (epsilon={eps})."


def cost_rows(results: dict) -> dict:
    """Cost per question per size, and what each +1 accuracy point costs.

    Tokens are always reported; dollars only when the model has a known price.
    "Per question" is per trial: one task answered by one whole group.
    """
    rows = results["per_size"]
    manifest = results.get("manifest", {})
    rates = PRICING_PER_MTOK.get(manifest.get("model"))
    if not all("input_tokens_total" in row for row in rows):
        return {"per_size": [], "steps": [], "priced": False}
    per_size = []
    for row in rows:
        n = row["trials"] or 1
        tokens = (row["input_tokens_total"] + row["output_tokens_total"]) / n
        dollars = None
        if rates:
            dollars = (row["input_tokens_total"] * rates[0] + row["output_tokens_total"] * rates[1]) / 1e6 / n
        per_size.append(
            {
                "size": row["size"],
                "accuracy": row["accuracy"],
                "tokens_per_question": round(tokens, 1),
                "dollars_per_question": None if dollars is None else round(dollars, 6),
                "tokens_per_correct": round(tokens / row["accuracy"], 1) if row["accuracy"] else None,
            }
        )
    steps = []
    for prev, cur, gain in zip(per_size, per_size[1:], results["gains"]):
        extra_tokens = cur["tokens_per_question"] - prev["tokens_per_question"]
        points = gain["gain"] * 100
        step = {
            "from_size": prev["size"],
            "to_size": cur["size"],
            "gain_points": round(points, 2),
            "extra_tokens_per_question": round(extra_tokens, 1),
            "tokens_per_point": round(extra_tokens / points, 1) if points > 0 else None,
            "dollars_per_point": None,
        }
        if rates and points > 0:
            extra_dollars = cur["dollars_per_question"] - prev["dollars_per_question"]
            step["dollars_per_point"] = round(extra_dollars / points, 6)
        steps.append(step)
    return {"per_size": per_size, "steps": steps, "priced": bool(rates)}


def _fmt_pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def render(results: dict) -> str:
    lines = []
    manifest = results.get("manifest", {})
    if manifest:
        lines.append(
            f"model={manifest.get('model')}  topology={manifest.get('topology')}  "
            f"trials={manifest.get('trials')}  seed={manifest.get('master_seed')}"
        )
        lines.append("")

    has_ref = any(row.get("independent_reference") is not None for row in results["per_size"])
    if has_ref:
        lines.append(
            "| size | accuracy | 95% CI | if mistakes were independent | best-of-N ceiling "
            "| mean output tokens |"
        )
        lines.append("|-----:|---------:|:------:|:---:|:---:|-------------------:|")
    else:
        lines.append("| size | accuracy | 95% CI | mean output tokens |")
        lines.append("|-----:|---------:|:------:|-------------------:|")
    for row in results["per_size"]:
        ci = row["ci95"]
        tokens = row.get("mean_output_tokens", "-")
        mid = ""
        if has_ref:
            ref = row.get("independent_reference")
            mid = f" {'-' if ref is None else f'{ref:.3f}'} | {row.get('best_of_n', 0):.3f} |"
        lines.append(
            f"| {row['size']} | {row['accuracy']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] |{mid} {tokens} |"
        )

    lines.append("")
    lines.append("| step | gain | 95% CI (paired) |")
    lines.append("|:----:|-----:|:---------------:|")
    for g in results["gains"]:
        ci = g["ci95"]
        lines.append(
            f"| {g['from_size']} -> {g['to_size']} | {g['gain']:+.3f} "
            f"| [{ci[0]:+.3f}, {ci[1]:+.3f}] |"
        )

    lines.append("")
    eps = results.get("epsilon")
    lines.append(_saturation_line("point rule", results.get("saturation_size"), eps))
    lines.append(_saturation_line("paired-CI rule", results.get("saturation_size_ci"), eps))

    rows = results["per_size"]
    if any("refusal_trials" in row for row in rows):
        flagged = [
            row for row in rows
            if row.get("refusal_trials") or row.get("unparsed_vote_trials")
        ]
        if flagged:
            for row in flagged:
                lines.append(
                    f"Data quality: size {row['size']}: {row['refusal_trials']} refusal "
                    f"trial(s), {row['unparsed_vote_trials']} trial(s) with unparsed votes."
                )
        else:
            lines.append("Data quality: no refusals, every vote parsed.")

    overlap = results.get("overlap") or {}
    if overlap.get("solo_accuracy") is not None:
        corr = overlap.get("error_correlation")
        same = overlap.get("same_wrong_answer_rate")
        lines.append("")
        lines.append(
            f"Shared mistakes (first answers, {overlap['pairs']} agent pairs): "
            f"solo accuracy {overlap['solo_accuracy']:.3f}, "
            f"error correlation {'-' if corr is None else f'{corr:+.2f}'} "
            "(0 = independent, 1 = always wrong together), "
            f"same wrong number when both wrong: {_fmt_pct(same)}."
        )

    costs = cost_rows(results)
    if costs["steps"]:
        unit = "$" if costs["priced"] else "tokens"
        lines.append("")
        lines.append(f"| step | gain (points) | extra tokens / question | {unit} per +1 point |")
        lines.append("|:----:|-----:|-----:|-----:|")
        for step in costs["steps"]:
            per_point = step["dollars_per_point"] if costs["priced"] else step["tokens_per_point"]
            if per_point is None:
                shown = "no gain"
            elif costs["priced"]:
                shown = f"${per_point:.4f}"
            else:
                shown = f"{per_point:.0f}"
            lines.append(
                f"| {step['from_size']} -> {step['to_size']} | {step['gain_points']:+.1f} "
                f"| {step['extra_tokens_per_question']:+.0f} | {shown} |"
            )

    rates = PRICING_PER_MTOK.get(manifest.get("model"))
    if rates and all("input_tokens_total" in row for row in rows):
        total = sum(
            (row["input_tokens_total"] * rates[0] + row["output_tokens_total"] * rates[1])
            / 1e6
            for row in rows
        )
        lines.append(
            f"Estimated API cost: ${total:.2f} "
            f"(${rates[0]:.0f}/MTok in, ${rates[1]:.0f}/MTok out)."
        )

    return "\n".join(lines)
