import json
import unittest
from pathlib import Path


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "association"
    / "w1_real_summary.json"
)


class RealAssociationEvidenceTest(unittest.TestCase):
    def test_clean_w1_summary_is_internally_consistent(self) -> None:
        summary = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertFalse(summary["git_dirty"])
        self.assertEqual(summary["clock_status"], "comparable")
        self.assertEqual(summary["runtime_event_count"], summary["stage_window_count"])
        self.assertEqual(
            summary["accepted_count"] + summary["background_count"],
            summary["ros2_event_count"],
        )
        self.assertEqual(
            summary["exact_tid_count"] + summary["pid_only_count"],
            summary["accepted_count"],
        )
        self.assertEqual(summary["ambiguous_count"], 0)
        self.assertAlmostEqual(
            summary["accepted_rate"],
            summary["accepted_count"] / summary["ros2_event_count"],
        )
        for name in (
            "ctf_sha256",
            "runtime_normalized_sha256",
            "ros2_normalized_sha256",
            "association_report_sha256",
        ):
            self.assertRegex(summary[name], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
