# robot_action_pkg

## Node

`robot_action_pkg` provides two action-stage nodes for AI Robotics Runtime.

- `robot_action_node`: legacy lightweight mock stage. It subscribes to planner output, simulates execution with a configurable delay, and publishes action `RuntimeEvent` messages.
- `action_manager_node`: serial ActionManager prototype. It subscribes to planner output, sends a `/robot_command` ROS2 Action goal, publishes feedback/result RuntimeEvents, and publishes successful results to `/action_manager/command_result` for CANBridge.

Current assumption: both nodes perform mock execution. They do not control real arm/base hardware. CANBridge remains in `can_bridge_pkg`.

## Topics

`robot_action_node` input:

- `/planner/command`
- Type: `ai_robot_runtime_interfaces/msg/PlannerCommand`

`action_manager_node` input/output:

- Input topic: `/planner/command`
- Action server/client: `/robot_command`
- Result topic: `/action_manager/command_result`
- Types: `ai_robot_runtime_interfaces/msg/PlannerCommand`, `ai_robot_runtime_interfaces/action/RobotCommand`

RuntimeEvent output:

- `/runtime/events`
- Type: `ai_robot_runtime_interfaces/msg/RuntimeEvent`

## Parameters

- `action_delay_ms`
  - Type: integer
  - Default: `100`
  - Meaning: mock execution delay after `action_execute_start` and before `action_execute_end`
  - Negative values are rejected at startup and replaced with `100`
- `feedback_period_ms`
  - Type: integer
  - Default: `50`
  - Meaning: ActionManager feedback period
- `goal_timeout_ms`
  - Type: integer
  - Default: `0`
  - Meaning: ActionManager timeout budget; `0` disables timeout

## RuntimeEvent

All action events reuse `PlannerCommand.header.trace_id` and `PlannerCommand.header.sequence_id`.

`RuntimeEvent.header.source_node` is always `robot_action_node`.

`RuntimeEvent.header.timestamp_ns` uses a monotonic steady clock.

| event_name | header.stage | event_type | extra_json |
| --- | --- | --- | --- |
| `action_command_received` | `action_receive` | `action` | Includes `action`, `target`, `speed`, `action_delay_ms` |
| `action_execute_start` | `action_execute_start` | `action` | Includes `action`, `target`, `speed`, `action_delay_ms` |
| `action_execute_end` | `action_execute_end` | `action` | Includes `action`, `target`, `speed`, `action_delay_ms` |

`action_manager_node` additionally emits:

| event_name | header.stage | event_type |
| --- | --- | --- |
| `action_command_received` | `action_receive` | `action_manager` |
| `action_goal_received` | `action_goal_received` | `action_manager` |
| `action_goal_sent` | `action_goal_sent` | `action_manager` |
| `action_goal_accepted` | `action_goal_accepted` | `action_manager` |
| `action_feedback` | `action_feedback` | `action_manager` |
| `action_result` | `action_result` | `action_manager` |
| `action_result_failed` | `action_result_failed` | `action_manager` |
| `action_goal_timeout` | `action_goal_timeout` | `action_manager` |
| `action_cancel_requested` | `action_cancel_requested` | `action_manager` |
| `action_cancelled` | `action_cancelled` | `action_manager` |

## Build

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
colcon build --packages-select robot_action_pkg
```

If this is a fresh workspace and the interface package has not been built yet:

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select ai_robot_runtime_interfaces robot_action_pkg
```

## Run

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch robot_action_pkg robot_action.launch.py
```

Run the ActionManager serial prototype:

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch robot_action_pkg action_manager.launch.py
```

## Check

Terminal 1:

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch robot_action_pkg robot_action.launch.py
```

Terminal 2:

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic echo /runtime/events
```

Terminal 3, publish one test command:

```bash
cd ros2_core
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic pub --once /planner/command ai_robot_runtime_interfaces/msg/PlannerCommand "{header: {trace_id: 'trace_manual_1', sequence_id: 1, source_node: 'manual_check', stage: 'planner_publish', timestamp_ns: 1}, action: 'move', target: 'mock_target', speed: 0.5, confidence: 1.0, reason: 'manual check'}"
```

Expected `/runtime/events` output includes:

- `event_name: action_command_received`, `stage: action_receive`
- `event_name: action_execute_start`, `stage: action_execute_start`
- `event_name: action_execute_end`, `stage: action_execute_end`

All three events should have the same `trace_id: trace_manual_1` and `sequence_id: 1`.
