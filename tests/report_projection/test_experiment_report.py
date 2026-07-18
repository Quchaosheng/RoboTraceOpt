import csv
import json
import tempfile
import unittest
from pathlib import Path

from reporting.experiment_report import (
    build_experiment_report,
    render_markdown,
    write_report_outputs,
)


class ExperimentReportTest(unittest.TestCase):
    def test_discovers_failed_runs_and_projects_only_recorded_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "evidence"
            source.mkdir()
            (source / "control.json").write_text(
                json.dumps(
                    {
                        "schema_version": "trial/v1",
                        "status": "completed",
                        "latency_ns": {"p95": 7000, "p99": 9000},
                        "sample_count": 30,
                        "label": "control",
                    }
                ),
                encoding="utf-8",
            )
            (source / "injected.json").write_text(
                json.dumps(
                    {
                        "schema_version": "trial/v1",
                        "status": "failed",
                        "failure_count": 1,
                        "reason": "capture stopped",
                    }
                ),
                encoding="utf-8",
            )
            (source / "broken.json").write_text("{", encoding="utf-8")

            report = build_experiment_report(source)
            markdown = render_markdown(report)

        self.assertEqual(report["artifact_count"], 3)
        self.assertEqual(report["status_counts"]["failed"], 1)
        self.assertEqual(report["status_counts"]["invalid_json"], 1)
        metrics = {
            (row["artifact"], row["metric"]): row["value"] for row in report["metrics"]
        }
        self.assertEqual(metrics[("control.json", "latency_ns.p95")], 7000)
        self.assertEqual(metrics[("control.json", "sample_count")], 30)
        self.assertNotIn(("control.json", "label"), metrics)
        self.assertIn("failed", markdown)
        self.assertIn("unavailable", markdown)

    def test_writes_sorted_json_markdown_and_csv_without_overwriting_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "evidence"
            output = Path(temporary_directory) / "report"
            source.mkdir()
            (source / "summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "summary/v1",
                        "status": "completed",
                        "terminal_coverage": 0.95,
                    }
                ),
                encoding="utf-8",
            )
            report = build_experiment_report(source)

            paths = write_report_outputs(report, output)
            with paths["csv"].open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["metric"], "terminal_coverage")
            self.assertTrue(paths["json"].is_file())
            self.assertTrue(paths["markdown"].is_file())
            with self.assertRaisesRegex(ValueError, "already exists"):
                write_report_outputs(report, output)

    def test_rejects_symlinked_evidence_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "evidence"
            source.mkdir()
            target = source / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = source / "link.json"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation is unavailable")

            with self.assertRaisesRegex(ValueError, "symlink"):
                build_experiment_report(source)


if __name__ == "__main__":
    unittest.main()
