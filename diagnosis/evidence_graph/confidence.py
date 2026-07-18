"""Calibration-gated scoring and confidence configuration."""

from __future__ import annotations

from dataclasses import dataclass
from string import hexdigits
from typing import Any


@dataclass(frozen=True)
class EvidenceAvailability:
    state: str
    reason_code: str
    provenance: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.state not in {"valid", "partial", "invalid"}:
            raise ValueError(f"unsupported evidence availability: {self.state}")


@dataclass(frozen=True)
class ScoringProfile:
    profile_id: str
    calibration_manifest_sha256: str
    thresholds: dict[str, float]
    weights: dict[str, float]
    conflict_penalty: float
    missing_penalty: float
    minimum_score: float
    minimum_margin: float
    minimum_completeness: float

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "ScoringProfile":
        if record.get("schema_version") != "diagnosis-scoring/v1":
            raise ValueError("unsupported scoring profile schema")
        if record.get("dataset_role") != "calibration":
            raise ValueError("scoring profile must come from calibration data")
        if record.get("frozen_before_test") is not True:
            raise ValueError("scoring profile must be frozen before test data")
        profile_id = record.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("scoring profile_id is required")
        manifest_hash = record.get("calibration_manifest_sha256")
        if (
            not isinstance(manifest_hash, str)
            or len(manifest_hash) != 64
            or any(character not in hexdigits for character in manifest_hash)
        ):
            raise ValueError("calibration manifest SHA-256 is required")
        thresholds = _numeric_mapping(record.get("thresholds"), "thresholds")
        weights = _numeric_mapping(record.get("weights"), "weights")
        if thresholds.keys() != weights.keys():
            raise ValueError("threshold and weight metric keys must match")
        if any(value <= 0 for value in (*thresholds.values(), *weights.values())):
            raise ValueError("thresholds and weights must be positive")
        profile = cls(
            profile_id=profile_id,
            calibration_manifest_sha256=manifest_hash.lower(),
            thresholds=thresholds,
            weights=weights,
            conflict_penalty=_number(record, "conflict_penalty"),
            missing_penalty=_number(record, "missing_penalty"),
            minimum_score=_number(record, "minimum_score"),
            minimum_margin=_number(record, "minimum_margin"),
            minimum_completeness=_number(record, "minimum_completeness"),
        )
        if (
            min(
                profile.conflict_penalty,
                profile.missing_penalty,
                profile.minimum_score,
                profile.minimum_margin,
            )
            < 0
        ):
            raise ValueError("scoring penalties and minima must be non-negative")
        if not 0 <= profile.minimum_completeness <= 1:
            raise ValueError("minimum_completeness must be between 0 and 1")
        return profile


def _number(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _numeric_mapping(value: object, label: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must be a non-empty object")
    result: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} keys must be non-empty strings")
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{label}.{key} must be numeric")
        result[key] = float(item)
    return result
