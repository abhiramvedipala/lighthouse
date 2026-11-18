## Summary
Prophet residual detector: one model per endpoint and signal, daily and weekly seasonality, seeded uncertainty, score = harmful residual over interval width normalised by train 99.9th percentile.

## How it was tested
`./scripts/check.sh` (142 tests). Prophet tests: spike, fit/score independence from later rows, causality, determinism.

## Numbers produced
Simulator: 15 fits in 12 s at 5-minute resolution (no 15-minute fallback needed). Validation F1 about 0.44.

Closes #12
