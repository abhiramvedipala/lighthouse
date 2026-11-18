## Summary
`lighthouse/evaluate.py`: alarm-event merging (gap <= 10 min), detection window [start, end + 5 min], precision over alarm events, recall over incidents, false alarms per day, detection delay, lead time versus the static alert, benign-event alarms counted separately, point-adjusted F1 in its own field, and a converter from the simulator labels.

## How it was tested
`uv run pytest tests/test_evaluate.py`: 26 hand-computed cases (merge boundary, tolerance edges, flag spanning two incidents, overlapping incidents on different services, cascade, lead time, benign events, window clipping, point-adjust).

## Numbers produced
None (metrics only).

Closes #7
