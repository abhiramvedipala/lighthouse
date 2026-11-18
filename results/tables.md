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
