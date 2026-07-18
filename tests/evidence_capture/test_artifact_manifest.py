from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.evidence_capture.artifact_manifest import (
    ARTIFACT_SCHEMA,
    ArtifactValidationError,
    build_artifact_manifest,
    measure_path,
    required_artifact_roles,
    validate_artifact_manifest,
)


BASE_ROLES = {
    "runtime_events",
    "run_manifest",
    "oracle_manifest",
    "command_manifest",
    "fault_summary",
}
TRACE_ROLES = {
    "process_manifest",
    "clock_calibration",
    "ros2_ctf",
    "ros2_events",
    "ros2_events_manifest",
}
EBPF_ROLES = {
    "process_manifest",
    "ebpf_events",
    "ebpf_capture_summary",
}


class ArtifactManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fault_role_contracts_are_frozen(self) -> None:
        self.assertEqual(required_artifact_roles("F1"), BASE_ROLES)
        self.assertEqual(required_artifact_roles("F2"), BASE_ROLES | TRACE_ROLES)
        self.assertEqual(
            required_artifact_roles("F3"),
            BASE_ROLES
            | TRACE_ROLES
            | {"scheduler_manifest", "ebpf_events", "ebpf_capture_summary"},
        )
        self.assertEqual(required_artifact_roles("F4"), BASE_ROLES | EBPF_ROLES)
        self.assertEqual(required_artifact_roles("F5"), BASE_ROLES | TRACE_ROLES)
        self.assertEqual(required_artifact_roles("F6"), BASE_ROLES)
        with self.assertRaisesRegex(ArtifactValidationError, "fault"):
            required_artifact_roles("F7")

    def test_directory_hash_uses_relative_paths_and_contents(self) -> None:
        ctf = self.root / "ctf"
        self._write(ctf / "b" / "stream", b"events")
        self._write(ctf / "a" / "metadata", b"meta")

        digest = hashlib.sha256()
        for relative, payload in (
            ("a/metadata", b"meta"),
            ("b/stream", b"events"),
        ):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)

        measured = measure_path(ctf)

        self.assertEqual(measured.kind, "directory")
        self.assertEqual(measured.bytes, 10)
        self.assertEqual(measured.sha256, digest.hexdigest())

    def test_builds_and_validates_a_stable_manifest(self) -> None:
        artifacts = self._base_artifacts()

        first = build_artifact_manifest(
            fault_id="F1",
            condition_variant="control",
            dataset_role="test",
            case_root=self.root,
            artifacts=artifacts,
        )
        second = build_artifact_manifest(
            fault_id="F1",
            condition_variant="control",
            dataset_role="test",
            case_root=self.root,
            artifacts=dict(reversed(list(artifacts.items()))),
        )

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], ARTIFACT_SCHEMA)
        self.assertEqual(
            [record["role"] for record in first["artifacts"]],
            sorted(BASE_ROLES),
        )
        self.assertEqual(
            validate_artifact_manifest(
                first,
                case_root=self.root,
                expected_fault_id="F1",
                expected_condition_variant="control",
                expected_dataset_role="test",
            ),
            first,
        )

    def test_rejects_missing_roles_and_paths_outside_the_case(self) -> None:
        missing = self._base_artifacts()
        del missing["fault_summary"]
        with self.assertRaises(ArtifactValidationError) as context:
            build_artifact_manifest(
                fault_id="F1",
                condition_variant="control",
                dataset_role="test",
                case_root=self.root,
                artifacts=missing,
            )
        self.assertEqual(context.exception.reason_code, "artifact_role_missing")

        outside = self.root.parent / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        escaped = self._base_artifacts()
        escaped["fault_summary"] = outside
        with self.assertRaises(ArtifactValidationError) as context:
            build_artifact_manifest(
                fault_id="F1",
                condition_variant="control",
                dataset_role="test",
                case_root=self.root,
                artifacts=escaped,
            )
        self.assertEqual(context.exception.reason_code, "artifact_path_escape")

    def test_detects_identity_and_nested_file_tampering(self) -> None:
        artifacts = self._base_artifacts()
        manifest = build_artifact_manifest(
            fault_id="F1",
            condition_variant="injected",
            dataset_role="calibration",
            case_root=self.root,
            artifacts=artifacts,
        )
        with self.assertRaises(ArtifactValidationError) as context:
            validate_artifact_manifest(
                manifest,
                case_root=self.root,
                expected_fault_id="F1",
                expected_condition_variant="control",
                expected_dataset_role="calibration",
            )
        self.assertEqual(context.exception.reason_code, "artifact_identity_mismatch")

        artifacts["runtime_events"].write_text('{"changed":true}\n', encoding="utf-8")
        with self.assertRaises(ArtifactValidationError) as context:
            validate_artifact_manifest(
                manifest,
                case_root=self.root,
                expected_fault_id="F1",
                expected_condition_variant="injected",
                expected_dataset_role="calibration",
            )
        self.assertIn(
            context.exception.reason_code,
            {"artifact_size_mismatch", "artifact_hash_mismatch"},
        )

    def _base_artifacts(self) -> dict[str, Path]:
        paths = {
            "runtime_events": self.root / "runtime_events.jsonl",
            "run_manifest": self.root / "run_manifest.json",
            "oracle_manifest": self.root / "oracle_manifest.json",
            "command_manifest": self.root / "command.json",
            "fault_summary": self.root / "summary.json",
        }
        for role, path in paths.items():
            path.write_text('{"role":"' + role + '"}\n', encoding="utf-8")
        return paths

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


if __name__ == "__main__":
    unittest.main()
