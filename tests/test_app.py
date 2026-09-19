from contextmap_tui.app import ContextMapTuiApp


async def test_app_boots_headlessly() -> None:
    app = ContextMapTuiApp()
    async with app.run_test():
        assert app.query_one("#bootstrap-message") is not None
        assert app.title == "ContextMap2"
