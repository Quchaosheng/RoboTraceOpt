import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_repeated_optimization_campaign import run_repeated_campaign


ROOT = Path(__file__).resolve().parents[2]


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


def campaign_args(directory):
    return {
        "campaign_name": "executor_repeated_test",
        "strategy": "guided",
        "budget": 4,
        "seed": 20260718,
        "repetitions": 5,
        "duration_seconds": 1,
        "minimum_confidence": 0.6,
        "minimum_completeness": 1.0,
        "quantile": "p95",
        "minimum_improvement_ratio": 0.0,
        "minimum_complete_trace_rate_delta": 0.0,
        "confidence_level": 0.95,
        "bootstrap_resamples": 100,
        "output_dir": Path(directory) / "campaign",
        "safe_root": Path(directory) / "build",
    }


def command_config(command):
    for argument, action in (
        ("--executor-threads", "executor_threads"),
        ("--frame-qos-depth", "frame_qos_depth"),
    ):
        if argument in command:
            return {action: int(command[command.index(argument) + 1])}
    raise AssertionError("candidate argument missing")


def write_report(output, config, objective, rate=1.0):
    output.mkdir(parents=True, exist_ok=True)
    (output / "trial_report.json").write_text(
        json.dumps(
            {
                "schema_version": "optimization-runtime-trial/v1",
                "candidate_config": config,
                "development_only": True,
                "formal_inference_allowed": False,
                "formal_optimization_allowed": False,
                "complete_trace_rate": rate,
                "complete_trace_count": 10,
                "metrics_ns": {
                    "callback_dispatch_upper_bound_ns": {"p95": objective}
                },
            }
        ),
        encoding="utf-8",
    )


class RepeatedCampaignCliTest(unittest.TestCase):
    def test_public_docs_freeze_pilot_command_and_ignore_boundaries(self):
        optimizer_readme = (ROOT / "optimizer/README.md").read_text(
            encoding="utf-8"
        )
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("--repetitions 5", optimizer_readme)
        self.assertIn("--confidence-level 0.95", optimizer_readme)
        self.assertIn("data/raw/optimization/pilot/", optimizer_readme)
        for pattern in ("data/raw/", "data/processed/", "*.docx", "*.pdf", "*.zip"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignore)

    def test_runs_manifest_order_and_selects_stable_candidate(self):
        calls = []

        def execute(command):
            calls.append(command_config(command))
            output = Path(command[command.index("--output-dir") + 1])
            root = output.parents[2]
            self.assertTrue((root / "campaign_manifest.json").is_file())
            config = command_config(command)
            objective = {1: 100.0, 2: 70.0, 3: 80.0, 4: 90.0}[
                config["executor_threads"]
            ]
            write_report(output, config, objective)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            summary = run_repeated_campaign(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
            manifest = json.loads(
                (args["output_dir"] / "campaign_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            decision = json.loads(
                (args["output_dir"] / "decision.json").read_text(encoding="utf-8")
            )

        self.assertEqual(len(calls), 20)
        self.assertEqual(
            calls,
            [row["candidate_config"] for row in manifest["schedule"]["trials"]],
        )
        self.assertEqual(summary["successful_trial_count"], 20)
        self.assertEqual(decision["action"], "apply_candidate")
        self.assertEqual(decision["selected_config"], {"executor_threads": 2})

    def test_candidate_failure_is_retained_and_later_trials_continue(self):
        calls = []
        failed_once = False

        def execute(command):
            nonlocal failed_once
            config = command_config(command)
            calls.append(config)
            output = Path(command[command.index("--output-dir") + 1])
            if config == {"executor_threads": 2} and not failed_once:
                failed_once = True
                output.mkdir(parents=True)
                return 1
            objective = 100.0 if config == {"executor_threads": 1} else 120.0
            write_report(output, config, objective)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            summary = run_repeated_campaign(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
            failed_results = list(args["output_dir"].glob("trials/**/trial_result.json"))

        self.assertEqual(len(calls), 20)
        self.assertEqual(summary["failed_trial_count"], 1)
        self.assertEqual(summary["action"], "restore_baseline")
        self.assertEqual(len(failed_results), 20)

    def test_baseline_failure_invalidates_one_pair_per_candidate(self):
        baseline_failures = 0

        def execute(command):
            nonlocal baseline_failures
            config = command_config(command)
            output = Path(command[command.index("--output-dir") + 1])
            if config == {"executor_threads": 1} and baseline_failures == 0:
                baseline_failures += 1
                output.mkdir(parents=True)
                return 1
            objective = 100.0 if config == {"executor_threads": 1} else 70.0
            write_report(output, config, objective)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            summary = run_repeated_campaign(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
            validations = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(
                    (args["output_dir"] / "candidate_validations").glob("*.json")
                )
            ]

        self.assertEqual(summary["trial_invocation_count"], 20)
        self.assertEqual(summary["action"], "restore_baseline")
        self.assertTrue(validations)
        self.assertTrue(
            all(row["reason_code"] == "incomplete_repeated_evidence" for row in validations)
        )
        self.assertTrue(all(row["failed_pair_count"] == 1 for row in validations))

    def test_denied_or_unsupported_diagnosis_starts_no_trial(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            denied_args = campaign_args(directory)
            denied_args["output_dir"] = Path(directory) / "denied"
            denied = run_repeated_campaign(
                diagnosis(status="abstained"),
                baseline(),
                **denied_args,
                execute_trial=lambda command: calls.append(command) or 0,
            )
            unsupported_args = campaign_args(directory)
            unsupported_args["output_dir"] = Path(directory) / "unsupported"
            unsupported = run_repeated_campaign(
                diagnosis(cause="scheduling_delay"),
                baseline("scheduling_delay", {"target_cpu": 1}),
                **unsupported_args,
                execute_trial=lambda command: calls.append(command) or 0,
            )

        self.assertEqual(calls, [])
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(unsupported["reason_code"], "unsupported_runtime_action")

    def test_existing_output_is_rejected_before_execution(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            args["output_dir"].mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_repeated_campaign(
                    diagnosis(),
                    baseline(),
                    **args,
                    execute_trial=lambda command: calls.append(command) or 0,
                )
        self.assertEqual(calls, [])

    def test_invalid_campaign_parameters_create_no_output(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            args["repetitions"] = 1
            with self.assertRaisesRegex(ValueError, "repetitions"):
                run_repeated_campaign(
                    diagnosis(),
                    baseline(),
                    **args,
                    execute_trial=lambda command: calls.append(command) or 0,
                )
            self.assertFalse(args["output_dir"].exists())
        self.assertEqual(calls, [])

    def test_successful_results_record_report_hashes(self):
        def execute(command):
            config = command_config(command)
            output = Path(command[command.index("--output-dir") + 1])
            write_report(output, config, 100.0)
            return 0

        with tempfile.TemporaryDirectory() as directory:
            args = campaign_args(directory)
            run_repeated_campaign(
                diagnosis(), baseline(), **args, execute_trial=execute
            )
            result_paths = sorted(args["output_dir"].glob("trials/**/trial_result.json"))
            results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]

        self.assertEqual(len(results), 20)
        self.assertTrue(all(len(row["trial_report_sha256"]) == 64 for row in results))


if __name__ == "__main__":
    unittest.main()
