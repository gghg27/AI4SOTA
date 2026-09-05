from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from pydantic import ValidationError

from ai4sota.compatibility import (
    AdapterKind,
    CompatibilityReport,
    MechanicalAdapterSpec,
    compile_compatibility,
)
from ai4sota.domain import (
    CompatibilityState,
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    TaskContract,
)

CONTENT_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def _documents() -> dict[str, dict[str, Any]]:
    return {
        "data": {
            "id": "data/eeg",
            "content_hash": CONTENT_HASH,
            "origin": {"type": "project"},
            "source": "source.yaml",
            "preprocessing": "preprocessing.yaml",
            "entrypoint": "adapter:load",
            "canonical_outputs": ["signal", "label", "subject_id", "sample_id"],
            "task_contract": "tasks/active.yaml",
            "task_contract_hash": CONTENT_HASH,
        },
        "method": {
            "id": "method/eegnet",
            "content_hash": CONTENT_HASH,
            "origin": {"type": "project"},
            "framework": "torch",
            "entrypoint": "model:build",
            "input_requirements": {"signal": {"field": "signal"}},
            "output_capabilities": ["logits"],
            "task_contracts": ["task/emotion"],
        },
        "evaluation": {
            "id": "evaluation/subject-holdout",
            "content_hash": CONTENT_HASH,
            "origin": {"type": "project"},
            "entrypoint": "evaluate:run",
            "task_contract": "tasks/active.yaml",
            "task_contract_hash": CONTENT_HASH,
            "required_predictions": ["logits"],
            "required_metadata": ["subject_id"],
            "protocol": {"kind": "group_holdout", "group_by": "subject_id"},
            "metrics": [
                {
                    "name": "macro_f1",
                    "primary": True,
                    "implementation": "metrics:macro_f1",
                    "required_prediction_fields": ["logits"],
                }
            ],
        },
        "task": {
            "id": "task/emotion",
            "content_hash": CONTENT_HASH,
            "prediction_unit": "trial",
            "target_type": "multiclass",
            "classes": {"negative": 0, "neutral": 1, "positive": 2},
            "required_metadata": ["subject_id"],
        },
    }


def load_case(fixture: str) -> dict[str, object]:
    documents = deepcopy(_documents())
    method_inputs = documents["method"]["input_requirements"]
    assert isinstance(method_inputs, dict)
    if fixture == "axis_transpose":
        method_inputs["signal"] = {
            "field": "signal",
            "adaptation": "axis_transpose",
            "parameters": {
                "source_axes": ["batch", "time", "channel"],
                "target_axes": ["batch", "channel", "time"],
            },
        }
    elif fixture == "resample":
        method_inputs["signal"] = {
            "field": "signal",
            "adaptation": "resample",
            "parameters": {"source_hz": 128, "target_hz": 256},
        }
    elif fixture == "missing_subject_id":
        documents["data"]["canonical_outputs"].remove("subject_id")
    elif fixture != "exact":
        raise AssertionError(f"unknown fixture: {fixture}")
    return {
        "data": DataModuleSpec.model_validate(documents["data"]),
        "method": MethodSpec.model_validate(documents["method"]),
        "evaluation": EvaluationSpec.model_validate(documents["evaluation"]),
        "task": TaskContract.model_validate(documents["task"]),
    }


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("exact", CompatibilityState.COMPATIBLE),
        ("axis_transpose", CompatibilityState.ADAPTABLE),
        ("resample", CompatibilityState.REQUIRES_DECISION),
        ("missing_subject_id", CompatibilityState.INCOMPATIBLE),
    ],
)
def test_compiler_returns_deterministic_verdict(
    fixture: str, expected: CompatibilityState
) -> None:
    """Catches incorrect severity aggregation or nondeterministic report hashing."""
    report = compile_compatibility(**load_case(fixture))

    assert report.state is expected
    assert report.contract_hash == compile_compatibility(
        **load_case(fixture)
    ).contract_hash
    assert report.contract_hash.startswith("sha256:")
    assert report.findings


def test_findings_are_field_specific_and_stably_ordered() -> None:
    """Catches empty compatible reports and iteration-order-dependent findings."""
    first = load_case("exact")
    second = load_case("exact")
    method = second["method"]
    assert isinstance(method, MethodSpec)
    second["method"] = method.model_copy(
        update={
            "input_requirements": {
                "z_aux": {"field": "sample_id"},
                "signal": {"field": "signal"},
            }
        }
    )
    first_method = first["method"]
    assert isinstance(first_method, MethodSpec)
    first["method"] = first_method.model_copy(
        update={
            "input_requirements": {
                "signal": {"field": "signal"},
                "z_aux": {"field": "sample_id"},
            }
        }
    )

    first_report = compile_compatibility(**first)
    second_report = compile_compatibility(**second)

    assert first_report.contract_hash == second_report.contract_hash
    assert first_report.findings == second_report.findings
    assert all(finding.field and finding.message for finding in first_report.findings)


