# tracetools fixture

`w1_ros2_events.jsonl` 是从真实 W1 LTTng CTF trace 中有界导出的 ROS 2 事件，不是手写样例。每类事件最多保留 8 条，供 adapter 契约测试使用。

`w1_ros2_events.manifest.json` 记录：

- 原始 CTF 目录哈希；
- 官方 ros2_tracing commit；
- 事件类型与数量；
- LTTng clock class、频率和 offset；
- 采集 host。

原始 CTF 位于生成环境的 `~/.cache/robotracert_fusion_traces/`，不提交到 Git。重新生成方法见 `docs/tracing/ROS2_TRACING_SMOKE.md`。
