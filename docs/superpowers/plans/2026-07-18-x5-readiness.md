# X5 Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RoboTraceOpt ready to deploy, qualify, demonstrate, and collect honest physical CAN evidence on an RDK X5 once the hardware is connected.

**Architecture:** Extend the existing capability and F6 SocketCAN paths instead of creating a second experiment framework. Keep physical CAN outside the frozen core matrix, fail closed on evidence classification, and use thin standard-library CLI wrappers for deployment, demonstration, and reporting.

**Tech Stack:** Bash, Python 3 standard library, Linux SocketCAN/can-utils, ROS 2 Humble, existing RoboTraceOpt experiment modules.

---

### Task 1: X5 Bootstrap and Read-Only Preflight

**Files:**
- Create: `scripts/bootstrap_x5.sh`
- Create: `scripts/preflight_x5.py`
- Create: `tests/environment/test_x5_preflight.py`
- Create: `tests/tools/test_bootstrap_x5.py`

- [ ] Write tests that require `evaluate_x5_readiness()` to reject WSL, x86, non-Humble ROS, a dirty Git worktree, and missing physical CAN peers while accepting an Ubuntu 22.04/aarch64/Humble clean report in software-only mode.
- [ ] Run `python -m pytest tests/environment/test_x5_preflight.py -q` and confirm import or assertion failures because the preflight module does not exist.
- [ ] Implement `scripts/preflight_x5.py` as a standard-library wrapper over `collect_capabilities()`. Add `--mode software|physical-can`, `--runtime-interface`, `--peer-interface`, `--bitrate`, JSON/Markdown outputs, and exit status 2 for blocked readiness.
- [ ] Re-run the preflight tests and confirm they pass.
- [ ] Write a subprocess test that requires `bash scripts/bootstrap_x5.sh --dry-run` to print the fixed apt package plan without executing `apt-get`.
- [ ] Run the bootstrap test and confirm failure because the script is absent.
- [ ] Implement an idempotent `--dry-run`/`--apply` bootstrap for Ubuntu 22.04. Install only build, ROS development, tracing, eBPF, CAN, scheduling, LLVM, and diagnostic packages; do not alter bootloader or kernel command line settings.
- [ ] Run the bootstrap test and `bash -n scripts/bootstrap_x5.sh`.
- [ ] Commit with `git commit -m "feat: add X5 bootstrap and preflight"`.

### Task 2: Physical SocketCAN Evidence Path

**Files:**
- Create: `experiments/physical_can/__init__.py`
- Create: `experiments/physical_can/interfaces.py`
- Modify: `experiments/fault_injection/fault_catalog.json`
- Modify: `experiments/fault_injection/registry.py`
- Modify: `experiments/fault_injection/runner.py`
- Modify: `experiments/fault_injection/socketcan_capture.py`
- Modify: `scripts/run_fault_condition.py`
- Modify: `diagnosis/adapters/socketcan_ack_lifecycle_adapter.py`
- Create: `experiments/fault_injection/compare_f6_physical_ack.py`
- Modify/Create tests under `tests/environment`, `tests/fault_injection`, and `tests/adapters`.

- [ ] Write interface tests for two distinct UP `info_kind=can` records with a matching bitrate. Cover vcan rejection, duplicate interface rejection, missing bitrate, down links, and bus-off state.
- [ ] Run the focused tests and confirm expected missing-module failures.
- [ ] Implement link classification and read-only `ip -details -json link` capture in `experiments/physical_can/interfaces.py`.
- [ ] Re-run the interface tests.
- [ ] Write registry and runner tests for `--f6-transport-profile physical`, default `can0/can1`, explicit interface/bitrate overrides, and development-only restriction.
- [ ] Run them and confirm the profile is currently rejected.
- [ ] Add the physical F6 profile and CLI plumbing while preserving mock and vcan behavior.
- [ ] Write capture tests requiring separate runtime/responder link snapshots, `virtual_can_bus=false`, `physical_can_evidence=true`, and a v2 manifest. Confirm a virtual or mismatched link cannot make that claim.
- [ ] Run them and confirm failure against the vcan-only capture implementation.
- [ ] Generalize the existing lifecycle owner to capture on the peer interface and validate both links. Preserve v1 vcan manifests and emit v2 for physical CAN.
- [ ] Write adapter and comparison tests that match runtime events on `can0` with peer responder/candump records on `can1`, propagate physical flags, retain development-only status, and reject mixed vcan/physical reports.
- [ ] Run them and confirm physical evidence is currently rejected.
- [ ] Generalize the adapter and add `compare_f6_physical_ack.py` without weakening the vcan validators.
- [ ] Run all F6, adapter, registry, and protocol tests.
- [ ] Commit with `git commit -m "feat: capture physical SocketCAN evidence"`.

### Task 3: Deterministic Defense Demonstration

**Files:**
- Create: `scripts/run_x5_demo.py`
- Create: `tests/tools/test_x5_demo.py`

- [ ] Write tests for a deterministic dry-run plan containing preflight, control, injected, two adapter commands, physical comparison, and report generation. Require unique output paths and `development_only=true`.
- [ ] Run the test and confirm failure because the entry point is absent.
- [ ] Implement a thin orchestration CLI with `--dry-run` and `--execute`. Do not shell-compose unquoted commands; invoke subprocess argument vectors. Stop on the first failed stage and write a retained `demo_summary.json` with stage status.
- [ ] Re-run the dry-run and failure-retention tests.
- [ ] Commit with `git commit -m "feat: add deterministic X5 defense demo"`.

### Task 4: Evidence-Only Report Projection and Runbook

**Files:**
- Create: `reporting/__init__.py`
- Create: `reporting/experiment_report.py`
- Create: `scripts/generate_experiment_report.py`
- Create: `tests/reporting/test_experiment_report.py`
- Create: `docs/hardware/X5_RUNBOOK.md`
- Modify: `README.md`

- [ ] Write report tests that discover JSON artifacts, retain failed runs, extract only existing scalar metrics, show unavailable values explicitly, and emit deterministic JSON/Markdown/CSV without recomputing measurements.
- [ ] Run the tests and confirm missing-module failures.
- [ ] Implement the artifact projection with `json`, `csv`, and `pathlib` only. Refuse symlinked inputs and output paths inside the source evidence tree when they would overwrite an input.
- [ ] Re-run report tests.
- [ ] Document wiring, bootstrap, software preflight, CAN link setup, dry-run, pilot, held-out experiment, demonstration, recovery, and recorded-video fallback commands.
- [ ] Add concise README entry points and explicit evidence boundaries.
- [ ] Run `ruff check`, `ruff format --check`, `compileall`, shell syntax checks, Python suites, ROS package tests where available, and the existing smoke workloads.
- [ ] Commit with `git commit -m "docs: add X5 experiment and defense runbook"`.

### Task 5: Integration and Publication

- [ ] Confirm `git diff --check`, a clean worktree, and no manuscript/PDF/ZIP files in commits.
- [ ] Review the branch diff against the design and evidence rules.
- [ ] Push `feat/x5-readiness` to `origin`.
- [ ] Report the exact tests run and list the X5-only acceptance checks that remain blocked until hardware is connected.
