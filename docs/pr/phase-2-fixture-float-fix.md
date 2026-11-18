## Summary
CI on `main` failed on the fixture regeneration test because of last-digit float differences across platforms.

## How it was tested
`uv run pytest tests/test_fixture.py` locally; CI run on this branch.

Closes #13
