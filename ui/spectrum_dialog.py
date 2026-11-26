"""Dialog for choosing source tabs when creating a Spectrum."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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


class SpectrumDialog(QDialog):
    """Choose one or more open web tabs, or create an empty Spectrum."""

    def __init__(
        self, views: list[QWebEngineView], current: QWebEngineView | None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Create Spectrum")
        self.resize(680, 520)
        self.create_empty = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose tabs to include in your Spectrum"))

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
        self.tab_list.setStyleSheet("QListWidget::item { padding: 8px; }")
        layout.addWidget(self.tab_list, 1)

        layout.addWidget(QLabel("What are you researching? (optional)"))
        self.research_focus_input = QLineEdit()
        self.research_focus_input.setPlaceholderText(
            "e.g. Compare price, features, and limitations"
        )
        self.research_focus_input.setMaxLength(1000)
        layout.addWidget(self.research_focus_input)

        buttons = QDialogButtonBox()
        self.create_button = buttons.addButton(
            "Create Spectrum", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.empty_button = buttons.addButton(
            "Create empty", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.create_button.clicked.connect(self._accept_if_valid)
        self.empty_button.clicked.connect(self._accept_empty)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_views(self) -> list[QWebEngineView]:
        """Return checked browser tabs in their visible order."""
        selected = []
        for index in range(self.tab_list.count()):
            item = self.tab_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                view = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(view, QWebEngineView):
                    selected.append(view)
        return selected

    @property
    def research_focus(self) -> str:
        """Return the optional research question for content curation."""
        return self.research_focus_input.text().strip()

    def _accept_if_valid(self) -> None:
        if not self.selected_views():
            QMessageBox.information(
                self, "Select tabs", "Choose at least one tab or create an empty Spectrum."
            )
            return
        self.accept()

    def _accept_empty(self) -> None:
        self.create_empty = True
        self.accept()
