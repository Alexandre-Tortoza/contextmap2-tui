from pathlib import Path
from threading import Event

from textual.widgets import Button, Input, RichLog

from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.ingestion import (
    FakeIngestionRunner,
    IngestionEvent,
    IngestionResult,
    UnavailableIngestionRunner,
)
from contextmap_tui.models import ArtifactOverview, ArtifactRef
from contextmap_tui.screens import ArtifactScreen, IngestionScreen


def _artifact(tmp_path: Path) -> ArtifactRef:
    return ArtifactRef(
        sequence_name="corridor",
        artifact_id="artifact-a",
        path=tmp_path / "sequences" / "corridor" / "artifact-a",
    )


async def _fill_minimal_form(app: ContextMapTuiApp, source: Path) -> None:
    app.screen.query_one("#source-path", Input).value = str(source)
    app.screen.query_one("#sequence-name", Input).value = "corridor"
    app.screen.query_one("#output-workspace", Input).value = str(source.parent)
    app.screen.query_one("#topic-rgb", Input).value = "/camera"
    app.screen.query_one("#topic-lidar", Input).value = "/points"


async def test_ingestion_console_exposes_unavailable_core_runner(tmp_path: Path) -> None:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        ingestion_runner=UnavailableIngestionRunner("core runner missing"),
        workspace_root=tmp_path,
    )

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, IngestionScreen)
        assert "unavailable" in str(app.screen.query_one("#runner-availability").render())
        assert "core runner missing" in str(app.screen.query_one("#runner-availability").render())


async def test_ingestion_preflight_and_result_reopen_persisted_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.bag"
    source.write_bytes(b"fixture")
    artifact = _artifact(tmp_path)
    client = FakeContextMapClient(
        artifacts=(artifact,),
        overviews={
            artifact.artifact_id: ArtifactOverview(
                ref=artifact,
                schema_version="0.2.0",
                created_at="2026-09-19T00:00:00+00:00",
                observation_counts={"image": 2, "lidar": 2},
                file_count=4,
                total_size_bytes=100,
            )
        },
    )
    runner = FakeIngestionRunner(
        result=IngestionResult(
            status="completed",
            artifact=artifact,
            observation_counts={"image": 2, "lidar": 2},
            warnings=("fixture warning",),
        ),
        events=tuple(
            IngestionEvent(
                "ingestion.progress",
                index,
                "2026-09-19T00:00:00Z",
                None,
                {"observations_read": index},
            )
            for index in range(1, 51)
        ),
    )
    app = ContextMapTuiApp(
        client=client,
        ingestion_runner=runner,
        workspace_root=tmp_path,
    )

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, IngestionScreen)
        await _fill_minimal_form(app, source)

        preflight_button = app.screen.query_one("#preflight", Button)
        preflight_button.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert "Preflight: OK" in str(app.screen.query_one("#preflight-result").render())
        assert not app.screen._ingestion_running

        run_button = app.screen.query_one("#run-ingestion", Button)
        run_button.focus()
        await pilot.pause()
        assert app.focused is run_button
        assert not run_button.disabled
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not app.screen._ingestion_running
        assert runner.run_calls == 1

        result_text = str(app.screen.query_one("#ingestion-result").render())
        assert "Running" not in str(app.screen.query_one("#execution-status").render())
        assert "status: completed" in result_text
        assert "artifact: corridor/artifact-a" in result_text
        open_button = app.screen.query_one("#open-result", Button)
        assert open_button.disabled is False

        open_button.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ArtifactScreen)


async def test_repeated_run_action_does_not_start_concurrent_workers(tmp_path: Path) -> None:
    class BlockingRunner(FakeIngestionRunner):
        started = Event()
        release = Event()

        def run(self, prepared: object, *, emit: object) -> IngestionResult:
            self.run_calls += 1
            self.started.set()
            self.release.wait(timeout=5)
            return self.result

    source = tmp_path / "source.bag"
    source.write_bytes(b"fixture")
    runner = BlockingRunner(result=IngestionResult(status="failed"))
    app = ContextMapTuiApp(
        client=FakeContextMapClient(), ingestion_runner=runner, workspace_root=tmp_path
    )

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        await _fill_minimal_form(app, source)
        screen = app.screen
        assert isinstance(screen, IngestionScreen)
        screen._run_pressed()
        await pilot.pause()
        assert runner.started.is_set()
        assert screen._ingestion_running
        screen._run_pressed()
        assert runner.run_calls == 1
        runner.release.set()
        await app.workers.wait_for_complete()


async def test_failed_artifact_reopen_keeps_navigation_disabled(tmp_path: Path) -> None:
    source = tmp_path / "source.bag"
    source.write_bytes(b"fixture")
    runner = FakeIngestionRunner(
        result=IngestionResult(status="completed", artifact=_artifact(tmp_path))
    )
    app = ContextMapTuiApp(
        client=FakeContextMapClient(), ingestion_runner=runner, workspace_root=tmp_path
    )

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        await _fill_minimal_form(app, source)
        screen = app.screen
        assert isinstance(screen, IngestionScreen)
        screen._run_pressed()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert "could not be reopened" in str(app.screen.query_one("#ingestion-result").render())
        assert app.screen.query_one("#open-result", Button).disabled


async def test_event_burst_is_logged_in_order_and_ui_stays_responsive(tmp_path: Path) -> None:
    source = tmp_path / "source.bag"
    source.write_bytes(b"fixture")
    events = tuple(
        IngestionEvent(
            kind="ingestion.progress",
            sequence=index,
            time="2026-09-23T00:00:00Z",
            stage_id="ingestion",
            data={"observations": index, "note": "[not markup]"},
        )
        for index in range(1, 501)
    )
    runner = FakeIngestionRunner(result=IngestionResult(status="failed"), events=events)
    app = ContextMapTuiApp(
        client=FakeContextMapClient(), ingestion_runner=runner, workspace_root=tmp_path
    )

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        await _fill_minimal_form(app, source)
        screen = app.screen
        assert isinstance(screen, IngestionScreen)
        screen._run_pressed()
        await app.workers.wait_for_complete()
        await pilot.pause()

        log = screen.query_one("#execution-log", RichLog)
        text = "".join(line.text for line in log.lines)
        positions = [text.index(f'"sequence": {n},') for n in (1, 250, 500)]
        assert positions == sorted(positions)
        assert text.count('"kind": "ingestion.progress"') == 500
        assert text.count("[not markup]") == 500
        assert "Status: failed" in str(screen.query_one("#execution-status").render())
        assert runner.run_calls == 1
