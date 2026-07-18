import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from experiments.evidence_capture.artifact_manifest import build_artifact_manifest
from experiments.protocol.session_integrity import (
    assess_session_integrity,
    mark_interrupted_runs,
)


def manifest():
    runs = []
    for index in range(1, 4):
        output = f"cases/{index:03d}_run_{index}"
        runs.append(
            {
                "sequence_index": index,
                "run_id": f"run_{index}",
                "output_dir": output,
                "expected_report": f"{output}/summary.json",
                "role_evidence_path": f"{output}/summary.json",
                "expected_child_dataset_role": "pilot",
            }
        )
    return {
        "schema_version": "formal-experiment-session-manifest/v1",
        "dataset_role": "pilot",
        "runs": runs,
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def artifact(root, path):
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def write_started(root, row):
    path = root / row["output_dir"] / "case_started.json"
    write_json(
        path,
        {
            "schema_version": "formal-experiment-case-started/v1",
            "run_id": row["run_id"],
            "dataset_role": "pilot",
        },
    )
    return path


def write_result(root, row, status="successful", role="pilot"):
    output = root / row["output_dir"]
    started = write_started(root, row)
    report = root / row["expected_report"]
    write_json(report, {"dataset_role": role, "status": "completed"})
    result_path = output / "case_result.json"
    write_json(
        result_path,
        {
            "schema_version": "formal-experiment-case-result/v1",
            "run_id": row["run_id"],
            "dataset_role": "pilot",
            "status": status,
            "reason_code": "" if status == "successful" else "trial_failed",
            "return_code": 0 if status == "successful" else 1,
            "artifacts": [artifact(root, started), artifact(root, report)],
        },
    )
    return result_path


class SessionIntegrityTest(unittest.TestCase):
    def test_complete_session_is_reconstructed_from_files(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for row in value["runs"]:
                write_result(root, row)

            audit = assess_session_integrity(value, root)

        self.assertEqual(
            audit["counts"],
            {
                "planned": 3,
                "not_started": 0,
                "running": 0,
                "successful": 3,
                "failed": 0,
                "interrupted": 0,
            },
        )
        self.assertEqual(audit["status"], "complete")
        self.assertEqual(audit["errors"], [])

    def test_nonterminal_failed_and_interrupted_states_are_incomplete(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_result(root, value["runs"][0], status="failed")
            write_started(root, value["runs"][1])

            before = assess_session_integrity(value, root)
            interrupted = mark_interrupted_runs(value, root)
            after = assess_session_integrity(value, root)

        self.assertEqual(before["counts"]["failed"], 1)
        self.assertEqual(before["counts"]["running"], 1)
        self.assertEqual(before["counts"]["not_started"], 1)
        self.assertEqual(interrupted, ["run_2"])
        self.assertEqual(after["counts"]["interrupted"], 1)
        self.assertEqual(after["counts"]["running"], 0)
        self.assertEqual(after["status"], "incomplete")

    def test_mark_interrupted_never_changes_terminal_results(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = write_result(root, value["runs"][0], status="failed")
            original = terminal.read_bytes()
            write_started(root, value["runs"][1])

            mark_interrupted_runs(value, root)

            self.assertEqual(terminal.read_bytes(), original)

    def test_hash_role_and_unreferenced_directory_errors_are_invalid(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = write_result(root, value["runs"][0], role="test")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["artifacts"][0]["sha256"] = "0" * 64
            write_json(result_path, result)
            (root / "cases/unreferenced").mkdir(parents=True)

            audit = assess_session_integrity(value, root)

        self.assertEqual(audit["status"], "invalid")
        self.assertIn("artifact_hash_mismatch", audit["errors"])
        self.assertIn("child_dataset_role_mismatch", audit["errors"])
        self.assertIn("unreferenced_case_directory", audit["errors"])

    def test_duplicate_runs_path_escape_and_result_role_are_invalid(self):
        duplicate = manifest()
        duplicate["runs"][1]["run_id"] = duplicate["runs"][0]["run_id"]
        escaped = manifest()
        escaped["runs"][0]["output_dir"] = "../escape"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate_audit = assess_session_integrity(duplicate, root)
            escaped_audit = assess_session_integrity(escaped, root)

        self.assertEqual(duplicate_audit["status"], "invalid")
        self.assertIn("duplicate_run_id", duplicate_audit["errors"])
        self.assertEqual(escaped_audit["status"], "invalid")
        self.assertIn("path_escape", escaped_audit["errors"])

        role_manifest = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = write_result(root, role_manifest["runs"][0])
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["dataset_role"] = "test"
            write_json(result_path, result)
            role_audit = assess_session_integrity(role_manifest, root)
        self.assertEqual(role_audit["status"], "invalid")
        self.assertIn("result_dataset_role_mismatch", role_audit["errors"])

    def test_nested_fault_artifacts_are_revalidated_from_the_manifest(self):
        value = manifest()
        row = value["runs"][0]
        value["runs"] = [row]
        output_relative = row["output_dir"]
        row["role_evidence_path"] = f"{output_relative}/run_manifest.json"
        row["expected_child_dataset_role"] = "development"
        row["expected_artifact_manifest"] = f"{output_relative}/artifact_manifest.json"
        row["expected_artifact_identity"] = {
            "fault_id": "F1",
            "condition_variant": "control",
            "dataset_role": "development",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / output_relative
            started = write_started(root, row)
            summary = output / "summary.json"
            run_manifest = output / "run_manifest.json"
            runtime_events = output / "runtime_events.jsonl"
            oracle = output / "oracle_manifest.json"
            command = output / "command.json"
            write_json(summary, {"status": "completed"})
            write_json(run_manifest, {"dataset_role": "development"})
            runtime_events.write_text("{}\n", encoding="utf-8")
            write_json(oracle, {"fault_id": "F1"})
            write_json(command, {"argv": ["test"]})
            child_manifest = build_artifact_manifest(
                fault_id="F1",
                condition_variant="control",
                dataset_role="development",
                case_root=output,
                artifacts={
                    "runtime_events": runtime_events,
                    "run_manifest": run_manifest,
                    "oracle_manifest": oracle,
                    "command_manifest": command,
                    "fault_summary": summary,
                },
            )
            child_manifest_path = output / "artifact_manifest.json"
            write_json(child_manifest_path, child_manifest)
            write_json(
                output / "case_result.json",
                {
                    "schema_version": "formal-experiment-case-result/v1",
                    "run_id": row["run_id"],
                    "dataset_role": "pilot",
                    "status": "successful",
                    "reason_code": "",
                    "return_code": 0,
                    "artifacts": [
                        artifact(root, path)
                        for path in (
                            started,
                            summary,
                            run_manifest,
                            child_manifest_path,
                        )
                    ],
                },
            )

            before = assess_session_integrity(value, root)
            runtime_events.write_text("[]\n", encoding="utf-8")
            after = assess_session_integrity(value, root)

        self.assertEqual(before["status"], "complete")
        self.assertEqual(after["status"], "invalid")
        self.assertIn("nested_artifact_hash_mismatch", after["errors"])


if __name__ == "__main__":
    unittest.main()
