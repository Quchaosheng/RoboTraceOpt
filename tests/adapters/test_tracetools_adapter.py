import json
import unittest
from pathlib import Path

from diagnosis.adapters.errors import AdapterReject
from diagnosis.adapters.tracetools_adapter import (
    adapt_tracetools_jsonl,
    adapt_tracetools_record,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "tracetools"


class TracetoolsAdapterTest(unittest.TestCase):
    def test_adapts_real_w1_fixture_without_pretending_trace_assignment(self) -> None:
        fixture = FIXTURE_ROOT / "w1_ros2_events.jsonl"
        with fixture.open("r", encoding="utf-8") as handle:
            record = json.loads(next(handle))

        event = adapt_tracetools_record(
            record, source_file=fixture.as_posix(), record_index=1
        )

        self.assertEqual(event.source, "ros2_tracing")
        self.assertEqual(event.event_type, "ros2:rcl_init")
        self.assertEqual(event.timestamp_ns, 691453036841)
        self.assertEqual(event.clock_id, "monotonic")
        self.assertEqual(event.pid, 477)
        self.assertEqual(event.tid, 477)
        self.assertEqual(event.host_id, "chaosheng")
        self.assertEqual(event.trace_id, "")
        self.assertEqual(event.stage, "")
        self.assertEqual(event.attributes["clock"]["ns_from_origin"], 1784105346552079364)
        self.assertEqual(event.provenance["record_index"], 1)

    def test_all_real_fixture_records_normalize(self) -> None:
        fixture = FIXTURE_ROOT / "w1_ros2_events.jsonl"
        manifest = json.loads(
            (FIXTURE_ROOT / "w1_ros2_events.manifest.json").read_text(encoding="utf-8")
        )
        with fixture.open("r", encoding="utf-8") as handle:
            events = adapt_tracetools_jsonl(handle, source_file=fixture.as_posix())

        self.assertEqual(len(events), manifest["event_count"])
        self.assertEqual(len(events), 98)
        self.assertTrue(all(event.clock_id == "monotonic" for event in events))
        self.assertTrue(all(event.pid > 0 and event.tid > 0 for event in events))

    def test_converts_non_nanosecond_clock_frequency(self) -> None:
        record = {
            "event_name": "ros2:callback_start",
            "host_id": "host-a",
            "clock": {
                "name": "monotonic",
                "frequency": 1_000_000,
                "value": 2_500,
                "ns_from_origin": 123,
                "offset_seconds": 0,
                "offset_cycles": 0,
                "origin_is_unix_epoch": False,
            },
            "context": {"vpid": 10, "vtid": 11, "procname": "node", "cpu_id": 2},
            "payload": {"callback": 42},
        }

        event = adapt_tracetools_record(record, source_file="trace.jsonl", record_index=4)

        self.assertEqual(event.timestamp_ns, 2_500_000)

    def test_rejects_unknown_clock_class(self) -> None:
        record = {
            "event_name": "ros2:callback_end",
            "host_id": "host-a",
            "clock": {"name": "unknown", "frequency": 1_000_000_000, "value": 1},
            "context": {"vpid": 10, "vtid": 11},
            "payload": {},
        }

        with self.assertRaises(AdapterReject) as context:
            adapt_tracetools_record(record, source_file="trace.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "unknown_clock")


if __name__ == "__main__":
    unittest.main()
