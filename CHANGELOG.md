# Changelog

One entry per merged PR.

## Phase 1
- PR-1 Traffic and log simulator: seeded seasonal traffic, 5 endpoints, ~110 log templates, JSON-lines and parquet output
- PR-2 Fault injector and labels: six fault types, two benign events, stratified scheduling, labels.json, example plots, 3.7 MB CI fixture
- PR-3 Loghub download and parser benchmark harness: get_data.sh for Loghub and NAB, grouping accuracy and template count harness
- PR-4 Template extraction and error signatures: Drain3 with masking config, regex baseline, persisted state, error signatures, first parser table
- PR-5 Aggregation into per-endpoint series: DuckDB per-endpoint per-minute table with signature features, schema doc, past-only leakage test
