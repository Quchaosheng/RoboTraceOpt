# RoboTraceOpt

RoboTraceOpt is a ROS 2 runtime analysis project for cross-layer tracing,
evidence-graph diagnosis, and diagnosis-guided configuration optimization in
robotic systems.

It combines application-level RuntimeEvent records with ROS 2 tracing and
Linux runtime evidence through explicit adapters. The diagnosis layer builds
typed evidence graphs, reports uncertainty instead of forcing a root-cause
label, and constrains optimization trials to actions that match the diagnosed
cause.

## What is included

- RuntimeEvent v2 instrumentation for three ROS 2 workloads.
- Adapters for RuntimeEvent, `ros2_tracing`, eBPF scheduling records, and
  SocketCAN/vcan ACK lifecycles.
- Topology-constrained trace-stage association and typed evidence graphs.
- Auditable root-cause inference with conflict handling and abstention.
- A bounded action registry and reproducible guided, random, and unguided
  search protocols.
- Candidate validation and offline rollback decisions.
- Balanced repeated campaigns with paired bootstrap confidence bounds.
- Development experiment runners for F1-F6 fault characterization.

## Repository layout

```text
ros2_core/     ROS 2 Humble packages and launch files
diagnosis/     evidence adapters, association, graph construction, inference
experiments/   fault catalog, controlled runners, matched comparisons
optimizer/     action constraints, search plans, objectives, validation
scripts/       build, capture, smoke, and experiment entry points
tests/         unit and contract tests
docs/          public schemas, environment notes, and migration references
```

## Environment

The primary development environment is Ubuntu 22.04 with ROS 2 Humble. The
core workspace can be built from WSL or native Ubuntu:

```bash
bash scripts/build_core.sh
source ~/.cache/robotraceopt_build/install/setup.bash
```

Run the migrated workloads:

```bash
bash scripts/run_smoke_workload.sh all 8
```

Run the Python test suite:

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest \
  tests.optimizer.test_action_registry \
  tests.optimizer.test_diagnosis_guided_sampler \
  tests.optimizer.test_runtime_objective \
  tests.optimizer.test_candidate_validator \
  tests.optimizer.test_rollback \
  tests.optimizer.test_trial_planner \
  tests.optimizer.test_runtime_trial \
  tests.optimizer.test_search_summary \
  tests.optimizer.test_diagnosis_gate \
  tests.optimizer.test_runtime_profiles \
  tests.optimizer.test_closed_loop \
  tests.optimizer.test_closed_loop_cli \
  tests.optimizer.test_campaign_schedule \
  tests.optimizer.test_paired_bootstrap \
  tests.optimizer.test_repeated_campaign_cli -q
```

## Evidence boundaries

Generated raw and processed experiment data is intentionally excluded from
Git. Development evidence is kept separate from calibration and held-out test
partitions. RuntimeEvent-only and vcan results are labeled as proxy evidence
and are not presented as formal syscall, scheduler, or physical CAN
attribution.

The repository contains implementation and public technical documentation
only. Private research documents and local experiment data are excluded.

## Project lineage

RoboTraceOpt consolidates engineering work from
[ROS2Probe](https://github.com/Quchaosheng/ROS2Probe) and
[RoboTraceRT](https://github.com/Quchaosheng/RoboTraceRT) into one maintained
codebase.
## Formal experiment readiness

The formal-session protocol freezes selected Chapter 6 cases before any ROS 2
process starts. Generate a read-only platform report after sourcing ROS 2 and
the built workspace:

```bash
python3 scripts/check_platform_capabilities.py \
  --label x86-wsl \
  --output-json data/raw/environment/x86-wsl.json
```

Current WSL development can rehearse only the cases whose reported
requirements are ready. This command writes a 42-run plan for F1, mock F6, and
the two optimization campaigns without starting a workload:

```bash
python3 scripts/run_formal_experiment_session.py \
  --matrix experiments/protocol/formal_experiment_matrix.json \
  --capability-report data/raw/environment/x86-wsl.json \
  --case diagnosis_f1_control \
  --case diagnosis_f1_injected \
  --case diagnosis_f6_control \
  --case diagnosis_f6_injected \
  --case optimization_executor \
  --case optimization_qos \
  --dataset-role pilot \
  --session-name readiness_dry_run_20260718_01 \
  --seed 20260718 \
  --output-dir data/raw/experiments/pilot/readiness_dry_run_20260718_01 \
  --dry-run
```

This dry-run does not contain measurement evidence. WSL is denied for
`calibration` and held-out `test` roles even when individual tools appear
available.

### Fault evidence commit point

A successful formal fault case writes `artifact_manifest.json` last. The
manifest names the required RuntimeEvent, run/oracle/command, identity,
tracing, eBPF, scheduler, and summary artifacts for that fault and records a
SHA-256 for every file or CTF directory. The outer session verifies this
manifest before accepting the case and revalidates its nested artifacts during
every integrity reconstruction. A missing or changed artifact makes the case
failed or the session invalid; it is preserved and is never silently replaced.

F3/F4 now invoke the eBPF collector during the workload window instead of only
checking that the tool is installed. Capture starts only when the live
`process-manifest/v2` reports `ebpf_identity_status=comparable`; the runner
does not match tasks by process name as a fallback. F2/F3/F5 perform a full ROS 2 trace export
after CTF capture, retaining every selected event rather
than the bounded sampling used by public fixtures.

This integration closes the evidence contract but does not establish X5 measurement results.
WSL dry-runs and synthetic tests remain readiness checks;
formal conclusions still require a qualified native Linux or X5 `test`
session with real artifacts.

On the actual X5, first generate a new report with `--label rdk-x5`. After the
report allows every selected requirement and Git is clean, the held-out entry
is:

```bash
python3 scripts/run_formal_experiment_session.py \
  --matrix experiments/protocol/formal_experiment_matrix.json \
  --capability-report data/raw/environment/rdk-x5.json \
  --dataset-role test \
  --session-name x5_test_01 \
  --seed 20260718 \
  --output-dir data/raw/experiments/test/x5_test_01
```

An interrupted session is continued with the same frozen arguments plus
`--resume`. Resume verifies the manifest sidecar, matrix, capability report,
Git commit, role, seed, and session name. Successful, failed, and interrupted
cases are terminal and are never rerun in place; a new measurement attempt
uses a new session name. Physical CAN is not part of this first formal matrix.
