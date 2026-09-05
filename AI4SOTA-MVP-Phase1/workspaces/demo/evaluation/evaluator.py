"""Editable evaluation layer: accuracy and macro-F1."""

import numpy as np

from ai4sota import CanonicalDataset, EvaluationResult, PredictionBundle


def evaluate(
    dataset: CanonicalDataset,
    predictions: PredictionBundle,
    config: dict,
) -> EvaluationResult:
    if not np.array_equal(dataset.sample_ids.astype(str), predictions.sample_ids.astype(str)):
        raise ValueError("prediction sample_ids do not align with dataset sample_ids")

    truth = np.asarray(dataset.targets[config["target_key"]]).reshape(-1)
    predicted = np.asarray(predictions.outputs[config["prediction_key"]]).reshape(-1)
    split = np.asarray(dataset.metadata[config["split_key"]]).astype(str)
    mask = split == str(config["evaluate_split"])
    if not mask.any():
        raise ValueError(f"no samples found for evaluation split {config['evaluate_split']!r}")

    truth = truth[mask]
    predicted = predicted[mask]
    labels = np.unique(np.concatenate([truth, predicted]))
    per_class_f1 = {}
    confusion = {}
    for label in labels:
        tp = int(np.sum((truth == label) & (predicted == label)))
        fp = int(np.sum((truth != label) & (predicted == label)))
        fn = int(np.sum((truth == label) & (predicted != label)))
        denominator = 2 * tp + fp + fn
        per_class_f1[str(label)] = 0.0 if denominator == 0 else (2 * tp / denominator)
        confusion[str(label)] = {"tp": tp, "fp": fp, "fn": fn}

    accuracy = float(np.mean(truth == predicted))
    macro_f1 = float(np.mean(list(per_class_f1.values())))
    return EvaluationResult(
        metrics={"accuracy": accuracy, "macro_f1": macro_f1},
        tables={
            "sample_count": int(mask.sum()),
            "per_class_f1": per_class_f1,
            "one_vs_rest_counts": confusion,
        },
    )

