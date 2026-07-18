import copy
import unittest
from pathlib import Path

from experiments.protocol.matrix import (
    load_experiment_matrix,
    validate_experiment_matrix,
)


MATRIX = Path("experiments/protocol/formal_experiment_matrix.json")


class ExperimentMatrixTest(unittest.TestCase):
    def test_public_matrix_freezes_diagnosis_and_optimization_cases(self):
        matrix = load_experiment_matrix(MATRIX)

        self.assertEqual(matrix["schema_version"], "formal-experiment-matrix/v1")
        self.assertEqual(len(matrix["cases"]), 14)
        fault_cases = [
            row for row in matrix["cases"] if row["runner_id"] == "fault_condition"
        ]
        self.assertEqual(len(fault_cases), 12)
        self.assertEqual(
            {row["parameters"]["fault_id"] for row in fault_cases},
            {f"F{index}" for index in range(1, 7)},
        )
        self.assertEqual(
            {row["parameters"]["condition_variant"] for row in fault_cases},
            {"control", "injected"},
        )
        self.assertEqual({row["repetitions"] for row in fault_cases}, {10})

        optimization_cases = [
            row
            for row in matrix["cases"]
            if row["runner_id"] == "repeated_optimization"
        ]
        self.assertEqual(
            {row["case_id"] for row in optimization_cases},
            {"optimization_executor", "optimization_qos"},
        )
        self.assertEqual(
            {row["parameters"]["campaign_repetitions"] for row in optimization_cases},
            {20},
        )

    def test_rejects_duplicate_ids_unknown_keys_and_invalid_runner(self):
        matrix = load_experiment_matrix(MATRIX)

        duplicate = copy.deepcopy(matrix)
        duplicate["cases"][1]["case_id"] = duplicate["cases"][0]["case_id"]
        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            validate_experiment_matrix(duplicate)

        extra = copy.deepcopy(matrix)
        extra["cases"][0]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unknown case fields"):
            validate_experiment_matrix(extra)

        invalid = copy.deepcopy(matrix)
        invalid["cases"][0]["runner_id"] = "shell"
        with self.assertRaisesRegex(ValueError, "runner_id"):
            validate_experiment_matrix(invalid)

    def test_rejects_invalid_capabilities_repetitions_and_parameters(self):
        matrix = load_experiment_matrix(MATRIX)

        capability = copy.deepcopy(matrix)
        capability["cases"][0]["requirements"] = ["imaginary"]
        with self.assertRaisesRegex(ValueError, "capability"):
            validate_experiment_matrix(capability)

        repetitions = copy.deepcopy(matrix)
        repetitions["cases"][0]["repetitions"] = 0
        with self.assertRaisesRegex(ValueError, "repetitions"):
            validate_experiment_matrix(repetitions)

        parameters = copy.deepcopy(matrix)
        parameters["cases"][0]["parameters"]["extra"] = True
        with self.assertRaisesRegex(ValueError, "parameter fields"):
            validate_experiment_matrix(parameters)

    def test_validation_returns_a_deep_copy(self):
        matrix = load_experiment_matrix(MATRIX)
        validated = validate_experiment_matrix(matrix)

        validated["cases"][0]["requirements"].append("cpu_control")

        self.assertNotEqual(validated, matrix)


if __name__ == "__main__":
    unittest.main()
