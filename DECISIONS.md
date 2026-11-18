# Decisions

Numbered, in the order they were made. Format: context, options, choice, why.

## D1. Local-first git workflow until the GitHub repo exists
- Context: `gh repo create` is not available to the build sessions; the owner creates `abhiramvedipala/lighthouse`.
- Options: wait for the repo, or build locally in the same shape.
- Choice: one branch per feature (`phase-N/<slug>`), merged into `main` with `git merge --no-ff`; PR bodies in `docs/pr/`, issues in `ISSUES.md`.
- Why: the history the owner studies has the same shape either way; pushing later is one command (see PROGRESS.md "Needs me").

## D2. Drain3 works on Python 3.12, so it is not vendored
- Context: Drain3 0.9.11 is sdist-only and from 2022.
- Choice: use it as a dependency (installs and parses on 3.12.12 with pandas 3.1 and numpy 2.5).
- Why: a vendored copy would only add code to maintain. If a later upgrade breaks it, `lighthouse/drain.py` is the fallback plan.

## D3. Simulator is vectorised and uses independent random streams
- Context: 14 days at about 5M requests must generate in seconds.
- Choice: sample all requests in one `np.repeat` pass; `SeedSequence.spawn` gives traffic, faults and logs separate streams.
- Why: adding a fault type never reshuffles the traffic noise, and a full run takes about 5 seconds.

## D4. The dependency cascade is injected, not simulated
- Context: `gateway /checkout` calls `orders` calls `inventory`, so an inventory outage should show upstream.
- Options: a real call-graph simulation, or inject errors on the upstream endpoints with a 1 to 2 minute lag.
- Choice: inject. Orders errors start 1-2 minutes after inventory, gateway checkout 1-2 minutes after orders.
- Why: the evaluation needs a labeled lag and cascade, not a causal model. Real call propagation is exercised later by the live stack.

## D5. Drain3 parameters for Loghub: sim_th 0.4, depth 4
- Context: tune the similarity threshold on HDFS and BGL only; OpenStack and Apache stay untouched.
- Result: `scripts/tune_drain.py` shows HDFS 0.9975 for every sim_th 0.3-0.7, BGL peaks at 0.856 for sim_th 0.3-0.5 (depth 5 is +0.0025) and collapses to 0.50 at 0.6+.
- Choice: sim_th 0.4, depth 4 (the Drain defaults, middle of the plateau). Depth 5 was not worth a 0.003 gain.

## D6. Simulator logs are parsed per service with sim_th 0.9
- Context: pooled Drain scored 0.62 on simulator logs. Identical text such as "config reloaded" exists in three services with different true template ids, and messages that differ by one keyword merge at 0.4.
- Choice: parse per service (the service is known at ingest) and use sim_th 0.9, chosen on train-day lines only (`scripts/tune_drain.py --sim`: 0.89 at 0.7, 0.917 at 0.8, 1.0 at 0.9).
- Why: honest and still documented as a simulator-specific setting. The Loghub setting stays 0.4. The regex baseline also scores 1.0 on the simulator because its masks cover every field the simulator emits; this says more about the simulator being easy than about Drain.

## D7. Leakage tests were shown to fail once
- Context: the Definition of done asks for leakage tests that fail when the split is broken.
- What I did: temporarily changed `RollingZScore.fit` to fit on all 20,160 minutes instead of the train window (and drop the train mask). `tests/test_leakage.py::test_fit_and_scores_before_the_train_cut_ignore_later_rows[rolling_zscore]` failed as it should; I reverted the change and the suite is green again.
- Why it matters: a leakage test that has never failed proves nothing. The poison-after-cut design also catches non-causal rolling windows, not only fitting on the wrong rows.

## D8. Alarms are per service; one threshold per detector
- Context: detectors score endpoints, IF scores services, and the brief speaks of false alarms per day per service.
- Choice: a service is flagged in a minute when its score exceeds the detector's threshold (service score = max over its endpoints). One threshold per detector, not per service, chosen on validation to maximise incident-level F1 subject to an average of at most 1 false alarm per service per day.
- Why: per-service thresholds would be fitted on only 3 to 4 validation incidents each. The cost: a noisy service can exceed 1 false alarm a day on average-feasible thresholds; the per-service numbers are in RESULTS.md.

## D9. Seasonal baseline design choices, and how they were made
- One-sided scores: a rate drop, an error rise and a latency rise are harmful; a traffic surge is not an alarm by itself. The benign surge events exist to test exactly this. The rolling z-score stays two-sided as specified, so it can false-alarm on surges.
- Slots pool their two neighbours (about 30 samples per weekend slot instead of 10).
- Each series' z is divided by its train 99.9th percentile before the max over signals. Without it the heavy-tailed error-rate z set the validation threshold at 18 and traffic drops (a rate-only signal at z about 8) were never caught on validation (recall 0 on that type).
- Process note: while developing this detector I printed test-window numbers once next to validation. The normaliser change was motivated by the validation failure on traffic drops, not by the test numbers, but the habit is wrong. From here on development output shows validation only; the test window is scored once, by `python -m lighthouse.evaluate --all`.

## D10. Isolation Forest: spec version reported, plus variants chosen on validation
- Observation (validation window only): the spec version (per service, raw levels + seasonal residuals + deltas + template features) reaches F1 0.43 and misses every latency spike, while the seasonal baseline gets 0.86 on the same window. A lone outlier in one of about 24 dimensions is not isolated sharply, and heavy-tailed noise dimensions (error-rate residual, WARN counts) make ordinary minutes look odd. A synthetic planted-spike test shows the same effect (spike ranks in the top decile, not the top 0.1 percent).
- Choice: report the spec version as `isolation_forest`, and report the variants (residual-only, per endpoint, no deltas) in the ablation table. Whichever variant has the best validation F1 is named in RESULTS.md as such; the headline row stays the spec version.
- Why: swapping silently to a better variant would hide that the specified model loses to the seasonal baseline, which is the finding the repo exists to report.
