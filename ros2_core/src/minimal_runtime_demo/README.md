# minimal_runtime_demo

## 1. 模块目标
用 C++ 创建最小 ROS2 Runtime 链路，用于 RuntimeEvent 可观测性与时延诊断实验。

## 2. 参考资料
- ROS2 Launch 官方教程（多节点 launch）
- ROS2 YAML 参数配置方式

## 3. 所在路径
`ros2_runtime_observability_ws/src/minimal_runtime_demo`

## 4. 输入输出
- 输入：`config/demo.yaml` 中的频率与模拟延迟参数
- 输出业务消息：`std_msgs/msg/String` JSON 字符串
- 输出观测事件：`ai_robot_runtime_interfaces/msg/RuntimeEvent` 到 `/runtime/events`

## 5. 节点链路
```text
input_node -> /demo/input -> planner_node
planner_node -> /demo/planner_output -> action_node
action_node -> /demo/action_output -> control_node
```

所有节点均使用 C++/`rclcpp` 实现。

## 6. 关键设计点
- `input_node` 每秒默认生成一个 `trace_id`，`sequence_id` 自增。
- 下游节点沿用同一个 `trace_id` 与 `sequence_id`。
- 每个关键阶段发布 `RuntimeEvent` 到 `/runtime/events`。
- 节点间业务消息暂用 JSON 字符串，字段包含 `trace_id`、`sequence_id`、`timestamp_ns`。

## 7. 未来要实现的代码
- 更严格的 JSON 解析或正式业务消息类型
- 可配置 QoS 与更复杂实验负载
- 与 logger/analysis/eBPF 的联合 launch

## 8. Build
```bash
cd <project-root>/ros2_runtime_observability_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select ai_robot_runtime_interfaces minimal_runtime_demo
```

## 9. Run
```bash
cd <project-root>/ros2_runtime_observability_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch minimal_runtime_demo minimal_demo.launch.py
```

## 10. Check Correctness
```bash
# 节点检查
ros2 node list

# 业务链路检查
ros2 topic echo /demo/input
ros2 topic echo /demo/planner_output
ros2 topic echo /demo/action_output

# RuntimeEvent 检查
ros2 topic echo /runtime/events
```

验证 `trace_id` 贯穿全链路：观察 `/runtime/events` 中同一 `trace_id` 是否依次出现 `input_publish`、`planner_receive`、`planner_process_start`、`planner_process_end`、`planner_publish`、`action_receive`、`action_start`、`action_end`、`action_publish`、`control_receive`、`control_send_start`、`control_send_end`。

## 11. Common Issues
- 未先构建并 source `ai_robot_runtime_interfaces`，导致消息类型不可用。
- launch 后看不到话题，先检查 `ros2 node list` 中四个节点是否存在。
- 参数不生效时检查 `config/demo.yaml` 的节点名是否与 launch 中 `name` 一致。
- 受限环境下 DDS socket 报错时，先在正常 ROS2 网络环境运行验证。

## 12. Next Step
与 `runtime_logger_pkg` 联合运行，将 `/runtime/events` 写入 JSONL 文件。
