# NormalizedEvent 统一证据模型

记录日期：2026-07-15

## 字段语义

| 字段 | 说明 |
|---|---|
| `event_id` | adapter 生成的稳定事件身份；RuntimeEvent 使用源文件与行号组成 |
| `source` | 证据来源类型，当前支持 `runtime_event`、`ros2_tracing` |
| `event_type` | 来源无关的事件语义；RuntimeEvent 映射为原 `event_name` |
| `timestamp_ns`、`clock_id` | 带显式时钟域的时间戳 |
| `trace_id`、`sequence_id`、`stage` | 业务 trace 与阶段身份 |
| `pid`、`tid`、`host_id` | 跨层关联身份 |
| `attributes` | 来源特有属性，不参与模型字段伪装 |
| `provenance` | adapter、源文件和原始记录行号 |

`oracle_id` 不在模型中。测试通过改变输入 `oracle_id` 并比较完整输出，验证它不能影响正式归一化结果。

## RuntimeEvent v2 映射

- `source = runtime_event`；
- `event_type = RuntimeEvent.event_name`；
- 原 `event_type`、`source_node`、`duration_ns`、`status`、`reason_code` 和解析后的 `extra_json` 放入 `attributes`；
- `provenance.adapter = runtime_event_v2`；
- 缺字段、未知时钟、无效运行身份或非法 `extra_json` 通过 `AdapterReject.reason_code` 显式拒绝。

当前接受的已知时钟域为 `monotonic`、`realtime` 和 `tai`。是否能合并仍需后续时钟校准模块判断；“已知名称”不等于“已经完成校准”。

## ros2_tracing 映射

tracetools adapter 使用 CTF raw monotonic clock value 和 frequency 计算 `timestamp_ns`，把 `ns_from_origin` 与 offset 留在 attributes 中。PID/TID 来自 LTTng `vpid/vtid` context。由于 adapter 阶段尚未执行关联，输出的 `trace_id` 与 `stage` 为空，后续算法必须给出接受、拒绝或未匹配原因，不能按最近时间戳强行填充。

## 实测

2026-07-15 将 W1 v2 smoke 的 654 行 RuntimeEvent 全量转换为 654 行 NormalizedEvent。首条输出保留 `source_file` 与 `record_index=1`，不含 `oracle_id`。转换结果位于 Git 忽略的 `data/processed/smoke/w1_normalized.jsonl`，仅作工程 smoke。

## 下一步

同一模型将由 tracetools、eBPF 和 CAN ACK adapter 输出。只有各 adapter 均保留原始 provenance 并通过 fixture 后，才开始 Trace-Stage 关联。
