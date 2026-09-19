"""Workspace browser for canonical ContextMap2 sequence artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Static

from contextmap_tui.client import ClientOperationError, ContextMapClient
from contextmap_tui.models import ArtifactRef
from contextmap_tui.screens.artifact import ArtifactScreen


class WorkspaceScreen(Screen[None]):
    """Discover and open canonical sequence artifacts from a local workspace."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "refresh", "Refresh"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, client: ContextMapClient, workspace_root: Path) -> None:
        """Create a workspace browser."""
        super().__init__()
        self._client = client
        self._workspace_root = workspace_root
        self._artifacts: tuple[ArtifactRef, ...] = ()

    def compose(self) -> ComposeResult:
        """Compose workspace path controls and artifact table."""
        with VerticalScroll(id="workspace-content"):
            yield Static("Artifact Explorer", id="workspace-title")
            with Horizontal():
                yield Input(value=str(self._workspace_root), id="workspace-path")
                yield Button("Refresh", id="refresh-workspace", variant="primary")
            yield Static("", id="workspace-status")
            yield DataTable(id="artifact-table", cursor_type="row")

    def on_mount(self) -> None:
        """Configure the table and perform initial discovery."""
        table = self.query_one("#artifact-table", DataTable)
        table.add_columns("Sequence", "Artifact", "Status", "Path")
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh artifact discovery from the selected workspace root."""
        path_text = self.query_one("#workspace-path", Input).value.strip()
        workspace_root = Path(path_text).expanduser()
        self._workspace_root = workspace_root
        table = self.query_one("#artifact-table", DataTable)
        table.clear()
        try:
            self._artifacts = self._client.list_artifacts(workspace_root)
        except (ClientOperationError, OSError) as error:
            self._artifacts = ()
            self.query_one("#workspace-status", Static).update(f"Discovery failed: {error}")
            return

        for artifact in self._artifacts:
            status = "ready" if artifact.readable else "unreadable"
            table.add_row(
                artifact.sequence_name,
                artifact.artifact_id,
                status,
                str(artifact.path),
            )
        self.query_one("#workspace-status", Static).update(
            f"{len(self._artifacts)} artifact(s) discovered in {workspace_root}"
        )

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    @on(Button.Pressed, "#refresh-workspace")
    def _refresh_pressed(self) -> None:
        self.action_refresh()

    @on(Input.Submitted, "#workspace-path")
    def _path_submitted(self) -> None:
        self.action_refresh()

    @on(DataTable.RowSelected, "#artifact-table")
    def _artifact_selected(self, event: DataTable.RowSelected) -> None:
        row_index = event.cursor_row
        if row_index < 0 or row_index >= len(self._artifacts):
            return
        artifact = self._artifacts[row_index]
        if not artifact.readable:
            self.notify(
                artifact.detail or "Artifact cannot be opened.",
                title="Unreadable artifact",
                severity="error",
            )
            return
        self.app.push_screen(ArtifactScreen(self._client, artifact))
