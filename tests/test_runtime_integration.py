from types import SimpleNamespace
from typing import Any, ClassVar

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
