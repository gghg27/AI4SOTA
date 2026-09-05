"""Editable data layer: raw NPZ -> CanonicalDataset."""

from pathlib import Path

import numpy as np

from ai4sota import CanonicalDataset


def load_dataset(project_dir: Path, config: dict) -> CanonicalDataset:
    source = Path(config["source"]["path"]).expanduser()
    if not source.is_absolute():
        source = project_dir / source

    with np.load(source, allow_pickle=False) as archive:
        X = np.asarray(archive[config["fields"]["inputs"]["features"]])
        y = np.asarray(archive[config["fields"]["targets"]["label"]]).reshape(-1)
        if len(X) != len(y):
            raise ValueError(f"X and y have different sample counts: {len(X)} vs {len(y)}")

        sample_key = config["fields"]["metadata"].get("sample_ids")
        if sample_key and sample_key in archive:
            sample_ids = np.asarray(archive[sample_key]).astype(str)
        else:
            sample_ids = np.asarray([f"sample_{index:06d}" for index in range(len(y))])

        split_key = config["fields"]["metadata"].get("split")
        if split_key and split_key in archive:
            split = np.asarray(archive[split_key]).astype(str)
        else:
            split = _make_split(
                len(y),
                test_ratio=float(config["split"]["test_ratio"]),
                seed=int(config["split"]["random_seed"]),
            )

    return CanonicalDataset(
        sample_ids=sample_ids,
        inputs={"features": X},
        targets={"label": y},
        metadata={"split": split},
        schema={
            "input_axes": ["sample", "feature"],
            "task": "binary_classification",
        },
    )


def _make_split(sample_count: int, test_ratio: float, seed: int) -> np.ndarray:
    if not 0.0 < test_ratio < 1.0:
        raise ValueError("test_ratio must be between 0 and 1")
    rng = np.random.default_rng(seed)
    order = rng.permutation(sample_count)
    test_count = max(1, round(sample_count * test_ratio))
    split = np.full(sample_count, "train", dtype="U5")
    split[order[:test_count]] = "test"
    return split
