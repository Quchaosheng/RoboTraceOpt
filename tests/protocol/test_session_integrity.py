import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()