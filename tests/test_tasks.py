import re
import unittest

from nagents.tasks import gen_arith, gen_chain, make_suite


def replay_chain(prompt: str) -> int:
    """Recompute a chain task's answer from its own prompt text."""
    value = int(re.search(r"Start with (\d+)\.", prompt).group(1))
    for op, num in re.findall(r"(Add|Subtract|Multiply by) (\d+)\.", prompt):
        n = int(num)
        if op == "Add":
            value += n
        elif op == "Subtract":
            value -= n
        else:
            value *= n
    return value


class TestChain(unittest.TestCase):
    def test_deterministic(self):
        a = gen_chain(10, seed=3, depth=6)
        b = gen_chain(10, seed=3, depth=6)
        self.assertEqual(a, b)
        c = gen_chain(10, seed=4, depth=6)
        self.assertNotEqual(a, c)

    def test_answer_matches_prompt(self):
        for task in gen_chain(50, seed=11, depth=9):
            self.assertEqual(replay_chain(task.prompt), int(task.answer), task.prompt)


class TestArith(unittest.TestCase):
    def test_deterministic_and_positive(self):
        a = gen_arith(20, seed=5)
        b = gen_arith(20, seed=5)
        self.assertEqual(a, b)
        for task in a:
            self.assertGreater(int(task.answer), 0)

    def test_answer_matches_prompt(self):
        for task in gen_arith(30, seed=9):
            nums = [int(n) for n in re.findall(r"\d+", task.prompt)]
            a, b, c, d, e, f = nums[:6]
            self.assertEqual(a * b + c * d - e * f, int(task.answer))


class TestMakeSuite(unittest.TestCase):
    def test_unknown_suite(self):
        with self.assertRaises(ValueError):
            make_suite("nope", 5, 1)

    def test_jsonl_needs_path(self):
        with self.assertRaises(ValueError):
            make_suite("jsonl", 5, 1)


if __name__ == "__main__":
    unittest.main()


class TestMult(unittest.TestCase):
    def test_deterministic_and_correct(self):
        from nagents.tasks import gen_mult
        a, b = gen_mult(5, seed=3, digits=7), gen_mult(5, seed=3, digits=7)
        self.assertEqual(a, b)
        for t in a:
            x, y = [int(w) for w in t.prompt.split("?")[0].split() if w.isdigit()]
            self.assertEqual(len(str(x)), 7)
            self.assertEqual(str(x * y), t.answer)

    def test_make_suite_routes_digits(self):
        from nagents.tasks import make_suite
        self.assertTrue(make_suite("mult", 2, 1, digits=4)[0].task_id.startswith("mult4-"))
