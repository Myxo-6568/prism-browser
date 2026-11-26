"""Collect HTML from multiple open pages with a bounded timeout."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView


class HtmlCollector(QObject):
    """Gather selected pages asynchronously and finish once or on timeout."""

    finished = pyqtSignal(object, object)

    def __init__(
        self, views: list[QWebEngineView], timeout_ms: int = 20_000, parent=None
    ):
        super().__init__(parent)
        self._views = list(views)
        self._pending = set(views)
        self._sources: list[dict[str, str]] = []
        self._titles = {
            view: view.title().strip() or view.url().host() or "Untitled page"
            for view in views
        }
        self._urls = {view: view.url().toString() for view in views}
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._finish)

    def start(self) -> None:
        """Begin asynchronous HTML collection from the selected views."""
        self._timer.start()
        if not self._pending:
            self._finish()
            return
        for view in self._views:
            view.page().toHtml(
                lambda raw_html, source_view=view: self._on_html(
                    source_view, raw_html
                )
            )

    def _on_html(self, view: QWebEngineView, raw_html: str) -> None:
        if self._finished or view not in self._pending:
            return
        self._pending.remove(view)
        self._sources.append(
            {
                "html": raw_html,
                "title": self._titles[view],
                "url": self._urls[view],
            }
        )
        if not self._pending:
            self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        missing = [self._titles[view] for view in self._pending]
        self.finished.emit(self._sources, missing)
