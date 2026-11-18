# Study guide

How to read this repo before an interview. The GitHub repo is created by the owner after the build, so the
"PRs" below are local merge commits (`Merge PR-n: ...`) with their bodies in `docs/pr/`.

## PRs in reading order

Phase 1: simulator, parsing, aggregation
1. PR-1 `phase-1/simulator`: seeded traffic and log generation (`lighthouse/sim/traffic.py`, `logs.py`).
2. PR-2 `phase-1/fault-injection`: six fault types, benign events, labels, the committed fixture.
3. PR-3 `phase-1/loghub-benchmark`: data download and the grouping-accuracy harness.
4. PR-4 `phase-1/drain-templates`: Drain3, regex baseline, error signatures.
5. PR-5 `phase-1/aggregation`: the per-endpoint per-minute table.
6. PR-6 `phase-1/docs-baseline`: README skeleton, tracking files.

Phase 2: detectors and evaluation
7. PR-7 `phase-2/eval-metrics`: `lighthouse/evaluate.py` and its 26 hand-computed tests.
8. PR-8 `phase-2/baseline-detectors`: detector interface, static threshold, z-score, threshold selection, leakage tests.
9. PR-9 `phase-2/seasonal-baseline`, PR-11 `phase-2/isolation-forest`, PR-12 `phase-2/prophet-detector`: the three models.
10. PR-10, PR-13: two small CI fixes (a lint line, Linux float digits).
11. GH #2 `phase-2/eval-report`: the full run and results; GH #4 `phase-2/nab-check`.

(Phases 3 to 5 are added as they land.)

## The commits that matter most (so far)

| Hash | Why it matters |
|---|---|
| `19b4059` | Vectorised request sampler: 5M requests in seconds, faults edit parameters not samples |
| `96bef3a` | Fault scheduler and effects: stratified placement so every split sees every type |
| `95ca786` | Loghub grouping accuracy in one groupby |
| `a07a6a5` | TemplateStore (persisted Drain state) and SignatureBook (first-seen, past-only) |
| `78eddef` | Why pooled Drain scored 0.62 on simulator logs and what per-service parsing fixed |
| `f6592f1` | DuckDB aggregation and the cumulative-sum new-signature feature |

Phase 2 commits worth opening: the evaluator (`feat(evaluate)`), the poison leakage test (`test(leakage)`), the seasonal normaliser (`feat(detectors): add the seasonal baseline`), and `feat(report)`.

## Reading paths

15 minutes: `README.md` (Results and How it works), `docs/schema.md`, `lighthouse/sim/faults.py` (`_apply`), `lighthouse/aggregate.py` (`aggregate`), `RESULTS.md`.

60 minutes: add `lighthouse/sim/traffic.py`, `lighthouse/sim/logs.py`, `lighthouse/parse/templates.py`, `lighthouse/parse/bench.py`, then the tests for each (`tests/test_sim_faults.py`, `tests/test_parse_templates.py`, `tests/test_aggregate.py`, especially the truncation test), then `DECISIONS.md` D3 to D6.
