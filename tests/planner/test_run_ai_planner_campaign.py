import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "run_ai_planner_campaign", SCRIPTS / "run_ai_planner_campaign.py"
)
assert spec is not None and spec.loader is not None
campaign = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = campaign
spec.loader.exec_module(campaign)


class RunAiPlannerCampaignTest(unittest.TestCase):
    def test_campaign_covers_delivery_replay_and_fail_closed_faults(self):
        args = types.SimpleNamespace(
            api_style="responses",
            real_timeout_s=30.0,
            mock_repetitions=1,
            real_repetitions=1,
            fault_repetitions=1,
        )
        by_name = {condition.name: condition for condition in campaign.conditions(args)}

        self.assertEqual(by_name["A0_mock_delivery"].expected_outcome, "delivery")
        self.assertTrue(by_name["A0_mock_delivery"].record_decisions)
        self.assertEqual(
            by_name["A2_connection_reset_fail_closed"].expected_outcome,
            "fail_closed",
        )
        self.assertEqual(
            by_name["F7_model_queue_deadline"].expected_outcome,
            "queue_expired",
        )
        self.assertEqual(
            by_name["F9_stale_model_output"].expected_outcome,
            "stale_output",
        )
        self.assertEqual(
            by_name["F10_fallback_storm"].expected_outcome,
            "fallback_storm",
        )
        self.assertTrue(by_name["A3_duplicate_request"].fixed_duplicate_identity)
        self.assertTrue(by_name["A3_duplicate_request"].second_camera_enabled)


if __name__ == "__main__":
    unittest.main()
