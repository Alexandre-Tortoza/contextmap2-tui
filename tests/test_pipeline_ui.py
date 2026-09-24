from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Button, DataTable, Input, Select

import runtime_values as values
from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.runtime import FakeRuntimeGateway, UnavailableRuntimeGateway
from contextmap_tui.screens import PipelineScreen, RunsScreen


def _text(app: ContextMapTuiApp, selector: str) -> str:
    return str(app.screen.query_one(selector).render())


async def _open(runtime: FakeRuntimeGateway) -> tuple[ContextMapTuiApp, object]:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(), runtime_gateway=runtime, workspace_root=Path("/workspace")
    )
    return app, app.run_test(size=(160, 60))


async def _press(pilot: object, app: ContextMapTuiApp, selector: str) -> None:
    app.screen.query_one(selector, Button).press()
    await pilot.pause()  # type: ignore[attr-defined]


async def test_pipeline_console_reports_missing_runtime() -> None:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        runtime_gateway=UnavailableRuntimeGateway("runtime missing"),
    )

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(app.screen, PipelineScreen)
        status = _text(app, "#runtime-availability")
        assert "unavailable" in status
        assert "runtime missing" in status


async def test_plan_renders_runtime_topology_digests_and_edits() -> None:
    runtime = values.gateway()
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()

        summary = _text(app, "#plan-summary")
        assert "preset: canonical/1" in summary
        assert "config digest: sha256:config-a" in summary
        assert "plan digest: sha256:plan-a" in summary
        assert "order: ingestion -> visual_perception" in summary
        assert "disabled stages: point_representation" in summary
        assert "Plan problems: none" in summary

        stages = app.screen.query_one("#pipeline-table", DataTable)
        perception = stages.get_row_at(1)
        assert perception[0] == "visual_perception"
        assert perception[4] == "sequence:SequenceArtifact<-ingestion"
        assert perception[5] == "VisualPerceptionArtifact"
        assert "visual_perception.region_discovery=none" in perception[6]

        edits = app.screen.query_one("#edit-table", DataTable)
        paths = [edits.get_row_at(row)[0] for row in range(edits.row_count)]
        assert paths == [edit.path for edit in runtime.resolution.plan.editable]


async def test_choice_edit_applies_runtime_path_and_refreshes_plan() -> None:
    runtime = values.gateway(
        next_resolution=values.resolution(
            digest="sha256:plan-b", config_digest="sha256:config-b", perception_backend="sam3"
        )
    )
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        edits = app.screen.query_one("#edit-table", DataTable)
        edits.move_cursor(row=1)
        await pilot.pause()
        choice = app.screen.query_one("#edit-choice", Select)
        choice.value = '"sam3"'
        await _press(pilot, app, "#apply-edit")

        assert runtime.edited == [("components.visual_perception.region_discovery.backend", "sam3")]
        summary = _text(app, "#plan-summary")
        assert "sha256:plan-b" in summary and "sha256:config-b" in summary
        row = app.screen.query_one("#pipeline-table", DataTable).get_row_at(1)
        assert "visual_perception.region_discovery=sam3" in row[6]


async def test_optional_component_none_and_selection_edits() -> None:
    runtime = values.gateway(next_resolution=values.resolution())
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        edits = app.screen.query_one("#edit-table", DataTable)
        edits.move_cursor(row=2)
        await pilot.pause()
        app.screen.query_one("#edit-choice", Select).value = "null"
        await _press(pilot, app, "#apply-edit")

        edits.move_cursor(row=4)
        await pilot.pause()
        app.screen.query_one("#edit-value", Input).value = '["latest"]'
        await _press(pilot, app, "#apply-edit")

        edits.move_cursor(row=3)
        await pilot.pause()
        app.screen.query_one("#edit-value", Input).value = "cuda:0"
        await _press(pilot, app, "#apply-edit")

        assert runtime.edited == [
            ("components.entity_resolution.appearance.backend", None),
            ("inputs.selections.ingestion", ["latest"]),
            ("resources.device", "cuda:0"),
        ]


