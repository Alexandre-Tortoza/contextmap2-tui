from contextmap_tui.app import ContextMapTuiApp
from contextmap_tui.client import FakeContextMapClient
from contextmap_tui.screens import HomeScreen


async def test_app_opens_home_with_injected_client() -> None:
    app = ContextMapTuiApp(client=FakeContextMapClient(backend_name="fixture", detail="ready"))

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert "fixture" in str(app.screen.query_one("#client-status").render())


async def test_home_navigation_bindings_do_not_replace_screen() -> None:
    app = ContextMapTuiApp(client=FakeContextMapClient())

    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("h")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
