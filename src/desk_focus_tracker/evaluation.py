from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desk_focus_tracker.domain import UNCERTAIN_STATUSES, Status


class EvaluationError(ValueError):
    """Raised when an evaluation data set is invalid."""


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    precision: float | None
    recall: float | None
    false_positive_rate: float | None
    support: int
    predicted: int

    def to_mapping(self) -> dict[str, float | int | None]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "support": self.support,
            "predicted": self.predicted,
        }


def load_labeled_results(path: Path) -> list[tuple[Status, Status]]:
    results: list[tuple[Status, Status]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    actual = Status(record["actual_status"])
                    predicted = Status(record["predicted_status"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    raise EvaluationError(
                        f"invalid evaluation record at line {line_number}: {error}"
                    ) from error
                results.append((actual, predicted))
    except OSError as error:
        raise EvaluationError(f"cannot read evaluation data {path}: {error}") from error
    if not results:
        raise EvaluationError("evaluation data must contain at least one record")
    return results


def evaluate_results(results: list[tuple[Status, Status]]) -> dict[str, Any]:
    if not results:
        raise EvaluationError("evaluation data must contain at least one record")

    total = len(results)
    correct = sum(actual is predicted for actual, predicted in results)
    uncertain = sum(predicted in UNCERTAIN_STATUSES for _, predicted in results)
    confusion = {actual.value: {predicted.value: 0 for predicted in Status} for actual in Status}
    for actual, predicted in results:
        confusion[actual.value][predicted.value] += 1

    classes: dict[str, dict[str, float | int | None]] = {}
    for status in Status:
        true_positive = sum(
            actual is status and predicted is status for actual, predicted in results
        )
        false_positive = sum(
            actual is not status and predicted is status for actual, predicted in results
        )
        false_negative = sum(
            actual is status and predicted is not status for actual, predicted in results
        )
        true_negative = total - true_positive - false_positive - false_negative
        predicted_count = true_positive + false_positive
        support = true_positive + false_negative
        metrics = ClassMetrics(
            precision=true_positive / predicted_count if predicted_count else None,
            recall=true_positive / support if support else None,
            false_positive_rate=(
                false_positive / (false_positive + true_negative)
                if false_positive + true_negative
                else None
            ),
            support=support,
            predicted=predicted_count,
        )
        classes[status.value] = metrics.to_mapping()

    return {
        "schema_version": 1,
        "samples": total,
        "overall_accuracy": correct / total,
        "uncertain_rate": uncertain / total,
        "primary_release_metric": {
            "name": "phone_use_precision",
            "value": classes[Status.POSSIBLE_PHONE_USE.value]["precision"],
        },
        "classes": classes,
        "confusion_matrix": confusion,
    }


def write_evaluation_report(input_path: Path, output_path: Path) -> dict[str, Any]:
    report = evaluate_results(load_labeled_results(input_path))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        raise EvaluationError(f"cannot write evaluation report {output_path}: {error}") from error
    return report
