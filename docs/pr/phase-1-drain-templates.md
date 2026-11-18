## Summary
Drain3 template mining with `config/drain3.ini` masks, a regex+exact-match baseline, `TemplateStore` with persisted state (ids survive a restart), `SignatureBook` for (service, template, exception) error signatures with first-seen time, and the benchmark run on Loghub and the simulator.

## How it was tested
`uv run pytest tests/test_parse_templates.py tests/test_parse_bench.py`: 50 hand-written lines, mask coverage, restart stability, match() side effects, exception extraction, first-seen and new-since (past only).

## Numbers produced
Grouping accuracy: HDFS 0.9975, BGL 0.8535, OpenStack 0.2985 (regex baseline 0.4815 wins), Apache 1.0, simulator 1.0 per service. See RESULTS.md.

Closes #4
