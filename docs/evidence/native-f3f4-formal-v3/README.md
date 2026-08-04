# RoboTraceOpt Native F3/F4 Formal Evidence V3

This package contains the compact, sanitized projection of the native Ubuntu
24.04 / ROS 2 Jazzy F3/F4 session executed on 2026-07-29. Raw CTF, ROS 2,
RuntimeEvent, and eBPF files are intentionally excluded.

The public projection retains aggregate `ebpf_events` counts in
`results/analysis_summary.*`, but not raw bpftrace output or per-event task
identity mappings. Those counts report non-zero collector output in the
qualified session; they do not independently establish scheduler- or
syscall-level causal attribution.

## Provenance

- Dataset role: `test`
- Formal experiment allowed: `true`
- Executed cases: `40/40 successful`
- Paired repetitions: `10` per control/injected condition
- Session seed: `20260729`
- Experiment commit: `384b21556d12e572ef8e490c1ab7cfef0c328203`
- Session integrity: `complete`
- Host class: native Linux, not WSL or a VM

The fixed session seed generated a balanced run order. Repetitions are paired
by their explicit repetition index; they are not described as independently
seeded trials.

## Main Results

| Fault | Evidence result | Control | Injected | Paired result |
|---|---|---:|---:|---:|
| F3 scheduling pressure | Complete lifecycle recovery | 95.30% | 67.56% | median difference -0.437; 95% bootstrap CI [-0.458, -0.017] |
| F4 service blocking | Request-response median | 0.875 ms | 101.212 ms | median difference +100.337 ms; 95% bootstrap CI [100.320, 100.350] ms |

F4 supports formal application-level blocking-delay inference. It does not
claim syscall-level causal attribution.

F3 is retained as scheduling-pressure evidence. Its complete-sample latency
medians are affected by missing and selected traces, and the response is
heterogeneous across repetitions. The defensible result is the reduction in
complete lifecycle recovery, not a claim that pressure improves latency or a
claim of scheduler-level causal attribution.

## Package Layout

- `metadata/`: sanitized environment, qualification, session, and integrity
  records.
- `results/`: aggregate metrics, run-level paired statistics, and scheduler
  analysis.
- `figures/`: thesis-ready SVG projections.
- `PACKAGE_MANIFEST.json`: source and public SHA-256 values for every projected
  artifact.
- `SHA256SUMS.txt`: checksums for the complete public package.

The source hashes in `PACKAGE_MANIFEST.json` refer to the retained private
artifacts before sanitization. Public hashes refer to the files in this
package. Local paths, usernames, and host identifiers have been replaced.

## Evidence Boundary

This package establishes native F3/F4 execution and the reported paired
measurements. It does not by itself establish multi-class diagnosis accuracy,
abstention performance, optimization benefit, ECU HIL behavior, or actuator
safety.
