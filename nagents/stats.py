"""Statistics: accuracy, bootstrap CIs, paired marginal gains, saturation."""
import random
from collections import Counter
from itertools import combinations
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


def independent_vote_accuracy(p: float, n: int) -> float:
    """Vote accuracy for n agents whose mistakes are independent and never match.

    Each agent is right with probability p. Wrong answers are all different, so
    the right answer wins with 2+ votes; with exactly one right vote every
    answer ties and the earliest agent's answer wins (probability 1/n that it is
    the right one). This is the best case for voting — the gap between it and
    the measured curve is what shared mistakes cost.
    """
    from math import comb

    total = 0.0
    for k in range(1, n + 1):
        weight = 1.0 if k >= 2 else 1.0 / n
        total += comb(n, k) * p ** k * (1 - p) ** (n - k) * weight
    return total


def error_overlap(groups: List[dict]) -> dict:
    """How often agents make the same mistake.

    `groups` holds one entry per trial cell with 2+ agents:
    {"answers": [round-1 answer per agent], "expected": "<truth>"}.
    Only first-round answers are used — they are given before anyone sees
    anyone else, so any overlap comes from the agents, not from the topology.

    Returns solo accuracy p, the error correlation (phi coefficient over every
    agent pair within a group: 0 = mistakes independent, 1 = always wrong
    together) and, among pairs that were both wrong, the share that gave the
    same wrong number.
    """
    answers = total_right = pairs = both_wrong = same_wrong = 0
    for group in groups:
        truth = str(group["expected"])
        wrong = [a != truth for a in group["answers"]]
        answers += len(wrong)
        total_right += sum(1 for w in wrong if not w)
        n = len(wrong)
        for i in range(n):
            for j in range(i + 1, n):
                pairs += 1
                if wrong[i] and wrong[j]:
                    both_wrong += 1
                    a, b = group["answers"][i], group["answers"][j]
                    if a and a == b:
                        same_wrong += 1
    if not answers or not pairs:
        return {"answers": answers, "pairs": pairs, "solo_accuracy": None,
                "error_correlation": None, "same_wrong_answer_rate": None}
    p = total_right / answers
    q = 1 - p
    corr = None
    if 0 < q < 1:
        corr = ((both_wrong / pairs) - q * q) / (q * (1 - q))
    return {
        "answers": answers,
        "pairs": pairs,
        "solo_accuracy": round(p, 4),
        "error_correlation": None if corr is None else round(corr, 4),
        "same_wrong_answer_rate": round(same_wrong / both_wrong, 4) if both_wrong else None,
    }


def _vote_credit(answers: List[str], truth: str) -> float:
    """Chance the right answer wins a plurality vote, ties broken at random."""
    counts = Counter(a for a in answers if a)
    if not counts:
        return 0.0
    top = max(counts.values())
    tied = [a for a, c in counts.items() if c == top]
    return 1.0 / len(tied) if truth in tied else 0.0


def seat_balanced(groups: List[dict], sizes: List[int], max_subsets: int = 300) -> dict:
    """Vote accuracy with every seat counted equally.

    `groups` holds one entry per trial: the first-round answers of the largest
    group and the truth. For each size n, every n-seat subset of those agents
    votes and the results are averaged, so no seat is the solo agent by
    accident of layout. Returns per-trial scores per size (floats in [0, 1])
    and each seat's own accuracy.
    """
    n_seats = min(len(g["answers"]) for g in groups)
    scores: Dict[int, List[float]] = {}
    for n in sizes:
        subsets = list(combinations(range(n_seats), n))
        if len(subsets) > max_subsets:
            subsets = random.Random(f"subsets:{n}").sample(subsets, max_subsets)
        scores[n] = [
            mean([_vote_credit([g["answers"][i] for i in sub], str(g["expected"])) for sub in subsets])
            for g in groups
        ]
    seat_accuracy = [
        round(mean([1.0 if g["answers"][i] == str(g["expected"]) else 0.0 for g in groups]), 4)
        for i in range(n_seats)
    ]
    return {"scores": scores, "seat_accuracy": seat_accuracy}
