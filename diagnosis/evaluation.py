"""Shared held-out evaluator for all diagnosis evidence modes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from diagnosis.evidence_graph.inference import DiagnosisResult


ABSTAIN_LABEL = "__abstain__"
EVIDENCE_MODES = {"app_only", "tracing_only", "ebpf_only", "fused"}


@dataclass(frozen=True)
class DiagnosisOracle:
    trace_id: str
    true_cause_id: str
    should_abstain: bool
    dataset_role: str
    session_id: str

    def __post_init__(self) -> None:
        if self.dataset_role not in {"calibration", "test"}:
            raise ValueError(f"invalid dataset role: {self.dataset_role}")
        if self.should_abstain == bool(self.true_cause_id):
            raise ValueError(
                "oracle must declare either a cause or required abstention"
            )
        if not self.session_id:
            raise ValueError("oracle session_id is required")


def validate_partition_isolation(
    calibration: Iterable[DiagnosisOracle], test: Iterable[DiagnosisOracle]
) -> None:
    calibration_by_id = _oracle_by_id(calibration, "calibration")
    test_by_id = _oracle_by_id(test, "test")
    overlap = sorted(calibration_by_id.keys() & test_by_id.keys())
    if overlap:
        raise ValueError(f"calibration/test trace overlap: {overlap}")
    session_overlap = sorted(
        {label.session_id for label in calibration_by_id.values()}
        & {label.session_id for label in test_by_id.values()}
    )
    if session_overlap:
        raise ValueError(f"calibration/test session overlap: {session_overlap}")


def evaluate_diagnoses(
    predictions: Iterable[DiagnosisResult],
    oracle: Iterable[DiagnosisOracle],
    *,
    mode: str,
    expected_role: str,
    calibration_bins: int = 10,
) -> dict[str, object]:
    if mode not in EVIDENCE_MODES:
        raise ValueError(f"unsupported evidence mode: {mode}")
    if expected_role not in {"calibration", "test"}:
        raise ValueError(f"invalid dataset role: {expected_role}")
    if calibration_bins < 1:
        raise ValueError("calibration_bins must be positive")
    predictions_by_id = _prediction_by_id(predictions)
    oracle_by_id = _oracle_by_id(oracle, expected_role)
    if predictions_by_id.keys() != oracle_by_id.keys():
        missing = sorted(predictions_by_id.keys() - oracle_by_id.keys())
        extra = sorted(oracle_by_id.keys() - predictions_by_id.keys())
        raise ValueError(f"oracle coverage mismatch: missing={missing}, extra={extra}")

    fault_ids = [
        trace_id for trace_id, label in oracle_by_id.items() if not label.should_abstain
    ]
    top_1_correct = 0
    top_k_correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    fault_confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    abstention_correct = 0
    calibration_samples: list[tuple[float, int]] = []
    for trace_id in sorted(predictions_by_id):
        result = predictions_by_id[trace_id]
        label = oracle_by_id[trace_id]
        ranked = [candidate.cause_id for candidate in result.candidates]
        predicted_label = (
            ranked[0] if result.status == "diagnosed" and ranked else ABSTAIN_LABEL
        )
        true_label = label.true_cause_id if not label.should_abstain else ABSTAIN_LABEL
        confusion[true_label][predicted_label] += 1
        predicted_abstain = result.status != "diagnosed"
        abstention_correct += predicted_abstain == label.should_abstain
        if label.should_abstain:
            continue
        fault_confusion[true_label][predicted_label] += 1
        top_1_correct += predicted_label == label.true_cause_id
        top_k_correct += label.true_cause_id in ranked
        if result.status == "diagnosed":
            calibration_samples.append(
                (result.confidence, int(predicted_label == label.true_cause_id))
            )

    cause_labels = sorted(
        {oracle_by_id[trace_id].true_cause_id for trace_id in fault_ids}
    )
    report_confusion = {
        true_label: dict(predicted_counts)
        for true_label, predicted_counts in confusion.items()
    }
    fault_count = len(fault_ids)
    return {
        "schema_version": "diagnosis-evaluation/v1",
        "mode": mode,
        "dataset_role": expected_role,
        "sample_count": len(predictions_by_id),
        "session_count": len({label.session_id for label in oracle_by_id.values()}),
        "fault_case_count": fault_count,
        "top_1_accuracy": _divide(top_1_correct, fault_count),
        "top_k_recall": _divide(top_k_correct, fault_count),
        "macro_f1": _macro_f1(
            {label: dict(counts) for label, counts in fault_confusion.items()},
            cause_labels,
        ),
        "abstention_accuracy": _divide(abstention_correct, len(predictions_by_id)),
        "confusion_matrix": report_confusion,
        "confidence_calibration": _confidence_calibration(
            calibration_samples, calibration_bins
        ),
    }


def _oracle_by_id(
    labels: Iterable[DiagnosisOracle], expected_role: str
) -> dict[str, DiagnosisOracle]:
    result: dict[str, DiagnosisOracle] = {}
    for label in labels:
        if label.dataset_role != expected_role:
            raise ValueError(
                f"oracle dataset role mismatch: expected {expected_role}, "
                f"got {label.dataset_role} for {label.trace_id}"
            )
        if label.trace_id in result:
            raise ValueError(f"duplicate oracle trace: {label.trace_id}")
        result[label.trace_id] = label
    return result


def _prediction_by_id(
    predictions: Iterable[DiagnosisResult],
) -> dict[str, DiagnosisResult]:
    result: dict[str, DiagnosisResult] = {}
    for prediction in predictions:
        if prediction.trace_id in result:
            raise ValueError(f"duplicate prediction trace: {prediction.trace_id}")
        if not 0 <= prediction.confidence <= 1:
            raise ValueError(f"confidence out of range: {prediction.trace_id}")
        result[prediction.trace_id] = prediction
    return result


def _macro_f1(
    confusion: dict[str, dict[str, int]], cause_labels: list[str]
) -> float | None:
    if not cause_labels:
        return None
    scores: list[float] = []
    for cause in cause_labels:
        true_positive = confusion.get(cause, {}).get(cause, 0)
        false_positive = sum(
            counts.get(cause, 0)
            for true_label, counts in confusion.items()
            if true_label != cause
        )
        false_negative = sum(
            count
            for predicted_label, count in confusion.get(cause, {}).items()
            if predicted_label != cause
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(_divide(2 * true_positive, denominator) or 0.0)
    return sum(scores) / len(scores)


def _confidence_calibration(
    samples: list[tuple[float, int]], bins: int
) -> dict[str, object]:
    if not samples:
        return {"sample_count": 0, "brier_score": None, "ece": None, "bins": []}
    brier = sum((confidence - correct) ** 2 for confidence, correct in samples) / len(
        samples
    )
    grouped: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for confidence, correct in samples:
        grouped[min(int(confidence * bins), bins - 1)].append((confidence, correct))
    records: list[dict[str, object]] = []
    ece = 0.0
    for index, items in enumerate(grouped):
        if not items:
            continue
        mean_confidence = sum(item[0] for item in items) / len(items)
        accuracy = sum(item[1] for item in items) / len(items)
        ece += len(items) / len(samples) * abs(mean_confidence - accuracy)
        records.append(
            {
                "bin_index": index,
                "count": len(items),
                "mean_confidence": mean_confidence,
                "accuracy": accuracy,
            }
        )
    return {
        "sample_count": len(samples),
        "brier_score": brier,
        "ece": ece,
        "bins": records,
    }


def _divide(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
