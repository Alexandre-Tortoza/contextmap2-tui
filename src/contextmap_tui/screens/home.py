"""Home screen for the ContextMap2 TUI."""

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Static

from contextmap_tui.client import ClientStatus, ContextMapClient
from contextmap_tui.ingestion import IngestionRunner
from contextmap_tui.runtime import RuntimeGateway
from contextmap_tui.screens.ingestion import IngestionScreen
from contextmap_tui.screens.pipeline import PipelineScreen
from contextmap_tui.screens.workspace import WorkspaceScreen


class HomeScreen(Screen[None]):
    """Application landing screen with stable top-level navigation hints."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("e", "explore", "Explore"),
        ("o", "operate", "Ingestion"),
        ("p", "pipeline", "Pipeline"),
    ]

    def __init__(
        self,
        status: ClientStatus,
        client: ContextMapClient,
        ingestion_runner: IngestionRunner,
        runtime_gateway: RuntimeGateway,
        workspace_root: Path,
    ) -> None:
        """Create the home screen from presentation and execution boundaries."""
        super().__init__()
        self._status = status
        self._client = client
        self._ingestion_runner = ingestion_runner
        self._runtime_gateway = runtime_gateway
        self._workspace_root = workspace_root

    def compose(self) -> ComposeResult:
        """Compose the landing screen."""
        connection = "connected" if self._status.connected else "unavailable"
        with VerticalScroll(id="home-content"):
            yield Label("ContextMap2", id="home-title")
            yield Static(
                "Explore [e]\n"
                "  Artifact and evidence inspection\n\n"
                "Ingestion [o]\n"
                "  Source configuration, preflight and execution\n\n"
                "Pipeline [p]\n"
                "  Runtime capabilities, topology, preflight, execution and lineage",
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
        """Open the Ingestion console."""
        self.app.push_screen(
            IngestionScreen(
                self._client,
                self._ingestion_runner,
                self._workspace_root,
            )
        )

    def action_pipeline(self) -> None:
        """Open the runtime pipeline console."""
        self.app.push_screen(PipelineScreen(self._runtime_gateway))
