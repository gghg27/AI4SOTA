from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from ai4sota.domain import (
    DataModuleSpec,
    DatasetSourceSpec,
    EvaluationSpec,
    ExperimentSpec,
    MethodSpec,
    ModuleKind,
    PreprocessingSpec,
    SplitManifest,
    TaskContract,
)
from ai4sota.domain.experiments import SplitMember
from ai4sota.files.hashing import sha256_file
from ai4sota.projects import ProjectLayout
from ai4sota.storage import ManifestStore, canonical_manifest_hash

ModelT = TypeVar("ModelT", bound=BaseModel)
ZERO_HASH = "sha256:" + "0" * 64


def write_hashed_manifest(
    path: Path, model: type[ModelT], payload: dict[str, object]
) -> ModelT:
    draft = model.model_validate({**payload, "content_hash": ZERO_HASH})
    value = draft.model_copy(update={"content_hash": canonical_manifest_hash(draft)})
    ManifestStore().write(path, value)
    return value


@pytest.fixture
def runnable_project(tmp_path: Path) -> tuple[ProjectLayout, ExperimentSpec, Path]:
    layout = ProjectLayout.create(tmp_path, "seed-emotion")
    external_data = tmp_path / "external" / "seed-records.bin"
    external_data.parent.mkdir()
    external_data.write_bytes(b"immutable external dataset bytes")
    fingerprint_hash = sha256_file(external_data)

    task = write_hashed_manifest(
        layout.task_file,
        TaskContract,
        {
            "id": "task/emotion",
            "version": "1.0.0",
            "prediction_unit": "trial",
            "target_type": "multiclass",
            "classes": {"negative": 0, "neutral": 1},
            "required_metadata": ["subject_id"],
        },
    )
    source = write_hashed_manifest(
        layout.module_dir(ModuleKind.DATA) / "dataset.yaml",
        DatasetSourceSpec,
        {
            "id": "dataset/seed",
            "version": "1.0.0",
            "name": "SEED",
            "locations": [str(external_data)],
            "sampling_rate_hz": 200.0,
            "metadata_fields": ["subject_id"],
            "fingerprint_hash": fingerprint_hash,
            "source_format": "binary",
        },
    )
    preprocessing = write_hashed_manifest(
        layout.module_dir(ModuleKind.DATA) / "preprocessing.yaml",
        PreprocessingSpec,
        {
            "id": "preprocessing/seed",
            "version": "1.0.0",
            "transforms": [{"name": "bandpass"}],
            "graph_hash": "sha256:" + "1" * 64,
        },
    )
    data = write_hashed_manifest(
        layout.module_dir(ModuleKind.DATA) / "module.yaml",
        DataModuleSpec,
        {
            "id": "data/seed",
            "version": "1.0.0",
            "origin": {"type": "project"},
            "source": source.id,
            "preprocessing": preprocessing.id,
            "entrypoint": "adapter:load_dataset",
            "canonical_outputs": ["features"],
            "task_contract": task.id,
            "task_contract_hash": task.content_hash,
        },
    )
    data_code = layout.module_dir(ModuleKind.DATA) / "adapter.py"
    data_code.write_text("def load_dataset():\n    return None\n", encoding="utf-8")

    method = write_hashed_manifest(
        layout.module_dir(ModuleKind.METHOD) / "module.yaml",
        MethodSpec,
        {
            "id": "method/linear",
            "version": "1.0.0",
            "origin": {"type": "project"},
            "framework": "numpy",
            "entrypoint": "model:fit_predict",
            "input_requirements": {"features": {"rank": 2}},
            "output_capabilities": ["logits"],
            "task_contracts": [task.id],
        },
    )
    method_code = layout.module_dir(ModuleKind.METHOD) / "model.py"
    method_code.write_text("LEARNING_RATE = 0.01\n", encoding="utf-8")

    evaluation = write_hashed_manifest(
        layout.module_dir(ModuleKind.EVALUATION) / "module.yaml",
        EvaluationSpec,
        {
            "id": "evaluation/subject-holdout",
            "version": "1.0.0",
            "origin": {"type": "project"},
            "entrypoint": "evaluator:evaluate",
            "task_contract": task.id,
            "task_contract_hash": task.content_hash,
            "required_predictions": ["logits"],
            "required_metadata": ["subject_id"],
            "protocol": {
                "kind": "group_holdout",
                "group_by": "subject_id",
                "test_fraction": 0.25,
            },
            "metrics": [
                {
                    "name": "accuracy",
                    "primary": True,
                    "implementation": "builtin/accuracy-v1",
                }
            ],
        },
    )
    (layout.module_dir(ModuleKind.EVALUATION) / "evaluator.py").write_text(
        "def evaluate():\n    return {}\n", encoding="utf-8"
    )

    split = write_hashed_manifest(
        layout.splits_dir / "approved.yaml",
        SplitManifest,
        {
            "id": "split/approved",
            "version": "1.0.0",
            "evaluation_hash": evaluation.content_hash,
            "seed": 17,
            "group_by": "subject_id",
            "members": [
                SplitMember(sample_id="sample-1", partition="train"),
                SplitMember(sample_id="sample-2", partition="test"),
            ],
        },
    )
    write_hashed_manifest(
        layout.splits_dir / "unselected.yaml",
        SplitManifest,
        {
            "id": "split/unselected",
            "version": "1.0.0",
            "evaluation_hash": evaluation.content_hash,
            "seed": 99,
            "group_by": "subject_id",
            "members": [
                SplitMember(sample_id="sample-1", partition="test"),
                SplitMember(sample_id="sample-2", partition="train"),
            ],
        },
    )
    fingerprint_record = layout.fingerprints_dir / "seed.yaml"
    ManifestStore().write(fingerprint_record, source)
    write_hashed_manifest(
        layout.fingerprints_dir / "unselected.yaml",
        DatasetSourceSpec,
        {
            "id": "dataset/unselected",
            "version": "1.0.0",
            "name": "Other data",
            "locations": [str(external_data)],
            "sampling_rate_hz": 200.0,
            "metadata_fields": ["subject_id"],
            "fingerprint_hash": "sha256:" + "f" * 64,
            "source_format": "binary",
        },
    )
    adapter = layout.adapters_dir / "logits_adapter.py"
    adapter.write_text("def adapt(value):\n    return value\n", encoding="utf-8")
    configs = layout.root / "configs"
    configs.mkdir()
    (configs / "train.yaml").write_text("batch_size: 16\n", encoding="utf-8")
    schemas = layout.root / "schemas"
    schemas.mkdir()
    (schemas / "prediction.json").write_text(
        '{"required": ["logits"]}\n', encoding="utf-8"
    )
    pipeline = layout.root / "pipeline.py"
    pipeline.write_text("RUNNER = 'v1'\n", encoding="utf-8")

    input_files = [
        layout.project_file,
        layout.task_file,
        *(path for kind in ModuleKind for path in layout.module_dir(kind).rglob("*")),
        adapter,
        configs / "train.yaml",
        schemas / "prediction.json",
        fingerprint_record,
        layout.splits_dir / "approved.yaml",
        pipeline,
    ]
    input_hashes = {
        path.relative_to(layout.root).as_posix(): sha256_file(path)
        for path in sorted(input_files)
        if path.is_file()
    }

    experiment = write_hashed_manifest(
        layout.root / "approved-experiment.yaml",
        ExperimentSpec,
        {
            "id": "experiment/approved",
            "version": "1.0.0",
            "project_id": "project/seed-emotion",
            "data_module_hash": data.content_hash,
            "method_module_hash": method.content_hash,
            "evaluation_module_hash": evaluation.content_hash,
            "task_contract_hash": task.content_hash,
            "data_fingerprint_hash": fingerprint_hash,
            "split_manifest_hash": split.content_hash,
            "seed": 17,
            "input_hashes": input_hashes,
            "generated_adapter_hashes": [sha256_file(adapter)],
            "runtime_config": {"batch_size": 16},
            "environment": {"python": "3.11"},
            "approval_id": "approval/run-001",
        },
    )
    return layout, experiment, external_data
