"""Textual application entry point."""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.widgets import Footer, Header

from contextmap_tui.client import ContextMapClient, FakeContextMapClient
from contextmap_tui.screens import HomeScreen


class ContextMapTuiApp(App[None]):
    """Root Textual application and navigation owner."""

    TITLE = "ContextMap2"
    SUB_TITLE = "TUI"
    BINDINGS: ClassVar[list[BindingType]] = [
        ("h", "home", "Home"),
        ("ctrl+p", "command_palette", "Commands"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, client: ContextMapClient | None = None) -> None:
        """Create the app with an injectable presentation gateway."""
        super().__init__()
        self.client = client or FakeContextMapClient(
            backend_name="not configured",
            connected=False,
            detail="Install/configure ContextMap2 integration in a later milestone.",
        )

    def compose(self) -> ComposeResult:
        """Compose persistent chrome; screens own page content."""
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Install and open the landing screen once the application is mounted."""
        self.install_screen(HomeScreen(self.client.status()), name="home")
        self.push_screen("home")

    def action_home(self) -> None:
        """Return to the named home screen without coupling callers to screen classes."""
        home = self.get_screen("home")
        if self.screen is home:
            return
        self.switch_screen("home")


def main() -> None:
    """Run the TUI application."""
    ContextMapTuiApp().run()


if __name__ == "__main__":
    main()
