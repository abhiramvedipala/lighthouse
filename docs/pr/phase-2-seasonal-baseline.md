## Summary
Seasonal baseline detector: per endpoint and signal (log rate, error rate, log p95) median and MAD per (weekday/weekend, 5-minute slot) from clean train minutes, robust z in the harmful direction, normalised by the train 99.9th percentile.

## How it was tested
`uv run pytest tests/test_detector_seasonal.py tests/test_leakage.py`: synthetic sine with a planted spike, drop vs surge asymmetry, slot layout, causality, fit independence from post-train data, unseen-slot fallback.

## Numbers produced
Validation (threshold selection): precision 0.93, recall 0.80, F1 0.86 at 0.11 false alarms per service-day; misses novel_error. Test numbers come from the full evaluation PR only.

Closes #9
