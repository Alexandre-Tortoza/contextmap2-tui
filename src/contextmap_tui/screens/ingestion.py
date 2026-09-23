"""Interactive Ingestion form over a public ContextMap2 request boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from textual import on, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, ProgressBar, RichLog, Select, Static

from contextmap_tui.client import ClientOperationError, ContextMapClient
from contextmap_tui.ingestion import (
    IngestionDiscovery,
    IngestionEvent,
    IngestionResult,
    IngestionRunner,
    PreparedIngestion,
)
from contextmap_tui.screens.artifact import ArtifactScreen


class IngestionScreen(Screen[None]):
    """Configure and coordinate one public core Ingestion request."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "back", "Back")]

    def __init__(
        self,
        client: ContextMapClient,
        runner: IngestionRunner,
        workspace_root: Path,
    ) -> None:
        """Create the console from presentation and execution boundaries."""
        super().__init__()
        self._client = client
        self._runner = runner
        self._workspace_root = workspace_root
        self._artifact_id = uuid4().hex
        self._ingestion_running = False
        self._active_prepared: PreparedIngestion | None = None
        self._result: IngestionResult | None = None
        self._prepared: PreparedIngestion | None = None
        self._discovery_error = ""
        try:
            self._discovery = runner.discover(workspace_root, profile="")
        except (ImportError, RuntimeError, ValueError) as error:
            self._discovery_error = f"{type(error).__name__}: {error}"
            self._discovery = IngestionDiscovery((), (), (), ())
        self._profile = self._discovery.profiles[0] if self._discovery.profiles else ""

    def compose(self) -> ComposeResult:
        """Compose controls from public runtime choices and core request fields."""
        with VerticalScroll(id="ingestion-content"):
            yield Static("Ingestion Console", id="ingestion-title")
            yield Static("", id="runner-availability")
            yield Select(
                ((name, name) for name in self._discovery.profiles),
                value=self._profile if self._profile else Select.NULL,
                prompt="Profile",
                id="profile",
            )
            yield Select(
                ((choice.backend_id, choice.backend_id) for choice in self._discovery.backends),
                prompt="Source adapter",
                id="source-backend",
            )
            yield Static("", id="source-options")
            yield Input(placeholder="source path", id="source-path")
            yield Input(placeholder="sequence name", id="sequence-name")
            yield Input(value=str(self._workspace_root), id="output-workspace")
            yield Input(value=self._artifact_id, id="artifact-id")
            yield Input(placeholder="optional final output directory", id="output-dir")
            yield Static("Topic mapping", classes="section-title")
            for name in self._discovery.topic_fields:
                yield Input(placeholder=name, id=f"topic-{name.replace('_', '-')}")
            yield Input(
                placeholder="required topic names, comma separated",
                id="required-topics",
            )
            yield Static("Clock and synchronization", classes="section-title")
            yield Input(placeholder="optional header clock id", id="clock-id")
            yield Select(
                ((name, name) for name in self._discovery.modalities),
                value="image" if "image" in self._discovery.modalities else Select.NULL,
                prompt="Reference modality",
                id="reference-modality",
            )
            yield Input(value="50000000", id="tolerance-ns")
            yield Static("Source window uses recording time, not the header clock.")
            yield Input(placeholder="optional recording clock id", id="window-clock-id")
            yield Input(placeholder="optional window start seconds", id="window-start")
            yield Input(placeholder="optional window end seconds", id="window-end")
            yield Static("Validation and provenance", classes="section-title")
            yield Select(
                (("Fail on problems", "fail"), ("Warn on problems", "warn")),
                value="fail",
                allow_blank=False,
                id="validation-policy",
            )
            yield Checkbox("Allow duplicate timestamps", value=True, id="allow-duplicates")
            yield Checkbox("Hash source content", value=True, id="hash-source")
            yield Static(
                "External calibration files are unavailable: the public core accepts "
                "CalibrationSet but exposes no general file decoder.",
                id="calibration-status",
            )
            yield Static("", id="effective-config")
            yield Static("", id="preflight-result")
            with Horizontal():
                yield Button("Preflight", id="preflight", variant="primary")
                yield Button("Run Ingestion", id="run-ingestion", variant="success")
                yield Button("Cancel", id="cancel-ingestion", variant="warning")
            yield ProgressBar(total=100, show_eta=False, id="ingestion-progress")
            yield Static("", id="execution-status")
            yield RichLog(id="execution-log", wrap=True, markup=False)
            yield Static("", id="ingestion-result")
            yield Button("Open Artifact", id="open-result", disabled=True)

    def on_mount(self) -> None:
        """Show availability and the runtime-reported backend choices."""
        availability = self._runner.availability()
        state = "available" if availability.available else "unavailable"
        detail = self._discovery_error or availability.detail
        self.query_one("#runner-availability", Static).update(f"Runner: {state}\n{detail}")
        self._render_source_options()
        self._refresh_effective_config()

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    def _render_source_options(self) -> None:
        lines = []
        for choice in self._discovery.backends:
            state = "available" if choice.available else "unavailable"
            details = "; ".join((*choice.reasons, choice.install_hint))
            lines.append(f"{choice.backend_id}: {state}" + (f" — {details}" if details else ""))
        self.query_one("#source-options", Static).update("\n".join(lines))

    def _select_text(self, widget_id: str) -> str:
        value = self.query_one(widget_id, Select).value
        return value if isinstance(value, str) else ""

    def _fields(self) -> dict[str, str]:
        fields = {
            "source_backend": self._select_text("#source-backend"),
            "source_path": self.query_one("#source-path", Input).value.strip(),
            "sequence_name": self.query_one("#sequence-name", Input).value.strip(),
            "artifact_id": self.query_one("#artifact-id", Input).value.strip(),
            "output_dir": self.query_one("#output-dir", Input).value.strip(),
            "required_topics": self.query_one("#required-topics", Input).value,
            "timestamp_clock_id": self.query_one("#clock-id", Input).value.strip(),
            "reference_modality": self._select_text("#reference-modality"),
            "tolerance_nanoseconds": self.query_one("#tolerance-ns", Input).value.strip(),
            "window_clock_id": self.query_one("#window-clock-id", Input).value.strip(),
            "window_start_seconds": self.query_one("#window-start", Input).value.strip(),
            "window_end_seconds": self.query_one("#window-end", Input).value.strip(),
            "validation_on_problems": self._select_text("#validation-policy"),
            "allow_duplicate_timestamps": (
                "true" if self.query_one("#allow-duplicates", Checkbox).value else "false"
            ),
            "hash_source": "true" if self.query_one("#hash-source", Checkbox).value else "false",
        }
        for name in self._discovery.topic_fields:
            fields[f"topics.{name}"] = self.query_one(
                f"#topic-{name.replace('_', '-')}", Input
            ).value.strip()
        return fields

    def _refresh_effective_config(self) -> PreparedIngestion | None:
        workspace_text = self.query_one("#output-workspace", Input).value.strip()
        try:
            if not workspace_text:
                raise ValueError("workspace path must not be empty")
            prepared = self._runner.prepare(
                self._fields(),
                workspace_root=Path(workspace_text).expanduser(),
                profile=self._profile,
            )
        except (ValueError, RuntimeError, ImportError) as error:
            self._prepared = None
            self.query_one("#effective-config", Static).update(f"Request incomplete: {error}")
            return None
        self._prepared = prepared
        lines = ["Effective core request:"]
        lines.extend(f"{key}: {value}" for key, value in prepared.preview.items())
        self.query_one("#effective-config", Static).update("\n".join(lines))
        return prepared

    @on(Input.Changed)
    def _input_changed(self) -> None:
        self._refresh_effective_config()

    @on(Checkbox.Changed)
    def _checkbox_changed(self) -> None:
        self._refresh_effective_config()

    @on(Select.Changed, "#profile")
    def _profile_changed(self) -> None:
        profile = self._select_text("#profile")
        if not profile or profile == self._profile:
            return
        try:
            self._discovery = self._runner.discover(self._workspace_root, profile=profile)
        except (ValueError, RuntimeError, ImportError) as error:
            self.query_one("#effective-config", Static).update(f"Profile unavailable: {error}")
            return
        self._profile = profile
        self.query_one("#source-backend", Select).set_options(
            (choice.backend_id, choice.backend_id) for choice in self._discovery.backends
        )
        self._render_source_options()
        self._refresh_effective_config()

    @on(Select.Changed, "#source-backend")
    @on(Select.Changed, "#reference-modality")
    @on(Select.Changed, "#validation-policy")
    def _selection_changed(self) -> None:
        self._refresh_effective_config()

    @on(Button.Pressed, "#preflight")
    def _preflight_pressed(self) -> None:
        prepared = self._refresh_effective_config()
        if prepared is None:
            self.query_one("#preflight-result", Static).update("Complete the request first.")
            return
        report = self._runner.preflight(prepared)
        lines = ["Preflight: OK" if report.ok else "Preflight: FAILED"]
        if report.identity:
            lines.append(f"request identity: {report.identity}")
        lines.extend(f"- problem: {item}" for item in report.problems)
        lines.extend(f"- warning: {item}" for item in report.warnings)
        if report.capabilities:
            lines.append("source capabilities: " + json.dumps(report.capabilities, sort_keys=True))
        if report.detail:
            lines.append(report.detail)
        self.query_one("#preflight-result", Static).update("\n".join(lines))

    @on(Button.Pressed, "#run-ingestion")
    def _run_pressed(self) -> None:
        if self._ingestion_running:
            return
        prepared = self._refresh_effective_config()
        if prepared is None:
            self.query_one("#execution-status", Static).update("Complete the request first.")
            return
        preflight = self._runner.preflight(prepared)
        if not preflight.ok:
            self.query_one("#execution-status", Static).update(
                "Cannot run: " + "; ".join(preflight.problems)
            )
            return
        self._ingestion_running = True
        self._active_prepared = prepared
        self._result = None
        self.query_one("#run-ingestion", Button).disabled = True
        self.query_one("#preflight", Button).disabled = True
        self.query_one("#open-result", Button).disabled = True
        self.query_one("#ingestion-progress", ProgressBar).update(total=100, progress=0)
        self.query_one("#execution-log", RichLog).clear()
        self.query_one("#execution-status", Static).update("Running...")
        self._execute(prepared)

    @work(thread=True, exclusive=True, group="ingestion")
    def _execute(self, prepared: PreparedIngestion) -> None:
        try:
            result = self._runner.run(prepared, emit=self._emit_from_worker)
        except Exception as error:
            self.app.call_from_thread(self._execution_crashed, error)
            raise
        self.app.call_from_thread(self._finish_execution, result)

    def _execution_crashed(self, error: Exception) -> None:
        self._ingestion_running = False
        self._active_prepared = None
        self.query_one("#run-ingestion", Button).disabled = False
        self.query_one("#preflight", Button).disabled = False
        self.query_one("#execution-status", Static).update(
            f"Unexpected execution error (bug): {type(error).__name__}: {error}"
        )

    def _emit_from_worker(self, event: IngestionEvent) -> None:
        self.app.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: IngestionEvent) -> None:
        """Apply one progress event on the Textual event loop."""
        self.query_one("#execution-log", RichLog).write(
            json.dumps(
                {
                    "sequence": event.sequence,
                    "time": event.time,
                    "kind": event.kind,
                    "stage_id": event.stage_id,
                    "data": dict(event.data),
                },
                sort_keys=True,
            )
        )

    def _finish_execution(self, result: IngestionResult) -> None:
        self._ingestion_running = False
        self._active_prepared = None
        self.query_one("#run-ingestion", Button).disabled = False
        self.query_one("#preflight", Button).disabled = False
        self._result = result
        self.query_one("#execution-status", Static).update(f"Status: {result.status}")
        if result.status == "completed":
            self.query_one("#ingestion-progress", ProgressBar).update(total=100, progress=100)
        counts = ", ".join(
            f"{name}={count}" for name, count in sorted(result.observation_counts.items())
        )
        lines = [f"status: {result.status}"]
        if result.request_identity:
            lines.append(f"request identity: {result.request_identity}")
        if result.artifact_id:
            lines.append(f"artifact id: {result.artifact_id}")
        if result.artifact_path:
            lines.append(f"artifact path: {result.artifact_path}")
        if result.content_hash:
            lines.append(f"content hash: {result.content_hash}")
        if counts:
            lines.append(f"observations: {counts}")
        if result.warnings:
            lines.append(f"warnings: {len(result.warnings)}")
            lines.extend(f"- {warning}" for warning in result.warnings)
        if result.detail:
            lines.append(result.detail)
        if result.diagnostics:
            lines.append("diagnostics: " + json.dumps(result.diagnostics, default=str))
        if result.metrics:
            lines.append("metrics: " + json.dumps(result.metrics, default=str))
        if result.failure:
            lines.append("failure: " + json.dumps(result.failure, default=str))
        if result.artifact is not None and result.status == "completed":
            try:
                overview = self._client.artifact_overview(result.artifact)
            except ClientOperationError as error:
                lines.append(f"persisted artifact could not be reopened: {error}")
            else:
                lines.append(
                    f"artifact: {overview.ref.sequence_name}/{overview.ref.artifact_id} "
                    f"(integrity={'OK' if overview.integrity_ok else 'problems'})"
                )
                self.query_one("#open-result", Button).disabled = not overview.integrity_ok
        self.query_one("#ingestion-result", Static).update("\n".join(lines))

    @on(Button.Pressed, "#cancel-ingestion")
    def _cancel_pressed(self) -> None:
        if self._active_prepared is None:
            return
        self._runner.cancel(self._active_prepared)
        self.query_one("#execution-status", Static).update("Cancellation requested...")

    @on(Button.Pressed, "#open-result")
    def _open_result_pressed(self) -> None:
        if self._result is None or self._result.artifact is None:
            return
        self.app.push_screen(ArtifactScreen(self._client, self._result.artifact))
