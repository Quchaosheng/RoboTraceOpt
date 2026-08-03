import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "verify_ai_planner_campaign", SCRIPTS / "verify_ai_planner_campaign.py"
)
assert spec is not None and spec.loader is not None
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def event(stage, *, action=None, backend="mock", replayed=False):
    extra = {
        "effective_backend": backend,
        "model_replayed": replayed,
    }
    if action is not None:
        extra["action"] = action
    return {
        "trace_id": "trace-1",
        "oracle_id": "oracle-1",
        "sequence_id": 1,
        "stage": stage,
        "timestamp_ns": 100,
        "pid": 1,
        "tid": 2,
        "host_id": "host",
        "clock_id": "monotonic",
        "duration_ns": 0,
        "status": "observed",
        "reason_code": "",
        "extra_json": json.dumps(extra),
    }


class VerifyAiPlannerCampaignTest(unittest.TestCase):
    def test_validates_one_trace_and_rejects_a_summary_trace_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "A0_mock_delivery" / "run_01"
            run_dir.mkdir(parents=True)
            (run_dir / "launch.log").write_text("launch\n", encoding="utf-8")
            (run_dir / "trial_summary.json").write_text("{}\n", encoding="utf-8")
            rows = [
                event("planner_receive"),
                event("planner_process_end"),
                event("planner_publish", action="move_forward"),
                event("can_ack_received"),
            ]
            (run_dir / "runtime_events.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            trial = {
                "condition": "A0_mock_delivery",
                "repetition": 1,
                "expected_terminal_stage": "can_ack_received",
                "expected_outcome": "delivery",
                "trace_id": "trace-1",
                "oracle_id": "oracle-1",
                "sequence_id": 1,
                "status": "complete",
                "semantic_errors": [],
                "task_success_semantics": "not_measured_by_runtime_event_campaign",
                "command_delivery_observed": True,
            }

            self.assertEqual(verifier.validate_trial(root, trial), [])

            trial["trace_id"] = "wrong"
            self.assertIn(
                "trial_summary_trace_mismatch",
                verifier.validate_trial(root, trial),
            )


if __name__ == "__main__":
    unittest.main()
