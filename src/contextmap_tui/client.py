"""Typed gateway between Textual presentation and ContextMap2 capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from contextmap_tui.models import (
    ArtifactOverview,
    ArtifactRef,
    CalibrationView,
    DiagnosticsView,
    ObservationFilter,
    ObservationPage,
    ObservationView,
    ProvenanceView,
    observation_matches,
)


class ClientOperationError(RuntimeError):
    """Raised when a gateway operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class ClientStatus:
    """Minimal information the application shell can show about its backend."""

    name: str
    connected: bool
    detail: str


@runtime_checkable
class ContextMapClient(Protocol):
    """Presentation-facing gateway over public ContextMap2 APIs."""

    def status(self) -> ClientStatus:
        """Return a lightweight status for the currently configured backend."""
        ...

    def list_artifacts(self, workspace_root: Path) -> tuple[ArtifactRef, ...]:
        """Discover canonical sequence artifacts in deterministic order."""
        ...

    def artifact_overview(self, artifact: ArtifactRef) -> ArtifactOverview:
        """Return manifest/integrity information for one artifact."""
        ...

    def observations(
        self,
        artifact: ArtifactRef,
        criteria: ObservationFilter,
        *,
        offset: int,
        limit: int,
    ) -> ObservationPage:
        """Return a filtered deterministic page of canonical observations."""
        ...

    def provenance(self, artifact: ArtifactRef) -> ProvenanceView | None:
        """Return persisted sequence provenance, when available."""
        ...

    def calibration(self, artifact: ArtifactRef) -> CalibrationView | None:
        """Return canonical sequence calibration, when available."""
        ...

    def diagnostics(self, artifact: ArtifactRef) -> DiagnosticsView | None:
        """Return optional debug diagnostics, when available."""
        ...


@dataclass(slots=True)
class FakeContextMapClient:
    """Deterministic gateway used by application and headless UI tests."""

    backend_name: str = "fake"
    connected: bool = True
    detail: str = "deterministic test gateway"
    artifacts: tuple[ArtifactRef, ...] = ()
    overviews: dict[str, ArtifactOverview] = field(default_factory=dict)
    observation_items: dict[str, tuple[ObservationView, ...]] = field(default_factory=dict)
    provenances: dict[str, ProvenanceView | None] = field(default_factory=dict)
    calibrations: dict[str, CalibrationView | None] = field(default_factory=dict)
    diagnostics_by_artifact: dict[str, DiagnosticsView | None] = field(default_factory=dict)

    def status(self) -> ClientStatus:
        """Return deterministic status data."""
        return ClientStatus(
            name=self.backend_name,
            connected=self.connected,
            detail=self.detail,
        )

    def list_artifacts(self, workspace_root: Path) -> tuple[ArtifactRef, ...]:
        """Return configured artifact references; workspace is intentionally ignored."""
        del workspace_root
        return self.artifacts

    def artifact_overview(self, artifact: ArtifactRef) -> ArtifactOverview:
        """Return configured overview data."""
        try:
            return self.overviews[artifact.artifact_id]
        except KeyError as error:
            raise ClientOperationError(f"no fake overview for {artifact.artifact_id}") from error

    def observations(
        self,
        artifact: ArtifactRef,
        criteria: ObservationFilter,
        *,
        offset: int,
        limit: int,
    ) -> ObservationPage:
        """Filter and page configured ObservationView values deterministically."""
        items = self.observation_items.get(artifact.artifact_id, ())
        filtered = tuple(item for item in items if observation_matches(item, criteria))
        return ObservationPage(
            items=filtered[offset : offset + limit],
            total=len(filtered),
            offset=offset,
            limit=limit,
        )

    def provenance(self, artifact: ArtifactRef) -> ProvenanceView | None:
        """Return configured sequence provenance."""
        return self.provenances.get(artifact.artifact_id)

    def calibration(self, artifact: ArtifactRef) -> CalibrationView | None:
        """Return configured calibration."""
        return self.calibrations.get(artifact.artifact_id)

    def diagnostics(self, artifact: ArtifactRef) -> DiagnosticsView | None:
        """Return configured diagnostics."""
        return self.diagnostics_by_artifact.get(artifact.artifact_id)
