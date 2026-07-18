import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from experiments.evidence_capture.artifact_manifest import build_artifact_manifest
from experiments.protocol.matrix import load_experiment_matrix
from scripts.run_formal_experiment_session import run_formal_session
from scripts.run_repeated_optimization_campaign import _git_commit


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_MATRIX = load_experiment_matrix(
    ROOT / "experiments/protocol/formal_experiment_matrix.json"
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(root, path):
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha(path),
    }


def write_matrix(path, case_count=3):
    value = copy.deepcopy(PUBLIC_MATRIX)
    value["cases"] = [
        row
        for row in value["cases"]
        if row["case_id"]
        in {
            "diagnosis_f1_control",
            "diagnosis_f1_injected",
            "diagnosis_f6_control",
        }
    ][:case_count]
    for row in value["cases"]:
        row["repetitions"] = 1
    write_json(path, value)
    return value


def write_capabilities(path, is_wsl=True):
    requirements = {
        item for row in PUBLIC_MATRIX["cases"] for item in row["requirements"]
    }
    write_json(
        path,
        {
            "schema_version": 1,
            "platform_label": "x86-wsl" if is_wsl else "x86-native",
            "host": {
                "hostname": "test-host",
                "system": "Linux",
                "machine": "x86_64",
                "kernel": "6.1",
                "is_wsl": is_wsl,
            },
            "readiness": {
                name: {"status": "ready", "path": name, "reason": "test"}
                for name in requirements
            },
            "provenance": {"git_commit": _git_commit(), "git_status": ""},
        },
    )


def execute_success(command):
    output = Path(command[command.index("--output-dir") + 1])
    child_role = command[command.index("--dataset-role") + 1]
    write_json(output / "summary.json", {"status": "completed"})
    write_json(output / "run_manifest.json", {"dataset_role": child_role})
    if "--fault-id" in command:
        write_fault_artifact_manifest(command)
    return 0


def write_fault_artifact_manifest(command):
    output = Path(command[command.index("--output-dir") + 1])
    fault_id = command[command.index("--fault-id") + 1]
    variant = command[command.index("--condition-variant") + 1]
    child_role = command[command.index("--dataset-role") + 1]
    paths = {
        "runtime_events": output / "runtime_events.jsonl",
        "run_manifest": output / "run_manifest.json",
        "oracle_manifest": output / "oracle_manifest.json",
        "command_manifest": output / "command.json",
        "fault_summary": output / "summary.json",
    }
    paths["runtime_events"].write_text("{}\n", encoding="utf-8")
    write_json(paths["oracle_manifest"], {"fault_id": fault_id})
    write_json(paths["command_manifest"], {"argv": command})
    value = build_artifact_manifest(
        fault_id=fault_id,
        condition_variant=variant,
        dataset_role=child_role,
        case_root=output,
        artifacts=paths,
    )
    write_json(output / "artifact_manifest.json", value)


def write_terminal(session_root, row):
    output = session_root / row["output_dir"]
    started = output / "case_started.json"
    write_json(
        started,
        {
            "schema_version": "formal-experiment-case-started/v1",
            "run_id": row["run_id"],
            "dataset_role": "pilot",
            "argv": row["argv"],
        },
    )
    report = session_root / row["expected_report"]
    role_file = session_root / row["role_evidence_path"]
    write_json(report, {"status": "completed"})
    write_json(
        role_file,
        {"dataset_role": row["expected_child_dataset_role"]},
    )
    files = {started, report, role_file}
    if "expected_artifact_manifest" in row:
        command = row["argv"]
        write_fault_artifact_manifest(command)
        files.add(session_root / row["expected_artifact_manifest"])
    write_json(
        output / "case_result.json",
        {
            "schema_version": "formal-experiment-case-result/v1",
            "run_id": row["run_id"],
            "dataset_role": "pilot",
            "status": "successful",
            "reason_code": "",
            "return_code": 0,
            "artifacts": [artifact(session_root, path) for path in sorted(files)],
        },
    )


