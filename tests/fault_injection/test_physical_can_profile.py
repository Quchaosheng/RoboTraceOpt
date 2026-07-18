import unittest
from pathlib import Path

from experiments.fault_injection.registry import (
    create_fault_manifests,
    load_fault_catalog,
    materialize_f6_injection,
)
from experiments.fault_injection.runner import (
    build_launch_command,
    require_capabilities,
)


class PhysicalCanProfileTest(unittest.TestCase):
    def test_materializes_overridable_physical_profile(self) -> None:
        spec = load_fault_catalog()["F6"]

        injection = materialize_f6_injection(
            spec,
            "control",
            "physical",
            can_interface="can2",
            responder_interface="can3",
            bitrate=250000,
        )

        self.assertEqual(injection["transport_profile"], "physical")
        self.assertEqual(injection["can_interface"], "can2")
        self.assertEqual(injection["responder_interface"], "can3")
        self.assertEqual(injection["bitrate"], 250000)
        self.assertEqual(injection["responder_policy"], "echo")
        self.assertFalse(injection["mock_mode"])

    def test_physical_profile_is_development_only_and_capability_gated(self) -> None:
        spec = load_fault_catalog()["F6"]
        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="test",
                session_id="physical-test",
                condition_id="physical-test-control",
                git_commit="a" * 40,
                condition_variant="control",
                f6_transport_profile="physical",
            )
        with self.assertRaisesRegex(ValueError, "socketcan_physical"):
            require_capabilities(
                spec,
                {"ros2_runtime", "runtime_event"},
                dataset_role="development",
                f6_transport_profile="physical",
            )

    def test_launch_uses_runtime_interface_without_exposing_peer_to_ros(self) -> None:
        spec = load_fault_catalog()["F6"]

        command = build_launch_command(
            spec,
            Path("/tmp/runtime.jsonl"),
            condition_variant="control",
            f6_transport_profile="physical",
            f6_can_interface="can2",
            f6_responder_interface="can3",
            f6_bitrate=250000,
        )

        self.assertIn("can_interface:=can2", command)
        self.assertFalse(any("can3" in argument for argument in command))
        self.assertFalse(any("250000" in argument for argument in command))


if __name__ == "__main__":
    unittest.main()
