from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.export_ros2_trace import EXPORT_SCHEMA, export_records
from scripts.export_tracetools_fixture import directory_sha256


class ExportRos2TraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.trace = self.root / "ctf"
        self.trace.mkdir()
        (self.trace / "metadata").write_text("ctf metadata", encoding="utf-8")
        self.output = self.root / "ros2_events.jsonl"
        self.manifest_path = self.root / "ros2_events.manifest.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exports_every_record_without_sampling(self) -> None:
        records = [self._record("ros2:callback_start", index) for index in range(12)]
        records.append(self._record("ros2:callback_end", 20))

        manifest = export_records(
            records,
            trace_path=self.trace,
            output_jsonl=self.output,
            output_manifest=self.manifest_path,
            host_id="x5-a",
            required_events={"ros2:callback_start", "ros2:callback_end"},
            generated_at_utc="2026-07-18T00:00:00+00:00",
        )

        exported = [
            json.loads(line) for line in self.output.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(exported, records)
        self.assertTrue(self.output.read_bytes().endswith(b"\n"))
        self.assertEqual(manifest["schema_version"], EXPORT_SCHEMA)
        self.assertEqual(manifest["event_count"], 13)
        self.assertEqual(manifest["event_counts"]["ros2:callback_start"], 12)
        self.assertEqual(manifest["source_trace_sha256"], directory_sha256(self.trace))
        self.assertEqual(
            json.loads(self.manifest_path.read_text(encoding="utf-8")), manifest
        )

    def test_rejects_missing_required_events_and_mixed_hosts(self) -> None:
        with self.assertRaisesRegex(ValueError, "required events"):
            export_records(
                [self._record("ros2:callback_start", 1)],
                trace_path=self.trace,
                output_jsonl=self.output,
                output_manifest=self.manifest_path,
                host_id="x5-a",
                required_events={"ros2:callback_start", "ros2:callback_end"},
                generated_at_utc="2026-07-18T00:00:00+00:00",
            )

        mixed = [
            self._record("ros2:callback_start", 1),
            self._record("ros2:callback_end", 2, host_id="x5-b"),
        ]
        with self.assertRaisesRegex(ValueError, "host"):
            export_records(
                mixed,
                trace_path=self.trace,
                output_jsonl=self.output,
                output_manifest=self.manifest_path,
                host_id="x5-a",
                required_events={"ros2:callback_start", "ros2:callback_end"},
                generated_at_utc="2026-07-18T00:00:00+00:00",
            )

    def test_rejects_invalid_clock_and_existing_outputs(self) -> None:
        broken = self._record("ros2:callback_start", 1)
        del broken["clock"]["frequency"]
        with self.assertRaisesRegex(ValueError, "clock"):
            export_records(
                [broken],
                trace_path=self.trace,
                output_jsonl=self.output,
                output_manifest=self.manifest_path,
                host_id="x5-a",
                required_events={"ros2:callback_start"},
                generated_at_utc="2026-07-18T00:00:00+00:00",
            )

    def test_direct_script_entrypoint_loads_repository_modules(self) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "export_ros2_trace.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Export all selected ROS 2 CTF events", completed.stdout)

        self.output.write_text("existing\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists"):
            export_records(
                [self._record("ros2:callback_start", 1)],
                trace_path=self.trace,
                output_jsonl=self.output,
                output_manifest=self.manifest_path,
                host_id="x5-a",
                required_events={"ros2:callback_start"},
                generated_at_utc="2026-07-18T00:00:00+00:00",
            )

    @staticmethod
    def _record(event_name: str, value: int, *, host_id: str = "x5-a") -> dict:
        return {
            "event_name": event_name,
            "host_id": host_id,
            "clock": {
                "name": "monotonic",
                "frequency": 1_000_000_000,
                "value": value,
                "ns_from_origin": value,
                "offset_seconds": 0,
                "offset_cycles": 0,
                "origin_is_unix_epoch": False,
            },
            "context": {},
            "payload": {},
        }


if __name__ == "__main__":
    unittest.main()
