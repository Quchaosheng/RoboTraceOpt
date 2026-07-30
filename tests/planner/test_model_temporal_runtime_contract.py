import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANNER = ROOT / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
PLANNER_LAUNCH = ROOT / "ros2_core/src/vlm_planner_pkg/launch/vlm_planner.launch.py"
BRINGUP = ROOT / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
CAMERA = ROOT / "ros2_core/src/camera_mock_pkg/src/camera_mock_node.cpp"


TEMPORAL_PARAMETERS = {
    "observation_ttl_ms",
    "observation_max_future_skew_ms",
    "model_queue_delay_ms",
    "model_queue_delay_mode",
    "model_dedup_window_ms",
    "model_failure_window_ms",
    "model_failure_storm_count",
    "model_record_path",
    "model_replay_path",
}


def declared_arguments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        str(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeclareLaunchArgument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }


class ModelTemporalRuntimeContractTest(unittest.TestCase):
    def test_launches_expose_all_temporal_model_contract_parameters(self) -> None:
        for path in (PLANNER_LAUNCH, BRINGUP):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertTrue(TEMPORAL_PARAMETERS <= declared_arguments(path))
                for parameter in TEMPORAL_PARAMETERS:
                    self.assertIn(f'"{parameter}": ParameterValue(', source)

    def test_node_admits_and_rechecks_temporal_contract_before_publish(self) -> None:
        source = PLANNER.read_text(encoding="utf-8")
        on_frame = source.split("def _on_camera_frame", 1)[1].split(
            "def _run_executor_contention", 1
        )[0]

        self.assertIn("make_model_request(", on_frame)
        self.assertIn("self._model_admission.admit", on_frame)
        self.assertGreaterEqual(on_frame.count("self._model_admission.output_allowed"), 2)
        self.assertIn("planner_queue_deadline_exceeded", on_frame)
        self.assertIn("planner_output_stale", on_frame)
        self.assertIn("planner_fallback_storm", on_frame)
        self.assertLess(on_frame.index("validate_decision"), on_frame.index("_command_publisher.publish"))

    def test_recording_and_replay_have_no_runtime_event_image_path(self) -> None:
        source = PLANNER.read_text(encoding="utf-8")
        make_extra = source.split("def _make_event_extra", 1)[1].split(
            "def _publish_event", 1
        )[0]

        self.assertIn("PlannerDecisionRecorder", source)
        self.assertIn("ReplayPlannerClient", source)
        self.assertIn("request.public_dict()", make_extra)
        self.assertIn("model_response_fingerprint", make_extra)
        self.assertNotIn("image_path", make_extra)

    def test_camera_exposes_an_explicit_duplicate_request_fault_hook(self) -> None:
        source = CAMERA.read_text(encoding="utf-8")
        bringup = BRINGUP.read_text(encoding="utf-8")
        for parameter in (
            "fixed_trace_id",
            "fixed_oracle_id",
            "fixed_sequence_id",
        ):
            self.assertIn(parameter, source)
            self.assertIn(f'"camera_{parameter}"', bringup)


if __name__ == "__main__":
    unittest.main()
