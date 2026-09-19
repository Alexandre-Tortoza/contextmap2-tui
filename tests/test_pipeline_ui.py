from pathlib import Path

from textual.widgets import DataTable, Input

from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.runtime import (
    FakeRuntimeGateway,
    PipelineConfigView,
    PipelineRunResult,
    PipelineStageView,
    RunRecord,
    RuntimeEvent,
    RuntimePreflight,
    StageCapability,
    UnavailableRuntimeGateway,
)
from contextmap_tui.screens import PipelineScreen


def _runtime() -> FakeRuntimeGateway:
    return FakeRuntimeGateway(
        stage_capabilities=(
            StageCapability(
                "ingestion",
                "Ingestion",
                True,
                False,
                ("canonical",),
            ),
            StageCapability(
                "visual_perception",
                "Visual Perception",
                True,
                True,
                ("foundation-v1", "foundation-v2"),
            ),
        ),
        config=PipelineConfigView(
            "fixture",
            (
                PipelineStageView("ingestion", True, "canonical"),
                PipelineStageView(
                    "visual_perception",
                    True,
                    "foundation-v1",
                    ("ingestion",),
                ),
            ),
        ),
        preflight_result=RuntimePreflight(ok=True),
        run_result=PipelineRunResult(
            status="completed",
            run_id="run-1",
            output_artifacts=("perception:artifact-1",),
        ),
        events=(RuntimeEvent("visual_perception", "running", 50),),
        run_records=(
            RunRecord(
                run_id="run-1",
                status="completed",
                effective_config={"preset": "fixture"},
                upstream_artifacts=("sequence:artifact-a",),
                output_artifacts=("perception:artifact-1",),
                metrics={"elapsed_ms": 12},
            ),
        ),
    )


async def test_pipeline_console_reports_missing_runtime() -> None:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        runtime_gateway=UnavailableRuntimeGateway("runtime missing"),
    )

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(app.screen, PipelineScreen)
        status = str(app.screen.query_one("#runtime-availability").render())
        assert "unavailable" in status
        assert "runtime missing" in status


async def test_pipeline_console_edits_preflights_runs_and_inspects_lineage() -> None:
    runtime = _runtime()
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        runtime_gateway=runtime,
        workspace_root=Path("/tmp/workspace"),
    )

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, PipelineScreen)

        table = app.screen.query_one("#pipeline-table", DataTable)
        table.move_cursor(row=1)
        toggle = app.screen.query_one("#toggle-stage")
        toggle.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.pipeline_config().stages[1].enabled is False

        backend = app.screen.query_one("#backend-id", Input)
        backend.value = "foundation-v2"
        table.move_cursor(row=1)
        apply_button = app.screen.query_one("#apply-backend")
        apply_button.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.pipeline_config().stages[1].backend == "foundation-v2"

        preflight = app.screen.query_one("#pipeline-preflight")
        preflight.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "Preflight: OK" in str(app.screen.query_one("#pipeline-preflight-result").render())

        run = app.screen.query_one("#run-pipeline")
        run.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert "Status: completed" in str(
            app.screen.query_one("#pipeline-execution-status").render()
        )

        run_table = app.screen.query_one("#run-table", DataTable)
        run_table.focus()
        run_table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()
        detail = str(app.screen.query_one("#run-detail").render())
        assert "sequence:artifact-a" in detail
        assert "perception:artifact-1" in detail
