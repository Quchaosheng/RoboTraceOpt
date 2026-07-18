import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from diagnosis.adapters.clock_calibration import (
    ClockCalibrationError,
    assess_clock_comparability,
    measure_local_monotonic_alignment,
)
from scripts.capture_process_manifest import (
    assess_ebpf_identity_status,
    capture_code_version,
    capture_process_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FUSION_FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "fusion"


class ClockCalibrationTest(unittest.TestCase):
    def test_cli_writes_local_alignment_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "clock.json"
            subprocess.run(
                [
                    "python3",
                    "-m",
                    "diagnosis.adapters.clock_calibration",
                    "--host-id",
                    "host-a",
                    "--sample-count",
                    "10",
                    "--tolerance-ns",
                    "1000000",
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=True,
            )

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["schema_version"], "clock-calibration/v1")
        self.assertEqual(report["source_host"], "host-a")
        self.assertEqual(report["status"], "comparable")

    def test_measures_bracketed_local_monotonic_alignment(self) -> None:
        reference_values = iter((1_000, 1_020, 2_000, 2_040))
        candidate_values = iter((1_011, 2_018))

        report = measure_local_monotonic_alignment(
            sample_count=2,
            reference_reader=lambda: next(reference_values),
            candidate_reader=lambda: next(candidate_values),
            host_id="host-a",
            tolerance_ns=100,
        )

        self.assertEqual(report.sample_count, 2)
        self.assertEqual(report.estimated_offset_ns, 0)
        self.assertEqual(report.max_error_ns, 22)
        self.assertEqual(report.status, "comparable")
        self.assertEqual(report.method, "bracketed_clock_gettime")

    def test_rejects_unknown_clock_domain(self) -> None:
        with self.assertRaises(ClockCalibrationError) as context:
            assess_clock_comparability(
                source_host="pc",
                target_host="rk3568",
                source_clock_id="monotonic",
                target_clock_id="mystery",
                offset_samples_ns=[10],
                uncertainty_samples_ns=[2],
                tolerance_ns=100,
                method="chrony",
            )

        self.assertEqual(context.exception.reason_code, "unknown_clock")

    def test_marks_cross_host_offset_over_tolerance_not_comparable(self) -> None:
        report = assess_clock_comparability(
            source_host="pc",
            target_host="rk3568",
            source_clock_id="monotonic",
            target_clock_id="monotonic",
            offset_samples_ns=[900, 1_100, 1_000],
            uncertainty_samples_ns=[50, 50, 50],
            tolerance_ns=500,
            method="chrony",
        )

        self.assertEqual(report.estimated_offset_ns, 1_000)
        self.assertEqual(report.max_error_ns, 150)
        self.assertEqual(report.status, "not_comparable")
        self.assertEqual(report.reason_code, "clock_error_over_tolerance")


class ProcessManifestTest(unittest.TestCase):
    def test_wsl_single_level_pid_namespace_is_not_ebpf_comparable(self) -> None:
        status, reason = assess_ebpf_identity_status(
            osrelease="6.18.0-microsoft-standard-WSL2",
            namespace_depths=[1, 1, 1],
        )

        self.assertEqual(status, "not_comparable")
        self.assertEqual(reason, "wsl_initial_pid_namespace_unavailable")

    def test_cli_rejects_runtime_events_below_minimum_process_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            runtime_events = root / "runtime_events.jsonl"
            output = root / "process_manifest.json"
            runtime_events.write_text(
                json.dumps({"source_node": "/only_one", "pid": os.getpid()}) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    "scripts/capture_process_manifest.py",
                    "--runtime-events",
                    str(runtime_events),
                    "--minimum-processes",
                    "2",
                    "--repo-root",
                    str(REPOSITORY_ROOT),
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected at least 2 process identities", result.stderr)
        self.assertFalse(output.exists())

    def test_code_version_ignores_windows_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(
                ["git", "-C", repo, "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo, "config", "user.name", "Test Runner"],
                check=True,
            )
            tracked = repo / "tracked.txt"
            tracked.write_bytes(b"first\nsecond\n")
            subprocess.run(["git", "-C", repo, "add", "tracked.txt"], check=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "-q", "-m", "fixture"],
                check=True,
            )
            tracked.write_bytes(b"first\r\nsecond\r\n")

            version = capture_code_version(repo)

        self.assertFalse(version["git_dirty"])

    def test_code_version_reports_dirty_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(
                ["git", "-C", repo, "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo, "config", "user.name", "Test Runner"],
                check=True,
            )
            tracked = repo / "tracked.txt"
            tracked.write_text("first\n", encoding="utf-8")
            subprocess.run(["git", "-C", repo, "add", "tracked.txt"], check=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "-q", "-m", "fixture"],
                check=True,
            )
            tracked.write_text("changed\n", encoding="utf-8")

            version = capture_code_version(repo)

        self.assertRegex(version["git_commit"], r"^[0-9a-f]{40}$")
        self.assertTrue(version["git_dirty"])

    def test_cli_derives_process_identity_from_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            runtime_events = root / "runtime_events.jsonl"
            output = root / "process_manifest.json"
            runtime_events.write_text(
                json.dumps(
                    {
                        "source_node": "/test_runner",
                        "pid": os.getpid(),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    "scripts/capture_process_manifest.py",
                    "--runtime-events",
                    str(runtime_events),
                    "--repo-root",
                    str(REPOSITORY_ROOT),
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=True,
            )

            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(manifest["processes"][0]["node"], "/test_runner")
        self.assertEqual(manifest["processes"][0]["pid"], os.getpid())

    def test_captures_threads_start_time_executable_and_git_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            proc_root = Path(temporary_directory)
            process_root = proc_root / "321"
            (process_root / "task" / "321").mkdir(parents=True)
            (process_root / "task" / "325").mkdir()
            (proc_root / "stat").write_text(
                "cpu 1 2 3 4\nbtime 1700000000\n", encoding="utf-8"
            )
            fields_after_name = ["S"] + ["0"] * 18 + ["250"] + ["0"] * 20
            (process_root / "stat").write_text(
                "321 (camera node) " + " ".join(fields_after_name) + "\n",
                encoding="utf-8",
            )
            (process_root / "cmdline").write_bytes(
                b"/opt/ros/camera_node\0--ros-args\0"
            )
            (process_root / "status").write_text(
                "Name:\tcamera node\nNSpid:\t9000\t321\n", encoding="utf-8"
            )
            (process_root / "task" / "321" / "status").write_text(
                "Name:\tcamera node\nNSpid:\t9000\t321\n", encoding="utf-8"
            )
            (process_root / "task" / "325" / "status").write_text(
                "Name:\tworker\nNSpid:\t9004\t325\n", encoding="utf-8"
            )

            manifest = capture_process_manifest(
                [("/camera", 321)],
                repo_root=REPOSITORY_ROOT,
                proc_root=proc_root,
                host_id="host-a",
                clock_ticks_per_second=100,
                captured_at_utc="2026-07-15T10:00:00Z",
            )

        self.assertEqual(manifest["schema_version"], "process-manifest/v2")
        self.assertEqual(manifest["host_id"], "host-a")
        self.assertEqual(manifest["ebpf_identity_status"], "comparable")
        self.assertRegex(manifest["git_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(manifest["captured_at_utc"], "2026-07-15T10:00:00Z")
        process = manifest["processes"][0]
        self.assertEqual(process["node"], "/camera")
        self.assertEqual(process["pid"], 321)
        self.assertEqual(process["kernel_pid"], 9000)
        self.assertEqual(process["tids"], [321, 325])
        self.assertEqual(
            process["threads"],
            [
                {"tid": 321, "kernel_tid": 9000},
                {"tid": 325, "kernel_tid": 9004},
            ],
        )
        self.assertEqual(process["executable"], "/opt/ros/camera_node")
        self.assertEqual(process["start_time_monotonic_ns"], 2_500_000_000)
        self.assertEqual(process["start_time_utc"], "2023-11-14T22:13:22.500000Z")

    def test_rejects_missing_process_instead_of_emitting_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            proc_root = Path(temporary_directory)
            (proc_root / "stat").write_text("btime 1700000000\n", encoding="utf-8")

            with self.assertRaises(ProcessLookupError):
                capture_process_manifest(
                    [("/missing", 999)],
                    repo_root=REPOSITORY_ROOT,
                    proc_root=proc_root,
                    host_id="host-a",
                )


class RealW1IdentityEvidenceTest(unittest.TestCase):
    def test_frozen_run_has_complete_clean_calibration_evidence(self) -> None:
        run = json.loads(
            (FUSION_FIXTURE_ROOT / "w1_run_manifest.json").read_text(encoding="utf-8")
        )
        clock_path = FUSION_FIXTURE_ROOT / "w1_clock_calibration.json"
        process_path = FUSION_FIXTURE_ROOT / "w1_process_manifest.json"
        clock = json.loads(clock_path.read_text(encoding="utf-8"))
        processes = json.loads(process_path.read_text(encoding="utf-8"))

        self.assertEqual(clock["status"], "comparable")
        self.assertLessEqual(
            abs(clock["estimated_offset_ns"]) + clock["max_error_ns"],
            clock["tolerance_ns"],
        )
        self.assertFalse(processes["git_dirty"])
        self.assertEqual(len(processes["processes"]), 4)
        self.assertEqual(processes["git_commit"], run["git_commit"])
        self.assertEqual(run["runtime_event_count"], 622)
        self.assertEqual(run["runtime_trace_count"], 30)
        self.assertEqual(run["ctf_event_count"], 147877)
        self.assertEqual(
            hashlib.sha256(clock_path.read_bytes()).hexdigest(),
            run["clock_calibration_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(process_path.read_bytes()).hexdigest(),
            run["process_manifest_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
