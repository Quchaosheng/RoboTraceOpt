# Native x86 F3/F4 Analysis

- Platform: `native-x86-ubuntu-24.04-jazzy`
- Dataset role: `test`
- Development only: `false`
- Formal inference allowed: `true`
- Cases: 40

| Fault | Variant | Runs | Complete/Observed | Rate | eBPF events |
|---|---|---:|---:|---:|---:|
| F3 | control | 10 | 7003/7348 | 0.9530 | 1849383 |
| F3 | injected | 10 | 4653/6887 | 0.6756 | 612620 |
| F4 | control | 10 | 382/383 | 0.9974 | 30413 |
| F4 | injected | 10 | 380/383 | 0.9922 | 31064 |

## Median comparisons

| Fault | Metric | Control ms | Injected ms | Ratio |
|---|---|---:|---:|---:|
| F3 | `dispatch_upper_bound_ns` | 0.5115 | 0.2597 | 0.508 |
| F3 | `zero_work_callback_elapsed_ns` | 0.1902 | 0.0593 | 0.312 |
| F3 | `planner_path_upper_bound_ns` | 1.2398 | 0.4866 | 0.392 |
| F4 | `server_processing_elapsed_ns` | 0.0092 | 100.1879 | 10831.708 |
| F4 | `request_response_elapsed_ns` | 0.8749 | 101.2119 | 115.687 |
| F4 | `pre_server_elapsed_ns` | 0.5074 | 0.4977 | 0.981 |
| F4 | `post_server_elapsed_ns` | 0.3525 | 0.5245 | 1.488 |

This session is retained as the formal native Ubuntu 24.04/Jazzy test partition. F4 supports formal application-level blocking-delay inference; F3 remains a scheduling-pressure proxy and does not establish syscall- or scheduler-level causal attribution.
