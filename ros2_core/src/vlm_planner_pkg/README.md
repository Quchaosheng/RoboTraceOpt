# vlm_planner_pkg

`vlm_planner_pkg` 实现 AI Robotics Runtime 的 `vlm_planner_node`。

节点订阅 `/camera/frame`，读取 `CameraFrame.header.trace_id` 与 `sequence_id`，生成受限的 `PlannerCommand` 并发布到 `/planner/command`，同时向 `/runtime/events` 发布 planner 阶段事件，供 logger 和 latency analysis 使用。

## 输入输出

| 类型 | Topic | 消息 |
| --- | --- | --- |
| 输入 | `/camera/frame` | `ai_robot_runtime_interfaces/msg/CameraFrame` |
| 输出 | `/planner/command` | `ai_robot_runtime_interfaces/msg/PlannerCommand` |
| 事件 | `/runtime/events` | `ai_robot_runtime_interfaces/msg/RuntimeEvent` |

## Backend

### mock backend

默认 `planner_backend=mock`，不需要网络、API key 或模型服务，适合离线复现和端到端链路测试。

mock 输出保持稳定：

- `action = move_forward`
- `target = front`
- `speed = 0.2`
- `confidence = 0.9`
- `reason = mock planner output`

`planner_delay_ms` 控制 mock planner 的模拟处理耗时。
`planner_delay_mode` 默认为 `sleep`；诊断实验 F1 使用 `busy_compute`，以便将应用计算延迟与 F4 阻塞系统调用分开。

### llm backend

`planner_backend=llm` 时，节点使用 OpenAI-compatible Chat Completions 接口请求模型。该 backend 是可选能力，不会成为项目运行的强依赖。

LLM 只能返回 JSON，节点会解析并校验后映射为 `PlannerCommand`：

```json
{
  "action": "move_forward",
  "target": "front",
  "speed": 0.2,
  "confidence": 0.8,
  "reason": "obstacle-free path inferred from mock frame"
}
```

安全约束：

- `action` 必须属于白名单：`move_forward`、`turn_left`、`turn_right`、`stop`、`inspect`
- `speed` 限制在 `[0.0, 1.0]`
- `confidence` 限制在 `[0.0, 1.0]`
- JSON 解析失败、超时、无 API key、无模型名或 action 不合法时，默认 fallback 到 mock
- RuntimeEvent 不记录 API key

## 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `planner_backend` | `mock` | planner backend，可选 `mock` 或 `llm` |
| `planner_delay_ms` | `50` | mock planner 延迟，单位 ms |
| `planner_delay_mode` | `sleep` | `sleep` 或 `busy_compute`；后者仅用于受控计算注入 |
| `executor_contention_enabled` | `false` | 启用 F2 单线程 executor 竞争 timer |
| `executor_contention_period_ms` | `25` | 竞争 callback 周期 |
| `executor_contention_load_ms` | `0` | 每次竞争 callback 的 busy-compute 时长 |
| `llm_provider` | `openai_compatible` | 当前预留 OpenAI-compatible adapter |
| `llm_api_base` | 环境变量 `LLM_API_BASE` | OpenAI-compatible API base，例如 `http://localhost:8000/v1` |
| `llm_api_key_env` | `LLM_API_KEY` | 保存 API key 的环境变量名 |
| `llm_model` | 环境变量 `LLM_MODEL` | 模型名；为空时 fallback mock |
| `llm_timeout_s` | `3.0` | LLM 请求超时秒数 |
| `fallback_to_mock` | `true` | LLM 不可用或输出不合法时是否 fallback mock |

`planner_mode` 仅保留为旧参数兼容，新命令应使用 `planner_backend`。

## RuntimeEvent

节点发布以下事件：

- `planner_receive`
- `planner_process_start`
- `planner_process_end`
- `planner_publish`

`extra_json` 至少包含：

- `planner_backend`
- `effective_backend`
- `used_fallback`
- `llm_model`，如果配置了模型名
- `action`
- `target`
- `speed`
- `confidence`
- `reason`

所有事件复用上游 `CameraFrame.header.trace_id` 与 `sequence_id`，`timestamp_ns` 使用 `time.monotonic_ns()`。

## Build

```bash
cd ai_robotics_runtime_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select vlm_planner_pkg
source install/setup.bash
```

## Run

mock 模式：

```bash
ros2 launch vlm_planner_pkg vlm_planner.launch.py planner_backend:=mock
```

llm 模式：

```bash
export LLM_API_BASE=http://localhost:8000/v1
export LLM_API_KEY=replace_with_key
export LLM_MODEL=replace_with_model
ros2 launch vlm_planner_pkg vlm_planner.launch.py planner_backend:=llm
```

也可以随启动参数显式传入：

```bash
ros2 launch vlm_planner_pkg vlm_planner.launch.py \
  planner_backend:=llm \
  llm_api_base:=http://localhost:8000/v1 \
  llm_model:=replace_with_model \
  llm_api_key_env:=LLM_API_KEY
```

## Check

终端 1：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch camera_mock_pkg camera_mock.launch.py
```

终端 2：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vlm_planner_pkg vlm_planner.launch.py planner_backend:=mock
```

终端 3：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic echo /planner/command
ros2 topic echo /runtime/events
```

检查点：

- `/planner/command` 有输出
- `PlannerCommand.header.trace_id` 沿用 `CameraFrame.header.trace_id`
- `/runtime/events` 包含四个 planner 事件
- mock 模式下 `reason` 为 `mock planner output`
- llm fallback 时 `extra_json.used_fallback=true`，`effective_backend=mock`

## Frame Transport Parameters

- `frame_qos_depth` sets the `/camera/frame` subscription depth and must be positive.
- `frame_qos_reliability` accepts `reliable` or `best_effort` and must match the
  camera endpoint.

Normal W1 runs retain depth 10 and reliable delivery. F5 development runs
override both endpoints through `runtime_bringup`.

## Common Issues

- 未启动 `camera_mock_node` 时，planner 不会收到输入，也不会发布 `/planner/command`。
- `planner_backend=llm` 但没有设置 `LLM_API_BASE`、`LLM_API_KEY` 或 `LLM_MODEL` 时，默认 fallback 到 mock。
- 如果模型返回非 JSON、非法 action 或超时，默认 fallback 到 mock。
- 如果 `fallback_to_mock=false`，LLM backend 失败时不会发布 PlannerCommand。
- 如果 `~/.ros/log` 不可写，先设置 `ROS_LOG_DIR` 到可写目录，例如 `export ROS_LOG_DIR=/tmp/ros_logs`。
