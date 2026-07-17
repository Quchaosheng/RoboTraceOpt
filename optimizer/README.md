# Diagnosis-guided optimization

The action registry is the first Phase 5 component. It maps a diagnosed
`cause_id` to a bounded, auditable set of configuration actions. A candidate
must pass `validate_action` before a search runner may evaluate it; actions
belonging to another cause are rejected instead of silently widening the
search space.

This layer does not claim an optimization improvement by itself. Search,
objective measurement, repeated trials, and rollback validation are separate
steps and must use calibration data only.

`optimizer.search.diagnosis_guided_sampler.sample_candidates` currently emits
deterministic boundary/interior candidates for one diagnosed action. The
`seed` is part of the reproducibility contract; stochastic search is deferred
until the objective and validation protocol are frozen.

The runtime objective keeps one latency quantile as the scalar search target
and treats complete-trace rate as a hard validation constraint. The retained
F4 development smoke compares the injected report against the zero-delay
candidate at p95. It reports a 0.987681 improvement ratio with no coverage
change and is stored at
`data/processed/optimization/development/f4_smoke_20260717_01/validation.json`.
Both inputs are development-only, so the result has
`formal_optimization_allowed=false` and cannot support a formal superiority
claim.

`optimizer.validation.rollback` converts an accepted or rejected validation
into an auditable `apply_candidate` or `restore_baseline` record. It validates
both configurations against the diagnosed cause and always records
`live_mutation_performed=false`; applying launch parameters to a live system is
outside this offline safety boundary.

The retained F1 development smoke uses planner-processing p95 as its objective.
It decreases from 100.157 ms to 0.188 ms with unchanged complete-trace rate,
producing an improvement ratio of 0.998119 and an `apply_candidate` decision.
The records are stored under
`data/processed/optimization/development/f1_smoke_20260717_01/`. This is also a
development-only pipeline check, not evidence that the search method is
superior to random or unguided optimization.

`optimizer.search.trial_planner` freezes comparable `guided`, `random`, and
`unguided_random` protocols. Each plan records its seed, budget, action-space
sizes, candidate configuration, and whether each trial is applicable to the
diagnosed cause. The retained F1/F4 plans use seed `20260717` and are stored in
`data/processed/optimization/development/search_plans_20260717/`. For both
causes the registry reduces the selectable action dimension from six to one.
The six-trial unguided plans contain one applicable action and five unrelated
actions; this is a protocol-level budget observation, not an optimization
performance result.

`optimizer.integration.diagnosis_gate` is the boundary between diagnosis and
search. It accepts only a valid `diagnosis-report/v1` with status `diagnosed`,
valid evidence, sufficient confidence and completeness, and a registered
action for `top_1`. Abstained, partial, ambiguous, low-confidence, and
unsupported diagnoses produce an auditable deny result with no trial plan.
Oracle and hidden-label fields are rejected recursively and are never consumed
by the optimizer.

The first real F1 search smoke was executed serially from commit `9af4488` with
five six-second trials per strategy. Guided evaluated 0/25/50/75/100 ms;
random evaluated the frozen 45/36/23/64/27 ms sequence. Measured
planner-processing p95 values followed the configured delay. With a provisional
30 ms target, guided reached the target in trial 1 and random in trial 3; best
p95 values were 0.195 ms and 23.203 ms. Minimum complete-trace rates were
0.9565 and 0.9545. The summary is stored at
`data/processed/optimization/development/f1_search_20260717_01/summary.json`.
This is one development smoke with a direction-informed guided ordering, so it
does not establish statistical superiority. Formal evaluation still requires
repeated randomized runs, frozen targets, calibration evidence, and an
unguided executable baseline.

The same runtime-trial protocol was then executed on W2/F4 from commit
`1088509`. Five guided and five random six-second trials evaluated the same
delay values as the F1 smoke. Request-response p95 increased from 1.052 ms at
0 ms configured delay to 103.182 ms at 100 ms, while all ten reports retained
complete trace rate 1.0. With the same provisional 30 ms target, guided reached
the target in trial 1 and random in trial 3; their best p95 values were
1.052 ms and 26.040 ms. The retained summary is
`data/processed/optimization/development/f4_search_20260717_01/summary.json`
with SHA-256
`5d4839d7757c774b64b1b724098fc62d7e2386de036c6b1341e27a6b88bfd12d`.
This cross-workload repetition supports pipeline generality only. It remains
development evidence and does not turn the injected delay parameter into a
real production tuning recommendation.

The first real Executor action uses `executor_threads=1..4` while retaining the
same 100 Hz input and 20 ms CPU-bound contention callback. The planner assigns
the frame subscription and contention timer to separate callback groups and
uses a `MultiThreadedExecutor` above one thread. In the retained development
run, one thread had the lowest dispatch-upper-bound p95 at 19.500 ms; two,
three, and four threads measured 90.620, 97.002, and 94.441 ms. This negative
result is consistent with Python GIL contention for CPU-bound callbacks. The
validator rejects the two-thread candidate with improvement ratio -3.647 and
emits `restore_baseline` for the one-thread configuration. The summary is kept
at `data/processed/optimization/development/f2_executor_threads_20260717_03/summary.json`
with SHA-256
`2746dbeec7f960155e483baa5389d72e46329da9a095a602fc41cb3c16300674`.
It does not support a general claim that single-thread executors outperform
multi-thread executors; the result is specific to this Python CPU-bound
workload and motivates a later C++ or process-isolated comparison.
