# Progress

Phase 1 and PRs 7-13 were built before the GitHub repo existed: merged locally with `git merge --no-ff`, bodies in `docs/pr/`, issues in `ISSUES.md`, all pushed afterwards. From the eval-report feature on, issues and PRs are on GitHub (numbers below with `GH`).

## Done
- [x] Phase 1, PR-1 `phase-1/simulator`: Traffic and log simulator
- [x] Phase 1, PR-2 `phase-1/fault-injection`: Fault injector and labels
- [x] Phase 1, PR-3 `phase-1/loghub-benchmark`: Loghub download and parser benchmark harness
- [x] Phase 1, PR-4 `phase-1/drain-templates`: Template extraction and error signatures
- [x] Phase 1, PR-5 `phase-1/aggregation`: Aggregation into per-endpoint series
- [x] Phase 1, PR-6 `phase-1/docs-baseline`: Docs and tracking baseline
- [x] Phase 2, PR-7 `phase-2/eval-metrics`: Incident-level evaluation module
- [x] Phase 2, PR-8 `phase-2/baseline-detectors`: Static threshold and rolling z-score detectors
- [x] Phase 2, PR-9 `phase-2/seasonal-baseline`: Seasonal baseline detector
- [x] Phase 2, PR-10 `phase-2/lint-fix`: Fix lint error merged into main
- [x] Phase 2, PR-11 `phase-2/isolation-forest`: Isolation Forest detector with ablations
- [x] Phase 2, PR-12 `phase-2/prophet-detector`: Prophet residual detector
- [x] Phase 2, PR-13 `phase-2/fixture-float-fix`: Fixture float tolerance for Linux CI
- [x] Phase 2, GH PR #2 `phase-2/eval-report`: Full evaluation and results table
- [x] Phase 2, GH PR #4 `phase-2/nab-check`: External sanity check on NAB
<!--done-->

## Next
Phase 3 (instrumented services, Kafka, Loki/Prometheus/Tempo, streaming consumer). Container work waits for the Docker disk check; services, load generator and consumer code are written first.

## Needs me
- Nothing yet. (Phase 3+ needs Docker disk space; the manager has the figure.)
