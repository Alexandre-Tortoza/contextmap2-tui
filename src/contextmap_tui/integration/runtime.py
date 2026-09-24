"""Thin discovery gateway over the public contextmap.runtime facade."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from contextmap_tui.runtime import (
    BackendCapability,
    ComponentCapability,
    RuntimeAvailability,
    RuntimeOperationError,
    StageCapability,
    UnavailableRuntimeGateway,
)


@dataclass(slots=True)
class LocalRuntimeGateway(UnavailableRuntimeGateway):
    """Discover the installed runtime without loading a backend or model."""

    reason: str = "Runtime plan and execution integration is pending."
    workspace_root: Path | None = None

    def _runtime(self) -> tuple[Any, Any]:
        try:
            module = import_module("contextmap.runtime")
        except ImportError as error:
            raise RuntimeOperationError(
                "contextmap.runtime is not present in the installed ContextMap2 core"
            ) from error
        if not hasattr(module, "Runtime"):
            raise RuntimeOperationError("installed contextmap.runtime lacks public Runtime")
        return module, module.Runtime(workspace=self.workspace_root)

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
