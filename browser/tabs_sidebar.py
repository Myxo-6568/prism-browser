"""Reorderable vertical tab list with favicon, title, and close affordance."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QListWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
)


class TabItemDelegate(QStyledItemDelegate):
    """Paint a compact favicon/title/close row while preserving Qt drag behavior."""

    def __init__(self, parent: QListWidget):
        super().__init__(parent)
        self.list_widget = parent
        self._pressed_row: int | None = None
        self._press_position = QPoint()
        self._hovered_row: int | None = None

    @staticmethod
    def _close_rect(rect: QRect) -> QRect:
        return QRect(rect.right() - 31, rect.center().y() - 11, 23, 22)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(42)
        return size

    def paint(self, painter: QPainter, option, index):
        item = self.list_widget.item(index.row())
        if item is None:
            return
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        style_option.text = ""
        style_option.icon = QIcon()
        style = (
            self.list_widget.style()
            if self.list_widget.style()
            else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            style_option,
            painter,
            self.list_widget,
        )

        painter.save()
        rect = option.rect
        icon_rect = QRect(rect.left() + 10, rect.center().y() - 9, 18, 18)
        icon = item.icon()
        if icon.isNull():
            painter.setPen(option.palette.color(QPalette.ColorRole.Text))
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "◉")
        else:
            icon.paint(painter, icon_rect)

        compact = bool(getattr(self.list_widget, "compact", False))
        if not compact:
            color_role = (
                QPalette.ColorRole.HighlightedText
                if option.state & QStyle.StateFlag.State_Selected
                else QPalette.ColorRole.Text
            )
            painter.setPen(option.palette.color(color_role))
            text_rect = QRect(
                icon_rect.right() + 9,
                rect.top(),
                max(0, rect.width() - 74),
                rect.height(),
            )
            metrics = QFontMetrics(option.font)
            title = metrics.elidedText(
                item.text(), Qt.TextElideMode.ElideRight, text_rect.width()
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title,
            )
        close_rect = self._close_rect(rect)
        hovered = self._hovered_row == index.row()
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(220, 76, 80, 38))
            painter.drawRoundedRect(close_rect, 6, 6)
        if not compact or hovered:
            close_color = QColor("#c64349") if hovered else QColor(
                option.palette.color(QPalette.ColorRole.Mid)
            )
            painter.setPen(close_color)
            painter.drawLine(
                close_rect.left() + 8,
                close_rect.top() + 7,
                close_rect.right() - 8,
                close_rect.bottom() - 7,
            )
            painter.drawLine(
                close_rect.right() - 8,
                close_rect.top() + 7,
                close_rect.left() + 8,
                close_rect.bottom() - 7,
            )
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonPress:
            position = event.position().toPoint()
            self._pressed_row = (
                index.row()
                if self._close_rect(option.rect).contains(position)
                else None
            )
            self._press_position = position
            return False
        if event.type() == QEvent.Type.MouseMove and self._pressed_row is not None:
            if (event.position().toPoint() - self._press_position).manhattanLength() > 5:
                self._pressed_row = None
            return False
        if event.type() == QEvent.Type.MouseMove:
            position = event.position().toPoint()
            hovered_row = (
                index.row()
                if self._close_rect(option.rect).contains(position)
                else None
            )
            if hovered_row != self._hovered_row:
                self._hovered_row = hovered_row
                self.list_widget.viewport().update()
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            position = event.position().toPoint()
            pressed_row = self._pressed_row
            self._pressed_row = None
            if (
                pressed_row == index.row()
                and self._close_rect(option.rect).contains(position)
            ):
                item = self.list_widget.item(index.row())
                if item is not None:
                    view = item.data(Qt.ItemDataRole.UserRole)
                    self.list_widget.closeRequested.emit(view)
                    return True
        if event.type() in {
            QEvent.Type.HoverMove,
            QEvent.Type.Leave,
        }:
            if event.type() == QEvent.Type.Leave:
                self._hovered_row = None
            self.list_widget.viewport().update()
        return False


class TabsListWidget(QListWidget):
    """Tab list that displays the close button and supports internal reordering."""

    closeRequested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.compact = False
        self.setItemDelegate(TabItemDelegate(self))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def event(self, event):
        if event.type() == QEvent.Type.Leave:
            self.viewport().update()
        return super().event(event)
