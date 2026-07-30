#!/usr/bin/env python3
"""Render dependency-free, thesis-ready SVG figures from a formal F3/F4 analysis."""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any


WIDTH = 1100
HEIGHT = 640
MARGIN_LEFT = 120
MARGIN_RIGHT = 60
MARGIN_TOP = 105
MARGIN_BOTTOM = 145
PLOT_WIDTH = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
PLOT_HEIGHT = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
BLUE = "#2678b2"
ORANGE = "#dc7f35"
GRID = "#d8dee6"
TEXT = "#1d2733"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def svg_document(title: str, body: list[str]) -> str:
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
            "<style>text{font-family:Arial,Helvetica,sans-serif;fill:#1d2733}.title{font-size:25px;font-weight:700}.subtitle{font-size:15px}.axis{font-size:15px}.tick{font-size:13px}.label{font-size:14px;font-weight:700}.note{font-size:13px}</style>",
            f"<title>{escape(title)}</title>",
            '<rect width="100%" height="100%" fill="white"/>',
            *body,
            "</svg>",
        ]
    ) + "\n"


def add_axes(body: list[str], *, maximum: float, y_label: str, ticks: list[float]) -> None:
    bottom = MARGIN_TOP + PLOT_HEIGHT
    body.extend(
        [
            f'<line x1="{MARGIN_LEFT}" y1="{bottom}" x2="{MARGIN_LEFT + PLOT_WIDTH}" y2="{bottom}" stroke="{TEXT}" stroke-width="1.5"/>',
            f'<line x1="{MARGIN_LEFT}" y1="{MARGIN_TOP}" x2="{MARGIN_LEFT}" y2="{bottom}" stroke="{TEXT}" stroke-width="1.5"/>',
            f'<text class="axis" transform="translate(28 {MARGIN_TOP + PLOT_HEIGHT / 2}) rotate(-90)" text-anchor="middle">{escape(y_label)}</text>',
        ]
    )
    for tick in ticks:
        y = bottom - PLOT_HEIGHT * tick / maximum
        body.extend(
            [
                f'<line x1="{MARGIN_LEFT}" y1="{y:.2f}" x2="{MARGIN_LEFT + PLOT_WIDTH}" y2="{y:.2f}" stroke="{GRID}" stroke-width="1"/>',
                f'<text class="tick" x="{MARGIN_LEFT - 12}" y="{y + 5:.2f}" text-anchor="end">{tick:g}</text>',
            ]
        )


def condition(summary: dict[str, Any], fault_id: str, variant: str) -> dict[str, Any]:
    for row in summary["conditions"]:
        if row["fault_id"] == fault_id and row["variant"] == variant:
            return row
    raise ValueError(f"missing {fault_id}/{variant} condition")


def f3_completeness(summary: dict[str, Any]) -> str:
    control = condition(summary, "F3", "control")
    injected = condition(summary, "F3", "injected")
    values = [("Matched control", float(control["complete_rate"]) * 100, BLUE), ("F3 pressure injected", float(injected["complete_rate"]) * 100, ORANGE)]
    body = [
        '<text class="title" x="60" y="48">F3 pressure: complete lifecycle recovery</text>',
        '<text class="subtitle" x="60" y="75">Formal Ubuntu 24.04/Jazzy test partition; recovery rate, not a scheduler-latency estimate</text>',
    ]
    add_axes(body, maximum=100, y_label="Complete lifecycle recovery (%)", ticks=[0, 20, 40, 60, 80, 100])
    bar_width = 190
    centers = [MARGIN_LEFT + PLOT_WIDTH * 0.29, MARGIN_LEFT + PLOT_WIDTH * 0.71]
    bottom = MARGIN_TOP + PLOT_HEIGHT
    for (label, value, colour), center in zip(values, centers):
        height = PLOT_HEIGHT * value / 100
        x = center - bar_width / 2
        y = bottom - height
        body.extend(
            [
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width}" height="{height:.2f}" fill="{colour}" rx="4"/>',
                f'<text class="label" x="{center}" y="{y - 12:.2f}" text-anchor="middle">{value:.2f}%</text>',
                f'<text class="axis" x="{center}" y="{bottom + 30}" text-anchor="middle">{escape(label)}</text>',
            ]
        )
    body.extend(
        [
            f'<text class="note" x="{MARGIN_LEFT}" y="{HEIGHT - 62}">Control: {control["complete"]}/{control["observed"]} complete traces; injected: {injected["complete"]}/{injected["observed"]}.</text>',
            f'<text class="note" x="{MARGIN_LEFT}" y="{HEIGHT - 38}">Interpretation boundary: incomplete lifecycles can select the remaining timing samples; do not claim scheduler-level causal latency from this figure.</text>',
        ]
    )
    return svg_document("F3 complete lifecycle recovery", body)


