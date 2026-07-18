import unittest
from unittest.mock import patch

from scripts.check_platform_capabilities import (
    classify_readiness,
    find_tracefs,
    parse_can_interfaces,
    render_markdown,
    tracing_capability_available,
)


class PlatformCapabilityTest(unittest.TestCase):
    def test_find_tracefs_skips_inaccessible_candidates(self) -> None:
        with patch("pathlib.Path.is_dir", side_effect=[PermissionError, False]):
            self.assertIsNone(find_tracefs())

    def test_tracing_capability_rejects_compiled_out_provider(self) -> None:
        trace_help = {"available": True, "returncode": 0}
        disabled_status = {
            "available": True,
            "returncode": 1,
            "stdout": "Tracing disabled",
        }

        self.assertFalse(tracing_capability_available(trace_help, disabled_status))

    def test_tracing_capability_accepts_enabled_provider(self) -> None:
        trace_help = {"available": True, "returncode": 0}
        enabled_status = {
            "available": True,
            "returncode": 0,
            "stdout": "Tracing enabled",
        }

        self.assertTrue(tracing_capability_available(trace_help, enabled_status))

    def test_tracing_capability_rejects_a_missing_tracetools_package(self) -> None:
        trace_help = {"available": True, "returncode": 0}
        missing_status = {
            "available": True,
            "returncode": 1,
            "stdout": "Package 'tracetools' not found",
        }

        self.assertFalse(tracing_capability_available(trace_help, missing_status))

    def test_ignores_empty_iproute2_can_placeholders(self) -> None:
        result = {
            "available": True,
            "returncode": 0,
            "stdout": '[{}, {}, {"ifname": "vcan0"}]',
        }

        self.assertEqual(parse_can_interfaces(result), [{"ifname": "vcan0"}])

    def test_prefers_core_ebpf_when_kernel_and_tool_checks_pass(self) -> None:
        readiness = classify_readiness(
            {
                "ros2_runtime": True,
                "tracetools": True,
                "btf": True,
                "sched_switch_tracepoint": True,
                "bpftool_probe": True,
                "can_interface": True,
                "can_utils": True,
                "cpu_governor_visible": True,
                "time_sync_reported": True,
                "scheduling_tools": True,
            }
        )

        self.assertEqual(readiness["ebpf"]["status"], "ready")
        self.assertEqual(readiness["ebpf"]["path"], "libbpf_core")
        self.assertEqual(readiness["ros2_tracing"]["status"], "ready")
        self.assertEqual(readiness["socketcan"]["status"], "ready")
        self.assertEqual(readiness["scheduling_tools"]["status"], "ready")

    def test_reports_tracefs_only_instead_of_claiming_ebpf_support(self) -> None:
        readiness = classify_readiness(
            {
                "ros2_runtime": True,
                "tracetools": False,
                "btf": False,
                "sched_switch_tracepoint": True,
                "bpftool_probe": False,
                "can_interface": False,
                "can_utils": False,
                "cpu_governor_visible": False,
                "time_sync_reported": False,
                "scheduling_tools": False,
            }
        )

        self.assertEqual(readiness["ebpf"]["status"], "partial")
        self.assertEqual(readiness["ebpf"]["path"], "tracefs_only")
        self.assertEqual(readiness["ros2_tracing"]["status"], "blocked")
        self.assertEqual(readiness["socketcan"]["status"], "blocked")
        self.assertEqual(readiness["cross_host_clock"]["status"], "blocked")
        self.assertEqual(readiness["scheduling_tools"]["status"], "blocked")

    def test_markdown_exposes_evidence_and_does_not_hide_blocked_checks(self) -> None:
        report = {
            "schema_version": 1,
            "generated_at_utc": "2026-07-15T00:00:00+00:00",
            "platform_label": "rk3568",
            "host": {"hostname": "rk", "machine": "aarch64", "kernel": "6.1"},
            "readiness": {
                "ebpf": {
                    "status": "blocked",
                    "path": "unavailable",
                    "reason": "No usable tracepoint was observed.",
                }
            },
            "evidence": {"kernel": {"btf_vmlinux": False}},
            "limitations": ["Board output is required before Phase 2 can close."],
        }

        markdown = render_markdown(report)

        self.assertIn("rk3568", markdown)
        self.assertIn("blocked", markdown)
        self.assertIn("btf_vmlinux", markdown)
        self.assertIn("Board output is required", markdown)


if __name__ == "__main__":
    unittest.main()
