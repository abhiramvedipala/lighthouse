# Progress

The GitHub repo does not exist yet, so features are merged locally with `git merge --no-ff` and PR bodies live in `docs/pr/`.

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
<!--done-->

## Needs me
- Create the private repo `abhiramvedipala/lighthouse` (sessions cannot): `gh repo create abhiramvedipala/lighthouse --private`, then add it as `origin`. Push `main` alone first and wait for CI, then tags and branches three at a time.
