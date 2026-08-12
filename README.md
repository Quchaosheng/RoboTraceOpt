# RoboTraceOpt

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)]() [![ROS 2](https://img.shields.io/badge/ROS%202-Humble%20%7C%20Jazzy-22314E)]() [![License](https://img.shields.io/badge/license-MIT-blue)]()

> **跨层诊断ROS 2时延 · 证据不完整时拒绝推测**

RoboTraceOpt统一应用、中间件、内核三层证据，定位ROS 2机器人系统的端到端延迟根因。它不会在证据不足时强行给出结论，而是明确告知缺失项。

---

## 核心特性

🔍 **跨层证据融合**  
统一RuntimeEvent、ros2_tracing、eBPF调度记录，构建完整时间线

🎯 **拒绝推测性根因**  
证据链不完整时，输出`INSUFFICIENT_EVIDENCE`而非猜测

📊 **成对实验验证**  
控制组/注入组对比 + bootstrap置信区间

🔐 **可复现证据包**  
冻结commit/tag + SHA-256校验 + artifact manifest

---

## 快速开始

### Ubuntu 24.04 / ROS 2 Jazzy

```bash
# 1. 检查依赖
bash scripts/bootstrap.sh --profile native-x86-2404 --dry-run
sudo bash scripts/bootstrap.sh --profile native-x86-2404 --apply

# 2. 构建核心工作空间
ROS_DISTRO=jazzy bash scripts/build_core.sh

# 3. 运行smoke测试
bash scripts/run_smoke_workload.sh all 8
```

### RDK X5 (ARM64)

```bash
# 预检查
bash scripts/bootstrap_x5.sh --dry-run
python3 scripts/preflight_x5.py --mode software

# 排练物理CAN演示（双接口）
python3 scripts/run_x5_demo.py \
  --dry-run \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --output-dir data/raw/demos/x5_plan_01
```

---

## 典型用例

### 案例1: 定位200ms+延迟峰值

**症状**: 机器人控制回调偶现200ms延迟

**诊断**:
```bash
# 1. 采集跨层trace（应用+ROS 2+内核）
bash scripts/capture_traces.sh

# 2. 构建证据图
python3 diagnosis/build_evidence_graph.py

# 3. 推断根因
python3 diagnosis/infer_root_cause.py
```

**结果**: 定位到shared_ptr析构阻塞 → 优化内存管理策略

---

### 案例2: 拒绝输出（TID生命周期断裂）

**症状**: ros2_tracing显示50ms，eBPF显示10ms，差40ms

**诊断结果**:
```json
{
  "status": "INSUFFICIENT_EVIDENCE",
  "missing": ["TID lifecycle tracking"],
  "reason": "TID changed mid-callback (12345 → 12346)",
  "suggestion": "Enable TID fork/exit tracing"
}
```

**为什么拒绝**: DDS线程池导致TID动态变化，证据链断裂 → 输出错误根因比说"不知道"更危险

---

## 正式实验结果

### F3/F4原生Linux结果

冻结Ubuntu 24.04 / Jazzy测试分区，完成40次运行（10对F3 + 10对F4）

| 案例 | 控制组 | 注入组 | 结论 |
| --- | --- | --- | --- |
| F3调度压力 | 95.30%完整恢复 | 67.56% | 压力降低恢复率；完整样本有选择偏差 |
| F4 100ms服务阻塞 | 0.875ms中位数 | 101.212ms | 成对中位数增加约100.337ms |

**证据包**: [docs/evidence/native-f3f4-formal-v3/](docs/evidence/native-f3f4-formal-v3/)

---

### WSL2路径关联评估

Humble重叠日志支持运行级held-out评估（校准01-05，held-out 06-10）

| Held-out场景 | Oracle traces | Precision | Recall | F1 | 95% CI |
| --- | --- | --- | --- | --- | --- |
| 双路10Hz | 6,024 | 1.0000 | 0.9772 | 0.9884 | [0.9793, 0.9939] |
| 双路混合速率 | 5,178 | 1.0000 | 1.0000 | 1.0000 | [1.0000, 1.0000] |

---

## 仓库结构

```
ros2_core/       ROS 2 Humble包和launch文件
diagnosis/       证据适配器、关联、图构建、推断
experiments/     故障目录、受控运行器、成对比较
optimizer/       动作约束、搜索计划、目标、验证
scripts/         构建、采集、smoke、实验入口
tests/           单元和契约测试
docs/            公开schema、环境说明、迁移参考
```

---

## 技术亮点

### 1. 跨层证据适配器

统一三层数据源到同一时间线：

```python
# RuntimeEvent v2（应用层）
adapters.runtime_event_adapter()

# ros2_tracing（中间件层）
adapters.ros2_tracing_adapter()

# eBPF scheduling（内核层）
adapters.ebpf_sched_adapter()
```

### 2. 证据图推断

构建类型化证据图 → 冲突处理 → 拒绝或输出根因

```python
graph = build_evidence_graph(traces)
result = infer_root_cause(graph)

if result.confidence < THRESHOLD:
    return "INSUFFICIENT_EVIDENCE"
```

### 3. 成对实验协议

```bash
# 控制组/注入组各10次
python3 scripts/run_formal_experiment_session.py \
  --case diagnosis_f4_control \
  --case diagnosis_f4_injected \
  --dataset-role test \
  --seed 20260729
```

---

## 证据边界

### ✅ 已验证

- 原生Linux F3/F4正式结果（40次运行）
- WSL2路径关联held-out评估（F1 0.9884/1.0000）
- X5物理CAN smoke（34发送/34 ACK/100%匹配）

### ⚠️ 未验证

- Held-out多类诊断准确率
- 运行时开销全面评估
- 优化收益量化
- ECU HIL行为
- 执行器安全性

---

## 项目演进

RoboTraceOpt整合了[ROS2Probe](https://github.com/Quchaosheng/ROS2Probe)和[RoboTraceRT](https://github.com/Quchaosheng/RoboTraceRT)的工程工作。

---

## License

MIT License - 详见 [LICENSE](LICENSE)

---

**为什么选择RoboTraceOpt？**

传统工具（perf/ftrace/Perfetto）只看单层，手工关联耗时且易错。RoboTraceOpt自动融合三层证据，在证据不足时拒绝推测，避免误导性根因。

如果你在构建可靠的ROS 2机器人系统，需要确定性的延迟诊断，RoboTraceOpt是你的工具。
