import inspect
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from experiments.fault_injection import scheduling_pressure
from experiments.fault_injection.registry import load_fault_catalog
from experiments.fault_injection.scheduling_pressure import (
    build_stress_command,
    process_tree_pids,
    select_target_cpu,
    snapshot_scheduler_processes,
    stop_process,
)
from scripts import run_fault_condition


class SchedulingPressureTest(unittest.TestCase):
    def test_selects_the_highest_allowed_cpu(self) -> None:
        self.assertEqual(select_target_cpu({2, 5, 3}), 5)
        with self.assertRaisesRegex(ValueError, "allowed CPU"):
            select_target_cpu(set())

    def test_builds_the_frozen_same_cpu_stress_command(self) -> None:
        command = build_stress_command(
            load_fault_catalog()["F3"],
            target_cpu=31,
            duration_seconds=8,
        )

        self.assertEqual(command[:4], ["taskset", "--cpu-list", "31", "stress-ng"])
        self.assertIn("--cpu", command)
        self.assertIn("--cpu-load", command)
        self.assertIn("--cpu-method", command)
        self.assertIn("matrixprod", command)
        self.assertIn("90", command)
        self.assertIn("13s", command)

    def test_snapshots_exact_affinity_and_sched_other(self) -> None:
        target_cpu = max(os.sched_getaffinity(0))
        process = subprocess.Popen(["sleep", "30"])
        try:
            os.sched_setaffinity(process.pid, {target_cpu})
            snapshot = snapshot_scheduler_processes(
                {"fixture": process.pid}, target_cpu
            )

            self.assertEqual(snapshot["fixture"]["allowed_cpus"], [target_cpu])
            self.assertEqual(snapshot["fixture"]["policy"], "SCHED_OTHER")
            self.assertEqual(snapshot["fixture"]["priority"], 0)
        finally:
            process.kill()
            process.wait()

    def test_discovers_a_live_child_process(self) -> None:
        process = subprocess.Popen(
            [
                "python3",
                "-c",
                "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)",
            ]
        )
        descendants: set[int] = set()
        try:
            for _ in range(20):
                descendants = process_tree_pids(process.pid)
                if len(descendants) >= 2:
                    break
                time.sleep(0.05)
            self.assertIn(process.pid, descendants)
            self.assertGreaterEqual(len(descendants), 2)
        finally:
            for pid in sorted(descendants - {process.pid}, reverse=True):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.kill()
            process.wait()

    def test_stops_graceful_and_signal_ignoring_processes(self) -> None:
        graceful = subprocess.Popen(["sleep", "30"])
        self.assertEqual(stop_process(graceful, 1.0), "graceful_sigint")

        stubborn = subprocess.Popen(
            [
                "python3",
                "-c",
                "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(30)",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.assertIsNotNone(stubborn.stdout)
        self.assertEqual(stubborn.stdout.readline().strip(), "ready")
        stubborn.stdout.close()
        self.assertEqual(stop_process(stubborn, 0.1), "forced_kill")

    def test_captures_an_auditable_injected_scheduler_manifest(self) -> None:
        self.assertTrue(hasattr(scheduling_pressure, "capture_scheduler_manifest"))
        target_cpu = max(os.sched_getaffinity(0))
        ros_process = subprocess.Popen(["sleep", "30"])
        stress_process = subprocess.Popen(["sleep", "30"])
        try:
            os.sched_setaffinity(ros_process.pid, {target_cpu})
            os.sched_setaffinity(stress_process.pid, {target_cpu})
            manifest = scheduling_pressure.capture_scheduler_manifest(
                process_manifest={
                    "schema_version": "process-manifest/v2",
                    "host_id": "host-a",
                    "git_commit": "a" * 40,
                    "ebpf_identity_status": "not_comparable",
                    "processes": [{"node": "planner", "pid": ros_process.pid}],
                },
                condition_variant="injected",
                target_cpu=target_cpu,
                ros_command=["taskset", "--cpu-list", str(target_cpu), "ros2"],
                stress_process_pid=stress_process.pid,
                stress_command=["taskset", "--cpu-list", str(target_cpu), "stress-ng"],
                stress_version="stress-ng fixture",
            )

            self.assertEqual(manifest["schema_version"], "f3-scheduler-manifest/v1")
            self.assertEqual(manifest["target_cpu"], target_cpu)
            self.assertEqual(manifest["ros_processes"]["planner"]["allowed_cpus"], [target_cpu])
            self.assertTrue(manifest["stress"]["enabled"])
            self.assertIn(stress_process.pid, manifest["stress"]["pids"])
            self.assertEqual(manifest["ebpf_identity_status"], "not_comparable")
        finally:
            ros_process.kill()
            stress_process.kill()
            ros_process.wait()
            stress_process.wait()

    def test_assembles_manifest_from_snapshots_taken_while_processes_were_live(self) -> None:
        self.assertIn(
            "ros_process_snapshots",
            inspect.signature(scheduling_pressure.capture_scheduler_manifest).parameters,
        )
        target_cpu = max(os.sched_getaffinity(0))
        ros_process = subprocess.Popen(["sleep", "30"])
        stress_process = subprocess.Popen(["sleep", "30"])
        os.sched_setaffinity(ros_process.pid, {target_cpu})
        os.sched_setaffinity(stress_process.pid, {target_cpu})
        ros_snapshots = snapshot_scheduler_processes(
            {"planner": ros_process.pid}, target_cpu
        )
        stress_snapshots = snapshot_scheduler_processes(
            {f"stress_{stress_process.pid}": stress_process.pid}, target_cpu
        )
        ros_process.kill()
        stress_process.kill()
        ros_process.wait()
        stress_process.wait()

        manifest = scheduling_pressure.capture_scheduler_manifest(
            process_manifest={
                "schema_version": "process-manifest/v2",
                "host_id": "host-a",
                "git_commit": "a" * 40,
                "ebpf_identity_status": "not_comparable",
                "processes": [{"node": "planner", "pid": ros_process.pid}],
            },
            condition_variant="injected",
            target_cpu=target_cpu,
            ros_command=["ros2"],
            stress_process_pid=stress_process.pid,
            stress_command=["stress-ng"],
            stress_version="stress-ng fixture",
            ros_process_snapshots=ros_snapshots,
            stress_process_pids=[stress_process.pid],
            stress_process_snapshots=stress_snapshots,
        )

        self.assertEqual(manifest["ros_processes"], ros_snapshots)
        self.assertEqual(manifest["stress"]["processes"], stress_snapshots)

    def test_freezes_runtime_processes_only_after_all_nodes_are_visible(self) -> None:
        target_cpu = max(os.sched_getaffinity(0))
        first_process = subprocess.Popen(["sleep", "30"])
        second_process = subprocess.Popen(["sleep", "30"])
        os.sched_setaffinity(first_process.pid, {target_cpu})
        os.sched_setaffinity(second_process.pid, {target_cpu})
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                events_path = Path(temporary_directory) / "runtime_events.jsonl"
                events_path.write_text(
                    json.dumps({"source_node": "camera", "pid": first_process.pid})
                    + "\n",
                    encoding="utf-8",
                )
                self.assertIsNone(
                    run_fault_condition.try_snapshot_runtime_processes(
                        events_path, minimum_processes=2, target_cpu=target_cpu
                    )
                )

                with events_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {"source_node": "planner", "pid": second_process.pid}
                        )
                        + "\n"
                    )
                snapshots = run_fault_condition.try_snapshot_runtime_processes(
                    events_path, minimum_processes=2, target_cpu=target_cpu
                )

                self.assertEqual(set(snapshots), {"camera", "planner"})
        finally:
            first_process.kill()
            second_process.kill()
            first_process.wait()
            second_process.wait()

    def test_runtime_snapshot_rejects_an_incomplete_json_line_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            events_path = Path(temporary_directory) / "runtime_events.jsonl"
            events_path.write_text(
                '{"source_node":"camera","pid":', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "invalid RuntimeEvent identity"):
                run_fault_condition.try_snapshot_runtime_processes(
                    events_path,
                    minimum_processes=1,
                    target_cpu=max(os.sched_getaffinity(0)),
                )

    def test_starts_managed_process_in_an_isolated_session(self) -> None:
        process = scheduling_pressure.start_isolated_process(
            ["sleep", "30"], cwd=Path.cwd(), output=subprocess.DEVNULL
        )
        try:
            self.assertNotEqual(os.getsid(process.pid), os.getsid(0))
            self.assertEqual(os.getsid(process.pid), process.pid)
        finally:
            process.kill()
            process.wait()


if __name__ == "__main__":
    unittest.main()
