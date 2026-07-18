import unittest
import tempfile
import subprocess
import json
import inspect
from dataclasses import replace
from pathlib import Path

from experiments.fault_injection.registry import (
    create_fault_manifests,
    load_fault_catalog,
)
from experiments.fault_injection.runner import (
    build_execution_script,
    build_launch_command,
    require_capabilities,
    write_condition_bundle,
)
from scripts.run_fault_condition import (
    validate_fault_output,
    validate_formal_qualification,
)


class FaultRegistryTest(unittest.TestCase):
    def test_catalog_freezes_all_six_independent_fault_classes(self) -> None:
        catalog = load_fault_catalog()

        self.assertEqual(set(catalog), {"F1", "F2", "F3", "F4", "F5", "F6"})
        self.assertEqual(
            {spec.cause_id for spec in catalog.values()},
            {
                "application_compute_delay",
                "executor_queueing",
                "scheduling_delay",
                "blocking_syscall_io",
                "dds_communication_delay",
                "can_ack_failure",
            },
        )
        self.assertTrue(all(spec.oracle_mechanism for spec in catalog.values()))

    def test_public_manifest_does_not_leak_hidden_fault_truth(self) -> None:
        public, oracle = create_fault_manifests(
            load_fault_catalog()["F6"],
            dataset_role="calibration",
            session_id="session-1",
            condition_id="condition-opaque-1",
            git_commit="a" * 40,
        )

        self.assertNotIn("fault_id", public)
        self.assertNotIn("cause_id", public)
        self.assertNotIn("oracle", public)
        self.assertEqual(oracle["fault_id"], "F6")
        self.assertEqual(oracle["cause_id"], "can_ack_failure")
        self.assertEqual(oracle["condition_id"], public["condition_id"])
        self.assertEqual(public["git_commit"], "a" * 40)

    def test_unimplemented_fault_cannot_enter_a_formal_run(self) -> None:
        spec = replace(
            load_fault_catalog()["F3"],
            implementation_status="requires_stress_runner",
        )
        with self.assertRaisesRegex(ValueError, "not ready"):
            create_fault_manifests(
                spec,
                dataset_role="calibration",
                session_id="session-1",
                condition_id="condition-opaque-1",
                git_commit="a" * 40,
            )

    def test_rejects_invalid_dataset_role_and_identity(self) -> None:
        spec = load_fault_catalog()["F6"]
        with self.assertRaisesRegex(ValueError, "dataset role"):
            create_fault_manifests(
                spec,
                dataset_role="production",
                session_id="session-1",
                condition_id="condition-1",
                git_commit="a" * 40,
            )
        with self.assertRaisesRegex(ValueError, "session_id"):
            create_fault_manifests(
                spec,
                dataset_role="test",
                session_id="",
                condition_id="condition-1",
                git_commit="a" * 40,
            )

    def test_development_role_is_separate_from_formal_partitions(self) -> None:
        public, oracle = create_fault_manifests(
            load_fault_catalog()["F6"],
            dataset_role="development",
            session_id="dev-session",
            condition_id="dev-condition",
            git_commit="a" * 40,
        )

        self.assertEqual(public["dataset_role"], "development")
        self.assertEqual(oracle["dataset_role"], "development")

    def test_f2_control_is_blinded_and_has_no_fault_cause(self) -> None:
        public, oracle = create_fault_manifests(
            load_fault_catalog()["F2"],
            dataset_role="development",
            session_id="f2-control",
            condition_id="opaque-control",
            git_commit="a" * 40,
            condition_variant="control",
        )

        self.assertNotIn("condition_variant", public)
        self.assertNotIn("cause_id", public)
        self.assertEqual(oracle["fault_id"], "F2")
        self.assertEqual(oracle["condition_variant"], "control")
        self.assertEqual(oracle["cause_id"], "none")
        self.assertFalse(oracle["injection"]["executor_contention_enabled"])

    def test_f1_variants_change_only_busy_compute_delay_magnitude(self) -> None:
        spec = load_fault_catalog()["F1"]
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f1-injected",
            condition_id="opaque-injected",
            git_commit="a" * 40,
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f1-control",
            condition_id="opaque-control",
            git_commit="a" * 40,
            condition_variant="control",
        )

        for public in (injected_public, control_public):
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("cause_id", public)
        self.assertEqual(injected_oracle["cause_id"], "application_compute_delay")
        self.assertEqual(control_oracle["cause_id"], "none")
        self.assertEqual(injected_oracle["injection"]["planner_delay_ms"], 100)
        self.assertEqual(control_oracle["injection"]["planner_delay_ms"], 0)
        self.assertEqual(
            control_oracle["injection"]["planner_delay_mode"], "busy_compute"
        )
        self.assertEqual(control_oracle["injection"]["input_rate_hz"], 4)
        self.assertEqual(control_oracle["injection"]["planner_backend"], "mock")
        self.assertTrue(control_oracle["injection"]["action_manager_enabled"])
        self.assertNotIn("control_delay_ms", control_oracle["injection"])

        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="calibration",
                session_id="f1-formal-control",
                condition_id="opaque-formal-control",
                git_commit="a" * 40,
                condition_variant="control",
            )

    def test_f6_variants_change_only_mock_ack_policy(self) -> None:
        spec = load_fault_catalog()["F6"]
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f6-injected",
            condition_id="opaque-injected",
            git_commit="a" * 40,
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f6-control",
            condition_id="opaque-control",
            git_commit="a" * 40,
            condition_variant="control",
        )

        for public in (injected_public, control_public):
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("cause_id", public)
        self.assertEqual(injected_oracle["cause_id"], "can_ack_failure")
        self.assertEqual(control_oracle["cause_id"], "none")
        self.assertEqual(injected_oracle["injection"]["mock_ack_policy"], "drop")
        self.assertEqual(control_oracle["injection"]["mock_ack_policy"], "success")
        self.assertEqual(control_oracle["injection"]["ack_timeout_ms"], 20)
        self.assertEqual(control_oracle["injection"]["max_retries"], 2)
        self.assertEqual(control_oracle["injection"]["ack_mode"], "mock")
        self.assertTrue(control_oracle["injection"]["mock_mode"])
        self.assertEqual(control_oracle["injection"]["input_rate_hz"], 4)
        self.assertNotIn("control_ack_policy", control_oracle["injection"])

        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="test",
                session_id="f6-formal-control",
                condition_id="opaque-formal-control",
                git_commit="a" * 40,
                condition_variant="control",
            )

    def test_f6_vcan_variants_are_blinded_and_change_only_responder_policy(
        self,
    ) -> None:
        spec = load_fault_catalog()["F6"]
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f6-vcan-injected",
            condition_id="opaque-vcan-injected",
            git_commit="a" * 40,
            f6_transport_profile="vcan",
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f6-vcan-control",
            condition_id="opaque-vcan-control",
            git_commit="a" * 40,
            condition_variant="control",
            f6_transport_profile="vcan",
        )

        for public in (injected_public, control_public):
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("responder_policy", public)
        self.assertEqual(injected_oracle["cause_id"], "can_ack_failure")
        self.assertEqual(control_oracle["cause_id"], "none")
        expected_shared = {
            "transport_profile": "vcan",
            "ack_mode": "socketcan",
            "mock_mode": False,
            "can_interface": "vcan0",
            "ack_can_id_offset": 128,
            "responder_delay_ms": 5,
            "ack_timeout_ms": 20,
            "max_retries": 2,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
        }
        for key, value in expected_shared.items():
            self.assertEqual(injected_oracle["injection"][key], value)
            self.assertEqual(control_oracle["injection"][key], value)
        self.assertEqual(injected_oracle["injection"]["responder_policy"], "drop")
        self.assertEqual(control_oracle["injection"]["responder_policy"], "echo")

    def test_f6_vcan_profile_is_development_only_and_capability_gated(self) -> None:
        spec = load_fault_catalog()["F6"]
        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="calibration",
                session_id="f6-vcan-formal",
                condition_id="opaque-vcan-formal",
                git_commit="a" * 40,
                f6_transport_profile="vcan",
            )
        with self.assertRaisesRegex(ValueError, "transport profile"):
            create_fault_manifests(
                spec,
                dataset_role="development",
                session_id="f6-vcan-unknown",
                condition_id="opaque-vcan-unknown",
                git_commit="a" * 40,
                f6_transport_profile="invalid",
            )
        with self.assertRaisesRegex(ValueError, "socketcan_vcan"):
            require_capabilities(
                spec,
                {"ros2_runtime", "runtime_event"},
                dataset_role="development",
                f6_transport_profile="vcan",
            )
        require_capabilities(
            spec,
            {"ros2_runtime", "runtime_event", "socketcan_vcan"},
            dataset_role="development",
            f6_transport_profile="vcan",
        )

    def test_f4_variants_change_only_server_blocking_delay(self) -> None:
        spec = load_fault_catalog()["F4"]
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f4-injected",
            condition_id="opaque-f4-injected",
            git_commit="a" * 40,
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f4-control",
            condition_id="opaque-f4-control",
            git_commit="a" * 40,
            condition_variant="control",
        )

        for public in (injected_public, control_public):
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("cause_id", public)
            self.assertNotIn("server_delay_ms", public)
        self.assertEqual(injected_oracle["cause_id"], "blocking_syscall_io")
        self.assertEqual(control_oracle["cause_id"], "none")
        self.assertEqual(injected_oracle["injection"]["server_delay_ms"], 100)
        self.assertEqual(control_oracle["injection"]["server_delay_ms"], 0)
        self.assertEqual(control_oracle["injection"]["request_rate_hz"], 5)
        self.assertEqual(
            control_oracle["injection"]["blocking_primitive"], "clock_nanosleep"
        )
        self.assertNotIn("control_delay_ms", control_oracle["injection"])
        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="test",
                session_id="f4-formal-control",
                condition_id="opaque-f4-formal-control",
                git_commit="a" * 40,
                condition_variant="control",
            )

    def test_rejects_unknown_condition_variant(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid condition variant"):
            create_fault_manifests(
                load_fault_catalog()["F4"],
                dataset_role="development",
                session_id="invalid-variant",
                condition_id="opaque-invalid",
                git_commit="a" * 40,
                condition_variant="baseline",
            )

    def test_f5_variants_are_blinded_and_development_only(self) -> None:
        spec = load_fault_catalog()["F5"]
        self.assertEqual(spec.implementation_status, "ready")
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f5-injected",
            condition_id="opaque-injected",
            git_commit="a" * 40,
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f5-control",
            condition_id="opaque-control",
            git_commit="a" * 40,
            condition_variant="control",
        )

        for public in (injected_public, control_public):
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("cause_id", public)
        self.assertEqual(injected_oracle["cause_id"], "dds_communication_delay")
        self.assertEqual(control_oracle["cause_id"], "none")
        self.assertEqual(injected_oracle["injection"]["publisher_depth"], 1)
        self.assertEqual(injected_oracle["injection"]["subscriber_depth"], 1)
        self.assertEqual(control_oracle["injection"]["publisher_depth"], 10)
        self.assertEqual(control_oracle["injection"]["subscriber_depth"], 10)
        with self.assertRaisesRegex(ValueError, "development-only"):
            create_fault_manifests(
                spec,
                dataset_role="calibration",
                session_id="f5-formal",
                condition_id="opaque-formal",
                git_commit="a" * 40,
            )

    def test_f3_variants_record_target_cpu_only_in_the_oracle(self) -> None:
        spec = load_fault_catalog()["F3"]
        self.assertEqual(spec.implementation_status, "ready")
        injected_public, injected_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f3-injected",
            condition_id="opaque-injected",
            git_commit="a" * 40,
            target_cpu=31,
        )
        control_public, control_oracle = create_fault_manifests(
            spec,
            dataset_role="development",
            session_id="f3-control",
            condition_id="opaque-control",
            git_commit="a" * 40,
            condition_variant="control",
            target_cpu=31,
        )

        for public in (injected_public, control_public):
            self.assertNotIn("target_cpu", public)
            self.assertNotIn("condition_variant", public)
            self.assertNotIn("cause_id", public)
        self.assertEqual(injected_oracle["cause_id"], "scheduling_delay")
        self.assertTrue(injected_oracle["injection"]["stress_enabled"])
        self.assertEqual(injected_oracle["injection"]["target_cpu"], 31)
        self.assertEqual(control_oracle["cause_id"], "none")
        self.assertFalse(control_oracle["injection"]["stress_enabled"])
        self.assertEqual(control_oracle["injection"]["target_cpu"], 31)


