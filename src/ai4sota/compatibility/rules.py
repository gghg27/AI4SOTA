"""Pure, stably ordered scientific compatibility rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from ai4sota.domain import (
    CompatibilityState,
    DataModuleSpec,
    EvaluationSpec,
    MethodSpec,
    TaskContract,
)

from .models import (
    AdapterKind,
    CompatibilityFinding,
    MechanicalAdapterSpec,
    json_parameters,
)

Rule = Callable[
    [DataModuleSpec, MethodSpec, EvaluationSpec, TaskContract],
    CompatibilityFinding,
]

_DECISION_ADAPTATIONS = frozenset(
    {
        "resample",
        "channel_set_change",
        "label_change",
        "label_mapping",
        "sample_membership",
        "normalization_fit_scope",
        "evaluation_protocol",
        "task_semantics",
        "windowing",
        "missing_values",
    }
)

_STATE_RANK = {
    CompatibilityState.COMPATIBLE: 0,
    CompatibilityState.ADAPTABLE: 1,
    CompatibilityState.REQUIRES_DECISION: 2,
    CompatibilityState.INCOMPATIBLE: 3,
}

_MECHANICAL_PARAMETER_KEYS = {
    AdapterKind.AXIS_TRANSPOSE: frozenset({"source_axes", "target_axes"}),
    AdapterKind.ADD_BATCH_DIMENSION: frozenset({"axis"}),
    AdapterKind.SAFE_DTYPE_CONVERSION: frozenset(
        {"source_dtype", "target_dtype"}
    ),
    AdapterKind.VARIABLE_LENGTH_PADDING_MASK: frozenset(
        {"variable_length", "mask_field"}
    ),
    AdapterKind.FIELD_RENAME: frozenset({"source_field", "target_field"}),
    AdapterKind.STRUCTURAL_WRAP: frozenset(
        {"wrapper", "value_semantics_unchanged"}
    ),
}


def evaluate_task_contracts(
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    task: TaskContract,
) -> CompatibilityFinding:
    mismatches: list[str] = []
    if data.task_contract_hash != task.content_hash:
        mismatches.append("data.task_contract_hash")
    if evaluation.task_contract_hash != task.content_hash:
        mismatches.append("evaluation.task_contract_hash")
    if method.task_contracts and task.id not in method.task_contracts:
        return CompatibilityFinding(
            rule="task_contract_identity",
            field="method.task_contracts",
            state=CompatibilityState.INCOMPATIBLE,
            message="Method does not declare support for the active TaskContract.",
        )
    if mismatches:
        field = mismatches[0]
        return CompatibilityFinding(
            rule="task_contract_identity",
            field=field,
            state=CompatibilityState.REQUIRES_DECISION,
            message=(
                f"{field} does not resolve to the active TaskContract; "
                "task semantics require a researcher decision."
            ),
        )
    return CompatibilityFinding(
        rule="task_contract_identity",
        field="task.content_hash",
        state=CompatibilityState.COMPATIBLE,
        message="Data, Method, and Evaluation accept the active TaskContract.",
    )


def evaluate_method_inputs(
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    task: TaskContract,
) -> CompatibilityFinding:
    del evaluation, task
    outputs = set(data.canonical_outputs)
    states: list[CompatibilityState] = []
    details: list[str] = []
    adapters: list[MechanicalAdapterSpec] = []
    fields: list[str] = []
    for requirement_name in sorted(method.input_requirements):
        field_path = f"method.input_requirements.{requirement_name}"
        fields.append(field_path)
        requirement = method.input_requirements[requirement_name]
        source_field, adaptation, parameters, error = _parse_requirement(
            requirement_name, requirement
        )
        if error is not None:
            states.append(CompatibilityState.INCOMPATIBLE)
            details.append(f"{field_path}: {error}")
            continue
        if source_field not in outputs:
            states.append(CompatibilityState.INCOMPATIBLE)
            details.append(
                f"{field_path}: Data does not supply canonical field {source_field!r}"
            )
            continue
        if adaptation is None:
            states.append(CompatibilityState.COMPATIBLE)
            details.append(f"{field_path}: supplied directly as {source_field!r}")
            continue
        state, detail, adapter = _classify_adaptation(
            adaptation, field_path, source_field, parameters
        )
        states.append(state)
        details.append(f"{field_path}: {detail}")
        if adapter is not None:
            adapters.append(adapter)
    if not states:
        return CompatibilityFinding(
            rule="method_inputs",
            field="method.input_requirements",
            state=CompatibilityState.COMPATIBLE,
            message="Method declares no required Data input fields.",
        )
    state = max(states, key=_STATE_RANK.__getitem__)
    return CompatibilityFinding(
        rule="method_inputs",
        field=next(
            field
            for field, item_state in zip(fields, states, strict=True)
            if item_state is state
        ),
        state=state,
        message="; ".join(details),
        adapters=tuple(adapters),
    )


def evaluate_prediction_capabilities(
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    task: TaskContract,
) -> CompatibilityFinding:
    del data, task
    required = set(evaluation.required_predictions)
    required.update(
        field
        for metric in evaluation.metrics
        for field in metric.required_prediction_fields
    )
    missing = sorted(required.difference(method.output_capabilities))
    if missing:
        return CompatibilityFinding(
            rule="prediction_capabilities",
            field="evaluation.required_predictions",
            state=CompatibilityState.INCOMPATIBLE,
            message=f"Method lacks required prediction capabilities: {', '.join(missing)}.",
        )
    supplied = ", ".join(sorted(required))
    return CompatibilityFinding(
        rule="prediction_capabilities",
        field="evaluation.required_predictions",
        state=CompatibilityState.COMPATIBLE,
        message=f"Method supplies all required prediction fields: {supplied}.",
    )


def evaluate_required_metadata(
    data: DataModuleSpec,
    method: MethodSpec,
    evaluation: EvaluationSpec,
    task: TaskContract,
) -> CompatibilityFinding:
    del method
    required = set(task.required_metadata)
    required.update(evaluation.required_metadata)
    required.add(evaluation.protocol.group_by)
    missing = sorted(required.difference(data.canonical_outputs))
    if missing:
        return CompatibilityFinding(
            rule="required_metadata",
            field="data.canonical_outputs",
            state=CompatibilityState.INCOMPATIBLE,
            message=f"Data lacks required metadata or identifiers: {', '.join(missing)}.",
        )
    supplied = ", ".join(sorted(required))
    return CompatibilityFinding(
        rule="required_metadata",
        field="data.canonical_outputs",
        state=CompatibilityState.COMPATIBLE,
        message=f"Data supplies all required metadata and identifiers: {supplied}.",
    )


def _parse_requirement(
    requirement_name: str, requirement: Any
) -> tuple[str, str | None, dict[str, Any], str | None]:
    if isinstance(requirement, str):
        if requirement.strip():
            return requirement, None, {}, None
        return requirement_name, None, {}, "field must be a non-empty string"
    if not isinstance(requirement, Mapping):
        return requirement_name, None, {}, "requirement must be a field name or mapping"
    field = requirement.get("field", requirement_name)
    if not isinstance(field, str) or not field.strip():
        return requirement_name, None, {}, "field must be a non-empty string"
    adaptation = requirement.get("adaptation")
    if adaptation is not None and (
        not isinstance(adaptation, str) or not adaptation.strip()
    ):
        return field, None, {}, "adaptation must be a non-empty string"
    raw_parameters = requirement.get("parameters", {})
    parameters = json_parameters(raw_parameters)
    if parameters is None:
        return field, adaptation, {}, "parameters must contain JSON-compatible values"
    return field, adaptation, parameters, None


def _classify_adaptation(
    adaptation: str,
    field_path: str,
    source_field: str,
    parameters: dict[str, Any],
) -> tuple[CompatibilityState, str, MechanicalAdapterSpec | None]:
    if adaptation in _DECISION_ADAPTATIONS:
        return (
            CompatibilityState.REQUIRES_DECISION,
            f"{adaptation!r} changes scientific semantics and requires a decision",
            None,
        )
    try:
        kind = AdapterKind(adaptation)
    except ValueError:
        return (
            CompatibilityState.INCOMPATIBLE,
            f"{adaptation!r} is not an approved mechanical adapter",
            None,
        )
    unexpected = sorted(set(parameters).difference(_MECHANICAL_PARAMETER_KEYS[kind]))
    if unexpected:
        return (
            CompatibilityState.INCOMPATIBLE,
            f"{adaptation!r} has unsupported parameters: {', '.join(unexpected)}",
            None,
        )
    problem = _validate_mechanical_adapter(kind, source_field, parameters)
    if problem is not None:
        state, message = problem
        return state, message, None
    return (
        CompatibilityState.ADAPTABLE,
        f"{adaptation!r} is an approved mechanical adaptation",
        MechanicalAdapterSpec(kind=kind, field=field_path, parameters=parameters),
    )


def _validate_mechanical_adapter(
    kind: AdapterKind, supplied_field: str, parameters: dict[str, Any]
) -> tuple[CompatibilityState, str] | None:
    if kind is AdapterKind.AXIS_TRANSPOSE:
        source = _string_sequence(parameters.get("source_axes"))
        target = _string_sequence(parameters.get("target_axes"))
        if source is None or target is None:
            return (
                CompatibilityState.INCOMPATIBLE,
                "axis_transpose requires source_axes and target_axes metadata",
            )
        if len(set(source)) != len(source) or len(set(target)) != len(target):
            return (
                CompatibilityState.INCOMPATIBLE,
                "axis_transpose requires unique semantic axis declarations",
            )
        if set(source) != set(target):
            return (
                CompatibilityState.REQUIRES_DECISION,
                "axis sets differ; changing signal dimensions requires a decision",
            )
    elif kind is AdapterKind.ADD_BATCH_DIMENSION:
        axis = parameters.get("axis")
        if not isinstance(axis, (int, str)) or isinstance(axis, bool):
            return (
                CompatibilityState.INCOMPATIBLE,
                "add_batch_dimension requires an integer or semantic axis",
            )
    elif kind is AdapterKind.SAFE_DTYPE_CONVERSION:
        source = parameters.get("source_dtype")
        target = parameters.get("target_dtype")
        if not _non_empty_string(source) or not _non_empty_string(target):
            return (
                CompatibilityState.INCOMPATIBLE,
                "safe_dtype_conversion requires source_dtype and target_dtype metadata",
            )
        try:
            safe = np.can_cast(np.dtype(source), np.dtype(target), casting="safe")
        except (TypeError, ValueError):
            return (
                CompatibilityState.INCOMPATIBLE,
                "safe_dtype_conversion requires recognized NumPy dtypes",
            )
        if not safe:
            return (
                CompatibilityState.REQUIRES_DECISION,
                "dtype conversion may lose values or precision and requires a decision",
            )
    elif kind is AdapterKind.VARIABLE_LENGTH_PADDING_MASK:
        if parameters.get("variable_length") is not True or not _non_empty_string(
            parameters.get("mask_field")
        ):
            return (
                CompatibilityState.INCOMPATIBLE,
                (
                    "variable_length_padding_mask requires variable_length=true "
                    "and a mask_field"
                ),
            )
    elif kind is AdapterKind.FIELD_RENAME:
        source = parameters.get("source_field")
        target = parameters.get("target_field")
        if (
            not _non_empty_string(source)
            or not _non_empty_string(target)
            or source != supplied_field
            or source == target
            or "value_transform" in parameters
        ):
            return (
                CompatibilityState.INCOMPATIBLE,
                "field_rename must change only the supplied field name",
            )
    elif kind is AdapterKind.STRUCTURAL_WRAP:
        if not _non_empty_string(
            parameters.get("wrapper")
        ) or parameters.get("value_semantics_unchanged") is not True:
            return (
                CompatibilityState.INCOMPATIBLE,
                "structural_wrap must explicitly preserve value semantics",
            )
    return None


def _string_sequence(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if not all(_non_empty_string(item) for item in value):
        return None
    return tuple(str(item) for item in value)


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


RULES: tuple[Rule, ...] = (
    evaluate_task_contracts,
    evaluate_method_inputs,
    evaluate_prediction_capabilities,
    evaluate_required_metadata,
)

__all__ = ["RULES", "Rule"]
