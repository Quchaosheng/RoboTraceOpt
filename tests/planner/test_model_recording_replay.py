import sys
import tempfile
import types
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "ros2_core/src/vlm_planner_pkg/src"
sys.path.insert(0, str(SOURCE))

interfaces = types.ModuleType("ai_robot_runtime_interfaces")
messages = types.ModuleType("ai_robot_runtime_interfaces.msg")
messages.CameraFrame = object
interfaces.msg = messages
sys.modules.setdefault("ai_robot_runtime_interfaces", interfaces)
sys.modules.setdefault("ai_robot_runtime_interfaces.msg", messages)

from planner_clients.base_client import BasePlannerClient  # noqa: E402
from planner_clients.admission import ModelAdmission  # noqa: E402
from planner_clients.model_contract import (  # noqa: E402
    PlannerErrorCode,
    make_model_request,
    validate_decision,
)
from planner_clients.recording import PlannerDecisionRecorder  # noqa: E402
from planner_clients.replay_client import ReplayPlannerClient  # noqa: E402
from planner_clients.schema import PlannerDecision  # noqa: E402


class Header:
    trace_id = "trace-7"
    oracle_id = "oracle-7"
    sequence_id = 11


class Frame:
    header = Header()
    image_path = "/private/robot/secret-frame.jpg"
    frame_id = 7
    encoding = "jpeg"
    width = 2
    height = 1
    payload = b"private-image-bytes"


class FixedClient(BasePlannerClient):
    def plan(self, _frame):
        return PlannerDecision("turn_left", "door", 0.3, 0.8, "clear route")


class TimeoutClient(BasePlannerClient):
    def plan(self, _frame):
        raise TimeoutError("provider timed out")


class ModelRecordingReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.request = make_model_request(
            self.frame,
            session_id="session-1",
            observation_timestamp_ns=1_000_000_000,
            ttl_ms=250,
            now_ns=1_010_000_000,
        )

    def test_request_has_deadline_and_only_fingerprints_the_frame(self) -> None:
        self.assertEqual(self.request.deadline_ns, 1_250_000_000)
        self.assertFalse(self.request.expired(1_249_999_999))
        self.assertTrue(self.request.expired(1_250_000_001))
        self.assertNotIn("secret-frame", str(self.request.public_dict()))
        self.assertNotIn("private-image-bytes", str(self.request.public_dict()))

    def test_recording_replays_the_normalized_decision_without_raw_input(self) -> None:
        result = FixedClient().plan_with_request(self.frame, self.request)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.jsonl"
            PlannerDecisionRecorder(path).record(self.request, result)
            recording = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-frame", recording)
            self.assertNotIn("private-image-bytes", recording)
            self.assertNotIn("/private/robot", recording)

            replay = ReplayPlannerClient(path).plan_with_request(self.frame, self.request)

        self.assertTrue(replay.succeeded)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.backend, "replay")
        self.assertEqual(replay.decision, result.decision)
        self.assertEqual(replay.response_fingerprint, result.response_fingerprint)

    def test_replay_fails_closed_when_multiple_records_match(self) -> None:
        result = FixedClient().plan_with_request(self.frame, self.request)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.jsonl"
            recorder = PlannerDecisionRecorder(path)
            recorder.record(self.request, result)
            recorder.record(self.request, result)
            replay = ReplayPlannerClient(path).plan_with_request(self.frame, self.request)

        self.assertFalse(replay.succeeded)
        self.assertEqual(replay.error_code, PlannerErrorCode.REPLAY_MISS)

    def test_base_contract_converts_timeout_to_stable_error_code(self) -> None:
        result = TimeoutClient().plan_with_request(self.frame, self.request)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.error_code, PlannerErrorCode.TIMEOUT)
        self.assertGreaterEqual(result.latency_ns, 0)

    def test_replay_decisions_are_validated_before_ros_publication(self) -> None:
        self.assertEqual(validate_decision(FixedClient().plan(self.frame)), "")
        invalid = PlannerDecision("move_forward", "front", float("nan"), 0.8, "bad")
        self.assertEqual(
            validate_decision(invalid), "planner_decision_speed_not_finite"
        )

    def test_temporal_admission_rejects_duplicates_stale_outputs_and_failure_storms(self) -> None:
        admission = ModelAdmission(
            dedup_window_ms=100,
            failure_window_ms=50,
            max_failures=3,
        )
        self.assertEqual(admission.admit(self.request, 1_010_000_000), "")
        self.assertEqual(
            admission.admit(self.request, 1_011_000_000), "planner_duplicate_request"
        )
        self.assertEqual(
            admission.output_allowed(self.request, 1_260_000_000),
            "planner_output_expired",
        )
        self.assertFalse(admission.note_backend_failure(2_000_000_000))
        self.assertFalse(admission.note_backend_failure(2_010_000_000))
        self.assertTrue(admission.note_backend_failure(2_020_000_000))

        future = make_model_request(
            self.frame,
            session_id="session-2",
            observation_timestamp_ns=3_000_000_000,
            ttl_ms=250,
            now_ns=2_000_000_000,
        )
        self.assertEqual(
            admission.admit(future, 2_000_000_000),
            "planner_observation_timestamp_future",
        )


if __name__ == "__main__":
    unittest.main()
