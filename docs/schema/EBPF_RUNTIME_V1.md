# eBPF runtime event v1

`ebpf-runtime/v1` is the collector-to-adapter contract for Linux scheduling
and syscall evidence. Every record contains:

```text
schema_version, event_source, timestamp_ns, clock_id, host_id,
collector, collector_version
```

`clock_id` must be `monotonic` because the collector uses kernel ktime. The
adapter rejects other or unknown clock domains.

## Event records

`sched_switch` records add `prev_tid`, `prev_comm`, `prev_state`, `next_tid`,
`next_comm`, and `cpu_id`. Linux scheduler tracepoint `prev_pid` and
`next_pid` fields identify tasks, so the collector renames them to TIDs. The
adapter uses a process-manifest kernel-TID map and emits at most two events:
`sched_switch_out` for a target previous task and `sched_switch_in` for a
target next task.

`sched_wakeup` records add `tid`, `comm`, and `target_cpu`. A target event is
emitted only when the TID exists in the process manifest.

`syscall` records add `pid`, `tid`, `comm`, `syscall_id`, `syscall_name`,
`ret`, and `duration_ns`. PID/TID disagreement with the process manifest is a
hard `identity_mismatch` rejection.

Raw eBPF PID/TID fields are kernel-namespace identities. NormalizedEvent uses
the corresponding runtime PID/TID so it can be compared with RuntimeEvent.
The raw kernel identities remain in `attributes`. A process-manifest/v2 report
whose `ebpf_identity_status` is not `comparable` is rejected before capture or
normalization.

## Deliberate boundary

The adapter does not assign ROS trace or stage identities. It also does not
calculate off-CPU duration. A later evidence-graph step pairs
`sched_switch_out`, optional `sched_wakeup`, and `sched_switch_in` events for
the same TID inside a calibrated StageWindow. Raw records for non-target
tasks are filtered out rather than represented with invented process IDs.

Conversion command:

```bash
python3 -m diagnosis.adapters.ebpf_adapter \
  --input data/raw/ebpf/events.jsonl \
  --process-manifest data/raw/ebpf/process_manifest.json \
  --output data/processed/ebpf/normalized.jsonl
```
