## Summary
Detector interface (`fit(ds, window)`, causal `score(ds)`), the static-threshold baseline (error rate > 5% or p95 > 2x SLO for 5 minutes, untuned), an EWMA rolling z-score, `Dataset` with time-based splits and train masks, validation-only threshold selection under a false-alarm cap, and leakage tests that poison all rows after a cut.

## How it was tested
`uv run pytest tests/test_detector_static.py tests/test_detector_zscore.py tests/test_thresholds.py tests/test_leakage.py`. The leakage test was shown to fail with a deliberately leaky fit (D7).

## Numbers produced
Preliminary, simulator test window (10 incidents): static threshold precision 1.0, recall 0.5 (catches spikes, bursts, outage; misses drift, novel error, traffic drop). Official numbers come with the full evaluation PR.

Closes #8
