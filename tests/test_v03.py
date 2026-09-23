"""Tests for 0.3: shared mistakes, cost per point, charts/report, compare, subagent runs."""
import json
import tempfile
import unittest
from pathlib import Path

from nagents.charts import accuracy_svg, cost_svg, write_charts
from nagents.compare import compare
from nagents.external import (
    ExternalModel,
    PendingAnswers,
    batch_prompt,
    ingest,
    make_batches,
    parse_replies,
)
from nagents.html import write_html
from nagents.models import MockModel
from nagents.report import cost_rows, render
from nagents.runner import recompute, run_grid
from nagents.stats import error_overlap, independent_vote_accuracy
from nagents.tasks import gen_chain


def _meta(task, agent, rnd=0, seed="7:0"):
    return {"task_id": task, "answer": "100", "seed": seed, "agent": agent, "round": rnd,
            "majority_correct": None}


class TestCorrelatedMock(unittest.TestCase):
    def test_zero_correlation_matches_the_independent_mock(self):
        old, new = MockModel(accuracy=0.6), MockModel(accuracy=0.6, correlation=0.0)
        for t in range(30):
            for a in range(5):
                m = _meta(f"t{t}", a)
                self.assertEqual(old.complete("s", "p", m).text, new.complete("s", "p", m).text)

    def test_full_correlation_makes_every_agent_agree(self):
        model = MockModel(accuracy=0.5, correlation=1.0)
        for t in range(20):
            texts = {model.complete("s", "p", _meta(f"t{t}", a)).text for a in range(7)}
            self.assertEqual(len(texts), 1)

    def test_own_accuracy_is_kept(self):
        model = MockModel(accuracy=0.6, correlation=0.5)
        right = sum(
            model.complete("s", "p", _meta(f"t{t}", a)).text.endswith("Answer: 100")
            for t in range(400) for a in range(5)
        )
        self.assertAlmostEqual(right / 2000, 0.6, delta=0.05)

    def test_bad_correlation_rejected(self):
        with self.assertRaises(ValueError):
            MockModel(correlation=1.5)


class TestOverlapStats(unittest.TestCase):
    def test_independent_reference_edges(self):
        self.assertAlmostEqual(independent_vote_accuracy(0.7, 1), 0.7)
        self.assertAlmostEqual(independent_vote_accuracy(1.0, 5), 1.0)
        self.assertAlmostEqual(independent_vote_accuracy(0.0, 5), 0.0)
        # n=2: both right, or exactly one right and it is agent 0 (half the time)
        self.assertAlmostEqual(independent_vote_accuracy(0.5, 2), 0.25 + 0.5 * 0.5)
        self.assertGreater(independent_vote_accuracy(0.6, 9), independent_vote_accuracy(0.6, 3))

    def test_always_wrong_together(self):
        groups = [{"answers": ["5", "5", "5"], "expected": "5"},
                  {"answers": ["9", "9", "9"], "expected": "5"}]
        o = error_overlap(groups)
        self.assertEqual(o["solo_accuracy"], 0.5)
        self.assertAlmostEqual(o["error_correlation"], 1.0)
        self.assertEqual(o["same_wrong_answer_rate"], 1.0)

    def test_different_wrong_numbers(self):
        groups = [{"answers": ["1", "2"], "expected": "5"}, {"answers": ["5", "5"], "expected": "5"}]
        self.assertEqual(error_overlap(groups)["same_wrong_answer_rate"], 0.0)

    def test_empty(self):
        self.assertIsNone(error_overlap([])["solo_accuracy"])

    def test_correlated_mock_shows_in_results(self):
        tasks = gen_chain(60, seed=2, depth=4)
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ind = run_grid(MockModel(0.6), tasks, [1, 3, 5], "independent", 2, a, "m", progress=False)
            cor = run_grid(MockModel(0.6, correlation=0.8), tasks, [1, 3, 5], "independent", 2, b, "m",
                           progress=False)
        self.assertLess(abs(ind["overlap"]["error_correlation"]), 0.15)
        self.assertGreater(cor["overlap"]["error_correlation"], 0.5)
        self.assertLess(cor["per_size"][-1]["accuracy"], ind["per_size"][-1]["accuracy"])
        for row in ind["per_size"]:
            self.assertGreaterEqual(row["best_of_n"], row["accuracy"])


