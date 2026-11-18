#!/usr/bin/env bash
# Offline gate: lint, tests on the fixture, eval smoke. No Docker, no network.
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS=4
echo "== ruff"; uv run ruff check .
echo "== pytest"; uv run pytest
if [ -f lighthouse/evaluate.py ] && grep -q "def main" lighthouse/evaluate.py; then
  echo "== eval smoke (fixture)"
  start=$(date +%s)
  uv run python -m lighthouse.evaluate --fixture
  elapsed=$(( $(date +%s) - start ))
  echo "eval smoke took ${elapsed}s"
  [ "$elapsed" -le 120 ] || { echo "FAIL: eval smoke over 2 minutes"; exit 1; }
fi
echo "check OK"
