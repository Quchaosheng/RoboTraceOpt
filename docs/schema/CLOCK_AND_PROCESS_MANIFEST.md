# Clock and process evidence contracts

## Clock calibration v1

`diagnosis.adapters.clock_calibration` compares two explicitly named clock
domains from paired offset and uncertainty samples. The report uses the median
sample as `estimated_offset_ns`. Its conservative residual bound is:

```text
max_error_ns = max(abs(sample_offset - estimated_offset) + sample_uncertainty)
```

A pair is `comparable` only when:

```text
abs(estimated_offset_ns) + max_error_ns <= tolerance_ns
```

Otherwise its status is `not_comparable` with reason code
`clock_error_over_tolerance`. Unknown clock names are rejected rather than
coerced. A distributed PC/RK3568 run must supply measurements from chrony,
PTP, or another recorded offset procedure; a local result must not be reused
as cross-host evidence.

The local smoke command brackets `clock_gettime(CLOCK_MONOTONIC)` with two
Python monotonic reads. It records the sample count, offset, error bound,
tolerance, hosts, method, and UTC measurement time:

```bash
python3 -m diagnosis.adapters.clock_calibration \
  --host-id "$(hostname)" \
  --sample-count 1000 \
  --tolerance-ns 100000 \
  --output data/raw/clock_calibration.json
```

## Process manifest v2

`scripts/capture_process_manifest.py` records live Linux identities from
`/proc`. Each record contains the ROS source node, resolved executable, PID,
the complete TID set visible at capture time, host, monotonic process start
time, and UTC process start time. The envelope contains the capture time and
repository version.

Version 2 also records `kernel_pid` and a `threads` list containing paired
runtime `tid` and `kernel_tid` values from `/proc/*/status` `NSpid`. This is
required because scheduler tracepoints report task IDs in the initial PID
namespace while RuntimeEvent reports IDs visible to the ROS process.

`ebpf_identity_status` is `comparable` only when this mapping is usable. WSL2
currently exposes a single-level `NSpid` even though scheduler tracepoints use
different global task IDs. Such runs are marked `not_comparable` with reason
`wsl_initial_pid_namespace_unavailable`; the eBPF adapter rejects them. Legacy
v1 manifests remain readable only when runtime and kernel IDs are the same.

`git_commit` identifies the checked-out commit. `git_dirty=true` means the run
also included uncommitted changes and therefore cannot be reproduced from the
commit alone. Missing processes, empty thread sets, invalid RuntimeEvent
identities, and conflicting node-to-PID mappings are hard failures.

For a live workload, identities can be derived from RuntimeEvent v2 records:

```bash
python3 scripts/capture_process_manifest.py \
  --runtime-events data/raw/smoke/w1/runtime_events.jsonl \
  --repo-root . \
  --output data/raw/process_manifest.json
```

The capture must run before the workload exits. `run_ros2_tracing_smoke.sh`
does this automatically and stores both reports under a session-specific
`data/raw/tracing/` directory.
