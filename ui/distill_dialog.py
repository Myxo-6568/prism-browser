"""Source-tab selection dialog for summary and comparison distillations."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView


class DistillDialog(QDialog):
    """Choose one or more open web tabs and a distillation mode."""

    def __init__(
        self, views: list[QWebEngineView], current: QWebEngineView | None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Distill tabs")
        self.resize(680, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose the tabs to use as sources"))

        self.tab_list = QListWidget()
        for view in views:
            if view.url().scheme().lower() not in {"http", "https"}:
                continue
            title = view.title().strip() or view.url().host() or "Untitled page"
            item = QListWidgetItem(f"{title}\n{view.url().toString()}")
            item.setIcon(view.icon())
            item.setToolTip(view.url().toString())
            item.setData(Qt.ItemDataRole.UserRole, view)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked if view is current else Qt.CheckState.Unchecked
            )
            self.tab_list.addItem(item)
        self.tab_list.setStyleSheet(
            "QListWidget::item { padding: 8px; }"
        )
        layout.addWidget(self.tab_list, 1)

        layout.addWidget(QLabel("What are you researching or comparing? (optional)"))
        self.research_focus_input = QLineEdit()
        self.research_focus_input.setPlaceholderText(
            "e.g. Compare price, battery life, and performance"
        )
        self.research_focus_input.setMaxLength(1000)
        layout.addWidget(self.research_focus_input)

        layout.addWidget(QLabel("Distillation mode"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Summarize together", "summary")
        self.mode_selector.addItem("Compare", "compare")
        layout.addWidget(self.mode_selector)

        buttons = QDialogButtonBox()
        self.distill_button = buttons.addButton(
            "Distill", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def mode(self) -> str:
        """Return the selected worker mode."""
        return str(self.mode_selector.currentData())

    @property
    def research_focus(self) -> str:
        """Return the optional research question for relevance filtering."""
        return self.research_focus_input.text().strip()

    def selected_views(self) -> list[QWebEngineView]:
        """Return checked source views in their visible tab-list order."""
        selected = []
        for index in range(self.tab_list.count()):
            item = self.tab_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                view = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(view, QWebEngineView):
                    selected.append(view)
        return selected

    def _accept_if_valid(self) -> None:
        selected = self.selected_views()
        if not selected:
            QMessageBox.information(
                self, "Select a source", "Choose at least one open web tab."
            )
            return
        if self.mode == "compare" and len(selected) < 2:
            QMessageBox.information(
                self, "Select more tabs", "Compare mode needs at least two tabs."
            )
            return
        self.accept()
