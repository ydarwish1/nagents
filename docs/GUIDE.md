# nagents guide

Everything the README leaves out: how to run it, what each command does, how
the numbers are computed, and where the study data lives.

## Running it for real

### 1. Claude subagents (no API key)

This is how the study above was run. Each seat in a group is answered by a
separate Claude subagent that gets a batch of *different* problems and answers
them with no tools. It never sees the same problem twice, so no subagent can
agree with itself.

```bash
# 1. Lay out the grid. It stops and lists the calls that need answers.
python3 -m nagents run --subagents "haiku,no-tools,10-per-batch" --suite mult --digits 7 \
    --trials 40 --sizes 1,2,3,4,5,7,9 --out runs/m7

# 2. Split them into batches (10 problems per subagent) with the exact prompt for each.
python3 -m nagents batches runs/m7 --prompts runs/m7/prompts

# 3. Give each prompts/bXXX.txt to one subagent (the nagents-solver agent in
#    .claude/agents/), save each reply to a file, then store the answers:
python3 -m nagents ingest runs/m7 runs/m7/replies/*.txt

# 4. Rerun step 1 with --resume. Debate runs loop once more for the revision round.
python3 -m nagents run ... --resume
```

Seats are shared across group sizes: the 3-agent group is seats 0 to 2 and
the 9-agent group is seats 0 to 8. A grid up to 9 therefore needs 9 answers
per problem, not 31, and every size is compared on the same answers. Each
batch mixes seats and is shuffled, so no seat always goes first. Replies are
keyed by a hash of exactly what the agent saw, so a reply can never be reused
for a different question. Token counts for subagent runs are estimated from
text length and marked as estimates.

### 2. The Claude API

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...   # or an `ant auth login` profile
python3 -m nagents run --suite mult --digits 7 --trials 40 --sizes 1,3,5 --model claude-opus-5 --effort low --out runs/api-01
```

`--effort` maps to `output_config.effort`. There is deliberately **no fallback
to another model** when one refuses: swapping models mid-run would corrupt the
measurement. A refusal is recorded and scored as wrong. `--workers N`
parallelizes calls without changing results.

### 3. OpenAI (GPT) models

```bash
export OPENAI_API_KEY=...
python3 -m nagents run --provider openai --model gpt-5 --effort low --suite mult --digits 7 \
    --trials 40 --sizes 1,3,5 --out runs/gpt-01
```

This calls the OpenAI Responses API directly, with no extra packages.
`--effort` maps to `reasoning.effort`. The same rules hold: no fallback model,
and a refusal or a cut-off reply is scored as wrong.

## Commands

| Command | What it does |
|---|---|
| `run` | Run the grid (`--mock`, `--subagents LABEL`, or the API). `--resume` continues a killed or waiting run. Writes transcripts, `results.json`, `charts/` and `report.html` |
| `report RUN [--html]` | Print the report again (and rebuild charts and HTML) |
| `recompute RUN` | Rebuild results from the transcripts alone. Refuses incomplete runs |
| `compare A B [--chart F.svg]` | Two runs side by side, paired per trial when they used the same tasks (for example debate vs. independent) |
| `batches RUN` / `ingest RUN FILES` | The subagent loop: batch the waiting calls, then store the replies |

## How a run works

1. **Tasks.** Seeded problems with one exact integer answer: `mult` (multiply two
   `--digits`-digit numbers), `chain` (chained arithmetic, `--depth` steps), easy word
   problems (`arith`), or your own JSONL file (`{"id", "prompt", "answer"}` per line).
   Haiku solved even 50-step chains perfectly, so `mult` is the suite with real headroom.
2. **Paired trials.** Trial *t* gives the same problem to every group size.
3. **Topology.** `independent`: everyone answers alone and the most common answer wins.
   `debate`: round 1 alone, then each agent sees the others' answers and revises before the vote.
4. **Stats.** Accuracy per size with bootstrap 95% CIs, and a paired gain for each
   step up in size. Gains stop at the smallest size where the paired-CI upper bound
   of every further gain is at most `epsilon`. For independent runs a second curve
   averages over every choice of seats, so no seat's luck or position drives the result.
5. **Shared mistakes.** From first-round answers: the error correlation between agents,
   how often two wrong agents gave the *same* wrong number, the curve for independent
   mistakes, and the "someone in the group was right" ceiling.

Transcripts are the source of truth; `results.json` can be deleted and rebuilt at any time.

## The study data

Every run behind the charts above is committed in `study/`, with each
subagent's prompt and reply: `pilot-*` (choosing the difficulty), `main-m7`
and `main-m8` (the voting curves), `debate-m7` (debate). Open any
`study/*/report.html`, or rebuild the README charts with
`python3 docs/make_study_charts.py`.

## Repo map

```
nagents/
  tasks.py       seeded task suites + JSONL loader
  models.py      MockModel (free; optional shared mistakes), AnthropicModel, OpenAIModel
  external.py    subagent answers: pending calls, shuffled batches, ingest
  topologies.py  independent / debate
  scoring.py     answer extraction + exact match
  runner.py      the grid; crash-safe, resumable transcripts
  stats.py       bootstrap CIs, paired gains, saturation, seat-balanced curve, shared mistakes
  report.py      text report + cost per point
  charts.py      SVG charts (no dependencies)
  html.py        report.html with a link to every transcript
  compare.py     two runs side by side
.claude/agents/nagents-solver.md   the solver subagent (no tools)
study/                             the real runs behind this README
docs/GUIDE.md                      this guide
docs/make_study_charts.py          rebuilds the README charts from study/
docs/make_demo.sh                  rebuilds the mock demo charts
SPEC.md                            the full plan and what each phase found
```

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

Offline, no dependencies. CI runs the tests plus a full mock grid, recompute, and compare on every push.
