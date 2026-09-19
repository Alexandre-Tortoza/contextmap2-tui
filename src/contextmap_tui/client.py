"""Typed gateway between Textual presentation and ContextMap2 capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ClientStatus:
    """Minimal information the application shell can show about its backend."""

    name: str
    connected: bool
    detail: str


@runtime_checkable
class ContextMapClient(Protocol):
    """Presentation-facing gateway.

    The interface deliberately starts small and grows only when a screen has a
    concrete information need. Implementations may adapt public ContextMap2 APIs,
    while tests can provide deterministic fakes with no core checkout installed.
    """

    def status(self) -> ClientStatus:
        """Return a lightweight status for the currently configured backend."""
        ...


@dataclass(slots=True)
class FakeContextMapClient:
    """Deterministic gateway used by application and headless UI tests."""

    backend_name: str = "fake"
    connected: bool = True
    detail: str = "deterministic test gateway"

    def status(self) -> ClientStatus:
        """Return deterministic status data."""
        return ClientStatus(
            name=self.backend_name,
            connected=self.connected,
            detail=self.detail,
        )
