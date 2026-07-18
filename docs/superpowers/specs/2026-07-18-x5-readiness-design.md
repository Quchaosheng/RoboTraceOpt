# X5 Readiness and Physical CAN Design

## Objective

Prepare RoboTraceOpt so that an RDK X5 can be connected later and used through
one documented workflow for platform qualification, physical CAN evidence,
formal experiments, and a short defense demonstration. Development runs must
remain clearly separated from formal hardware evidence.

## Considered Approaches

1. Add only an installation checklist. This is small, but leaves interface
   validation, evidence provenance, and the defense workflow manual.
2. Add command-line preflight, physical CAN capture, demonstration orchestration,
   and report generation using the existing Python and shell patterns. This is
   the selected approach because it closes the workflow without a new runtime
   dependency or a separate UI.
3. Build a browser dashboard and remote deployment service. This adds maintenance
   and failure modes without improving the validity of the thesis evidence.

## Scope

### X5 bootstrap and preflight

A bootstrap shell script installs the ordinary Ubuntu/ROS tooling that can be
installed non-interactively and prints manual actions for kernel or ROS packages
that cannot be inferred safely. It does not change kernel boot parameters.

A read-only preflight command records OS, architecture, ROS distribution, Git
identity, BTF/eBPF readiness, tracing readiness, thermal sensors, and SocketCAN
interfaces. It produces JSON and Markdown. Formal readiness requires native
Linux, `aarch64`, ROS 2 Humble, a clean matching Git commit, and all capabilities
required by the selected experiment matrix.

### Physical CAN evidence

The existing SocketCAN responder and capture logic will be reused. A physical
CAN runner will require two distinct interfaces, normally `can0` for the runtime
and `can1` for the ACK/fault peer. Before capture it will verify that both links
exist, are up, are CAN devices, use the requested bitrate, and are not `vcan`.

The runner records interface metadata before and after each run, command and ACK
frames, monotonic timestamps, requested fault policy, process outcomes, and file
hashes. Only this path may emit `physical_can_evidence=true`. A missing interface,
virtual interface, bitrate mismatch, capture failure, or incomplete manifest
produces a retained failed run and never falls back to simulated evidence.

The first formal cross-layer matrix remains unchanged. Physical CAN is an
additional F6 experiment set so an unavailable adapter cannot invalidate the
core X5 diagnosis matrix.

### Defense demonstration

A single command will run a short deterministic sequence:

1. preflight and show the evidence level;
2. capture a normal CAN ACK condition;
3. capture a deterministic dropped-ACK condition;
4. run diagnosis and the selected optimization comparison;
5. generate a compact Markdown summary and machine-readable JSON.

The command supports `--dry-run` on the development machine. It refuses to label
dry-run, vcan, or mock output as physical evidence. It also writes the exact
commands to a runbook so the demonstration can be rehearsed or recorded.

### Report generation

The report generator consumes existing session and comparison artifacts. It
does not recompute or invent missing measurements. It reports run counts,
failures, completeness, latency quantiles already present in source artifacts,
paired improvement estimates, confidence intervals, and provenance. Missing
fields are shown as unavailable. Outputs are JSON, Markdown, and flat CSV files
suited to thesis plotting.

## Component Boundaries

- `scripts/bootstrap_x5.sh`: idempotent package preparation only.
- `scripts/preflight_x5.py`: read-only collection and readiness decision.
- `experiments/physical_can/`: interface validation, capture orchestration, and
  physical evidence manifests.
- `scripts/run_x5_demo.py`: thin orchestration over existing commands.
- `scripts/generate_experiment_report.py`: artifact-only report projection.
- `docs/hardware/`: wiring, deployment, pilot, formal run, and defense runbook.

All Python components use the standard library and existing repository modules.
No dashboard, database, or remote agent is introduced.

## Failure and Integrity Rules

- Commands fail closed for formal or physical claims.
- Failed and interrupted runs are retained under unique output directories.
- Existing files are never overwritten unless an explicit empty output directory
  is provided.
- Every accepted physical run ends with a manifest containing SHA-256 hashes.
- Git commit and dirty-state provenance are recorded in every report.
- Development summaries carry a visible `development_only` status.

## Testing

Unit tests use recorded `ip -details -json link` fixtures and temporary artifact
directories. They cover real CAN versus vcan classification, distinct-interface
requirements, missing metadata, manifest hashing, dry-run command construction,
and report handling of failed or incomplete trials. Shell scripts receive syntax
checks. Existing Python, Ruff, compile, ROS package, and smoke suites remain the
regression gate.

Native X5 acceptance is intentionally deferred until hardware is connected. It
requires Ubuntu 22.04/ROS 2 Humble build, eBPF and tracing smoke tests, two
physical CAN interfaces, a pilot run, and a held-out formal run.
