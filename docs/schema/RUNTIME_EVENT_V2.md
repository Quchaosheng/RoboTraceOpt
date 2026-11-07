# RuntimeEvent v2 契约

记录日期：2026-07-15

## 目的

RuntimeEvent v2 在应用语义事件中加入跨层关联所需的进程、线程、主机和时钟身份。当前字段仍是应用层证据，不单独证明 ROS 2 executor、DDS 或内核根因。

## 字段

JSONL 行使用**平铺**字段，不嵌套 `header` 对象。ROS 2 消息
（`ai_robot_runtime_interfaces/msg/RuntimeEvent.msg`）里这些字段挂在
`TraceHeader header` 之下，但 `runtime_event_logger_node.cpp::event_to_json_line`
把它们展开到顶层，adapter 也只读顶层。按消息定义写 `{"header": {...}}` 的记录会被
拒绝为 `missing_required_field`。

| 字段 | 含义 | 当前约束 |
|---|---|---|
| `trace_id` | 端到端业务 trace 身份 | 运行节点必须提供 |
| `oracle_id` | 独立实验真值 | 只供评测，不得用于正式关联/诊断/优化 |
| `sequence_id` | 来源内顺序身份 | 不单独作为跨来源关联键 |
| `source_node` | 产生事件的节点 | 运行节点必须提供 |
| `stage` | 关联用的阶段名 | 运行节点必须提供 |
| `timestamp_ns` | 事件时间戳 | 必须结合 `clock_id` 解释 |
| `event_name` | 事件名 | 映射为 normalized `event_type` |
| `event_type` | 事件类别 | 如 `can_bridge`/`action`/`planner` |
| `pid`、`tid` | 事件发生时的 Linux 进程/线程 | 新运行必须为正整数 |
| `host_id` | 事件发生主机 | 当前取 `gethostname()`/`socket.gethostname()` |
| `clock_id` | 时间戳域 | 当前运行节点统一为 `monotonic` |
| `duration_ns` | 已知事件区间长度 | `0` 表示未提供，不表示真实耗时为零（见下节） |
| `status` | 事件状态 | 默认 `observed`，Action/CAN 可提供更具体状态 |
| `reason_code` | 机器可读原因码 | 空字符串表示未提供；后续由故障分类冻结取值 |
| `extra_json` | 非关联必需扩展属性 | 不再存放 PID/TID/host/clock 等关键身份 |

### 一行完整记录

```json
{"trace_id":"task-1","oracle_id":"","sequence_id":42,"source_node":"device_bridge","stage":"can_frame_sent","timestamp_ns":1000,"event_name":"can_frame_sent","event_type":"can_bridge","pid":10,"tid":11,"host_id":"x5","clock_id":"monotonic","duration_ns":0,"status":"observed","reason_code":"","extra_json":"{\"command_id\":1,\"retry_count\":0}"}
```

`tests/adapters/test_runtime_event_adapter.py::test_documented_jsonl_shape_is_accepted`
用该行做接受测试，`test_rejects_the_nested_message_header_shape` 断言嵌套形态被拒；
改字段时两侧必须一起改。

### `extra_json` 里 CAN 生产者必须提供什么

`can_ack_lifecycle` 适配器（F6）只要求 `retry_count`（整数）。其余键**可省略**：
manifest 是 profile 的权威来源，事件不必复述。若生产者提供了这些键，它们必须与
oracle `injection` 一致，否则判 `event_profile_mismatch`：

| 键 | 与 manifest 的关系 |
|---|---|
| `ack_mode`、`mock_mode`、`can_interface`、`ack_timeout_ms`、`max_retries` | 出现时必须等于 `injection` 中的同名值 |
| `can_id`、`ack_can_id` | 出现时必须是十六进制字符串或整数，且两者之差等于 `ack_can_id_offset` |

同机 Phase 3 关联只接受已知且一致的时钟域。`clock_id=unknown` 的旧记录可以归档和单源分析，但不得直接与 ros2_tracing/eBPF 时间戳融合。

## 发射实现

C++ 节点统一调用：

```cpp
ai_robot_runtime_interfaces::populate_runtime_identity(event, "monotonic");
```

