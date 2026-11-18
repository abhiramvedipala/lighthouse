# Interview notes

## Phase 1: simulator, parsing, aggregation

**What this phase built**
- A seeded simulator for three services and five endpoints: seasonal request rates, lognormal latency, 657k log lines from about 110 templates, 40 labeled faults of six types and 6 benign events over 14 days.
- A Loghub benchmark harness and Drain3 template mining with masking, a regex baseline, persisted template state and error signatures with first-seen times.
- A DuckDB aggregate table at (service, endpoint, minute) grain with signature features that only read the past.

**Key design decisions and why**
- Faults edit parameter arrays before sampling, so traffic noise never changes when a fault is added. "Why not simulate the call graph?" The evaluation needs a labeled cascade with a lag, not a causal model (D4).
- Faults are placed in stratified slices per type so the test window has every type. "Why not uniform random?" It can leave a type out of the test window and make per-type results empty.
- Drain3 tuned on HDFS and BGL only (D5), per-service parsing and a stricter threshold for simulator logs (D6). "Why not tune on all four?" Then there is no untouched sample to tell whether the setting generalises.

**Hardest problem.** Pooled Drain scored 0.62 on simulator logs while the regex baseline scored 1.0. Digging in showed identical text ("config reloaded") in three services with different true ids, plus messages that differ by a single keyword and merge at similarity 0.4. Fix: parse per service (the service is known at ingest) and pick the threshold on train-day lines only.

**Likely questions**
1. *How do you measure parser quality?* Grouping accuracy: a line counts only if its whole predicted group equals its true group. It is strict; one stray line costs the group.
2. *Drain3 missed 0.9 on BGL and OpenStack. Why report that?* The target was a goal, not a result. BGL gets 0.8535 and OpenStack 0.2985, where plain regex masking does better (0.4815). I tuned only on HDFS and BGL, so OpenStack shows what a new log format does to a threshold tuned elsewhere.
3. *How do you stop future data leaking into features?* The new-signature feature is a cumulative sum over first-seen events up to the current minute, and a test aggregates the fixture truncated at minute 1000 and requires identical features up to that minute.
4. *Why is the simulator's regex baseline as good as Drain?* Every field the simulator emits is matched by a mask, so exact match after masking is already perfect. It says the simulator is easy on this axis, which is a limit I state in the README.
5. *How are template ids kept stable between batch and streaming?* Drain3 state is persisted to a file; a test splits the fixture lines across a restart and requires identical ids.

**Files to open:** `lighthouse/sim/faults.py`, `lighthouse/aggregate.py`, `lighthouse/parse/templates.py`, `tests/test_aggregate.py`, `DECISIONS.md` D5 and D6.

## Phase 2: detectors and evaluation

**What this phase built**
- An incident-level evaluator: alarm events merged at 10 minutes, detection window [start, end + 5 min], precision over alarm events, recall over incidents, lead time versus the static alert, benign-event alarms, and point-adjusted F1 in its own column.
- Five detectors behind one fit/score interface (static threshold, EWMA z-score, seasonal baseline, Isolation Forest, Prophet residual) with validation-only threshold selection under a false-alarm cap and poison-after-cut leakage tests.
- A full run (44.5 s) with IF ablations, charts, and a NAB sanity check.

**Key design decisions and why**
- Alarms per service, one threshold per detector (D8). "Why not per-service thresholds?" Three or four validation incidents per service would overfit them.
- Seasonal baseline scores only the harmful direction and normalises each signal by its train 99.9th percentile (D9). "Why not two-sided?" A planned surge would be an alarm. The normaliser fixed traffic drops, which a heavy-tailed error z had hidden.
- The spec Isolation Forest stays the headline even though variants did better on validation (D10).

**Hardest problem.** Isolation Forest and Prophet looked fine on validation (F1 0.43, 0.44) and collapsed on test (0.18, 0.14, 14 and 7 false alarms a day). A read-only count of false alarms per day showed 44 of 50 IF alarms fell on the weekend, and the train window holds one weekend. I did not tune anything to fix it; the finding went into RESULTS.md and the limits.

**Likely questions**
1. *Did ML beat the threshold?* No. The seasonal baseline (F1 0.79) beat the static threshold (0.67) because it also catches drift and traffic drops; IF (0.18) and Prophet (0.14) lost to it. No detector caught the novel errors.
2. *Why incident level instead of point level?* On-call cares whether an incident was caught and how many alerts fired. Point-adjusted F1 is shown separately because one lucky flag earns a whole segment.
3. *How do you know there is no leakage?* Poison every row after a cut and require identical scores before it; thresholds take only validation scores and labels; the test was shown failing with a deliberately leaky fit.
4. *Why did IF fail?* A lone outlier in one of 24 noisy dimensions is not isolated sharply, and a single train weekend leaves weekend levels rare. Residual-only per-endpoint models did better on validation (0.64) but still lost on test (0.24).
5. *How reliable are 10 test incidents?* Each one moves recall by 0.1; the numbers are indicative. The NAB check (5 windows) is a sanity check, not a ranking.

**Files to open:** `lighthouse/evaluate.py`, `tests/test_evaluate.py`, `lighthouse/detectors/seasonal.py`, `tests/test_leakage.py`, `lighthouse/report.py`, `RESULTS.md`, `DECISIONS.md` D7 to D10.
