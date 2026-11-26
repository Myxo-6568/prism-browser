"""Qt WebChannel bridge for the local Prism homepage."""

from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class HomeBridge(QObject):
    """Expose homepage search and appearance settings to local page JavaScript."""

    searchRequested = pyqtSignal(str)
    appearanceChanged = pyqtSignal(str)

    def __init__(self, appearance: dict[str, str], parent=None):
        super().__init__(parent)
        self._appearance = appearance

    def set_appearance(self, appearance: dict[str, str]) -> None:
        """Update the settings returned to the homepage and notify it."""
        self._appearance = appearance
        self.appearanceChanged.emit(json.dumps(appearance))

    @pyqtSlot(str)
    def search(self, text: str) -> None:
        """Forward a homepage search request to its owning browser tab."""
        self.searchRequested.emit(text)

    @pyqtSlot(result=str)
    def get_appearance(self) -> str:
        """Return encoded theme, accent, and optional background image URL."""
        return json.dumps(self._appearance)
