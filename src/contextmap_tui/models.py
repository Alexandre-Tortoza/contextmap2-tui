"""Presentation models used by the TUI gateway and screens."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Stable reference to one canonical sequence artifact."""

    sequence_name: str
    artifact_id: str
    path: Path
    readable: bool = True
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactOverview:
    """Compact artifact metadata and integrity state."""

    ref: ArtifactRef
    schema_version: str
    created_at: str
    observation_counts: Mapping[str, int]
    file_count: int
    total_size_bytes: int
    integrity_problems: tuple[str, ...] = ()

    @property
    def integrity_ok(self) -> bool:
        """Whether the core reader reported no integrity problems."""
        return not self.integrity_problems


@dataclass(frozen=True, slots=True)
class ObservationFilter:
    """UI-level filtering criteria over canonical observation metadata."""

    text: str = ""
    modality: str = ""
    sensor_or_frame: str = ""


@dataclass(frozen=True, slots=True)
class ObservationView:
    """Textual projection of one canonical SourceObservation."""

    observation_id: str
    modality: str
    sensor_id: str
    frame_id: str
    timestamp_nanoseconds: int
    clock_id: str
    calibration_id: str | None
    source_type: str
    source_path: str
    source_topic: str | None
    source_message_index: int | None
    raw_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObservationPage:
    """One deterministic page of filtered observations."""

    items: tuple[ObservationView, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class ProvenanceView:
    """Inspectable sequence provenance without exposing persistence internals."""

    source_type: str
    source_path: str
    source_content_hash: str | None
    configuration_hash: str | None
    content_identity: str
    adapter_type: str | None
    code_version: str | None
    calibration_source_hash: str | None
    synchronization_policy: str | None
    ingestion_config: Mapping[str, object]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrationEntryView:
    """Inspectable canonical calibration entry."""

    calibration_id: str
    sensor_id: str
    frame_id: str
    camera_model: str
    content_hash: str
    source_type: str
    source_path: str


@dataclass(frozen=True, slots=True)
class TransformView:
    """Inspectable static transform using the core T_A_B convention."""

    parent_frame: str
    child_frame: str
    translation: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class CalibrationView:
    """Canonical calibration inventory."""

    schema_version: str
    entries: tuple[CalibrationEntryView, ...]
    static_transforms: tuple[TransformView, ...]


@dataclass(frozen=True, slots=True)
class SynchronizationDecisionView:
    """One persisted synchronization decision."""

    frame_index: int
    anchor_observation_id: str
    modality: str
    selected_observation_id: str | None
    offset_nanoseconds: int | None
    status: str


@dataclass(frozen=True, slots=True)
class DroppedEventView:
    """One source observation not selected by synchronization."""

    observation_id: str
    modality: str
    reason: str


@dataclass(frozen=True, slots=True)
class DiagnosticsView:
    """Debug diagnostics kept distinct from contractual artifact evidence."""

    warning_count: int
    warnings: tuple[str, ...]
    source_types: tuple[str, ...]
    topic_counts: Mapping[str, int]
    synchronization_status_counts: Mapping[str, int]
    decisions: tuple[SynchronizationDecisionView, ...]
    dropped_events: tuple[DroppedEventView, ...]
    calibration_ids: tuple[str, ...]
    frame_ids: tuple[str, ...]
    static_transform_count: int


def observation_matches(item: ObservationView, criteria: ObservationFilter) -> bool:
    """Apply UI metadata filters without changing canonical ordering."""
    if criteria.modality and item.modality != criteria.modality:
        return False
    target = criteria.sensor_or_frame.casefold().strip()
    if target and target not in item.sensor_id.casefold() and target not in item.frame_id.casefold():
        return False
    text = criteria.text.casefold().strip()
    if not text:
        return True
    haystack = " ".join(
        value
        for value in (
            item.observation_id,
            item.modality,
            item.sensor_id,
            item.frame_id,
            item.clock_id,
            item.source_type,
            item.source_topic or "",
        )
    ).casefold()
    return text in haystack
