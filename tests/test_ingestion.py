from pathlib import Path
from threading import Event

import pytest

from contextmap_tui.ingestion import (
    FakeIngestionRunner,
    IngestionResult,
    UnavailableIngestionRunner,
    parse_required_topics,
)


def test_required_topics_are_only_parsed_as_form_input() -> None:
    assert parse_required_topics(" rgb, lidar, rgb ") == frozenset({"rgb", "lidar"})


def test_unavailable_runner_never_falls_back_to_tui_engine(tmp_path: Path) -> None:
    runner = UnavailableIngestionRunner("core runner missing")

    assert runner.availability().available is False
    assert runner.discover(tmp_path, profile="canonical/1").backends == ()
    with pytest.raises(RuntimeError, match="core runner missing"):
        runner.prepare({}, workspace_root=tmp_path, profile="canonical/1")


def test_fake_runner_honors_preexisting_cancellation(tmp_path: Path) -> None:
    runner = FakeIngestionRunner(result=IngestionResult(status="completed"))
    prepared = runner.prepare({}, workspace_root=tmp_path, profile="canonical/1")
    cancel = Event()
    cancel.set()

    result = runner.run(prepared, emit=lambda event: None, cancel_event=cancel)

    assert result.status == "cancelled"
