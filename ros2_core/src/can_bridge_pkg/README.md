# can_bridge_pkg

## 模块目标

`can_bridge_node` 是第 5 步的最小可运行 SocketCAN/vCAN bridge mock。

它把 ROS2 机器人动作命令编码成模拟 CAN frame，发布 CAN bridge 阶段的 `RuntimeEvent`，用于保留 ROS2-CAN 技术主线，并支撑后续端到端 trace 和 latency analysis。

默认兼容模式下，本模块订阅 `/planner/command`。当 `runtime_bringup` 使用 `action_manager_enabled=true` 时，CANBridge 的 `command_topic` 会切换为 `/action_manager/command_result`，从而形成 `AI-Planner -> ActionManager -> CANBridge` 串行链路。

## mock_mode 与真实 SocketCAN

- `mock_mode=true`：默认模式，不要求存在 `vcan0` 或真实 CAN 硬件；节点只把动作命令编码成 mock CAN frame，并在日志和 `RuntimeEvent.extra_json` 中输出 `can_id` 和 `payload_hex`。
- `mock_mode=false`：尝试使用 Linux SocketCAN API 向 `can_interface` 发送 CAN frame；如果接口不存在或系统不支持 SocketCAN，会记录错误并继续发布 `can_frame_sent` 事件，其中 `send_success=false`。

## 输入输出

输入：

- Topic: `/planner/command`
- Serial mode topic: `/action_manager/command_result`
- Type: `ai_robot_runtime_interfaces/msg/PlannerCommand`

输出：

- Topic: `/runtime/events`
- Type: `ai_robot_runtime_interfaces/msg/RuntimeEvent`

## 参数

- `can_interface`
  - Type: string
  - Default: `vcan0`
- `command_topic`
  - Type: string
  - Default: `/planner/command`
  - Meaning: PlannerCommand 输入 topic；串行模式下使用 `/action_manager/command_result`
- `mock_mode`
  - Type: bool
  - Default: `true`
- `can_send_delay_ms`
  - Type: integer
  - Default: `5`
  - Meaning: mock/SocketCAN send 前的模拟发送延迟
- `ack_enabled`
  - Type: bool
  - Default: `true`
  - Meaning: 是否启用 ACK/timeout/retry RuntimeEvent 闭环
- `ack_mode`
  - Type: string
  - Default: `mock`
  - Meaning: ACK 来源，支持 `mock`、`socketcan` 或 `disabled`；`socketcan` 会监听 `can_id + ack_can_id_offset` 的 ACK frame，并要求 ACK payload 与控制 frame payload 一致
- `ack_timeout_ms`
  - Type: integer
  - Default: `50`
  - Meaning: 每次发送后的 ACK 等待预算
- `max_retries`
  - Type: integer
  - Default: `2`
  - Meaning: ACK 超时后的最大重试次数
- `retry_backoff_ms`
  - Type: integer
  - Default: `10`
  - Meaning: 重试前等待时间
- `mock_ack_delay_ms`
  - Type: integer
  - Default: `5`
  - Meaning: mock ACK 延迟
- `mock_ack_policy`
  - Type: string
  - Default: `success`
  - Meaning: mock ACK 策略，支持 `success`、`delayed`、`drop_first`、`drop`
- `ack_can_id_offset`
  - Type: integer
  - Default: `128`
  - Meaning: `socketcan` ACK 模式下 ACK CAN ID 相对控制 CAN ID 的偏移量

## RuntimeEvent

所有事件都会保留输入 `PlannerCommand.header.trace_id` 和 `PlannerCommand.header.sequence_id`。

`RuntimeEvent.header.source_node` 固定为 `can_bridge_node`。

`RuntimeEvent.header.timestamp_ns` 使用单调 steady clock。

`extra_json` 至少包含：

- `action`
- `target`
- `speed`
- `can_interface`
- `mock_mode`
- `can_id`
- `payload_hex`
- `ack_can_id`
- `ack_mode`
- `retry_count`

事件列表：

| event_name | header.stage | event_type |
| --- | --- | --- |
| `can_command_received` | `can_receive` | `can_bridge` |
| `can_encode_start` | `can_encode_start` | `can_bridge` |
| `can_encode_end` | `can_encode_end` | `can_bridge` |
| `can_frame_sent` | `can_frame_sent` | `can_bridge` |
| `can_ack_wait_start` | `can_ack_wait_start` | `can_bridge` |
| `can_ack_received` | `can_ack_received` | `can_bridge` |
| `can_ack_timeout` | `can_ack_timeout` | `can_bridge` |
| `can_retry_scheduled` | `can_retry_scheduled` | `can_bridge` |
| `can_retry_exhausted` | `can_retry_exhausted` | `can_bridge` |
| `can_frame_send_failed` | `can_frame_send_failed` | `can_bridge` |

ACK mock 策略：

- `success`：发送后产生 `can_ack_received`。
- `delayed`：ACK 延迟超过 timeout，用于制造 ACK 长尾/超时场景。
- `drop_first`：第一次 ACK 丢失，触发 `can_ack_timeout` 和 `can_retry_scheduled`，重试后产生 `can_ack_received`。
- `drop`：所有 ACK 丢失，最终产生 `can_retry_exhausted`。

`socketcan` ACK 策略：

- CANBridge 发送控制 frame 后进入 `can_ack_wait_start`。
- 节点在同一 SocketCAN 接口上等待 ACK frame，默认 ACK ID 为 `can_id + 0x80`。
- ACK frame 的 payload 需要与控制 frame payload 一致，匹配后产生 `can_ack_received`。
- 超过 `ack_timeout_ms` 未匹配到 ACK 时产生 `can_ack_timeout`，并按 `max_retries` 执行重试或进入 `can_retry_exhausted`。

## Build

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
colcon build --packages-select can_bridge_pkg
```

如果这是全新 workspace，先构建接口包：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select ai_robot_runtime_interfaces can_bridge_pkg
```

## Run

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch can_bridge_pkg can_bridge.launch.py
```

## Check

终端 1：

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch can_bridge_pkg can_bridge.launch.py
```

终端 2：

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic echo /runtime/events
```

终端 3，发布一条 planner command：

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic pub --once /planner/command ai_robot_runtime_interfaces/msg/PlannerCommand "{header: {trace_id: 'test_trace_can_1', sequence_id: 1, source_node: 'manual_test', stage: 'planner_publish', timestamp_ns: 123456}, action: 'move_forward', target: 'front', speed: 0.2, confidence: 0.9, reason: 'manual test'}"
```

预期 `/runtime/events` 中可以看到：

- `can_command_received`
- `can_encode_start`
- `can_encode_end`
- `can_frame_sent`

这些事件应保留同一个 `trace_id: test_trace_can_1` 和 `sequence_id: 1`，且 `extra_json` 中包含 `can_id` 和 `payload_hex`。

## vcan0 测试

默认 `mock_mode=true` 不需要创建 `vcan0`。如果要验证真实 Linux SocketCAN 发送路径，先创建 vCAN：

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
ip link show vcan0
```

然后把配置或 launch 参数切到：

```yaml
can_bridge_node:
  ros__parameters:
    can_interface: "vcan0"
    mock_mode: false
    can_send_delay_ms: 5
```

可以用 `candump vcan0` 观察帧；如果未安装 `can-utils`，继续使用 `/runtime/events` 和节点日志验证。
