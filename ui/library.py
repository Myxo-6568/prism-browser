"""Searchable dialog for browsing and managing saved distillations."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from prism.storage import DistillationRecord, LibraryRepository


class LibraryDialog(QDialog):
    """Search, open, and delete saved distillations."""

    def __init__(self, repository: LibraryRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.selected_record: DistillationRecord | None = None
        self.setWindowTitle("Prism Library")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saved distillations"))

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search titles, content, or sources")
        self.search_field.textChanged.connect(self.refresh_results)
        layout.addWidget(self.search_field)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.open_selected)
        layout.addWidget(self.result_list, 1)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(self.open_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(self.open_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)

        self.refresh_results()

    def refresh_results(self, _query: str = "") -> None:
        """Reload result rows matching the current search term."""
        self.result_list.clear()
        try:
            records = self.repository.search_distillations(self.search_field.text())
        except Exception as exc:
            QMessageBox.warning(self, "Library error", str(exc))
            return
        for record in records:
            source = record.source_title or record.source_url
            detail = f"{record.created_at}  ·  {source}" if source else record.created_at
            item = QListWidgetItem(f"{record.title}\n{detail}")
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setToolTip(record.source_url)
            self.result_list.addItem(item)

    def open_selected(self, _item=None) -> None:
        """Accept the dialog with the selected record."""
        item = self.result_list.currentItem()
        if item is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        self.selected_record = self.repository.get_distillation(record_id)
        if self.selected_record is not None:
            self.accept()

    def delete_selected(self) -> None:
        """Delete the selected record after explicit confirmation."""
        item = self.result_list.currentItem()
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete distillation",
            "Delete this saved distillation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.delete_distillation(item.data(Qt.ItemDataRole.UserRole))
        except Exception as exc:
            QMessageBox.warning(self, "Library error", str(exc))
            return
        self.refresh_results()
