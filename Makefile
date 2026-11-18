.PHONY: check test lint fixture eval
check:
	./scripts/check.sh
test:
	uv run pytest
lint:
	uv run ruff check .
fixture:
	uv run python scripts/make_fixture.py
eval:
	uv run python -m lighthouse.evaluate --all
