"""Group topologies: how N agents work the same task.

Calls within a round are independent, so `workers > 1` runs them through a
thread pool. Bookkeeping (usage, transcripts) happens on the main thread in
agent order, so transcripts and results are identical at any worker count.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import List

from .scoring import extract_answer

SYSTEM = (
    "You are a careful problem solver. Show your working briefly. "
    "Always end with one final line in exactly this form: Answer: <number>"
)

TOPOLOGIES = ("independent", "debate")


def _majority(answers: List[str]) -> str:
    """Most common answer. Ties break to the answer that appeared first."""
    counts = Counter(answers)
    return max(counts, key=lambda a: (counts[a], -answers.index(a)))


def _final_vote(answers: List[str]) -> str:
    """Majority over parseable answers only — an empty answer never outvotes
    a real one. Returns "" when nothing parsed."""
    valid = [a for a in answers if a]
    return _majority(valid) if valid else ""


def run_group(model, task, size: int, topology: str, seed: str, workers: int = 1) -> dict:
    """Run one task through a group of `size` agents. Returns a full transcript."""
    if topology not in TOPOLOGIES:
        raise ValueError(f"unknown topology: {topology}")

    agents = [{"agent": i, "rounds": []} for i in range(size)]
    usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def complete_round(round_no: int, prompts: List[str], majority_correct=None) -> None:
        def call(i: int):
            meta = {
                "task_id": task.task_id,
                "answer": task.answer,
                "seed": seed,
                "agent": i,
                "round": round_no,
                "majority_correct": majority_correct,
            }
            return model.complete(SYSTEM, prompts[i], meta)

        if workers > 1 and size > 1:
            with ThreadPoolExecutor(max_workers=min(workers, size)) as pool:
                replies = list(pool.map(call, range(size)))
        else:
            replies = [call(i) for i in range(size)]

        for i, reply in enumerate(replies):
            usage["input_tokens"] += reply.input_tokens
            usage["output_tokens"] += reply.output_tokens
            usage["calls"] += 1
            agents[i]["rounds"].append(
                {
                    "round": round_no,
                    "prompt": prompts[i],
                    "reply": reply.text,
                    "answer": extract_answer(reply.text),
                    "stop_reason": reply.stop_reason,
                }
            )

    # Round 0: everyone answers alone.
    complete_round(0, [task.prompt] * size)
    round0 = [agent["rounds"][0]["answer"] for agent in agents]

    if topology == "debate" and size > 1:
        majority_correct = _final_vote(round0) == task.answer  # mock plumbing only
        prompts = []
        for i in range(size):
            others = [a for j, a in enumerate(round0) if j != i]
            prompts.append(
                task.prompt
                + "\n\nOther solvers answered the same problem independently. "
                + "Their answers: "
                + ", ".join(a if a else "(no answer)" for a in others)
                + ". Check your own work against theirs, then give your final answer. "
                + "End with one final line in exactly this form: Answer: <number>"
            )
        complete_round(1, prompts, majority_correct=majority_correct)
        final_answers = [agent["rounds"][1]["answer"] for agent in agents]
    else:
        final_answers = round0

    return {
        "task_id": task.task_id,
        "size": size,
        "topology": topology,
        "seed": seed,
        "agents": agents,
        "votes": final_answers,
        "final_answer": _final_vote(final_answers),
        "usage": usage,
    }