class TestCostAndVisuals(unittest.TestCase):
    def _results(self, tmp, label="claude-opus-5"):
        tasks = gen_chain(12, seed=5, depth=4)
        return run_grid(MockModel(0.6), tasks, [1, 3, 5], "independent", 5, tmp, label, progress=False)

    def test_cost_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._results(tmp)
        costs = cost_rows(res)
        self.assertTrue(costs["priced"])
        self.assertEqual([c["size"] for c in costs["per_size"]], [1, 3, 5])
        tok = [c["tokens_per_question"] for c in costs["per_size"]]
        self.assertTrue(tok[0] < tok[1] < tok[2])
        for step in costs["steps"]:
            if step["gain_points"] <= 0:
                self.assertIsNone(step["tokens_per_point"])
            else:
                self.assertGreater(step["dollars_per_point"], 0)

    def test_unpriced_model_reports_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._results(tmp, label="mock")
        self.assertFalse(cost_rows(res)["priced"])
        self.assertIn("tokens per +1 point", render(res))

    def test_old_results_still_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._results(tmp)
        for row in res["per_size"]:
            for key in ("best_of_n", "independent_reference", "input_tokens_total"):
                row.pop(key, None)
        res.pop("overlap")
        text = render(res)
        self.assertIn("| size | accuracy | 95% CI | mean output tokens |", text)
        self.assertTrue(accuracy_svg(res).startswith("<svg"))
        self.assertIsNone(cost_svg(res))

    def test_charts_and_html_link_every_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = self._results(tmp)
            paths = write_charts(res, tmp)
            self.assertEqual({p.name for p in paths}, {"accuracy.svg", "cost.svg"})
            html = write_html(res, tmp).read_text(encoding="utf-8")
        self.assertEqual(html.count('href="trials/'), 12 * 3)
        self.assertIn("<svg", html)


