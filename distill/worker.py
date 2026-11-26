"""Background worker for Gemini distillation requests."""

import json

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from .core import distill_sources_to_result


class DistillSignals(QObject):
    """Signals emitted by a background distillation task."""

    finished = pyqtSignal(int, str, str, str, str, str, str)
    error = pyqtSignal(int, str)


class DistillWorker(QRunnable):
    """Run extraction and Gemini summarization outside the GUI thread."""

    def __init__(
        self,
        sources: list[dict[str, str]],
        mode: str,
        research_focus: str = "",
    ):
        super().__init__()
        self.sources = sources
        self.mode = mode
        self.research_focus = research_focus.strip()
        self.signals = DistillSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = distill_sources_to_result(
                self.sources,
                mode=self.mode,
                research_focus=self.research_focus,
            )
        except Exception as exc:
            self.signals.error.emit(id(self), str(exc))
        else:
            title = (
                self.sources[0].get("title", "") or "Distilled page"
                if len(self.sources) == 1
                else f"{len(self.sources)} sources distilled"
            )
            metadata = [
                {"title": source.get("title", ""), "url": source.get("url", "")}
                for source in self.sources
            ]
            self.signals.finished.emit(
                id(self),
                title,
                self.sources[0].get("url", ""),
                self.mode,
                result.markdown,
                result.html,
                json.dumps(metadata),
            )
