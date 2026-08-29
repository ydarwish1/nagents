import json
import tempfile
import unittest
from pathlib import Path

from nagents.models import MockModel, ModelReply
from nagents.report import render
from nagents.runner import recompute, run_grid
from nagents.tasks import gen_chain


class ExplodingModel:
    """Stub that fails the test if any API call is made (proves resume reuse)."""

    def complete(self, system, prompt, meta):
        raise AssertionError("model was called — resume did not reuse transcripts")


class RefusesAgentZero:
    def complete(self, system, prompt, meta):
        if meta["agent"] == 0:
            return ModelReply("", stop_reason="refusal")
        return ModelReply(f"Answer: {meta['answer']}")


class TestRunGrid(unittest.TestCase):
    def test_end_to_end_mock(self):
        tasks = gen_chain(10, seed=3, depth=4)
        sizes = [1, 3]
        with tempfile.TemporaryDirectory() as tmp:
            results = run_grid(
                MockModel(accuracy=0.7), tasks, sizes, "independent", 3, tmp,
                "mock-test", progress=False,
            )
            out = Path(tmp)
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "results.json").exists())
            trial_files = sorted((out / "trials").glob("*.json"))
            self.assertEqual(len(trial_files), len(tasks) * len(sizes))

            # Paired design: the same task appears at every size for a trial.
            t0 = json.loads((out / "trials" / "t0000-n01.json").read_text())
            t0b = json.loads((out / "trials" / "t0000-n03.json").read_text())
            self.assertEqual(t0["task_id"], t0b["task_id"])
            self.assertEqual(t0["seed"], t0b["seed"])

            # Aggregates recomputable from disk: results match trial files.
            on_disk = json.loads((out / "results.json").read_text())
            self.assertEqual(on_disk["per_size"], results["per_size"])
            self.assertEqual(results["per_size"][0]["trials"], len(tasks))

            # Report renders without blowing up and names the model.
            text = render(results)
            self.assertIn("mock-test", text)
            self.assertIn("| size |", text)


class TestResume(unittest.TestCase):
    def test_resume_reuses_transcripts_without_calling_the_model(self):
        tasks = gen_chain(6, seed=3, depth=4)
        sizes = [1, 3]
        with tempfile.TemporaryDirectory() as tmp:
            first = run_grid(
                MockModel(accuracy=0.7), tasks, sizes, "independent", 3, tmp,
                "mock-test", progress=False,
            )
            resumed = run_grid(
                ExplodingModel(), tasks, sizes, "independent", 3, tmp,
                "mock-test", resume=True, progress=False,
            )
            self.assertEqual(first["per_size"], resumed["per_size"])
            self.assertEqual(first["gains"], resumed["gains"])

    def test_nonempty_dir_without_resume_is_refused(self):
        tasks = gen_chain(2, seed=3, depth=4)
        with tempfile.TemporaryDirectory() as tmp:
            run_grid(MockModel(), tasks, [1], "independent", 3, tmp,
                     "mock-test", progress=False)
            with self.assertRaises(SystemExit):
                run_grid(MockModel(), tasks, [1], "independent", 3, tmp,
                         "mock-test", progress=False)

    def test_config_mismatch_is_refused(self):
        tasks = gen_chain(2, seed=3, depth=4)
        with tempfile.TemporaryDirectory() as tmp:
            run_grid(MockModel(), tasks, [1, 3], "independent", 3, tmp,
                     "mock-test", progress=False)
            with self.assertRaises(SystemExit):
                run_grid(MockModel(), tasks, [1, 3], "debate", 3, tmp,
                         "mock-test", resume=True, progress=False)


class TestRecompute(unittest.TestCase):
    def test_recompute_matches_original(self):
        tasks = gen_chain(6, seed=3, depth=4)
        with tempfile.TemporaryDirectory() as tmp:
            first = run_grid(MockModel(accuracy=0.7), tasks, [1, 3], "independent",
                             3, tmp, "mock-test", progress=False)
            (Path(tmp) / "results.json").unlink()
            rebuilt = recompute(tmp)
            self.assertEqual(first, rebuilt)

    def test_recompute_refuses_incomplete_runs(self):
        tasks = gen_chain(4, seed=3, depth=4)
        with tempfile.TemporaryDirectory() as tmp:
            run_grid(MockModel(), tasks, [1], "independent", 3, tmp,
                     "mock-test", progress=False)
            (Path(tmp) / "trials" / "t0002-n01.json").unlink()
            with self.assertRaises(SystemExit):
                recompute(tmp)


class TestDataQuality(unittest.TestCase):
    def test_refusals_and_unparsed_votes_are_counted(self):
        tasks = gen_chain(3, seed=5, depth=4)
        with tempfile.TemporaryDirectory() as tmp:
            results = run_grid(RefusesAgentZero(), tasks, [1, 2], "independent",
                               5, tmp, "stub", progress=False)
            by_size = {row["size"]: row for row in results["per_size"]}
            # Size 1: the only agent refuses every trial -> all wrong.
            self.assertEqual(by_size[1]["refusal_trials"], 3)
            self.assertEqual(by_size[1]["unparsed_vote_trials"], 3)
            self.assertEqual(by_size[1]["accuracy"], 0.0)
            # Size 2: agent 1 still answers; the empty vote never outvotes it.
            self.assertEqual(by_size[2]["refusal_trials"], 3)
            self.assertEqual(by_size[2]["accuracy"], 1.0)
            # The report surfaces the problem.
            self.assertIn("refusal", render(results))


if __name__ == "__main__":
    unittest.main()