def f4_latency(summary: dict[str, Any]) -> str:
    metrics = summary["comparisons"]["F4"]["metrics_ns"]
    selected = [
        ("Server processing", metrics["server_processing_elapsed_ns"]["median"]),
        ("Request-response", metrics["request_response_elapsed_ns"]["median"]),
    ]
    values = [float(row[1][kind]) / 1e6 for row in selected for kind in ("control", "injected")]
    maximum = max(values) * 1.12
    ticks = [0, 25, 50, 75, 100]
    body = [
        '<text class="title" x="60" y="48">F4 blocking delay: median application-level latency</text>',
        '<text class="subtitle" x="60" y="75">Formal Ubuntu 24.04/Jazzy test partition; ten runs per condition</text>',
    ]
    add_axes(body, maximum=maximum, y_label="Median elapsed time (ms)", ticks=ticks)
    centers = [MARGIN_LEFT + PLOT_WIDTH * 0.28, MARGIN_LEFT + PLOT_WIDTH * 0.72]
    bar_width = 105
    gap = 24
    bottom = MARGIN_TOP + PLOT_HEIGHT
    for (label, metric), center in zip(selected, centers):
        for variant, colour, offset in (("control", BLUE, -(bar_width + gap) / 2), ("injected", ORANGE, (bar_width + gap) / 2)):
            value = float(metric[variant]) / 1e6
            height = PLOT_HEIGHT * value / maximum
            x = center + offset - bar_width / 2
            y = bottom - height
            body.extend(
                [
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width}" height="{height:.2f}" fill="{colour}" rx="4"/>',
                    f'<text class="label" x="{x + bar_width / 2:.2f}" y="{y - 12:.2f}" text-anchor="middle">{value:.3f}</text>',
                ]
            )
        body.append(f'<text class="axis" x="{center}" y="{bottom + 30}" text-anchor="middle">{escape(label)}</text>')
    body.extend(
        [
            f'<rect x="{WIDTH - 285}" y="{MARGIN_TOP + 8}" width="16" height="16" fill="{BLUE}" rx="2"/>',
            f'<text class="tick" x="{WIDTH - 262}" y="{MARGIN_TOP + 21}">Matched control</text>',
            f'<rect x="{WIDTH - 285}" y="{MARGIN_TOP + 34}" width="16" height="16" fill="{ORANGE}" rx="2"/>',
            f'<text class="tick" x="{WIDTH - 262}" y="{MARGIN_TOP + 47}">F4 injected</text>',
            f'<text class="note" x="{MARGIN_LEFT}" y="{HEIGHT - 42}">The injected profile configures a 100 ms server delay. The evidence is application-level; it does not assert syscall-level attribution.</text>',
        ]
    )
    return svg_document("F4 application-level blocking delay", body)


def main() -> int:
    args = parse_args()
    summary = read_json(args.analysis_summary)
    if summary.get("dataset_role") != "test" or not summary.get("formal_experiment_allowed"):
        raise SystemExit("figures require a formal test analysis summary")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / "figure_f3_completeness.svg").write_text(f3_completeness(summary), encoding="utf-8")
    (output / "figure_f4_latency.svg").write_text(f4_latency(summary), encoding="utf-8")
    print(json.dumps({"status": "completed", "output_dir": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
