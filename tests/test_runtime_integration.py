from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

import contextmap_tui.integration.runtime as runtime_module
from contextmap_tui.integration.runtime import LocalRuntimeGateway


def test_local_runtime_reports_missing_public_module(monkeypatch: Any) -> None:
    def fail(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(runtime_module, "import_module", fail)

    availability = LocalRuntimeGateway().availability()

    assert availability.available is False
    assert "contextmap.runtime is not present" in availability.detail


def test_local_runtime_does_not_use_guessed_api_version(monkeypatch: Any) -> None:
    class Status:
        contextmap_version = "0.8.0"
        schemas: ClassVar[dict[str, str]] = {"run": "2"}
        profiles = ("canonical/1",)

    class Runtime:
        def __init__(self, *, workspace: object) -> None:
            del workspace

        def status(self) -> Status:
            return Status()

    module = SimpleNamespace(API_VERSION="not-public", Runtime=Runtime)
    monkeypatch.setattr(runtime_module, "import_module", lambda name: module)

    availability = LocalRuntimeGateway().availability()

    assert availability.available
    assert availability.contextmap_version == "0.8.0"
    assert availability.schemas == {"run": "2"}
    assert availability.profiles == ("canonical/1",)


def test_unimplemented_stage_keeps_runtime_reason(monkeypatch: Any) -> None:
    stage = SimpleNamespace(
        stage_id="context_map",
        capability="context_map",
        implemented=False,
        reason="assembly is not a runtime stage yet",
        optional=True,
        default_enabled=False,
        components=(),
    )

    class Runtime:
        def __init__(self, *, workspace: object) -> None:
            del workspace

        def capabilities(self, *, profile: str) -> tuple[SimpleNamespace, ...]:
            assert profile == "canonical/9"
            return (stage,)

    module = SimpleNamespace(Runtime=Runtime, ConfigurationError=ValueError)
    monkeypatch.setattr(runtime_module, "import_module", lambda name: module)

    (found,) = LocalRuntimeGateway().capabilities(profile="canonical/9")

    assert found.implemented is False
    assert found.available is False
    assert found.detail == "assembly is not a runtime stage yet"


def test_context_map_stage_is_not_invented() -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway()
    for profile in ("canonical/1", "canonical/2"):
        ids = {stage.stage_id for stage in gateway.capabilities(profile=profile)}
        plan = gateway.resolve_pipeline(profile=profile).plan
        assert "context_map" not in ids
        assert "context_map" not in {stage.stage_id for stage in plan.stages}
