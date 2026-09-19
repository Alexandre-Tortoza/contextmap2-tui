"""Compatibility probe for the future public contextmap.runtime package."""

from __future__ import annotations

from importlib import import_module

from contextmap_tui.runtime import RuntimeAvailability, UnavailableRuntimeGateway


class LocalRuntimeGateway(UnavailableRuntimeGateway):
    """Report real installed-core runtime availability without private imports."""

    def availability(self) -> RuntimeAvailability:
        """Probe only the documented public module boundary."""
        try:
            module = import_module("contextmap.runtime")
        except ImportError:
            return RuntimeAvailability(
                available=False,
                detail=(
                    "contextmap.runtime is not present in the installed ContextMap2 core. "
                    "Pipeline configuration/execution remains unavailable."
                ),
            )

        api_version = getattr(module, "API_VERSION", None)
        return RuntimeAvailability(
            available=False,
            api_version=str(api_version) if api_version is not None else None,
            detail=(
                "contextmap.runtime was found, but this TUI has no verified adapter for its "
                "public contract. No private-import or guessed fallback is used."
            ),
        )
