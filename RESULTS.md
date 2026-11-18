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

## Simulator data and aggregation

Command: `uv run python -m lighthouse.sim.run --out data/sim` (seed 20261112, 14 days from 2026-10-05).

| Item | Value |
|---|---|
| Days, endpoints, services | 14, 5, 3 |
| Requests | 5,288,170 |
| Log lines | 657,184 (one INFO per 20 requests plus every WARN and ERROR) |
| Faults | 40: latency_spike 8, error_burst 8, dependency_outage 4, latency_drift 6, traffic_drop 6, novel_error 8 |
| Benign events | 6: traffic_surge 4, deploy 2 |
| Generation time | 4.7 s (load average about 4) |

Aggregation. Command: `/usr/bin/time -l uv run python -m lighthouse.aggregate --source sim`.

| Item | Value |
|---|---|
| Output | 100,800 rows (5 endpoints x 20,160 minutes), 12 columns, see docs/schema.md |
| Wall-clock | 14.5 s (including Drain3 over all 657k log lines) |
| Peak RAM | 1.1 GB |
| Machine load (`uptime`, 1 min) | 10.4 before, 11.4 after |

## Detection: incident-level results (test window, days 11-14)

**Who beat whom.** The seasonal baseline wins: precision 0.79, recall 0.80, F1 0.79, with 3 incidents caught that the static alert missed and a median lead of 3.0 minutes on the 5 incidents both catch. Isolation Forest and Prophet lose to it, and also to the plain static threshold on F1 (0.67): IF reaches F1 0.18 and Prophet 0.14, because on the test window they raise 14.3 and 7.3 false alarms per day against under 1 per service-day on validation. Per fault type: the static threshold catches loud faults (latency spikes 2/2, error bursts 2/2, the outage 1/1) and misses drift (0/1), traffic drops (0/2) and novel errors (0/2); the seasonal baseline also catches drift (1/1) and both traffic drops; **no detector catches novel errors (0/2 everywhere)**, so the log-template signal did not help on this simulator. The z-score is close to the static alert (F1 0.69). Targets missed: IF and Prophet do not reach precision/recall 0.8; only the seasonal baseline does (0.79/0.80, slightly under on precision); the lead-time target of 2+ minutes holds for the seasonal baseline (3.0), z-score (4.0) and IF (4.0, over 2 shared incidents).

Why IF and Prophet collapse (diagnosis, not tuned): `scripts/fa_by_day.py` shows their false alarms are on the weekend days of the test window (Isolation Forest 44 of 50 alarm events on Sat/Sun, Prophet 20 of 26), while the seasonal baseline (2) and z-score (2) barely alarm. The train window contains a single weekend, so models that learn weekly shape from raw levels see an ordinary weekend as rare; the seasonal baseline has explicit weekday/weekend slots and the z-score adapts online. With only 10 test incidents each count moves recall by 0.1, so treat the numbers as indicative, not tight.

Command: `uv run python -m lighthouse.evaluate --all` (simulator seed 20261112, thresholds in `results/thresholds.json`, raw metrics in `results/metrics.json`). Test window 4 days, 10 real incidents, 3 benign events. Offline train + evaluate wall-clock: **44.5 s** (including 6 IF ablation fits and 15 Prophet fits at 5-minute resolution), measured at load average about 100 (the machine was shared), so it is a pessimistic figure. Precision counts alarm events; point-adjusted F1 is a separate column that inflates scores by crediting a whole incident for one flag. Charts: `docs/lead_time.png`, `docs/incident_timeline.png`. The ensemble (max of normalised seasonal, IF, Prophet) was not better than its best member on validation (0.43 vs 0.86) and is therefore not reported.

| Detector | Precision | Recall | F1 | False alarms/day | Median delay (min) | Median lead vs static (min) | Detector-only catches | Benign-event alarms | Point-adjusted F1 |
|---|---|---|---|---|---|---|---|---|---|
| static_threshold | 1.00 | 0.50 | 0.67 | 0.00 | 4.0 | reference | - | 0 (0/3 events) | 0.36 |
| rolling_zscore | 0.80 | 0.60 | 0.69 | 0.50 | 1.0 | 4.0 | 1 | 0 (0/3 events) | 0.41 |
| seasonal_baseline | 0.79 | 0.80 | 0.79 | 0.75 | 2.0 | 3.0 | 3 | 0 (0/3 events) | 0.71 |
| isolation_forest | 0.11 | 0.50 | 0.18 | 14.25 | 2.0 | 4.0 | 2 | 0 (0/3 events) | 0.58 |
| prophet_residual | 0.09 | 0.30 | 0.14 | 7.25 | 5.0 | -1.0 | 0 | 0 (0/3 events) | 0.12 |

