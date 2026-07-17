# ai_robot_runtime_interfaces

## 1. 模块目标

定义 AI Robotics Runtime 的共享 ROS2 消息与 Action 接口，统一 Camera、Planner、Action、CAN、Logger 的数据契约。

## 2. 所在路径

`ai_robotics_runtime_ws/src/ai_robot_runtime_interfaces`

## 3. 接口清单与作用

- `msg/TraceHeader.msg`：全链路追踪头，承载 `trace_id`、实验真值 `oracle_id`、`sequence_id`、`source_node`、`stage`、`timestamp_ns`。
- `msg/CameraFrame.msg`：Camera 阶段输出，第一版仅传 `image_path` 或 `frame_id`，不传原始图像。
- `msg/PlannerCommand.msg`：Planner 阶段输出的动作意图，包含 `action/target/speed/confidence/reason`。
- `msg/RuntimeEvent.msg`：运行时关键事件记录，包含 PID/TID、主机、时钟域、状态和原因码；`extra_json` 只用于非关联必需的扩展上下文。
- `action/RobotCommand.action`：Planner 到 RobotActionServer 的执行协议，含 Goal/Result/Feedback。

## 4. trace_id 贯穿说明（Camera -> Planner -> Action -> CAN）

1. `camera_mock_node` 生成一帧输入时创建 `trace_id`，并填充 `TraceHeader`。
2. `vlm_planner_node` 接收 `CameraFrame` 后，沿用同一 `trace_id` 产生 `PlannerCommand`。
3. `robot_action_server` 在 `RobotCommand.Goal` 中继续沿用该 `trace_id`，Result 与 Feedback 写入阶段时间戳。
4. `can_bridge_node` 处理执行命令时继续透传同一 `trace_id` 到 `RuntimeEvent`，形成端到端链路关联。

约束：同一条任务链路不重置 `trace_id`，只递增或保持 `sequence_id` 语义一致。

`oracle_id` 仅用于实验评分。正常重建和时延统计不得读取该字段；关联准确率工具使用它检查一个重建组是否混入多个真实消息流。

## RuntimeEvent v2

所有新运行事件必须设置 `pid`、`tid`、`host_id` 和 `clock_id`。当前同机工作负载统一使用 `clock_id=monotonic`。`duration_ns=0` 表示事件未直接提供持续时间，不能解释为真实耗时为零。C++ 节点使用 `runtime_event_identity.hpp` 填充运行身份。

## 5. Build

```bash
cd ai_robotics_runtime_ws
colcon build --packages-select ai_robot_runtime_interfaces
```

## 6. Check

```bash
source install/setup.bash
ros2 interface list | grep ai_robot_runtime_interfaces
ros2 interface show ai_robot_runtime_interfaces/msg/TraceHeader
ros2 interface show ai_robot_runtime_interfaces/msg/CameraFrame
ros2 interface show ai_robot_runtime_interfaces/msg/PlannerCommand
ros2 interface show ai_robot_runtime_interfaces/msg/RuntimeEvent
ros2 interface show ai_robot_runtime_interfaces/action/RobotCommand
ros2 interface show ai_robot_runtime_interfaces/srv/RuntimeQuery
```

`RuntimeQuery.srv` is the request/response contract for the journal-strengthening
service experiment. `payload_id` is application business data and is deliberately
separate from `TraceHeader` and the experiment-only `oracle_id`.

## 7. 预期结果

- `ros2 interface list` 可见 4 个 `msg` 和 1 个 `action`。
- `ros2 interface show` 的字段定义与本 README 完全一致。
- 不需要任何业务节点即可完成接口层验证。
