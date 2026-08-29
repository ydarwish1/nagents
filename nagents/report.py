"""Turn results.json into a small human-readable report."""

# Anthropic first-party rates, (input, output) $ per MTok. Cached 2026-08;
# re-check before quoting costs anywhere that matters.
PRICING_PER_MTOK = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _saturation_line(label: str, value, eps) -> str:
    if value is None:
        return f"Saturation ({label}): not reached in the measured range (epsilon={eps})."
    return f"Saturation ({label}): gains stop at size {value} (epsilon={eps})."


def render(results: dict) -> str:
    lines = []
    manifest = results.get("manifest", {})
    if manifest:
        lines.append(
            f"model={manifest.get('model')}  topology={manifest.get('topology')}  "
            f"trials={manifest.get('trials')}  seed={manifest.get('master_seed')}"
        )
        lines.append("")

    lines.append("| size | accuracy | 95% CI | mean output tokens |")
    lines.append("|-----:|---------:|:------:|-------------------:|")
    for row in results["per_size"]:
        ci = row["ci95"]
        tokens = row.get("mean_output_tokens", "-")
        lines.append(
            f"| {row['size']} | {row['accuracy']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] | {tokens} |"
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
