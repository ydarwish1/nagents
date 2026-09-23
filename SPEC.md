# nagents — full specification and plan

**Question:** do more agents actually help — and where do they stop helping?

Everyone assumes "more agents = better." This project measures it: same task,
group sizes 1 to N, exact scoring, full transcripts, real confidence intervals.
The deliverable is a curve (accuracy vs. group size), the point where it
flattens, and the receipts to prove neither is luck.

---

## 1. Research questions

- **RQ1 — Does accuracy rise with group size?** For a fixed task suite and
  topology, is `acc(N)` increasing in N?
- **RQ2 — Where does it saturate?** Smallest N after which additional agents
  add less than `epsilon` accuracy (with CIs that support the claim).
- **RQ3 — What does each marginal win cost?** Tokens (and dollars) per added
  point of accuracy, per size step.
- **RQ4 — Does topology matter?** Independent-vote vs. debate at equal N: which
  buys more accuracy per token?
- **RQ5 (stretch) — Does difficulty move the saturation point?** Harder tasks
  should saturate later. Measured via the `chain` suite's depth knob.

## 2. Method

### 2.1 Tasks

Every task has one exact integer answer, so scoring is mechanical (no LLM
judge in the core loop — judge bias is a threat to validity).

- `chain` (primary): seeded chained-arithmetic problems. `--depth` controls
  difficulty; deep chains induce real model slips, which gives the curve room
  to move.
- `arith`: two-product word problems. Easy; used as a smoke suite.
- `jsonl`: bring-your-own suite (`{"id", "prompt", "answer"}` per line) for
  external benchmarks (e.g. a GSM-hard subset) without shipping their data.

### 2.2 Topologies

- `independent`: N agents answer the same task in isolation; majority vote
  (self-consistency). Ties break deterministically to the earliest answer.
- `debate`: round 1 independent; round 2 each agent sees the others' round-1
  answers and revises; vote over round-2 answers.
- Future (phase 5): orchestrator-workers, heterogeneous models per seat.

### 2.3 Design rules (what makes the wins not luck)

- **Paired trials.** Trial t uses the same task at every group size. Size
  comparisons are paired, which shrinks variance and licenses paired CIs.
- **Seeded everything.** Task generation, mock behavior, and bootstrap
  resampling are all seeded. A run is reproducible from its `manifest.json`.
- **Transcripts are the ground truth.** Every agent call (prompt, reply,
  extracted answer, stop reason, token usage) is written to
  `runs/<run>/trials/tNNNN-nSS.json`. Aggregates are recomputable from disk.
- **No refusal fallback.** A refusal is scored incorrect and logged — never
  silently answered by a different model.
- **No mid-run code edits.** The manifest records the nagents version; a run is
  one code version end to end.
- **Crash-safe and resumable.** Every trial cell is written the moment it
  finishes. `--resume` reloads finished cells (never re-runs, never re-bills)
  and refuses a run directory whose manifest config differs from the command.
- **Results are disposable, transcripts are not.** `nagents recompute` rebuilds
  `results.json` from the trial files alone and refuses incomplete runs — a
  partial grid can never masquerade as a result.

### 2.4 Statistics

- Accuracy per size, with percentile bootstrap 95% CIs (2000 resamples, seeded).
- Marginal gain per size step, with paired bootstrap CIs over per-trial
  differences.
- Saturation, two rules reported side by side (default `epsilon` 0.01):
  - **Point rule**: smallest size s such that no larger measured size beats s
    by more than `epsilon`. "Not reached" when the curve still climbs.
  - **Paired-CI rule** (stricter): smallest s where, for every larger measured
    size, the upper bound of the paired 95% CI on the gain over s is at most
    `epsilon` — saturation is only called when the data rules out a meaningful
    hidden gain.
- Data quality per size: refusal trials and unparsed-vote trials are counted
  and surfaced in the report; an unparsed answer never outvotes a real one.
- Cost: mean output tokens per size, so RQ3 is dollars-per-point arithmetic.

### 2.5 Models

- Real runs: `claude-opus-5` by default via the official `anthropic` SDK
  (thinking adaptive by default; `--effort` exposed; no temperature — current
  models do not accept sampling overrides, diversity comes from sampling).
- `MockModel`: deterministic hash-based fake with tunable per-agent accuracy.
  It exists to test the pipeline and demo the analysis, not to make claims.

