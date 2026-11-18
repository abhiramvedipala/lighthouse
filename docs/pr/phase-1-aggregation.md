## Summary
`lighthouse/aggregate.py` builds the one aggregate table described in `docs/schema.md`: per (service, endpoint, minute) request count, error count and rate, p50/p95/p99, WARN/ERROR lines, distinct error signatures and 24-hour new signatures. DuckDB over parquet, Drain per service in time order.

## How it was tested
`uv run pytest tests/test_aggregate.py`: hand-computed tiny example, empty minutes, new-signature expiry at exactly 24 h, and a truncation test proving the features only read the past.

## Numbers produced
14-day simulator: 100,800 rows in 14.5 s, peak 1.1 GB (load average about 10).

Closes #5
