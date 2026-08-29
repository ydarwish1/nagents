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

### 2.4 Statistics

- Accuracy per size, with percentile bootstrap 95% CIs (2000 resamples, seeded).
- Marginal gain per size step, with paired bootstrap CIs over per-trial
  differences.
- Saturation (v0 heuristic): smallest size s such that no larger measured size
  beats s by more than `epsilon` (default 0.01). Returns "not reached" when the
  curve still climbs at the largest measured size. CIs are printed next to it;
  phase 4 upgrades this to a CI-based rule.
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

### Phase 0 — Foundation (this commit) ✅
Scaffold, task generators, both topologies, mock model, transcript writer,
bootstrap stats, saturation heuristic, CLI, unit tests, CI.
**Exit:** tests green; mock grid runs end to end and shows a rise-then-flatten
curve. Cost: $0.

### Phase 1 — Real smoke run
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
Upgrade saturation to a CI-based rule; charts (accuracy vs. N, cost vs. N,
gain-per-dollar); write-up with links into the committed transcripts of every
headline number. Publish as the portfolio "nagents" page (card 06).
**Exit:** a reader can click from any claim to the transcript behind it.

### Phase 5 — Stretch
Heterogeneous seats (mixed models), orchestrator-worker topology,
tool-using agents, external benchmark suites via `jsonl`.

## 5. Threats to validity (tracked, not hand-waved)

- **Ceiling effects.** If solo accuracy is ~100%, groups can't help. Mitigation:
  the depth knob; pick depths where solo accuracy lands 40–80% in phase 1.
- **Answer-extraction errors masquerading as model errors.** Mitigation: strict
  `Answer: <number>` contract, extractor unit-tested, transcripts auditable.
- **Vote ties.** Deterministic tie-break, recorded in the transcript.
- **API drift mid-experiment.** Model id pinned in the manifest; one run = one
  code version; phases re-run their own baselines rather than borrowing.
- **Mock leakage.** Mock results are labeled `mock(...)` in every manifest and
  report; they never mix with real results in one run directory.

## 6. Definition of done

The project is done when phases 0–4 are complete: a published page states, for
at least one real model and two difficulty levels, (a) the measured accuracy
curve with CIs, (b) the saturation point or its absence, (c) the cost per
marginal point, (d) independent vs. debate — each claim linked to transcripts.
