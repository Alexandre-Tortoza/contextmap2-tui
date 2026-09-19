"""Presentation contracts for configuring and coordinating Ingestion."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Protocol, runtime_checkable

from contextmap_tui.models import ArtifactRef

_TOPIC_FIELDS = ("rgb", "camera_info", "lidar", "imu", "pose")
_SOURCE_TYPES = frozenset({"ros1_bag", "ros2_bag", "dataset"})
_REFERENCE_MODALITIES = frozenset({"image", "lidar", "imu", "external_pose"})


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    """Explicit, auditable input to one future core Ingestion run."""

    source_type: str
    source_path: Path
    sequence_name: str
    workspace_root: Path
    topics: Mapping[str, str]
    required_topics: frozenset[str] = frozenset()
    timestamp_clock_id: str | None = None
    calibration_path: Path | None = None
    reference_modality: str = "image"
    tolerance_nanoseconds: int = 50_000_000

    def effective_config(self) -> Mapping[str, object]:
        """Return a deterministic primitive projection for inspection."""
        return {
            "source_type": self.source_type,
            "source_path": str(self.source_path),
            "sequence_name": self.sequence_name,
            "workspace_root": str(self.workspace_root),
            "topics": dict(sorted(self.topics.items())),
            "required_topics": sorted(self.required_topics),
            "timestamp_clock_id": self.timestamp_clock_id,
            "calibration_path": (
                str(self.calibration_path) if self.calibration_path is not None else None
            ),
            "reference_modality": self.reference_modality,
            "tolerance_nanoseconds": self.tolerance_nanoseconds,
        }


@dataclass(frozen=True, slots=True)
class RunnerAvailability:
    """Whether a production-capable Ingestion runner is currently available."""

    available: bool
    detail: str


@dataclass(frozen=True, slots=True)
class IngestionPreflight:
    """Cheap validation result produced before decoding a full source."""

    ok: bool
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class IngestionEvent:
    """Progress evidence emitted by an Ingestion runner."""

    phase: str
    message: str
    progress_percent: float | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Terminal state of one requested Ingestion execution."""

    status: str
    artifact: ArtifactRef | None = None
    observation_counts: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    detail: str = ""


ProgressSink = Callable[[IngestionEvent], None]


@runtime_checkable
class IngestionRunner(Protocol):
    """Execution boundary implemented by a stable core orchestration API."""

    def availability(self) -> RunnerAvailability:
        """Report whether execution is supported in the installed core."""
        ...

    def preflight(self, request: IngestionRequest) -> IngestionPreflight:
        """Validate a request without performing the full run."""
        ...

    def run(
        self,
        request: IngestionRequest,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Execute Ingestion without placing source/scientific logic in the TUI."""
        ...


@dataclass(slots=True)
class UnavailableIngestionRunner:
    """Explicit production placeholder while the core lacks a public runner."""

    reason: str = (
        "The installed ContextMap2 core does not expose a stable public Ingestion runner yet."
    )

    def availability(self) -> RunnerAvailability:
        """Report the missing core capability."""
        return RunnerAvailability(available=False, detail=self.reason)

    def preflight(self, request: IngestionRequest) -> IngestionPreflight:
        """Return an explicit unsupported result."""
        del request
        return IngestionPreflight(ok=False, problems=(self.reason,), detail=self.reason)

    def run(
        self,
        request: IngestionRequest,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Reject execution rather than silently implementing a second engine."""
        del request, emit, cancel_event
        return IngestionResult(status="unsupported", detail=self.reason)


@dataclass(slots=True)
class FakeIngestionRunner:
    """Deterministic runner for headless TUI tests."""

    result: IngestionResult
    preflight_result: IngestionPreflight = IngestionPreflight(ok=True)
    events: Sequence[IngestionEvent] = ()
    available: bool = True

    def availability(self) -> RunnerAvailability:
        """Return deterministic availability."""
        return RunnerAvailability(
            available=self.available,
            detail="deterministic fake runner" if self.available else "fake runner unavailable",
        )

    def preflight(self, request: IngestionRequest) -> IngestionPreflight:
        """Return the configured preflight result."""
        del request
        return self.preflight_result

    def run(
        self,
        request: IngestionRequest,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Emit configured progress and return configured result."""
        del request
        if cancel_event.is_set():
            return IngestionResult(status="cancelled", detail="cancelled before execution")
        for event in self.events:
            if cancel_event.is_set():
                return IngestionResult(status="cancelled", detail="cancelled during execution")
            emit(event)
        return self.result


def validate_ingestion_request(request: IngestionRequest) -> tuple[str, ...]:
    """Validate only presentation/local constraints, leaving domain checks to the core."""
    problems: list[str] = []
    if request.source_type not in _SOURCE_TYPES:
        problems.append(f"unsupported source_type: {request.source_type!r}")
    if not request.sequence_name.strip():
        problems.append("sequence_name must not be empty")
    if not request.source_path.exists():
        problems.append(f"source path does not exist: {request.source_path}")
    if not request.workspace_root.exists():
        problems.append(f"workspace root does not exist: {request.workspace_root}")
    if request.calibration_path is not None and not request.calibration_path.exists():
        problems.append(f"calibration path does not exist: {request.calibration_path}")
    unknown_topics = request.required_topics - set(_TOPIC_FIELDS)
    if unknown_topics:
        problems.append(f"unknown required topic fields: {sorted(unknown_topics)}")
    for required in sorted(request.required_topics):
        if not request.topics.get(required, "").strip():
            problems.append(f"required topic {required!r} has no mapping")
    if request.reference_modality not in _REFERENCE_MODALITIES:
        problems.append(f"unsupported reference modality: {request.reference_modality!r}")
    if request.tolerance_nanoseconds < 0:
        problems.append("tolerance_nanoseconds must be >= 0")
    return tuple(problems)


def parse_required_topics(value: str) -> frozenset[str]:
    """Parse a comma-separated required topic list."""
    return frozenset(item.strip() for item in value.split(",") if item.strip())
