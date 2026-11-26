"""Prism appearance and homepage settings dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    """Edit theme, accent color, and homepage background image preferences."""

    def __init__(
        self,
        theme: str,
        accent: str,
        background_path: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Prism Settings")
        self.resize(440, 240)
        self.background_path = background_path

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.theme_selector = QComboBox()
        self.theme_selector.addItem("System", "system")
        self.theme_selector.addItem("Light", "light")
        self.theme_selector.addItem("Dark", "dark")
        self._select_data(self.theme_selector, theme)
        form.addRow("Theme", self.theme_selector)

        self.accent_selector = QComboBox()
        for label, value in (
            ("Prism violet", "violet"),
            ("Ocean blue", "blue"),
            ("Forest green", "green"),
        ):
            self.accent_selector.addItem(label, value)
        self._select_data(self.accent_selector, accent)
        form.addRow("Accent color", self.accent_selector)
        layout.addLayout(form)

        background_row = QVBoxLayout()
        self.background_label = QLabel()
        self._update_background_label()
        choose_button = QPushButton("Choose homepage background…")
        choose_button.clicked.connect(self.choose_background)
        reset_button = QPushButton("Reset to default gradient")
        reset_button.clicked.connect(self.reset_background)
        background_row.addWidget(self.background_label)
        background_row.addWidget(choose_button)
        background_row.addWidget(reset_button)
        layout.addLayout(background_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @property
    def theme(self) -> str:
        """Return the chosen theme key."""
        return str(self.theme_selector.currentData())

    @property
    def accent(self) -> str:
        """Return the chosen accent preset key."""
        return str(self.accent_selector.currentData())

    def choose_background(self) -> None:
        """Select a local image to be copied into Prism app-data on save."""
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose homepage background",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if path:
            self.background_path = path
            self._update_background_label()

    def reset_background(self) -> None:
        """Remove the custom image selection."""
        self.background_path = ""
        self._update_background_label()

    def _update_background_label(self) -> None:
        self.background_label.setText(
            f"Current background: {self.background_path or 'Default gradient'}"
        )
