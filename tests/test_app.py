from pathlib import Path

from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.screens import HomeScreen, WorkspaceScreen


async def test_app_opens_home_with_injected_client() -> None:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(backend_name="fixture", detail="ready"),
        workspace_root=Path("/tmp/workspace"),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert "fixture" in str(app.screen.query_one("#client-status").render())


async def test_explore_binding_opens_workspace_and_home_binding_returns() -> None:
    app = ContextMapTuiApp(
        client=FakeContextMapClient(),
        workspace_root=Path("/tmp/workspace"),
    )

    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceScreen)
        await pilot.press("h")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


async def test_operate_binding_keeps_home_until_runtime_milestone() -> None:
    app = ContextMapTuiApp(client=FakeContextMapClient())

    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
