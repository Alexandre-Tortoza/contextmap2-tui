"""Contract checks against the public ContextMap2 dev ingestion API."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

from contextmap_tui.integration.ingestion import LocalIngestionRunner


def _fields(tmp_path: Path) -> dict[str, str]:
    return {
        "source_backend": "ros1_bag",
        "source_path": str(tmp_path / "source.bag"),
        "sequence_name": "corridor",
        "artifact_id": "artifact-a",
        "output_dir": "",
        "topics.rgb": "/camera",
        "topics.lidar": "/points",
        "required_topics": "rgb,lidar",
        "timestamp_clock_id": "header-clock",
        "reference_modality": "image",
        "tolerance_nanoseconds": "50000000",
        "window_clock_id": "recording-clock",
        "window_start_seconds": "1.25",
        "window_end_seconds": "2.5",
        "validation_on_problems": "warn",
        "allow_duplicate_timestamps": "false",
        "hash_source": "false",
    }


def test_source_options_come_from_runtime_discovery(tmp_path: Path) -> None:
    core = pytest.importorskip("contextmap.runtime")
    runner = LocalIngestionRunner()
    discovery = runner.discover(tmp_path, profile="canonical/1")
    stage = next(
        item
        for item in core.Runtime(workspace=tmp_path).capabilities()
        if item.stage_id == "ingestion"
    )
    expected = {
        backend.backend_id for component in stage.components for backend in component.backends
    }

    assert {item.backend_id for item in discovery.backends} == expected
    assert set(discovery.profiles) >= {"canonical/1", "canonical/2"}


@pytest.mark.parametrize("backend", ["ros1_bag", "ros2_bag"])
def test_effective_request_is_public_core_request(tmp_path: Path, backend: str) -> None:
    core = pytest.importorskip("contextmap.runtime")
    runner = LocalIngestionRunner()
    fields = _fields(tmp_path)
    fields["source_backend"] = backend
    prepared = runner.prepare(fields, workspace_root=tmp_path, profile="canonical/1")
    request = prepared.request

    assert isinstance(request, core.IngestionRequest)
    assert (
        request.source_type == prepared.config.config.components["ingestion.source_adapter"].backend
    )
    assert request.output_dir == str(tmp_path / "sequences" / "corridor" / "artifact-a")
    assert request.identity == prepared.identity
    assert request.window.clock_id == "recording-clock"
    assert request.window.start_seconds == 1.25
    assert request.window.end_seconds == 2.5
    assert request.validation.on_problems == "warn"
    assert request.validation.allow_duplicate_timestamps is False
    assert request.hash_source is False
    assert request.config_identity == prepared.config.digest
    assert request.to_document()["window"]["clock_id"] == "recording-clock"


@pytest.mark.parametrize("policy", ["fail", "warn"])
@pytest.mark.parametrize("hash_source", ["true", "false"])
def test_policy_hash_and_explicit_output_round_trip(
    tmp_path: Path, policy: str, hash_source: str
) -> None:
    pytest.importorskip("contextmap.runtime")
    fields = _fields(tmp_path)
    fields["validation_on_problems"] = policy
    fields["hash_source"] = hash_source
    fields["output_dir"] = str(tmp_path / "chosen-output")

    request = (
        LocalIngestionRunner()
        .prepare(fields, workspace_root=tmp_path, profile="canonical/1")
        .request
    )

    assert request.validation.on_problems == policy
    assert request.hash_source is (hash_source == "true")
    assert request.output_dir == str(tmp_path / "chosen-output")


def test_core_composition_reports_missing_optional_dependency(tmp_path: Path) -> None:
    core = pytest.importorskip("contextmap.runtime")
    if find_spec("rosbags") is not None:
        pytest.skip("optional rosbags dependency is installed")
    source = tmp_path / "source.bag"
    source.write_bytes(b"not a real bag")
    runner = LocalIngestionRunner()
    prepared = runner.prepare(_fields(tmp_path), workspace_root=tmp_path, profile="canonical/1")

    with pytest.raises(core.BackendUnavailableError, match="optional module 'rosbags'"):
        core.Runtime(workspace=tmp_path).ingestion(prepared.config)


def test_window_validation_is_owned_by_core(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    fields = _fields(tmp_path)
    fields["window_end_seconds"] = fields["window_start_seconds"]

    with pytest.raises(ValueError, match="end_seconds must be > start_seconds"):
        LocalIngestionRunner().prepare(fields, workspace_root=tmp_path, profile="canonical/1")


def test_unknown_backend_and_calibration_file_are_explicit(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    runner = LocalIngestionRunner()
    fields = _fields(tmp_path)
    fields["source_backend"] = "dataset"
    with pytest.raises(ValueError, match=r"not reported by Runtime\.capabilities"):
        runner.prepare(fields, workspace_root=tmp_path, profile="canonical/1")

    fields = _fields(tmp_path)
    fields["calibration_path"] = str(tmp_path / "calibration.yaml")
    with pytest.raises(ValueError, match="calibration"):
        runner.prepare(fields, workspace_root=tmp_path, profile="canonical/1")
