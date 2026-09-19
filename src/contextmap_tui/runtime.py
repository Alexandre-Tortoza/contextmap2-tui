"""Presentation boundary for the future ContextMap2 global runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from threading import Event
from typing import Never, Protocol, runtime_checkable


class RuntimeOperationError(RuntimeError):
    """Raised when a runtime operation is unsupported or invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeAvailability:
    """Compatibility state between the TUI and the installed core runtime."""

    available: bool
    detail: str
    api_version: str | None = None


@dataclass(frozen=True, slots=True)
class StageCapability:
    """Runtime-reported choices for one stage, projected for presentation."""

    stage_id: str
    display_name: str
    available: bool
    optional: bool
    backend_options: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PipelineStageView:
    """One runtime-resolved stage in the effective pipeline configuration."""

    stage_id: str
    enabled: bool
    backend: str | None
    inputs: tuple[str, ...] = ()
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PipelineConfigView:
    """Read/edit projection of a runtime-owned pipeline configuration."""

    config_id: str
    stages: tuple[PipelineStageView, ...]


@dataclass(frozen=True, slots=True)
class RuntimePreflight:
    """Runtime-owned preflight result before heavy execution."""

    ok: bool
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Progress event emitted by global runtime execution."""

    stage_id: str
    message: str
    progress_percent: float | None = None


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    """Terminal state returned by one global pipeline execution."""

    status: str
    run_id: str | None = None
    output_artifacts: tuple[str, ...] = ()
    reused_artifacts: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Persisted run/lineage projection supplied by the runtime."""

    run_id: str
    status: str
    effective_config: Mapping[str, object]
    upstream_artifacts: tuple[str, ...]
    output_artifacts: tuple[str, ...]
    metrics: Mapping[str, object] = field(default_factory=dict)
    detail: str = ""


RuntimeProgressSink = Callable[[RuntimeEvent], None]


@runtime_checkable
class RuntimeGateway(Protocol):
    """TUI-facing adapter over a stable public contextmap.runtime contract."""

    def availability(self) -> RuntimeAvailability:
        """Report installed runtime compatibility."""
        ...

    def capabilities(self) -> tuple[StageCapability, ...]:
        """Return runtime-discovered stage/backend capabilities."""
        ...

    def pipeline_config(self) -> PipelineConfigView:
        """Return the runtime-resolved effective pipeline configuration."""
        ...

    def edit_stage(
        self,
        config: PipelineConfigView,
        stage_id: str,
        *,
        enabled: bool | None = None,
        backend: str | None = None,
    ) -> PipelineConfigView:
        """Ask the runtime to validate and apply a supported stage edit."""
        ...

    def preflight(self, config: PipelineConfigView) -> RuntimePreflight:
        """Run lightweight runtime preflight."""
        ...

    def run(
        self,
        config: PipelineConfigView,
        *,
        emit: RuntimeProgressSink,
        cancel_event: Event,
    ) -> PipelineRunResult:
        """Execute the runtime plan outside the Textual event loop."""
        ...

    def list_runs(self) -> tuple[RunRecord, ...]:
        """Return persisted runs in runtime-defined order."""
        ...


