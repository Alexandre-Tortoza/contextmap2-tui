"""Resolved-plan editor contract against the public runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextmap_tui.integration.runtime import LocalRuntimeGateway
from contextmap_tui.runtime import RuntimeOperationError, RuntimeScope


@pytest.mark.parametrize("profile", ["canonical/1", "canonical/2"])
def test_resolution_matches_public_config_and_plan(tmp_path: Path, profile: str) -> None:
    core = pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(profile=profile)
    runtime = core.Runtime(workspace=tmp_path)
    config = runtime.resolve_config(profile=profile)
    plan = runtime.resolve_plan(config)

    assert resolution.config.digest == config.digest
    assert resolution.plan.to_document() == plan.to_document()
    assert resolution.plan.order == plan.order
    assert resolution.plan.disabled_stages == plan.disabled_stages
    assert resolution.plan.preset == profile


def test_edit_uses_public_path_and_refreshes_both_digests(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    initial = gateway.resolve_pipeline(profile="canonical/1")
    path = "pipeline.stages.point_representation"
    assert next(edit for edit in initial.plan.editable if edit.path == path).current is False

    changed = gateway.apply_edit(initial, path=path, value=True)

    assert changed.plan.config_digest != initial.plan.config_digest
    assert changed.plan.plan_digest != initial.plan.plan_digest
    assert "point_representation" in changed.plan.order
    assert "point_representation" not in changed.plan.disabled_stages
    assert (
        gateway.resolve_pipeline(
            profile=changed.profile, overrides=changed.overrides
        ).plan.to_document()
        == changed.plan.to_document()
    )


def test_optional_component_none_and_invalid_edits(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    initial = gateway.resolve_pipeline(profile="canonical/2")
    path = "components.entity_resolution.appearance.backend"
    edit = next(item for item in initial.plan.editable if item.path == path)
    assert None in edit.allowed
    selected = gateway.apply_edit(initial, path=path, value="entity-appearance-comparison-v1")
    restored = gateway.apply_edit(selected, path=path, value=None)
    assert next(item for item in restored.plan.editable if item.path == path).current is None

    with pytest.raises(RuntimeOperationError, match="not declared editable"):
        gateway.apply_edit(initial, path="pipeline.stages.context_map", value=True)
    with pytest.raises(RuntimeOperationError):
        gateway.apply_edit(initial, path=path, value="invented")


def test_device_debug_and_input_edits(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(profile="canonical/1")
    for path, value in (
        ("resources.device", "cpu"),
        ("policies.debug_level", "standard"),
        ("inputs.sequence", "corridor"),
    ):
        resolution = gateway.apply_edit(resolution, path=path, value=value)
        assert next(item for item in resolution.plan.editable if item.path == path).current == value


def test_canonical_2_topology_components_and_no_invented_stage(tmp_path: Path) -> None:
    core = pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(profile="canonical/2")
    public = core.Runtime(workspace=tmp_path).capabilities(profile="canonical/2")
    planned = {stage.stage_id: stage for stage in resolution.plan.stages}

    assert resolution.plan.order is not None
    assert [stage.stage_id for stage in resolution.plan.stages] == list(resolution.plan.order)
    assert set(planned) | set(resolution.plan.disabled_stages) <= {s.stage_id for s in public}
    assert len(planned["visual_perception"].backends) == 4
    assert "context_map" not in resolution.plan.run_stages
    paths = {edit.path: edit for edit in resolution.plan.editable}
    optional_predicates = [
        edit
        for path, edit in paths.items()
        if path.startswith("components.spatial_relations.") and None in (edit.allowed or ())
    ]
    assert optional_predicates
    for stage in resolution.plan.stages:
        for item in stage.inputs:
            assert item.source in planned


def test_exact_and_latest_selection_edits(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(profile="canonical/1")
    path = "inputs.selections.ingestion"
    assert next(edit for edit in resolution.plan.editable if edit.path == path).kind == "selection"

    latest = gateway.apply_edit(resolution, path=path, value=["latest"])
    assert next(e for e in latest.plan.editable if e.path == path).current == ["latest"]
    assert any(problem.path == "inputs.selections" for problem in latest.plan.problems)

    exact = gateway.apply_edit(latest, path=path, value=["run-0001"])
    assert next(e for e in exact.plan.editable if e.path == path).current == ["run-0001"]
    assert exact.overrides.count(f'{path}=["run-0001"]') == 1
    assert not any(item.startswith(f'{path}=["latest"]') for item in exact.overrides)


def test_unknown_target_is_a_returned_plan_problem(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    resolution = gateway.resolve_pipeline(
        profile="canonical/1", scope=RuntimeScope(targets=("not_a_stage",))
    )

    assert resolution.plan.problems
    assert any("not_a_stage" in str(problem) for problem in resolution.plan.problems)


def test_unchanged_state_re_resolves_to_same_digests(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    first = gateway.apply_edit(
        gateway.resolve_pipeline(profile="canonical/1"), path="resources.device", value="cpu"
    )
    again = gateway.resolve_pipeline(
        profile=first.profile, files=first.files, overrides=first.overrides, scope=first.scope
    )

    assert again.config.digest == first.config.digest
    assert again.plan.plan_digest == first.plan.plan_digest


async def test_pipeline_screen_edits_real_plan_by_runtime_path(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    from textual.widgets import Button, DataTable, Select

    from contextmap_tui.app import ContextMapTuiApp
    from contextmap_tui.client import FakeContextMapClient
    from contextmap_tui.screens import PipelineScreen

    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    app = ContextMapTuiApp(
        client=FakeContextMapClient(), runtime_gateway=gateway, workspace_root=tmp_path
    )
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.press("p")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PipelineScreen)
        before = gateway.resolve_pipeline(profile="canonical/1").plan
        assert f"plan digest: {before.plan_digest}" in str(
            screen.query_one("#plan-summary").render()
        )

        edits = screen.query_one("#edit-table", DataTable)
        assert edits.get_row_at(0)[0] == "pipeline.stages.point_representation"
        edits.move_cursor(row=0)
        await pilot.pause()
        screen.query_one("#edit-choice", Select).value = "true"
        screen.query_one("#apply-edit", Button).press()
        await pilot.pause()

        summary = str(screen.query_one("#plan-summary").render())
        assert before.plan_digest not in summary
        assert "disabled stages: none" in summary
        stages = screen.query_one("#pipeline-table", DataTable)
        ids = [stages.get_row_at(row)[0] for row in range(stages.row_count)]
        assert "point_representation" in ids
