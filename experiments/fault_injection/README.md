# Diagnosis fault injection

The catalog freezes F1-F6 identities, target root causes, independent oracle
mechanisms, required capabilities, and current implementation status.

Current executable conditions:

- F1 application compute delay on W1. The planner uses a busy-compute loop,
  not sleep, and records the selected delay mode in RuntimeEvent metadata.
- F2 executor queueing on W1. A busy timer occupies the planner's default
  single-thread executor while the measured planner callback has zero work;
  the runner requires and captures ros2_tracing CTF evidence. On Humble 4.1.2,
  the Python planner does not emit callback start/end tracepoints, so the
  reported metric is a publish-to-callback dispatch upper bound that includes
  DDS transfer, not a pure executor queue-residence measurement.
- F3 same-CPU scheduling pressure on W1. Development runs pin the ROS launch
  tree and a controlled `stress-ng` worker to one CPU. Calibration/test still
  require identity-comparable eBPF scheduling evidence and remain blocked on
  WSL.
- F4 blocking syscall/I/O on W2. Formal execution requires an
  identity-comparable eBPF platform, so WSL is rejected.
- F5 DDS/QoS pressure on W1. Matched development variants carry a 256 KiB
  payload at 100 Hz with reliable keep-last QoS and change only the camera
  publisher/subscriber history depth from 1 to 10. F5 is rejected outside the
  development partition until its evidence profile is frozen.
- F6 CAN/ACK retry exhaustion on W1. The existing mock ACK path is sufficient
  for a RuntimeEvent development smoke and later ros2_tracing collection.

F3 formal scheduling evidence requires an identity-comparable eBPF platform.
WSL output is restricted to development proxy characterization.

The retained F4 development comparison uses the serially executed pair `_02`
from commit `f9ed1a3`. The injected condition configured a 100 ms
`clock_nanosleep` delay and produced 35/35 complete service lifecycles; the
zero-delay control produced 37/37. Server processing elapsed median was
107.861 ms versus 0.0166 ms, an absolute increase of 107.845 ms. The full
request-to-response median absolute increase was 108.172 ms. The comparison is
stored at
`data/processed/diagnosis/development/f4_matched_20260717_02/comparison.json`.
RuntimeEvent SHA-256 values are `79a7ef0f2d3739574635a7c4da3000d080c375e67a5ce32f4f81a8b3ac7283a1`
(injected) and `fe9aac4d3bb20a813a9ddea6631f66c00377979102e032a26c634a2c49d79fb4`
(control); report hashes are `de178642a64bb2e41653ab031dec11fa03bd54e1a8f1cd4bfd7666fa3358a0e9`,
`66374460374f3f985d6b6fb8ccd17ca6213b1303959af734464e0ef605a66985`, and
comparison hash `d2c1c0b5a12ffbd36d5bda5c0229b7acee9dd3e32050d47e3d9d05180186cc09`.
The adapter accepts two distinct server PIDs as one duplicated ROS service
execution and selects the lower PID deterministically; duplicate stages on one
PID remain invalid. A parallel pair was rejected because the two ROS graphs
cross-talked and mixed 100 ms/0 ms metadata. All F4 reports remain
development-only with `formal_syscall_attribution=false` and
`ebpf_evidence=false`.

The retained F2 development comparison uses injected/control pair `_07` and is
written to
`data/processed/diagnosis/development/f2_matched_20260717_07/comparison.json`.
It contains 525 injected and 655 control pairs. The median and p95 ratios are
28.29 and 43.73, while the control p99 is higher because its observed tail is
retained. This bundle is development-only and cannot enter calibration or test
metrics.

The retained F5 development comparison uses pair `_01` from commit `f2735dd`.
Depth 1/1 reduced pairing rate from 0.95070 to 0.92094 and produced 81 received
sequence gaps versus 37 at depth 10/10. Median publish-to-receive upper-bound
latency was effectively unchanged, while depth 1 had lower p95/p99 values.
This is a delivery-completeness versus stale-latency trade-off, not evidence of
a pure DDS delay increase. The pair remains outside calibration and test.

The retained F3 development comparison uses pair `_04` from commit `4970205`.
Both variants pin the ROS process tree to CPU 31; injected additionally pins a
90% `stress-ng matrixprod` worker to that CPU. Complete proxy traces fell from
496/687 in control to 53/601 under pressure. The dispatch upper-bound median
ratio is 1.06, while p90/p95/p99 ratios are 107.96/155.35/158.91. The
zero-work callback elapsed distribution did not increase, so this result is
reported as a tail dispatch and completeness effect rather than callback
execution slowdown. The comparison is stored at
`data/processed/diagnosis/development/f3_matched_20260717_04/comparison.json`.
It is a WSL development proxy and is not admitted as formal scheduling
attribution.

