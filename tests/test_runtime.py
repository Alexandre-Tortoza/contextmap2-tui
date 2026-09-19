from threading import Event

import pytest

from contextmap_tui.runtime import (
    FakeRuntimeGateway,
    PipelineConfigView,
    PipelineRunResult,
    PipelineStageView,
    RuntimeOperationError,
    StageCapability,
)


def _runtime() -> FakeRuntimeGateway:
    return FakeRuntimeGateway(
        stage_capabilities=(
            StageCapability(
                stage_id="ingestion",
                display_name="Ingestion",
                available=True,
                optional=False,
                backend_options=("canonical",),
            ),
            StageCapability(
                stage_id="visual_perception",
                display_name="Visual Perception",
                available=True,
                optional=True,
                backend_options=("foundation-v1", "foundation-v2"),
            ),
        ),
        config=PipelineConfigView(
            config_id="fixture",
            stages=(
                PipelineStageView("ingestion", True, "canonical"),
                PipelineStageView(
                    "visual_perception",
                    True,
                    "foundation-v1",
                    inputs=("ingestion",),
                ),
            ),
        ),
        run_result=PipelineRunResult(status="completed", run_id="run-1"),
    )


def test_fake_runtime_validates_optional_stage_and_backend_edits() -> None:
    runtime = _runtime()
    config = runtime.pipeline_config()

    config = runtime.edit_stage(config, "visual_perception", enabled=False)
    config = runtime.edit_stage(config, "visual_perception", backend="foundation-v2")

    stage = config.stages[1]
    assert stage.enabled is False
    assert stage.backend == "foundation-v2"

    with pytest.raises(RuntimeOperationError, match="mandatory"):
        runtime.edit_stage(config, "ingestion", enabled=False)
    with pytest.raises(RuntimeOperationError, match="not supported"):
        runtime.edit_stage(config, "visual_perception", backend="invented")


def test_fake_runtime_honors_preexisting_cancellation() -> None:
    runtime = _runtime()
    cancel = Event()
    cancel.set()

    result = runtime.run(
        runtime.pipeline_config(),
        emit=lambda event: None,
        cancel_event=cancel,
    )

    assert result.status == "cancelled"