class FaultRunnerTest(unittest.TestCase):
    def test_formal_qualification_accepts_matching_injected_case(self) -> None:
        validate_formal_qualification(
            {
                "schema_version": "formal-experiment-qualification/v1",
                "status": "allowed",
                "dataset_role": "test",
                "development_only": False,
                "formal_experiment_allowed": True,
                "matrix_sha256": "a" * 64,
                "capability_sha256": "b" * 64,
                "git_commit": "c" * 40,
                "git_status": "",
                "selected_case_ids": ["diagnosis_f1_injected"],
                "cases": [
                    {
                        "case_id": "diagnosis_f1_injected",
                        "status": "ready",
                        "missing_requirements": [],
                        "role_errors": [],
                    }
                ],
            },
            dataset_role="test",
            fault_id="F1",
            condition_variant="injected",
            case_id="diagnosis_f1_injected",
            git_commit="c" * 40,
            git_status="",
        )

    def test_setup_scripts_are_sourced_with_nounset_temporarily_disabled(self) -> None:
        script = build_execution_script(
            ["ros2", "launch", "pkg", "file.py"],
            setup_path=Path("/tmp/runtime/setup.bash"),
            ros_log_dir=Path("/tmp/ros-log"),
            duration_seconds=8,
            tracing_overlay_setup=Path("/tmp/tracing/setup.bash"),
            trace_session="fault_f2_session",
            trace_dir=Path("/tmp/ctf"),
        )

        self.assertIn(
            "set +u\n"
            "source /tmp/runtime/setup.bash\n"
            "source /tmp/tracing/setup.bash\n"
            "set -u",
            script,
        )

    def test_tracing_execution_script_owns_lttng_lifecycle(self) -> None:
        script = build_execution_script(
            ["ros2", "launch", "pkg", "file.py"],
            setup_path=Path("/tmp/runtime/setup.bash"),
            ros_log_dir=Path("/tmp/ros-log"),
            duration_seconds=8,
            tracing_overlay_setup=Path("/tmp/tracing/setup.bash"),
            trace_session="fault_f2_session",
            trace_dir=Path("/tmp/ctf"),
        )

        self.assertIn("source /tmp/runtime/setup.bash", script)
        self.assertIn("source /tmp/tracing/setup.bash", script)
        self.assertIn("ros2 run tracetools status", script)
        self.assertIn("lttng create fault_f2_session --output=/tmp/ctf", script)
        self.assertIn('lttng enable-event --userspace "ros2:*"', script)
        for context in ("vpid", "vtid", "procname"):
            self.assertIn(f"--type={context}", script)
        self.assertIn("lttng destroy fault_f2_session", script)

    def test_runtime_only_script_does_not_start_lttng(self) -> None:
        script = build_execution_script(
            ["ros2", "launch", "pkg", "file.py"],
            setup_path=Path("/tmp/runtime/setup.bash"),
            ros_log_dir=Path("/tmp/ros-log"),
            duration_seconds=8,
        )

        self.assertNotIn("lttng", script)

    def test_builds_f1_busy_compute_command(self) -> None:
        command = build_launch_command(
            load_fault_catalog()["F1"], Path("/tmp/runtime_events.jsonl")
        )

        self.assertIn("planner_delay_mode:=busy_compute", command)
        self.assertIn("planner_delay_ms:=100", command)

    def test_builds_f1_control_with_only_delay_magnitude_changed(self) -> None:
        spec = load_fault_catalog()["F1"]
        injected = build_launch_command(spec, Path("/tmp/runtime_events.jsonl"))
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
        )

        self.assertEqual(set(injected) - set(control), {"planner_delay_ms:=100"})
        self.assertEqual(set(control) - set(injected), {"planner_delay_ms:=0"})
        for argument in (
            "planner_delay_mode:=busy_compute",
            "camera_rate_hz:=4",
            "planner_backend:=mock",
            "action_manager_enabled:=true",
        ):
            self.assertIn(argument, injected)
            self.assertIn(argument, control)

    def test_builds_f2_single_executor_contention_command(self) -> None:
        command = build_launch_command(
            load_fault_catalog()["F2"], Path("/tmp/runtime_events.jsonl")
        )

        self.assertIn("planner_delay_ms:=0", command)
        self.assertIn("action_manager_enabled:=false", command)
        self.assertIn("executor_contention_enabled:=true", command)
        self.assertIn("executor_contention_period_ms:=25", command)
        self.assertIn("executor_contention_load_ms:=20", command)
        self.assertIn("camera_rate_hz:=100", command)

    def test_builds_matched_f2_control_command(self) -> None:
        command = build_launch_command(
            load_fault_catalog()["F2"],
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
        )

        self.assertIn("camera_rate_hz:=100", command)
        self.assertIn("planner_delay_ms:=0", command)
        self.assertIn("action_manager_enabled:=false", command)
        self.assertIn("executor_contention_enabled:=false", command)
        self.assertIn("executor_contention_period_ms:=25", command)
        self.assertIn("executor_contention_load_ms:=20", command)

    def test_builds_f5_commands_with_only_history_depth_changed(self) -> None:
        spec = load_fault_catalog()["F5"]
        self.assertEqual(spec.implementation_status, "ready")
        injected = build_launch_command(spec, Path("/tmp/runtime_events.jsonl"))
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
        )

        expected_common = {
            "camera_rate_hz:=100",
            "frame_payload_bytes:=262144",
            "frame_qos_reliability:=reliable",
            "planner_delay_ms:=0",
            "executor_contention_enabled:=false",
            "action_manager_enabled:=false",
        }
        self.assertTrue(expected_common <= set(injected))
        self.assertTrue(expected_common <= set(control))
        self.assertEqual(
            set(injected) - set(control),
            {"frame_qos_depth:=1"},
        )
        self.assertEqual(
            set(control) - set(injected),
            {"frame_qos_depth:=10"},
        )

    def test_builds_same_cpu_f3_ros_commands_for_both_variants(self) -> None:
        spec = load_fault_catalog()["F3"]
        self.assertIn("target_cpu", inspect.signature(build_launch_command).parameters)
        injected = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            target_cpu=31,
        )
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
            target_cpu=31,
        )

        self.assertEqual(injected, control)
        self.assertEqual(injected[:3], ["taskset", "--cpu-list", "31"])
        self.assertIn("camera_rate_hz:=100", injected)
        self.assertIn("planner_delay_ms:=0", injected)
        self.assertIn("executor_contention_enabled:=false", injected)
        self.assertIn("action_manager_enabled:=false", injected)

    def test_f3_capability_gate_is_role_sensitive(self) -> None:
        spec = load_fault_catalog()["F3"]
        development = {"ros2_runtime", "ros2_tracing", "stress_ng", "taskset"}
        self.assertIn(
            "dataset_role", inspect.signature(require_capabilities).parameters
        )

        with self.assertRaisesRegex(ValueError, "identity_comparable_ebpf"):
            require_capabilities(spec, development, dataset_role="development")
        require_capabilities(
            spec,
            development | {"identity_comparable_ebpf"},
            dataset_role="development",
        )
        with self.assertRaisesRegex(ValueError, "identity_comparable_ebpf"):
            require_capabilities(spec, development, dataset_role="calibration")
        with self.assertRaisesRegex(ValueError, "taskset"):
            require_capabilities(
                spec,
                development - {"taskset"},
                dataset_role="development",
            )

    def test_builds_f6_command_from_frozen_injection(self) -> None:
        spec = load_fault_catalog()["F6"]

        command = build_launch_command(spec, Path("/tmp/runtime_events.jsonl"))

        self.assertEqual(
            command[:4], ["ros2", "launch", "runtime_bringup", "ai_runtime.launch.py"]
        )
        self.assertIn("mock_ack_policy:=drop", command)
        self.assertIn("ack_timeout_ms:=20", command)
        self.assertIn("max_retries:=2", command)
        self.assertIn("output_path:=/tmp/runtime_events.jsonl", command)

    def test_builds_f6_control_with_only_ack_policy_changed(self) -> None:
        spec = load_fault_catalog()["F6"]
        injected = build_launch_command(spec, Path("/tmp/runtime_events.jsonl"))
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
        )

        self.assertEqual(set(injected) - set(control), {"mock_ack_policy:=drop"})
        self.assertEqual(set(control) - set(injected), {"mock_ack_policy:=success"})
        for argument in (
            "camera_rate_hz:=4",
            "planner_backend:=mock",
            "action_manager_enabled:=true",
            "ack_mode:=mock",
            "mock_mode:=true",
            "ack_timeout_ms:=20",
            "max_retries:=2",
        ):
            self.assertIn(argument, injected)
            self.assertIn(argument, control)

    def test_builds_identical_f6_vcan_launch_commands(self) -> None:
        spec = load_fault_catalog()["F6"]
        injected = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            f6_transport_profile="vcan",
        )
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
            f6_transport_profile="vcan",
        )

        self.assertEqual(injected, control)
        for argument in (
            "ack_mode:=socketcan",
            "mock_mode:=false",
            "can_interface:=vcan0",
            "ack_can_id_offset:=128",
            "ack_timeout_ms:=20",
            "max_retries:=2",
        ):
            self.assertIn(argument, injected)
        self.assertFalse(
            any(value.startswith("mock_ack_policy:=") for value in injected)
        )

    def test_capability_gate_rejects_formal_f4_on_wsl(self) -> None:
        spec = load_fault_catalog()["F4"]
        self.assertIn(
            "dataset_role", inspect.signature(require_capabilities).parameters
        )

        with self.assertRaisesRegex(ValueError, "identity_comparable_ebpf"):
            require_capabilities(spec, {"ros2_runtime"}, dataset_role="development")
        require_capabilities(
            spec,
            {"ros2_runtime", "identity_comparable_ebpf"},
            dataset_role="development",
        )
        with self.assertRaisesRegex(ValueError, "identity_comparable_ebpf"):
            require_capabilities(spec, {"ros2_runtime"}, dataset_role="calibration")

    def test_builds_f4_commands_with_only_server_delay_changed(self) -> None:
        spec = load_fault_catalog()["F4"]
        injected = build_launch_command(spec, Path("/tmp/runtime_events.jsonl"))
        control = build_launch_command(
            spec,
            Path("/tmp/runtime_events.jsonl"),
            condition_variant="control",
        )

        self.assertEqual(set(injected) - set(control), {"server_delay_ms:=100"})
        self.assertEqual(set(control) - set(injected), {"server_delay_ms:=0"})
        for argument in (
            "request_rate_hz:=5",
            "runtime_events_enabled:=true",
            "output_path:=/tmp/runtime_events.jsonl",
        ):
            self.assertIn(argument, injected)
            self.assertIn(argument, control)

    def test_bundle_keeps_public_and_oracle_files_separate(self) -> None:
        spec = load_fault_catalog()["F6"]
        public, oracle = create_fault_manifests(
            spec,
            dataset_role="test",
            session_id="session-1",
            condition_id="condition-1",
            git_commit="a" * 40,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            command = build_launch_command(spec, root / "runtime_events.jsonl")

            paths = write_condition_bundle(root, public, oracle, command)

            self.assertEqual(paths["public_manifest"].name, "run_manifest.json")
            self.assertEqual(paths["oracle_manifest"].name, "oracle_manifest.json")
            self.assertNotIn(
                "cause_id", paths["public_manifest"].read_text(encoding="utf-8")
            )
            self.assertIn(
                "can_ack_failure", paths["oracle_manifest"].read_text(encoding="utf-8")
            )

    def test_prepare_cli_rejects_formal_role_without_qualification(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "condition"

            completed = subprocess.run(
                [
                    "python3",
                    "scripts/run_fault_condition.py",
                    "--fault-id",
                    "F6",
                    "--dataset-role",
                    "calibration",
                    "--session-id",
                    "session-1",
                    "--condition-id",
                    "condition-1",
                    "--output-dir",
                    str(output_dir),
                    "--capability",
                    "ros2_runtime",
                    "--capability",
                    "runtime_event",
                ],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("qualification report", completed.stderr)
            self.assertFalse(output_dir.exists())

    def test_prepare_cli_writes_a_blinded_f6_vcan_bundle(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "condition"
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/run_fault_condition.py",
                    "--fault-id",
                    "F6",
                    "--dataset-role",
                    "development",
                    "--session-id",
                    "f6-vcan",
                    "--condition-id",
                    "opaque-f6-vcan",
                    "--condition-variant",
                    "control",
                    "--f6-transport-profile",
                    "vcan",
                    "--output-dir",
                    str(output_dir),
                    "--capability",
                    "ros2_runtime",
                    "--capability",
                    "runtime_event",
                    "--capability",
                    "socketcan_vcan",
                ],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            public = json.loads(
                (output_dir / "run_manifest.json").read_text(encoding="utf-8")
            )
            oracle = json.loads(
                (output_dir / "oracle_manifest.json").read_text(encoding="utf-8")
            )
            command = json.loads(
                (output_dir / "command.json").read_text(encoding="utf-8")
            )["argv"]
            self.assertNotIn("responder_policy", public)
            self.assertEqual(oracle["injection"]["responder_policy"], "echo")
            self.assertIn("ack_mode:=socketcan", command)
            self.assertFalse(
                any(value.startswith("mock_ack_policy:=") for value in command)
            )

    def test_prepare_f3_cli_freezes_cpu_and_stress_commands(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "condition"
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/run_fault_condition.py",
                    "--fault-id",
                    "F3",
                    "--dataset-role",
                    "development",
                    "--session-id",
                    "f3-dev",
                    "--condition-id",
                    "opaque-f3",
                    "--output-dir",
                    str(output_dir),
                    "--capability",
                    "ros2_runtime",
                    "--capability",
                    "ros2_tracing",
                    "--capability",
                    "stress_ng",
                    "--capability",
                    "taskset",
                    "--capability",
                    "identity_comparable_ebpf",
                ],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            oracle = json.loads(
                (output_dir / "oracle_manifest.json").read_text(encoding="utf-8")
            )
            commands = json.loads(
                (output_dir / "command.json").read_text(encoding="utf-8")
            )
            target_cpu = oracle["injection"]["target_cpu"]
            self.assertEqual(
                commands["argv"][:3], ["taskset", "--cpu-list", str(target_cpu)]
            )
            self.assertEqual(
                commands["stress_argv"][:4],
                ["taskset", "--cpu-list", str(target_cpu), "stress-ng"],
            )

    def test_f6_validator_requires_retry_exhausted_terminal(self) -> None:
        rows = [
            {"trace_id": trace_id, "event_name": event_name}
            for trace_id in ("trace-1", "trace-2")
            for event_name in (
                "can_ack_wait_start",
                "can_ack_timeout",
                "can_retry_exhausted",
            )
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runtime_events.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            summary = validate_fault_output(
                "F6", "w1", path, condition_variant="injected"
            )

        self.assertEqual(summary["trace_count"], 2)
        self.assertEqual(summary["fault_complete_trace_count"], 2)
        self.assertEqual(summary["incomplete_trace_count"], 0)
        self.assertEqual(summary["missing_events"], [])

    def test_f6_control_validator_requires_received_terminal(self) -> None:
        rows = [
            {"trace_id": trace_id, "event_name": event_name}
            for trace_id in ("trace-1", "trace-2")
            for event_name in ("can_ack_wait_start", "can_ack_received")
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runtime_events.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            summary = validate_fault_output(
                "F6", "w1", path, condition_variant="control"
            )

        self.assertEqual(summary["fault_complete_trace_count"], 2)
        self.assertEqual(
            summary["required_events"], ["can_ack_received", "can_ack_wait_start"]
        )

    def test_f5_validator_requires_camera_delivery_endpoints(self) -> None:
        rows = [
            {"trace_id": trace_id, "event_name": event_name}
            for trace_id in ("trace-1", "trace-2")
            for event_name in (
                "camera_frame_published",
                "planner_receive",
                "planner_process_end",
            )
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runtime_events.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            try:
                summary = validate_fault_output("F5", "w1", path)
            except KeyError:
                self.fail("F5 output requirements are not registered")

        self.assertEqual(summary["fault_complete_trace_count"], 2)
        self.assertEqual(summary["missing_events"], [])

    def test_f3_validator_requires_the_zero_work_planner_path(self) -> None:
        rows = [
            {"trace_id": trace_id, "event_name": event_name}
            for trace_id in ("trace-1", "trace-2")
            for event_name in (
                "camera_frame_published",
                "planner_receive",
                "planner_process_start",
                "planner_process_end",
                "planner_publish",
            )
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "runtime_events.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            try:
                summary = validate_fault_output("F3", "w1", path)
            except KeyError:
                self.fail("F3 output requirements are not registered")

        self.assertEqual(summary["fault_complete_trace_count"], 2)


if __name__ == "__main__":
    unittest.main()
