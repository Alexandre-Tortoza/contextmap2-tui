"""Textual application entry point."""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.widgets import Footer, Header, Static


class ContextMapTuiApp(App[None]):
    """Root Textual application."""

    TITLE = "ContextMap2"
    SUB_TITLE = "TUI"
    BINDINGS: ClassVar[list[BindingType]] = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        """Compose the minimal bootstrap UI."""
        yield Header()
        yield Static(
            "ContextMap2 TUI\n\n"
            "Artifact Explorer e fluxos de execução serão adicionados por milestones.",
            id="bootstrap-message",
        )
        yield Footer()


def main() -> None:
    """Run the TUI application."""
    ContextMapTuiApp().run()


if __name__ == "__main__":
    main()
