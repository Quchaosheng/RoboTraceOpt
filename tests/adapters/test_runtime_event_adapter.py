import unittest
import json

from diagnosis.adapters.errors import AdapterReject
from diagnosis.adapters.runtime_event_adapter import (
    adapt_runtime_event,
    adapt_runtime_jsonl,
)


def runtime_record() -> dict:
    return {
        "trace_id": "trace-1",
        "oracle_id": "evaluation-only-a",
        "sequence_id": 7,
        "source_node": "planner",
        "stage": "planner_publish",
        "timestamp_ns": 123456,
        "event_name": "planner_publish",
        "event_type": "planner",
        "pid": 101,
        "tid": 102,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "duration_ns": 0,
        "status": "observed",
        "reason_code": "",
        "extra_json": '{"backend":"mock"}',
    }


class RuntimeEventAdapterTest(unittest.TestCase):
    def test_jsonl_adapter_preserves_source_line_numbers(self) -> None:
        first = runtime_record()
        second = runtime_record()
        second["trace_id"] = "trace-2"
        lines = ["\n", json.dumps(first) + "\n", json.dumps(second) + "\n"]

        events = adapt_runtime_jsonl(lines, source_file="runtime_events.jsonl")

        self.assertEqual([event.trace_id for event in events], ["trace-1", "trace-2"])
        self.assertEqual(
            [event.provenance["record_index"] for event in events], [2, 3]
        )

    def test_adapts_v2_record_with_auditable_provenance(self) -> None:
        event = adapt_runtime_event(
            runtime_record(), source_file="run/runtime_events.jsonl", record_index=12
        )

        self.assertEqual(event.event_id, "runtime_event:run/runtime_events.jsonl:12")
        self.assertEqual(event.source, "runtime_event")
        self.assertEqual(event.event_type, "planner_publish")
        self.assertEqual(event.clock_id, "monotonic")
        self.assertEqual(event.pid, 101)
        self.assertEqual(event.tid, 102)
        self.assertEqual(event.attributes["extra"], {"backend": "mock"})
        self.assertEqual(event.provenance["record_index"], 12)

    def test_oracle_id_cannot_influence_formal_normalization(self) -> None:
        first = runtime_record()
        second = runtime_record()
        second["oracle_id"] = "evaluation-only-b"

        first_event = adapt_runtime_event(first, source_file="events.jsonl", record_index=1)
        second_event = adapt_runtime_event(second, source_file="events.jsonl", record_index=1)

        self.assertEqual(first_event, second_event)
        self.assertNotIn("oracle_id", first_event.to_dict())
        self.assertNotIn("evaluation-only", str(first_event.to_dict()))

    def test_rejects_unknown_clock_domain(self) -> None:
        record = runtime_record()
        record["clock_id"] = "unknown"

        with self.assertRaises(AdapterReject) as context:
            adapt_runtime_event(record, source_file="events.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "unknown_clock")

    def test_rejects_non_runtime_process_identity(self) -> None:
        record = runtime_record()
        record["pid"] = 0

        with self.assertRaises(AdapterReject) as context:
            adapt_runtime_event(record, source_file="events.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "invalid_runtime_identity")

    def test_rejects_invalid_extra_json(self) -> None:
        record = runtime_record()
        record["extra_json"] = "not-json"

        with self.assertRaises(AdapterReject) as context:
            adapt_runtime_event(record, source_file="events.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "invalid_extra_json")

    def test_rejects_fractional_integer_field_without_truncation(self) -> None:
        record = runtime_record()
        record["timestamp_ns"] = 123.5

        with self.assertRaises(AdapterReject) as context:
            adapt_runtime_event(record, source_file="events.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "invalid_numeric_field")

    def test_rejects_non_string_extra_json(self) -> None:
        record = runtime_record()
        record["extra_json"] = {"backend": "mock"}

        with self.assertRaises(AdapterReject) as context:
            adapt_runtime_event(record, source_file="events.jsonl", record_index=1)

        self.assertEqual(context.exception.reason_code, "invalid_extra_json")


if __name__ == "__main__":
    unittest.main()
