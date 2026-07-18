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

The first real QoS action sweep used a 100 Hz camera stream, 256 KiB payloads,
reliable delivery, and `frame_qos_depth=1,2,4,6,8,10` at commit `a000347`.
The corresponding publish-to-receive p95 values were 1.041, 1.096, 1.015,
1.310, 0.984, and 0.829 ms. Complete-trace rates were 0.9542, 0.9495,
0.9600, 0.9358, 0.9477, and 0.9488. The depth-10 baseline had the lowest
p95. Depth 8 was the closest nonbaseline setting, but its p95 was 18.7%
higher and its complete-trace rate was lower by 0.0011. The validator rejected
that candidate and emitted `restore_baseline`. Depth 4 had the highest
complete-trace rate, but its p95 was 22.4% higher than the baseline. The
retained summary is
`data/processed/optimization/development/qos_depth_20260717_01/summary.json`
with SHA-256
`6a94e037b5a73b93638280f4b93d937c2b9930d3dbc13e63047bc48a68b04947`.
This single WSL development sweep does not support a general QoS depth
recommendation. Repeated runs with randomized order and native Linux are
still required.

The closed-loop runner connects a diagnosis report to the existing gate,
constrained trial planner, runtime trial reports, candidate validator, and
rollback decision. A baseline profile is supplied as a JSON file so its cause,
configuration, path, and SHA-256 remain auditable. The runner executes the
baseline once, skips duplicate or inapplicable candidates, evaluates the
remaining candidates serially, and writes `decision.json` without changing a
live system.

```bash
python3 scripts/run_closed_loop_optimization.py \
  --diagnosis-report tests/fixtures/optimizer/diagnosis_executor_queueing.json \
  --baseline-profile tests/fixtures/optimizer/baseline_executor_threads.json \
  --strategy guided \
  --budget 4 \
  --seed 20260718 \
  --duration-seconds 8 \
  --minimum-confidence 0.6 \
  --output-dir data/raw/optimization/development/executor_closed_loop_20260718_02
```

The retained Executor closed-loop run at commit `9defdc1` validated all three
nonbaseline candidates. Its p95 dispatch upper bound was 19.283 ms for the
one-thread baseline and 51.571, 60.551, and 67.635 ms for two, three, and four
threads. The decision therefore rejected every candidate and restored
`executor_threads=1`. The summary SHA-256 is
`f5020ba649bbde56f1de8a5359822f2bf056eb6e66f3e2e2767eaca613e86619`;
the decision SHA-256 is
`7ed2c5ffef0936e29f3993bfca3e1fdfde02f07005acd60fe060bba957ac2ed9`.
An earlier `_01` run is retained locally as invalid development evidence: its
ROS build cache still referred to another worktree, so the requested candidate
thread counts did not reach the installed launch file and no candidate report
was accepted.

The retained QoS closed-loop run used the same commit and seed. Its depth-10
baseline measured 0.811 ms p95, while depths 1, 4, and 7 measured 0.901, 0.939,
and 0.904 ms. All candidate reports were valid, but none improved the primary
objective, so the decision restored `frame_qos_depth=10`. The summary SHA-256
is `f8fb0dcd3912b821268345b6cd7cc20aa1a5e19d35204a5b9df71355fa63a45e`;
the decision SHA-256 is
`3a191c0af627744756701b6bd8198c49ca2889a64ea137830750a8062292ea35`.
Both runs are development-only WSL measurements, not general tuning claims.

The committed diagnosis fixtures are synthetic orchestration inputs. They
carry no oracle fields and do not provide diagnosis-accuracy evidence. The
runtime trials remain real development measurements. Diagnosed causes without
an executable runtime profile are denied before any ROS process starts.

## Repeated pilot campaigns

The repeated campaign runner evaluates whether a single-run decision remains
supported across balanced repeats. Each block contains the baseline and every
unique candidate once. A seeded initial permutation is cyclically rotated so
that no configuration is permanently assigned to the cold-start or final
position. Candidate comparisons use only the baseline measured in the same
block.

The validator bootstraps the median paired improvement ratio and complete-trace
rate delta with the Python standard library. A candidate is accepted only when
all planned pairs succeed, the latency-improvement confidence lower bound
meets the frozen threshold, and the completeness-delta lower bound does not
cross its allowed regression threshold. Failed and invalid trials remain in
the campaign and prevent acceptance; the runner never retries or replaces
them.

Run the five-block Executor pilot:

```bash
python3 scripts/run_repeated_optimization_campaign.py \
  --diagnosis-report tests/fixtures/optimizer/diagnosis_executor_queueing.json \
  --baseline-profile tests/fixtures/optimizer/baseline_executor_threads.json \
  --campaign-name executor_repeated_20260718_01 \
  --strategy guided \
  --budget 4 \
  --seed 20260718 \
  --repetitions 5 \
  --duration-seconds 8 \
  --minimum-confidence 0.6 \
  --minimum-completeness 1.0 \
  --minimum-improvement-ratio 0.0 \
  --minimum-complete-trace-rate-delta 0.0 \
  --confidence-level 0.95 \
  --bootstrap-resamples 10000 \
  --output-dir data/raw/optimization/pilot/executor_repeated_20260718_01
```

Run the matching QoS pilot by using
`diagnosis_dds_communication_delay.json`, `baseline_qos_depth.json`, campaign
name `qos_repeated_20260718_01`, and output
`data/raw/optimization/pilot/qos_repeated_20260718_01` with the same seed,
budget, repetitions, duration, thresholds, and bootstrap settings.

The output freezes the schedule before execution and retains one terminal
record per planned trial:

```text
campaign_manifest.json
trials/block_NN/position_NN_cfg_HASH/{trial_report,trial_result}.json
candidate_validations/cfg_HASH.json
decision.json
summary.json
```

These commands always produce `dataset_role=pilot`, `development_only=true`,
and `formal_optimization_allowed=false`. WSL measurements are protocol and
variance checks, not formal superiority evidence. Native Linux and X5 use the
same CLI and schemas but must write separate datasets and environment
manifests; pilot and formal results must not be pooled.
