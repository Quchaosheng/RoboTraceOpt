# RoboTraceOpt

[English](README.md) | **简体中文**

[![CI](https://github.com/Quchaosheng/RoboTraceOpt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Quchaosheng/RoboTraceOpt/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-2EA44F)](LICENSE)

RoboTraceOpt 用于分析 ROS 2 在应用层、中间件和 Linux 层的运行行为。它将跨层追踪、证据图诊断和受约束的配置优化组合成一条可审计的机器人系统分析流程。

显式适配器统一应用层 RuntimeEvent、ROS 2 trace 与 Linux 运行时证据。诊断层构建带类型的证据图；证据不足或互相冲突时，系统会保留不确定性并拒绝强行输出根因。只有与已诊断原因匹配的动作，才允许进入优化试验。

## 仓库内容

- 三种 ROS 2 工作负载的 RuntimeEvent v2 埋点。
- RuntimeEvent、<code>ros2_tracing</code>、eBPF 调度记录和 SocketCAN/vcan ACK 生命周期适配器。
- 受拓扑约束的 trace-stage 关联与带类型证据图。
- 支持冲突处理和拒绝判断的可审计根因推断。
- 有界动作注册表，以及可复现的引导、随机和无引导搜索协议。
- 候选配置验证与离线回滚决策。
- 平衡重复实验和配对 bootstrap 置信区间。
- 用于 F1-F6 故障特征开发验证的实验 runner。

## 仓库结构

~~~text
ros2_core/     ROS 2 Humble 包与 launch 文件
cpp_core/      可移植的 C++17 planner、诊断与优化库
diagnosis/     证据适配、关联、证据图构建和推断
experiments/   故障目录、受控 runner 与配对比较
optimizer/     动作约束、搜索计划、目标函数和验证
scripts/       构建、采集、冒烟和实验入口
tests/         单元测试与契约测试
docs/          公共 schema、环境说明和迁移参考
~~~

## 可移植 C++ 核心

第一阶段 C++ 重构位于 [`cpp_core`](cpp_core/)：包含 planner 安全契约、trace-stage
诊断、证据图和确定性优化的无第三方依赖 C++17 库，并提供统一 CMake、CTest、安装
导出和跨模块示例。

~~~bash
cmake -S cpp_core -B build/cpp-core -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp-core --parallel
ctest --test-dir build/cpp-core --output-on-failure
~~~

在适配层和 shadow-mode 验证完成前，当前 Python/ROS 2 实现仍是默认路径。分阶段替换
顺序和兼容门槛见 [`docs/CPP_MIGRATION.md`](docs/CPP_MIGRATION.md)。

## RDK X5 准备

X5 环境配置、双适配器物理 CAN 接线、pilot 执行、简短答辩演示和恢复步骤见 [X5_RUNBOOK](docs/hardware/X5_RUNBOOK.md)。必需的采集产物、CANable/SLCAN 分支和结论边界见 [PHYSICAL_CAN_EVIDENCE](docs/hardware/PHYSICAL_CAN_EVIDENCE.md)。

预览软件包安装并执行只读软件预检：

~~~bash
bash scripts/bootstrap_x5.sh --dry-run
python3 scripts/preflight_x5.py --mode software
~~~

当两路物理 CAN 接口均为 UP 时，可以在不启动工作负载的情况下预演完整流程：

~~~bash
python3 scripts/run_x5_demo.py \
  --dry-run \
  --runtime-interface can0 \
  --peer-interface can1 \
  --bitrate 500000 \
  --output-dir data/raw/demos/x5_plan_01
~~~

当前物理结果是带 responder peer 的双接口 SocketCAN 冒烟测试。它属于开发证据，不是 ECU HIL 结果，也不能替代冻结的原生 X5 tracing/eBPF 矩阵。在报告 F6 诊断或性能结论前，仍需保留一组满足采集契约的 normal/drop 对照。

## 环境

主要开发环境是 Ubuntu 22.04 与 ROS 2 Humble。核心工作区可在 WSL 或原生 Ubuntu 构建：

~~~bash
bash scripts/build_core.sh
source ~/.cache/robotraceopt_build/install/setup.bash
~~~

仓库严格区分以下环境：

| 分区 | 环境 | 支持的结论 |
| --- | --- | --- |
| 开发与 WSL 证据 | Ubuntu 22.04 / ROS 2 Humble | WSL 冒烟、关联、RuntimeEvent proxy 与就绪检查 |
| 归档的原生 F3/F4 候选 | Ubuntu 24.04 / ROS 2 Jazzy | 仅保留工具和候选文件，不接受已完成的原生结论 |
| X5 硬件路径 | arm64 Ubuntu 22.04.5 / ROS 2 Humble | X5 软件、物理 CAN 准备及单独合格的硬件冒烟 |

Humble 工作区是开发和论文基线。Jazzy 目前只有面向未来资格验证的 provisioning、capability 与 runner 工具。Jazzy 负向预检只是环境 guard，不是 Jazzy 工作负载结果。不同环境产生的结果不能合并统计。

运行迁移后的工作负载：

~~~bash
bash scripts/run_smoke_workload.sh all 8
~~~

运行 Python 测试：

~~~bash
python3 -m unittest discover -s tests -q
~~~

完整的优化器回归命令保留在英文 README 中，CI 还会执行 Ruff、Python 编译检查和 ROS 2 Humble 工作区构建测试。

## AI planner 可靠性

AI planner 通过同一套带版本的请求/结果契约支持显式 mock、OpenAI-compatible 和确定性 replay 后端。按配置只记录规范化决策证据，拒绝过期或重复输出，并在最终 CAN guard 前按 fail-closed 方式终止。配置、回放、故障 campaign 和“命令送达不等于任务完成”的区别见 [OpenAI-compatible proxy 配置](docs/ai/OPENAI_COMPATIBLE_PROXY_SETUP.md)。

默认视觉模式只发送 metadata；只有 <code>payload_base64</code> 配置了真实 JPEG、PNG 或 WebP 数据时才会发送图像字节。mock camera 不构成真实 VLM 实验。

<code>replay</code> 是已实现的后端，而不仅是 launch 参数。<code>ReplayPlannerClient</code> 会回放规范化决策 JSONL，并对唯一匹配、歧义拒绝和 ROS 发布前校验进行测试。它不回放原始模型或图像输入；当前 checkout 没有 <code>data/</code> 下的录制文件，因此必须由先前运行提供 recording。

## 证据边界

生成的原始和处理后实验数据不会提交到 Git。开发证据与 calibration、held-out test 分区保持分离。仅有 RuntimeEvent 或 vcan 的结果会标为 proxy evidence，不能表述为正式 syscall、scheduler 或物理 CAN 归因。

<code>physical_can_evidence=true</code> 只证明被记录的物理 SocketCAN 传输路径；它本身不是 ECU HIL、功能安全、执行器或正式实验结果。仓库只包含实现和公开技术文档，私有研究材料与本地实验数据不在仓库中。

### 当前 checkout 的产物状态

当前 checkout 没有 <code>data/</code> 目录，Git 在该目录下跟踪的路径数为 0。README 和 runbook 中的命令会在 <code>data/raw/</code>、<code>data/processed/</code> 或 <code>data/reports/</code> 创建本地忽略文件；这些文件不存在不等于实验结果为 0。

已提交的结果产物是 [docs/evidence](docs/evidence/) 下经过清理的公开投影。每个包都带有自己的 manifest 与结论边界。

## 归档的原生 F3/F4 候选包

[历史 native F3/F4 路径](docs/evidence/native-f3f4-formal-v3/) 为兼容性和审计历史而保留。公开投影没有包含重新判定该 session 所需的原始 CTF、ROS 2、RuntimeEvent、bpftrace/eBPF 和逐事件身份记录，因此不能证明原生正式实验已经完成。

不能将归档中的计数、图表或 metadata 引用为原生执行、F3/F4 配对效应、调度器或 syscall 归因、诊断准确率、优化收益、ECU HIL 行为或执行器安全结论。未来的原生结论必须来自新的干净 session，并让原始产物、环境报告、身份映射、manifest 和 checksum 通过当前资格契约。

## WSL2 run-held-out 关联评估

早期 WSL2 / Ubuntu 22.04 / ROS 2 Humble 重叠日志支持一项独立的 run-held-out 路径关联评估。每种场景使用 run 01-05 校准时间戳基线，run 06-10 留作测试。预测器只接收事件身份、trace ID、sequence ID、stage 和 timestamp；oracle identity 在生成公共分组后才连接。

| held-out 场景 | Oracle traces | <code>trace_id_contract</code> precision | Recall | F1 | run-bootstrap 95% F1 CI |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dual 10 Hz | 6,024 | 1.0000 | 0.9772 | 0.9884 | [0.9793, 0.9939] |
| Dual mixed-rate | 5,178 | 1.0000 | 1.0000 | 1.0000 | [1.0000, 1.0000] |

这些结果是关联和路径有效性证据，不是 F1-F6 根因分类。各 run 共用同一主机和启动过程，使用 mock-mode delay，并记录了 commit <code>65273ea</code> 上的 dirty source tree。因此它们只能作为有限的 WSL2 关联证据，不能补齐原生执行、held-out 诊断或正式优化缺口。

完整公开包见 [run-held-out association package](docs/evidence/wsl-heldout-association-20260731/)。逐行预测仍保留在私有审计副本中。

## 有限的辅助证据

- [WSL2 RuntimeEvent proxy-overhead 包](docs/evidence/wsl-runtimeevent-overhead-20260712/)包含 60 个整段运行摘要：在标称 5 Hz 和压力 20 Hz 下分别测试 disabled、buffered 与 per-event flush。该 block-ordered、dirty-tree WSL2 campaign 不是原生或四模式 tracing/fused 证据。
- [X5 physical-CAN smoke 包](docs/evidence/x5-physical-can-smoke-20260727/)保留一次 40 秒 arm64 PREEMPT_RT 采集：34 次发送、34 次匹配 ACK、100% payload match，send-to-ACK P50/P95 为 6.039 ms / 6.238 ms。planner 使用 mock 且没有 drop/timeout 对照，因此它既不是 ECU HIL，也不能证明当前 fail-closed model runtime。

每个公开结果包的 manifest 与结论边界见 [公共证据索引](docs/evidence/)。

## 项目沿革

RoboTraceOpt 将 [ROS2Probe](https://github.com/Quchaosheng/ROS2Probe) 与 [RoboTraceRT](https://github.com/Quchaosheng/RoboTraceRT) 的工程工作整合到一个持续维护的代码库中。

## 正式实验就绪流程

正式 session 协议会在 ROS 2 进程启动前冻结选定的 Chapter 6 case。source ROS 2 和构建后的工作区后，先生成只读平台报告：

~~~bash
python3 scripts/check_platform_capabilities.py \
  --label x86-wsl \
  --output-json data/raw/environment/x86-wsl.json
~~~

当前 WSL 开发环境只能预演 capability report 标记为 ready 的 case。英文 README 中的 42-run dry-run 命令只生成计划，不启动工作负载，也不包含测量证据。即使单项工具可用，WSL 仍会拒绝 <code>calibration</code> 和 held-out <code>test</code> role。

### 故障证据提交点

成功的正式 fault case 最后写入 <code>artifact_manifest.json</code>。manifest 列出该故障必需的 RuntimeEvent、run/oracle/command、identity、tracing、eBPF、scheduler 和 summary 产物，并为每个文件或 CTF 目录记录 SHA-256。外层 session 在接收 case 前验证 manifest，并在每次完整性重建时重新校验嵌套产物。

F3/F4 会在 workload window 内真正调用 eBPF collector，而不是只检查工具是否安装。只有实时 <code>process-manifest/v2</code> 报告 <code>ebpf_identity_status=comparable</code> 时才开始采集；runner 不会回退到按进程名匹配。F2/F3/F5 在 CTF 采集后执行完整 ROS 2 trace export。

这些实现补齐的是合格 session 的产物接收契约，不会把 tool-ready 或 WSL capture 变成原生证据，也不建立 X5 测量结果。正式结论仍需要合格的原生 Linux 或 X5 <code>test</code> session 与真实产物。

实际 X5 held-out 命令、<code>--resume</code> 语义和正式矩阵范围见英文 README 与 X5 runbook。恢复会核对 manifest sidecar、matrix、capability report、Git commit、role、seed 和 session name；成功、失败和中断的 case 都是终态，不会原地重跑。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
