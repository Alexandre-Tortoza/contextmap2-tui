from pathlib import Path
from threading import Event

from contextmap_tui.ingestion import (
    FakeIngestionRunner,
    IngestionRequest,
    IngestionResult,
    UnavailableIngestionRunner,
    parse_required_topics,
    validate_ingestion_request,
)


def _request(tmp_path: Path) -> IngestionRequest:
    source = tmp_path / "source.bag"
    source.write_bytes(b"fixture")
    return IngestionRequest(
        source_type="ros1_bag",
        source_path=source,
        sequence_name="corridor",
        workspace_root=tmp_path,
        topics={"rgb": "/camera", "lidar": "/points"},
        required_topics=frozenset({"rgb", "lidar"}),
        reference_modality="image",
        tolerance_nanoseconds=50_000_000,
    )


def test_request_validation_and_effective_config_are_deterministic(tmp_path: Path) -> None:
    request = _request(tmp_path)

    assert validate_ingestion_request(request) == ()
    assert request.effective_config()["required_topics"] == ["lidar", "rgb"]
    assert parse_required_topics(" rgb, lidar, rgb ") == frozenset({"rgb", "lidar"})


def test_validation_rejects_missing_required_mapping(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request = IngestionRequest(
        source_type=request.source_type,
        source_path=request.source_path,
        sequence_name=request.sequence_name,
        workspace_root=request.workspace_root,
        topics={"rgb": "/camera"},
        required_topics=frozenset({"rgb", "lidar"}),
    )

    problems = validate_ingestion_request(request)

    assert "required topic 'lidar' has no mapping" in problems


def test_unavailable_runner_never_falls_back_to_tui_engine(tmp_path: Path) -> None:
    runner = UnavailableIngestionRunner()
    request = _request(tmp_path)

    assert runner.availability().available is False
    assert runner.preflight(request).ok is False
    result = runner.run(request, emit=lambda event: None, cancel_event=Event())
    assert result.status == "unsupported"


def test_fake_runner_honors_preexisting_cancellation(tmp_path: Path) -> None:
    runner = FakeIngestionRunner(result=IngestionResult(status="completed"))
    cancel = Event()
    cancel.set()

    result = runner.run(_request(tmp_path), emit=lambda event: None, cancel_event=cancel)

    assert result.status == "cancelled"
