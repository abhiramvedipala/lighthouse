## Summary
`scripts/get_data.sh` downloads the four Loghub 2k samples and the NAB series into the gitignored `data/`. `lighthouse/parse/bench.py` computes Loghub grouping accuracy and template counts for any registered parser.

## How it was tested
`uv run pytest tests/test_parse_bench.py` (9 cases on a hand-made truth set). Manual: `uv run python -m lighthouse.parse.bench --all` runs the exact-match floor on all four samples (HDFS 0.001, BGL 0.194, OpenStack 0.198, Apache 0.291).

## Numbers produced
Exact-match baseline only; Drain3 numbers come in the next PR.

Closes #3
