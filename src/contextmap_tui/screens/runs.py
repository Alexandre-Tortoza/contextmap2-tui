"""Read-only inspector of persisted runtime runs and their recorded lineage."""

from __future__ import annotations

from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from contextmap_tui.runtime import RuntimeGateway, RuntimeOperationError
from contextmap_tui.screens.runtime_text import record_text, run_stage_row, summary_row


class RunsScreen(Screen[None]):
    """List ``Runtime.list_runs`` and inspect one run through ``Runtime.inspect_run``."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "back", "Back"),
        ("r", "reload", "Reload"),
    ]

    def __init__(self, runtime: RuntimeGateway, *, select: str | None = None) -> None:
        """Create the inspector; ``select`` is an exact run directory to open first."""
        super().__init__()
        self._runtime = runtime
        self._summaries: tuple[Any, ...] = ()
        self._select = select

    def compose(self) -> ComposeResult:
        """Compose the run list and the persisted record detail."""
        with VerticalScroll(id="runs-content"):
            yield Static("Persisted runs", id="runs-title")
            yield Static("", markup=False, id="runs-status")
            yield DataTable(id="runs-table", cursor_type="row")
            yield Static("Recorded stages", classes="section-title")
            yield DataTable(id="run-stages-table", cursor_type="row")
            yield Static("Select a run.", markup=False, id="run-record")

    def on_mount(self) -> None:
        """Configure tables and list the runs."""
        self.query_one("#runs-table", DataTable).add_columns(
            "Dataset",
            "Run",
            "Readable",
            "Status",
            "Interrupted",
            "Created",
            "Updated",
            "Resumed from",
            "Failure / error",
        )
        self.query_one("#run-stages-table", DataTable).add_columns(
            "Stage", "Outcome", "Inputs", "Output", "Reuse decision", "Elapsed"
        )
        self.action_reload()
        if self._select is not None:
            self._show(self._select)

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    def action_reload(self) -> None:
        """List the persisted runs again, in runtime order."""
        table = self.query_one("#runs-table", DataTable)
        table.clear()
        try:
            self._summaries = self._runtime.list_runs()
        except RuntimeOperationError as error:
            self._summaries = ()
            self.query_one("#runs-status", Static).update(str(error))
            return
        for summary in self._summaries:
            table.add_row(*summary_row(summary))
        self.query_one("#runs-status", Static).update(f"{len(self._summaries)} run(s)")

    @on(DataTable.RowSelected, "#runs-table")
    def _run_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if row < 0 or row >= len(self._summaries):
            return
        summary = self._summaries[row]
        if not summary.readable:
            self._clear_record(f"{summary.dataset}/{summary.run_id}: unreadable\n{summary.error}")
            return
        directory = self._runtime.run_directory(summary)
        # Um run_id só é único dentro do seu dataset: o diretório exato evita adivinhar.
        self._show(directory or summary.run_id)

    def _clear_record(self, text: str) -> None:
        self.query_one("#run-stages-table", DataTable).clear()
        self.query_one("#run-record", Static).update(text)

    def _show(self, run: str) -> None:
        try:
            record = self._runtime.inspect_run(run)
        except RuntimeOperationError as error:
            self._clear_record(str(error))
            return
        stages = self.query_one("#run-stages-table", DataTable)
        stages.clear()
        for stage in record.stages:
            stages.add_row(*run_stage_row(stage))
        self.query_one("#run-record", Static).update(record_text(record))
