"""Editable method layer: a dependency-light binary classification baseline."""

import numpy as np

from ai4sota import CanonicalDataset, PredictionBundle


def fit_predict(dataset: CanonicalDataset, config: dict) -> PredictionBundle:
    X = np.asarray(dataset.inputs[config["input_key"]], dtype=np.float64)
    y_raw = np.asarray(dataset.targets[config["target_key"]]).reshape(-1)
    split = np.asarray(dataset.metadata[config["split_key"]]).astype(str)

    if X.ndim < 2:
        raise ValueError("features must have shape (sample, ...)")
    X = X.reshape(len(X), -1)
    classes = np.unique(y_raw)
    if len(classes) != 2:
        raise ValueError(f"baseline requires exactly two classes; got {classes.tolist()}")
    y = (y_raw == classes[1]).astype(np.float64)

    train_mask = split == "train"
    if train_mask.sum() < 2:
        raise ValueError("training split must contain at least two samples")
    mean = X[train_mask].mean(axis=0)
    scale = X[train_mask].std(axis=0)
    scale[scale < 1e-12] = 1.0
    Z = (X - mean) / scale
    Z = np.column_stack([np.ones(len(Z)), Z])

    weights = np.zeros(Z.shape[1], dtype=np.float64)
    learning_rate = float(config["learning_rate"])
    l2 = float(config["l2"])
    for _ in range(int(config["epochs"])):
        probability = _sigmoid(Z[train_mask] @ weights)
        gradient = Z[train_mask].T @ (probability - y[train_mask]) / train_mask.sum()
        gradient[1:] += l2 * weights[1:]
        weights -= learning_rate * gradient

    probability = _sigmoid(Z @ weights)
    encoded_prediction = (probability >= 0.5).astype(np.int64)
    predicted_label = classes[encoded_prediction]
    return PredictionBundle(
        sample_ids=dataset.sample_ids,
        outputs={
            "label": predicted_label,
            "positive_probability": probability,
        },
        metadata={"classes": classes.tolist()},
    )


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))
