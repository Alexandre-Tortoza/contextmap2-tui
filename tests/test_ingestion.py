from pathlib import Path
from types import SimpleNamespace

import pytest

from contextmap_tui.ingestion import (
    FakeIngestionRunner,
    IngestionResult,
    PreparedIngestion,
    UnavailableIngestionRunner,
    parse_required_topics,
)
from contextmap_tui.integration.ingestion import LocalIngestionRunner


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
    runner.cancel(prepared)

    result = runner.run(prepared, emit=lambda event: None)

    assert result.status == "cancelled"


def test_unexpected_service_exception_is_not_a_domain_result() -> None:
    class BrokenService:
        def run(self, request: object, **kwargs: object) -> None:
            del request, kwargs
            raise RuntimeError("programming bug")

    prepared = PreparedIngestion(
        request=object(),
        config=object(),
        runtime=SimpleNamespace(ingestion=lambda config: BrokenService()),
        cancellation=object(),
    )

    with pytest.raises(RuntimeError, match="programming bug"):
        LocalIngestionRunner().run(prepared, emit=lambda event: None)
