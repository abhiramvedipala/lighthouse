## Summary
Six labeled fault types (latency_spike, error_burst, dependency_outage with cascade, latency_drift, traffic_drop, novel_error) plus benign traffic surge and deploy events. Stratified placement over the 14 days, labels written to labels.json, one example plot per type in docs/faults/, and `scripts/make_fixture.py` producing the committed 2-day fixture.

## How it was tested
`uv run pytest tests/test_sim_faults.py tests/test_fixture.py`: counts, split coverage, no overlap per service, each effect measured on the generated series, determinism, fixture size and regeneration.

## Numbers produced
Full run: 5.29M requests, 657k log lines, 40 faults, 6 benign events in 3.2 s. Fixture: 211k requests, 26.6k lines, 12 faults, 3.7 MB.

Closes #2
