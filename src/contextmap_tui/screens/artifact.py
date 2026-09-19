"""Detailed textual explorer for one canonical sequence artifact."""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Static

from contextmap_tui.client import ClientOperationError, ContextMapClient
from contextmap_tui.models import (
    ArtifactRef,
    CalibrationView,
    DiagnosticsView,
    ObservationFilter,
    ObservationPage,
    ObservationView,
    ProvenanceView,
)

_PAGE_SIZE = 100


class ArtifactScreen(Screen[None]):
    """Inspect manifest, canonical observations, provenance and debug diagnostics."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "back", "Back"),
        ("r", "reload", "Reload"),
    ]

    def __init__(self, client: ContextMapClient, artifact: ArtifactRef) -> None:
        """Create an artifact explorer for one stable artifact reference."""
        super().__init__()
        self._client = client
        self._artifact = artifact
        self._offset = 0
        self._page = ObservationPage(items=(), total=0, offset=0, limit=_PAGE_SIZE)

    def compose(self) -> ComposeResult:
        """Compose overview, observation browser and metadata panels."""
        with VerticalScroll(id="artifact-content"):
            yield Static(
                f"{self._artifact.sequence_name} / {self._artifact.artifact_id}",
                id="artifact-title",
            )
            yield Static("", id="artifact-overview")
            yield Static("Observations", classes="section-title")
            with Horizontal():
                yield Input(placeholder="text / id / topic", id="filter-text")
                yield Input(placeholder="modality", id="filter-modality")
                yield Input(placeholder="sensor or frame", id="filter-sensor-frame")
                yield Button("Apply", id="apply-filter", variant="primary")
            with Horizontal():
                yield Button("Previous", id="previous-page")
                yield Button("Next", id="next-page")
                yield Static("", id="page-status")
            yield DataTable(id="observation-table", cursor_type="row")
            yield Static("Select an observation to inspect provenance.", id="observation-detail")
            yield Static("Provenance", classes="section-title")
            yield Static("", id="provenance-view")
            yield Static("Calibration", classes="section-title")
            yield Static("", id="calibration-view")
            yield Static("Diagnostics (debug evidence)", classes="section-title")
            yield Static("", id="diagnostics-view")

    def on_mount(self) -> None:
        """Initialize the observation table and load the persisted artifact."""
        table = self.query_one("#observation-table", DataTable)
        table.add_columns("ID", "Modality", "Sensor", "Frame", "Timestamp ns", "Clock")
        self.action_reload()

    def action_back(self) -> None:
        """Return to the workspace browser."""
        self.app.pop_screen()

    def action_reload(self) -> None:
        """Reload every view from the persisted artifact."""
        try:
            overview = self._client.artifact_overview(self._artifact)
            provenance = self._client.provenance(self._artifact)
            calibration = self._client.calibration(self._artifact)
            diagnostics = self._client.diagnostics(self._artifact)
        except ClientOperationError as error:
            self.notify(str(error), title="Artifact error", severity="error")
            return

        integrity = (
            "OK" if overview.integrity_ok else f"{len(overview.integrity_problems)} problem(s)"
        )
        counts = ", ".join(
            f"{name}={count}" for name, count in sorted(overview.observation_counts.items())
        )
        problems = ""
        if overview.integrity_problems:
            problems = "\n" + "\n".join(f"- {item}" for item in overview.integrity_problems)
        self.query_one("#artifact-overview", Static).update(
            f"Schema: {overview.schema_version}\n"
            f"Created: {overview.created_at}\n"
            f"Observations: {counts}\n"
            f"Files: {overview.file_count} ({overview.total_size_bytes} bytes)\n"
            f"Integrity: {integrity}{problems}"
        )
        self.query_one("#provenance-view", Static).update(_format_provenance(provenance))
        self.query_one("#calibration-view", Static).update(_format_calibration(calibration))
        self.query_one("#diagnostics-view", Static).update(_format_diagnostics(diagnostics))
        self._offset = 0
        self._load_observations()

    def _criteria(self) -> ObservationFilter:
        return ObservationFilter(
            text=self.query_one("#filter-text", Input).value,
            modality=self.query_one("#filter-modality", Input).value.strip(),
            sensor_or_frame=self.query_one("#filter-sensor-frame", Input).value,
        )

    def _load_observations(self) -> None:
        try:
            self._page = self._client.observations(
                self._artifact,
                self._criteria(),
                offset=self._offset,
                limit=_PAGE_SIZE,
            )
        except ClientOperationError as error:
            self.notify(str(error), title="Observation error", severity="error")
            return

        table = self.query_one("#observation-table", DataTable)
        table.clear()
        for item in self._page.items:
            table.add_row(
                item.observation_id,
                item.modality,
                item.sensor_id,
                item.frame_id,
                str(item.timestamp_nanoseconds),
                item.clock_id,
            )
        end = min(self._page.offset + len(self._page.items), self._page.total)
        start = self._page.offset + 1 if self._page.items else 0
        self.query_one("#page-status", Static).update(f"{start}-{end} of {self._page.total}")
        self.query_one("#observation-detail", Static).update(
            "Select an observation to inspect provenance."
        )

    @on(Button.Pressed, "#apply-filter")
    def _apply_filter(self) -> None:
        self._offset = 0
        self._load_observations()

    @on(Input.Submitted)
    def _filter_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {"filter-text", "filter-modality", "filter-sensor-frame"}:
            self._offset = 0
            self._load_observations()

    @on(Button.Pressed, "#previous-page")
    def _previous_page(self) -> None:
        self._offset = max(0, self._offset - _PAGE_SIZE)
        self._load_observations()

    @on(Button.Pressed, "#next-page")
    def _next_page(self) -> None:
        if self._offset + _PAGE_SIZE < self._page.total:
            self._offset += _PAGE_SIZE
            self._load_observations()

    @on(DataTable.RowSelected, "#observation-table")
    def _observation_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._page.items):
            return
        self.query_one("#observation-detail", Static).update(
            _format_observation(self._page.items[event.cursor_row])
        )


def _format_observation(item: ObservationView) -> str:
    metadata = ", ".join(f"{key}={value!r}" for key, value in sorted(item.raw_metadata.items()))
    return (
        f"observation_id: {item.observation_id}\n"
        f"modality: {item.modality}\n"
        f"sensor_id: {item.sensor_id}\n"
        f"frame_id: {item.frame_id}\n"
        f"timestamp: {item.timestamp_nanoseconds} ns ({item.clock_id})\n"
        f"calibration_id: {item.calibration_id or 'none'}\n"
        f"source: {item.source_type} {item.source_path}\n"
        f"topic: {item.source_topic or 'none'}\n"
        f"message_index: {item.source_message_index}\n"
        f"raw_metadata: {metadata or 'none'}"
    )


def _format_provenance(view: ProvenanceView | None) -> str:
    if view is None:
        return "Not present in this artifact."
    return (
        f"source_type: {view.source_type}\n"
        f"source_path: {view.source_path}\n"
        f"source_content_hash: {view.source_content_hash or 'none'}\n"
        f"configuration_hash: {view.configuration_hash or 'none'}\n"
        f"content_identity: {view.content_identity}\n"
        f"adapter_type: {view.adapter_type or 'none'}\n"
        f"code_version: {view.code_version or 'none'}\n"
        f"synchronization_policy: {view.synchronization_policy or 'none'}\n"
        f"warnings: {len(view.warnings)}"
    )


def _format_calibration(view: CalibrationView | None) -> str:
    if view is None:
        return "Not present in this artifact."
    lines = [f"schema_version: {view.schema_version}", f"entries: {len(view.entries)}"]
    for entry in view.entries:
        lines.append(
            f"- {entry.calibration_id}: sensor={entry.sensor_id}, "
            f"frame={entry.frame_id}, camera={entry.camera_model}"
        )
    lines.append(f"static_transforms: {len(view.static_transforms)}")
    for transform in view.static_transforms:
        lines.append(
            f"- T_{transform.parent_frame}_{transform.child_frame}: "
            f"t={transform.translation}, q_xyzw={transform.rotation_xyzw}"
        )
    return "\n".join(lines)


def _format_diagnostics(view: DiagnosticsView | None) -> str:
    if view is None:
        return "Not present. Diagnostics are optional debug evidence."
    lines = [
        f"warnings: {view.warning_count}",
        f"source_types: {', '.join(view.source_types) or 'none'}",
        f"sync decisions: {len(view.decisions)}",
        f"dropped events: {len(view.dropped_events)}",
        f"calibration_ids: {', '.join(view.calibration_ids) or 'none'}",
        f"frames: {', '.join(view.frame_ids) or 'none'}",
        f"static_transforms: {view.static_transform_count}",
    ]
    if view.synchronization_status_counts:
        statuses = ", ".join(
            f"{name}={count}"
            for name, count in sorted(view.synchronization_status_counts.items())
        )
        lines.append(f"sync status: {statuses}")
    if view.warnings:
        lines.extend(f"- warning: {warning}" for warning in view.warnings)
    if view.dropped_events:
        lines.extend(
            f"- dropped {event.observation_id} ({event.modality}): {event.reason}"
            for event in view.dropped_events
        )
    return "\n".join(lines)
