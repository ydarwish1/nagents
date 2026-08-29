"""Group topologies: how N agents work the same task."""
from collections import Counter
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


def run_group(model, task, size: int, topology: str, seed: str) -> dict:
    """Run one task through a group of `size` agents. Returns a full transcript."""
    if topology not in TOPOLOGIES:
        raise ValueError(f"unknown topology: {topology}")

    agents = [{"agent": i, "rounds": []} for i in range(size)]
    usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def ask(agent: int, rnd: int, prompt: str, majority_correct=None) -> None:
        meta = {
            "task_id": task.task_id,
            "answer": task.answer,
            "seed": seed,
            "agent": agent,
            "round": rnd,
            "majority_correct": majority_correct,
        }
        reply = model.complete(SYSTEM, prompt, meta)
        usage["input_tokens"] += reply.input_tokens
        usage["output_tokens"] += reply.output_tokens
        usage["calls"] += 1
        agents[agent]["rounds"].append(
            {
                "round": rnd,
                "prompt": prompt,
                "reply": reply.text,
                "answer": extract_answer(reply.text),
                "stop_reason": reply.stop_reason,
            }
        )

    # Round 0: everyone answers alone.
    for i in range(size):
        ask(i, 0, task.prompt)
    round0 = [agent["rounds"][0]["answer"] for agent in agents]

    if topology == "debate" and size > 1:
        majority_correct = _majority(round0) == task.answer  # mock plumbing only
        for i in range(size):
            others = [a for j, a in enumerate(round0) if j != i]
            prompt = (
                task.prompt
                + "\n\nOther solvers answered the same problem independently. "
                + "Their answers: "
                + ", ".join(a if a else "(no answer)" for a in others)
                + ". Check your own work against theirs, then give your final answer. "
                + "End with one final line in exactly this form: Answer: <number>"
            )
            ask(i, 1, prompt, majority_correct=majority_correct)
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
        "final_answer": _majority(final_answers),
        "usage": usage,
    }
