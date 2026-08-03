# WSL2 RuntimeEvent Proxy Overhead Evidence

This package contains a sanitized, run-level recomputation of an existing ROS2Probe campaign. It is **limited paper-supporting evidence**, not the missing native four-mode RoboTraceOpt overhead experiment.

## What it supports

- Ubuntu 22.04 / ROS 2 Humble on WSL2.
- RuntimeEvent disabled, buffered, and per-event flush modes.
- Nominal 5 Hz and stress 20 Hz workloads.
- Ten 60-second runs per condition.
- Process CPU, peak RSS, output rate, and enabled-mode internal latency/completeness summaries.

## What it does not support

- Native Linux overhead.
- RuntimeEvent-only vs ros2_tracing vs full fused comparison.
- A latency delta against disabled mode, which has no RuntimeEvent latency output.
- A randomized causal estimate: conditions were captured in blocks and the source tree was dirty.

`results/run_metrics.csv` is the source for the figure and summary. Bootstrap intervals resample whole runs. Raw event logs are intentionally excluded; `results/source_artifact_hashes.json` binds the recomputation to the local source artifacts without exposing local paths.
