# camera_mock_pkg

## 1. 模块目标

提供无真实相机时可运行的 C++ ROS2 输入节点 `camera_mock_node`，作为 AI Robotics Runtime 的 Camera/Input 源。

节点固定周期发布 mock 相机帧，不传真实图像，只传 `image_path` 与 `frame_id`，并同步发布 RuntimeEvent 供后续日志与延迟分析使用。

## 2. 可靠参考资料

- ROS2 C++ 节点开发官方文档
- ROS2 发布/订阅最佳实践
- EmbodiedAgents/EMOS（ROS2-native agent 组织方式）

## 3. 所在路径

`ai_robotics_runtime_ws/src/camera_mock_pkg`

## 4. 输入输出

- 输入：`config/camera_mock.yaml`
- 输出 topic：`/camera/frame`
- 输出类型：`ai_robot_runtime_interfaces/msg/CameraFrame`
- RuntimeEvent topic：`/runtime/events`
- RuntimeEvent 类型：`ai_robot_runtime_interfaces/msg/RuntimeEvent`

## 5. 关键设计点

- 使用 `rclcpp` 实现。
- 节点名固定为 `camera_mock_node`。
- 默认 `camera_rate_hz = 1.0`，即每秒发布一条 `CameraFrame`。
- 每条消息生成新的 `trace_id`，格式包含 `source_id`、单调时钟时间戳和本地序号。
- `sequence_id` 从 1 开始自增。
- `source_id` 标识发布源实例，默认值为 `camera_a`，用于双发布源实验。
- `oracle_id` 由独立随机生成器产生，只用于实验评分，不参与正常 trace 重建。
- `runtime_events_enabled=false` 时仍发布业务消息，但不发布 RuntimeEvent，用于完整追踪开销对比。
- `image_path = fake_image_{sequence_id}.jpg`。
- `frame_id = sequence_id`。
- `encoding = mock`。
- `width = 640`，`height = 480`。
- RuntimeEvent 的 `stage = camera_publish`。
- RuntimeEvent 的 `event_name = camera_frame_published`。
- `timestamp_ns` 使用 `std::chrono::steady_clock` 生成，且 camera publish 事件复用消息发布边界的时间戳。
- 假设：`RuntimeEvent.event_type` 第一版使用 `camera_publish`，`extra_json` 记录 mock 帧元数据。

## 6. 已实现的代码

- `src/camera_mock_node.cpp`
- `include/camera_mock_pkg/camera_mock_node.hpp`
- `launch/camera_mock.launch.py`
- `config/camera_mock.yaml`

## 7. Build

```bash
cd ai_robotics_runtime_ws
colcon build --packages-select ai_robot_runtime_interfaces camera_mock_pkg
```

## 8. Run

```bash
source ai_robotics_runtime_ws/install/setup.bash
ros2 launch camera_mock_pkg camera_mock.launch.py
```

## 9. Check Correctness

```bash
source ai_robotics_runtime_ws/install/setup.bash
ros2 topic hz /camera/frame
ros2 topic echo /camera/frame --once
ros2 topic echo /runtime/events --once
```

验收标准：

- `/camera/frame` 每秒有消息。
- 每条 `CameraFrame` 有非空 `trace_id`。
- `/runtime/events` 中能看到 `stage: camera_publish`。
- `sequence_id` 连续自增。

## 10. Common Issues

- QoS 配置不匹配导致下游收不到消息。
- mock 帧率参数过高导致本机 CPU 占用异常。
- 未先 build/source `ai_robot_runtime_interfaces` 会导致接口类型找不到。
- 如果 `~/.ros/log` 不可写，先设置 `ROS_LOG_DIR` 到可写目录，例如 `export ROS_LOG_DIR=/tmp/ros_logs`。

## 11. Frame Transport Parameters

- `frame_payload_bytes` sets the byte payload per frame and defaults to `0`.
- `frame_qos_depth` sets the `/camera/frame` publisher depth and must be positive.
- `frame_qos_reliability` accepts `reliable` or `best_effort`.

F5 development runs override these through `runtime_bringup`. Normal W1 runs
retain zero payload bytes, depth 10, and reliable delivery.

## 12. Next Step

与 `vlm_planner_pkg` 对接最小输入输出契约，验证链路前两段连通。
