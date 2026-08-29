"""Statistics: accuracy, bootstrap CIs, paired marginal gains, saturation."""
import random
from typing import Dict, List, Optional


def mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(xs: List[float], iters: int = 2000, alpha: float = 0.05, seed: str = "ci"):
    """Percentile bootstrap CI for the mean. Deterministic for a fixed seed."""
    if not xs:
        return (0.0, 0.0)
    rng = random.Random(f"boot:{seed}")
    n = len(xs)
    means = []
    for _ in range(iters):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(mean(sample))
    means.sort()
    lo = means[int((alpha / 2) * iters)]
    hi = means[min(iters - 1, int((1 - alpha / 2) * iters))]
    return (lo, hi)


def paired_diff_ci(a: List[float], b: List[float], iters: int = 2000, alpha: float = 0.05, seed: str = "diff"):
    """CI for mean(b - a), paired by trial. a and b must be trial-aligned."""
    diffs = [bi - ai for ai, bi in zip(a, b)]
    return bootstrap_ci(diffs, iters=iters, alpha=alpha, seed=seed)


def find_saturation(sizes: List[int], accuracies: List[float], epsilon: float = 0.01) -> Optional[int]:
    """Point-estimate rule: smallest size after which no larger measured size
    gains more than epsilon.

    Returns None when the curve is still climbing at the largest measured size.
    """
    for i, s in enumerate(sizes):
        if all(accuracies[j] - accuracies[i] <= epsilon for j in range(i + 1, len(sizes))):
            still_climbing = (
                i == len(sizes) - 1
                and len(sizes) > 1
                and accuracies[-1] - accuracies[-2] > epsilon
            )
            return None if still_climbing else s
    return None


def find_saturation_ci(sizes: List[int], correct_by_size: Dict[int, List[int]], epsilon: float = 0.01) -> Optional[int]:
    """Paired-CI rule: smallest size s where, for every larger measured size,
    the upper bound of the paired 95% CI on the gain over s is <= epsilon.

    Stricter than the point rule: it only calls saturation when the data rules
    out a meaningful hidden gain. Returns None when no size below the largest
    qualifies (the curve may still be climbing).
    """
    for i, s in enumerate(sizes):
        if i == len(sizes) - 1 and len(sizes) > 1:
            return None
        ok = True
        for j in range(i + 1, len(sizes)):
            _, hi = paired_diff_ci(
                correct_by_size[s], correct_by_size[sizes[j]], seed=f"sat:{s}:{sizes[j]}"
            )
            if hi > epsilon:
                ok = False
                break
        if ok:
            return s
    return None


def summarize(
    sizes: List[int],
    correct_by_size: Dict[int, List[int]],
    tokens_by_size: Optional[Dict[int, List[int]]] = None,
    epsilon: float = 0.01,
    extras_by_size: Optional[Dict[int, dict]] = None,
) -> dict:
    per_size = []
    for s in sizes:
        xs = correct_by_size[s]
        lo, hi = bootstrap_ci(xs, seed=f"acc:{s}")
        row = {
            "size": s,
            "trials": len(xs),
            "accuracy": round(mean(xs), 4),
            "ci95": [round(lo, 4), round(hi, 4)],
        }
        if tokens_by_size:
            row["mean_output_tokens"] = round(mean(tokens_by_size[s]), 1)
        if extras_by_size:
            row.update(extras_by_size[s])
        per_size.append(row)

    gains = []
    for prev, cur in zip(sizes, sizes[1:]):
        lo, hi = paired_diff_ci(
            correct_by_size[prev], correct_by_size[cur], seed=f"gain:{prev}:{cur}"
        )
        gains.append(
            {
                "from_size": prev,
                "to_size": cur,
                "gain": round(mean(correct_by_size[cur]) - mean(correct_by_size[prev]), 4),
                "ci95": [round(lo, 4), round(hi, 4)],
            }
        )

    accs = [mean(correct_by_size[s]) for s in sizes]
    return {
        "per_size": per_size,
        "gains": gains,
        "saturation_size": find_saturation(sizes, accs, epsilon),
        "saturation_size_ci": find_saturation_ci(sizes, correct_by_size, epsilon),
        "epsilon": epsilon,
    }
