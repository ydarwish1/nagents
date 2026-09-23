import unittest

from nagents.models import OpenAIModel


def fake(reply):
    sent = []

    def post(body):
        sent.append(body)
        return reply

    return post, sent


class TestOpenAIModel(unittest.TestCase):
    def test_request_and_text(self):
        post, sent = fake({
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": "6 x 7\\nAnswer: 42"}]},
            ],
            "usage": {"input_tokens": 30, "output_tokens": 9},
        })
        reply = OpenAIModel("gpt-5", max_tokens=500, effort="low", post=post).complete("sys", "q", {"answer": "42"})
        self.assertEqual(reply.text, "6 x 7\\nAnswer: 42")
        self.assertEqual((reply.input_tokens, reply.output_tokens, reply.stop_reason), (30, 9, "end_turn"))
        body = sent[0]
        self.assertEqual(body["instructions"], "sys")
        self.assertEqual(body["input"], "q")
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertNotIn("answer", str(body))  # the model never sees the answer

    def test_refusal_and_cutoff(self):
        post, _ = fake({"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]})
        self.assertEqual(OpenAIModel("gpt-5", post=post).complete("s", "q", {}).stop_reason, "refusal")
        post, _ = fake({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []})
        reply = OpenAIModel("gpt-5", post=post).complete("s", "q", {})
        self.assertEqual((reply.text, reply.stop_reason), ("", "max_output_tokens"))

    def test_needs_a_key(self):
        import os
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                OpenAIModel("gpt-5")
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
