# Archived Native F3/F4 Candidate Projection

> **Status:** not accepted as completed or formal evidence.

The directory name is retained for repository compatibility and audit history.
The files are a sanitized historical projection, not a currently qualified
native Ubuntu experiment package.

## What is retained

- Sanitized environment and session metadata.
- Aggregate candidate tables and figures.
- Package manifests and checksums for the public projection.
- Tooling inputs useful when designing a new qualification run.

## Why it is not qualified

The public projection excludes the raw CTF, ROS 2, RuntimeEvent,
bpftrace/eBPF, and per-event identity records required to independently verify
the platform, workload window, event attribution, completeness, and reported
statistics. Historical metadata labels cannot substitute for those artifacts.

Consequently, this directory does **not** establish:

- completed native Ubuntu or Native Linux execution;
- a completed control/injected F3/F4 matrix;
- scheduler- or syscall-level causal attribution;
- diagnosis accuracy, abstention quality, or optimization benefit;
- ECU/HIL, actuator, or functional-safety behavior.

## Allowed use

Use this directory only to inspect the packaging schema, integrity layout, and
requirements for a future rerun. Do not cite its archived counts, figures, or
metadata as experimental results.

A future native claim requires a new clean session with a frozen source
reference, environment report, raw event artifacts, identity mapping,
run-level outputs, manifests, and checksums that pass the current qualification
contract.
