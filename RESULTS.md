# Results

Every number has the command that produced it. Speed-dependent numbers carry the `uptime` load average.
Machine: Apple M3, 16 GB, other builds running.

## Parser: grouping accuracy and template counts

Command: `uv run python -m lighthouse.parse.bench --all --sim-dir data/sim` (after `scripts/get_data.sh` and
`uv run python -m lighthouse.sim.run --out data/sim`). Load average 4.3 at run time.
Drain3 uses sim_th 0.4 and depth 4, tuned on HDFS and BGL only (D5). "regex_exact" masks variables with
the same regexes and groups identical strings. "exact" treats every distinct line as its own template.
The simulator row parses per service (D6), and `drain3@0.9` uses the simulator threshold.

| Dataset | Parser | Grouping accuracy | Templates found | Templates true |
|---|---|---|---|---|
| HDFS | **drain3** | **0.9975** | 16 | 14 |
| HDFS | regex_exact | 0.5055 | 194 | 14 |
| HDFS | exact | 0.0010 | 2000 | 14 |
| BGL | **drain3** | **0.8535** | 107 | 120 |
| BGL | regex_exact | 0.4015 | 926 | 120 |
| BGL | exact | 0.1940 | 1367 | 120 |
| OpenStack (untouched) | drain3 | 0.2985 | 33 | 43 |
| OpenStack (untouched) | **regex_exact** | **0.4815** | 107 | 43 |
| OpenStack (untouched) | exact | 0.1980 | 1548 | 43 |
| Apache (untouched) | drain3 | 1.0000 | 6 | 6 |
| Apache (untouched) | regex_exact | 1.0000 | 6 | 6 |
| Apache (untouched) | exact | 0.2905 | 886 | 6 |
| Simulator, 14 days, pooled (sim_th 0.4) | drain3 | 0.6194 | 103 | 119 |
| Simulator, per service | drain3@0.9 | 1.0000 | 119 | 119 |
| Simulator, per service | regex_exact | 1.0000 | 119 | 119 |

Reading: the 0.9 target holds on HDFS (0.9975) and Apache (1.0). It does not hold on BGL (0.8535) and badly
fails on OpenStack (0.2985), where the plain regex baseline beats Drain3 (0.4815). I did not tune on
OpenStack. On the simulator the regex baseline ties Drain3 because the simulator's fields are easy to mask.
