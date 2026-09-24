"""Text rendering of public runtime values: read attributes, never infer missing ones."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

UNKNOWN = "unknown (not recorded)"


def value_text(value: object) -> str:
    """Render one value as the JSON the runtime override grammar accepts."""
    return json.dumps(value, sort_keys=True, default=str)


def _problems(label: str, problems: Iterable[Any]) -> list[str]:
    return [f"- {label}: {problem}" for problem in problems]


def _mapping(value: Mapping[str, Any] | None, *, empty: str = "none") -> str:
    if value is None:
        return UNKNOWN
    if not value:
        return empty
    return ", ".join(f"{key}={value_text(item)}" for key, item in value.items())


def plan_summary(plan: Any) -> str:
    """Identity, order, scope and structural problems of a ``ResolvedPipelinePlan``."""
    order = "cycle (no order)" if plan.order is None else " -> ".join(plan.order)
    lines = [
        f"preset: {plan.preset}",
        f"config digest: {plan.config_digest}",
        f"plan digest: {plan.plan_digest}",
        f"order: {order}",
        f"disabled stages: {', '.join(plan.disabled_stages) or 'none'}",
        f"run stages: {', '.join(plan.run_stages) or 'none'}",
    ]
    if plan.selections is not None:
        lines.append(f"selections: {value_text(plan.selections)}")
    if plan.problems:
        lines.append("Plan problems:")
        lines.extend(_problems("problem", plan.problems))
    else:
        lines.append("Plan problems: none")
    return "\n".join(lines)


def stage_row(stage: Any) -> tuple[str, ...]:
    """One table row of a ``RuntimePlanStage``."""
    inputs = "; ".join(
        f"{item.name}:{item.contract}<-{item.source}"
        + (" (optional)" if item.optional else "")
        + (" (multiple)" if item.multiple else "")
        for item in stage.inputs
    )
    backends = "; ".join(
        f"{component}={'none' if backend is None else backend}"
        for component, backend in stage.backends.items()
    )
    available = "yes" if stage.available else f"no: {stage.unavailable_reason}"
    return (
        stage.stage_id,
        stage.capability,
        "yes" if stage.in_scope else "no",
        available,
        inputs or "none",
        stage.output or "none",
        backends or "none",
        ", ".join(stage.provided) or "none",
        stage.config_digest,
    )


def edit_row(edit: Any) -> tuple[str, ...]:
    """One table row of a ``RuntimeEdit``."""
    allowed = "any" if edit.allowed is None else " | ".join(value_text(x) for x in edit.allowed)
    return (edit.path, edit.kind, value_text(edit.current), allowed)


def preflight_text(report: Any) -> str:
    """Everything a ``RuntimePreflightReport`` states, blocking problems first."""
    lines = ["Preflight: OK" if report.ok else "Preflight: BLOCKED"]
    lines.extend(_problems("problem", report.problems))
    lines.extend(f"- warning: {warning}" for warning in report.warnings)
    lines.append(f"config digest: {report.config_digest}")
    lines.append(f"plan digest: {report.plan_digest}")
    lines.append(f"stages: {', '.join(report.stages) or 'none'}")
    lines.append(f"missing executors: {', '.join(report.missing_executors) or 'none'}")
    for stage, ids in report.provided.items():
        lines.append(f"provided {stage}: {', '.join(ids)}")
    for stage, output in report.outputs.items():
        lines.append(f"output {stage}: {output or 'none'}")
    for stage, decision in report.predicted_reuse.items():
        lines.append(f"predicted reuse {stage}: {value_text(decision)}")
    return "\n".join(lines)


def event_text(event: Any) -> str:
    """One persisted ``ExecutionEvent`` line."""
    stage = event.stage_id or "run"
    data = value_text(dict(event.data)) if event.data else ""
    return f"#{event.sequence} {event.time} {event.kind} [{stage}] {data}".rstrip()


def execution_text(result: Any) -> str:
    """Status and identity of a ``RuntimeExecutionResult``, read from its record."""
    record = result.record
    lines = [
        f"Status: {result.status}",
        f"run_id: {result.run_id}",
        f"directory: {record.directory}",
    ]
    if record.failure is not None:
        lines.append(f"failure: {value_text(record.failure)}")
    lines.extend(_problems("blocked", record.blocked_problems))
    lines.extend(f"- event sink error (presentation only): {item}" for item in result.event_errors)
    return "\n".join(lines)


def summary_row(summary: Any) -> tuple[str, ...]:
    """One table row of a ``RuntimeRunSummary``; unreadable runs keep their error."""
    if not summary.readable:
        return (summary.dataset, summary.run_id, "no", "unreadable", "", "", "", "", summary.error)
    return (
        summary.dataset,
        summary.run_id,
        "yes",
        summary.status or "",
        "yes" if summary.interrupted else "no",
        summary.created_at or "",
        summary.updated_at or "",
        summary.resumed_from or "",
        summary.failure_category or "",
    )


def run_stage_row(stage: Any) -> tuple[str, ...]:
    """One table row of a ``RuntimeRunStage``; absent facts stay unknown."""
    inputs = (
        UNKNOWN
        if stage.inputs is None
        else "; ".join(f"{name}={', '.join(ids) or 'none'}" for name, ids in stage.inputs.items())
        or "none"
    )
    output = UNKNOWN if stage.output is None else value_text(dict(stage.output))
    decision = "none" if stage.decision is None else value_text(dict(stage.decision))
    elapsed = UNKNOWN if stage.elapsed_s is None else f"{stage.elapsed_s:.3f}s"
    return (stage.stage_id, stage.outcome, inputs, output, decision, elapsed)


def record_text(record: Any) -> str:
    """Every field of a ``RuntimeRunRecord`` exactly as persisted."""
    lines = [
        f"run_id: {record.run_id}",
        f"directory: {record.directory}",
        f"status: {record.status}",
        f"interrupted: {'yes' if record.interrupted else 'no'}",
        f"created_at: {record.created_at}",
        f"updated_at: {record.updated_at}",
        f"config digest: {record.config_digest}",
        f"plan digest: {record.plan_digest}",
        f"targets: {', '.join(record.targets) or 'none'}",
        f"backends: {_mapping(record.backends)}",
        "provided: "
        + (
            "; ".join(f"{stage}={', '.join(ids)}" for stage, ids in record.provided.items())
            or "none"
        ),
        f"selections: {'none' if record.selections is None else value_text(record.selections)}",
        f"resumed_from: {record.resumed_from or 'none'}",
        f"resume: {'none' if record.resume is None else value_text(record.resume)}",
        f"failure: {'none' if record.failure is None else value_text(record.failure)}",
        f"code identity: {record.code_identity or UNKNOWN}",
        f"environment: {_mapping(record.environment, empty=UNKNOWN)}",
    ]
    if record.blocked_problems:
        lines.append("Blocked by:")
        lines.extend(_problems("problem", record.blocked_problems))
    if record.notes:
        lines.append("Runtime notes:")
        lines.extend(f"- {note}" for note in record.notes)
    lines.append("Events:")
    lines.extend(f"  {event_text(event)}" for event in record.events)
    return "\n".join(lines)