class TestCompare(unittest.TestCase):
    def test_paired_compare(self):
        tasks = gen_chain(15, seed=4, depth=4)
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            run_grid(MockModel(0.6), tasks, [1, 3], "independent", 4, a, "mock", progress=False)
            run_grid(MockModel(0.6), tasks, [1, 3], "debate", 4, b, "mock", progress=False)
            text = compare(a, b)
        self.assertIn("Paired by trial", text)
        self.assertIn("| 3 |", text)

    def test_unpaired_compare(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            run_grid(MockModel(0.6), gen_chain(8, 1, 4), [1, 3], "independent", 1, a, "m", progress=False)
            run_grid(MockModel(0.6), gen_chain(8, 1, 6), [1, 3], "independent", 1, b, "m", progress=False)
            self.assertIn("Not paired", compare(a, b))


class Solver:
    """Stands in for a subagent: answers a batch prompt correctly, except seat 1."""

    def __init__(self, tasks):
        self.answers = {t.prompt: t.answer for t in tasks}

    def reply(self, batch):
        blocks = []
        for item in batch["items"]:
            truth = next(a for p, a in self.answers.items() if item["prompt"].startswith(p))
            answer = int(truth) + (1 if batch["seat"] == 1 else 0)
            blocks.append(f"=== {item['id']}\nworking\nAnswer: {answer}")
        return "\n\n".join(blocks)


def _drive(tasks, sizes, topology, run_dir, max_loops=4):
    """Run the pending -> batches -> ingest -> resume loop to completion."""
    solver = Solver(tasks)
    for loop in range(max_loops):
        try:
            return run_grid(ExternalModel(run_dir), tasks, sizes, topology, 3, run_dir,
                            "subagents:test", resume=loop > 0, progress=False), loop
        except PendingAnswers:
            for batch in make_batches(run_dir, per_batch=4):
                ingest(run_dir, solver.reply(batch))
    raise AssertionError("run did not finish")


class TestSubagentRuns(unittest.TestCase):
    def test_independent_run_needs_one_loop_and_shares_seats_across_sizes(self):
        tasks = gen_chain(6, seed=3, depth=3)
        with tempfile.TemporaryDirectory() as tmp:
            first = None
            try:
                run_grid(ExternalModel(tmp), tasks, [1, 3, 5], "independent", 3, tmp, "subagents:test", progress=False)
            except PendingAnswers as waiting:
                first = waiting
            # nested design: seats 0..4 per task, shared by the 1-, 3- and 5-agent groups
            self.assertEqual(first.requests, 6 * 5)
            self.assertFalse(any((Path(tmp) / "trials").iterdir()))
            results, loops = _drive(tasks, [1, 3, 5], "independent", tmp)
            self.assertEqual(loops, 1)
            self.assertFalse((Path(tmp) / "pending.jsonl").exists())
            # seat 1 is always wrong: groups of 3 and 5 still vote right
            self.assertEqual([r["accuracy"] for r in results["per_size"]], [1.0, 1.0, 1.0])
            self.assertEqual(recompute(tmp)["per_size"], results["per_size"])

    def test_debate_needs_a_second_loop_and_never_asks_for_garbage(self):
        tasks = gen_chain(4, seed=8, depth=3)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                run_grid(ExternalModel(tmp), tasks, [1, 3], "debate", 3, tmp, "subagents:test", progress=False)
            except PendingAnswers:
                pass
            rows = [json.loads(l) for l in (Path(tmp) / "pending.jsonl").read_text().splitlines()]
            self.assertEqual({r["round"] for r in rows}, {0})  # round 2 waits for round 1
            results, loops = _drive(tasks, [1, 3], "debate", tmp)
            self.assertEqual(loops, 2)
            record = json.loads((Path(tmp) / "trials" / "t0000-n03.json").read_text())
            self.assertEqual(len(record["agents"][0]["rounds"]), 2)

    def test_batches_never_repeat_a_task(self):
        tasks = gen_chain(5, seed=1, depth=3)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                run_grid(ExternalModel(tmp), tasks, [1, 3], "independent", 3, tmp, "subagents:test", progress=False)
            except PendingAnswers:
                pass
            batches = make_batches(tmp, per_batch=3)
            for b in batches:
                ids = [i["id"] for i in b["items"]]
                self.assertLessEqual(len(ids), 3)
                prompts = [i["prompt"] for i in b["items"]]
                self.assertEqual(len(prompts), len(set(prompts)))
            self.assertEqual(sum(len(b["items"]) for b in batches), 15)
            text = batch_prompt(batches[0])
            self.assertIn("no tools", text)
            self.assertIn(batches[0]["items"][0]["id"], text)

    def test_ingest_ignores_unknown_ids_and_duplicates(self):
        tasks = gen_chain(2, seed=1, depth=3)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                run_grid(ExternalModel(tmp), tasks, [1], "independent", 3, tmp, "subagents:test", progress=False)
            except PendingAnswers:
                pass
            key = json.loads((Path(tmp) / "pending.jsonl").read_text().splitlines()[0])["key"]
            reply = f"=== {key}\nAnswer: 3\n\n=== {'f' * 24}\nAnswer: 4"
            stats = ingest(tmp, reply)
            self.assertEqual((stats["added"], stats["unknown"]), (1, ["f" * 24]))
            self.assertEqual(ingest(tmp, reply)["added"], 0)

    def test_parse_replies(self):
        text = "=== " + "a" * 24 + "\nx\nAnswer: 1\n=== " + "b" * 24 + "\nAnswer: 2\n"
        self.assertEqual(parse_replies(text), {"a" * 24: "x\nAnswer: 1", "b" * 24: "Answer: 2"})


if __name__ == "__main__":
    unittest.main()
