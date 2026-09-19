from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import contextmap_tui.integration.local as local_module
from contextmap_tui.integration.local import LocalContextMapClient
from contextmap_tui.models import ObservationFilter


class _Reader:
    opened: ClassVar[list[Path]] = []

    def __init__(self, path: Path) -> None:
        self.opened.append(path)
        if path.name == "broken":
            raise ValueError("broken manifest")
        self.manifest = SimpleNamespace(
            sequence_name=path.parent.name,
            artifact_id=path.name,
            schema_version="0.2.0",
            created_at="2026-09-19T00:00:00+00:00",
            observation_counts={"image": 1},
            file_inventory=(SimpleNamespace(size_bytes=20),),
        )

    def verify_integrity(self) -> list[str]:
        return []

    def list_observations(self) -> list[Any]:
        timestamp = SimpleNamespace(total_nanoseconds=lambda: 123, clock_id="clock")
        provenance = SimpleNamespace(
            source_type="fixture",
            source_path="source.bag",
            source_topic="/camera",
            source_message_index=7,
            raw_metadata={"bag_timestamp_nanoseconds": 124},
        )
        return [
            SimpleNamespace(
                observation_id="frame-1",
                sensor_id="camera",
                frame_id="camera_optical",
                timestamp=timestamp,
                provenance=provenance,
                calibration_id="camera-calib",
            )
        ]

    def read_provenance(self) -> None:
        return None

    def read_calibration(self) -> None:
        return None

    def read_diagnostics(self) -> None:
        return None


def _fake_ingestion() -> SimpleNamespace:
    return SimpleNamespace(
        SequenceArtifactReader=_Reader,
        observation_modality=lambda observation: "image",
        compute_content_identity=lambda provenance: "sha256:identity",
    )


def test_local_client_discovers_by_opening_public_reader(tmp_path: Path, monkeypatch: Any) -> None:
    sequence = tmp_path / "sequences" / "corridor"
    (sequence / "artifact-a").mkdir(parents=True)
    (sequence / "broken").mkdir()
    (sequence / ".tmp-incomplete").mkdir()
    _Reader.opened = []
    monkeypatch.setattr(local_module, "import_module", lambda name: _fake_ingestion())

    artifacts = LocalContextMapClient().list_artifacts(tmp_path)

    assert [item.artifact_id for item in artifacts] == ["artifact-a", "broken"]
    assert artifacts[0].readable is True
    assert artifacts[1].readable is False
    assert {path.name for path in _Reader.opened} == {"artifact-a", "broken"}


def test_local_client_projects_reader_data_without_parsing_json(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifact_dir = tmp_path / "sequences" / "corridor" / "artifact-a"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setattr(local_module, "import_module", lambda name: _fake_ingestion())
    client = LocalContextMapClient()
    ref = client.list_artifacts(tmp_path)[0]

    overview = client.artifact_overview(ref)
    page = client.observations(ref, ObservationFilter(), offset=0, limit=10)

    assert overview.integrity_ok is True
    assert overview.total_size_bytes == 20
    assert page.total == 1
    assert page.items[0].observation_id == "frame-1"
    assert page.items[0].raw_metadata["bag_timestamp_nanoseconds"] == 124