Recall per fault type on the test window (detected / incidents):

| Detector | latency_spike | error_burst | dependency_outage | latency_drift | traffic_drop | novel_error |
|---|---|---|---|---|---|---|
| static_threshold | 2/2 | 2/2 | 1/1 | 0/1 | 0/2 | 0/2 |
| rolling_zscore | 2/2 | 2/2 | 1/1 | 0/1 | 1/2 | 0/2 |
| seasonal_baseline | 2/2 | 2/2 | 1/1 | 1/1 | 2/2 | 0/2 |
| isolation_forest | 1/2 | 1/2 | 1/1 | 1/1 | 1/2 | 0/2 |
| prophet_residual | 2/2 | 0/2 | 1/1 | 0/1 | 0/2 | 0/2 |

Validation (where thresholds were chosen): rolling_zscore F1 0.67 at threshold 8.702; seasonal_baseline F1 0.86 at threshold 2.203; isolation_forest F1 0.43 at threshold 0.590; prophet_residual F1 0.44 at threshold 1.007; ensemble F1 0.43 at threshold 0.926

Isolation Forest ablations (thresholds on validation, scored on test):

| Variant | Val F1 | Test precision | Test recall | Test F1 | False alarms/day |
|---|---|---|---|---|---|
| isolation_forest (spec) | 0.43 | 0.11 | 0.50 | 0.18 | 14.25 |
| no residual features | 0.39 | 0.11 | 0.30 | 0.16 | 6.25 |
| no template features | 0.38 | 0.09 | 0.40 | 0.14 | 10.50 |
| contaminated train | 0.47 | 0.12 | 0.40 | 0.18 | 11.00 |
| residual-only features | 0.55 | 0.10 | 0.30 | 0.15 | 11.50 |
| residual-only, per endpoint | 0.64 | 0.15 | 0.70 | 0.24 | 13.00 |


## External sanity check: NAB (window level)

Command: `uv run python -m lighthouse.nab` after `scripts/get_data.sh` (51 s, load average about 100). Same detectors and the same `evaluate.py`, but NAB's labeled windows as incidents, a 35/25/40 time split and an unlabeled threshold (99.9th percentile of the detector's validation scores), because there are too few windows for a labeled validation. Window-level precision and recall, not the official NAB score (that needs per-profile weights and a different window convention). Isolation Forest here uses residual-only features. A sample this small shows the detectors are not only tuned to the simulator; it does not rank them.

| Series | Detector | Test windows | Detected | Alarm events | Precision | Recall |
|---|---|---|---|---|---|---|
| machine_temperature | seasonal_baseline | 2 | 2 | 7 | 0.43 | 1.0 |
| machine_temperature | isolation_forest | 2 | 2 | 7 | 0.57 | 1.0 |
| machine_temperature | prophet_residual | 2 | 0 | 0 | n/a | 0.0 |
| ec2_cpu_utilization | all three | 0 | n/a | 0 | n/a | n/a (its only window falls in the train part) |
| rds_cpu_utilization | seasonal_baseline | 2 | 2 | 11 | 0.27 | 1.0 |
| rds_cpu_utilization | isolation_forest | 2 | 2 | 3 | 0.33 | 1.0 |
| rds_cpu_utilization | prophet_residual | 2 | 2 | 1 | 1.00 | 1.0 |
| elb_request_count | seasonal_baseline | 1 | 1 | 12 | 0.17 | 1.0 |
| elb_request_count | isolation_forest | 1 | 1 | 13 | 0.23 | 1.0 |
| elb_request_count | prophet_residual | 1 | 1 | 34 | 0.15 | 1.0 |

Reading: windows are 17 to 48 hours wide, so recall is easy (every detector finds 5 of 5 windows on rds and elb) and precision is the discriminating number, which is low for all (0.15 to 0.57) except Prophet on rds (1 alarm, 1.0). Prophet missed both machine_temperature windows with no alarms at all. Nothing here contradicts the simulator ranking, and nothing confirms it: n is 5 windows.
