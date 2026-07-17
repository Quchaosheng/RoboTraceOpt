import unittest

from diagnosis.adapters.legacy_runtime_event_adapter import adapt_legacy_event


class LegacyRuntimeEventAdapterTest(unittest.TestCase):
    def test_adapts_flat_v1_event_without_guessing_clock_domain(self) -> None:
        old = {
            "trace_id": "trace-1",
            "oracle_id": "oracle-1",
            "sequence_id": 3,
            "source_node": "planner",
            "stage": "planner_publish",
            "timestamp_ns": 123,
            "event_name": "planner_publish",
            "event_type": "runtime",
            "extra_json": "{}",
        }

        event = adapt_legacy_event(old)

        self.assertEqual(event["trace_id"], "trace-1")
        self.assertEqual(event["oracle_id"], "oracle-1")
        self.assertEqual(event["clock_id"], "unknown")
        self.assertEqual(event["host_id"], "unknown")
        self.assertEqual(event["pid"], 0)
        self.assertEqual(event["tid"], 0)
        self.assertEqual(event["duration_ns"], 0)
        self.assertEqual(event["status"], "observed")
        self.assertEqual(event["reason_code"], "")

    def test_accepts_nested_ros_message_shape_and_explicit_provenance(self) -> None:
        old = {
            "header": {
                "trace_id": "trace-2",
                "oracle_id": "oracle-2",
                "sequence_id": 4,
                "source_node": "control",
                "stage": "control_send_end",
                "timestamp_ns": 456,
            },
            "event_name": "control_send_end",
            "event_type": "runtime",
            "extra_json": "{}",
        }

        event = adapt_legacy_event(
            old, legacy_clock_id="realtime", legacy_host_id="archived-host"
        )

        self.assertEqual(event["trace_id"], "trace-2")
        self.assertEqual(event["clock_id"], "realtime")
        self.assertEqual(event["host_id"], "archived-host")

    def test_rejects_missing_required_trace_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "trace_id"):
            adapt_legacy_event(
                {
                    "timestamp_ns": 123,
                    "event_name": "planner_publish",
                    "stage": "planner_publish",
                }
            )


if __name__ == "__main__":
    unittest.main()