该 helper 在事件发生线程读取 PID、native TID 和 hostname。Python planner 使用 `os.getpid()`、`threading.get_native_id()` 和 `socket.gethostname()` 填充相同字段。

## 旧 JSONL

旧日志不做原地修改。转换命令：

```bash
python3 -m diagnosis.adapters.legacy_runtime_event_adapter \
  --input old_runtime_events.jsonl \
  --output adapted_runtime_events_v2.jsonl
```

默认补入 `clock_id=unknown`、`host_id=unknown`、`pid=0` 和 `tid=0`。只有原始实验记录能证明时钟与主机时，才可显式提供：

```bash
python3 -m diagnosis.adapters.legacy_runtime_event_adapter \
  --input old_runtime_events.jsonl \
  --output adapted_runtime_events_v2.jsonl \
  --legacy-clock-id monotonic \
  --legacy-host-id archived-host
```

适配器保留 `oracle_id`，但不读取它来推断任何字段。

## 实测

2026-07-15 在 WSL/Humble 由统一 smoke 入口重跑：

| 工作负载 | 事件数 | trace 数 | 进程数 | 线程数 | 时钟域 |
|---|---:|---:|---:|---:|---|
| W1 | 654 | 32 | 4 | 35 | `monotonic` |
| W2 | 234 | 39 | 2 | 2 | `monotonic` |
| W3 | 504 | 42 | 4 | 4 | `monotonic` |

上述结果只用于工程 smoke，不作为正式性能评测数据。

## 尚未完成

- ros2_tracing、eBPF 和 CAN ACK 的 normalized event 适配器（RuntimeEvent adapter 已完成）；
- process manifest 与节点/PID/TID 生命周期记录；
- 同机时钟偏差实测和跨主机 offset 报告；
- Trace-Stage 关联及 oracle 隔离评测。

## `duration_ns` 的三态语义

`duration_ns` 只有这一个字段，却要表达三种不同的事实。当前实现把它们当作同一
个值，这是已知限制；区分方式写在下面，正式实验前必须落成显式字段（见
"未完成部分"）。

| 情况 | 当前的记录方式 | 诊断层如何理解 |
|---|---|---|
| **点事件**：本来就没有区间，例如 `camera_frame_published`、`can_frame_sent` | `duration_ns = 0`，且该 stage 没有对应的 `_end` 事件 | 零宽窗口，不参与区间度量 |
| **未提供**：这是一个区间，但采集时没有测量 | `duration_ns = 0`，且存在配对 `_end` 或本应有 | 优先用配对 `_end`；没有则视为未测量 |
| **测量为零**：确实测到了 0 | 与上两者无法区分 | 与"未提供"同样处理，即视为未测量 |

因此 `duration_ns = 0` **永远不等于**"测得 0 ns"。窗口构造据此工作：

- 一个 stage 的区间只来自两处：配对的 `<body>_end` 事件，或该事件自己声明的
  `duration_ns`；
- 两者都没有时，窗口是零宽的，且 `StageWindow.contains()` 对任何时间戳都返回
  `False`，因此它不会吸收时间戳相同的系统事件；
- 只有 `end_ns > start_ns` 的窗口才被视为"已测量"。

`planner_process_start` / `planner_process_end` 这类成对阶段按配对计算区间；
`planner_output_stale`、`planner_backend_failure`、`planner_fallback_storm`
等终止事件是单条事件，它们声明的 `duration_ns` 才是测量值。

### 未完成部分

以下属于 schema 变更，已刻意留到正式实验之前，而不是现在改：

- 在 `RuntimeEvent`（或 normalized attributes）中冻结机器可读的
  `duration_semantics`，取值如 `point` / `unmeasured` / `measured`；
- 让每个 emitter 为携带非零 duration 的事件声明语义；
- 保持 StageWindow、root-cause catalog、trial 报告与优化报告使用同一语义；
- 增加跨语言 fixture，使同一批记录在 Python 与 C++ 下产生相同的窗口语义；
- 旧日志中的 `duration_ns = 0` 必须继续被解释为"未提供"，不得被重新解释为
  测量到的零。

在这之前，不要基于窗口时长做新的诊断准确率或优化收益声明。
