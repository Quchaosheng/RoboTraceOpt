import copy
import sys
import unittest
from pathlib import Path

from experiments.protocol.matrix import load_experiment_matrix
from experiments.protocol.runner_registry import build_case_argv
from experiments.protocol.session_manifest import build_session_manifest


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "experiments/protocol/formal_experiment_matrix.json"
MATRIX = load_experiment_matrix(MATRIX_PATH)


def qualification(case_ids, role="pilot"):
    return {
        "schema_version": "formal-experiment-qualification/v1",
        "status": "allowed",
        "reason_codes": [],
        "dataset_role": role,
        "development_only": role in {"development", "pilot"},
        "formal_experiment_allowed": role == "test",
        "platform_label": "x86-native",
        "matrix_sha256": "a" * 64,
        "capability_sha256": "b" * 64,
        "git_commit": "c" * 40,
        "git_status": "",
        "selected_case_ids": list(case_ids),
        "cases": [],
    }


def build(matrix, case_ids, role="pilot", name="formal_session"):
    return build_session_manifest(
        matrix,
        qualification(case_ids, role),
        session_name=name,
        dataset_role=role,
        seed=20260718,
        session_root=Path("/tmp/formal_session"),
        repository_root=ROOT,
        safe_root=Path("/tmp/robotraceopt_build"),
        matrix_source={"path": str(MATRIX_PATH), "sha256": "a" * 64},
        capability_source={"path": "/tmp/capabilities.json", "sha256": "b" * 64},
        generated_at_utc="2026-07-18T00:00:00+00:00",
        git_commit="c" * 40,
    )


class SessionManifestTest(unittest.TestCase):
    def test_full_matrix_compiles_122_deterministic_runs(self):
        case_ids = [row["case_id"] for row in MATRIX["cases"]]

        first = build(MATRIX, case_ids)
        second = build(MATRIX, case_ids)

        self.assertEqual(first, second)
        self.assertEqual(
            first["schema_version"],
            "formal-experiment-session-manifest/v1",
        )
        self.assertEqual(len(first["runs"]), 122)
        self.assertEqual(first["dataset_role"], "pilot")
        self.assertTrue(first["development_only"])
        self.assertFalse(first["formal_experiment_allowed"])
        self.assertTrue(all(isinstance(row["argv"], list) for row in first["runs"]))
        self.assertFalse(
            any(
                "shell=True" in part
                for row in first["runs"]
                for part in row["argv"]
            )
        )

    def test_balanced_fault_rotation_places_two_cases_twice_per_position(self):
        matrix = copy.deepcopy(MATRIX)
        matrix["cases"] = [
            row
            for row in matrix["cases"]
            if row["case_id"] in {"diagnosis_f1_control", "diagnosis_f1_injected"}
        ]
        for row in matrix["cases"]:
            row["repetitions"] = 4

        manifest = build(matrix, [row["case_id"] for row in matrix["cases"]])

        self.assertEqual(len(manifest["runs"]), 8)
        for counts in manifest["position_counts"].values():
            self.assertEqual(counts, {"1": 2, "2": 2})
        for block in range(1, 5):
            rows = [row for row in manifest["runs"] if row["block_index"] == block]
            self.assertEqual({row["position_index"] for row in rows}, {1, 2})

    def test_fault_commands_map_roles_and_catalog_capabilities(self):
        f3 = next(row for row in MATRIX["cases"] if row["case_id"] == "diagnosis_f3_injected")
        pilot = build_case_argv(
            f3,
            run_id="session_f3_r01",
            dataset_role="pilot",
            output_dir=Path("/tmp/session/case"),
            repository_root=ROOT,
            safe_root=Path("/tmp/build"),
            qualification_path=Path("/tmp/session/qualification.json"),
            seed=7,
        )
        test = build_case_argv(
            f3,
            run_id="session_f3_r01",
            dataset_role="test",
            output_dir=Path("/tmp/session/case"),
            repository_root=ROOT,
            safe_root=Path("/tmp/build"),
            qualification_path=Path("/tmp/session/qualification.json"),
            seed=7,
        )

        self.assertEqual(pilot["argv"][0], sys.executable)
        self.assertEqual(
            pilot["argv"][pilot["argv"].index("--dataset-role") + 1],
            "development",
        )
        self.assertEqual(
            test["argv"][test["argv"].index("--dataset-role") + 1],
            "test",
        )
        for capability in (
            "ros2_runtime",
            "ros2_tracing",
            "stress_ng",
            "taskset",
            "identity_comparable_ebpf",
        ):
            self.assertIn(capability, pilot["argv"])
        self.assertEqual(pilot["expected_report"], "summary.json")
        self.assertEqual(pilot["role_evidence_path"], "run_manifest.json")
        self.assertEqual(pilot["expected_child_dataset_role"], "development")

    def test_formal_optimization_command_contains_frozen_policy(self):
        case = next(row for row in MATRIX["cases"] if row["case_id"] == "optimization_executor")
        invocation = build_case_argv(
            case,
            run_id="x5_executor_r01",
            dataset_role="test",
            output_dir=Path("/tmp/session/case"),
            repository_root=ROOT,
            safe_root=Path("/tmp/build"),
            qualification_path=Path("/tmp/session/qualification.json"),
            seed=20260718,
        )
        argv = invocation["argv"]

        for option, value in (
            ("--dataset-role", "test"),
            ("--repetitions", "20"),
            ("--confidence-level", "0.95"),
            ("--bootstrap-resamples", "10000"),
        ):
            self.assertEqual(argv[argv.index(option) + 1], value)
        self.assertIn("--qualification-report", argv)
        self.assertEqual(invocation["expected_report"], "summary.json")
        self.assertEqual(invocation["role_evidence_path"], "summary.json")
        self.assertEqual(invocation["expected_child_dataset_role"], "test")

    def test_rejects_unsafe_names_and_qualification_mismatches(self):
        with self.assertRaisesRegex(ValueError, "session name"):
            build(MATRIX, ["optimization_executor"], name="bad/name")

        report = qualification(["optimization_executor"], "test")
        with self.assertRaisesRegex(ValueError, "dataset role"):
            build_session_manifest(
                MATRIX,
                report,
                session_name="safe",
                dataset_role="pilot",
                seed=1,
                session_root=Path("/tmp/safe"),
                repository_root=ROOT,
                safe_root=Path("/tmp/build"),
                matrix_source={"path": str(MATRIX_PATH), "sha256": "a" * 64},
                capability_source={"path": "/tmp/cap.json", "sha256": "b" * 64},
                generated_at_utc="2026-07-18T00:00:00+00:00",
                git_commit="c" * 40,
            )


if __name__ == "__main__":
    unittest.main()