"""Preflight, execution and run-inspection contract against the public runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from contextmap_tui.integration.runtime import LocalRuntimeGateway
from contextmap_tui.runtime import (
    RuntimeOperationError,
    RuntimePipelineResolution,
    RuntimeReuse,
    RuntimeScope,
)

core = pytest.importorskip("contextmap.runtime")

TARGETS = ("ingestion", "state_estimation")
OVERRIDES = (
    'inputs.sequence="corridor"',
    'components.ingestion.source_adapter.backend="ros1_bag"',
    'components.state_estimation.estimator.backend="external_pose"',
    'components.state_estimation.estimator.external_pose={"reference_frame": "map", '
    '"body_frame": "base"}',
)


class PureStage:
    """Test double owned by the test, standing in for the executor owner."""

    def __init__(self, stage_id: str, contract: str, produced: set[str], fail: bool = False):
        self._stage_id = stage_id
        self._contract = contract
        self._produced = produced
        self.fail = fail

    def execute(self, request: Any) -> Any:
        if self.fail:
            raise RuntimeError(f"{self._stage_id} exploded")
        parts = [request.config_digest] + [
            f"{name}={ref.content_hash}"
            for name, refs in sorted(request.inputs.items())
            for ref in refs
        ]
        digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
        artifact_id = f"{self._stage_id}-{digest[:8]}"
        self._produced.add(artifact_id)
        return core.ArtifactRef(
            stage_id=self._stage_id,
            contract=self._contract,
            artifact_id=artifact_id,
            content_hash=f"sha256:{digest}",
        )


def _gateway(
    workspace: Path, produced: set[str], *, executors: bool = True, fail: str | None = None
) -> tuple[LocalRuntimeGateway, dict[str, PureStage]]:
    stages = {
        "ingestion": PureStage("ingestion", "SequenceArtifact", produced),
        "state_estimation": PureStage(
            "state_estimation",
            "StateEstimationRunArtifact",
            produced,
            fail=fail == "state_estimation",
        ),
    }
    options: dict[str, Any] = {
        "module_available": lambda _name: True,
        "environ": {},
        "verifier": lambda ref: ref.artifact_id in produced,
    }
    if executors:
        options["executors"] = stages
    return LocalRuntimeGateway(workspace_root=workspace, runtime_options=options), stages


def _resolve(gateway: LocalRuntimeGateway, **scope: Any) -> RuntimePipelineResolution:
    return gateway.resolve_pipeline(
        profile="canonical/1",
        overrides=OVERRIDES,
        scope=RuntimeScope(targets=scope.pop("targets", TARGETS), **scope),
    )


def _run(gateway: LocalRuntimeGateway, resolution: RuntimePipelineResolution, **kw: Any) -> Any:
    events: list[Any] = []
    result = gateway.run(
        resolution,
        events=kw.pop("events", events.append),
        cancellation=kw.pop("cancellation", gateway.cancellation()),
        **kw,
    )
    return result, events


def _outcomes(result: Any) -> dict[str, str]:
    return {stage.stage_id: stage.outcome for stage in result.record.stages}


def test_successful_subgraph_run_matches_persisted_record(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    resolution = _resolve(gateway)
    assert resolution.plan.run_stages == TARGETS

    report = gateway.preflight(resolution)
    assert report.ok, report.problems
    assert report.missing_executors == ()

    result, events = _run(gateway, resolution)

    assert result.status == "completed"
    assert _outcomes(result) == {"ingestion": "completed", "state_estimation": "completed"}
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[0].kind == "run_planned" and events[-1].kind == "run_completed"
    (summary,) = gateway.list_runs()
    assert (summary.dataset, summary.run_id, summary.status) == (
        "corridor",
        result.run_id,
        "completed",
    )
    record = gateway.inspect_run(gateway.run_directory(summary) or "")
    assert record == result.record
    assert record.config_digest == resolution.config.digest


def test_missing_executor_blocks_preflight_and_run(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set(), executors=False)
    resolution = _resolve(gateway)

    report = gateway.preflight(resolution)
    assert not report.ok
    assert "ingestion" in report.missing_executors

    result, _ = _run(gateway, resolution)
    assert result.status == "blocked"
    assert result.record.blocked_problems


def test_stage_failure_is_recorded_without_fallback(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set(), fail="state_estimation")
    result, _ = _run(gateway, _resolve(gateway))

    assert result.status == "failed"
    assert _outcomes(result) == {"ingestion": "completed", "state_estimation": "failed"}
    assert result.record.failure is not None
    assert "exploded" in str(result.record.failure)


def test_cooperative_cancellation_stops_between_stages(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    token = gateway.cancellation()

    def cancel_after_ingestion(event: Any) -> None:
        if event.kind == "stage_completed" and event.stage_id == "ingestion":
            token.cancel("stop from test")

    result, _ = _run(gateway, _resolve(gateway), events=cancel_after_ingestion, cancellation=token)

    assert result.status == "cancelled"
    assert _outcomes(result)["state_estimation"] == "pending"


def test_raising_event_sink_does_not_change_the_run(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())

    def broken(event: Any) -> None:
        raise ValueError("renderer bug")

    result, _ = _run(gateway, _resolve(gateway), events=broken)

    assert result.status == "completed"
    assert result.event_errors
    assert "renderer bug" in result.event_errors[0]


def test_reuse_prediction_hit_and_forced_recompute(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path / "ws", set())
    resolution = _resolve(gateway)
    reuse = RuntimeReuse(index=str(tmp_path / "index"), code_identity="tui-test")

    first, _ = _run(gateway, resolution, reuse=reuse)
    assert first.status == "completed"
    report = gateway.preflight(resolution, reuse=reuse)
    assert {item["kind"] for item in report.predicted_reuse.values()} == {"reused"}

    again, _ = _run(gateway, resolution, reuse=reuse)
    assert set(_outcomes(again).values()) == {"reused"}
    reused = next(stage for stage in again.record.stages if stage.stage_id == "ingestion")
    assert reused.decision is not None and reused.decision["kind"] == "reused"

    forced = RuntimeReuse(
        index=reuse.index, code_identity=reuse.code_identity, force=("state_estimation",)
    )
    partial, _ = _run(gateway, resolution, reuse=forced)
    assert _outcomes(partial) == {"ingestion": "reused", "state_estimation": "completed"}


def test_reuse_without_verifier_is_refused_by_runtime(tmp_path: Path) -> None:
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(profile="canonical/1")
    with pytest.raises(RuntimeOperationError, match="verifier"):
        gateway.preflight(resolution, reuse=RuntimeReuse(index=str(tmp_path), code_identity="x"))


def test_resume_is_a_new_run_and_invalid_resume_is_rejected(tmp_path: Path) -> None:
    produced: set[str] = set()
    gateway, stages = _gateway(tmp_path / "ws", produced, fail="state_estimation")
    resolution = _resolve(gateway)
    reuse = RuntimeReuse(index=str(tmp_path / "index"), code_identity="tui-test")
    failed, _ = _run(gateway, resolution, reuse=reuse)
    assert failed.status == "failed"

    with pytest.raises(RuntimeOperationError, match="reuse"):
        _run(gateway, resolution, resume=failed.record.directory)

    stages["state_estimation"].fail = False
    resumed, _ = _run(gateway, resolution, reuse=reuse, resume=failed.record.directory)

    assert resumed.status == "completed"
    assert resumed.run_id != failed.run_id
    assert resumed.record.resumed_from == failed.run_id
    assert _outcomes(resumed)["ingestion"] == "reused"
    assert gateway.inspect_run(failed.record.directory).status == "failed"

    with pytest.raises(RuntimeOperationError):
        _run(gateway, resolution, reuse=reuse, resume=resumed.record.directory)


def test_exact_provided_upstream_artifact_from_recorded_output(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    first, _ = _run(gateway, _resolve(gateway))
    ingestion = next(stage for stage in first.record.stages if stage.stage_id == "ingestion")
    assert ingestion.output is not None

    resolution = _resolve(
        gateway,
        targets=("state_estimation",),
        provided={"ingestion": dict(ingestion.output)},
    )
    planned = {stage.stage_id: stage for stage in resolution.plan.stages}
    assert planned["ingestion"].provided == (ingestion.output["artifact_id"],)
    assert resolution.plan.run_stages == ("state_estimation",)

    result, _ = _run(gateway, resolution)
    assert result.status == "completed"
    assert result.record.provided == {"ingestion": (ingestion.output["artifact_id"],)}


def test_provided_artifacts_conflict_with_configured_selections(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    document = {"stage_id": "ingestion", "contract": "SequenceArtifact", "artifact_id": "a"}
    with pytest.raises(RuntimeOperationError, match="selections"):
        gateway.resolve_pipeline(
            profile="canonical/1",
            overrides=(*OVERRIDES, 'inputs.selections.ingestion=["latest"]'),
            scope=RuntimeScope(targets=TARGETS, provided={"ingestion": document}),
        )


def test_same_run_id_in_two_datasets_uses_exact_directory(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    first, _ = _run(gateway, _resolve(gateway))
    other = gateway.resolve_pipeline(
        profile="canonical/1",
        overrides=(*OVERRIDES, 'inputs.sequence="lab"'),
        scope=RuntimeScope(targets=TARGETS),
    )
    second, _ = _run(gateway, other)
    assert first.run_id == second.run_id

    with pytest.raises(RuntimeOperationError, match="several datasets"):
        gateway.inspect_run(first.run_id)
    summaries = gateway.list_runs()
    assert [(item.dataset, item.run_id) for item in summaries] == [
        ("corridor", first.run_id),
        ("lab", second.run_id),
    ]
    directories = [gateway.run_directory(item) for item in summaries]
    assert [gateway.inspect_run(item or "").directory for item in directories] == directories


def test_unreadable_run_record_stays_listed(tmp_path: Path) -> None:
    (tmp_path / "corridor" / "run-0001").mkdir(parents=True)
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)

    (summary,) = gateway.list_runs()

    assert not summary.readable
    assert summary.error
    with pytest.raises(RuntimeOperationError):
        gateway.inspect_run(gateway.run_directory(summary) or "")


def _catalog(path: Path, output: dict[str, Any]) -> Path:
    entry = core.CatalogEntry(
        ref=core.ArtifactRef.from_document(output), lineage=core.Lineage(), run_index=0
    )
    path.write_text(
        json.dumps({"schema_version": "0.1.0", "entries": [entry.to_document()]}),
        encoding="utf-8",
    )
    return path


def test_catalog_selection_execution_without_provided_artifacts(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path / "ws", set())
    first, _ = _run(gateway, _resolve(gateway))
    ingestion = next(stage for stage in first.record.stages if stage.stage_id == "ingestion")
    assert ingestion.output is not None
    catalog = _catalog(tmp_path / "catalog.json", dict(ingestion.output))
    overrides = (*OVERRIDES, 'inputs.selections.ingestion=["latest"]')

    missing = gateway.resolve_pipeline(
        profile="canonical/1",
        overrides=overrides,
        scope=RuntimeScope(targets=("state_estimation",)),
    )
    assert any(problem.path == "inputs.selections" for problem in missing.plan.problems)
    assert not gateway.preflight(missing).ok

    selected = gateway.resolve_pipeline(
        profile="canonical/1",
        overrides=overrides,
        scope=RuntimeScope(targets=("state_estimation",), catalog=str(catalog)),
    )
    assert selected.plan.selections is not None
    report = gateway.preflight(selected)
    assert report.ok, report.problems
    assert any("latest" in warning for warning in report.warnings)

    result, _ = _run(gateway, selected)
    assert result.status == "completed"
    assert result.record.selections is not None
    stage = next(s for s in result.record.stages if s.stage_id == "state_estimation")
    assert stage.inputs == {"sequence": (ingestion.output["artifact_id"],)}


def test_invalid_catalog_file_is_rejected(tmp_path: Path) -> None:
    gateway, _ = _gateway(tmp_path, set())
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeOperationError, match="schema_version"):
        gateway.resolve_pipeline(
            profile="canonical/1",
            overrides=(*OVERRIDES, 'inputs.selections.ingestion=["latest"]'),
            scope=RuntimeScope(targets=TARGETS, catalog=str(tmp_path / "bad.json")),
        )


def test_canonical_2_gaps_are_reported_not_substituted(tmp_path: Path) -> None:
    gateway = LocalRuntimeGateway(
        workspace_root=tmp_path,
        runtime_options={"module_available": lambda _name: True, "environ": {}},
    )
    resolution = gateway.resolve_pipeline(
        profile="canonical/2", overrides=('inputs.sequence="corridor"',)
    )
    report = gateway.preflight(resolution)

    assert not report.ok
    assert "ingestion" in report.missing_executors
    assert set(report.missing_executors) <= set(report.stages)
    result, events = _run(gateway, resolution)
    assert result.status == "blocked"
    assert [event.kind for event in events] == ["run_planned", "run_blocked"]
    assert all(stage.outcome == "pending" for stage in result.record.stages)


@pytest.mark.parametrize(
    ("filename", "note"),
    [("effective_config.json", "backends are unknown"), ("execution.json", "lineage is unknown")],
)
def test_unreadable_record_parts_become_runtime_notes(
    tmp_path: Path, filename: str, note: str
) -> None:
    gateway, _ = _gateway(tmp_path, set())
    result, _ = _run(gateway, _resolve(gateway))
    (Path(result.record.directory) / filename).write_text("{not json", encoding="utf-8")

    record = gateway.inspect_run(result.record.directory)

    assert any(note in item for item in record.notes)
    if filename == "effective_config.json":
        assert record.backends is None
    else:
        assert record.selections is None and record.resume is None
