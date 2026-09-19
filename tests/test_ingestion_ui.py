from pathlib import Path

from textual.widgets import Button, Input

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
        events=(
            IngestionEvent("read", "reading source", 25),
            IngestionEvent("write", "writing artifact", 90),
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

        run_button = app.screen.query_one("#run-ingestion", Button)
        run_button.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        result_text = str(app.screen.query_one("#ingestion-result").render())
        assert "status: completed" in result_text
        assert "artifact: corridor/artifact-a" in result_text
        open_button = app.screen.query_one("#open-result", Button)
        assert open_button.disabled is False

        open_button.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ArtifactScreen)
