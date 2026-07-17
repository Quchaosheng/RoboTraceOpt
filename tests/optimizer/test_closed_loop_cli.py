import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_closed_loop_optimization import run_closed_loop


def diagnosis(cause="executor_queueing", status="diagnosed"):
    return {
        "schema_version": "diagnosis-report/v1",
        "trace_id": "trace-1",
        "status": status,
        "evidence_state": "valid" if status == "diagnosed" else "not_observed",
        "confidence": 0.9 if status == "diagnosed" else 0.0,
        "completeness": 1.0,
        "top_1": cause if status == "diagnosed" else None,
        "top_k": [cause] if status == "diagnosed" else [],
    }


def baseline(cause="executor_queueing", config=None):
    return {
        "schema_version": "optimization-baseline-profile/v1",
        "cause_id": cause,
        "baseline_config": config or {"executor_threads": 1},
    }


def write_report(output: Path, objective: float) -> None:
    output.mkdir(parents=True)
    (output / "trial_report.json").write_text(
        json.dumps(
            {
                "schema_version": "optimization-runtime-trial/v1",
                "development_only": True,
                "formal_inference_allowed": False,
                "complete_trace_rate": 1.0,
                "complete_trace_count": 2,
                "metrics_ns": {
                    "callback_dispatch_upper_bound_ns": {"p95": objective}
                },
            }
        ),
        encoding="utf-8",
    )


def run_args(directory: str):
    return {
        "strategy": "guided",
        "budget": 2,
        "seed": 7,
        "duration_seconds": 1,
        "minimum_confidence": 0.6,
        "minimum_completeness": 1.0,
        "quantile": "p95",
        "minimum_improvement_ratio": 0.0,
        "minimum_complete_trace_rate_delta": 0.0,
        "output_dir": Path(directory) / "run",
        "safe_root": Path(directory) / "build",
    }


class ClosedLoopCliTest(unittest.TestCase):
    def test_denied_diagnosis_starts_no_trial(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            summary = run_closed_loop(
                diagnosis(status="abstained"),
                baseline(),
                **run_args(directory),
                execute_trial=lambda command: calls.append(command) or 0,
            )
        self.assertEqual(summary["status"], "denied")
        self.assertEqual(calls, [])

    def test_runs_baseline_and_selects_an_improving_candidate(self) -> None:
        def execute(command):
            output = Path(command[command.index("--output-dir") + 1])
            threads = command[command.index("--executor-threads") + 1]
            write_report(output, 100.0 if threads == "1" else 70.0)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = run_args(directory)
            summary = run_closed_loop(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
            decision = json.loads(
                (args["output_dir"] / "decision.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (args["output_dir"] / "closed_loop_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(decision["action"], "apply_candidate")
        self.assertEqual(decision["selected_config"], {"executor_threads": 4})
        self.assertEqual(len(manifest["inputs"]["diagnosis"]["sha256"]), 64)

    def test_existing_output_is_rejected_before_execution(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            args = run_args(directory)
            args["output_dir"].mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_closed_loop(
                    diagnosis(),
                    baseline(),
                    **args,
                    execute_trial=lambda command: calls.append(command) or 0,
                )
        self.assertEqual(calls, [])

    def test_unsupported_runtime_cause_writes_denial_without_execution(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            summary = run_closed_loop(
                diagnosis(cause="scheduling_delay"),
                baseline("scheduling_delay", {"target_cpu": 1}),
                **run_args(directory),
                execute_trial=lambda command: calls.append(command) or 0,
            )
        self.assertEqual(summary["status"], "denied")
        self.assertEqual(summary["reason_code"], "unsupported_runtime_action")
        self.assertEqual(calls, [])

    def test_baseline_failure_aborts_candidates(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            summary = run_closed_loop(
                diagnosis(),
                baseline(),
                **run_args(directory),
                execute_trial=lambda command: calls.append(command) or 1,
            )
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["reason_code"], "baseline_trial_failed")
        self.assertEqual(len(calls), 1)

    def test_failed_candidate_consumes_budget_and_later_candidate_runs(self) -> None:
        calls = []

        def execute(command):
            calls.append(command)
            output = Path(command[command.index("--output-dir") + 1])
            threads = command[command.index("--executor-threads") + 1]
            if threads == "2":
                return 1
            write_report(output, 100.0 if threads == "1" else 80.0)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = run_args(directory)
            args["budget"] = 3
            summary = run_closed_loop(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
        self.assertEqual(summary["failed_candidate_count"], 1)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
