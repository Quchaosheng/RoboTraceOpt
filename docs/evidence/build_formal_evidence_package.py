#!/usr/bin/env python3
"""Build a small, sanitized evidence package from the frozen F3/F4 session."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any


JSON_SOURCES = {
    "metadata/session_summary.json": ("session", "summary.json"),
    "metadata/qualification.json": ("session", "qualification.json"),
    "metadata/session_manifest.json": ("session", "session_manifest.json"),
    "metadata/integrity.json": ("session", "integrity.json"),
    "metadata/environment_capabilities.json": ("environment", ""),
    "results/analysis_summary.json": ("analysis", "analysis_summary.json"),
    "results/paired_statistics.json": ("statistics", "paired_statistics.json"),
    "results/scheduler_analysis.json": ("scheduler", "scheduler_analysis.json"),
}

COPY_SOURCES = {
    "results/analysis_summary.md": ("analysis", "analysis_summary.md"),
    "results/metrics.csv": ("analysis", "metrics.csv"),
    "results/run_metrics.csv": ("statistics", "run_metrics.csv"),
    "results/scheduler_runs.csv": ("scheduler", "scheduler_runs.csv"),
    "figures/figure_f3_completeness.svg": ("figures", "figure_f3_completeness.svg"),
    "figures/figure_f4_latency.svg": ("figures", "figure_f4_latency.svg"),
}

README = """# RoboTraceOpt Native F3/F4 Formal Evidence V3

This package contains the compact, sanitized projection of the native Ubuntu
24.04 / ROS 2 Jazzy F3/F4 session executed on 2026-07-29. Raw CTF, ROS 2,
RuntimeEvent, and eBPF files are intentionally excluded.

## Provenance

- Dataset role: `test`
- Formal experiment allowed: `true`
- Executed cases: `40/40 successful`
- Paired repetitions: `10` per control/injected condition
- Session seed: `20260729`
- Experiment commit: `384b21556d12e572ef8e490c1ab7cfef0c328203`
- Session integrity: `complete`
- Host class: native Linux, not WSL or a VM

The fixed session seed generated a balanced run order. Repetitions are paired
by their explicit repetition index; they are not described as independently
seeded trials.

## Main Results

| Fault | Evidence result | Control | Injected | Paired result |
|---|---|---:|---:|---:|
| F3 scheduling pressure | Complete lifecycle recovery | 95.30% | 67.56% | median difference -0.437; 95% bootstrap CI [-0.458, -0.017] |
| F4 service blocking | Request-response median | 0.875 ms | 101.212 ms | median difference +100.337 ms; 95% bootstrap CI [100.320, 100.350] ms |

F4 supports formal application-level blocking-delay inference. It does not
claim syscall-level causal attribution.

F3 is retained as scheduling-pressure evidence. Its complete-sample latency
medians are affected by missing and selected traces, and the response is
heterogeneous across repetitions. The defensible result is the reduction in
complete lifecycle recovery, not a claim that pressure improves latency or a
claim of scheduler-level causal attribution.

## Package Layout

- `metadata/`: sanitized environment, qualification, session, and integrity
  records.
- `results/`: aggregate metrics, run-level paired statistics, and scheduler
  analysis.
- `figures/`: thesis-ready SVG projections.
- `PACKAGE_MANIFEST.json`: source and public SHA-256 values for every projected
  artifact.
- `SHA256SUMS.txt`: checksums for the complete public package.

The source hashes in `PACKAGE_MANIFEST.json` refer to the retained private
artifacts before sanitization. Public hashes refer to the files in this
package. Local paths, usernames, and host identifiers have been replaced.

## Evidence Boundary

