"""Discovery contract against the current public ContextMap2 runtime."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Select

from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.integration.runtime import LocalRuntimeGateway
from contextmap_tui.runtime import RuntimeOperationError
from contextmap_tui.screens import PipelineScreen


def test_status_and_profile_topologies_match_public_runtime(tmp_path: Path) -> None:
    core = pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    status = gateway.availability()
    runtime = core.Runtime(workspace=tmp_path)

    assert status.available
    assert status.contextmap_version == runtime.status().contextmap_version
    assert status.schemas == runtime.status().schemas
    assert set(status.profiles) >= {"canonical/1", "canonical/2"}

    for profile in status.profiles:
        found = gateway.capabilities(profile=profile)
        declared = runtime.capabilities(profile=profile)
        assert [stage.stage_id for stage in found] == [stage.stage_id for stage in declared]
        for view, original in zip(found, declared, strict=True):
            assert view.implemented == original.implemented
            assert view.default_enabled == original.default_enabled
            assert [item.component_id for item in view.components] == [
                item.component_id for item in original.components
            ]
            for component, public in zip(view.components, original.components, strict=True):
                assert component.optional == public.optional
                assert [backend.backend_id for backend in component.backends] == [
                    backend.backend_id for backend in public.backends
                ]


def test_multi_component_and_optional_stages_are_preserved(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    first = {stage.stage_id: stage for stage in gateway.capabilities(profile="canonical/1")}
    second = {stage.stage_id: stage for stage in gateway.capabilities(profile="canonical/2")}

    assert len(first["visual_perception"].components) == 4
    assert "semantic_mapping" not in first
    assert second["semantic_mapping"].implemented
    assert second["semantic_mapping"].components == ()
    assert not second["entity_resolution"].optional
    assert not second["spatial_relations"].optional
    assert any(component.optional for component in second["entity_resolution"].components)
    assert any(component.optional for component in second["spatial_relations"].components)


def test_unknown_profile_and_discovery_do_not_import_heavy_sdks(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    heavy = {"rosbags", "torch", "transformers", "cv2", "open3d"}
    before = {name for name in heavy if name in sys.modules}

    gateway.capabilities(profile="canonical/2")

    assert {name for name in heavy if name in sys.modules} == before
    with pytest.raises(RuntimeOperationError, match="unknown profile"):
        gateway.capabilities(profile="unknown/9")


def test_missing_module_and_secret_names_match_core_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = pytest.importorskip("contextmap.runtime")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gateway = LocalRuntimeGateway(workspace_root=tmp_path)
    stages = gateway.capabilities(profile="canonical/1")
    originals = core.Runtime(workspace=tmp_path).capabilities(profile="canonical/1")

    def backend_of(items: Any, component_id: str, backend_id: str) -> Any:
        return next(
            backend
            for stage in items
            for component in stage.components
            if component.component_id == component_id
            for backend in component.backends
            if backend.backend_id == backend_id
        )

    gemini = backend_of(stages, "visual_perception.semantic_interpretation", "gemini")
    original = backend_of(originals, "visual_perception.semantic_interpretation", "gemini")
    assert gemini.secrets == ("GEMINI_API_KEY",)
    assert gemini.reasons == original.reasons
    assert not gemini.available
    ros = backend_of(stages, "ingestion.source_adapter", "ros1_bag")
    original_ros = backend_of(originals, "ingestion.source_adapter", "ros1_bag")
    assert ros.requires == original_ros.requires
    assert ros.reasons == original_ros.reasons
    assert ros.install_hint == original_ros.install_hint

    monkeypatch.setenv("GEMINI_API_KEY", "private-marker-do-not-render")
    assert "private-marker-do-not-render" not in repr(gateway.capabilities())


async def test_pipeline_screen_renders_profile_and_component_hierarchy(tmp_path: Path) -> None:
    pytest.importorskip("contextmap.runtime")
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        runtime_gateway=LocalRuntimeGateway(workspace_root=tmp_path),
        workspace_root=tmp_path,
    )

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, PipelineScreen)
        status = str(app.screen.query_one("#runtime-availability").render())
        assert "canonical/1" in status and "canonical/2" in status
        selector = app.screen.query_one("#runtime-profile", Select)
        selector.value = "canonical/2"
        await pilot.pause()
        detail = str(app.screen.query_one("#capability-detail").render())
        assert "semantic_mapping" in detail
        assert "entity_resolution.appearance: optional=True" in detail
        assert "spatial_relations.contact_predicate: optional=True" in detail
        assert "visual_perception.dense_features" in detail
