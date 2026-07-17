# eBPF capture status

Recorded on 2026-07-15 using Ubuntu 22.04 under WSL2, kernel
`6.18.33.2-microsoft-standard-WSL2`.

## Implemented path

`scripts/capture_ebpf_runtime.py` uses the Ubuntu `bpftrace` package and emits
`ebpf-runtime/v1` JSONL. It attaches `sched:sched_switch`,
`sched:sched_wakeup`, `raw_syscalls:sys_enter`, and
`raw_syscalls:sys_exit`. Syscalls are paired by kernel TID. The adapter emits
target switch-out, switch-in, wakeup, and syscall-interval events without
assigning ROS trace or stage identities.

## WSL2 result

A minimal three-second `sched_switch` program loaded successfully and counted
13,572 real switches. The complete four-probe program also passed the verifier
and attached. Development runs observed 455,818 raw lines in four seconds and
921,445 raw lines in eight seconds.

These raw lines are not a formal cross-layer fixture. WSL procfs reported the
ROS `can_bridge_node` as PID 445 while the scheduler tracepoint reported its
global task ID as 3541. `/proc/<pid>/status` exposed only a single `NSpid`, so
the mapping back to RuntimeEvent PID/TID could not be recovered. The current
WSL status is therefore:

```text
eBPF program loading: ready
cross-layer task identity: not_comparable
formal W1 eBPF fixture: blocked on native x86 or RK3568 run
```

The collector and adapter reject this condition instead of matching by
`comm` or emitting invented identities.

## Reproduction on a comparable host

Run W1 long enough to capture a live v2 process manifest, then invoke:

```bash
python3 scripts/capture_ebpf_runtime.py \
  --process-manifest data/raw/ebpf/process_manifest.json \
  --duration 5 \
  --output data/raw/ebpf/events.jsonl \
  --summary-output data/raw/ebpf/summary.json

python3 -m diagnosis.adapters.ebpf_adapter \
  --input data/raw/ebpf/events.jsonl \
  --process-manifest data/raw/ebpf/process_manifest.json \
  --output data/processed/ebpf/normalized.jsonl
```

The run is admissible only when the process manifest reports
`ebpf_identity_status=comparable`, the collector summary contains non-zero
events, and the adapter converts the frozen fixture without rejection.