@dataclass(slots=True)
class UnavailableRuntimeGateway:
    """Explicit unsupported runtime boundary with no hidden fallback."""

    reason: str = "contextmap.runtime is not available in the installed ContextMap2 core."

    def availability(self) -> RuntimeAvailability:
        """Report that no verified runtime execution capability exists."""
        return RuntimeAvailability(available=False, detail=self.reason)

    def _raise(self) -> Never:
        raise RuntimeOperationError(self.reason)

    def capabilities(self) -> tuple[StageCapability, ...]:
        """Reject capability discovery while the runtime is unavailable."""
        self._raise()

    def pipeline_config(self) -> PipelineConfigView:
        """Reject configuration access while the runtime is unavailable."""
        self._raise()

    def edit_stage(
        self,
        config: PipelineConfigView,
        stage_id: str,
        *,
        enabled: bool | None = None,
        backend: str | None = None,
    ) -> PipelineConfigView:
        """Reject edits rather than guessing unsupported runtime semantics."""
        del config, stage_id, enabled, backend
        self._raise()

    def preflight(self, config: PipelineConfigView) -> RuntimePreflight:
        """Reject preflight while the runtime is unavailable."""
        del config
        self._raise()

    def run(
        self,
        config: PipelineConfigView,
        *,
        emit: RuntimeProgressSink,
        cancel_event: Event,
    ) -> PipelineRunResult:
        """Reject execution while the runtime is unavailable."""
        del config, emit, cancel_event
        self._raise()

    def list_runs(self) -> tuple[RunRecord, ...]:
        """Reject run discovery while the runtime is unavailable."""
        self._raise()


@dataclass(slots=True)
class FakeRuntimeGateway:
    """Deterministic runtime used to validate TUI behavior in CI."""

    stage_capabilities: tuple[StageCapability, ...]
    config: PipelineConfigView
    preflight_result: RuntimePreflight = RuntimePreflight(ok=True)
    run_result: PipelineRunResult = PipelineRunResult(status="completed", run_id="fake-run")
    events: Sequence[RuntimeEvent] = ()
    run_records: tuple[RunRecord, ...] = ()

    def availability(self) -> RuntimeAvailability:
        """Report deterministic test runtime availability."""
        return RuntimeAvailability(
            available=True,
            detail="deterministic fake runtime",
            api_version="fake",
        )

    def capabilities(self) -> tuple[StageCapability, ...]:
        """Return configured fake stage capabilities."""
        return self.stage_capabilities

    def pipeline_config(self) -> PipelineConfigView:
        """Return the current deterministic fake configuration."""
        return self.config

    def edit_stage(
        self,
        config: PipelineConfigView,
        stage_id: str,
        *,
        enabled: bool | None = None,
        backend: str | None = None,
    ) -> PipelineConfigView:
        """Validate and apply an edit using deterministic fake runtime rules."""
        capability = next(
            (item for item in self.stage_capabilities if item.stage_id == stage_id),
            None,
        )
        if capability is None or not capability.available:
            raise RuntimeOperationError(f"stage is unavailable: {stage_id}")

        stages = list(config.stages)
        index = next((i for i, item in enumerate(stages) if item.stage_id == stage_id), None)
        if index is None:
            raise RuntimeOperationError(f"stage is not in resolved config: {stage_id}")
        stage = stages[index]

        if enabled is not None and enabled != stage.enabled:
            if not capability.optional:
                raise RuntimeOperationError(f"mandatory stage cannot be toggled: {stage_id}")
            stage = replace(stage, enabled=enabled)
        if backend is not None and backend != stage.backend:
            if backend not in capability.backend_options:
                raise RuntimeOperationError(
                    f"backend {backend!r} is not supported by stage {stage_id!r}"
                )
            stage = replace(stage, backend=backend)

        stages[index] = stage
        updated = PipelineConfigView(config_id=config.config_id, stages=tuple(stages))
        self.config = updated
        return updated

    def preflight(self, config: PipelineConfigView) -> RuntimePreflight:
        """Return the configured deterministic preflight result."""
        del config
        return self.preflight_result

    def run(
        self,
        config: PipelineConfigView,
        *,
        emit: RuntimeProgressSink,
        cancel_event: Event,
    ) -> PipelineRunResult:
        """Emit configured events and return the deterministic run result."""
        del config
        if cancel_event.is_set():
            return PipelineRunResult(status="cancelled")
        for event in self.events:
            if cancel_event.is_set():
                return PipelineRunResult(status="cancelled")
            emit(event)
        return self.run_result

    def list_runs(self) -> tuple[RunRecord, ...]:
        """Return configured persisted run projections."""
        return self.run_records