class FormalSessionCliTest(unittest.TestCase):
    def test_pilot_dry_run_writes_plan_and_invokes_nothing(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "session"
            write_matrix(matrix, case_count=2)
            write_capabilities(capabilities)

            summary = run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=[
                    "diagnosis_f1_control",
                    "diagnosis_f1_injected",
                ],
                dataset_role="pilot",
                session_name="pilot_dry_run",
                seed=7,
                output_dir=output,
                safe_root=root / "build",
                dry_run=True,
                resume=False,
                execute_case=lambda command: calls.append(command) or 0,
            )

            self.assertTrue((output / "qualification.json").is_file())
            self.assertTrue((output / "session_manifest.json").is_file())
            self.assertTrue((output / "session_manifest.sha256").is_file())
            self.assertTrue((output / "integrity.json").is_file())
            self.assertFalse((output / "cases").exists())

        self.assertEqual(calls, [])
        self.assertEqual(summary["status"], "planned")
        self.assertFalse(summary["execution_performed"])
        self.assertFalse(summary["formal_experiment_allowed"])

    def test_wsl_test_role_is_denied_before_execution(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "denied"
            write_matrix(matrix, case_count=1)
            write_capabilities(capabilities, is_wsl=True)

            summary = run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=["diagnosis_f1_control"],
                dataset_role="test",
                session_name="wsl_test",
                seed=7,
                output_dir=output,
                safe_root=root / "build",
                dry_run=False,
                resume=False,
                execute_case=lambda command: calls.append(command) or 0,
            )

        self.assertEqual(calls, [])
        self.assertEqual(summary["status"], "denied")
        self.assertFalse(summary["formal_experiment_allowed"])

    def test_successful_fault_case_records_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "session"
            write_matrix(matrix, case_count=1)
            write_capabilities(capabilities)

            summary = run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=["diagnosis_f1_control"],
                dataset_role="pilot",
                session_name="artifact_success",
                seed=7,
                output_dir=output,
                safe_root=root / "build",
                dry_run=False,
                resume=False,
                execute_case=execute_success,
            )
            result_path = next(output.glob("cases/*/case_result.json"))
            result = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(result["status"], "successful")
        self.assertTrue(
            any(
                row["path"].endswith("/artifact_manifest.json")
                for row in result["artifacts"]
            )
        )

    def test_missing_or_tampered_fault_artifacts_fail_the_case(self):
        def missing(command):
            output = Path(command[command.index("--output-dir") + 1])
            child_role = command[command.index("--dataset-role") + 1]
            write_json(output / "summary.json", {"status": "completed"})
            write_json(output / "run_manifest.json", {"dataset_role": child_role})
            return 0

        def tampered(command):
            execute_success(command)
            output = Path(command[command.index("--output-dir") + 1])
            (output / "runtime_events.jsonl").write_text("[]\n", encoding="utf-8")
            return 0

        for executor, expected_reason in (
            (missing, "artifact_manifest_missing"),
            (tampered, "artifact_hash_mismatch"),
        ):
            with (
                self.subTest(reason=expected_reason),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                matrix = root / "matrix.json"
                capabilities = root / "capabilities.json"
                output = root / "session"
                write_matrix(matrix, case_count=1)
                write_capabilities(capabilities)
                run_formal_session(
                    matrix_path=matrix,
                    capability_path=capabilities,
                    selected_case_ids=["diagnosis_f1_control"],
                    dataset_role="pilot",
                    session_name="artifact_failure",
                    seed=7,
                    output_dir=output,
                    safe_root=root / "build",
                    dry_run=False,
                    resume=False,
                    execute_case=executor,
                )
                result_path = next(output.glob("cases/*/case_result.json"))
                result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason_code"], expected_reason)

    def test_manifest_exists_before_execution_and_failure_does_not_abort(self):
        calls = []

        def execute(command):
            output = Path(command[command.index("--output-dir") + 1])
            session_root = output.parents[1]
            self.assertTrue((session_root / "session_manifest.json").is_file())
            calls.append(command)
            if len(calls) == 2:
                return 1
            return execute_success(command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "session"
            write_matrix(matrix, case_count=3)
            write_capabilities(capabilities)

            summary = run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=[
                    row["case_id"] for row in json.loads(matrix.read_text())["cases"]
                ],
                dataset_role="pilot",
                session_name="execution_test",
                seed=9,
                output_dir=output,
                safe_root=root / "build",
                dry_run=False,
                resume=False,
                execute_case=execute,
            )
            results = list(output.glob("cases/*/case_result.json"))

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(results), 3)
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(summary["counts"]["failed"], 1)

    def test_resume_skips_terminal_marks_started_and_runs_only_new(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "session"
            value = write_matrix(matrix, case_count=3)
            write_capabilities(capabilities)
            case_ids = [row["case_id"] for row in value["cases"]]
            run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=case_ids,
                dataset_role="pilot",
                session_name="resume_test",
                seed=11,
                output_dir=output,
                safe_root=root / "build",
                dry_run=True,
                resume=False,
            )
            manifest = json.loads((output / "session_manifest.json").read_text())
            write_terminal(output, manifest["runs"][0])
            second_output = output / manifest["runs"][1]["output_dir"]
            write_json(
                second_output / "case_started.json",
                {
                    "schema_version": "formal-experiment-case-started/v1",
                    "run_id": manifest["runs"][1]["run_id"],
                    "dataset_role": "pilot",
                },
            )

            summary = run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=case_ids,
                dataset_role="pilot",
                session_name="resume_test",
                seed=11,
                output_dir=output,
                safe_root=root / "build",
                dry_run=False,
                resume=True,
                execute_case=lambda command: (
                    calls.append(command) or execute_success(command)
                ),
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["counts"]["successful"], 2)
        self.assertEqual(summary["counts"]["interrupted"], 1)
        self.assertEqual(summary["status"], "incomplete")

    def test_resume_rejects_manifest_or_input_drift_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "session"
            value = write_matrix(matrix, case_count=1)
            write_capabilities(capabilities)
            case_ids = [row["case_id"] for row in value["cases"]]
            run_formal_session(
                matrix_path=matrix,
                capability_path=capabilities,
                selected_case_ids=case_ids,
                dataset_role="pilot",
                session_name="drift_test",
                seed=1,
                output_dir=output,
                safe_root=root / "build",
                dry_run=True,
                resume=False,
            )
            (output / "session_manifest.sha256").write_text("0" * 64 + "\n")
            calls = []
            with self.assertRaisesRegex(ValueError, "manifest hash"):
                run_formal_session(
                    matrix_path=matrix,
                    capability_path=capabilities,
                    selected_case_ids=case_ids,
                    dataset_role="pilot",
                    session_name="drift_test",
                    seed=1,
                    output_dir=output,
                    safe_root=root / "build",
                    dry_run=False,
                    resume=True,
                    execute_case=lambda command: calls.append(command) or 0,
                )
            self.assertEqual(calls, [])

    def test_non_resume_rejects_existing_output_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            capabilities = root / "capabilities.json"
            output = root / "existing"
            write_matrix(matrix, case_count=1)
            write_capabilities(capabilities)
            output.mkdir()
            marker = output / "marker"
            marker.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already exists"):
                run_formal_session(
                    matrix_path=matrix,
                    capability_path=capabilities,
                    selected_case_ids=["diagnosis_f1_control"],
                    dataset_role="pilot",
                    session_name="existing",
                    seed=1,
                    output_dir=output,
                    safe_root=root / "build",
                    dry_run=True,
                    resume=False,
                )

            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_public_docs_freeze_readiness_commands_and_data_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        optimizer_readme = (ROOT / "optimizer/README.md").read_text(encoding="utf-8")
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for expected in (
            "scripts/check_platform_capabilities.py",
            "scripts/run_formal_experiment_session.py",
            "--dataset-role pilot",
            "--dataset-role test",
            "--dry-run",
            "--resume",
            "WSL",
            "X5",
            "artifact_manifest.json",
            "F3/F4",
            "F2/F3/F5",
            "comparable",
            "full ROS 2 trace export",
            "does not establish X5 measurement results",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, readme + optimizer_readme)
        for pattern in (
            "data/raw/",
            "data/processed/",
            "data/reports/",
            "*.docx",
            "*.pdf",
            "*.zip",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignore)
        self.assertIn("does not contain measurement evidence", readme)


if __name__ == "__main__":
    unittest.main()
