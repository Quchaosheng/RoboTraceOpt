import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "ai_campaign_contract", ROOT / "scripts/ai_campaign_contract.py"
)
assert spec is not None and spec.loader is not None
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def row(stage, *, trace="trace-1", oracle="oracle-1", sequence=1, action=None, **extra):
    payload = {
        "trace_id": trace,
        "oracle_id": oracle,
        "sequence_id": sequence,
        "stage": stage,
    }
    payload["extra"] = ({"action": action} if action is not None else {}) | extra
    payload["reason_code"] = extra.get("reason_code", "")
    return payload


class AiCampaignContractTest(unittest.TestCase):
    def test_selects_one_trace_instead_of_mixing_first_events(self):
        rows = [
            row("planner_receive", trace="old"),
            row("planner_publish", trace="old", action="move_forward"),
            row("planner_receive", trace="selected"),
            row("planner_command_abstained", trace="selected"),
        ]
        key, selected = contract.select_trace_events(rows, "planner_command_abstained")

        self.assertEqual(key, ("selected", "oracle-1", 1))
        self.assertEqual(
            [event["trace_id"] for event in selected], ["selected", "selected"]
        )

    def test_delivery_is_command_delivery_not_task_success(self):
        summary = contract.summarize_trace(
            [
                row("planner_receive"),
                row("planner_publish", action="turn_left", effective_backend="llm"),
                row("can_ack_received"),
            ]
        )

        self.assertEqual(contract.validate_trace(summary, "delivery"), [])
        self.assertEqual(summary["action_execution_complete_count"], 0)

    def test_fail_closed_rejects_any_downstream_motion_or_ack(self):
        summary = contract.summarize_trace(
            [
                row("planner_receive"),
                row("planner_backend_failure", model_error_code="timeout"),
                row("planner_command_abstained"),
            ]
        )

        self.assertEqual(contract.validate_trace(summary, "fail_closed"), [])

        unsafe = dict(summary)
        unsafe["planner_publish_count"] = 1
        unsafe["can_ack_count"] = 1
        self.assertIn(
            "failed_model_output_reached_downstream",
            contract.validate_trace(unsafe, "fail_closed"),
        )

    def test_duplicate_and_stale_outcomes_have_distinct_gates(self):
        duplicate = contract.summarize_trace(
            [
                row("planner_receive"),
                row("planner_publish", action="stop"),
                row("can_ack_received"),
                row("planner_duplicate_request"),
                row("planner_command_abstained"),
            ]
        )
        stale = contract.summarize_trace(
            [
                row("planner_receive"),
                row("planner_output_stale"),
                row("planner_command_abstained"),
            ]
        )

        self.assertEqual(contract.validate_trace(duplicate, "duplicate_request"), [])
        self.assertEqual(contract.validate_trace(stale, "stale_output"), [])

    def test_fallback_storm_uses_the_window_count_from_its_terminal_trace(self):
        storm = contract.summarize_trace(
            [
                row("planner_receive"),
                row("planner_backend_failure", model_error_code="http_failure"),
                row(
                    "planner_fallback_storm",
                    model_failure_count_in_window=3,
                ),
                row("planner_command_abstained"),
            ]
        )

        self.assertEqual(contract.validate_trace(storm, "fallback_storm"), [])


if __name__ == "__main__":
    unittest.main()
