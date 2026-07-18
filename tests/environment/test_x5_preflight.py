import unittest

from scripts.preflight_x5 import evaluate_x5_readiness, render_x5_markdown


def capability_report() -> dict:
    return {
        "schema_version": 1,
        "platform_label": "rdk-x5",
        "host": {
            "system": "Linux",
            "machine": "aarch64",
            "is_wsl": False,
            "os_release": {"ID": "ubuntu", "VERSION_ID": "22.04"},
        },
        "readiness": {
            "ebpf": {"status": "ready"},
            "identity_comparable_ebpf": {"status": "ready"},
            "ros2_tracing": {"status": "ready"},
            "socketcan": {"status": "ready"},
        },
        "evidence": {
            "ros2": {"ros_distro": "humble"},
            "can": {
                "interfaces": [
                    {
                        "ifname": "can0",
                        "flags": ["UP", "LOWER_UP"],
                        "linkinfo": {
                            "info_kind": "can",
                            "info_data": {
                                "state": "ERROR-ACTIVE",
                                "bittiming": {"bitrate": 500000},
                            },
                        },
                    },
                    {
                        "ifname": "can1",
                        "flags": ["UP", "LOWER_UP"],
                        "linkinfo": {
                            "info_kind": "can",
                            "info_data": {
                                "state": "ERROR-ACTIVE",
                                "bittiming": {"bitrate": 500000},
                            },
                        },
                    },
                ]
            },
        },
        "provenance": {"git_commit": "a" * 40, "git_status": ""},
        "limitations": [],
    }


class X5PreflightTest(unittest.TestCase):
    def test_accepts_clean_native_humble_software_environment(self) -> None:
        result = evaluate_x5_readiness(capability_report(), mode="software")

        self.assertEqual(result["status"], "ready")
        self.assertTrue(all(check["ready"] for check in result["checks"]))

    def test_rejects_non_target_platform_ros_and_dirty_git(self) -> None:
        report = capability_report()
        report["host"].update({"machine": "x86_64", "is_wsl": True})
        report["host"]["os_release"]["VERSION_ID"] = "24.04"
        report["evidence"]["ros2"]["ros_distro"] = "jazzy"
        report["provenance"]["git_status"] = " M README.md"

        result = evaluate_x5_readiness(report, mode="software")
        failed = {check["name"] for check in result["checks"] if not check["ready"]}

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            failed,
            {"native_linux", "aarch64", "ubuntu_22_04", "ros2_humble", "git_clean"},
        )

    def test_physical_mode_requires_distinct_real_can_links(self) -> None:
        report = capability_report()
        report["evidence"]["can"]["interfaces"][1]["linkinfo"]["info_kind"] = "vcan"

        result = evaluate_x5_readiness(
            report,
            mode="physical-can",
            runtime_interface="can0",
            peer_interface="can1",
            bitrate=500000,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("physical_can_pair", result["failed_checks"])

    def test_markdown_keeps_blocking_reasons_visible(self) -> None:
        report = capability_report()
        report["host"]["machine"] = "x86_64"
        result = evaluate_x5_readiness(report, mode="software")

        markdown = render_x5_markdown(result)

        self.assertIn("blocked", markdown)
        self.assertIn("aarch64", markdown)
        self.assertIn("x86_64", markdown)


if __name__ == "__main__":
    unittest.main()
