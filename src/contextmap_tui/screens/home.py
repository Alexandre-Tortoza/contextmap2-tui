"""Home screen for the ContextMap2 TUI."""

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Static

from contextmap_tui.client import ClientStatus, ContextMapClient
from contextmap_tui.screens.workspace import WorkspaceScreen


class HomeScreen(Screen[None]):
    """Application landing screen with stable top-level navigation hints."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("e", "explore", "Explore"),
        ("o", "operate", "Operate"),
    ]

    def __init__(
        self,
        status: ClientStatus,
        client: ContextMapClient,
        workspace_root: Path,
    ) -> None:
        """Create the home screen from gateway and workspace information."""
        super().__init__()
        self._status = status
        self._client = client
        self._workspace_root = workspace_root

    def compose(self) -> ComposeResult:
        """Compose the landing screen."""
        connection = "connected" if self._status.connected else "unavailable"
        with VerticalScroll(id="home-content"):
            yield Label("ContextMap2", id="home-title")
            yield Static(
                "Explore\n"
                "  Artifact and evidence inspection\n\n"
                "Operate\n"
                "  Ingestion and pipeline execution (as core APIs become available)",
                id="home-actions",
            )
            yield Static(
                f"Backend: {self._status.name} [{connection}]\n{self._status.detail}",
                id="client-status",
            )

    def action_explore(self) -> None:
        """Open the canonical artifact workspace browser."""
        self.app.push_screen(WorkspaceScreen(self._client, self._workspace_root))

    def action_operate(self) -> None:
        """Report that execution consoles are not part of this milestone."""
        self.notify("Execution consoles depend on later milestones.", title="Operate")