The retained F1 development comparison uses pair `_02` from commit `085935c`.
Both variants use the same 4 Hz W1 profile and busy-compute mode; only the
configured delay changes from 0 to 100 ms. Each report contains 29 complete
planner traces. Median planner processing elapsed time increased from 0.076 ms
to 100.135 ms, an absolute increase of 100.059 ms. The 1318.62 median ratio is
reported only as a secondary statistic because the control interval is close
to zero. This metric is a RuntimeEvent elapsed interval, not CPU time. The
comparison is stored at
`data/processed/diagnosis/development/f1_matched_20260717_02/comparison.json`
and remains outside calibration and test.

The retained F6 development comparison uses pair `_03` from commit `4d1a60d`.
The injected drop condition produced 28/28 retry-exhausted terminals, each
with three attempts, three timeouts, and two scheduled retries. The success
control produced 30/30 ACK-received terminals with no retries. Median
retry-exhausted latency was 94.798 ms and median control ACK latency was
5.127 ms; they are separate terminal-state strata and are not divided into an
artificial ratio. The comparison is stored at
`data/processed/diagnosis/development/f6_matched_20260717_03/comparison.json`.
This is mock ACK lifecycle evidence with `physical_can_evidence=false`, not
SocketCAN or physical CAN evidence.

## F6 vcan responder

The matched vcan extension uses the same responder executable in both
conditions. Only `--policy` changes between `drop` and `echo`; both use the
same interface, ACK offset, and 5 ms decision delay.

```bash
python3 -m experiments.fault_injection.socketcan_responder \
  --interface vcan0 \
  --policy echo \
  --ack-can-id-offset 128 \
  --delay-ms 5 \
  --session-id f6_vcan_control_001 \
  --output-jsonl /tmp/f6_vcan_control_responder.jsonl
```

The responder observes standard command IDs `0x100..0x17f`. Echo ACKs use the
command ID plus 128 and preserve the payload byte-for-byte. Each JSONL record
contains the session, policy, interface, decision, frame identity, and both
monotonic and realtime timestamps. This is Linux SocketCAN/vcan evidence only;
it sets no physical-controller, transceiver, wiring, arbitration, or bus-error
claim.

The retained matched vcan development pair is `_02` from commit `66f6a76`.
After removing each condition's output path, the 15 ROS launch arguments are
identical. Both reports contain 29 valid terminal traces with 1.0 terminal,
command-frame, and responder coverage. Injected/drop contains 87 command
attempts and 29/29 retry-exhausted terminals; control/echo contains 29 command
attempts, 29 matching ACK frames, and 29/29 ACK-received terminals. Median
terminal latency is 91.736 ms for retry exhaustion and 5.116 ms for ACK
success. These are different terminal strata, so the comparator leaves both
cross-condition latency comparisons `null`.

The comparison is stored at
`data/processed/diagnosis/development/f6_vcan_matched_20260717_02/comparison.json`
with SHA-256
`f3d8fbc78664359d88667cb534e8a4ca773c35dcda7226641066af2be9768b5b`.
This is development-only Linux SocketCAN/vcan evidence with
`virtual_can_bus=true` and `physical_can_evidence=false`.

Prepare a blinded F6 bundle without starting ROS 2:

```bash
python3 scripts/run_fault_condition.py \
  --fault-id F6 \
  --dataset-role calibration \
  --case-id diagnosis_f6_injected \
  --qualification-report data/raw/diagnosis/calibration/session_f6_001/qualification.json \
  --session-id session_f6_001 \
  --condition-id condition_opaque_001 \
  --output-dir data/raw/diagnosis/calibration/session_f6_001/condition_opaque_001 \
  --capability ros2_runtime \
  --capability runtime_event
```

Calibration and test children must receive the matching qualification report
created by `scripts/run_formal_experiment_session.py`; capability flags alone
are accepted only for development runs. Control variants and F5 remain
development-only until their profiles are frozen.

Add `--execute --duration-seconds 8` to launch the condition. The output
directory contains separate public, oracle, command, runtime-event, launch-log,
and summary files. Reusing an existing bundle path is rejected.
Use `--dataset-role development` for smoke runs; the diagnosis evaluator
accepts only calibration/test labels, so development data cannot enter formal
metrics.

Check:

```bash
python3 -m unittest tests.fault_injection.test_fault_registry -v
bash -n scripts/*.sh
```
