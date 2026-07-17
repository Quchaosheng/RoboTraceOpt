# RuntimeEvent v2 契约

记录日期：2026-07-15

## 目的

RuntimeEvent v2 在应用语义事件中加入跨层关联所需的进程、线程、主机和时钟身份。当前字段仍是应用层证据，不单独证明 ROS 2 executor、DDS 或内核根因。

## 字段

| 字段 | 含义 | 当前约束 |
|---|---|---|
| `header.trace_id` | 端到端业务 trace 身份 | 运行节点必须提供 |
| `header.oracle_id` | 独立实验真值 | 只供评测，不得用于正式关联/诊断/优化 |
| `header.sequence_id` | 来源内顺序身份 | 不单独作为跨来源关联键 |
| `header.timestamp_ns` | 事件时间戳 | 必须结合 `clock_id` 解释 |
| `pid`、`tid` | 事件发生时的 Linux 进程/线程 | 新运行必须为正整数 |
| `host_id` | 事件发生主机 | 当前取 `gethostname()`/`socket.gethostname()` |
| `clock_id` | 时间戳域 | 当前运行节点统一为 `monotonic` |
| `duration_ns` | 已知事件区间长度 | `0` 表示未提供，不表示真实耗时为零 |
| `status` | 事件状态 | 默认 `observed`，Action/CAN 可提供更具体状态 |
| `reason_code` | 机器可读原因码 | 空字符串表示未提供；后续由故障分类冻结取值 |
| `extra_json` | 非关联必需扩展属性 | 不再存放 PID/TID/host/clock 等关键身份 |

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
