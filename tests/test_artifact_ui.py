from pathlib import Path

from textual.widgets import DataTable, Input

from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.models import (
    ArtifactOverview,
    ArtifactRef,
    CalibrationEntryView,
    CalibrationView,
    DiagnosticsView,
    ObservationView,
    ProvenanceView,
)
from contextmap_tui.screens import ArtifactScreen, WorkspaceScreen


def _fixture_client() -> FakeContextMapClient:
    ref = ArtifactRef(
        "corridor",
        "artifact-a",
        Path("/tmp/workspace/sequences/corridor/artifact-a"),
    )
    observation = ObservationView(
        observation_id="frame-1",
        modality="image",
        sensor_id="front_camera",
        frame_id="camera_optical",
        timestamp_nanoseconds=123,
        clock_id="robot-clock",
        calibration_id="camera-calib",
        source_type="fixture",
        source_path="source.bag",
        source_topic="/camera/image_raw",
        source_message_index=4,
        raw_metadata={"bag_timestamp_nanoseconds": 124},
    )
    return FakeContextMapClient(
        artifacts=(ref,),
        overviews={
            "artifact-a": ArtifactOverview(
                ref=ref,
                schema_version="0.2.0",
                created_at="2026-09-19T00:00:00+00:00",
                observation_counts={"image": 1},
                file_count=3,
                total_size_bytes=128,
            )
        },
        observation_items={"artifact-a": (observation,)},
        provenances={
            "artifact-a": ProvenanceView(
                source_type="fixture",
                source_path="source.bag",
                source_content_hash="sha256:source",
                configuration_hash="sha256:config",
                content_identity="sha256:identity",
                adapter_type="fixture",
                code_version="test",
                calibration_source_hash=None,
                synchronization_policy=None,
                ingestion_config={},
                warnings=(),
            )
        },
        calibrations={
            "artifact-a": CalibrationView(
                schema_version="0.1.0",
                entries=(
                    CalibrationEntryView(
                        calibration_id="camera-calib",
                        sensor_id="front_camera",
                        frame_id="camera_optical",
                        camera_model="PinholeCameraModel",
                        content_hash="sha256:calib",
                        source_type="fixture",
                        source_path="calib.yaml",
                    ),
                ),
                static_transforms=(),
            )
        },
        diagnostics_by_artifact={
            "artifact-a": DiagnosticsView(
                warning_count=0,
                warnings=(),
                source_types=("fixture",),
                topic_counts={"/camera/image_raw": 1},
                synchronization_status_counts={},
                decisions=(),
                dropped_events=(),
                calibration_ids=("camera-calib",),
                frame_ids=("camera_optical",),
                static_transform_count=0,
            )
        },
    )


async def test_user_can_navigate_workspace_to_artifact_evidence() -> None:
    app = ContextMapTuiApp(
        client=_fixture_client(),
        workspace_root=Path("/tmp/workspace"),
    )

    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceScreen)
        table = app.screen.query_one("#artifact-table", DataTable)
        table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ArtifactScreen)
        assert "Integrity: OK" in str(app.screen.query_one("#artifact-overview").render())
        assert "sha256:identity" in str(app.screen.query_one("#provenance-view").render())
        assert "camera-calib" in str(app.screen.query_one("#calibration-view").render())

        observation_table = app.screen.query_one("#observation-table", DataTable)
        observation_table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()

        detail = str(app.screen.query_one("#observation-detail").render())
        assert "frame-1" in detail
        assert "/camera/image_raw" in detail


async def test_artifact_filter_updates_table() -> None:
    app = ContextMapTuiApp(
        client=_fixture_client(),
        workspace_root=Path("/tmp/workspace"),
    )

    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        workspace_table = app.screen.query_one("#artifact-table", DataTable)
        workspace_table.move_cursor(row=0)
        await pilot.press("enter")
        await pilot.pause()

        modality = app.screen.query_one("#filter-modality", Input)
        modality.value = "lidar"
        await pilot.click("#apply-filter")
        await pilot.pause()

        assert "0-0 of 0" in str(app.screen.query_one("#page-status").render())
