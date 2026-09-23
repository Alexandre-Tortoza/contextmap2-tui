"""Public ContextMap2 ingestion request construction for the terminal form."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from threading import Event
from typing import Any

from contextmap_tui.ingestion import (
    IngestionDiscovery,
    IngestionPreflight,
    IngestionResult,
    PreparedIngestion,
    ProgressSink,
    RunnerAvailability,
    SourceBackendChoice,
    parse_required_topics,
)

_SOURCE_COMPONENT = "ingestion.source_adapter"
_FORM_FIELDS = frozenset(
    {
        "source_backend",
        "source_path",
        "sequence_name",
        "artifact_id",
        "output_dir",
        "required_topics",
        "timestamp_clock_id",
        "reference_modality",
        "tolerance_nanoseconds",
        "window_clock_id",
        "window_start_seconds",
        "window_end_seconds",
        "validation_on_problems",
        "allow_duplicate_timestamps",
        "hash_source",
    }
)


def _boolean(value: str, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{field} must be true or false")


class LocalIngestionRunner:
    """Construct requests exclusively through the core's public root APIs."""

    @staticmethod
    def _api() -> tuple[Any, Any]:
        return import_module("contextmap.runtime"), import_module("contextmap.ingestion")

    def availability(self) -> RunnerAvailability:
        """Report public request support while execution remains unavailable."""
        try:
            runtime, ingestion = self._api()
            if not all(
                hasattr(runtime, name) for name in ("Runtime", "IngestionRequest")
            ) or not hasattr(ingestion, "SourceTopicMapping"):
                return RunnerAvailability(
                    False, "installed core lacks the public ingestion request"
                )
        except ImportError as error:
            return RunnerAvailability(False, f"ContextMap2 is not installed: {error}")
        return RunnerAvailability(
            False,
            "Public ingestion request is available; execution integration is pending.",
        )

    def discover(self, workspace_root: Path, *, profile: str) -> IngestionDiscovery:
        """Read profiles, source adapters, topics and modalities from public APIs."""
        runtime_api, ingestion = self._api()
        runtime = runtime_api.Runtime(workspace=workspace_root)
        status = runtime.status()
        selected_profile = profile or status.profiles[0]
        stage = next(
            (
                item
                for item in runtime.capabilities(profile=selected_profile)
                if item.stage_id == "ingestion"
            ),
            None,
        )
        if stage is None:
            raise ValueError(f"profile {selected_profile!r} has no ingestion stage")
        component = next(
            (item for item in stage.components if item.component_id == _SOURCE_COMPONENT),
            None,
        )
        if component is None:
            raise ValueError(f"profile {selected_profile!r} has no {_SOURCE_COMPONENT} component")
        return IngestionDiscovery(
            profiles=tuple(status.profiles),
            backends=tuple(
                SourceBackendChoice(
                    backend_id=item.backend_id,
                    available=item.available,
                    reasons=tuple(item.reasons),
                    install_hint=item.install_hint,
                )
                for item in component.backends
            ),
            topic_fields=tuple(
                field.name for field in dataclasses.fields(ingestion.SourceTopicMapping)
            ),
            modalities=tuple(
                sorted(ingestion.MODALITY_NAMES, key=lambda name: (name != "image", name))
            ),
        )

    def prepare(
        self,
        fields: Mapping[str, str],
        *,
        workspace_root: Path,
        profile: str,
    ) -> PreparedIngestion:
        """Convert raw form strings through the core's public request constructor."""
        runtime_api, _ = self._api()
        discovery = self.discover(workspace_root, profile=profile)
        unknown = set(fields) - _FORM_FIELDS - {f"topics.{name}" for name in discovery.topic_fields}
        if "calibration_path" in fields:
            raise ValueError("calibration files have no public decoder to CalibrationSet")
        if unknown:
            raise ValueError(f"unsupported form fields: {sorted(unknown)}")
        backend = fields.get("source_backend", "").strip()
        if backend not in {choice.backend_id for choice in discovery.backends}:
            raise ValueError(f"source backend {backend!r} is not reported by Runtime.capabilities")
        source_path = fields.get("source_path", "").strip()
        sequence_name = fields.get("sequence_name", "").strip()
        artifact_id = fields.get("artifact_id", "").strip()
        if not source_path or not sequence_name or not artifact_id:
            raise ValueError("source path, sequence name and artifact id must not be empty")
        runtime = runtime_api.Runtime(workspace=workspace_root)
        config = runtime.resolve_config(
            profile=profile,
            overrides=(f"components.{_SOURCE_COMPONENT}.backend={json.dumps(backend)}",),
        )
        selected = config.config.components[_SOURCE_COMPONENT].backend
        if selected != backend:
            raise ValueError("effective runtime configuration changed the selected source backend")
        output_text = fields.get("output_dir", "").strip()
        output_dir = (
            Path(output_text).expanduser()
            if output_text
            else workspace_root / "sequences" / sequence_name / artifact_id
        )
        window_keys = ("window_clock_id", "window_start_seconds", "window_end_seconds")
        window_values = tuple(fields.get(name, "").strip() for name in window_keys)
        window: dict[str, object] | None = None
        if any(window_values):
            if not all(window_values):
                raise ValueError("window requires clock id, start seconds and end seconds")
            window = {
                "clock_id": window_values[0],
                "start_seconds": float(window_values[1]),
                "end_seconds": float(window_values[2]),
            }
        policy = fields.get("validation_on_problems", "fail")
        document = {
            "source_path": str(Path(source_path).expanduser()),
            "sequence_name": sequence_name,
            "topics": {
                name: value.strip()
                for name in discovery.topic_fields
                if (value := fields.get(f"topics.{name}", "").strip())
            },
            "required_topics": sorted(parse_required_topics(fields.get("required_topics", ""))),
            "timestamp_clock_id": fields.get("timestamp_clock_id", "").strip() or None,
            "synchronization": {
                "reference_modality": fields.get("reference_modality", "").strip(),
                "tolerance_nanoseconds": int(fields.get("tolerance_nanoseconds", "").strip()),
            },
            "window": window,
            "validation": {
                "on_problems": policy,
                "allow_duplicate_timestamps": _boolean(
                    fields.get("allow_duplicate_timestamps", "true"),
                    "allow_duplicate_timestamps",
                ),
            },
            "hash_source": _boolean(fields.get("hash_source", "true"), "hash_source"),
            "config_identity": config.digest,
        }
        request = runtime_api.IngestionRequest.from_document(
            document,
            source_type=selected,
            output_dir=str(output_dir),
            artifact_id=artifact_id,
        )
        return PreparedIngestion(request=request, config=config, runtime=runtime)

    def preflight(self, prepared: PreparedIngestion) -> IngestionPreflight:
        """Keep execution unavailable until the service adapter is connected."""
        del prepared
        reason = "Public ingestion execution adapter is not connected yet."
        return IngestionPreflight(ok=False, problems=(reason,))

    def run(
        self,
        prepared: PreparedIngestion,
        *,
        emit: ProgressSink,
        cancel_event: Event,
    ) -> IngestionResult:
        """Never execute a substitute ingestion runner."""
        del prepared, emit, cancel_event
        return IngestionResult(
            status="unsupported", detail="Public ingestion service not connected"
        )
