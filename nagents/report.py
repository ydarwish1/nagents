"""Turn results.json into a small human-readable report."""


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
    sat = results.get("saturation_size")
    eps = results.get("epsilon")
    if sat is None:
        lines.append(f"Saturation: not reached in the measured range (epsilon={eps}).")
    else:
        lines.append(f"Saturation: gains stop at size {sat} (epsilon={eps}).")
    return "\n".join(lines)
