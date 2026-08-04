# F3 CPU 压力负结果：我测到了完整性下降，但没有测到干净的调度延迟因果效应

## 预期

我最初对 F3 的预期很直接：把 ROS 进程树与受控 `stress-ng` 工作线程固定到同一 CPU 后，CPU 竞争应当增加规划器主线程从 runnable 到 running 的等待时间，并进一步推高发布到回调 dispatch 的延迟。如果这个链条成立，我应该同时看到三类相互一致的信号：完整生命周期恢复率下降、身份绑定的 scheduler latency 整体右移，以及 RuntimeEvent 路径上界的中位数和尾部分位数共同上升。

早期 WSL 开发实验似乎支持这个方向。[故障注入说明](../../experiments/fault_injection/README.md)记录的 development pair `_04` 中，完整 proxy trace 从 control 的 496/687 降到 injected 的 53/601；dispatch 上界中位数比为 1.06，而 p90/p95/p99 比值达到 107.96/155.35/158.91。这是一条很强的工程告警，但不是正式 scheduler attribution：WSL 的 PID/内核 task identity 不可比，适配器也明确输出 `formal_scheduling_attribution=false`，见 [scheduler pressure adapter](../../diagnosis/adapters/scheduling_pressure_adapter.py) 与 [diagnosis 说明](../../diagnosis/README.md)。因此，我把它当作“尾部 dispatch 与完整性可能恶化”的开发代理，而不是原结论的证明。

## 实验设计

正式实验使用 [native F3/F4 formal package](../evidence/native-f3f4-formal-v3/README.md)：Ubuntu 24.04、ROS 2 Jazzy、native Linux，dataset role 为 `test`，会话完整性为 `complete`。整个 F3/F4 矩阵 40/40 case 成功执行；F3 包含 control 与 injected 各 10 次配对重复，固定 seed 为 `20260729`。这里的“40/40”表示 F3/F4 全矩阵的执行成功，不等于每一条业务生命周期都完整恢复。

F3 injected 条件在目标 CPU 上加入受控压力。正式分析一方面统计 RuntimeEvent 完整路径，另一方面从 eBPF `sched_wakeup` 到 `sched_switch` 构造规划器主线程的身份绑定间隔。后者要求 `process_manifest.kernel_pid == eBPF tid/next_tid`，细节见 [scheduler analysis](../evidence/native-f3f4-formal-v3/results/scheduler_analysis.json)。我以 run 为配对单位，而不是把所有事件池化后假装彼此独立；同时保留缺失路径、采集时长、wakeups 数量和尾部分位数，因为这些量决定“幸存样本”是否还能代表原总体。

## 结果

最稳固的正式结果是完整路径恢复率从 95.30% 降到 67.56%。原始汇总为 control 7003/7348、injected 4653/6887；配对 complete-rate 差异中位数为 -0.437，95% bootstrap CI 为 [-0.458, -0.017]。这些数字可在 [analysis summary](../evidence/native-f3f4-formal-v3/results/analysis_summary.md)和 [paired statistics](../evidence/native-f3f4-formal-v3/results/paired_statistics.json)中交叉复核。

但 latency 没有按原预期形成干净、同向的证据。完整样本中的 dispatch 上界中位数反而从 0.5115 ms 降到 0.2597 ms；与此同时 p95 从 0.879 ms 升到 3.013 ms，p99 从 14.684 ms 升到 53.183 ms。身份绑定 scheduler 样本也呈现较低的 pooled median：57.989 us 降到 9.100 us，10 个配对 run 中 9 个为负差；可是 injected 只留下 2745 个匹配 wakeup-switch，而 control 有 7970 个，且多次 injected capture 约 2.0-2.3 秒，control 多为 5.6-6.1 秒。分析文件最终明确标记 `trace_level_attribution=false`。

所以我得到的是一个负结果：CPU 压力显著破坏了端到端证据完整性，并伴随 dispatch 尾部膨胀；我没有得到“CPU 压力使 scheduler latency 整体上升”的干净因果估计。

## 为什么不能得出原结论

第一，缺失不是可忽略的小噪声。injected 条件有 2234 条不完整生命周期，完整率下降近 28 个百分点。只有完成并能配对的 trace 才进入路径延迟统计，压力下最慢、被截断或未完成的请求更可能被排除，于是中位数下降完全可能是选择偏差，而不是系统变快。

第二，scheduler 分析只覆盖被观测到且成功匹配的 runnable-to-running 片段。其 match rate 接近 1，只说明“进入该分析的 wakeup 基本找到了 switch”，不说明没有进入捕获窗口的生命周期、未产生可用 wakeup 的阶段或提前终止的路径不存在。事件数量与 capture duration 的系统性差异使 control/injected 的暴露时间不等价。

第三，指标并不等价。RuntimeEvent 的 `dispatch_upper_bound_ns` 包含传输与回调 dispatch 上界；eBPF 间隔只测规划器主线程的一段调度等待。二者都不能单独覆盖完整因果链。正式数据的中位数下降、尾部上升和完整性下降共同指向异质响应：多数“幸存”事件很快，少数事件很慢，另一些路径直接缺失。把这种结果压缩成单一 scheduler latency 增长，会掩盖最重要的工程事实。

第四，早期 WSL proxy 不能补上这个缺口。它能帮助我提出“尾部 dispatch 与完整性受压”的假设，但由于身份不可比、环境为虚拟化内核且证据契约明确限制为 development，它不能被冒充为 native formal scheduler attribution。

## 下一步实验

下一轮我会优先修正可辨识性，而不是简单增加重复次数。首先，把 control 与 injected 的 eBPF 捕获改为固定墙钟窗口，并在窗口外设置对称 warm-up/cool-down，确保相同暴露时间；同时记录启动、停止和缓冲区丢失原因。其次，为每个请求预注册 expected lifecycle，并把“完整、右删失、捕获丢失、应用未完成”分层统计，使用删失感知分析，禁止只比较完整样本。

然后，我会把 scheduler latency 与同一 trace 的端到端阶段做一对一连接，至少报告每个 run 的 wakeup 数、CPU runnable queue、调度尾部、dispatch 尾部和完整率，并按压力强度做 0%、30%、60%、90% 剂量梯度。如果延迟尾部随剂量单调上升、缺失机制可解释，且固定窗口下 identity-bound scheduler 指标与 dispatch 尾部在 run 级共同变化，我才会重新讨论 scheduler 因果归因。否则，F3 的正式结论仍应停留在“同核 CPU 压力降低完整路径恢复率，并暴露尾部 dispatch 风险”。

## 复核命令

```bash
python3 -m json.tool docs/evidence/native-f3f4-formal-v3/results/scheduler_analysis.json
python3 -m json.tool docs/evidence/native-f3f4-formal-v3/results/paired_statistics.json
python3 scripts/analyze_f3_scheduler_latency.py --help
rg -n "95.30|67.56|40/40|formal_scheduling_attribution|trace_level_attribution|107.96" docs experiments diagnosis
sha256sum -c docs/evidence/native-f3f4-formal-v3/SHA256SUMS.txt
```
