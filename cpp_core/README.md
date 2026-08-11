# RoboTraceOpt C++ Core

`cpp_core` 是 RoboTraceOpt 第一阶段的 C++17 核心。它不依赖 ROS、Python 或第三方
库，可以在 Windows、普通 Linux、ROS 2 主机和 X5 arm64 上独立构建。

现有 Python/ROS 实现仍然保留。当前 C++ core 是经过单元测试的并行实现，还不是
`vlm_planner_node.py` 的默认替代品。

## 已迁移模块

| CMake target | 内容 |
| --- | --- |
| `RoboTraceOpt::planner` | planner 请求/结果、decision guard、时序 admission、Mock/Replay |
| `RoboTraceOpt::diagnosis` | NormalizedEvent、stage window、关联、W1/W2 topology、证据图 |
| `RoboTraceOpt::optimizer` | objective、动作约束、候选采样、bootstrap、候选验证 |

所有库都使用强类型 API。JSON/JSONL、HTTP 和 ROS 2 适配层负责把外部数据转换成这些
类型，核心库本身不读取文件、环境变量或网络。

## Windows 快速构建

需要 CMake、Ninja 和支持 C++17 的编译器。在 PowerShell 中运行：

```powershell
cd cpp_core
cmake --preset dev
cmake --build --preset dev
ctest --preset dev
.\build\dev\examples\robotraceopt_core_demo.exe
```

Release 构建只需把三条命令中的 `dev` 换成 `release`。

## Linux 快速构建

```bash
cmake -S cpp_core -B build/cpp-core -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp-core --parallel
ctest --test-dir build/cpp-core --output-on-failure
./build/cpp-core/examples/robotraceopt_core_demo
```

不需要测试和示例时：

```bash
cmake -S cpp_core -B build/cpp-core-lib \
  -DROBOTRACEOPT_BUILD_TESTS=OFF \
  -DROBOTRACEOPT_BUILD_EXAMPLES=OFF
cmake --build build/cpp-core-lib --parallel
```

## 安装和引用

```bash
cmake --install build/cpp-core --prefix /opt/robotraceopt-core
```

其他 CMake 工程可以通过 `find_package(RoboTraceOptCore CONFIG REQUIRED)` 引入，
再链接 `RoboTraceOpt::planner`、`RoboTraceOpt::diagnosis` 或
`RoboTraceOpt::optimizer`。

## 当前边界

- planner 尚未包含 OpenAI-compatible HTTP、图像编码、JSONL recording 和 ROS 2 node。
- diagnosis 尚未包含 trace/eBPF/SocketCAN JSONL adapter、callback identity 和 inference。
- optimizer 的 C++ bootstrap 使用固定 SplitMix64；判定语义与 Python 相同，但有限次数
  重采样的区间端点不保证与 Python MT19937 逐值相同。
- 正式实验切换实现后必须重新 calibration；新旧 `code_version` 的数据不能混合统计。

完整迁移顺序和兼容门槛见 [`docs/CPP_MIGRATION.md`](../docs/CPP_MIGRATION.md)。
