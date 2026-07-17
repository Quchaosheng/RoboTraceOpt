# service_runtime_demo

This package provides a C++ ROS 2 request/response application for the journal-strengthening experiment.

The client sends `/runtime/query` requests with two identities:

- `TraceHeader`, used by the tracing workflow.
- `payload_id`, application business data used only as independent evaluation ground truth.

The server records `service_receive`, `service_process_start`, `service_process_end`, and `service_response`. The client records `query_sent` and `response_received`. Every RuntimeEvent carries `trace_id` and a monotonic `timestamp_ns`.

`fault_every_n` injects a deterministic source-context construction fault by changing the trace sequence while leaving `payload_id` unchanged. It does not model every possible context failure.

## Build

```bash
colcon build --packages-select ai_robot_runtime_interfaces runtime_logger_pkg service_runtime_demo
```

## Run

```bash
source install/setup.bash
ros2 launch service_runtime_demo service_runtime_demo.launch.py \
  request_rate_hz:=2.0 server_delay_ms:=50 runtime_events_enabled:=true
```

## Check

```bash
colcon test --packages-select service_runtime_demo --event-handlers console_direct+
python3 -m unittest src/runtime_analysis_tools/tests/test_service_experiment_contract.py -v
```

Expected output is one complete six-stage trace per successful request. This package is a controlled service experiment and does not represent deployed robot hardware.
