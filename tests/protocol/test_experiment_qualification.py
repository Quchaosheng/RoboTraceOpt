import copy
import unittest
from pathlib import Path

from experiments.protocol.matrix import load_experiment_matrix
from experiments.protocol.qualification import qualify_experiment_session


MATRIX = load_experiment_matrix(Path("experiments/protocol/formal_experiment_matrix.json"))


def capability_report(
    *,
    label="x86-wsl",
    machine="x86_64",
    is_wsl=True,
):
    names = {
        requirement
        for case in MATRIX["cases"]
        for requirement in case["requirements"]
    }
    return {
        "schema_version": 1,
        "platform_label": label,
        "host": {
            "hostname": "test-host",
            "system": "Linux",
            "machine": machine,
            "kernel": "6.1.0",
            "is_wsl": is_wsl,
        },
        "readiness": {
            name: {"status": "ready", "path": name, "reason": "test"}
            for name in names
        },
        "provenance": {"git_commit": "c" * 40, "git_status": ""},
    }


def qualify(
    report,
    role="pilot",
    selected=("optimization_executor",),
    git_status="",
):
    return qualify_experiment_session(
        MATRIX,
        report,
        selected_case_ids=list(selected),
        dataset_role=role,
        matrix_sha256="a" * 64,
        capability_sha256="b" * 64,
        git_commit="c" * 40,
        git_status=git_status,
    )


class ExperimentQualificationTest(unittest.TestCase):
    def test_wsl_allows_pilot_but_denies_test(self):
        pilot = qualify(capability_report())
        self.assertEqual(pilot["status"], "allowed")
        self.assertFalse(pilot["formal_experiment_allowed"])

        denied = qualify(capability_report(), role="test")
        self.assertEqual(denied["status"], "denied")
        self.assertIn("wsl_formal_role_forbidden", denied["reason_codes"])

    def test_native_x86_and_matching_x5_allow_test(self):
        native = qualify(
            capability_report(label="x86-native", is_wsl=False), role="test"
        )
        x5 = qualify(
            capability_report(
                label="rdk-x5", machine="aarch64", is_wsl=False
            ),
            role="test",
        )

        self.assertEqual(native["status"], "allowed")
        self.assertTrue(native["formal_experiment_allowed"])
        self.assertEqual(x5["status"], "allowed")
        self.assertTrue(x5["formal_experiment_allowed"])

    def test_x5_label_requires_arm_architecture(self):
        result = qualify(
            capability_report(label="rdk-x5", machine="x86_64", is_wsl=False),
            role="test",
        )

        self.assertEqual(result["status"], "denied")
        self.assertIn("platform_label_architecture_mismatch", result["reason_codes"])

    def test_formal_roles_require_clean_git(self):
        result = qualify(
            capability_report(label="x86-native", is_wsl=False),
            role="calibration",
            git_status=" M optimizer/README.md",
        )

        self.assertEqual(result["status"], "denied")
        self.assertIn("dirty_formal_worktree", result["reason_codes"])

    def test_selected_partial_capability_denies_but_unselected_does_not(self):
        report = capability_report(label="x86-native", is_wsl=False)
        report["readiness"]["ros2_tracing"]["status"] = "partial"
        denied = qualify(
            report,
            selected=("diagnosis_f2_control",),
        )
        allowed = qualify(report, selected=("optimization_executor",))

        self.assertEqual(denied["status"], "denied")
        self.assertIn("capability_not_ready", denied["reason_codes"])
        self.assertEqual(
            denied["cases"][0]["missing_requirements"], ["ros2_tracing"]
        )
        self.assertEqual(allowed["status"], "allowed")

    def test_rejects_invalid_role_selection_and_hashes(self):
        report = capability_report()
        with self.assertRaisesRegex(ValueError, "dataset role"):
            qualify(report, role="formal")
        with self.assertRaisesRegex(ValueError, "selected cases"):
            qualify(report, selected=())
        with self.assertRaisesRegex(ValueError, "duplicate selected case"):
            qualify(
                report,
                selected=("optimization_executor", "optimization_executor"),
            )
        with self.assertRaisesRegex(ValueError, "matrix_sha256"):
            qualify_experiment_session(
                MATRIX,
                report,
                selected_case_ids=["optimization_executor"],
                dataset_role="pilot",
                matrix_sha256="bad",
                capability_sha256="b" * 64,
                git_commit="c" * 40,
                git_status="",
            )

    def test_report_is_deterministic_and_does_not_mutate_inputs(self):
        report = capability_report()
        before = copy.deepcopy(report)

        first = qualify(report)
        second = qualify(report)

        self.assertEqual(first, second)
        self.assertEqual(report, before)


if __name__ == "__main__":
    unittest.main()