This package establishes native F3/F4 execution and the reported paired
measurements. It does not by itself establish multi-class diagnosis accuracy,
abstention performance, optimization benefit, ECU HIL behavior, or actuator
safety.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--environment-report", type=Path, required=True)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    parser.add_argument("--statistics-dir", type=Path, required=True)
    parser.add_argument("--scheduler-dir", type=Path, required=True)
    parser.add_argument("--figures-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_string(value: str, roots: list[str]) -> str:
    sanitized = value
    for root in sorted(roots, key=len, reverse=True):
        variants = {root, root.replace("\\", "/"), root.replace("/", "\\")}
        for variant in variants:
            sanitized = sanitized.replace(variant, "<EXPERIMENT_ROOT>")
    sanitized = re.sub(r"/home/[^/]+/", "<LOCAL_HOME>/", sanitized)
    sanitized = re.sub(r"/root/", "<LOCAL_HOME>/", sanitized)
    sanitized = re.sub(
        r"[A-Za-z]:\\Users\\[^\\]+\\",
        lambda _match: "<LOCAL_HOME>\\",
        sanitized,
    )
    return sanitized


def sanitize_json(value: Any, roots: list[str], key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: sanitize_json(item, roots, name) for name, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item, roots, key) for item in value]
    if isinstance(value, str):
        if key in {"hostname", "host_id"}:
            return "native-x86-host"
        return sanitize_string(value, roots)
    return value


def resolve_source(kind: str, name: str, args: argparse.Namespace) -> Path:
    if kind == "session":
        return args.session_dir / name
    if kind == "environment":
        return args.environment_report
    return getattr(args, f"{kind}_dir") / name


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finish_package(output_dir: Path) -> str:
    (output_dir / "README.md").write_text(README, encoding="utf-8")
    files = sorted(
        path for path in output_dir.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    sums = "".join(
        f"{sha256(path)}  {path.relative_to(output_dir).as_posix()}\n"
        for path in files
    )
    (output_dir / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    archive = output_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
            bundle.write(
                path,
                arcname=f"{output_dir.name}/{path.relative_to(output_dir).as_posix()}",
            )
    digest = sha256(archive)
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
    )
    return digest


def main() -> int:
    args = parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"output directory must be empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    roots = [
        str(args.session_dir),
        str(args.session_dir.parent.parent.parent.parent),
        str(args.analysis_dir),
        str(args.statistics_dir),
        str(args.scheduler_dir),
        str(args.figures_dir),
    ]
    provenance: list[dict[str, Any]] = []

    for destination, (kind, name) in JSON_SOURCES.items():
        source = resolve_source(kind, name, args)
        raw = json.loads(source.read_text(encoding="utf-8"))
        target = args.output_dir / destination
        write_json(target, sanitize_json(raw, roots))
        provenance.append(
            {
                "public_path": destination,
                "source_name": source.name,
                "source_sha256": sha256(source),
                "public_sha256": sha256(target),
                "public_bytes": target.stat().st_size,
            }
        )

    for destination, (kind, name) in COPY_SOURCES.items():
        source = resolve_source(kind, name, args)
        target = args.output_dir / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        provenance.append(
            {
                "public_path": destination,
                "source_name": source.name,
                "source_sha256": sha256(source),
                "public_sha256": sha256(target),
                "public_bytes": target.stat().st_size,
            }
        )

    package = {
        "schema_version": "robotraceopt-public-evidence-package/v1",
        "dataset": "native-x86-ubuntu-24.04-jazzy-f3f4-formal-v3",
        "dataset_role": "test",
        "formal_experiment_allowed": True,
        "experiment_git_commit": "384b21556d12e572ef8e490c1ab7cfef0c328203",
        "session_seed": 20260729,
        "paired_repetitions": 10,
        "raw_data_included": False,
        "sanitization": "Local paths, usernames, and host identifiers are replaced.",
        "sanitization_version": "v2-root-home-redaction",
        "files": sorted(provenance, key=lambda item: item["public_path"]),
    }
    write_json(args.output_dir / "PACKAGE_MANIFEST.json", package)
    archive_sha256 = finish_package(args.output_dir)
    print(json.dumps({"status": "completed", "files": len(provenance), "archive_sha256": archive_sha256}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
