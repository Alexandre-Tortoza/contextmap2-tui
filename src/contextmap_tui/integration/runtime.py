"""Thin gateway over the public contextmap.runtime ``Runtime`` facade."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from contextmap_tui.runtime import (
    BackendCapability,
    ComponentCapability,
    RuntimeAvailability,
    RuntimeCancellation,
    RuntimeEventSink,
    RuntimeOperationError,
    RuntimePipelineResolution,
    RuntimeReuse,
    RuntimeScope,
    StageCapability,
    UnavailableRuntimeGateway,
)


@dataclass(slots=True)
class LocalRuntimeGateway(UnavailableRuntimeGateway):
    """Operate the installed public Runtime; no backend or model is loaded by the TUI.

    ``runtime_options`` are public ``Runtime(...)`` keyword arguments (``executors``,
    ``providers``, ``verifier``...) supplied by whoever owns them; the TUI never builds an executor,
    provider or verifier itself. Without a verifier, the runtime itself refuses reuse and resume.
    """

    reason: str = "contextmap.runtime is not available in the installed ContextMap2 core."
    workspace_root: Path | None = None
    runtime_options: Mapping[str, Any] = field(default_factory=dict)

    def _runtime(self) -> tuple[Any, Any]:
        try:
            module = import_module("contextmap.runtime")
        except ImportError as error:
            raise RuntimeOperationError(
                "contextmap.runtime is not present in the installed ContextMap2 core"
            ) from error
        if not hasattr(module, "Runtime"):
            raise RuntimeOperationError("installed contextmap.runtime lacks public Runtime")
        return module, module.Runtime(workspace=self.workspace_root, **self.runtime_options)

    def availability(self) -> RuntimeAvailability:
        """Read version, schema versions and profiles from Runtime.status()."""
        try:
            _, runtime = self._runtime()
            status = runtime.status()
        except RuntimeOperationError as error:
            return RuntimeAvailability(available=False, detail=str(error))
        return RuntimeAvailability(
            available=True,
            detail="Public ContextMap2 Runtime is available.",
            contextmap_version=status.contextmap_version,
            schemas=dict(status.schemas),
            profiles=tuple(status.profiles),
        )

    def capabilities(self, *, profile: str | None = None) -> tuple[StageCapability, ...]:
        """Preserve public stage/component/backend hierarchy for one profile."""
        module, runtime = self._runtime()
        selected = profile or runtime.status().profiles[0]
        try:
            declared = runtime.capabilities(profile=selected)
        except module.ConfigurationError as error:
            raise RuntimeOperationError(str(error)) from error
        return tuple(
            StageCapability(
                stage_id=stage.stage_id,
                display_name=stage.stage_id.replace("_", " ").title(),
                available=stage.implemented,
                optional=stage.optional,
                detail=stage.reason,
                capability=stage.capability,
                implemented=stage.implemented,
                default_enabled=stage.default_enabled,
                components=tuple(
                    ComponentCapability(
                        component_id=component.component_id,
                        optional=component.optional,
                        backends=tuple(
                            BackendCapability(
                                backend_id=backend.backend_id,
                                available=backend.available,
                                reasons=tuple(backend.reasons),
                                requires=tuple(backend.requires),
                                secrets=tuple(backend.secrets),
                                install_hint=backend.install_hint,
                            )
                            for backend in component.backends
                        ),
                    )
                    for component in stage.components
                ),
            )
            for stage in declared
        )

    def resolve_pipeline(
        self,
        *,
        profile: str,
        files: Sequence[str] = (),
        overrides: Sequence[str] = (),
        scope: RuntimeScope | None = None,
    ) -> RuntimePipelineResolution:
        """Resolve the public effective configuration and plan without graph logic."""
        scope = scope or RuntimeScope()
        module, runtime = self._runtime()
        try:
            config = runtime.resolve_config(profile=profile, files=files, overrides=overrides)
            plan = runtime.resolve_plan(config, **self._scope(module, scope))
        except (module.ConfigurationError, ValueError) as error:
            raise RuntimeOperationError(str(error)) from error
        return RuntimePipelineResolution(
            profile=profile,
            files=tuple(files),
            overrides=tuple(overrides),
            config=config,
            plan=plan,
            scope=scope,
        )

    def apply_edit(
        self, resolution: RuntimePipelineResolution, *, path: str, value: object
    ) -> RuntimePipelineResolution:
        """Use a RuntimeEdit path and the core's JSON override grammar."""
        if not any(edit.path == path for edit in resolution.plan.editable):
            raise RuntimeOperationError(f"path {path!r} is not declared editable by Runtime")
        prefix = f"{path}="
        overrides = (
            *(override for override in resolution.overrides if not override.startswith(prefix)),
            f"{path}={json.dumps(value)}",
        )
        return self.resolve_pipeline(
            profile=resolution.profile,
            files=resolution.files,
            overrides=overrides,
            scope=resolution.scope,
        )

    def preflight(
        self, resolution: RuntimePipelineResolution, *, reuse: RuntimeReuse | None = None
    ) -> Any:
        """Return ``Runtime.preflight`` verbatim; it imports and loads nothing."""
        module, runtime = self._runtime()
        try:
            return runtime.preflight(
                resolution.config,
                **self._scope(module, resolution.scope),
                reuse=self._reuse(runtime, reuse),
            )
        except (module.ConfigurationError, ValueError) as error:
            raise RuntimeOperationError(str(error)) from error

    def cancellation(self) -> RuntimeCancellation:
        """Hand out the core cooperative token, so the runner checks it between stages."""
        module, _ = self._runtime()
        token: RuntimeCancellation = module.CancellationToken()
        return token

    def run(
        self,
        resolution: RuntimePipelineResolution,
        *,
        events: RuntimeEventSink,
        cancellation: RuntimeCancellation,
        reuse: RuntimeReuse | None = None,
        resume: str | None = None,
    ) -> Any:
        """Delegate to ``Runtime.run``; every expected outcome comes back as its result."""
        module, runtime = self._runtime()
        try:
            return runtime.run(
                resolution.config,
                **self._scope(module, resolution.scope),
                reuse=self._reuse(runtime, reuse),
                resume=resume,
                events=_Sink(events),
                cancellation=cancellation,
            )
        except (
            module.ConfigurationError,
            module.ResumeError,
            module.RunRecordError,
            ValueError,
        ) as error:
            raise RuntimeOperationError(str(error)) from error

    def list_runs(self) -> tuple[Any, ...]:
        """Return ``Runtime.list_runs`` verbatim, unreadable records included."""
        _, runtime = self._runtime()
        try:
            return tuple(runtime.list_runs())
        except ValueError as error:
            raise RuntimeOperationError(str(error)) from error

    def inspect_run(self, run: str) -> Any:
        """Return ``Runtime.inspect_run`` verbatim."""
        module, runtime = self._runtime()
        try:
            return runtime.inspect_run(run)
        except module.RunRecordError as error:
            raise RuntimeOperationError(str(error)) from error

    def run_directory(self, summary: Any) -> str | None:
        """Locate a listed run by the documented ``<workspace>/<dataset>/<run>`` layout."""
        if self.workspace_root is None:
            return None
        return str(self.workspace_root / summary.dataset / summary.run_id)

    @staticmethod
    def _scope(module: Any, scope: RuntimeScope) -> dict[str, Any]:
        provided = (
            {
                stage: module.ArtifactRef.from_document(document)
                for stage, document in scope.provided.items()
            }
            if scope.provided
            else None
        )
        return {
            "targets": scope.targets,
            "provided": provided,
            "catalog": None if scope.catalog is None else module.load_catalog(scope.catalog),
        }

    @staticmethod
    def _reuse(runtime: Any, reuse: RuntimeReuse | None) -> Any:
        if reuse is None:
            return None
        return runtime.reuse_policy(
            reuse.index, code_identity=reuse.code_identity, force=reuse.force
        )


@dataclass(frozen=True, slots=True)
class _Sink:
    """Adapt a presentation callback to the core ``EventSink`` protocol."""

    deliver: RuntimeEventSink

    def emit(self, event: Any) -> None:
        self.deliver(event)
