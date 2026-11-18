## Summary
Seeded simulator for the three-service demo topology: seasonal request rates with Poisson noise, lognormal latency, base error rate, and structured log lines from fixed templates (1 INFO per 20 requests plus every WARN and ERROR).

## How it was tested
`uv run pytest tests/test_sim_traffic.py tests/test_sim_logs.py`: seasonality shape, weekend ratio, determinism, volume bounds, log volume rule, ground-truth coverage, no unfilled placeholders.

## Numbers produced
One full-scale day: about 413k requests and 51k log lines, generated in 0.15 s.

Closes #1
