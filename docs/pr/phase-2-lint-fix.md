## Summary
One line in `tests/test_leakage.py` exceeded the line limit after PR-9 and failed `ruff check`, which `scripts/check.sh` runs.

## How it was tested
`uv run ruff check .` clean, then `./scripts/check.sh` before merging.

Closes #10
