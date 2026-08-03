#!/usr/bin/env python3
"""Build sanitized, explicitly limited evidence packages from existing runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import zipfile
from pathlib import Path
from typing import Any, Iterable


OVERHEAD_CONDITIONS = {
    "overhead_disabled": ("nominal_5hz", "disabled"),
    "overhead_buffered": ("nominal_5hz", "buffered"),
    "overhead_flush": ("nominal_5hz", "flush"),
    "overhead_stress_disabled": ("stress_20hz", "disabled"),
    "overhead_stress_buffered": ("stress_20hz", "buffered"),
    "overhead_stress_flush": ("stress_20hz", "flush"),
}

COLORS = {"disabled": "#666666", "buffered": "#0072B2", "flush": "#D55E00"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overhead-root", type=Path, required=True)
    parser.add_argument("--can-root", type=Path, required=True)
    parser.add_argument("--assessment-root", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def median_ci(values: Iterable[float], seed: int, iterations: int = 20000) -> dict[str, float]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return {"median": math.nan, "ci95_low": math.nan, "ci95_high": math.nan}
    rng = random.Random(seed)
    boot = sorted(statistics.median(rng.choices(clean, k=len(clean))) for _ in range(iterations))
    low = boot[int(0.025 * (iterations - 1))]
    high = boot[int(0.975 * (iterations - 1))]
    return {"median": statistics.median(clean), "ci95_low": low, "ci95_high": high}


def sanitize_text(value: str, roots: Iterable[Path]) -> str:
    result = value
    for root in sorted((str(path) for path in roots), key=len, reverse=True):
        for variant in {root, root.replace("\\", "/"), root.replace("/", "\\")}:
            result = result.replace(variant, "<CAPTURE_ROOT>")
    result = re.sub(r"/home/[^/]+/(?:thesis_can/)?data/reports/[^/]+", "<CAPTURE_ROOT>", result)
    result = re.sub(r"(?m)^\s*(Machine ID|Boot ID):.*$", r"\1: <REDACTED>", result)
    result = re.sub(r"(?m)^\s*Static hostname:.*$", " Static hostname: <REDACTED>", result)
    result = re.sub(r"(?m)^\s*Serial\s*:.*$", "\tSerial           : <REDACTED>", result)
    return result


def sanitize_json(value: Any, roots: Iterable[Path]) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_json(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item, roots) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, roots)
    return value


def reset_output(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def svg_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_overhead_figure(rows: list[dict[str, Any]], output: Path) -> None:
    width, height = 1120, 570
    panels = [
        ("Mean process CPU (%)", "mean_cpu_percent", 0, 0),
        ("Peak process RSS (MiB)", "peak_rss_mb", 1, 0),
        ("Output rate (Hz)", "can_send_rate_hz", 0, 1),
    ]
    workloads = ["nominal_5hz", "stress_20hz"]
    modes = ["disabled", "buffered", "flush"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#202124;letter-spacing:0}.title{font-size:21px;font-weight:700}.label{font-size:13px}.small{font-size:11px;fill:#555}.axis{stroke:#777;stroke-width:1}.grid{stroke:#e3e6e8;stroke-width:1}.median{stroke:#111;stroke-width:3}</style>',
        '<text x="50" y="34" class="title">WSL2 RuntimeEvent proxy overhead (10 runs per condition)</text>',
    ]
    panel_positions = [(50, 75, 500, 200), (600, 75, 470, 200), (50, 330, 500, 190)]
    for panel_index, (title, metric, _, _) in enumerate(panels):
        x, y, w, h = panel_positions[panel_index]
        values = [float(row[metric]) for row in rows]
        minimum, maximum = min(values), max(values)
        pad = max((maximum - minimum) * 0.12, 0.1)
        lower, upper = max(0.0, minimum - pad), maximum + pad
        svg.append(f'<text x="{x}" y="{y - 12}" class="label" font-weight="700">{svg_escape(title)}</text>')
        for tick in range(5):
            value = lower + (upper - lower) * tick / 4
            yy = y + h - (value - lower) / (upper - lower) * h
            svg.append(f'<line x1="{x}" y1="{yy:.1f}" x2="{x+w}" y2="{yy:.1f}" class="grid"/>')
            svg.append(f'<text x="{x-8}" y="{yy+4:.1f}" text-anchor="end" class="small">{value:.1f}</text>')
        svg.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+h}" class="axis"/>')
        svg.append(f'<line x1="{x}" y1="{y+h}" x2="{x+w}" y2="{y+h}" class="axis"/>')
        group_width = w / len(workloads)
        for wi, workload in enumerate(workloads):
            center = x + group_width * (wi + 0.5)
            svg.append(f'<text x="{center:.1f}" y="{y+h+34}" text-anchor="middle" class="label">{workload.replace("_", " ")}</text>')
            for mi, mode in enumerate(modes):
                xpos = center + (mi - 1) * 62
                points = [float(row[metric]) for row in rows if row["workload"] == workload and row["mode"] == mode]
                for pi, value in enumerate(points):
                    jitter = ((pi * 17) % 19 - 9) * 1.2
                    yy = y + h - (value - lower) / (upper - lower) * h
                    svg.append(f'<circle cx="{xpos+jitter:.1f}" cy="{yy:.1f}" r="3.5" fill="{COLORS[mode]}" fill-opacity="0.68"/>')
                med = statistics.median(points)
                yy = y + h - (med - lower) / (upper - lower) * h
                svg.append(f'<line x1="{xpos-20}" y1="{yy:.1f}" x2="{xpos+20}" y2="{yy:.1f}" class="median"/>')
                if panel_index == 2:
                    svg.append(f'<text x="{xpos:.1f}" y="{y+h+18}" text-anchor="middle" class="small">{mode}</text>')
    legend_x, legend_y = 650, 360
    svg.append('<text x="650" y="338" class="label" font-weight="700">RuntimeEvent mode</text>')
    for index, mode in enumerate(modes):
        yy = legend_y + index * 34
        svg.append(f'<circle cx="{legend_x}" cy="{yy}" r="6" fill="{COLORS[mode]}"/>')
        svg.append(f'<text x="{legend_x+16}" y="{yy+5}" class="label">{mode}</text>')
    svg.append('<text x="650" y="485" class="small">Points are independent runs; black bars are run medians.</text>')
    svg.append('<text x="650" y="504" class="small">Block-ordered WSL2 capture; descriptive only, not native four-mode evidence.</text>')
    svg.append('</svg>')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")


def build_can_figure(latency_rows: list[dict[str, str]], output: Path) -> None:
    width, height = 980, 430
    values = [float(row["can_send_to_ack_ms"]) for row in latency_rows]
    med = statistics.median(values)
    p95 = statistics.quantiles(values, n=100, method="inclusive")[94]
    lower = max(0.0, min(values) - 0.15)
    upper = max(values) + 0.15
    x0, y0, w, h = 75, 70, 835, 260
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#202124;letter-spacing:0}.title{font-size:21px;font-weight:700}.label{font-size:13px}.small{font-size:11px;fill:#555}.axis{stroke:#777}.grid{stroke:#e3e6e8}.med{stroke:#0072B2;stroke-width:2}.p95{stroke:#D55E00;stroke-width:2;stroke-dasharray:6 4}</style>',
        '<text x="55" y="34" class="title">X5 dual-CANable normal-ACK smoke</text>',
    ]
    for tick in range(6):
        value = lower + (upper - lower) * tick / 5
        yy = y0 + h - (value - lower) / (upper - lower) * h
        svg.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+w}" y2="{yy:.1f}" class="grid"/>')
        svg.append(f'<text x="{x0-10}" y="{yy+4:.1f}" text-anchor="end" class="small">{value:.2f}</text>')
    for index, value in enumerate(values, start=1):
        xx = x0 + (index - 1) / (len(values) - 1) * w
        yy = y0 + h - (value - lower) / (upper - lower) * h
        svg.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="4" fill="#009E73"/>')
    for value, css, label in [(med, "med", f"median {med:.3f} ms"), (p95, "p95", f"empirical p95 {p95:.3f} ms")]:
        yy = y0 + h - (value - lower) / (upper - lower) * h
        svg.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0+w}" y2="{yy:.1f}" class="{css}"/>')
        svg.append(f'<text x="{x0+w-4}" y="{yy-6:.1f}" text-anchor="end" class="small">{label}</text>')
    svg.extend([
        f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0+h}" class="axis"/>',
        f'<line x1="{x0}" y1="{y0+h}" x2="{x0+w}" y2="{y0+h}" class="axis"/>',
        f'<text x="{x0+w/2}" y="{y0+h+38}" text-anchor="middle" class="label">Trace sequence (n={len(values)})</text>',
        f'<text x="18" y="{y0+h/2}" transform="rotate(-90 18 {y0+h/2})" text-anchor="middle" class="label">CAN send-to-ACK latency (ms)</text>',
        '<text x="55" y="404" class="small">Single 40 s normal-ACK session; no drop/timeout comparator and no ECU HIL claim.</text>',
        '</svg>',
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")


def finish_package(package: Path, archive: Path) -> str:
    files = sorted(path for path in package.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    sums = "".join(f"{sha256(path)}  {path.relative_to(package).as_posix()}\n" for path in files)
    (package / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(item for item in package.rglob("*") if item.is_file()):
            bundle.write(path, arcname=f"{package.name}/{path.relative_to(package).as_posix()}")
    digest = sha256(archive)
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return digest


def build_overhead_package(source: Path, assessment: Path) -> tuple[Path, str]:
    output = assessment / "ROS2Probe-wsl-runtimeevent-overhead-20260712-public"
    reset_output(output)
    rows: list[dict[str, Any]] = []
    source_hashes: list[dict[str, Any]] = []
    commits: set[str] = set()
    for condition, (workload, mode) in OVERHEAD_CONDITIONS.items():
        run_dirs = sorted((source / condition).glob("run_*"))
        if len(run_dirs) != 10:
            raise ValueError(f"expected 10 runs for {condition}, found {len(run_dirs)}")
        for run_dir in run_dirs:
            manifest_path = run_dir / "manifest.json"
            manifest = load_json(manifest_path)
            environment = manifest["environment"]
            resource = manifest["resource_summary"]
            commits.add(environment["git_commit"])
            row: dict[str, Any] = {
                "workload": workload,
                "mode": mode,
                "run_id": manifest["run_id"],
                "duration_s": manifest["duration_s"],
                "mean_cpu_percent": resource["mean_cpu_percent"],
                "peak_rss_mb": resource["peak_rss_mb"],
                "can_send_count": resource["can_send_count"],
                "can_send_rate_hz": resource["can_send_rate_hz"],
                "trace_count": "",
                "valid_trace_rate": "",
                "total_latency_p50_ms": "",
                "total_latency_p95_ms": "",
                "total_latency_p99_ms": "",
                "git_dirty": str(environment["git_dirty"]).lower(),
            }
            logical_files = [manifest_path, run_dir / "resource_samples.json"]
            if mode != "disabled":
                latency_path = run_dir / "latency" / "latency_summary.json"
                integrity_path = run_dir / "integrity" / "trace_integrity_summary.json"
                correlation_path = run_dir / "correlation" / "correlation_summary.json"
                latency = load_json(latency_path)
                integrity = load_json(integrity_path)
                total = latency["latency_metrics"]["total_latency_ms"]
                row.update({
                    "trace_count": latency["trace_count"],
                    "valid_trace_rate": integrity["valid_trace_rate"],
                    "total_latency_p50_ms": total["p50_ms"],
                    "total_latency_p95_ms": total["p95_ms"],
                    "total_latency_p99_ms": total["p99_ms"],
                })
                logical_files.extend([latency_path, integrity_path, correlation_path])
            rows.append(row)
            for artifact in logical_files:
                source_hashes.append({
                    "source_path": f"{condition}/{run_dir.name}/{artifact.relative_to(run_dir).as_posix()}",
                    "sha256": sha256(artifact),
                    "bytes": artifact.stat().st_size,
                })
    if len(commits) != 1:
        raise ValueError(f"expected one source commit, got {sorted(commits)}")
    fields = list(rows[0])
    write_csv(output / "results" / "run_metrics.csv", rows, fields)
    summary_rows: list[dict[str, Any]] = []
    metrics = ["mean_cpu_percent", "peak_rss_mb", "can_send_rate_hz"]
    for workload in ["nominal_5hz", "stress_20hz"]:
        baseline_rows = [row for row in rows if row["workload"] == workload and row["mode"] == "disabled"]
        baseline = {metric: statistics.median(float(row[metric]) for row in baseline_rows) for metric in metrics}
        for mode in ["disabled", "buffered", "flush"]:
            subset = [row for row in rows if row["workload"] == workload and row["mode"] == mode]
            for metric_index, metric in enumerate(metrics):
                stats = median_ci((float(row[metric]) for row in subset), 20260712 + metric_index * 100 + len(summary_rows))
                summary_rows.append({
                    "workload": workload,
                    "mode": mode,
                    "metric": metric,
                    "n_runs": len(subset),
                    **{key: f"{value:.6f}" for key, value in stats.items()},
                    "relative_to_disabled_percent": f"{(stats['median'] / baseline[metric] - 1) * 100:.6f}",
                })
            if mode != "disabled":
                for metric_index, metric in enumerate(["total_latency_p50_ms", "total_latency_p95_ms", "total_latency_p99_ms", "valid_trace_rate"]):
                    stats = median_ci((float(row[metric]) for row in subset), 20261712 + metric_index * 100 + len(summary_rows))
                    summary_rows.append({
                        "workload": workload,
                        "mode": mode,
                        "metric": metric,
                        "n_runs": len(subset),
                        **{key: f"{value:.6f}" for key, value in stats.items()},
                        "relative_to_disabled_percent": "",
                    })
    write_csv(output / "results" / "summary.csv", summary_rows, list(summary_rows[0]))
    write_json(output / "results" / "source_artifact_hashes.json", sorted(source_hashes, key=lambda item: item["source_path"]))
    protocol = {
        "schema_version": "limited-evidence-protocol/v1",
        "dataset": "ros2probe-wsl2-runtimeevent-overhead-20260712",
        "qualification": "limited-paper-support-only",
        "formal_experiment_allowed": False,
        "source_git_commit": next(iter(commits)),
        "source_git_dirty": True,
        "environment": "Ubuntu 22.04 / ROS 2 Humble on WSL2",
        "design": {"workloads": ["5 Hz nominal", "20 Hz stress"], "modes": ["disabled", "buffered", "flush"], "runs_per_condition": 10, "duration_s": 60},
        "valid_claim": "WSL2 proxy comparison of RuntimeEvent disabled, buffered, and per-event flush modes.",
        "invalid_claims": ["native Linux overhead", "ros2_tracing or fused overhead", "causal effect from randomized ordering", "latency comparison against disabled mode"],
        "limitations": ["WSL2 host", "dirty source tree", "block-ordered capture", "disabled mode has no internal event latency or completeness outputs"],
    }
    write_json(output / "protocol_manifest.public.json", protocol)
    build_overhead_figure(rows, output / "figures" / "figure_wsl_runtimeevent_proxy_overhead.svg")
    readme = """# WSL2 RuntimeEvent Proxy Overhead Evidence\n\nThis package contains a sanitized, run-level recomputation of an existing ROS2Probe campaign. It is **limited paper-supporting evidence**, not the missing native four-mode RoboTraceOpt overhead experiment.\n\n## What it supports\n\n- Ubuntu 22.04 / ROS 2 Humble on WSL2.\n- RuntimeEvent disabled, buffered, and per-event flush modes.\n- Nominal 5 Hz and stress 20 Hz workloads.\n- Ten 60-second runs per condition.\n- Process CPU, peak RSS, output rate, and enabled-mode internal latency/completeness summaries.\n\n## What it does not support\n\n- Native Linux overhead.\n- RuntimeEvent-only vs ros2_tracing vs full fused comparison.\n- A latency delta against disabled mode, which has no RuntimeEvent latency output.\n- A randomized causal estimate: conditions were captured in blocks and the source tree was dirty.\n\n`results/run_metrics.csv` is the source for the figure and summary. Bootstrap intervals resample whole runs. Raw event logs are intentionally excluded; `results/source_artifact_hashes.json` binds the recomputation to the local source artifacts without exposing local paths.\n"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    archive = assessment / f"{output.name}.zip"
    return output, finish_package(output, archive)


