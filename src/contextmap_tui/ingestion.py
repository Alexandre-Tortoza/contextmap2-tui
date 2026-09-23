"""Presentation boundary for public ContextMap2 ingestion requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, Protocol, runtime_checkable

from contextmap_tui.models import ArtifactRef


@dataclass(frozen=True, slots=True)
class SourceBackendChoice:
    """One source adapter reported by Runtime capability discovery."""

    backend_id: str
    available: bool
    reasons: tuple[str, ...] = ()
    install_hint: str = ""


@dataclass(frozen=True, slots=True)
class IngestionDiscovery:
    """Public runtime choices needed to compose the ingestion form."""

    profiles: tuple[str, ...]
    backends: tuple[SourceBackendChoice, ...]
    topic_fields: tuple[str, ...]
    modalities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedIngestion:
    """Opaque public core request and its resolved runtime context."""

    request: Any
    config: Any
    runtime: Any

    @property
    def identity(self) -> str:
        """Return the identity computed by the core request."""
        return str(self.request.identity)

    @property
    def preview(self) -> Mapping[str, object]:
        """Expose the core's own request document plus publication location."""
        return {
            "request_identity": self.identity,
            "artifact_id": self.request.artifact_id,
            "output_dir": self.request.output_dir,
            **self.request.to_document(),
        }


@dataclass(frozen=True, slots=True)
class RunnerAvailability:
    """Whether a public ingestion runner can be used in this environment."""

    available: bool
    detail: str


@dataclass(frozen=True, slots=True)
class IngestionPreflight:
    """Presentation projection of the core's preflight report."""

    ok: bool
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class IngestionEvent:
    """Structured progress event projected for Textual."""

    phase: str
    message: str
    progress_percent: float | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Terminal state shown by the console."""

    status: str
    artifact: ArtifactRef | None = None
    observation_counts: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    detail: str = ""


ProgressSink = Callable[[IngestionEvent], None]


@runtime_checkable
class IngestionRunner(Protocol):
    """Presentation-facing boundary over public runtime ingestion."""

    def availability(self) -> RunnerAvailability:
        """Report whether the public service is installed."""
        ...

    def discover(self, workspace_root: Path, *, profile: str) -> IngestionDiscovery:
        """Return options from public runtime/capability contracts."""
        ...

    def prepare(
        self,
        fields: Mapping[str, str],
        *,
        workspace_root: Path,
        profile: str,
    ) -> PreparedIngestion:
        """Build a public core request from raw form values."""
        ...

    def preflight(self, prepared: PreparedIngestion) -> IngestionPreflight:
        """Validate the public request through the core service."""
        ...

    def run(
        self,
        prepared: PreparedIngestion,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Execute the public request outside the Textual event loop."""
        ...


@dataclass(slots=True)
class UnavailableIngestionRunner:
    """Explicit fallback when the installed core lacks its public service."""

    reason: str = "The installed ContextMap2 core has no public Ingestion service."

    def availability(self) -> RunnerAvailability:
        """Report why no public service is available."""
        return RunnerAvailability(available=False, detail=self.reason)

    def discover(self, workspace_root: Path, *, profile: str) -> IngestionDiscovery:
        """Return no selectable backend."""
        del workspace_root, profile
        return IngestionDiscovery((), (), (), ())

    def prepare(
        self,
        fields: Mapping[str, str],
        *,
        workspace_root: Path,
        profile: str,
    ) -> PreparedIngestion:
        """Reject a request when the public service is absent."""
        del fields, workspace_root, profile
        raise RuntimeError(self.reason)

    def preflight(self, prepared: PreparedIngestion) -> IngestionPreflight:
        """Return an explicit unsupported result."""
        del prepared
        return IngestionPreflight(ok=False, problems=(self.reason,), detail=self.reason)

    def run(
        self,
        prepared: PreparedIngestion,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Never construct an alternate ingestion engine."""
        del prepared, emit, cancel_event
        return IngestionResult(status="unsupported", detail=self.reason)


@dataclass(slots=True)
class FakeIngestionRunner:
    """Deterministic presentation boundary for headless UI tests."""

    result: IngestionResult
    preflight_result: IngestionPreflight = IngestionPreflight(ok=True)
    events: Sequence[IngestionEvent] = ()
    available: bool = True
    prepared_fields: Mapping[str, str] | None = None

    def availability(self) -> RunnerAvailability:
        """Report deterministic test availability."""
        return RunnerAvailability(
            available=self.available,
            detail="deterministic fake runner" if self.available else "fake runner unavailable",
        )

    def discover(self, workspace_root: Path, *, profile: str) -> IngestionDiscovery:
        """Provide stable choices to exercise the form without the core."""
        del workspace_root, profile
        return IngestionDiscovery(
            profiles=("canonical/1",),
            backends=(SourceBackendChoice("ros1_bag", True),),
            topic_fields=("rgb", "camera_info", "lidar", "imu", "pose"),
            modalities=("image", "lidar", "imu", "external_pose"),
        )

    def prepare(
        self,
        fields: Mapping[str, str],
        *,
        workspace_root: Path,
        profile: str,
    ) -> PreparedIngestion:
        """Echo presentation values through a fake core-shaped request."""
        del workspace_root, profile
        self.prepared_fields = dict(fields)
        request = SimpleNamespace(
            identity="fake-request",
            artifact_id=fields.get("artifact_id", "fake-artifact"),
            output_dir=fields.get("output_dir", ""),
            to_document=lambda: dict(fields),
        )
        return PreparedIngestion(request=request, config=None, runtime=None)

    def preflight(self, prepared: PreparedIngestion) -> IngestionPreflight:
        """Return the configured report."""
        del prepared
        return self.preflight_result

    def run(
        self,
        prepared: PreparedIngestion,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Emit configured progress and return the configured result."""
        del prepared
        if cancel_event.is_set():
            return IngestionResult(status="cancelled", detail="cancelled before execution")
        for event in self.events:
            if cancel_event.is_set():
                return IngestionResult(status="cancelled", detail="cancelled during execution")
            emit(event)
        return self.result


def parse_required_topics(value: str) -> frozenset[str]:
    """Parse a comma-separated presentation field."""
    return frozenset(item.strip() for item in value.split(",") if item.strip())
