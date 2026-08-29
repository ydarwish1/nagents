import unittest

from nagents.scoring import extract_answer, is_correct


class TestExtractAnswer(unittest.TestCase):
    def test_answer_line(self):
        self.assertEqual(extract_answer("So it works out.\nAnswer: 42"), "42")

    def test_case_and_equals(self):
        self.assertEqual(extract_answer("ANSWER = -3"), "-3")

    def test_last_answer_line_wins(self):
        self.assertEqual(extract_answer("Answer: 7\nWait, no.\nAnswer: 9"), "9")

    def test_commas_and_dollar(self):
        self.assertEqual(extract_answer("Answer: $1,234"), "1234")

    def test_fallback_last_integer(self):
        self.assertEqual(extract_answer("I compute 12 then 25 in total"), "25")

    def test_empty(self):
        self.assertEqual(extract_answer(""), "")
        self.assertEqual(extract_answer("no numbers here"), "")

    def test_leading_zeros_canonicalized(self):
        self.assertEqual(extract_answer("Answer: 007"), "7")


class TestIsCorrect(unittest.TestCase):
    def test_match(self):
        self.assertTrue(is_correct("Answer: 15", "15"))

    def test_mismatch(self):
        self.assertFalse(is_correct("Answer: 16", "15"))


if __name__ == "__main__":
    unittest.main()
