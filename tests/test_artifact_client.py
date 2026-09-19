from pathlib import Path

from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.models import (
    ArtifactOverview,
    ArtifactRef,
    ObservationFilter,
    ObservationView,
)


def _observation(identity: str, modality: str, sensor: str, frame: str) -> ObservationView:
    return ObservationView(
        observation_id=identity,
        modality=modality,
        sensor_id=sensor,
        frame_id=frame,
        timestamp_nanoseconds=1,
        clock_id="robot-clock",
        calibration_id=None,
        source_type="fixture",
        source_path="fixture.bin",
        source_topic=f"/{sensor}",
        source_message_index=0,
    )


def test_fake_client_preserves_artifact_and_observation_order() -> None:
    ref = ArtifactRef("corridor", "artifact-a", Path("/tmp/artifact-a"))
    observations = (
        _observation("image-1", "image", "front", "camera"),
        _observation("scan-1", "lidar", "lidar", "velodyne"),
        _observation("image-2", "image", "rear", "camera-rear"),
    )
    client = FakeContextMapClient(
        artifacts=(ref,),
        overviews={
            ref.artifact_id: ArtifactOverview(
                ref=ref,
                schema_version="0.2.0",
                created_at="2026-09-19T00:00:00+00:00",
                observation_counts={"image": 2, "lidar": 1},
                file_count=4,
                total_size_bytes=100,
            )
        },
        observation_items={ref.artifact_id: observations},
    )

    assert client.list_artifacts(Path("ignored")) == (ref,)
    page = client.observations(
        ref,
        ObservationFilter(modality="image", sensor_or_frame="camera"),
        offset=0,
        limit=10,
    )
    assert [item.observation_id for item in page.items] == ["image-1", "image-2"]
    assert page.total == 2


def test_fake_client_pages_after_filtering() -> None:
    ref = ArtifactRef("corridor", "artifact-a", Path("/tmp/artifact-a"))
    observations = tuple(
        _observation(f"image-{index}", "image", "front", "camera") for index in range(5)
    )
    client = FakeContextMapClient(
        artifacts=(ref,), observation_items={ref.artifact_id: observations}
    )

    page = client.observations(ref, ObservationFilter(text="image"), offset=2, limit=2)

    assert [item.observation_id for item in page.items] == ["image-2", "image-3"]
    assert page.total == 5
    assert page.offset == 2
