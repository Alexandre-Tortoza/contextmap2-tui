"""Interactive Ingestion configuration and execution console."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, ProgressBar, RichLog, Static

from contextmap_tui.client import ClientOperationError, ContextMapClient
from contextmap_tui.ingestion import (
    IngestionEvent,
    IngestionRequest,
    IngestionResult,
    IngestionRunner,
    parse_required_topics,
    validate_ingestion_request,
)
from contextmap_tui.screens.artifact import ArtifactScreen


class IngestionScreen(Screen[None]):
    """Configure, preflight and coordinate one Ingestion request."""

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
        self._cancel_event = Event()
        self._result: IngestionResult | None = None

    def compose(self) -> ComposeResult:
        """Compose explicit source, topic, time and synchronization controls."""
        with VerticalScroll(id="ingestion-content"):
            yield Static("Ingestion Console", id="ingestion-title")
            yield Static("", id="runner-availability")
            yield Input(value="ros1_bag", placeholder="source type", id="source-type")
            yield Input(placeholder="source path", id="source-path")
            yield Input(placeholder="sequence name", id="sequence-name")
            yield Input(value=str(self._workspace_root), id="output-workspace")
            yield Static("Topic mapping", classes="section-title")
            yield Input(placeholder="/camera/image_raw", id="topic-rgb")
            yield Input(placeholder="/camera/camera_info", id="topic-camera-info")
            yield Input(placeholder="/velodyne_points", id="topic-lidar")
            yield Input(placeholder="/imu/data", id="topic-imu")
            yield Input(placeholder="/odom", id="topic-pose")
            yield Input(
                value="rgb,lidar",
                placeholder="required topic fields, comma separated",
                id="required-topics",
            )
            yield Static("Time / calibration / synchronization", classes="section-title")
            yield Input(placeholder="optional clock_id", id="clock-id")
            yield Input(placeholder="optional canonical calibration path", id="calibration-path")
            yield Input(value="image", id="reference-modality")
            yield Input(value="50000000", id="tolerance-ns")
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
        """Show runner availability without pretending unsupported execution works."""
        availability = self._runner.availability()
        state = "available" if availability.available else "unavailable"
        self.query_one("#runner-availability", Static).update(
            f"Runner: {state}\n{availability.detail}"
        )
        self._refresh_effective_config()

    def action_back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    def _request(self) -> IngestionRequest:
        source_path = Path(self.query_one("#source-path", Input).value.strip()).expanduser()
        workspace_root = Path(self.query_one("#output-workspace", Input).value.strip()).expanduser()
        calibration_text = self.query_one("#calibration-path", Input).value.strip()
        clock_text = self.query_one("#clock-id", Input).value.strip()
        topics = {
            "rgb": self.query_one("#topic-rgb", Input).value.strip(),
            "camera_info": self.query_one("#topic-camera-info", Input).value.strip(),
            "lidar": self.query_one("#topic-lidar", Input).value.strip(),
            "imu": self.query_one("#topic-imu", Input).value.strip(),
            "pose": self.query_one("#topic-pose", Input).value.strip(),
        }
        topics = {name: value for name, value in topics.items() if value}
        tolerance_text = self.query_one("#tolerance-ns", Input).value.strip()
        try:
            tolerance = int(tolerance_text)
        except ValueError:
            tolerance = -1
        return IngestionRequest(
            source_type=self.query_one("#source-type", Input).value.strip(),
            source_path=source_path,
            sequence_name=self.query_one("#sequence-name", Input).value.strip(),
            workspace_root=workspace_root,
            topics=topics,
            required_topics=parse_required_topics(self.query_one("#required-topics", Input).value),
            timestamp_clock_id=clock_text or None,
            calibration_path=Path(calibration_text).expanduser() if calibration_text else None,
            reference_modality=self.query_one("#reference-modality", Input).value.strip(),
            tolerance_nanoseconds=tolerance,
        )

    def _refresh_effective_config(self) -> IngestionRequest:
        request = self._request()
        lines = ["Effective request:"]
        for key, value in request.effective_config().items():
            lines.append(f"{key}: {value}")
        self.query_one("#effective-config", Static).update("\n".join(lines))
        return request

    @on(Input.Changed)
    def _input_changed(self) -> None:
        self._refresh_effective_config()

    @on(Button.Pressed, "#preflight")
    def _preflight_pressed(self) -> None:
        request = self._refresh_effective_config()
        local_problems = validate_ingestion_request(request)
        if local_problems:
            self.query_one("#preflight-result", Static).update(
                "Local validation failed:\n" + "\n".join(f"- {item}" for item in local_problems)
            )
            return
        report = self._runner.preflight(request)
        lines = ["Preflight: OK" if report.ok else "Preflight: FAILED"]
        lines.extend(f"- problem: {item}" for item in report.problems)
        lines.extend(f"- warning: {item}" for item in report.warnings)
        if report.detail:
            lines.append(report.detail)
        self.query_one("#preflight-result", Static).update("\n".join(lines))

    @on(Button.Pressed, "#run-ingestion")
    def _run_pressed(self) -> None:
        request = self._refresh_effective_config()
        local_problems = validate_ingestion_request(request)
        if local_problems:
            self.query_one("#execution-status", Static).update(
                "Cannot run: " + "; ".join(local_problems)
            )
            return
        preflight = self._runner.preflight(request)
        if not preflight.ok:
            self.query_one("#execution-status", Static).update(
                "Cannot run: " + "; ".join(preflight.problems)
            )
            return
        self._cancel_event = Event()
        self._result = None
        self.query_one("#open-result", Button).disabled = True
        self.query_one("#ingestion-progress", ProgressBar).update(progress=0)
        self.query_one("#execution-log", RichLog).clear()
        self.query_one("#execution-status", Static).update("Running...")
        self._execute(request)

    @work(thread=True, exclusive=True, group="ingestion")
    def _execute(self, request: IngestionRequest) -> None:
        result = self._runner.run(
            request,
            emit=self._emit_from_worker,
            cancel_event=self._cancel_event,
        )
        self.app.call_from_thread(self._finish_execution, result)

    def _emit_from_worker(self, event: IngestionEvent) -> None:
        self.app.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: IngestionEvent) -> None:
        """Apply one progress event on the Textual event loop."""
        self.query_one("#execution-log", RichLog).write(f"[{event.phase}] {event.message}")
        if event.progress_percent is not None:
            progress = min(100.0, max(0.0, event.progress_percent))
            self.query_one("#ingestion-progress", ProgressBar).update(progress=progress)

    def _finish_execution(self, result: IngestionResult) -> None:
        self._result = result
        self.query_one("#execution-status", Static).update(f"Status: {result.status}")
        if result.status == "completed":
            self.query_one("#ingestion-progress", ProgressBar).update(progress=100)
        counts = ", ".join(
            f"{name}={count}" for name, count in sorted(result.observation_counts.items())
        )
        lines = [f"status: {result.status}"]
        if counts:
            lines.append(f"observations: {counts}")
        if result.warnings:
            lines.append(f"warnings: {len(result.warnings)}")
            lines.extend(f"- {warning}" for warning in result.warnings)
        if result.detail:
            lines.append(result.detail)

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
                self.query_one("#open-result", Button).disabled = False
        self.query_one("#ingestion-result", Static).update("\n".join(lines))

    @on(Button.Pressed, "#cancel-ingestion")
    def _cancel_pressed(self) -> None:
        self._cancel_event.set()
        self.query_one("#execution-status", Static).update("Cancellation requested...")

    @on(Button.Pressed, "#open-result")
    def _open_result_pressed(self) -> None:
        if self._result is None or self._result.artifact is None:
            return
        self.app.push_screen(ArtifactScreen(self._client, self._result.artifact))
