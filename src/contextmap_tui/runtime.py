"""Presentation boundary for the public ContextMap2 runtime.

Plans, preflight reports, execution results, run summaries and run records are the public
``contextmap.runtime`` values themselves, carried opaquely. The TUI renders their attributes and
never keeps a second schema, topology or lineage model of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Never, Protocol, runtime_checkable


class RuntimeOperationError(RuntimeError):
    """Raised when a runtime operation is unsupported or invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeAvailability:
    """Compatibility state between the TUI and the installed core runtime."""

    available: bool
    detail: str
    contextmap_version: str | None = None
    schemas: Mapping[str, str] = field(default_factory=dict)
    profiles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackendCapability:
    """One backend reported by a public RuntimeComponent."""

    backend_id: str
    available: bool
    reasons: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    install_hint: str = ""


@dataclass(frozen=True, slots=True)
class ComponentCapability:
    """One runtime variation point, preserving optional backend=None."""

    component_id: str
    optional: bool
    backends: tuple[BackendCapability, ...] = ()


@dataclass(frozen=True, slots=True)
class StageCapability:
    """Runtime-reported choices for one stage, projected for presentation."""

    stage_id: str
    display_name: str
    available: bool
    optional: bool
    backend_options: tuple[str, ...] = ()
    detail: str = ""
    capability: str = ""
    implemented: bool = True
    default_enabled: bool = True
    components: tuple[ComponentCapability, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    """What one execution covers, handed verbatim to ``Runtime.resolve_plan``/``preflight``/``run``.

    Attributes:
        targets: Stages to produce, or ``None`` for the complete pipeline.
        provided: Exact upstream artifacts by stage, as persisted ``ArtifactRef`` documents read
            from a run record. Mutually exclusive with configured ``inputs.selections``; the
            runtime rejects the combination.
        catalog: Catalog file listing the runs selections may resolve against.
    """

    targets: tuple[str, ...] | None = None
    provided: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    catalog: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeReuse:
    """Inputs of ``Runtime.reuse_policy``; the policy itself is built by the core."""

    index: str
    code_identity: str
    force: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimePipelineResolution:
    """Opaque public EffectiveConfig and ResolvedPipelinePlan plus resolution inputs."""

    profile: str
    files: tuple[str, ...]
    overrides: tuple[str, ...]
    config: Any
    plan: Any
    scope: RuntimeScope = RuntimeScope()


@runtime_checkable
class RuntimeCancellation(Protocol):
    """Cooperative cancellation handle; the local gateway hands out the core token."""

    def cancel(self, reason: str = "cancelled") -> None:
        """Ask the run to stop before its next stage."""
        ...

    @property
    def cancelled(self) -> bool:
        """Whether cancellation was requested."""
        ...


RuntimeEventSink = Callable[[Any], None]
"""Receives each public ``ExecutionEvent`` after the runtime persisted it."""


@runtime_checkable
class RuntimeGateway(Protocol):
    """TUI-facing adapter over the public ``contextmap.runtime.Runtime`` facade."""

    def availability(self) -> RuntimeAvailability:
        """Report installed runtime compatibility."""
        ...

    def capabilities(self, *, profile: str | None = None) -> tuple[StageCapability, ...]:
        """Return runtime-discovered stage/backend capabilities."""
        ...

    def resolve_pipeline(
        self,
        *,
        profile: str,
        files: Sequence[str] = (),
        overrides: Sequence[str] = (),
        scope: RuntimeScope | None = None,
    ) -> RuntimePipelineResolution:
        """Resolve configuration and plan through the public runtime."""
        ...

    def apply_edit(
        self, resolution: RuntimePipelineResolution, *, path: str, value: object
    ) -> RuntimePipelineResolution:
        """Apply one public RuntimeEdit and resolve again."""
        ...

    def preflight(
        self, resolution: RuntimePipelineResolution, *, reuse: RuntimeReuse | None = None
    ) -> Any:
        """Return the public ``RuntimePreflightReport``; nothing is loaded."""
        ...

    def cancellation(self) -> RuntimeCancellation:
        """Return a fresh cooperative cancellation token for one run."""
        ...

    def run(
        self,
        resolution: RuntimePipelineResolution,
        *,
        events: RuntimeEventSink,
        cancellation: RuntimeCancellation,
        reuse: RuntimeReuse | None = None,
        resume: str | None = None,
    ) -> Any:
        """Execute outside the Textual event loop; return the public ``RuntimeExecutionResult``."""
        ...

    def list_runs(self) -> tuple[Any, ...]:
        """Return public ``RuntimeRunSummary`` values in runtime order."""
        ...

    def inspect_run(self, run: str) -> Any:
        """Return the public ``RuntimeRunRecord`` for a run id or exact run directory."""
        ...

    def run_directory(self, summary: Any) -> str | None:
        """Return the exact directory of a listed run, so ambiguous ids are never guessed."""
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

    def capabilities(self, *, profile: str | None = None) -> tuple[StageCapability, ...]:
        """Reject capability discovery while the runtime is unavailable."""
        del profile
        self._raise()

    def resolve_pipeline(
        self,
        *,
        profile: str,
        files: Sequence[str] = (),
        overrides: Sequence[str] = (),
        scope: RuntimeScope | None = None,
    ) -> RuntimePipelineResolution:
        """Reject plan resolution while runtime is unavailable."""
        del profile, files, overrides, scope
        self._raise()

    def apply_edit(
        self, resolution: RuntimePipelineResolution, *, path: str, value: object
    ) -> RuntimePipelineResolution:
        """Reject edits while runtime is unavailable."""
        del resolution, path, value
        self._raise()

    def preflight(
        self, resolution: RuntimePipelineResolution, *, reuse: RuntimeReuse | None = None
    ) -> Any:
        """Reject preflight while the runtime is unavailable."""
        del resolution, reuse
        self._raise()

    def cancellation(self) -> RuntimeCancellation:
        """Reject execution handles while the runtime is unavailable."""
        self._raise()

    def run(
        self,
        resolution: RuntimePipelineResolution,
        *,
        events: RuntimeEventSink,
        cancellation: RuntimeCancellation,
        reuse: RuntimeReuse | None = None,
        resume: str | None = None,
    ) -> Any:
        """Reject execution while the runtime is unavailable."""
        del resolution, events, cancellation, reuse, resume
        self._raise()

    def list_runs(self) -> tuple[Any, ...]:
        """Reject run discovery while the runtime is unavailable."""
        self._raise()

    def inspect_run(self, run: str) -> Any:
        """Reject run inspection while the runtime is unavailable."""
        del run
        self._raise()

    def run_directory(self, summary: Any) -> str | None:
        """No workspace is known while the runtime is unavailable."""
        del summary
        return None


class FakeCancellation:
    """Deterministic cancellation token for tests."""

    def __init__(self) -> None:
        """Create a token that is not cancelled."""
        self.reason = ""
        self._cancelled = False

    def cancel(self, reason: str = "cancelled") -> None:
        """Record the request."""
        self.reason = reason
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        """Whether cancellation was requested."""
        return self._cancelled


@dataclass(slots=True)
class FakeRuntimeGateway:
    """Deterministic runtime used to validate TUI behavior in CI.

    It returns injected public-shaped values and makes no runtime decision of its own.
    """

    stage_capabilities: tuple[StageCapability, ...]
    resolution: RuntimePipelineResolution
    preflight_report: Any = None
    execution_result: Any = None
    events: Sequence[Any] = ()
    run_summaries: tuple[Any, ...] = ()
    run_records: Mapping[str, Any] = field(default_factory=dict)
    next_resolution: RuntimePipelineResolution | None = None
    edited: list[tuple[str, object]] = field(default_factory=list)
    scopes: list[RuntimeScope] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    workspace: str = "/workspace"

    def availability(self) -> RuntimeAvailability:
        """Report deterministic test runtime availability."""
        return RuntimeAvailability(
            available=True,
            detail="deterministic fake runtime",
            contextmap_version="fake",
            profiles=(self.resolution.profile,),
        )

    def capabilities(self, *, profile: str | None = None) -> tuple[StageCapability, ...]:
        """Return configured fake stage capabilities."""
        del profile
        return self.stage_capabilities

    def resolve_pipeline(
        self,
        *,
        profile: str,
        files: Sequence[str] = (),
        overrides: Sequence[str] = (),
        scope: RuntimeScope | None = None,
    ) -> RuntimePipelineResolution:
        """Return the injected resolution, recording the requested scope."""
        del profile, files, overrides
        self.scopes.append(scope or RuntimeScope())
        return self.resolution

    def apply_edit(
        self, resolution: RuntimePipelineResolution, *, path: str, value: object
    ) -> RuntimePipelineResolution:
        """Record a UI edit and return the injected next resolution."""
        if not any(edit.path == path for edit in resolution.plan.editable):
            raise RuntimeOperationError(f"path {path!r} is not declared editable")
        self.edited.append((path, value))
        if self.next_resolution is None:
            raise RuntimeOperationError("no fake resolution configured for edit")
        self.resolution = self.next_resolution
        return self.resolution

    def preflight(
        self, resolution: RuntimePipelineResolution, *, reuse: RuntimeReuse | None = None
    ) -> Any:
        """Return the injected preflight report."""
        del resolution, reuse
        if self.preflight_report is None:
            raise RuntimeOperationError("no fake preflight report configured")
        return self.preflight_report

    def cancellation(self) -> RuntimeCancellation:
        """Return a deterministic token."""
        return FakeCancellation()

    def run(
        self,
        resolution: RuntimePipelineResolution,
        *,
        events: RuntimeEventSink,
        cancellation: RuntimeCancellation,
        reuse: RuntimeReuse | None = None,
        resume: str | None = None,
    ) -> Any:
        """Emit the injected events and return the injected execution result."""
        self.runs.append({"resolution": resolution, "reuse": reuse, "resume": resume})
        for event in self.events:
            if cancellation.cancelled:
                break
            events(event)
        if self.execution_result is None:
            raise RuntimeOperationError("no fake execution result configured")
        return self.execution_result

    def list_runs(self) -> tuple[Any, ...]:
        """Return injected run summaries."""
        return self.run_summaries

    def inspect_run(self, run: str) -> Any:
        """Return the injected record for an exact directory or id."""
        record = self.run_records.get(run)
        if record is None:
            raise RuntimeOperationError(f"no run record for {run!r}")
        return record

    def run_directory(self, summary: Any) -> str | None:
        """Return the documented ``<workspace>/<dataset>/<run>`` location."""
        return str(Path(self.workspace) / summary.dataset / summary.run_id)
