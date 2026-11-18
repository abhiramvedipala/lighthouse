# Aggregate table schema

One table, one grain: **(service, endpoint, minute)**. Built by `lighthouse/aggregate.py` with DuckDB
over the request parquet and the parsed logs, written to `aggregates.parquet`. Every minute of the
window is present for every endpoint, including minutes with no requests (count 0, latency null),
so a traffic drop shows up as a row and not as a hole.

| Column | Type | Meaning |
|---|---|---|
| `ts` | timestamp (UTC) | start of the 1-minute window |
| `service` | string | `gateway`, `orders` or `inventory` |
| `endpoint` | string | for example `POST /checkout` |
| `request_count` | int | requests that started in the minute |
| `error_count` | int | requests with status >= 500 |
| `error_rate` | float | `error_count / request_count`, 0 when there are no requests |
| `p50_ms`, `p95_ms`, `p99_ms` | float | latency percentiles (linear interpolation), null with no requests |
| `warn_error_lines` | int | WARN and ERROR log lines in the minute |
| `distinct_error_sigs` | int | distinct error signatures among the ERROR lines in the minute |
| `new_sigs_24h` | int | error signatures first seen on this endpoint within the 24 hours up to the end of the minute |

An **error signature** is `(service, template id, exception class)`. Template ids come from Drain3 run
per service in log order. `new_sigs_24h` only reads log lines up to the end of the minute, so a
signature is never "new" before it has actually appeared. For the first 24 hours of a window every
signature is new (cold start); detectors that use this column should skip or discount day 1.
