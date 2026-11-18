## Summary
`IsolationForestDetector`: one IsolationForest (200 trees, contamination auto) per service on concatenated endpoint features, with switches for residuals, template features, raw levels, deltas, per-endpoint models and clean vs contaminated training, and a permutation-importance helper (AUC drop on validation).

## How it was tested
`uv run pytest tests/test_detector_iforest.py tests/test_leakage.py` (the IF is registered in the poison tests); `./scripts/check.sh`.

## Numbers produced
Validation only, simulator: spec IF F1 0.43 versus seasonal baseline 0.86; it misses latency spikes and novel errors. Explanation and decision D10 in DECISIONS.md. Test-window numbers come from the full evaluation PR.

Closes #11
