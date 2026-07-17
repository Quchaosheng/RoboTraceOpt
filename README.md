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
source ~/.cache/robotracert_fusion_build/install/setup.bash
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
  tests.optimizer.test_diagnosis_gate -q
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
