# C++ 重构路线

RoboTraceOpt 采用渐进式混合架构，而不是一次性逐行翻译 Python。目标是把实时路径、
高吞吐数据处理和可复用算法迁到 C++17，同时保留 ROS launch、实验编排和报告等低频
控制面脚本。这样可以降低迁移风险，也不会破坏现有实验的可审计性。

## 当前边界

当前生产代码约有 22,705 行 Python 和 3,334 行 C++。Python 的主要分布如下：

| 区域 | 规模 | 目标 |
| --- | ---: | --- |
| `scripts/` | 7,010 行 | 保留为薄 CLI 和实验编排 |
| `diagnosis/` | 5,983 行 | 迁移 schema、关联、证据图及高吞吐适配器 |
| `experiments/` | 4,574 行 | 保留协议/runner；后续迁移时序敏感的 CAN 采集 |
| ROS 2 Python 包 | 3,074 行 | 优先迁移 planner 实时路径，保留 launch |
| `optimizer/` | 1,862 行 | 迁移确定性算法，保留文件和进程编排 |
| `reporting/` | 202 行 | 保留 |

`vlm_planner_node.py` 和 `planner_clients` 是唯一位于 ROS 回调关键路径上的 Python
实现。诊断、优化和实验代码大多运行在离线控制面，因此它们的迁移顺序由吞吐、复用
价值和接口稳定性决定，而不是只看行数。

## 迁移阶段

### 阶段一：可并存的 C++ 核心

- 建立无 ROS、无第三方依赖的 `cpp_core` CMake 工程。
- 迁移 planner 请求/结果、decision 校验、admission 和 fail-closed 契约。
- 迁移 `NormalizedEvent`、stage window、关联和强约束证据图模型。
- 迁移 runtime objective、诊断引导采样和配对 bootstrap 验证。
- 用 CTest 固定输入校验、边界条件和确定性行为。

阶段一不删除 Python，也不改变现有 ROS 2 节点默认实现。C++ 和 Python 将暂时作为
双实现存在，方便用相同 fixture 做差分测试。

### 阶段二：接入运行路径

- 新增 `rclcpp` planner node，并冻结原 package、executable、topic、message 和参数名。
- Python 与 C++ planner 同包安装；launch 通过实现开关选择，初期默认 Python。
- shadow 运行时将 C++ 输出 remap 到独立 topic，只比较事件和命令，不进入 CAN。
- 为 runtime/tracetools/eBPF/SocketCAN 增加 C++ JSONL adapter CLI。
- Python inference 和 experiment runner 通过稳定 JSONL/JSON schema 调用 C++ CLI。

HTTP backend 需要 `libcurl` 和严格的 JSON canonicalization。接入前必须用 golden
fixture 验证 hash、record/replay、错误分类、代理和脱敏行为，不能只验证“请求成功”。

### 阶段三：替换与清理

- 迁移 SocketCAN capture/responder 和剩余高吞吐 adapter。
- 按实际性能收益选择性迁移 inference、candidate validation 和 rollback。
- C++ planner 通过硬件与 held-out 验证后再成为默认实现。
- 至少保留一个发布周期的 Python reference，然后删除重复实时实现。

ROS launch、正式 experiment session、manifest/checksum、报告生成继续使用 Python。
这些代码是低频控制面，保留它们比移植为 C++ 更容易审计和维护；用户只需通过已有
命令使用，不需要直接修改 Python。

## 兼容性门槛

每次替换必须同时满足以下条件：

1. ROS topic、message、parameter、package 和 executable 名称保持兼容。
2. JSON/JSONL schema version、reason code 和 fail-closed 决策语义保持兼容。
3. admission 的 deadline、future-skew、dedup 和 failure-window 边界有 golden test。
4. 任何 admit、queue、backend、output 或 decision 失败都不得发布 motion command。
5. Python 与 C++ 的哈希、record/replay key 和有限浮点校验逐 fixture 对比。
6. 新旧实现产生的正式实验数据按 `code_version` 分区，不混合统计。
7. x86_64 与 X5 arm64 分别构建；ROS 2 Humble 和 Jazzy 不共享二进制产物。

## 不做的事情

- 不把 Python AST 或实现细节当作跨语言契约；只冻结外部行为和数据 schema。
- 不在第一阶段引入 pybind11 ABI。优先使用标准 C++ 库和稳定 CLI 边界。
- 不宣称 Windows 上的单元测试替代 Ubuntu/ROS 2 或 X5 的运行验证。
- 不在缺少完整 tracing、eBPF、CAN 和 identity 证据时重新解释历史实验结论。