async def test_runtime_rejection_and_plan_problems_are_surfaced() -> None:
    problem = values.Problem("pipeline.targets", "unknown target 'nope'")
    runtime = values.gateway(resolution=values.resolution(problems=(problem,)))
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        assert "pipeline.targets: unknown target 'nope'" in _text(app, "#plan-summary")

        edits = app.screen.query_one("#edit-table", DataTable)
        edits.move_cursor(row=0)
        await pilot.pause()
        app.screen.query_one("#edit-choice", Select).value = "true"
        await _press(pilot, app, "#apply-edit")
        assert "Rejected: no fake resolution configured" in _text(app, "#pipeline-config-status")


async def test_scope_targets_and_provided_artifact_from_recorded_run() -> None:
    runtime = values.gateway()
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        app.screen.query_one("#scope-targets", Input).value = "visual_perception"
        app.screen.query_one("#provided-run", Input).value = "/workspace/corridor/run-0001"
        app.screen.query_one("#provided-stages", Input).value = "ingestion"
        await _press(pilot, app, "#apply-scope")

        scope = runtime.scopes[-1]
        assert scope.targets == ("visual_perception",)
        assert scope.provided == {"ingestion": values.SEQUENCE_OUTPUT}

        app.screen.query_one("#provided-stages", Input).value = "state_estimation"
        await _press(pilot, app, "#apply-scope")
        assert runtime.scopes[-1] is scope


async def test_blocked_preflight_prevents_execution() -> None:
    problem = values.Problem("stages.visual_perception", "no executor is registered for it")
    runtime = values.gateway(preflight_report=values.preflight(ok=False, problems=(problem,)))
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        await _press(pilot, app, "#run-pipeline")

        report = _text(app, "#pipeline-preflight-result")
        assert "Preflight: BLOCKED" in report
        assert "no executor is registered" in report
        assert "missing executors: visual_perception" in report
        assert "Cannot run: preflight is blocked" in _text(app, "#pipeline-execution-status")
        assert runtime.runs == []


async def test_preflight_renders_reuse_prediction_and_run_links_to_inspector() -> None:
    runtime = values.gateway()
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        await _press(pilot, app, "#pipeline-preflight")
        report = _text(app, "#pipeline-preflight-result")
        assert "Preflight: OK" in report
        assert 'predicted reuse ingestion: {"kind": "reused"' in report
        assert "'latest' resolved to 'seq-1'" in report

        app.screen.query_one("#reuse-index", Input).value = "/index"
        app.screen.query_one("#reuse-code", Input).value = "git:abc"
        await _press(pilot, app, "#run-pipeline")
        await app.workers.wait_for_complete()
        await pilot.pause()

        status = _text(app, "#pipeline-execution-status")
        assert "Status: completed" in status
        assert "run_id: run-0001" in status
        assert runtime.runs[-1]["reuse"].index == "/index"
        assert runtime.runs[-1]["resume"] is None

        await _press(pilot, app, "#inspect-run")
        assert isinstance(app.screen, RunsScreen)
        assert "directory: /workspace/corridor/run-0001" in _text(app, "#run-record")


async def test_resume_and_event_sink_errors_are_presentation_only() -> None:
    result = SimpleNamespace(
        status="completed",
        run_id="run-0002",
        record=values.record("run-0002", resumed_from="run-0001"),
        event_errors=("event 3 (stage_reused): ValueError: renderer",),
    )
    runtime = values.gateway(execution_result=result)
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        app.screen.query_one("#resume-run", Input).value = "run-0001"
        await _press(pilot, app, "#resume-pipeline")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert runtime.runs[-1]["resume"] == "run-0001"
        status = _text(app, "#pipeline-execution-status")
        assert "run_id: run-0002" in status
        assert "event sink error (presentation only)" in status


async def test_cancel_forwards_to_runtime_token() -> None:
    runtime = values.gateway(
        execution_result=SimpleNamespace(
            status="cancelled",
            run_id="run-0001",
            record=values.record(status="cancelled"),
            event_errors=(),
        )
    )
    app, context = await _open(runtime)
    async with context as pilot:  # type: ignore[attr-defined]
        await pilot.press("p")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PipelineScreen)
        await _press(pilot, app, "#run-pipeline")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await _press(pilot, app, "#cancel-pipeline")

        assert screen._cancellation is not None and screen._cancellation.cancelled
        assert "Cancellation requested" in _text(app, "#pipeline-execution-status")
