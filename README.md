# nagents

**Do more agents actually help? Measured.**

- Same task, group sizes one to N
- Finds where more agents stop helping
- Keeps transcripts, so wins aren't luck

`nagents` runs the same set of tasks through agent groups of size 1, 2, 3, ... N,
scores every trial against a known correct answer, and reports where the
accuracy curve stops climbing. Every agent's full prompt and reply is written to
disk, so every number in the report can be traced back to a transcript.

The full plan, start to finish, lives in [SPEC.md](SPEC.md).

## Quickstart (no API key needed)

The mock model is deterministic and free. It demos the whole pipeline:

```bash
python3 -m nagents run --mock --suite chain --depth 8 --trials 40 --sizes 1,2,3,4,5,7,9 --out runs/demo
```

You get a table like this (accuracy per group size, paired bootstrap CIs, and
the saturation point), plus full transcripts under `runs/demo/trials/`:

```
| size | accuracy | 95% CI | mean output tokens |
| step | gain | 95% CI (paired) |
Saturation: gains stop at size N (epsilon=0.01).
```

Print the report again later:

```bash
python3 -m nagents report runs/demo
```

`results.json` is never the source of truth — the transcripts are. Rebuild the
results from the trial files at any time (it refuses incomplete runs):

```bash
python3 -m nagents recompute runs/demo
```

## Real runs (Claude API)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...   # or use an `ant auth login` profile
python3 -m nagents run --suite chain --depth 10 --trials 30 --sizes 1,3,5 --model claude-opus-5 --effort low --out runs/real-01
```

Notes for real runs:

- Default model is `claude-opus-5`. `--effort low|medium|high|xhigh|max` maps to
  the API's `output_config.effort`.
- There is deliberately **no refusal fallback to another model**: swapping
  models mid-eval would contaminate the measurement. A refusal is recorded in
  the transcript and scored as incorrect.
- Agent diversity comes from natural sampling (current Claude models do not
  accept temperature overrides).
- `--workers N` runs the independent calls inside a round in parallel.
  Transcripts and results are identical at any worker count.
- A killed run loses at most the trial in flight. Rerun the same command with
  `--resume`: finished transcripts are reloaded, never re-billed. The run
  directory's manifest is checked first — a config that differs is refused, so
  two different experiments can never blend into one result.

## How a run works

1. A task suite is generated from a seed (or loaded from a JSONL file). Every
   task has an exact integer answer.
2. For each trial, the **same task** is given to every group size (paired
   design — sizes are compared on identical work).
3. A topology decides how the group works:
   - `independent` — N agents answer alone; majority vote picks the final answer.
   - `debate` — round 1 alone; round 2 each agent sees the others' answers and
     revises; majority vote on round 2.
4. Every trial writes a JSON transcript: every agent's prompt, reply, extracted
   answer, and token usage.
5. Stats: accuracy per size with bootstrap 95% CIs, paired marginal gain per
   size step, and a saturation heuristic (`epsilon` = gain considered noise).

## Repo map

```
nagents/          the package
  tasks.py        seeded task generators + JSONL loader
  models.py       MockModel (deterministic, free) + AnthropicModel (real runs)
  topologies.py   independent / debate group runners
  scoring.py      answer extraction + exact match
  runner.py       the grid: tasks x sizes, transcripts to disk
  stats.py        bootstrap CIs, paired gains, saturation
  report.py       results.json -> readable table
  cli.py          nagents run / report / recompute
tests/            offline unit tests (stdlib unittest, no API, no deps)
SPEC.md           the full plan, phases 0-5
runs/             output (gitignored)
```

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

No dependencies. CI runs the tests plus a full mock grid on every push.
