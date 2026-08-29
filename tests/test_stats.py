import unittest

from nagents.stats import bootstrap_ci, find_saturation, mean, paired_diff_ci, summarize


class TestBasics(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([1, 0, 1, 0]), 0.5)
        self.assertEqual(mean([]), 0.0)

    def test_bootstrap_deterministic_and_sane(self):
        xs = [1] * 60 + [0] * 40
        lo1, hi1 = bootstrap_ci(xs, seed="t")
        lo2, hi2 = bootstrap_ci(xs, seed="t")
        self.assertEqual((lo1, hi1), (lo2, hi2))
        self.assertLessEqual(lo1, 0.6)
        self.assertGreaterEqual(hi1, 0.6)
        self.assertLess(hi1 - lo1, 0.3)

    def test_paired_diff_ci_positive_effect(self):
        a = [0] * 50 + [1] * 50
        b = [1] * 80 + [0] * 20
        lo, hi = paired_diff_ci(a, b, seed="p")
        self.assertGreater(hi, lo)
        self.assertGreater(hi, 0)


class TestSaturation(unittest.TestCase):
    def test_plateau_found(self):
        sizes = [1, 3, 5, 7]
        accs = [0.5, 0.7, 0.705, 0.708]
        self.assertEqual(find_saturation(sizes, accs, epsilon=0.01), 3)

    def test_still_climbing(self):
        self.assertIsNone(find_saturation([1, 3, 5], [0.5, 0.6, 0.7], epsilon=0.01))

    def test_single_size(self):
        self.assertEqual(find_saturation([5], [0.8], epsilon=0.01), 5)

    def test_flat_curve(self):
        self.assertEqual(find_saturation([1, 2, 3], [0.9, 0.9, 0.9], epsilon=0.01), 1)


class TestSummarize(unittest.TestCase):
    def test_shape(self):
        sizes = [1, 3]
        correct = {1: [1, 0, 1, 0], 3: [1, 1, 1, 0]}
        tokens = {1: [100, 100, 100, 100], 3: [300, 300, 300, 300]}
        out = summarize(sizes, correct, tokens)
        self.assertEqual(len(out["per_size"]), 2)
        self.assertEqual(len(out["gains"]), 1)
        self.assertEqual(out["per_size"][0]["accuracy"], 0.5)
        self.assertEqual(out["per_size"][1]["mean_output_tokens"], 300.0)
        self.assertEqual(out["gains"][0]["gain"], 0.25)


if __name__ == "__main__":
    unittest.main()
