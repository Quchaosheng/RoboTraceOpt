import unittest

from diagnosis.adapters.scheduling_pressure_adapter import (
    derive_scheduling_pressure_evidence,
)


EVENTS = (
    "camera_frame_published",
    "planner_receive",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
)


def runtime_event(
    trace_id: str,
    event_name: str,
    timestamp_ns: int,
    sequence_id: int,
    *,
    clock_id: str = "monotonic",
) -> dict:
    camera = event_name == "camera_frame_published"
    return {
        "trace_id": trace_id,
        "sequence_id": sequence_id,
        "source_node": "camera_mock_node" if camera else "vlm_planner_node",
        "stage": event_name,
        "timestamp_ns": timestamp_ns,
        "event_name": event_name,
        "pid": 10 if camera else 20,
        "tid": 10 if camera else 20,
        "host_id": "host-a",
        "clock_id": clock_id,
    }


def complete_trace(trace_id: str, sequence_id: int, base: int) -> list[dict]:
    offsets = (0, 100, 110, 130, 150)
    return [
        runtime_event(trace_id, event_name, base + offset, sequence_id)
        for event_name, offset in zip(EVENTS, offsets)
    ]


def process_manifest() -> dict:
    return {
        "schema_version": "process-manifest/v2",
        "host_id": "host-a",
        "git_commit": "a" * 40,
        "osrelease": "6.18.0-microsoft-standard-WSL2",
        "ebpf_identity_status": "not_comparable",
        "ebpf_identity_reason": "wsl_initial_pid_namespace_unavailable",
        "processes": [
            {"node": "camera_mock_node", "pid": 10},
            {"node": "vlm_planner_node", "pid": 20},
        ],
    }


def scheduler_manifest(variant: str = "injected") -> dict:
    process = {
        "allowed_cpus": [31],
        "policy": "SCHED_OTHER",
        "priority": 0,
    }
    return {
        "schema_version": "f3-scheduler-manifest/v1",
        "condition_variant": variant,
        "target_cpu": 31,
        "target_cpu_selection": "highest_allowed_cpu",
        "host_id": "host-a",
        "git_commit": "a" * 40,
        "ebpf_identity_status": "not_comparable",
        "ros_processes": {
            "camera_mock_node": {"pid": 10, **process},
            "vlm_planner_node": {"pid": 20, **process},
        },
        "stress": {
            "enabled": variant == "injected",
            "command": ["stress-ng"] if variant == "injected" else [],
            "version": "stress-ng fixture",
            "pids": [30, 31] if variant == "injected" else [],
            "processes": (
                {
                    "stress_30": {"pid": 30, **process},
                    "stress_31": {"pid": 31, **process},
                }
                if variant == "injected"
                else {}
            ),
            "cleanup_status": (
                "graceful_sigint" if variant == "injected" else "not_applicable"
            ),
        },
    }


def oracle_manifest(variant: str = "injected") -> dict:
    return {
        "schema_version": "fault-oracle/v1",
        "fault_id": "F3",
        "condition_variant": variant,
        "cause_id": "scheduling_delay" if variant == "injected" else "none",
        "injection": {
            "stressors": 1,
            "cpu_load_percent": 90,
            "cpu_method": "matrixprod",
            "input_rate_hz": 100,
            "affinity": "same_cpu",
            "scheduler_policy": "SCHED_OTHER",
            "scheduler_priority": 0,
            "target_cpu": 31,
            "stress_enabled": variant == "injected",
        },
    }


def derive(records: list[dict], variant: str = "injected"):
    return derive_scheduling_pressure_evidence(
        records,
        process_manifest(),
        scheduler_manifest(variant),
        oracle_manifest(variant),
        runtime_source_file="runtime.jsonl",
        process_manifest_source_file="process.json",
        scheduler_manifest_source_file="scheduler.json",
        oracle_manifest_source_file="oracle.json",
    )


class SchedulingPressureAdapterTest(unittest.TestCase):
    def test_derives_three_non_formal_proxies_and_missingness(self) -> None:
        records = complete_trace("trace-1", 1, 1000)
        records.extend(complete_trace("trace-2", 2, 2000))
        records.append(runtime_event("trace-3", EVENTS[0], 3000, 3))

        events, report = derive(records)

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["observed_trace_count"], 3)
        self.assertEqual(report["complete_trace_count"], 2)
        self.assertEqual(report["incomplete_trace_count"], 1)
        self.assertEqual(report["metrics_ns"]["dispatch_upper_bound_ns"]["median"], 100)
        self.assertEqual(report["metrics_ns"]["zero_work_callback_elapsed_ns"]["median"], 20)
        self.assertEqual(report["metrics_ns"]["planner_path_upper_bound_ns"]["median"], 150)
        self.assertFalse(report["formal_scheduling_attribution"])
        self.assertEqual(report["ebpf_identity_status"], "not_comparable")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "scheduling_pressure_proxy")
        self.assertFalse(events[0].attributes["formal_scheduling_attribution"])

    def test_accepts_a_control_without_stress_processes(self) -> None:
        events, report = derive(complete_trace("trace-1", 1, 1000), "control")

        self.assertEqual(report["condition_variant"], "control")
        self.assertEqual(report["status"], "valid")
        self.assertEqual(len(events), 1)

    def test_rejects_wrong_affinity_and_missing_injected_stressor(self) -> None:
        scheduler = scheduler_manifest()
        scheduler["ros_processes"]["vlm_planner_node"]["allowed_cpus"] = [30, 31]
        events, report = derive_scheduling_pressure_evidence(
            complete_trace("trace-1", 1, 1000),
            process_manifest(),
            scheduler,
            oracle_manifest(),
            runtime_source_file="runtime.jsonl",
            process_manifest_source_file="process.json",
            scheduler_manifest_source_file="scheduler.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "ros_affinity_mismatch")

        scheduler = scheduler_manifest()
        scheduler["stress"]["pids"] = []
        events, report = derive_scheduling_pressure_evidence(
            complete_trace("trace-1", 1, 1000),
            process_manifest(),
            scheduler,
            oracle_manifest(),
            runtime_source_file="runtime.jsonl",
            process_manifest_source_file="process.json",
            scheduler_manifest_source_file="scheduler.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "stressor_not_observed")

    def test_excludes_clock_mismatch_and_negative_intervals(self) -> None:
        clock = complete_trace("clock", 1, 1000)
        clock[1]["clock_id"] = "realtime"
        negative = complete_trace("negative", 2, 2000)
        negative[3]["timestamp_ns"] = negative[2]["timestamp_ns"] - 1

        events, report = derive(clock + negative)

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_count"], 2)
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {"clock_or_host_mismatch": 1, "negative_proxy_interval": 1},
        )


if __name__ == "__main__":
    unittest.main()
