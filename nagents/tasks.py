"""Task suites. Every task has one exact integer answer so scoring is mechanical.

All generators seed with strings (deterministic across processes; tuple seeds
would go through hash() and break reproducibility under hash randomization).
"""
import json
import random
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Task:
    task_id: str
    prompt: str
    answer: str  # canonical integer answer, as a string


ANSWER_INSTRUCTION = (
    "Work it out step by step. "
    "End with one final line in exactly this form: Answer: <number>"
)


def gen_arith(n: int, seed: int) -> List[Task]:
    """Two-product word problems. Ground truth a*b + c*d - e*f, always positive."""
    rng = random.Random(f"arith:{seed}")
    tasks = []
    for i in range(n):
        a, b, c, d = (rng.randint(4, 12) for _ in range(4))
        e, f = rng.randint(1, 4), rng.randint(1, 5)
        total = a * b + c * d - e * f
        prompt = (
            f"A warehouse holds {a} crates with {b} widgets in each crate. "
            f"It also holds {c} shelves with {d} widgets on each shelf. "
            f"Then {e} trucks each take away {f} widgets. "
            f"How many widgets are left in the warehouse? {ANSWER_INSTRUCTION}"
        )
        tasks.append(Task(f"arith-{seed}-{i}", prompt, str(total)))
    return tasks


def gen_chain(n: int, seed: int, depth: int = 8) -> List[Task]:
    """Chained mental arithmetic. Difficulty grows with depth."""
    rng = random.Random(f"chain:{seed}:{depth}")
    tasks = []
    for i in range(n):
        value = rng.randint(2, 9)
        steps = [f"Start with {value}."]
        for _ in range(depth):
            op = rng.choice(["add", "subtract", "multiply"])
            if abs(value) > 100000:
                op = rng.choice(["add", "subtract"])
            if op == "add":
                k = rng.randint(2, 99)
                value += k
                steps.append(f"Add {k}.")
            elif op == "subtract":
                k = rng.randint(2, 99)
                value -= k
                steps.append(f"Subtract {k}.")
            else:
                k = rng.randint(2, 9)
                value *= k
                steps.append(f"Multiply by {k}.")
        prompt = " ".join(steps) + f" What number do you have now? {ANSWER_INSTRUCTION}"
        tasks.append(Task(f"chain{depth}-{seed}-{i}", prompt, str(value)))
    return tasks


def gen_mult(n: int, seed: int, digits: int = 6) -> List[Task]:
    """Multiply two random `digits`-digit numbers. Difficulty grows with digits.

    Chained arithmetic turned out too easy for models that reason before
    answering (Haiku solved 50-step chains perfectly), so this suite gives a
    difficulty knob that keeps biting: long multiplication of big numbers.
    """
    if digits < 1:
        raise ValueError("digits must be at least 1")
    rng = random.Random(f"mult:{seed}:{digits}")
    lo, hi = 10 ** (digits - 1), 10 ** digits - 1
    tasks = []
    for i in range(n):
        a, b = rng.randint(lo, hi), rng.randint(lo, hi)
        prompt = f"What is {a} multiplied by {b}? {ANSWER_INSTRUCTION}"
        tasks.append(Task(f"mult{digits}-{seed}-{i}", prompt, str(a * b)))
    return tasks


def load_jsonl(path: str) -> List[Task]:
    """Load a custom suite: one JSON object per line with id, prompt, answer."""
    tasks = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            tasks.append(Task(str(obj["id"]), obj["prompt"], str(obj["answer"])))
    return tasks


def make_suite(
    name: str,
    trials: int,
    seed: int,
    depth: int = 8,
    path: Optional[str] = None,
    digits: int = 6,
) -> List[Task]:
    if name == "mult":
        return gen_mult(trials, seed, digits)
    if name == "arith":
        return gen_arith(trials, seed)
    if name == "chain":
        return gen_chain(trials, seed, depth)
    if name == "jsonl":
        if not path:
            raise ValueError("suite 'jsonl' needs --suite-path")
        return load_jsonl(path)[:trials]
    raise ValueError(f"unknown suite: {name}")
