import json
import tempfile
import unittest
from pathlib import Path

from nagents.models import MockModel
from nagents.report import render
from nagents.runner import run_grid
from nagents.tasks import gen_chain


class TestRunGrid(unittest.TestCase):
    def test_end_to_end_mock(self):
        tasks = gen_chain(10, seed=3, depth=4)
        sizes = [1, 3]
        with tempfile.TemporaryDirectory() as tmp:
            results = run_grid(
                MockModel(accuracy=0.7), tasks, sizes, "independent", 3, tmp, "mock-test"
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


if __name__ == "__main__":
    unittest.main()
