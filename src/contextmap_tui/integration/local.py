"""Local adapter over the public ContextMap2 Python API."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, cast

from contextmap_tui.client import ClientOperationError, ClientStatus
from contextmap_tui.models import (
    ArtifactOverview,
    ArtifactRef,
    CalibrationEntryView,
    CalibrationView,
    DiagnosticsView,
    DroppedEventView,
    ObservationFilter,
    ObservationPage,
    ObservationView,
    ProvenanceView,
    SynchronizationDecisionView,
    TransformView,
    observation_matches,
)

_PUBLIC_INGESTION_MODULE = "contextmap.ingestion"


class LocalContextMapClient:
    """Read local ContextMap2 artifacts using only the core public API."""

    def status(self) -> ClientStatus:
        """Report whether the public ingestion API can be imported."""
        try:
            self._ingestion()
        except ClientOperationError as error:
            return ClientStatus(name="contextmap", connected=False, detail=str(error))
        return ClientStatus(
            name="contextmap",
            connected=True,
            detail="public ContextMap2 ingestion API available",
        )

    def list_artifacts(self, workspace_root: Path) -> tuple[ArtifactRef, ...]:
        """Discover sequence artifacts and validate them by opening the core reader."""
        ingestion = self._ingestion()
        reader_type = ingestion.SequenceArtifactReader
        sequences_root = workspace_root / "sequences"
        if not sequences_root.is_dir():
            return ()

        result: list[ArtifactRef] = []
        for sequence_dir in sorted(path for path in sequences_root.iterdir() if path.is_dir()):
            for artifact_dir in sorted(path for path in sequence_dir.iterdir() if path.is_dir()):
                if artifact_dir.name.startswith(".tmp-"):
                    continue
                try:
                    reader = reader_type(artifact_dir)
                    manifest = reader.manifest
                    result.append(
                        ArtifactRef(
                            sequence_name=str(manifest.sequence_name),
                            artifact_id=str(manifest.artifact_id),
                            path=artifact_dir,
                        )
                    )
                except Exception as error:
                    result.append(
                        ArtifactRef(
                            sequence_name=sequence_dir.name,
                            artifact_id=artifact_dir.name,
                            path=artifact_dir,
                            readable=False,
                            detail=f"{type(error).__name__}: {error}",
                        )
                    )
        return tuple(result)

    def artifact_overview(self, artifact: ArtifactRef) -> ArtifactOverview:
        """Project manifest and reader integrity output into a presentation model."""
        reader = self._reader(artifact)
        manifest = reader.manifest
        inventory = tuple(manifest.file_inventory)
        return ArtifactOverview(
            ref=artifact,
            schema_version=str(manifest.schema_version),
            created_at=str(manifest.created_at),
            observation_counts=dict(manifest.observation_counts),
            file_count=len(inventory),
            total_size_bytes=sum(int(entry.size_bytes) for entry in inventory),
            integrity_problems=tuple(str(item) for item in reader.verify_integrity()),
        )

    def observations(
        self,
        artifact: ArtifactRef,
        criteria: ObservationFilter,
        *,
        offset: int,
        limit: int,
    ) -> ObservationPage:
        """Read canonical observations and return one filtered page."""
        if offset < 0 or limit <= 0:
            raise ClientOperationError("offset must be >= 0 and limit must be > 0")
        ingestion = self._ingestion()
        modality_of = ingestion.observation_modality
        reader = self._reader(artifact)
        items: list[ObservationView] = []
        for observation in reader.list_observations():
            provenance = observation.provenance
            view = ObservationView(
                observation_id=str(observation.observation_id),
                modality=str(modality_of(observation)),
                sensor_id=str(observation.sensor_id),
                frame_id=str(observation.frame_id),
                timestamp_nanoseconds=int(observation.timestamp.total_nanoseconds()),
                clock_id=str(observation.timestamp.clock_id),
                calibration_id=(
                    str(observation.calibration_id)
                    if observation.calibration_id is not None
                    else None
                ),
                source_type=str(provenance.source_type),
                source_path=str(provenance.source_path),
                source_topic=(
                    str(provenance.source_topic) if provenance.source_topic is not None else None
                ),
                source_message_index=provenance.source_message_index,
                raw_metadata=dict(provenance.raw_metadata),
            )
            if observation_matches(view, criteria):
                items.append(view)
        return ObservationPage(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            offset=offset,
            limit=limit,
        )

    def provenance(self, artifact: ArtifactRef) -> ProvenanceView | None:
        """Read sequence provenance through the public reader."""
        ingestion = self._ingestion()
        reader = self._reader(artifact)
        provenance = reader.read_provenance()
        if provenance is None:
            return None
        identity = ingestion.compute_content_identity(provenance)
        return ProvenanceView(
            source_type=str(provenance.source_type),
            source_path=str(provenance.source_path),
            source_content_hash=provenance.source_content_hash,
            configuration_hash=provenance.configuration_hash,
            content_identity=str(identity),
            adapter_type=provenance.adapter_type,
            code_version=provenance.code_version,
            calibration_source_hash=provenance.calibration_source_hash,
            synchronization_policy=provenance.synchronization_policy,
            ingestion_config=dict(provenance.ingestion_config),
            warnings=tuple(str(item) for item in provenance.warnings),
        )

    def calibration(self, artifact: ArtifactRef) -> CalibrationView | None:
        """Read canonical calibration and static transforms through the core reader."""
        reader = self._reader(artifact)
        calibration = reader.read_calibration()
        if calibration is None:
            return None
        entries = tuple(
            CalibrationEntryView(
                calibration_id=str(entry.calibration_id),
                sensor_id=str(entry.sensor_id),
                frame_id=str(entry.frame_id),
                camera_model=(
                    type(entry.camera_model).__name__ if entry.camera_model is not None else "none"
                ),
                content_hash=str(entry.content_hash),
                source_type=str(entry.provenance.source_type),
                source_path=str(entry.provenance.source_path),
            )
            for _, entry in sorted(calibration.entries.items(), key=lambda pair: str(pair[0]))
        )
        transforms = tuple(
            TransformView(
                parent_frame=str(transform.parent_frame),
                child_frame=str(transform.child_frame),
                translation=cast(
                    tuple[float, float, float],
                    tuple(float(value) for value in transform.translation),
                ),
                rotation_xyzw=cast(
                    tuple[float, float, float, float],
                    tuple(float(value) for value in transform.rotation),
                ),
            )
            for transform in calibration.static_transforms
        )
        return CalibrationView(
            schema_version=str(calibration.schema_version),
            entries=entries,
            static_transforms=transforms,
        )

    def diagnostics(self, artifact: ArtifactRef) -> DiagnosticsView | None:
        """Read optional debug diagnostics without making them contractual inputs."""
        ingestion = self._ingestion()
        reader = self._reader(artifact)
        diagnostics = reader.read_diagnostics()
        if diagnostics is None:
            return None
        summary = diagnostics.summary
        synchronization = diagnostics.synchronization
        decisions: tuple[SynchronizationDecisionView, ...] = ()
        dropped_events: tuple[DroppedEventView, ...] = ()
        if synchronization is not None:
            decisions = tuple(
                SynchronizationDecisionView(
                    frame_index=int(item.frame_index),
                    anchor_observation_id=str(item.anchor_observation_id),
                    modality=str(item.modality),
                    selected_observation_id=(
                        str(item.selected_observation_id)
                        if item.selected_observation_id is not None
                        else None
                    ),
                    offset_nanoseconds=item.offset_nanoseconds,
                    status=str(item.status),
                )
                for item in synchronization.decisions
            )
            modality_of = ingestion.observation_modality
            dropped_events = tuple(
                DroppedEventView(
                    observation_id=str(item.observation.observation_id),
                    modality=str(modality_of(item.observation)),
                    reason=str(item.reason),
                )
                for item in synchronization.dropped_events
            )
        return DiagnosticsView(
            warning_count=int(summary.warning_count),
            warnings=tuple(str(item) for item in diagnostics.warnings),
            source_types=tuple(str(item) for item in summary.source_types),
            topic_counts=dict(summary.topic_counts),
            synchronization_status_counts=dict(summary.synchronization_status_counts),
            decisions=decisions,
            dropped_events=dropped_events,
            calibration_ids=tuple(str(item) for item in summary.calibration_ids),
            frame_ids=tuple(str(item) for item in summary.frame_ids),
            static_transform_count=int(summary.static_transform_count),
        )

    def _reader(self, artifact: ArtifactRef) -> Any:
        if not artifact.readable:
            raise ClientOperationError(artifact.detail or "artifact is not readable")
        ingestion = self._ingestion()
        reader_type = ingestion.SequenceArtifactReader
        try:
            return reader_type(artifact.path)
        except Exception as error:
            raise ClientOperationError(f"cannot open artifact {artifact.path}: {error}") from error

    @staticmethod
    def _ingestion() -> Any:
        try:
            return import_module(_PUBLIC_INGESTION_MODULE)
        except ImportError as error:
            raise ClientOperationError(
                "ContextMap2 is not installed. Install the core package in the same environment."
            ) from error
