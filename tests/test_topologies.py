import unittest

from nagents.models import MockModel, ModelReply
from nagents.stats import mean
from nagents.tasks import gen_chain
from nagents.topologies import _final_vote, _majority, run_group


class RefusesAgentZero:
    """Stub: agent 0 always refuses with an empty reply; others answer right."""

    def complete(self, system, prompt, meta):
        if meta["agent"] == 0:
            return ModelReply("", stop_reason="refusal")
        return ModelReply(f"Answer: {meta['answer']}")


class TestVoting(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_majority(["5", "7", "5"]), "5")

    def test_tie_breaks_to_first_seen(self):
        self.assertEqual(_majority(["5", "7", "7", "5"]), "5")

    def test_final_vote_ignores_empty(self):
        self.assertEqual(_final_vote(["", "5"]), "5")
        self.assertEqual(_final_vote(["", ""]), "")


class TestGroups(unittest.TestCase):
    def test_transcript_shape_independent(self):
        model = MockModel(accuracy=0.9)
        task = gen_chain(1, seed=2, depth=4)[0]
        rec = run_group(model, task, size=3, topology="independent", seed="s:0")
        self.assertEqual(len(rec["agents"]), 3)
        for agent in rec["agents"]:
            self.assertEqual(len(agent["rounds"]), 1)
            self.assertIn("prompt", agent["rounds"][0])
            self.assertIn("reply", agent["rounds"][0])
        self.assertEqual(rec["usage"]["calls"], 3)
        self.assertIn(rec["final_answer"], rec["votes"])

    def test_transcript_shape_debate(self):
        model = MockModel(accuracy=0.6)
        task = gen_chain(1, seed=2, depth=4)[0]
        rec = run_group(model, task, size=3, topology="debate", seed="s:0")
        for agent in rec["agents"]:
            self.assertEqual(len(agent["rounds"]), 2)
        self.assertEqual(rec["usage"]["calls"], 6)

    def test_workers_do_not_change_results(self):
        task = gen_chain(1, seed=8, depth=5)[0]
        serial = run_group(MockModel(0.6), task, 5, "independent", "w:0", workers=1)
        pooled = run_group(MockModel(0.6), task, 5, "independent", "w:0", workers=4)
        self.assertEqual(serial, pooled)
        serial_d = run_group(MockModel(0.6), task, 4, "debate", "w:1", workers=1)
        pooled_d = run_group(MockModel(0.6), task, 4, "debate", "w:1", workers=3)
        self.assertEqual(serial_d, pooled_d)

    def test_refusal_never_outvotes_an_answer(self):
        task = gen_chain(1, seed=2, depth=4)[0]
        rec = run_group(RefusesAgentZero(), task, 2, "independent", "s:0")
        self.assertEqual(rec["final_answer"], task.answer)
        self.assertEqual(rec["votes"][0], "")

    def test_majority_vote_beats_solo(self):
        """The core premise, demonstrated on the mock: groups outvote solo errors."""
        model = MockModel(accuracy=0.65)
        tasks = gen_chain(300, seed=1, depth=4)
        acc = {}
        for size in (1, 5):
            hits = []
            for t, task in enumerate(tasks):
                rec = run_group(model, task, size, "independent", seed=f"m:{t}")
                hits.append(1 if rec["final_answer"] == task.answer else 0)
            acc[size] = mean(hits)
        self.assertGreater(acc[5], acc[1] + 0.05)

    def test_unknown_topology(self):
        task = gen_chain(1, seed=2, depth=4)[0]
        with self.assertRaises(ValueError):
            run_group(MockModel(), task, 2, "swarm", seed="s")


if __name__ == "__main__":
    unittest.main()
