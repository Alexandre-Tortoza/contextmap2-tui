from pathlib import Path

from textual.widgets import DataTable

import runtime_values as values
from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.runtime import FakeRuntimeGateway
from contextmap_tui.screens import RunsScreen


def _text(app: ContextMapTuiApp, selector: str) -> str:
    return str(app.screen.query_one(selector).render())


def _app(runtime: FakeRuntimeGateway) -> ContextMapTuiApp:
    return ContextMapTuiApp(
        client=FakeContextMapClient(), runtime_gateway=runtime, workspace_root=Path("/workspace")
    )


async def _select(pilot: object, app: ContextMapTuiApp, row: int) -> None:
    table = app.screen.query_one("#runs-table", DataTable)
    table.focus()
    table.move_cursor(row=row)
    await pilot.press("enter")  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]


async def test_run_list_keeps_order_status_and_unreadable_records() -> None:
    runtime = values.gateway(
        run_summaries=(
            values.summary(),
            values.summary("run-0002", status="failed", failure_category="stage"),
            values.summary("run-0003", readable=False),
            values.summary("run-0001", dataset="lab", resumed_from="run-0000"),
        )
    )
    app = _app(runtime)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, RunsScreen)
        table = app.screen.query_one("#runs-table", DataTable)
        rows = [table.get_row_at(row) for row in range(table.row_count)]
        assert [(row[0], row[1], row[3]) for row in rows] == [
            ("corridor", "run-0001", "completed"),
            ("corridor", "run-0002", "failed"),
            ("corridor", "run-0003", "unreadable"),
            ("lab", "run-0001", "completed"),
        ]
        assert rows[1][8] == "stage"
        assert rows[2][8] == "run.json is not valid JSON"
        assert rows[3][7] == "run-0000"

        await _select(pilot, app, 2)
        assert "unreadable" in _text(app, "#run-record")


async def test_record_shows_persisted_lineage_without_inference() -> None:
    record = values.record(
        stages=(
            values.run_stage(
                "ingestion", "completed", inputs={}, output=values.SEQUENCE_OUTPUT, elapsed_s=1.5
            ),
            values.run_stage("visual_perception", "reused", decision={"kind": "reused"}),
        ),
        backends=None,
        code_identity=None,
        notes=("the persisted configuration is unreadable, so backends are unknown",),
    )
    runtime = values.gateway(run_records={"/workspace/corridor/run-0001": record})
    app = _app(runtime)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.press("r")
        await pilot.pause()
        await _select(pilot, app, 0)

        detail = _text(app, "#run-record")
        assert "backends: unknown (not recorded)" in detail
        assert "code identity: unknown (not recorded)" in detail
        assert "the persisted configuration is unreadable" in detail
        assert "#1 2026-09-23T00:00:01Z run_planned [run]" in detail
        stages = app.screen.query_one("#run-stages-table", DataTable)
        ingestion = stages.get_row_at(0)
        reused = stages.get_row_at(1)
        assert ingestion[1] == "completed" and '"artifact_id": "seq-1"' in ingestion[3]
        assert ingestion[5] == "1.500s"
        assert reused[1] == "reused"
        assert reused[2] == "unknown (not recorded)"
        assert reused[3] == "unknown (not recorded)"
        assert '"kind": "reused"' in reused[4]


async def test_failed_blocked_and_resumed_records() -> None:
    blocked = values.record(
        "run-0002",
        status="blocked",
        blocked_problems=(values.Problem("stages.ingestion", "no executor is registered"),),
    )
    failed = values.record(
        "run-0003",
        status="failed",
        failure={"stage_id": "visual_perception", "category": "stage", "message": "boom"},
    )
    resumed = values.record(
        "run-0004",
        resumed_from="run-0003",
        resume={"reused": ["ingestion"], "recomputed": ["visual_perception"]},
        interrupted=False,
    )
    runtime = values.gateway(
        run_summaries=(
            values.summary("run-0002", status="blocked"),
            values.summary("run-0003", status="failed"),
            values.summary("run-0004", resumed_from="run-0003"),
        ),
        run_records={
            "/workspace/corridor/run-0002": blocked,
            "/workspace/corridor/run-0003": failed,
            "/workspace/corridor/run-0004": resumed,
        },
    )
    app = _app(runtime)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.press("r")
        await pilot.pause()
        await _select(pilot, app, 0)
        assert "stages.ingestion: no executor is registered" in _text(app, "#run-record")
        await _select(pilot, app, 1)
        assert '"category": "stage"' in _text(app, "#run-record")
        await _select(pilot, app, 2)
        detail = _text(app, "#run-record")
        assert "resumed_from: run-0003" in detail
        assert '"recomputed": ["visual_perception"]' in detail


async def test_same_run_id_in_two_datasets_opens_exact_directory() -> None:
    lab = values.record(dataset="lab", code_identity="git:lab")
    runtime = values.gateway(
        run_summaries=(values.summary(), values.summary(dataset="lab")),
        run_records={
            "/workspace/corridor/run-0001": values.record(),
            "/workspace/lab/run-0001": lab,
        },
    )
    app = _app(runtime)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.press("r")
        await pilot.pause()
        await _select(pilot, app, 1)
        detail = _text(app, "#run-record")
        assert "directory: /workspace/lab/run-0001" in detail
        assert "code identity: git:lab" in detail
