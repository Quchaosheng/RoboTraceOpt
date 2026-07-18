# ros2_tracing 实采与适配状态

记录日期：2026-07-15

## 环境结论

当前 `/opt/ros/humble` 中的 `tracetools` CLI 已安装，但 provider 编译为 disabled：

- `ros2 run tracetools status` 输出 `Tracing disabled`；
- W1 节点运行时 `lttng list --userspace` 不显示 ROS 2 UST provider；
- 系统 `libtracetools.so` 不依赖 `liblttng-ust`。

因此默认 WSL 能力报告把 ros2_tracing 标为 blocked。为冻结开发 fixture，项目使用官方 `ros2/ros2_tracing` tag `4.1.2`、commit `3c159b382d2d565e26eaa91e39c9ec06a5c6fe88` 在 `/root/.cache` 构建隔离 overlay，不覆盖 `/opt/ros/humble`。

## 可复现入口

```bash
bash scripts/build_tracetools_overlay.sh
bash scripts/run_ros2_tracing_smoke.sh w1 8
```

第二条命令启用 `ros2:*` UST events，并添加 `vpid`、`vtid` 和 `procname` context。原始 CTF 默认写入 `~/.cache/robotracert_fusion_traces/`，不进入 Git。

从 CTF 导出有界 fixture：

```bash
python3 scripts/export_tracetools_fixture.py \
  --trace <ctf-directory> \
  --output-jsonl tests/fixtures/tracetools/w1_ros2_events.jsonl \
  --output-manifest tests/fixtures/tracetools/w1_ros2_events.manifest.json \
  --max-per-event 8 \
  --host-id <host> \
  --tracetools-source-commit 3c159b382d2d565e26eaa91e39c9ec06a5c6fe88
```

## Fixture 与 adapter

当前 fixture 来自真实 W1 tracing smoke，包含 98 条、13 类 ROS 2 事件。manifest 记录 CTF 目录 SHA-256、clock class、host 和上游 commit。

归一化命令：

```bash
python3 -m diagnosis.adapters.tracetools_adapter \
  --input tests/fixtures/tracetools/w1_ros2_events.jsonl \
  --output data/processed/smoke/w1_ros2_normalized.jsonl
```

98 条 fixture 已全部转换。adapter 输出 `source=ros2_tracing`，保留 PID/TID、payload、CPU、原始时钟和 provenance；在关联算法运行前，`trace_id` 与 `stage` 保持为空。

## 时钟口径

CTF clock class 名称为 `monotonic`，频率为 1 GHz。fixture 同时保留：

- `clock.value`：启动以来 raw monotonic cycle；1 GHz 下可直接换算为 monotonic 纳秒；
- `clock.ns_from_origin`：加上 LTTng epoch offset 后的值，只作 provenance；
- offset seconds/cycles：供后续校准审计。

adapter 使用 `clock.value * 1e9 / frequency` 生成 NormalizedEvent `timestamp_ns`，不会把 `ns_from_origin` 与 RuntimeEvent monotonic 时间直接混合。

## 边界

- fixture 是有界样本，不是完整正式实验 trace；
- 隔离 overlay 是 WSL 开发补救，不代表原生 x86 或 RK3568 默认可用；
- 当前只完成事件归一化，没有完成 node handle、callback、publisher/subscription 到 trace/stage 的关联；
- 正式实验必须重新采集、生成 run manifest，并记录 provider 版本与 clock metadata。

## Formal-session export boundary

The bounded fixture exporter remains for small public regression fixtures.
Formal F2/F3/F5 fault cases instead call `scripts/export_ros2_trace.py` after
the CTF session stops. That command performs a full ROS 2 trace export for the
frozen event allowlist, rejects missing fault-specific event categories, and
records the CTF directory hash, host, clock classes, and event counts. Both the
CTF directory and exported JSONL are required by `artifact_manifest.json`.