## 3. Architecture

```
tasks.py -> topologies.py -> runner.py -> transcripts (disk) -> stats.py -> report.py
                 ^
             models.py (MockModel | AnthropicModel)
```

One deliberate constraint: the core engine is stdlib-only. `anthropic` is the
single optional dependency (real runs only). Tests never touch the network.

## 4. Phases — start to finish

### Phase 0 — Foundation ✅
Scaffold, task generators, both topologies, mock model, transcript writer,
bootstrap stats, saturation heuristic, CLI, unit tests, CI.
**Exit:** tests green; mock grid runs end to end and shows a rise-then-flatten
curve. Cost: $0.

### Phase 0.1 — Hardening ✅
Crash-safe resume (`--resume` + manifest config guard), `recompute` (results
rebuilt from transcripts, incomplete runs refused), `--workers` parallel calls
(results identical at any worker count), refusal/unparsed-vote tracking,
empty votes excluded from majority, paired-CI saturation rule, dollar cost
estimates in the report, SDK retries raised for long grids, CI matrix
(Python 3.9 + 3.13) that also exercises run → recompute → report.
**Exit:** tests green; a resumed run provably makes zero model calls. Cost: $0.

### Phase 0.2 — Shared mistakes, cost per point, receipts, subagents ✅
- **Shared mistakes (why curves flatten).** From first-round answers only: error
  correlation between agents (phi over agent pairs), how often two wrong agents
  gave the same wrong number, a best-case "if mistakes were independent" curve
  (independent agents, wrong answers never matching), and the "someone in the
  group was right" ceiling. The mock gains `--mock-correlation` so the effect can
  be demonstrated and tested offline; correlation 0 reproduces the old mock exactly.
- **Cost per point (RQ3).** Tokens (and dollars when the model is priced) per
  question per size, and per +1 accuracy point for every size step.
- **Receipts (phase 4 groundwork).** `charts/accuracy.svg`, `charts/cost.svg`, and
  `report.html` with every trial cell linking to its transcript; `compare` puts two
  runs side by side, paired per trial when they share tasks, with an overlay chart.
- **Subagent backend.** `--subagents LABEL` answers calls with Claude subagents
  instead of the API: pending calls → `batches` (no batch ever repeats a task) →
  `ingest` → `--resume`. Replies are keyed by a hash of exactly what the agent
  saw. Seats are shared across sizes (nested design), so a grid up to size N costs
  N answers per task rather than the sum of all sizes. Token counts are estimated
  from text length and flagged.
**Exit:** tests green; a subagent plumbing check (1 subagent, 2 throwaway
problems) completed pending → ingest → resume → report. Cost: $0.

### Phase 1 — Real smoke run
Subagent route (no API key): `nagents-solver` subagents (Haiku, no tools, 10
problems per subagent), `chain` at depths 6, 10 and 14, 10 trials, seats 1–5.
Pick the depth where solo accuracy lands 40–80% for phase 2.
API route: as below.
Wire check against the live API. `chain --depth 10`, sizes {1,3,5}, 10 trials,
`--effort low`, topology independent.
**Exit:** transcripts parse, refusal/stop-reason handling observed, measured
per-call token costs recorded back into this file (the estimates below are
estimates until then).
Est. cost: ~150 calls ≈ $2–6 at Opus 5 rates ($5/M in, $25/M out).

### Phase 2 — The main grid
Sizes {1,2,3,4,5,7,9}, ≥100 trials, `chain` at two depths (difficulty axis,
RQ5) — topology independent.
**Exit:** RQ1/RQ2 answered with CIs for one topology; saturation point stated
or explicitly "not reached." Est. cost: 31 calls/trial × 100 trials × 2 depths
≈ 6,200 calls ≈ $60–250 (pin down after phase 1).

### Phase 3 — Topology comparison
Same grid, topology debate (2 rounds ⇒ ~2× calls at N>1). Paired against
phase 2 results per trial.
**Exit:** RQ4 answered: accuracy-per-token for debate vs. independent at equal
N. Est. cost: ~2× phase 2.

### Phase 4 — Analysis & publication
Pick the headline saturation rule (both rules ship since phase 0.1; prefer the
paired-CI rule when trial counts support it); charts (accuracy vs. N, cost vs.
N, gain-per-dollar); write-up with links into the committed transcripts of
every headline number. Publish as the portfolio "nagents" page (card 06).
**Exit:** a reader can click from any claim to the transcript behind it.