def test_nested_parameter_insertion_order_does_not_change_the_report() -> None:
    """Catches nested adapter mappings leaking insertion order into the hash."""
    first = load_case("exact")
    second = load_case("exact")
    first_method = first["method"]
    second_method = second["method"]
    assert isinstance(first_method, MethodSpec)
    assert isinstance(second_method, MethodSpec)
    first["method"] = first_method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": "axis_transpose",
                    "parameters": {
                        "source_axes": ["batch", "time", "channel"],
                        "target_axes": ["batch", "channel", "time"],
                    },
                }
            }
        }
    )
    second["method"] = second_method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": "axis_transpose",
                    "parameters": {
                        "target_axes": ["batch", "channel", "time"],
                        "source_axes": ["batch", "time", "channel"],
                    },
                }
            }
        }
    )

    first_report = compile_compatibility(**first)
    second_report = compile_compatibility(**second)

    assert first_report == second_report


@pytest.mark.parametrize(
    "requirement",
    [
        {"field": "signal", "normalization_fit_scope": "all_samples"},
        {"field": "signal", "parameters": {"target_hz": 256}},
    ],
)
def test_requirement_envelope_rejects_undeclared_semantics(
    requirement: dict[str, object]
) -> None:
    """Catches semantic or parameter keys bypassing explicit adaptation review."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={"input_requirements": {"signal": requirement}}
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert any(
        finding.field == "method.input_requirements.signal"
        for finding in report.findings
    )


@pytest.mark.parametrize(
    ("kind", "parameters"),
    [
        (
            "axis_transpose",
            {
                "source_axes": ["batch", "time", "channel"],
                "target_axes": ["batch", "channel", "time"],
            },
        ),
        ("add_batch_dimension", {"axis": "batch"}),
        (
            "safe_dtype_conversion",
            {"source_dtype": "float32", "target_dtype": "float64"},
        ),
        (
            "variable_length_padding_mask",
            {"variable_length": True, "mask_field": "attention_mask"},
        ),
        (
            "field_rename",
            {"source_field": "signal", "target_field": "inputs"},
        ),
        (
            "structural_wrap",
            {"wrapper": "mapping", "value_semantics_unchanged": True},
        ),
    ],
)
def test_only_declared_mechanical_adapters_are_generated(
    kind: str, parameters: dict[str, object]
) -> None:
    """Catches approved mechanical transformations being escalated or omitted."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": kind,
                    "parameters": parameters,
                }
            }
        }
    )

    report = compile_compatibility(**case)

    adapters = tuple(
        adapter for finding in report.findings for adapter in finding.adapters
    )
    assert report.state is CompatibilityState.ADAPTABLE
    assert [adapter.kind.value for adapter in adapters] == [kind]
    assert all(adapter.api_version == "ai4sota/v1" for adapter in adapters)


def test_returned_adapter_parameters_are_deeply_immutable() -> None:
    """Catches a caller mutating adapter semantics after the report is hashed."""
    report = compile_compatibility(**load_case("axis_transpose"))
    adapter = next(
        adapter for finding in report.findings for adapter in finding.adapters
    )
    parameters = cast(Any, adapter.parameters)

    with pytest.raises(TypeError):
        parameters["source_axes"][0] = "frequency"
    with pytest.raises(TypeError):
        parameters["target_axes"] = ("time", "channel", "batch")

    assert report.contract_hash == (
        "sha256:2dc4f6be2a970bd92c596cd2a405e6a6337605de5cc4c971062d4cd4bdfd0b1b"
    )


@pytest.mark.parametrize(
    ("adaptation", "parameters"),
    [
        ("resample", {"declared": True}),
        ("channel_set_change", {"declared": True}),
        ("label_mapping", {"declared": True}),
        ("sample_membership", {"declared": True}),
        ("normalization_fit_scope", {"declared": True}),
        ("evaluation_protocol", {"declared": True}),
        ("task_semantics", {"declared": True}),
        ("windowing", {"declared": True}),
        (
            "axis_transpose",
            {
                "source_axes": ["batch", "time", "channel"],
                "target_axes": ["batch", "frequency", "time"],
            },
        ),
        (
            "safe_dtype_conversion",
            {"source_dtype": "float64", "target_dtype": "float32"},
        ),
    ],
)
def test_scientific_transformations_require_a_decision(
    adaptation: str, parameters: dict[str, object]
) -> None:
    """Catches scientific choices being silently emitted as mechanical adapters."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": adaptation,
                    "parameters": parameters,
                }
            }
        }
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.REQUIRES_DECISION
    assert not any(finding.adapters for finding in report.findings)


@pytest.mark.parametrize(
    ("adaptation", "parameters"),
    [
        ("safe_dtype_conversion", {}),
        (
            "variable_length_padding_mask",
            {"variable_length": False, "mask_field": "attention_mask"},
        ),
        (
            "structural_wrap",
            {
                "wrapper": "mapping",
                "value_semantics_unchanged": True,
                "fill_value": float("nan"),
            },
        ),
        (
            "field_rename",
            {"source_field": "absent", "target_field": "inputs"},
        ),
        (
            "axis_transpose",
            {
                "source_axes": ["batch", "time", "channel"],
                "target_axes": ["batch", "channel", "time"],
                "target_hz": 256,
            },
        ),
        ("unregistered_transform", {}),
    ],
)
def test_unsafe_or_unknown_adapter_declarations_are_incompatible(
    adaptation: str, parameters: dict[str, object]
) -> None:
    """Catches malformed whitelist claims bypassing the compatibility gate."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": adaptation,
                    "parameters": parameters,
                }
            }
        }
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert not any(finding.adapters for finding in report.findings)


