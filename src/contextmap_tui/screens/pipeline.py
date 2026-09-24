"""Pipeline console: runtime-resolved plan, edits, preflight and execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, ProgressBar, RichLog, Select, Static

from contextmap_tui.runtime import (
    RuntimeCancellation,
    RuntimeGateway,
    RuntimeOperationError,
    RuntimePipelineResolution,
    RuntimeReuse,
    RuntimeScope,
    StageCapability,
)
from contextmap_tui.screens.runs import RunsScreen
from contextmap_tui.screens.runtime_text import (
    edit_row,
    event_text,
    execution_text,
    plan_summary,
    preflight_text,
    stage_row,
    value_text,
)

_FINISHED_STAGE_EVENTS = frozenset({"stage_completed", "stage_reused", "stage_failed"})


def _csv(text: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in text.split(",") if item.strip())


class PipelineScreen(Screen[None]):
    """Render and change only what ``Runtime.resolve_config``/``resolve_plan`` report."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "back", "Back"),
        ("l", "runs", "Runs"),
    ]

    def __init__(self, runtime: RuntimeGateway) -> None:
        """Create a pipeline console over one runtime gateway."""
        super().__init__()
        self._runtime = runtime
        self._resolution: RuntimePipelineResolution | None = None
        self._capabilities: tuple[StageCapability, ...] = ()
        self._profile = ""
        self._cancellation: RuntimeCancellation | None = None
        self._planned: tuple[str, ...] = ()
        self._finished: set[str] = set()
        self._last_run_directory: str | None = None

    def compose(self) -> ComposeResult:
        """Compose capability, plan, edit, execution and progress surfaces."""
        with VerticalScroll(id="pipeline-content"):
            yield Static("Pipeline Console", id="pipeline-title")
            yield Static("", markup=False, id="runtime-availability")
            yield Select((), prompt="Runtime profile", id="runtime-profile")
            yield Static("Capabilities", classes="section-title")
            yield DataTable(id="capability-table", cursor_type="row")
            yield Static("", markup=False, id="capability-detail")
            yield Static("Resolved plan", classes="section-title")
            yield Static("", markup=False, id="plan-summary")
            yield DataTable(id="pipeline-table", cursor_type="row")
            yield Static("Runtime edits", classes="section-title")
            yield DataTable(id="edit-table", cursor_type="row")
            with Horizontal():
                yield Select((), prompt="allowed value", id="edit-choice")
                yield Input(placeholder="JSON value", id="edit-value")
                yield Button("Apply edit", id="apply-edit")
            yield Static("", markup=False, id="pipeline-config-status")
            yield Static("Execution scope", classes="section-title")
            with Horizontal():
                yield Input(placeholder="targets (comma separated)", id="scope-targets")
                yield Input(placeholder="catalog file", id="scope-catalog")
            with Horizontal():
                yield Input(placeholder="provide from run (id or directory)", id="provided-run")
                yield Input(placeholder="provided stages (comma separated)", id="provided-stages")
                yield Button("Apply scope", id="apply-scope")
            with Horizontal():
                yield Input(placeholder="reuse index directory", id="reuse-index")
                yield Input(placeholder="code identity", id="reuse-code")
                yield Input(placeholder="force recompute stages", id="reuse-force")
            with Horizontal():
                yield Button("Preflight", id="pipeline-preflight", variant="primary")
                yield Button("Run", id="run-pipeline", variant="success")
                yield Input(placeholder="resume run (id or directory)", id="resume-run")
                yield Button("Resume", id="resume-pipeline")
                yield Button("Cancel", id="cancel-pipeline", variant="warning")
            yield Static("", markup=False, id="pipeline-preflight-result")
            yield ProgressBar(total=100, show_eta=False, id="pipeline-progress")
            yield Static("", markup=False, id="pipeline-execution-status")
            yield Button("Inspect run", id="inspect-run", disabled=True)
            yield RichLog(id="pipeline-log", wrap=True, markup=False)

    def on_mount(self) -> None:
        """Configure data tables and discover the runtime contract."""
        self.query_one("#capability-table", DataTable).add_columns(
            "Stage", "Implemented", "Optional", "Default", "Components"
        )
        self.query_one("#pipeline-table", DataTable).add_columns(
            "Stage",
            "Capability",
            "In scope",
            "Available",
            "Inputs",
            "Output",
            "Backends",
            "Provided",
            "Stage digest",
        )
        self.query_one("#edit-table", DataTable).add_columns("Path", "Kind", "Current", "Allowed")
        self._load_runtime()

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    def action_runs(self) -> None:
        """Open the persisted-run inspector."""
        self.app.push_screen(RunsScreen(self._runtime))

    # --- discovery ---------------------------------------------------------------------

    def _load_runtime(self) -> None:
        availability = self._runtime.availability()
        state = "available" if availability.available else "unavailable"
        version = (
            f" version={availability.contextmap_version}" if availability.contextmap_version else ""
        )
        schemas = ", ".join(
            f"{name}={value}" for name, value in sorted(availability.schemas.items())
        )
        self.query_one("#runtime-availability", Static).update(
            f"Runtime: {state}{version}\n{availability.detail}\n"
            f"schemas: {schemas or 'unknown'}\n"
            f"profiles: {', '.join(availability.profiles) or 'none'}"
        )
        if not availability.available:
            return
        self._profile = availability.profiles[0] if availability.profiles else ""
        selector = self.query_one("#runtime-profile", Select)
        selector.set_options((profile, profile) for profile in availability.profiles)
        if self._profile:
            selector.value = self._profile
        self._load_profile()

    def _load_profile(self) -> None:
        self._load_capabilities()
        self._resolve(lambda: self._runtime.resolve_pipeline(profile=self._profile))

    def _load_capabilities(self) -> None:
        try:
            self._capabilities = self._runtime.capabilities(profile=self._profile)
        except RuntimeOperationError as error:
            self.query_one("#capability-detail", Static).update(str(error))
            return
        capability_table = self.query_one("#capability-table", DataTable)
        capability_table.clear()
        details = []
        for item in self._capabilities:
            capability_table.add_row(
                item.display_name,
                "yes" if item.implemented else "no",
                "yes" if item.optional else "no",
                "yes" if item.default_enabled else "no",
                str(len(item.components)),
            )
            details.append(
                f"{item.stage_id} ({item.capability or 'capability unknown'}): "
                f"{'implemented' if item.implemented else 'not implemented'}; "
                f"optional={item.optional}; default_enabled={item.default_enabled}"
            )
            if item.detail:
                details.append(f"  reason: {item.detail}")
            for component in item.components:
                details.append(f"  {component.component_id}: optional={component.optional}")
                for backend in component.backends:
                    details.append(
                        f"    {backend.backend_id}: "
                        f"{'available' if backend.available else 'unavailable'}"
                    )
                    details.extend(f"      reason: {reason}" for reason in backend.reasons)
                    if backend.requires:
                        details.append("      modules: " + ", ".join(backend.requires))
                    if backend.secrets:
                        details.append("      secret names: " + ", ".join(backend.secrets))
                    if backend.install_hint:
                        details.append("      install: " + backend.install_hint)
        self.query_one("#capability-detail", Static).update("\n".join(details))

    @on(Select.Changed, "#runtime-profile")
    def _profile_changed(self) -> None:
        selected = self.query_one("#runtime-profile", Select).value
        if not isinstance(selected, str) or selected == self._profile:
            return
        self._profile = selected
        self._load_profile()

    # --- plan and edits ----------------------------------------------------------------

    def _resolve(self, resolve: Callable[[], RuntimePipelineResolution]) -> bool:
        """Replace the current resolution with the runtime's answer, or surface its refusal."""
        try:
            resolution = resolve()
        except RuntimeOperationError as error:
            self.query_one("#pipeline-config-status", Static).update(f"Rejected: {error}")
            self.notify(str(error), title="Runtime rejected the change", severity="error")
            return False
        self._resolution = resolution
        self._render_plan()
        return True

    def _render_plan(self) -> None:
        resolution = self._resolution
        if resolution is None:
            return
        plan = resolution.plan
        self.query_one("#plan-summary", Static).update(plan_summary(plan))
        stages = self.query_one("#pipeline-table", DataTable)
        stages.clear()
        for stage in plan.stages:
            stages.add_row(*stage_row(stage))
        edits = self.query_one("#edit-table", DataTable)
        edits.clear()
        for edit in plan.editable:
            edits.add_row(*edit_row(edit))
        overrides = ", ".join(resolution.overrides) or "none"
        self.query_one("#pipeline-config-status", Static).update(f"overrides: {overrides}")
        self._show_edit(self._selected_edit())

    def _selected_edit(self) -> Any | None:
        if self._resolution is None:
            return None
        editable = self._resolution.plan.editable
        row = self.query_one("#edit-table", DataTable).cursor_row
        if row < 0 or row >= len(editable):
            return None
        return editable[row]

    @on(DataTable.RowHighlighted, "#edit-table")
    def _edit_highlighted(self) -> None:
        self._show_edit(self._selected_edit())

    def _show_edit(self, edit: Any | None) -> None:
        choice = self.query_one("#edit-choice", Select)
        value = self.query_one("#edit-value", Input)
        if edit is None:
            choice.set_options(())
            return
        if edit.allowed is None:
            choice.set_options(())
            value.value = "" if edit.current is None else value_text(edit.current)
            return
        options = [(value_text(item), value_text(item)) for item in edit.allowed]
        choice.set_options(options)
        current = value_text(edit.current)
        if any(option == current for _, option in options):
            choice.value = current
        value.value = ""

    def _edit_value(self, edit: Any) -> tuple[bool, object]:
        if edit.allowed is not None:
            selected = self.query_one("#edit-choice", Select).value
            if not isinstance(selected, str):
                return False, None
            return True, json.loads(selected)
        text = self.query_one("#edit-value", Input).value.strip()
        if edit.kind == "text":
            # Texto livre: JSON quando válido, caso contrário a string literal.
            if not text:
                return True, None
            try:
                return True, json.loads(text)
            except json.JSONDecodeError:
                return True, text
        try:
            return True, json.loads(text) if text else None
        except json.JSONDecodeError as error:
            self.notify(f"invalid JSON value: {error}", title="Invalid edit", severity="error")
            return False, None

    @on(Button.Pressed, "#apply-edit")
    def _apply_edit(self) -> None:
        resolution = self._resolution
        edit = self._selected_edit()
        if resolution is None or edit is None:
            return
        ok, value = self._edit_value(edit)
        if not ok:
            return
        self._resolve(lambda: self._runtime.apply_edit(resolution, path=edit.path, value=value))

    # --- scope ---------------------------------------------------------------------------

    def _scope(self) -> RuntimeScope | None:
        targets = _csv(self.query_one("#scope-targets", Input).value)
        catalog = self.query_one("#scope-catalog", Input).value.strip() or None
        run = self.query_one("#provided-run", Input).value.strip()
        stages = _csv(self.query_one("#provided-stages", Input).value)
        provided: dict[str, Any] = {}
        if run or stages:
            if not (run and stages):
                self.notify("provide both a run and its stages", severity="error")
                return None
            try:
                record = self._runtime.inspect_run(run)
            except RuntimeOperationError as error:
                self.notify(str(error), title="Cannot read provided run", severity="error")
                return None
            outputs = {stage.stage_id: stage.output for stage in record.stages}
            missing = [stage for stage in stages if outputs.get(stage) is None]
            if missing:
                self.notify(
                    f"run {record.run_id} records no output for: {', '.join(missing)}",
                    title="Cannot provide artifact",
                    severity="error",
                )
                return None
            provided = {stage: dict(outputs[stage]) for stage in stages}
        return RuntimeScope(targets=targets or None, provided=provided, catalog=catalog)

    @on(Button.Pressed, "#apply-scope")
    def _apply_scope(self) -> None:
        resolution = self._resolution
        scope = self._scope()
        if resolution is None or scope is None:
            return
        self._resolve(
            lambda: self._runtime.resolve_pipeline(
                profile=resolution.profile,
                files=resolution.files,
                overrides=resolution.overrides,
                scope=scope,
            )
        )

    def _reuse(self) -> RuntimeReuse | None:
        index = self.query_one("#reuse-index", Input).value.strip()
        if not index:
            return None
        return RuntimeReuse(
            index=index,
            code_identity=self.query_one("#reuse-code", Input).value.strip(),
            force=_csv(self.query_one("#reuse-force", Input).value),
        )

    # --- preflight and execution ---------------------------------------------------------

    def _run_preflight(self) -> Any | None:
        resolution = self._resolution
        result = self.query_one("#pipeline-preflight-result", Static)
        if resolution is None:
            result.update("Runtime configuration is unavailable.")
            return None
        try:
            report = self._runtime.preflight(resolution, reuse=self._reuse())
        except RuntimeOperationError as error:
            result.update(f"Preflight rejected: {error}")
            return None
        result.update(preflight_text(report))
        return report

    @on(Button.Pressed, "#pipeline-preflight")
    def _preflight(self) -> None:
        self._run_preflight()

    @on(Button.Pressed, "#run-pipeline")
    def _run_pressed(self) -> None:
        self._start(resume=None)

    @on(Button.Pressed, "#resume-pipeline")
    def _resume_pressed(self) -> None:
        resume = self.query_one("#resume-run", Input).value.strip()
        if not resume:
            self.notify("enter the run to resume", severity="error")
            return
        self._start(resume=resume)

    def _start(self, *, resume: str | None) -> None:
        status = self.query_one("#pipeline-execution-status", Static)
        resolution = self._resolution
        if resolution is None:
            status.update("Cannot run: runtime configuration is unavailable.")
            return
        report = self._run_preflight()
        if report is None:
            status.update("Cannot run: preflight did not complete.")
            return
        if not report.ok:
            # Nenhum modelo é carregado: o runtime já recusou a configuração.
            status.update("Cannot run: preflight is blocked.")
            return
        try:
            self._cancellation = self._runtime.cancellation()
        except RuntimeOperationError as error:
            status.update(str(error))
            return
        self._planned = tuple(report.stages)
        self._finished = set()
        self.query_one("#pipeline-progress", ProgressBar).update(progress=0)
        self.query_one("#pipeline-log", RichLog).clear()
        self.query_one("#inspect-run", Button).disabled = True
        status.update("Resuming..." if resume else "Running...")
        self._execute(resolution, self._cancellation, self._reuse(), resume)

    @work(thread=True, exclusive=True, group="pipeline")
    def _execute(
        self,
        resolution: RuntimePipelineResolution,
        cancellation: RuntimeCancellation,
        reuse: RuntimeReuse | None,
        resume: str | None,
    ) -> None:
        try:
            result = self._runtime.run(
                resolution,
                events=self._emit_from_worker,
                cancellation=cancellation,
                reuse=reuse,
                resume=resume,
            )
        except RuntimeOperationError as error:
            self.app.call_from_thread(self._execution_rejected, str(error))
            return
        self.app.call_from_thread(self._finish_execution, result)

    def _emit_from_worker(self, event: Any) -> None:
        self.app.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: Any) -> None:
        self.query_one("#pipeline-log", RichLog).write(event_text(event))
        if event.kind in _FINISHED_STAGE_EVENTS and event.stage_id is not None:
            self._finished.add(event.stage_id)
            if self._planned:
                progress = 100 * len(self._finished) / len(self._planned)
                self.query_one("#pipeline-progress", ProgressBar).update(progress=progress)

    def _execution_rejected(self, message: str) -> None:
        self.query_one("#pipeline-execution-status", Static).update(f"Rejected: {message}")

    def _finish_execution(self, result: Any) -> None:
        if result.status == "completed":
            self.query_one("#pipeline-progress", ProgressBar).update(progress=100)
        self._last_run_directory = result.record.directory
        self.query_one("#pipeline-execution-status", Static).update(execution_text(result))
        self.query_one("#inspect-run", Button).disabled = False

    @on(Button.Pressed, "#cancel-pipeline")
    def _cancel_pressed(self) -> None:
        if self._cancellation is None:
            return
        self._cancellation.cancel("cancelled from the TUI")
        self.query_one("#pipeline-execution-status", Static).update(
            "Cancellation requested; the runtime stops before its next stage..."
        )

    @on(Button.Pressed, "#inspect-run")
    def _inspect_pressed(self) -> None:
        if self._last_run_directory is not None:
            self.app.push_screen(RunsScreen(self._runtime, select=self._last_run_directory))