### Phase 5 — Stretch
Heterogeneous seats (mixed models), orchestrator-worker topology,
tool-using agents, external benchmark suites via `jsonl`.

### Findings so far (2026-09-23, Claude Haiku via subagents, no tools)

All runs are committed in `study/`.

- **Chain arithmetic is too easy.** Haiku solved `chain` perfectly at depths
  6, 10, 14, 25 and 50 (`study/pilot-d*`), so the `mult` suite was added:
  multiply two `--digits`-digit numbers. Solo accuracy: 5 digits 88%, 7 digits
  60%, 9 digits 6% (`study/pilot-m*`). Phase 2 used 7 and 8 digits.
- **Phase 2 (voting, 40 trials, sizes 1–9, every seat counted equally).**
  7 digits: 57.8% → 97.8%; 8 digits: 37.8% → 91.1%. No saturation in range for
  either. Error correlation +0.06 / +0.02, same wrong answer 1.1% / 0.4%, so
  both curves sit close to the independent-mistakes reference. Size 2 = size 1
  (a split pair is a tie).
- **Phase 3 (debate vs. voting, 7 digits, paired).** Debate reached 40/40 at
  sizes 3 and 5 against 77.5% / 82.5% for voting on the same seats
  (+22.5 [+10, +37.5] and +17.5 [+7.5, +30] points), at ~2.6× the tokens.
- **Sonnet (same setup, `study/sonnet-*`).** One Sonnet agent was right
  49/50 at 8 digits, 50/50 at 10 and 12, 49/50 at 16, and 44/50 at 20 in the
  pilots (10 problems, 5 seats each). The 20-digit main run (40 trials, sizes
  1, 3, 5, seat-balanced): 95.0% [92.0, 97.5] → 99.5% → 100%. Error correlation
  0.00, same wrong answer 0%. One 20-digit batch twice hit the subagent's
  64k output-token limit and was re-run as two batches of 5 (`b019a`, `b019b`);
  two other batches needed one retry each.
- **Haiku vs. Sonnet.** On the same kind of task, one Sonnet at 20 digits beats
  nine Haikus at 8 digits (95% vs. 91%). Token counts for subagent runs cover
  visible reply text only, not hidden reasoning, so they do not compare cost
  across models.
- **Position-in-batch bias (threat found and fixed).** Within a 10-problem
  batch, the first problem was right ~72% of the time against 22–44% later.
  Batches used to put seat 0 first, inflating size 1. Fixes: batches are
  shuffled by a hash of each call's key; every independent run reports a seat
  check (each seat's solo accuracy) and a seat-balanced curve (plurality credit
  averaged over all n-seat subsets of the largest group, ties split). Runs
  before the fix are kept; the seat-balanced curve is the headline for them.

## 5. Threats to validity (tracked, not hand-waved)

- **Ceiling effects.** If solo accuracy is ~100%, groups can't help. Mitigation:
  the depth knob; pick depths where solo accuracy lands 40–80% in phase 1.
- **Answer-extraction errors masquerading as model errors.** Mitigation: strict
  `Answer: <number>` contract, extractor unit-tested, transcripts auditable.
- **Vote ties.** Deterministic tie-break, recorded in the transcript.
- **Order effects inside a subagent batch.** A subagent gives the first problem in a batch the most care, so a
  seat that always comes first looks better. Mitigation: shuffled batches, the
  seat check, and the seat-balanced curve (see findings above).
- **API drift mid-experiment.** Model id pinned in the manifest; one run = one
  code version; phases re-run their own baselines rather than borrowing.
- **Mock leakage.** Mock results are labeled `mock(...)` in every manifest and
  report; they never mix with real results in one run directory (the manifest
  config guard enforces this mechanically).
- **Partial-run bias.** A crashed grid must not be read as a result: results
  are only written when the grid completes, and `recompute` refuses a run with
  missing cells instead of silently aggregating what survived.

## 6. Definition of done

The project is done when phases 0–4 are complete: a published page states, for
at least one real model and two difficulty levels, (a) the measured accuracy
curve with CIs, (b) the saturation point or its absence, (c) the cost per
marginal point, (d) independent vs. debate — each claim linked to transcripts.