def sanitize_runtime_events(source: Path, target: Path, roots: list[Path]) -> int:
    count = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8") as input_handle, target.open("w", encoding="utf-8", newline="\n") as output_handle:
        for line in input_handle:
            if not line.strip():
                continue
            event = load_json_line(line)
            if "extra_json" in event and isinstance(event["extra_json"], str):
                try:
                    nested = json.loads(event["extra_json"])
                    event["extra_json"] = json.dumps(sanitize_json(nested, roots), separators=(",", ":"), sort_keys=True)
                except json.JSONDecodeError:
                    event["extra_json"] = sanitize_text(event["extra_json"], roots)
            event = sanitize_json(event, roots)
            output_handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            count += 1
    return count


def load_json_line(line: str) -> dict[str, Any]:
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("JSONL record must be an object")
    return value


def build_can_package(source: Path, assessment: Path) -> tuple[Path, str]:
    output = assessment / "RoboTraceOpt-x5-physical-can-smoke-20260727-public"
    reset_output(output)
    roots = [source, source.parent]
    summary_names = ["camera_capture_summary.json", "hardware_can_ack_summary.json", "hardware_can_write_summary.json", "latency_summary.json"]
    source_hashes: list[dict[str, Any]] = []
    for name in summary_names:
        artifact = source / name
        write_json(output / "results" / name, sanitize_json(load_json(artifact), roots))
        source_hashes.append({"source_path": name, "sha256": sha256(artifact), "bytes": artifact.stat().st_size})
    copy_names = ["hardware_can_ack_report.csv", "hardware_can_write_report.csv", "latency_report.csv", "candump_can1.log", "candump_can2.log", "ack_responder.jsonl", "can_interface_details.txt", "slcan_setup.txt", "usb_devices.txt"]
    for name in copy_names:
        artifact = source / name
        destination_group = "results" if artifact.suffix == ".csv" else "evidence"
        target = output / destination_group / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = sanitize_text(artifact.read_text(encoding="utf-8"), roots)
        target.write_text(text, encoding="utf-8")
        source_hashes.append({"source_path": name, "sha256": sha256(artifact), "bytes": artifact.stat().st_size})
    environment = sanitize_text((source / "environment.txt").read_text(encoding="utf-8"), roots)
    (output / "evidence" / "environment.public.txt").write_text(environment, encoding="utf-8")
    notes = sanitize_text((source / "hardware_can_experiment_notes.md").read_text(encoding="utf-8"), roots)
    (output / "evidence" / "hardware_can_experiment_notes.public.md").write_text(notes, encoding="utf-8")
    source_hashes.extend([
        {"source_path": "environment.txt", "sha256": sha256(source / "environment.txt"), "bytes": (source / "environment.txt").stat().st_size},
        {"source_path": "hardware_can_experiment_notes.md", "sha256": sha256(source / "hardware_can_experiment_notes.md"), "bytes": (source / "hardware_can_experiment_notes.md").stat().st_size},
    ])
    event_count = sanitize_runtime_events(source / "runtime_events.jsonl", output / "evidence" / "runtime_events.public.jsonl", roots)
    source_hashes.append({"source_path": "runtime_events.jsonl", "sha256": sha256(source / "runtime_events.jsonl"), "bytes": (source / "runtime_events.jsonl").stat().st_size})
    frame_rows = [{"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size} for path in sorted((source / "camera_frames").glob("*.jpg"))]
    write_csv(output / "evidence" / "camera_frame_hashes.csv", frame_rows, ["file", "sha256", "bytes"])
    ack = load_json(source / "hardware_can_ack_summary.json")
    writes = load_json(source / "hardware_can_write_summary.json")
    camera = load_json(source / "camera_capture_summary.json")
    if not (ack["runtime_ack_count"] == ack["matched_runtime_ack_count"] == 34 and writes["matched_send_count"] == 34 and len(frame_rows) == 34):
        raise ValueError("X5 smoke expected 34 matched ACKs, sends, and retained frames")
    with (source / "latency_report.csv").open("r", encoding="utf-8", newline="") as handle:
        latency_rows = list(csv.DictReader(handle))
    build_can_figure(latency_rows, output / "figures" / "figure_x5_can_ack_smoke.svg")
    protocol = {
        "schema_version": "limited-evidence-protocol/v1",
        "dataset": "x5-dual-canable-camera-normal-ack-smoke-20260727-100139",
        "qualification": "limited-hardware-smoke-only",
        "formal_experiment_allowed": False,
        "environment": "arm64 Ubuntu 22.04.5, Linux 6.1.83-rt28 PREEMPT_RT",
        "hardware": {"transport": "two CANable/SocketCAN interfaces", "bitrate": 500000, "camera": "USB V4L2 1280x720"},
        "session": {"duration_s": 40, "traces": 34, "runtime_events": event_count, "camera_frames_retained": camera["retained_frame_count"]},
        "observed": {"matched_runtime_acks": ack["matched_runtime_ack_count"], "payload_match_rate": writes["payload_match_rate"], "camera_event_frame_count": camera["event_frame_count"]},
        "valid_claim": "Physical dual-interface SocketCAN normal-ACK path smoke on an X5-class arm64 system.",
        "invalid_claims": ["ECU HIL", "normal-vs-drop fault comparison", "formal physical CAN experiment", "proof of current fail-closed AI runtime"],
        "limitations": ["single session", "normal ACK path only", "planner backend was mock", "no timeout/drop comparator", "camera frames excluded from public archive; hashes retained"],
    }
    write_json(output / "protocol_manifest.public.json", protocol)
    write_json(output / "results" / "source_artifact_hashes.json", sorted(source_hashes, key=lambda item: item["source_path"]))
    readme = """# X5 Physical CAN Normal-ACK Smoke Evidence\n\nThis sanitized package preserves the strongest existing X5 dual-CANable capture. It is **hardware smoke evidence**, not ECU HIL and not a formal fault-control experiment.\n\n## Observed\n\n- arm64 Ubuntu 22.04.5 with a PREEMPT_RT kernel.\n- Two physical CANable/SocketCAN interfaces at 500 kbit/s.\n- One 40-second camera-to-action-to-CAN session.\n- 34 runtime sends, 34 matched runtime ACKs, and 100% payload matching.\n- 34 retained 1280x720 USB-camera frames; public archive carries hashes rather than scene images.\n\n## Boundaries\n\n- Only the normal ACK path was captured; there is no paired drop/timeout condition.\n- The planner backend was mock. The physical claim applies to camera capture and CAN transport, not model inference or the current fail-closed runtime.\n- This is not an ECU or vehicle HIL setup.\n\nLocal paths, machine identifiers, boot identifiers, and camera serial values are removed. Source hashes bind the package to the preserved local capture.\n"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    archive = assessment / f"{output.name}.zip"
    return output, finish_package(output, archive)


def main() -> int:
    args = parse_args()
    args.assessment_root.mkdir(parents=True, exist_ok=True)
    overhead_dir, overhead_hash = build_overhead_package(args.overhead_root, args.assessment_root)
    can_dir, can_hash = build_can_package(args.can_root, args.assessment_root)
    print(json.dumps({
        "overhead_package": str(overhead_dir),
        "overhead_zip_sha256": overhead_hash,
        "can_package": str(can_dir),
        "can_zip_sha256": can_hash,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
