from typing import Any

import contextmap_tui.integration.runtime as runtime_module
from contextmap_tui.integration.runtime import LocalRuntimeGateway


def test_local_runtime_reports_missing_public_module(monkeypatch: Any) -> None:
    def fail(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(runtime_module, "import_module", fail)

    availability = LocalRuntimeGateway().availability()

    assert availability.available is False
    assert "contextmap.runtime is not present" in availability.detail


def test_local_runtime_does_not_guess_unverified_contract(monkeypatch: Any) -> None:
    class Module:
        API_VERSION = "future"

    monkeypatch.setattr(runtime_module, "import_module", lambda name: Module())

    availability = LocalRuntimeGateway().availability()

    assert availability.available is False
    assert availability.api_version == "future"
    assert "no verified adapter" in availability.detail
