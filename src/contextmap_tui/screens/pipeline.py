"""Pipeline configuration, preflight, execution and run-lineage console."""

from __future__ import annotations

from threading import Event
from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, ProgressBar, RichLog, Static

from contextmap_tui.runtime import (
    PipelineConfigView,
    PipelineRunResult,
    RunRecord,
    RuntimeEvent,
    RuntimeGateway,
    RuntimeOperationError,
)


class PipelineScreen(Screen[None]):
    """Operate only the topology/configuration exposed by the runtime gateway."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "back", "Back")]

    def __init__(self, runtime: RuntimeGateway) -> None:
        """Create a pipeline console over one runtime gateway."""
        super().__init__()
        self._runtime = runtime
        self._config: PipelineConfigView | None = None
        self._capability_ids: list[str] = []
        self._cancel_event = Event()
        self._runs: tuple[RunRecord, ...] = ()

    def compose(self) -> ComposeResult:
        """Compose capability, topology, execution and lineage surfaces."""
        with VerticalScroll(id="pipeline-content"):
            yield Static("Pipeline Console", id="pipeline-title")
            yield Static("", id="runtime-availability")
            yield Static("Capabilities", classes="section-title")
            yield DataTable(id="capability-table", cursor_type="row")
            yield Static("Effective pipeline", classes="section-title")
            yield DataTable(id="pipeline-table", cursor_type="row")
            with Horizontal():
                yield Button("Toggle optional stage", id="toggle-stage")
                yield Input(placeholder="backend id", id="backend-id")
                yield Button("Apply backend", id="apply-backend")
            yield Static("", id="pipeline-config-status")
            with Horizontal():
                yield Button("Preflight", id="pipeline-preflight", variant="primary")
                yield Button("Run pipeline", id="run-pipeline", variant="success")
                yield Button("Cancel", id="cancel-pipeline", variant="warning")
            yield Static("", id="pipeline-preflight-result")
            yield ProgressBar(total=100, show_eta=False, id="pipeline-progress")
            yield Static("", id="pipeline-execution-status")
            yield RichLog(id="pipeline-log", wrap=True, markup=False)
            yield Static("Persisted runs / lineage", classes="section-title")
            yield DataTable(id="run-table", cursor_type="row")
            yield Static("Select a persisted run.", id="run-detail")

    def on_mount(self) -> None:
        """Configure data tables and discover the runtime contract."""
        capabilities = self.query_one("#capability-table", DataTable)
        capabilities.add_columns("Stage", "Available", "Optional", "Backends", "Detail")
        pipeline = self.query_one("#pipeline-table", DataTable)
        pipeline.add_columns("Stage", "Enabled", "Backend", "Inputs")
        runs = self.query_one("#run-table", DataTable)
        runs.add_columns("Run", "Status", "Upstream", "Outputs")
        self._load_runtime()

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    def _load_runtime(self) -> None:
        availability = self._runtime.availability()
        state = "available" if availability.available else "unavailable"
        api = f" api={availability.api_version}" if availability.api_version else ""
        self.query_one("#runtime-availability", Static).update(
            f"Runtime: {state}{api}\n{availability.detail}"
        )
        if not availability.available:
            return
        try:
            capabilities = self._runtime.capabilities()
            self._config = self._runtime.pipeline_config()
        except RuntimeOperationError as error:
            self.query_one("#pipeline-config-status", Static).update(str(error))
            return

        capability_table = self.query_one("#capability-table", DataTable)
        capability_table.clear()
        self._capability_ids = []
        for item in capabilities:
            self._capability_ids.append(item.stage_id)
            capability_table.add_row(
                item.display_name,
                "yes" if item.available else "no",
                "yes" if item.optional else "no",
                ", ".join(item.backend_options) or "none",
                item.detail,
            )
        self._render_config()
        self._refresh_runs()

    def _render_config(self) -> None:
        table = self.query_one("#pipeline-table", DataTable)
        table.clear()
        if self._config is None:
            return
        for stage in self._config.stages:
            table.add_row(
                stage.stage_id,
                "yes" if stage.enabled else "no",
                stage.backend or "none",
                ", ".join(stage.inputs) or "none",
            )
        self.query_one("#pipeline-config-status", Static).update(
            f"config_id: {self._config.config_id}"
        )
        if self._config.stages:
            table.focus()

    def _selected_stage_id(self) -> str | None:
        if self._config is None:
            return None
        table = self.query_one("#pipeline-table", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._config.stages):
            return None
        return self._config.stages[row].stage_id

    @on(Button.Pressed, "#toggle-stage")
    def _toggle_stage(self) -> None:
        stage_id = self._selected_stage_id()
        if self._config is None or stage_id is None:
            return
        stage = next(item for item in self._config.stages if item.stage_id == stage_id)
        try:
            self._config = self._runtime.edit_stage(
                self._config,
                stage_id,
                enabled=not stage.enabled,
            )
        except RuntimeOperationError as error:
            self.notify(str(error), title="Invalid pipeline edit", severity="error")
            return
        self._render_config()

    @on(Button.Pressed, "#apply-backend")
    def _apply_backend(self) -> None:
        stage_id = self._selected_stage_id()
        backend = self.query_one("#backend-id", Input).value.strip()
        if self._config is None or stage_id is None or not backend:
            return
        try:
            self._config = self._runtime.edit_stage(
                self._config,
                stage_id,
                backend=backend,
            )
        except RuntimeOperationError as error:
            self.notify(str(error), title="Invalid backend", severity="error")
            return
        self._render_config()

    @on(Button.Pressed, "#pipeline-preflight")
    def _preflight(self) -> None:
        if self._config is None:
            self.query_one("#pipeline-preflight-result", Static).update(
                "Runtime configuration is unavailable."
            )
            return
        try:
            report = self._runtime.preflight(self._config)
        except RuntimeOperationError as error:
            self.query_one("#pipeline-preflight-result", Static).update(str(error))
            return
        lines = ["Preflight: OK" if report.ok else "Preflight: FAILED"]
        lines.extend(f"- problem: {item}" for item in report.problems)
        lines.extend(f"- warning: {item}" for item in report.warnings)
        if report.detail:
            lines.append(report.detail)
        self.query_one("#pipeline-preflight-result", Static).update("\n".join(lines))

    @on(Button.Pressed, "#run-pipeline")
    def _run_pressed(self) -> None:
        if self._config is None:
            self.query_one("#pipeline-execution-status", Static).update(
                "Cannot run: runtime configuration is unavailable."
            )
            return
        try:
            report = self._runtime.preflight(self._config)
        except RuntimeOperationError as error:
            self.query_one("#pipeline-execution-status", Static).update(str(error))
            return
        if not report.ok:
            self.query_one("#pipeline-execution-status", Static).update(
                "Cannot run: " + "; ".join(report.problems)
            )
            return

        self._cancel_event = Event()
        self.query_one("#pipeline-progress", ProgressBar).update(progress=0)
        self.query_one("#pipeline-log", RichLog).clear()
        self.query_one("#pipeline-execution-status", Static).update("Running...")
        self._execute(self._config)

    @work(thread=True, exclusive=True, group="pipeline")
    def _execute(self, config: PipelineConfigView) -> None:
        result = self._runtime.run(
            config,
            emit=self._emit_from_worker,
            cancel_event=self._cancel_event,
        )
        self.app.call_from_thread(self._finish_execution, result)

    def _emit_from_worker(self, event: RuntimeEvent) -> None:
        self.app.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: RuntimeEvent) -> None:
        self.query_one("#pipeline-log", RichLog).write(f"[{event.stage_id}] {event.message}")
        if event.progress_percent is not None:
            progress = min(100.0, max(0.0, event.progress_percent))
            self.query_one("#pipeline-progress", ProgressBar).update(progress=progress)

    def _finish_execution(self, result: PipelineRunResult) -> None:
        if result.status == "completed":
            self.query_one("#pipeline-progress", ProgressBar).update(progress=100)
        lines = [f"Status: {result.status}"]
        if result.run_id:
            lines.append(f"run_id: {result.run_id}")
        if result.output_artifacts:
            lines.append("outputs: " + ", ".join(result.output_artifacts))
        if result.reused_artifacts:
            lines.append("reused: " + ", ".join(result.reused_artifacts))
        if result.detail:
            lines.append(result.detail)
        self.query_one("#pipeline-execution-status", Static).update("\n".join(lines))
        self._refresh_runs()

    @on(Button.Pressed, "#cancel-pipeline")
    def _cancel_pressed(self) -> None:
        self._cancel_event.set()
        self.query_one("#pipeline-execution-status", Static).update("Cancellation requested...")

    def _refresh_runs(self) -> None:
        try:
            self._runs = self._runtime.list_runs()
        except RuntimeOperationError:
            self._runs = ()
            return
        table = self.query_one("#run-table", DataTable)
        table.clear()
        for run in self._runs:
            table.add_row(
                run.run_id,
                run.status,
                str(len(run.upstream_artifacts)),
                str(len(run.output_artifacts)),
            )

    @on(DataTable.RowSelected, "#run-table")
    def _run_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if row < 0 or row >= len(self._runs):
            return
        self.query_one("#run-detail", Static).update(_format_run(self._runs[row]))


def _format_run(run: RunRecord) -> str:
    """Format only persisted lineage fields provided by the runtime."""
    config = ", ".join(f"{key}={value!r}" for key, value in sorted(run.effective_config.items()))
    metrics = ", ".join(f"{key}={value!r}" for key, value in sorted(run.metrics.items()))
    return (
        f"run_id: {run.run_id}\n"
        f"status: {run.status}\n"
        f"upstream: {', '.join(run.upstream_artifacts) or 'none'}\n"
        f"outputs: {', '.join(run.output_artifacts) or 'none'}\n"
        f"config: {config or 'none'}\n"
        f"metrics: {metrics or 'none'}\n"
        f"detail: {run.detail or 'none'}"
    )
