# Changelog

One entry per merged PR.

## Phase 1
- PR-1 Traffic and log simulator: seeded seasonal traffic, 5 endpoints, ~110 log templates, JSON-lines and parquet output
- PR-2 Fault injector and labels: six fault types, two benign events, stratified scheduling, labels.json, example plots, 3.7 MB CI fixture
- PR-3 Loghub download and parser benchmark harness: get_data.sh for Loghub and NAB, grouping accuracy and template count harness
- PR-4 Template extraction and error signatures: Drain3 with masking config, regex baseline, persisted state, error signatures, first parser table
- PR-5 Aggregation into per-endpoint series: DuckDB per-endpoint per-minute table with signature features, schema doc, past-only leakage test
- PR-6 Docs and tracking baseline: README with all sections, Mermaid architecture, study guide, Phase 1 interview notes

## Phase 2
- PR-7 Incident-level evaluation module: alarm merging, tolerance, precision/recall/F1, FA per day, delay, lead vs static, point-adjusted F1, benign alarms
- PR-8 Static threshold and rolling z-score detectors: Detector interface, static threshold baseline, EWMA z-score, validation-only threshold selection, leakage tests
- PR-9 Seasonal baseline detector: median/MAD per weekday-weekend 5-minute slot, one-sided robust z, per-series normaliser
- PR-10 Fix lint error merged into main: wrap one long line that failed ruff on main
- PR-11 Isolation Forest detector with ablations: per-service IF with residual/template/delta features, ablation switches, permutation importance
- PR-12 Prophet residual detector: per-series Prophet on 5-minute bins, interval-width residual score, 12 s for 15 fits
