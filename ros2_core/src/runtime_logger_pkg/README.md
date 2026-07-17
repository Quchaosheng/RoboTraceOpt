# runtime_logger_pkg

## 模块目标

`runtime_event_logger_node` 是第 6 步的 RuntimeEvent Logger。

它订阅 `/runtime/events`，把收到的 `ai_robot_runtime_interfaces/msg/RuntimeEvent` 逐行写入 JSONL 文件，作为后续 latency analysis 的输入。

系统级 `runtime_events_enabled=false` 时，bringup 不启动 logger，所有业务节点也停止 RuntimeEvent 发布。

当前范围只做日志落盘，不实现 analysis，不修改 `RuntimeEvent.msg`，不重构其他模块。

## 输入 topic

- Topic: `/runtime/events`
- Type: `ai_robot_runtime_interfaces/msg/RuntimeEvent`

## 输出文件

默认输出：

```text
logs/runtime_events.jsonl
```

如果 `logs/` 目录不存在，节点会自动创建。日志文件以 append 模式打开，避免覆盖已有 trace 数据。

## 参数

- `output_path`
  - Type: string
  - Default: `logs/runtime_events.jsonl`
  - Meaning: JSONL 输出路径
- `flush_every_event`
  - Type: bool
  - Default: `false`
  - Meaning: `false` 使用文件流缓冲；`true` 每写入一个事件后立即 flush，用于开销对比或实时观察

## JSONL 字段

每个 RuntimeEvent 写一行合法 JSON，字段至少包括：

- `trace_id`
- `oracle_id`
- `sequence_id`
- `source_node`
- `stage`
- `timestamp_ns`
- `event_name`
- `event_type`
- `pid`
- `tid`
- `host_id`
- `clock_id`
- `duration_ns`
- `status`
- `reason_code`
- `extra_json`

`extra_json` 会作为 JSON 字符串写入，并进行必要转义。

示例：

```json
{"trace_id":"logger_test_1","sequence_id":1,"source_node":"manual_test","stage":"test_stage","timestamp_ns":123456789,"event_name":"manual_event","event_type":"test","extra_json":"{\"ok\":true}"}
```

## Build

```bash
cd ai_robotics_runtime_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select runtime_logger_pkg
```

如果这是全新 workspace，先构建接口包：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select ai_robot_runtime_interfaces runtime_logger_pkg
```

## Run

```bash
cd ai_robotics_runtime_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch runtime_logger_pkg runtime_logger.launch.py output_path:=logs/runtime_events.jsonl
```

## Check

终端 1 启动 logger：

```bash
cd ai_robotics_runtime_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select runtime_logger_pkg
source install/setup.bash
ros2 launch runtime_logger_pkg runtime_logger.launch.py output_path:=logs/runtime_events.jsonl
```

终端 2 发布测试事件：

```bash
cd ai_robotics_runtime_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic pub --once /runtime/events ai_robot_runtime_interfaces/msg/RuntimeEvent "{header: {trace_id: 'logger_test_1', sequence_id: 1, source_node: 'manual_test', stage: 'test_stage', timestamp_ns: 123456789}, event_name: 'manual_event', event_type: 'test', extra_json: '{\"ok\":true}'}"
```

终端 3 查看日志：

```bash
cd ai_robotics_runtime_ws
tail -f logs/runtime_events.jsonl
```

也可以校验最后一行是合法 JSON：

```bash
python3 -m json.tool < <(tail -n 1 logs/runtime_events.jsonl)
```
