"""Test doubles shaped like public ``contextmap.runtime`` values, for CI without the core."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from contextmap_tui.runtime import (
    FakeRuntimeGateway,
    RuntimePipelineResolution,
    StageCapability,
)


class Problem:
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def edit(path: str, kind: str, allowed: tuple[Any, ...] | None, current: Any) -> SimpleNamespace:
    return SimpleNamespace(path=path, kind=kind, allowed=allowed, current=current)


def plan(
    *,
    digest: str = "sha256:plan-a",
    config_digest: str = "sha256:config-a",
    perception_backend: str | None = None,
    point_enabled: bool = False,
    problems: tuple[Problem, ...] = (),
) -> SimpleNamespace:
    ingestion = SimpleNamespace(
        stage_id="ingestion",
        capability="ingestion",
        optional=False,
        available=True,
        unavailable_reason="",
        backends={"ingestion.source_adapter": "ros1_bag"},
        inputs=(),
        output="SequenceArtifact",
        config_digest="sha256:stage-ingestion",
        in_scope=True,
        provided=(),
    )
    perception = SimpleNamespace(
        stage_id="visual_perception",
        capability="visual_perception",
        optional=False,
        available=True,
        unavailable_reason="",
        backends={
            "visual_perception.region_discovery": perception_backend,
            "visual_perception.dense_features": None,
        },
        inputs=(
            SimpleNamespace(
                name="sequence",
                contract="SequenceArtifact",
                source="ingestion",
                optional=False,
                multiple=False,
            ),
        ),
        output="VisualPerceptionArtifact",
        config_digest="sha256:stage-perception",
        in_scope=True,
        provided=(),
    )
    order = ("ingestion", "visual_perception")
    return SimpleNamespace(
        preset="canonical/1",
        config_digest=config_digest,
        plan_digest=digest,
        order=order,
        stages=(ingestion, perception),
        disabled_stages=() if point_enabled else ("point_representation",),
        run_stages=order,
        selections=None,
        problems=problems,
        editable=(
            edit("pipeline.stages.point_representation", "toggle", (True, False), point_enabled),
            edit(
                "components.visual_perception.region_discovery.backend",
                "choice",
                ("florence2", "sam2", "sam3"),
                perception_backend,
            ),
            edit(
                "components.entity_resolution.appearance.backend",
                "choice",
                ("entity-appearance-comparison-v1", None),
                None,
            ),
            edit("resources.device", "text", None, None),
            edit("inputs.selections.ingestion", "selection", None, None),
        ),
    )


def resolution(**kwargs: Any) -> RuntimePipelineResolution:
    built = plan(**kwargs)
    return RuntimePipelineResolution(
        profile="canonical/1",
        files=(),
        overrides=(),
        config=SimpleNamespace(digest=built.config_digest),
        plan=built,
    )


def preflight(*, ok: bool = True, problems: tuple[Problem, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        ok=ok,
        problems=problems,
        warnings=("stage 'ingestion': 'latest' resolved to 'seq-1'",),
        config_digest="sha256:config-a",
        plan_digest="sha256:plan-a",
        stages=("ingestion", "visual_perception"),
        provided={},
        outputs={"ingestion": "SequenceArtifact", "visual_perception": "VisualPerceptionArtifact"},
        predicted_reuse={"ingestion": {"kind": "reused", "reason": "identical identity"}},
        missing_executors=() if ok else ("visual_perception",),
    )


def event(sequence: int, kind: str, stage_id: str | None, **data: Any) -> SimpleNamespace:
    return SimpleNamespace(
        sequence=sequence,
        time=f"2026-09-23T00:00:0{sequence}Z",
        kind=kind,
        stage_id=stage_id,
        data=data,
    )


def run_stage(
    stage_id: str,
    outcome: str,
    *,
    inputs: dict[str, tuple[str, ...]] | None = None,
    output: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    elapsed_s: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        stage_id=stage_id,
        outcome=outcome,
        inputs=inputs,
        output=output,
        decision=decision,
        elapsed_s=elapsed_s,
    )


SEQUENCE_OUTPUT = {
    "stage_id": "ingestion",
    "contract": "SequenceArtifact",
    "artifact_id": "seq-1",
    "content_hash": "sha256:seq",
    "location": "corridor/run-0001/ingestion",
}


def record(
    run_id: str = "run-0001",
    *,
    dataset: str = "corridor",
    status: str = "completed",
    stages: tuple[SimpleNamespace, ...] | None = None,
    **fields: Any,
) -> SimpleNamespace:
    values: dict[str, Any] = {
        "run_id": run_id,
        "directory": f"/workspace/{dataset}/{run_id}",
        "status": status,
        "interrupted": False,
        "config_digest": "sha256:config-a",
        "plan_digest": "sha256:plan-a",
        "backends": {"ingestion.source_adapter": "ros1_bag"},
        "targets": ("ingestion", "visual_perception"),
        "provided": {},
        "stages": stages
        if stages is not None
        else (
            run_stage("ingestion", "completed", inputs={}, output=SEQUENCE_OUTPUT, elapsed_s=1.5),
            run_stage(
                "visual_perception",
                "reused",
                output={"artifact_id": "vp-1"},
                decision={"kind": "reused", "reason": "identical identity"},
            ),
        ),
        "selections": None,
        "resumed_from": None,
        "resume": None,
        "failure": None,
        "blocked_problems": (),
        "code_identity": "git:abc",
        "environment": {"python": "3.11"},
        "created_at": "2026-09-23T00:00:00Z",
        "updated_at": "2026-09-23T00:00:09Z",
        "events": (event(1, "run_planned", None), event(2, "run_completed", None)),
        "notes": (),
    }
    values.update(fields)
    return SimpleNamespace(**values)


def summary(
    run_id: str = "run-0001", *, dataset: str = "corridor", readable: bool = True, **fields: Any
) -> SimpleNamespace:
    values: dict[str, Any] = {
        "run_id": run_id,
        "dataset": dataset,
        "readable": readable,
        "status": "completed" if readable else None,
        "interrupted": False if readable else None,
        "created_at": "2026-09-23T00:00:00Z" if readable else None,
        "updated_at": "2026-09-23T00:00:09Z" if readable else None,
        "resumed_from": None,
        "failure_category": None,
        "error": None if readable else "run.json is not valid JSON",
    }
    values.update(fields)
    return SimpleNamespace(**values)


def gateway(**kwargs: Any) -> FakeRuntimeGateway:
    defaults: dict[str, Any] = {
        "stage_capabilities": (
            StageCapability("ingestion", "Ingestion", True, False),
            StageCapability("visual_perception", "Visual Perception", True, False),
        ),
        "resolution": resolution(),
        "preflight_report": preflight(),
        "execution_result": SimpleNamespace(
            status="completed", run_id="run-0001", record=record(), event_errors=()
        ),
        "events": (
            event(1, "run_planned", None),
            event(2, "stage_completed", "ingestion"),
            event(3, "stage_reused", "visual_perception"),
            event(4, "run_completed", None),
        ),
        "run_summaries": (summary(),),
        "run_records": {"/workspace/corridor/run-0001": record()},
    }
    defaults.update(kwargs)
    return FakeRuntimeGateway(**defaults)
