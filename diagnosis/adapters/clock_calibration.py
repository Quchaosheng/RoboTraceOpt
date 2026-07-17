"""Create auditable clock-comparability reports for evidence fusion."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Callable, Sequence


KNOWN_CLOCKS = {"monotonic", "realtime", "tai"}


class ClockCalibrationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ClockCalibrationReport:
    schema_version: str
    source_host: str
    target_host: str
    source_clock_id: str
    target_clock_id: str
    method: str
    sample_count: int
    estimated_offset_ns: int
    max_error_ns: int
    tolerance_ns: int
    status: str
    reason_code: str
    measured_at_utc: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def assess_clock_comparability(
    *,
    source_host: str,
    target_host: str,
    source_clock_id: str,
    target_clock_id: str,
    offset_samples_ns: Sequence[int],
    uncertainty_samples_ns: Sequence[int],
    tolerance_ns: int,
    method: str,
    measured_at_utc: str | None = None,
) -> ClockCalibrationReport:
    unknown = sorted(
        {source_clock_id, target_clock_id} - KNOWN_CLOCKS
    )
    if unknown:
        raise ClockCalibrationError(
            "unknown_clock", "unsupported clock domain: " + ", ".join(unknown)
        )
    if not source_host or not target_host:
        raise ClockCalibrationError("invalid_host", "source and target host are required")
    if not method:
        raise ClockCalibrationError("invalid_method", "calibration method is required")
    if tolerance_ns < 0:
        raise ClockCalibrationError("invalid_tolerance", "tolerance must be non-negative")
    if not offset_samples_ns or len(offset_samples_ns) != len(uncertainty_samples_ns):
        raise ClockCalibrationError(
            "invalid_samples", "offset and uncertainty samples must be non-empty and paired"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (*offset_samples_ns, *uncertainty_samples_ns)
    ):
        raise ClockCalibrationError("invalid_samples", "samples must be integer nanoseconds")
    if any(value < 0 for value in uncertainty_samples_ns):
        raise ClockCalibrationError("invalid_samples", "uncertainty cannot be negative")

    estimated_offset_ns = int(median(offset_samples_ns))
    max_error_ns = max(
        abs(offset - estimated_offset_ns) + uncertainty
        for offset, uncertainty in zip(offset_samples_ns, uncertainty_samples_ns)
    )
    within_tolerance = abs(estimated_offset_ns) + max_error_ns <= tolerance_ns

    return ClockCalibrationReport(
        schema_version="clock-calibration/v1",
        source_host=source_host,
        target_host=target_host,
        source_clock_id=source_clock_id,
        target_clock_id=target_clock_id,
        method=method,
        sample_count=len(offset_samples_ns),
        estimated_offset_ns=estimated_offset_ns,
        max_error_ns=max_error_ns,
        tolerance_ns=tolerance_ns,
        status="comparable" if within_tolerance else "not_comparable",
        reason_code="" if within_tolerance else "clock_error_over_tolerance",
        measured_at_utc=measured_at_utc or _utc_now(),
    )


def measure_local_monotonic_alignment(
    *,
    sample_count: int = 100,
    reference_reader: Callable[[], int] = time.monotonic_ns,
    candidate_reader: Callable[[], int] | None = None,
    host_id: str,
    tolerance_ns: int = 100_000,
) -> ClockCalibrationReport:
    if sample_count <= 0:
        raise ClockCalibrationError("invalid_samples", "sample_count must be positive")
    if candidate_reader is None:
        candidate_reader = lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC)

    offsets: list[int] = []
    uncertainties: list[int] = []
    for _ in range(sample_count):
        before = reference_reader()
        candidate = candidate_reader()
        after = reference_reader()
        if after < before:
            raise ClockCalibrationError(
                "non_monotonic_sample", "reference clock moved backwards"
            )
        midpoint = (before + after) // 2
        offsets.append(candidate - midpoint)
        uncertainties.append((after - before + 1) // 2)

    return assess_clock_comparability(
        source_host=host_id,
        target_host=host_id,
        source_clock_id="monotonic",
        target_clock_id="monotonic",
        offset_samples_ns=offsets,
        uncertainty_samples_ns=uncertainties,
        tolerance_ns=tolerance_ns,
        method="bracketed_clock_gettime",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--sample-count", type=int, default=100)
    parser.add_argument("--tolerance-ns", type=int, default=100_000)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = measure_local_monotonic_alignment(
        sample_count=args.sample_count,
        host_id=args.host_id,
        tolerance_ns=args.tolerance_ns,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
