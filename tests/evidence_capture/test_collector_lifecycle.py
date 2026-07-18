from __future__ import annotations

import signal
import unittest
from pathlib import Path

from experiments.evidence_capture.collector_lifecycle import (
    EvidenceCaptureError,
    build_ebpf_capture_argv,
    needs_process_manifest,
    remaining_capture_duration,
    validate_ebpf_identity,
    validate_ebpf_summary,
)


class CollectorLifecycleTest(unittest.TestCase):
    def test_process_manifest_and_remaining_window_contract(self) -> None:
        self.assertFalse(needs_process_manifest({"runtime_event"}))
        self.assertTrue(needs_process_manifest({"runtime_event", "ros2_tracing"}))
        self.assertTrue(needs_process_manifest({"runtime_event", "ebpf"}))
        self.assertEqual(remaining_capture_duration(8.0, 1.5, shutdown_margin=0.5), 6.0)
        with self.assertRaises(EvidenceCaptureError) as context:
            remaining_capture_duration(8.0, 7.0, shutdown_margin=0.5)
        self.assertEqual(context.exception.reason_code, "insufficient_ebpf_window")

    def test_ebpf_identity_must_be_comparable_and_nonempty(self) -> None:
        validate_ebpf_identity(self._process_manifest())
        with self.assertRaises(EvidenceCaptureError) as context:
            validate_ebpf_identity(
                {
                    **self._process_manifest(),
                    "ebpf_identity_status": "not_comparable",
                }
            )
        self.assertEqual(
            context.exception.reason_code, "identity_domain_not_comparable"
        )
        with self.assertRaises(EvidenceCaptureError) as context:
            validate_ebpf_identity({**self._process_manifest(), "processes": []})
        self.assertEqual(context.exception.reason_code, "process_manifest_invalid")

    def test_builds_argv_without_a_shell_string(self) -> None:
        argv = build_ebpf_capture_argv(
            python=Path("/usr/bin/python3"),
            script=Path("/repo/scripts/capture_ebpf_runtime.py"),
            process_manifest=Path("/case/process_manifest.json"),
            duration=5.1254,
            output=Path("/case/ebpf_events.jsonl"),
            summary_output=Path("/case/ebpf_capture_summary.json"),
        )
        self.assertEqual(
            argv,
            [
                "/usr/bin/python3",
                "/repo/scripts/capture_ebpf_runtime.py",
                "--process-manifest",
                "/case/process_manifest.json",
                "--duration",
                "5.125",
                "--output",
                "/case/ebpf_events.jsonl",
                "--summary-output",
                "/case/ebpf_capture_summary.json",
            ],
        )
        self.assertNotIn("shell=True", argv)

    def test_validates_fault_specific_ebpf_counts(self) -> None:
        validate_ebpf_summary(self._summary(counts={"sched_switch": 4}), fault_id="F3")
        validate_ebpf_summary(self._summary(counts={"syscall": 2}), fault_id="F4")
        with self.assertRaises(EvidenceCaptureError) as context:
            validate_ebpf_summary(self._summary(counts={"syscall": 2}), fault_id="F3")
        self.assertEqual(context.exception.reason_code, "ebpf_scheduler_events_missing")
        with self.assertRaises(EvidenceCaptureError) as context:
            validate_ebpf_summary(
                self._summary(counts={"sched_switch": 2}), fault_id="F4"
            )
        self.assertEqual(context.exception.reason_code, "ebpf_syscall_events_missing")

    def test_rejects_unsuccessful_or_malformed_capture(self) -> None:
        for updates, reason in (
            ({"event_count": 0}, "ebpf_events_missing"),
            ({"malformed_line_count": 1}, "ebpf_events_malformed"),
            ({"bpftrace_returncode": 2}, "ebpf_collector_failed"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(EvidenceCaptureError) as context:
                    validate_ebpf_summary(
                        {**self._summary(counts={"sched_wakeup": 1}), **updates},
                        fault_id="F3",
                    )
                self.assertEqual(context.exception.reason_code, reason)

    @staticmethod
    def _process_manifest() -> dict:
        return {
            "schema_version": "process-manifest/v2",
            "host_id": "x5-a",
            "ebpf_identity_status": "comparable",
            "processes": [{"node": "planner", "pid": 10}],
        }

    @staticmethod
    def _summary(*, counts: dict[str, int]) -> dict:
        return {
            "schema_version": "ebpf-capture-summary/v1",
            "collector": "bpftrace",
            "collector_version": "0.14.0",
            "host_id": "x5-a",
            "duration_s": 5.0,
            "target_tid_count": 1,
            "target_pid_count": 1,
            "event_count": sum(counts.values()),
            "counts_by_type": counts,
            "malformed_line_count": 0,
            "raw_stdout_line_count": sum(counts.values()),
            "raw_stdout_sample": [],
            "bpftrace_returncode": -signal.SIGINT,
            "bpftrace_stderr": "",
        }


if __name__ == "__main__":
    unittest.main()