def test_missing_prediction_capability_is_incompatible() -> None:
    """Catches an evaluator requesting output the method cannot produce."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(update={"output_capabilities": ("labels",)})

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert any(finding.field == "evaluation.required_predictions" for finding in report.findings)


def test_task_contract_hash_mismatch_requires_a_decision() -> None:
    """Catches unresolved task semantics being treated as an exact match."""
    case = load_case("exact")
    evaluation = case["evaluation"]
    assert isinstance(evaluation, EvaluationSpec)
    case["evaluation"] = evaluation.model_copy(
        update={"task_contract_hash": OTHER_HASH}
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.REQUIRES_DECISION
    assert any(finding.field == "evaluation.task_contract_hash" for finding in report.findings)


def test_explicitly_unsupported_task_contract_is_incompatible() -> None:
    """Catches a missing Method task capability being presented as resolvable."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={"task_contracts": ("task/regression",)}
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert any(finding.field == "method.task_contracts" for finding in report.findings)


def test_missing_method_task_capabilities_are_incompatible() -> None:
    """Catches an empty task capability list being treated as an implicit wildcard."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(update={"task_contracts": ()})

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert any(finding.field == "method.task_contracts" for finding in report.findings)


@pytest.mark.parametrize("axis", ["", "   ", 0, -1, 99])
def test_batch_dimension_requires_a_non_empty_semantic_axis(axis: object) -> None:
    """Catches ambiguous or unbounded numeric Batch-axis declarations."""
    case = load_case("exact")
    method = case["method"]
    assert isinstance(method, MethodSpec)
    case["method"] = method.model_copy(
        update={
            "input_requirements": {
                "signal": {
                    "field": "signal",
                    "adaptation": "add_batch_dimension",
                    "parameters": {"axis": axis},
                }
            }
        }
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert not any(finding.adapters for finding in report.findings)


def test_incompatible_dominates_a_scientific_decision() -> None:
    """Catches aggregate severity depending on rule or fixture ordering."""
    case = load_case("resample")
    data = case["data"]
    assert isinstance(data, DataModuleSpec)
    case["data"] = data.model_copy(
        update={
            "canonical_outputs": tuple(
                field for field in data.canonical_outputs if field != "subject_id"
            )
        }
    )

    report = compile_compatibility(**case)

    assert report.state is CompatibilityState.INCOMPATIBLE
    assert {finding.state for finding in report.findings} >= {
        CompatibilityState.REQUIRES_DECISION,
        CompatibilityState.INCOMPATIBLE,
    }


def test_compatibility_models_reject_unknown_fields() -> None:
    """Catches output contracts silently accepting unversioned data."""
    with pytest.raises(ValidationError):
        MechanicalAdapterSpec(
            kind=AdapterKind.ADD_BATCH_DIMENSION,
            field="method.input_requirements.signal",
            parameters={"axis": 0},
            unsupported=True,
        )
    with pytest.raises(ValidationError):
        CompatibilityReport(
            state=CompatibilityState.COMPATIBLE,
            findings=(),
            contract_hash=CONTENT_HASH,
        )


def test_report_rejects_tampered_aggregate_state() -> None:
    """Catches deserialized reports whose verdict does not match their findings."""
    document = compile_compatibility(**load_case("exact")).model_dump(mode="json")
    document["state"] = CompatibilityState.INCOMPATIBLE

    with pytest.raises(ValidationError, match="state"):
        CompatibilityReport.model_validate(document)


def test_report_rejects_tampered_contract_hash() -> None:
    """Catches deserialized reports whose findings no longer match their hash."""
    document = compile_compatibility(**load_case("exact")).model_dump(mode="json")
    document["contract_hash"] = OTHER_HASH

    with pytest.raises(ValidationError, match="contract_hash"):
        CompatibilityReport.model_validate(document)


def test_exact_report_hash_matches_an_independent_literal() -> None:
    """Catches drift in canonical finding content or hash serialization."""
    report = compile_compatibility(**load_case("exact"))

    assert report.contract_hash == (
        "sha256:1cc7c2df9fef7d7e3c1894aa852ec3f9b126aef2deb191870b8b4f12c6490202"
    )
