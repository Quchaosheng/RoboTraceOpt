"""Project recorded experiment artifacts into JSON, Markdown, and CSV."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_experiment_report(source: Path) -> dict[str, Any]:
    if source.is_symlink():
        raise ValueError(f"symlinked evidence source is forbidden: {source}")
    root = source.resolve()
    if not root.is_dir():
        raise ValueError(f"evidence source is not a directory: {source}")
    entries = sorted(root.rglob("*"))
    symlinks = [path for path in entries if path.is_symlink()]
    if symlinks:
        raise ValueError(f"symlinked evidence is forbidden: {symlinks[0]}")

    artifacts: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for path in (item for item in entries if item.is_file() and item.suffix == ".json"):
        relative = path.relative_to(root).as_posix()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = None
        if not isinstance(value, dict):
            artifact = {
                "path": relative,
                "schema_version": "unavailable",
                "status": "invalid_json",
                "development_only": None,
                "physical_can_evidence": None,
                "sha256": _sha256(path),
            }
            artifact_metrics: list[tuple[str, int | float]] = []
        else:
            artifact = {
                "path": relative,
                "schema_version": str(value.get("schema_version", "unavailable")),
                "status": str(value.get("status", "unreported")),
                "development_only": value.get("development_only")
                if isinstance(value.get("development_only"), bool)
                else None,
                "physical_can_evidence": value.get("physical_can_evidence")
                if isinstance(value.get("physical_can_evidence"), bool)
                else None,
                "sha256": _sha256(path),
            }
            artifact_metrics = list(_recorded_metrics(value))
        artifacts.append(artifact)
        metrics.extend(
            {"artifact": relative, "metric": name, "value": number}
            for name, number in artifact_metrics
        )

    status_counts = Counter(artifact["status"] for artifact in artifacts)
    return {
        "schema_version": "experiment-report-projection/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(root),
        "artifact_count": len(artifacts),
        "status_counts": dict(sorted(status_counts.items())),
        "artifacts": artifacts,
        "metrics": sorted(metrics, key=lambda row: (row["artifact"], row["metric"])),
        "limitations": [
            "Only scalar metrics already present in source JSON are projected.",
            "Missing values are unavailable; this report does not impute or recompute measurements.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Experiment Evidence Report",
        "",
        f"- Source artifacts: **{report['artifact_count']}**",
        f"- Generated: `{report['generated_at_utc']}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Schema | Status | Physical CAN |",
        "|---|---|---|---|",
    ]
    for artifact in report["artifacts"]:
        physical = artifact["physical_can_evidence"]
        lines.append(
            f"| `{artifact['path']}` | `{artifact['schema_version']}` | "
            f"{artifact['status']} | {physical if physical is not None else 'unavailable'} |"
        )
    lines.extend(
        [
            "",
            "## Recorded Metrics",
            "",
            "| Artifact | Metric | Value |",
            "|---|---|---:|",
        ]
    )
    if report["metrics"]:
        lines.extend(
            f"| `{row['artifact']}` | `{row['metric']}` | {row['value']} |"
            for row in report["metrics"]
        )
    else:
        lines.append("| unavailable | unavailable | unavailable |")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def write_report_outputs(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output = output_dir.resolve()
    paths = {
        "json": output / "experiment_report.json",
        "markdown": output / "experiment_report.md",
        "csv": output / "experiment_metrics.csv",
    }
    existing = [path for path in paths.values() if path.exists() or path.is_symlink()]
    if existing:
        raise ValueError(f"report output already exists: {existing[0]}")
    output.mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    by_artifact: dict[str, list[dict[str, Any]]] = {}
    for row in report["metrics"]:
        by_artifact.setdefault(row["artifact"], []).append(row)
    with paths["csv"].open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("artifact", "schema_version", "status", "metric", "value"),
        )
        writer.writeheader()
        for artifact in report["artifacts"]:
            rows = by_artifact.get(artifact["path"], [])
            if not rows:
                rows = [
                    {
                        "artifact": artifact["path"],
                        "metric": "unavailable",
                        "value": "unavailable",
                    }
                ]
            for row in rows:
                writer.writerow(
                    {
                        "artifact": artifact["path"],
                        "schema_version": artifact["schema_version"],
                        "status": artifact["status"],
                        "metric": row["metric"],
                        "value": row["value"],
                    }
                )
    return paths


def _recorded_metrics(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _recorded_metrics(value[key], path)
    elif isinstance(value, list):
        return
    elif (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and _is_metric_name(prefix.rsplit(".", 1)[-1])
    ):
        yield prefix, value


def _is_metric_name(name: str) -> bool:
    return name in {
        "mean",
        "median",
        "min",
        "max",
        "p50",
        "p90",
        "p95",
        "p99",
    } or name.endswith(
        ("_count", "_rate", "_coverage", "_delta", "_ns", "_ms", "_percent")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
