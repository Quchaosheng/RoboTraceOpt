# diagnosis

Typed evidence graph rules and checks are documented in
`docs/fusion/TYPED_EVIDENCE_GRAPH.md`.
Calibration-gated inference and abstention are documented in
`docs/fusion/DIAGNOSIS_INFERENCE.md`.
Held-out metric semantics and partition isolation are documented in
`docs/fusion/DIAGNOSIS_EVALUATION.md`.

本目录承载统一证据、Trace-Stage 关联、证据图诊断和后续优化输入。当前只完成与 RuntimeEvent v2 相关的基础模块：

- `schema/normalized_event.py`：来源无关的 `NormalizedEvent`；
- `adapters/runtime_event_adapter.py`：正式 RuntimeEvent v2 -> NormalizedEvent；
- `adapters/tracetools_adapter.py`：导出的 ros2_tracing CTF fixture -> NormalizedEvent；
- `adapters/legacy_runtime_event_adapter.py`：旧 RuntimeEvent JSON -> v2 日志形状；
- `adapters/errors.py`：带 `reason_code` 的适配拒绝异常。

## Run

正式 v2 日志：

```bash
python3 -m diagnosis.adapters.runtime_event_adapter \
  --input data/raw/smoke/w1/runtime_events.jsonl \
  --output data/processed/smoke/w1_normalized.jsonl
```

旧日志先显式适配：

```bash
python3 -m diagnosis.adapters.legacy_runtime_event_adapter \
  --input old_runtime_events.jsonl \
  --output adapted_runtime_events_v2.jsonl
```

ros2_tracing fixture：

```bash
python3 -m diagnosis.adapters.tracetools_adapter \
  --input tests/fixtures/tracetools/w1_ros2_events.jsonl \
  --output data/processed/smoke/w1_ros2_normalized.jsonl
```

## F5 DDS Pressure Evidence

`diagnosis.adapters.dds_pressure_adapter` validates camera/planner process
identity and traced `/camera/frame` endpoint depths before deriving
publish-to-receive upper bounds. The bounds explicitly include executor wait;
they are not pure DDS transfer timestamps. The report retains endpoint
missingness and received sequence gaps.

## F3 Scheduling Pressure Proxies

`diagnosis.adapters.scheduling_pressure_adapter` validates the F3 oracle,
process manifest, same-CPU scheduler manifest, and stressor lifecycle before
deriving three RuntimeEvent timing proxies. These records explicitly set
`formal_scheduling_attribution=false` and are not admitted as eBPF scheduling
intervals.

## F1 Application Compute Delay Evidence

`diagnosis.adapters.application_compute_delay_adapter` validates the blinded
run manifest and F1 oracle before pairing planner start/end RuntimeEvents. Its
primary metric is a planner processing elapsed interval measured by
RuntimeEvent timestamps; it is not CPU time. The secondary camera-to-planner
publish interval includes transport and callback dispatch. F1 matched reports
are development-only and cannot enter formal inference.

## F6 Mock ACK Lifecycle Evidence

`diagnosis.adapters.mock_ack_lifecycle_adapter` reconstructs ACK wait,
timeout, retry, and terminal sequences from RuntimeEvent and validates each
event's `extra_json` against the F6 oracle. It reports application-level mock
ACK success and retry exhaustion only. Every output explicitly sets
`physical_can_evidence=false`; SocketCAN and physical CAN require separate
evidence strata.

## F6 SocketCAN/vcan ACK Lifecycle Evidence

`diagnosis.adapters.socketcan_ack_lifecycle_adapter` reconstructs the same F6
retry and terminal contract while requiring independent RuntimeEvent,
responder JSONL, and candump matches for every command attempt. RuntimeEvent is
the source of trace identity and terminal state. Responder monotonic time is
used only for bounded same-host ordering; candump realtime timestamps preserve
capture order and are never subtracted from RuntimeEvent monotonic timestamps.

The adapter rejects mock profiles, physical-CAN claims, payload/ID mismatch,
unexpected ACKs under drop, and terminal states that contradict the blinded
condition variant. Outputs set `socketcan_evidence=true`,
`virtual_can_bus=true`, and `physical_can_evidence=false`.

## F4 Service Blocking-Delay Evidence

`diagnosis.adapters.service_blocking_delay_adapter` validates the W2
`query_sent`, server processing start/end, and `response_received` lifecycle.
It derives server processing and request/response elapsed intervals from
RuntimeEvent while preserving incomplete and invalid trace reasons. Client
events are validated by payload identity; only server start/end events are
required to carry the configured delay metadata.

This first F4 evidence stratum is a development proxy. It explicitly sets
`formal_syscall_attribution=false` and `ebpf_evidence=false`; the server
interval is elapsed time around the configured blocking operation, not CPU
time or kernel syscall attribution.

## Check

```bash
python3 -m unittest tests.adapters.test_runtime_event_adapter -v
python3 -m unittest tests.schema.test_legacy_runtime_event_adapter -v
python3 -m unittest tests.adapters.test_tracetools_adapter -v
python3 -m unittest tests.adapters.test_dds_pressure_adapter -v
python3 -m unittest tests.adapters.test_scheduling_pressure_adapter -v
python3 -m unittest tests.adapters.test_application_compute_delay_adapter -v
python3 -m unittest tests.adapters.test_mock_ack_lifecycle_adapter -v
python3 -m unittest tests.adapters.test_socketcan_ack_lifecycle_adapter -v
python3 -m unittest tests.adapters.test_service_blocking_delay_adapter -v
```

## 边界

- `oracle_id` 不属于 `NormalizedEvent`，正式 adapter 不读取它；
- `clock_id=unknown`、PID/TID 非正数、未知 host 和损坏 JSON 均拒绝进入正式证据流；
- 每个接受事件保留 adapter 名、源文件和原始行号；
- 当前没有实现 eBPF、CAN ACK adapter，也没有实现关联或诊断。tracetools adapter 不会提前填写 trace/stage。
