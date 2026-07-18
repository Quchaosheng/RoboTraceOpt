import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diagnosis.adapters.ebpf_adapter import (
    TaskIdentity,
    adapt_ebpf_jsonl,
    adapt_ebpf_record,
    load_process_identities,
)
from diagnosis.adapters.errors import AdapterReject


IDENTITIES = {
    101: TaskIdentity(pid=10, tid=101, kernel_pid=10, kernel_tid=101),
    102: TaskIdentity(pid=10, tid=102, kernel_pid=10, kernel_tid=102),
    202: TaskIdentity(pid=20, tid=202, kernel_pid=20, kernel_tid=202),
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROCESS_MANIFEST = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "fusion" / "w1_process_manifest.json"
)


def common_record(event_source: str) -> dict:
    return {
        "schema_version": "ebpf-runtime/v1",
        "event_source": event_source,
        "timestamp_ns": 123_456,
        "clock_id": "monotonic",
        "host_id": "host-a",
        "collector": "bpftrace",
        "collector_version": "0.14.0",
    }


class EbpfAdapterTest(unittest.TestCase):
    def test_v2_manifest_maps_kernel_tid_back_to_runtime_identity(self) -> None:
        manifest = {
            "schema_version": "process-manifest/v2",
            "ebpf_identity_status": "comparable",
            "processes": [
                {
                    "pid": 321,
                    "kernel_pid": 9000,
                    "tids": [321, 325],
                    "threads": [
                        {"tid": 321, "kernel_tid": 9000},
                        {"tid": 325, "kernel_tid": 9004},
                    ],
                }
            ],
        }
        identities = load_process_identities(manifest)
        record = common_record("sched_wakeup")
        record.update({"tid": 9004, "comm": "worker", "target_cpu": 2})

        event = adapt_ebpf_record(
            record,
            tid_to_pid=identities,
            source_file="ebpf.jsonl",
            record_index=1,
        )[0]

        self.assertEqual((event.pid, event.tid), (321, 325))
        self.assertEqual(event.attributes["kernel_tid"], 9004)

    def test_rejects_v2_manifest_without_comparable_kernel_identity(self) -> None:
        manifest = {
            "schema_version": "process-manifest/v2",
            "ebpf_identity_status": "not_comparable",
            "ebpf_identity_reason": "wsl_initial_pid_namespace_unavailable",
            "processes": [],
        }

        with self.assertRaises(AdapterReject) as context:
            load_process_identities(manifest)

        self.assertEqual(
            context.exception.reason_code, "identity_domain_not_comparable"
        )

    def test_cli_converts_with_frozen_process_manifest(self) -> None:
        manifest = json.loads(PROCESS_MANIFEST.read_text(encoding="utf-8"))
        process = manifest["processes"][0]
        record = common_record("sched_wakeup")
        record.update(
            {
                "host_id": manifest["host_id"],
                "tid": process["tids"][0],
                "comm": process["node"],
                "target_cpu": 1,
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "ebpf.jsonl"
            output_path = root / "normalized.jsonl"
            input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    "-m",
                    "diagnosis.adapters.ebpf_adapter",
                    "--input",
                    str(input_path),
                    "--process-manifest",
                    str(PROCESS_MANIFEST),
                    "--output",
                    str(output_path),
                ],
                cwd=REPOSITORY_ROOT,
                check=True,
            )
            normalized = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(normalized["source"], "ebpf")
        self.assertEqual(normalized["pid"], process["pid"])

    def test_rejects_duplicate_tid_in_process_manifest(self) -> None:
        manifest = {
            "schema_version": "process-manifest/v1",
            "processes": [
                {"pid": 10, "tids": [101]},
                {"pid": 20, "tids": [101]},
            ],
        }

        with self.assertRaises(AdapterReject) as context:
            load_process_identities(manifest)

        self.assertEqual(context.exception.reason_code, "identity_mismatch")

    def test_splits_switch_into_target_thread_out_and_in_events(self) -> None:
        record = common_record("sched_switch")
        record.update(
            {
                "prev_tid": 101,
                "prev_comm": "camera_node",
                "prev_state": 1,
                "next_tid": 202,
                "next_comm": "planner_node",
                "cpu_id": 3,
            }
        )

        events = adapt_ebpf_record(
            record,
            tid_to_pid=IDENTITIES,
            source_file="ebpf.jsonl",
            record_index=7,
        )

        self.assertEqual(
            [event.event_type for event in events],
            ["sched_switch_out", "sched_switch_in"],
        )
        self.assertEqual(
            [(event.pid, event.tid) for event in events], [(10, 101), (20, 202)]
        )
        self.assertEqual(events[0].attributes["counterpart_tid"], 202)
        self.assertEqual(events[1].attributes["counterpart_tid"], 101)
        self.assertEqual(events[0].provenance["record_index"], 7)

    def test_ignores_non_target_side_of_scheduler_switch(self) -> None:
        record = common_record("sched_switch")
        record.update(
            {
                "prev_tid": 0,
                "prev_comm": "swapper/0",
                "prev_state": 0,
                "next_tid": 101,
                "next_comm": "camera_node",
                "cpu_id": 0,
            }
        )

        events = adapt_ebpf_record(
            record,
            tid_to_pid=IDENTITIES,
            source_file="ebpf.jsonl",
            record_index=1,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "sched_switch_in")
        self.assertEqual(events[0].tid, 101)

    def test_adapts_wakeup_for_manifest_thread(self) -> None:
        record = common_record("sched_wakeup")
        record.update({"tid": 102, "comm": "camera_node", "target_cpu": 2})

        event = adapt_ebpf_record(
            record,
            tid_to_pid=IDENTITIES,
            source_file="ebpf.jsonl",
            record_index=2,
        )[0]

        self.assertEqual(event.event_type, "sched_wakeup")
        self.assertEqual((event.pid, event.tid), (10, 102))
        self.assertEqual(event.attributes["target_cpu"], 2)

    def test_adapts_syscall_interval_and_checks_manifest_identity(self) -> None:
        record = common_record("syscall")
        record.update(
            {
                "pid": 10,
                "tid": 101,
                "comm": "camera_node",
                "syscall_id": 202,
                "syscall_name": "futex",
                "ret": 0,
                "duration_ns": 8_000,
            }
        )

        event = adapt_ebpf_record(
            record,
            tid_to_pid=IDENTITIES,
            source_file="ebpf.jsonl",
            record_index=3,
        )[0]

        self.assertEqual(event.event_type, "syscall_interval")
        self.assertEqual(event.attributes["duration_ns"], 8_000)
        self.assertEqual(event.attributes["syscall_name"], "futex")

    def test_rejects_syscall_identity_mismatch(self) -> None:
        record = common_record("syscall")
        record.update(
            {
                "pid": 999,
                "tid": 101,
                "comm": "camera_node",
                "syscall_id": 1,
                "syscall_name": "write",
                "ret": 1,
                "duration_ns": 100,
            }
        )

        with self.assertRaises(AdapterReject) as context:
            adapt_ebpf_record(
                record,
                tid_to_pid=IDENTITIES,
                source_file="ebpf.jsonl",
                record_index=4,
            )

        self.assertEqual(context.exception.reason_code, "identity_mismatch")

    def test_rejects_non_monotonic_kernel_clock(self) -> None:
        record = common_record("sched_wakeup")
        record.update(
            {"clock_id": "unknown", "tid": 101, "comm": "node", "target_cpu": 1}
        )

        with self.assertRaises(AdapterReject) as context:
            adapt_ebpf_record(
                record,
                tid_to_pid=IDENTITIES,
                source_file="ebpf.jsonl",
                record_index=5,
            )

        self.assertEqual(context.exception.reason_code, "unknown_clock")

    def test_jsonl_adapter_preserves_line_provenance(self) -> None:
        wakeup = common_record("sched_wakeup")
        wakeup.update({"tid": 101, "comm": "node", "target_cpu": 1})
        lines = ["\n", json.dumps(wakeup) + "\n"]

        events = adapt_ebpf_jsonl(
            lines, tid_to_pid=IDENTITIES, source_file="ebpf.jsonl"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].provenance["record_index"], 2)


if __name__ == "__main__":
    unittest.main()
