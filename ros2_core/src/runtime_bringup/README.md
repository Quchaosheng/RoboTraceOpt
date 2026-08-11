# runtime_bringup

## 模块目标

`runtime_bringup` 是第 8 步的系统级 launch-only package。

它提供一键启动入口，拉起 AI Robotics Runtime MVP 链路：

```text
camera_mock_node -> vlm_planner_node -> robot_action_node -> can_bridge_node -> runtime_event_logger_node
```

增强链路默认继续使用 Python planner。通过 `planner_implementation:=cpp` 可将主
planner 切换为 C++ 实现；节点名和主链 topic 保持不变，因此下游节点无需修改。

默认模式保留旧的并行兼容链路。设置 `action_manager_enabled:=true` 后，bringup 会启动 `action_manager_node`，关闭旧 `robot_action_node`，并让 CANBridge 订阅 `/action_manager/command_result`，形成：

```text
camera_mock_node -> vlm_planner_node -> action_manager_node -> can_bridge_node -> runtime_event_logger_node
```

## 一键启动

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
colcon build --packages-select runtime_bringup
source install/setup.bash
ros2 launch runtime_bringup ai_runtime.launch.py
```

如果依赖包还没构建过，直接构建整个 workspace：

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 launch runtime_bringup ai_runtime.launch.py
```

## 参数

`ai_runtime.launch.py` 支持：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `camera_rate_hz` | `1.0` | camera mock 发布频率 |
| `second_camera_enabled` | `false` | 是否启动第二个 camera mock（用于 sequence_id collision） |
| `planner_implementation` | `python` | 主 planner 实现，可选 `python` 或 `cpp` |
| `planner_shadow_enabled` | `false` | 在 Python 主 planner 旁启动隔离的 C++ shadow；主实现为 `cpp` 时忽略 |
| `planner_backend` | `mock` | planner backend，可选 `mock` 或 `llm` |
| `planner_delay_ms` | `50` | mock planner 处理延迟 |
| `planner_delay_mode` | `sleep` | planner 延迟机制；F1 使用 `busy_compute` |
| `executor_contention_enabled` | `false` | 是否启用 F2 planner executor 竞争 timer |
| `executor_contention_period_ms` | `25` | 竞争 timer 周期，单位 ms |
| `executor_contention_load_ms` | `0` | 竞争 callback busy-compute 时长，单位 ms |
| `action_delay_ms` | `100` | mock robot action 执行延迟 |
| `action_manager_enabled` | `false` | 是否启用 ActionManager 串行链路 |
| `action_feedback_period_ms` | `50` | ActionManager feedback 周期 |
| `action_goal_timeout_ms` | `0` | ActionManager goal timeout；0 表示不启用 |
| `can_interface` | `vcan0` | CANBridge 使用的 SocketCAN 接口，例如 `vcan0`、`can0` |
| `can_send_delay_ms` | `5` | mock CAN send 延迟 |
| `runtime_event_enabled` | `true` | 是否启用 RuntimeEvent instrumentation，并启动 runtime logger |
| `output_path` | `logs/runtime_events.jsonl` | RuntimeEvent JSONL 日志路径 |
| `mock_mode` | `true` | CAN bridge 是否使用 mock 模式 |

示例：

```bash
ros2 launch runtime_bringup ai_runtime.launch.py \
  camera_rate_hz:=2.0 \
  second_camera_enabled:=false \
  planner_backend:=mock \
  action_manager_enabled:=true \
  can_interface:=vcan0 \
  planner_delay_ms:=80 \
  action_delay_ms:=120 \
  can_send_delay_ms:=10 \
  runtime_event_enabled:=true \
  output_path:=logs/runtime_events.jsonl \
  mock_mode:=true
```

直接切换到 C++ 主 planner：

```bash
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_implementation:=cpp \
  planner_backend:=mock
```

先以 shadow 方式对照 Python 与 C++ 输出：

```bash
ros2 launch runtime_bringup ai_runtime.launch.py \
  planner_implementation:=python \
  planner_shadow_enabled:=true \
  planner_backend:=mock

ros2 topic echo /shadow/planner/command
ros2 topic echo /shadow/runtime/events
```

## C++ shadow 安全边界

- C++ shadow 只订阅正常的 `/camera/frame` 输入。
- 它发布的 `/planner/command` 被强制 remap 到 `/shadow/planner/command`。
- 它发布的 `/runtime/events` 被强制 remap 到 `/shadow/runtime/events`。
- `robot_action_node`、`action_manager_node` 和 `can_bridge_node` 仍只消费主链
  `/planner/command`（或 `/action_manager/command_result`），不会订阅 shadow command。
- `planner_shadow_enabled` 仅在 `planner_implementation:=python` 时生效，避免 C++
  已作为主 planner 时重复启动第二个实例。

## 查看 topic 和节点

另开终端：

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 node list
ros2 topic list
ros2 topic echo /runtime/events
```

预期节点：

- `/camera_mock_node`
- `/vlm_planner_node`（Python/C++ 主实现共用节点名）
- `/vlm_planner_cpp_shadow_node`（仅 `planner_shadow_enabled:=true` 时）
- `/robot_action_node`（默认兼容模式）
- `/action_manager_node`（`action_manager_enabled:=true` 时）
- `/can_bridge_node`
- `/runtime_event_logger_node`

查看日志落盘：

```bash
cd ros2_core
tail -f logs/runtime_events.jsonl
```

## 停止后运行分析

停止 launch 后执行：

```bash
cd ros2_core
python3 src/runtime_analysis_tools/scripts/analyze_latency.py \
  --input logs/runtime_events.jsonl \
  --output-dir reports

head reports/latency_report.csv
cat reports/latency_summary.json
```

重点检查：

- `trace_count > 0`
- `total_latency_ms` 有值
- `planner_process_ms` 大致接近 `planner_delay_ms`
- `missing_total_latency_count` 不应等于 `trace_count`

## Common Issues

- `output_path` 是相对路径时，会相对于启动 `ros2 launch` 的当前目录解析。建议从 workspace 根目录启动。
- 默认 `mock_mode=true` 不要求真实 CAN 或 `vcan0`。
- `runtime_event_enabled:=false` 时 `/runtime/events` 不会持续输出，`runtime_event_logger_node` 不会启动，`logs/runtime_events.jsonl` 也不会更新。这是开销对比模式的预期行为。
