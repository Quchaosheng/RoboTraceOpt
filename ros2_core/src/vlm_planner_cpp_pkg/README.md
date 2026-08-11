# vlm_planner_cpp_pkg

`vlm_planner_cpp_pkg` is the C++17 `rclcpp` runtime replacement for the Python
`vlm_planner_node`. The node keeps the public node and executable name
`vlm_planner_node`.

## Safety contract

- `planner_backend=mock` is the only backend allowed to publish motion.
- `llm`, `replay`, and unknown backends enter fail-closed abstain mode.
- An abstaining request publishes evidence events but never publishes a
  `PlannerCommand`.
- Every command and event copies `trace_id`, `oracle_id`, and `sequence_id`
  from the input `CameraFrame`.
- `ModelAdmission` rejects missing identity, future/expired observations, and
  duplicate requests. `validate_decision` gates every command publication.

The mock command remains compatible with the Python implementation:
`move_forward`, target `front`, speed `0.2`, confidence `0.9`, and reason
`mock planner output`.

## ROS API

| Direction | Topic | Type |
| --- | --- | --- |
| Subscribe | `/camera/frame` | `ai_robot_runtime_interfaces/msg/CameraFrame` |
| Publish | `/planner/command` | `ai_robot_runtime_interfaces/msg/PlannerCommand` |
| Publish | `/runtime/events` | `ai_robot_runtime_interfaces/msg/RuntimeEvent` |

The XML launch exposes `camera_topic`, `command_topic`, and `event_topic` as
ROS remappings. The topics therefore remain usable for shadow execution.

Normal requests emit `planner_receive`, `planner_process_start`,
`planner_process_end`, and `planner_publish`. Rejections additionally emit the
specific rejection event and `planner_command_abstained`; no command is sent.

## Parameters

The complete compatibility parameter set is in `config/planner.yaml`. Important
parameters are:

| Parameter | Default | Contract |
| --- | --- | --- |
| `planner_backend` | `mock` | Only explicit `mock` enables motion |
| `planner_delay_ms` | `50` | Non-negative controlled mock delay |
| `planner_delay_mode` | `sleep` | `sleep` or `busy_compute` |
| `executor_threads` | `1` | Integer from 1 through 4 |
| `runtime_event_enabled` | `true` | Enables RuntimeEvent publication |
| `frame_qos_depth` | `10` | Positive KEEP_LAST depth |
| `frame_qos_reliability` | `reliable` | `reliable` or `best_effort` |
| `observation_ttl_ms` | `1000` | Positive observation lifetime, matching the Python runtime |
| `model_queue_delay_ms` | `0` | Non-negative delay before inference |

The LLM, recording, and replay parameter names remain declared for launch-file
compatibility. Their adapters are intentionally unavailable in this first C++
runtime and select abstention instead of mock fallback.
The Python planner's plural `runtime_events_enabled` spelling is also accepted
as a compatibility alias; either event flag can disable publication.

## Build and run

The workspace must provide `ai_robot_runtime_interfaces` and the CMake package
`robotraceopt_core`, exporting `robotraceopt_core::planner`.

```bash
colcon build --packages-select ai_robot_runtime_interfaces robotraceopt_core vlm_planner_cpp_pkg
source install/setup.bash
ros2 launch vlm_planner_cpp_pkg vlm_planner.launch.xml planner_backend:=mock
```

Shadow topics can be selected without changing the node:

```bash
ros2 launch vlm_planner_cpp_pkg vlm_planner.launch.xml \
  command_topic:=/shadow/planner/command \
  event_topic:=/shadow/runtime/events
```

Run the contract test with:

```bash
colcon test --packages-select vlm_planner_cpp_pkg
colcon test-result --verbose
```
