import json
import sqlite3
import shutil
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSettings, QStandardPaths, QThreadPool, Qt, QUrl, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from prism.browser.profile import create_web_profile
from prism.browser.home_bridge import HomeBridge
from prism.browser.html_collector import HtmlCollector
from prism.browser.tabs_sidebar import TabsListWidget
from prism.distill import ASSET_DIR, DistillWorker
from prism.distill.core import extract_text_from_html
from prism.storage import Database, LibraryRepository, SpectrumRepository
from prism.spectrum.bridge import SpectrumBridge
from prism.spectrum.worker import SpectrumChatWorker
from prism.ui.distill_dialog import DistillDialog
from prism.ui.library import LibraryDialog
from prism.ui.logo import load_prism_icon
from prism.ui.settings import SettingsDialog
from prism.ui.spectrum_dialog import SpectrumDialog


HOME_URL = "file:///Users/vishruth/PycharmProjects/Classwork/P2/prism/assets/home.html"
HOME_PAGE = Path(__file__).resolve().parent / "prism" / "assets" / "home.html"
SPECTRUM_PAGE = Path(__file__).resolve().parent / "prism" / "assets" / "spectrum.html"
ACCENTS = {
    "violet": "#6d5ce7",
    "blue": "#3478e5",
    "green": "#23966b",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prism")
        self.resize(1440, 900)
        self.setWindowIcon(load_prism_icon())
        self.settings = QSettings("Prism", "PrismBrowser")
        self.library = LibraryRepository(Database())
        self.spectrums = SpectrumRepository(self.library.database)
        self.web_profile = create_web_profile(QApplication.instance())
        self.theme = self.library.get_setting("theme", "system")
        self.accent = self.library.get_setting("accent", "violet")
        self.background_path = self.library.get_setting("home_background", "")
        self._home_bridges: dict[QWebEngineView, HomeBridge] = {}
        self._home_channels: dict[QWebEngineView, QWebChannel] = {}
        self._spectrum_bridges: dict[QWebEngineView, SpectrumBridge] = {}
        self._spectrum_channels: dict[QWebEngineView, QWebChannel] = {}
        self._spectrum_tab_ids: dict[QWebEngineView, int] = {}
        self._spectrum_chat_workers: dict[int, SpectrumChatWorker] = {}
        self.views: list[QWebEngineView] = []
        self._tab_urls: dict[QWebEngineView, QUrl] = {}
        self.pinned_views: set[QWebEngineView] = set()
        self.bookmarks: list[dict[str, str]] = self._load_bookmarks()
        self.saved_pinned_urls = self._load_pinned_urls()
        self.saved_session = self._load_session()
        self.thread_pool = QThreadPool.globalInstance()
        self._distill_workers: dict[int, DistillWorker] = {}
        self._html_collectors: set[HtmlCollector] = set()

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        root_layout.addWidget(self.splitter)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(68)
        self.sidebar.setMaximumWidth(360)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 16)
        sidebar_layout.setSpacing(10)
        self.splitter.addWidget(self.sidebar)

        brand = QHBoxLayout()
        brand_mark = QLabel()
        brand_mark.setPixmap(load_prism_icon().pixmap(30, 30))
        brand_mark.setObjectName("brandMark")
        brand_name = QLabel("prism")
        brand_name.setObjectName("brandName")
        self.brand_name = brand_name
        brand.addWidget(brand_mark)
        brand.addWidget(brand_name)
        brand.addStretch()
        sidebar_layout.addLayout(brand)

        tabs_header = QHBoxLayout()
        tabs_label = QLabel("TABS")
        tabs_label.setObjectName("sectionLabel")
        self.tabs_label = tabs_label
        tabs_header.addWidget(tabs_label)
        tabs_header.addStretch()
        new_tab_button = QToolButton()
        new_tab_button.setText("+")
        new_tab_button.setToolTip("New tab (⌘T)")
        new_tab_button.clicked.connect(self.add_new_tab)
        new_tab_button.setObjectName("sidebarAddButton")
        tabs_header.addWidget(new_tab_button)
        sidebar_layout.addLayout(tabs_header)

        self.tab_list = TabsListWidget()
        self.tab_list.setObjectName("tabList")
        self.tab_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.tab_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tab_list.customContextMenuRequested.connect(self.show_tab_menu)
        self.tab_list.currentItemChanged.connect(self.activate_tab_item)
        self.tab_list.model().rowsMoved.connect(self._tab_order_changed)
        self.tab_list.closeRequested.connect(self.close_view)
        sidebar_layout.addWidget(self.tab_list, 1)

        bookmarks_header = QLabel("BOOKMARKS")
        bookmarks_header.setObjectName("sectionLabel")
        self.bookmarks_header = bookmarks_header
        sidebar_layout.addWidget(bookmarks_header)
        self.bookmark_list = QListWidget()
        self.bookmark_list.setObjectName("bookmarkList")
        self.bookmark_list.setMaximumHeight(190)
        self.bookmark_list.itemActivated.connect(self.open_bookmark)
        sidebar_layout.addWidget(self.bookmark_list)
        self.refresh_bookmarks()

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(16, 12, 16, 14)
        main_layout.setSpacing(10)
        self.splitter.addWidget(main)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._splitter_moved)

        chrome = QHBoxLayout()
        chrome.setSpacing(8)
        self.back_button = self._chrome_button("‹", "Back")
        self.forward_button = self._chrome_button("›", "Forward")
        self.reload_button = self._chrome_button("↻", "Reload")
        self.back_button.clicked.connect(self.go_back)
        self.forward_button.clicked.connect(self.go_forward)
        self.reload_button.clicked.connect(self.reload_page)
        chrome.addWidget(self.back_button)
        chrome.addWidget(self.forward_button)
        chrome.addWidget(self.reload_button)

        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("addressBar")
        self.search_bar.setPlaceholderText("Search or enter an address")
        self.search_bar.returnPressed.connect(self.load_url)
        chrome.addWidget(self.search_bar, 1)

        self.bookmark_button = QPushButton("☆")
        self.bookmark_button.setObjectName("chromeButton")
        self.bookmark_button.setToolTip("Bookmark this page")
        self.bookmark_button.clicked.connect(self.toggle_bookmark)
        chrome.addWidget(self.bookmark_button)

        self.distill_button = QPushButton("✦  Distill")
        self.distill_button.setObjectName("distillButton")
        self.distill_button.clicked.connect(self.distill_tab)
        chrome.addWidget(self.distill_button)
        self.spectrum_button = QPushButton("Spectrum")
        self.spectrum_button.setObjectName("chromeButton")
        self.spectrum_button.clicked.connect(self.open_spectrum_dialog)
        chrome.addWidget(self.spectrum_button)
        self.library_button = QPushButton("Library")
        self.library_button.setObjectName("chromeButton")
        self.library_button.clicked.connect(self.open_library)
        chrome.addWidget(self.library_button)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("chromeButton")
        self.settings_button.clicked.connect(self.open_settings)
        chrome.addWidget(self.settings_button)
        main_layout.addLayout(chrome)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        main_layout.addWidget(self.pages, 1)

        self._install_shortcuts()
        self.apply_theme()
        QApplication.styleHints().colorSchemeChanged.connect(
            self._system_theme_changed
        )
        for url in self.saved_pinned_urls:
            view = self.add_new_tab(QUrl(url), "Pinned tab")
            self.pinned_views.add(view)
        for url in self.saved_session["tabs"]:
            if url not in self.saved_pinned_urls:
                self.add_new_tab(QUrl(url), "Restoring tab")
        if self.tab_list.count() == 0:
            self.add_new_tab(label="New tab")
        if self.pinned_views:
            self._reorder_tabs()
        active_url = self.saved_session["active_url"]
        if active_url:
            for index in range(self.tab_list.count()):
                item = self.tab_list.item(index)
                view = item.data(Qt.ItemDataRole.UserRole)
                if self._tab_urls.get(view, view.url()).toString() == active_url:
                    self.tab_list.setCurrentItem(item)
                    break
        self._save_session_state()
        self._restore_sidebar_width()

    def _system_theme_changed(self, _scheme):
        """Refresh app colors when the OS appearance changes in System mode."""
        if self.theme == "system":
            self.apply_theme()

    def showEvent(self, event):
        """Re-evaluate compact mode once the splitter has its real on-screen size."""
        super().showEvent(event)
        self.apply_sidebar_mode()

    def _chrome_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setObjectName("chromeButton")
        return button

    def _install_shortcuts(self):
        modifier = "Meta" if sys.platform == "darwin" else "Ctrl"
        shortcuts = [
            (f"{modifier}+T", self.add_new_tab),
            (f"{modifier}+W", self.close_current_tab),
            (f"{modifier}+L", self.focus_address_bar),
            (f"{modifier}+D", self.toggle_bookmark),
        ]
        for sequence, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)

    def add_new_tab(self, url: QUrl | None = None, label: str = "New tab"):
        if not isinstance(url, QUrl):
            url = None
        is_home = url is None
        target_url = QUrl.fromLocalFile(str(HOME_PAGE)) if is_home else url
        view = QWebEngineView()
        page = QWebEnginePage(self.web_profile, view)
        view.setPage(page)
        if is_home:
            bridge = HomeBridge(self._home_appearance(), view)
            bridge.searchRequested.connect(
                lambda text, browser=view: self.navigate_home_search(browser, text)
            )
            channel = QWebChannel(page)
            channel.registerObject("prism", bridge)
            page.setWebChannel(channel)
            self._home_bridges[view] = bridge
            self._home_channels[view] = channel
        self.views.append(view)
        self._tab_urls[view] = target_url
        self.pages.addWidget(view)
        item = QListWidgetItem(f"◉  {label}")
        item.setData(Qt.ItemDataRole.UserRole, view)
        item.setToolTip(label)
        item.setIcon(view.icon())
        self.tab_list.addItem(item)
        self.tab_list.setCurrentItem(item)
        view.titleChanged.connect(
            lambda title, browser=view: self.update_tab_title(browser, title)
        )
        view.iconChanged.connect(
            lambda icon, browser=view: self.update_tab_icon(browser, icon)
        )
        view.urlChanged.connect(
            lambda qurl, browser=view: self.update_address_bar(browser, qurl)
        )
        view.urlChanged.connect(
            lambda qurl, browser=view: self._record_tab_url(browser, qurl)
        )
        view.load(target_url)
        self._save_session_state()
        self.apply_sidebar_mode()
        return view

    def _record_tab_url(self, view: QWebEngineView, url: QUrl):
        self._tab_urls[view] = url
        self._save_session_state()

    def current_web_view(self) -> QWebEngineView | None:
        widget = self.pages.currentWidget()
        return widget if isinstance(widget, QWebEngineView) else None

    def activate_tab_item(self, item: QListWidgetItem | None, _previous=None):
        if item is None:
            return
        view = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(view, QWebEngineView):
            self.pages.setCurrentWidget(view)
            self.sync_active_tab()
            self._save_session_state()

    def sync_active_tab(self):
        view = self.current_web_view()
        if view is None:
            return
        self.search_bar.setText(view.url().toString())
        self.update_bookmark_button()
        self.back_button.setEnabled(view.history().canGoBack())
        self.forward_button.setEnabled(view.history().canGoForward())

    def update_tab_title(self, view: QWebEngineView, title: str):
        item = self._item_for_view(view)
        if item is not None:
            shown_title = title.strip() or "New tab"
            prefix = "◆" if view in self.pinned_views else "◉"
            item.setText(f"{prefix}  {shown_title[:28]}")
            item.setToolTip(shown_title)
        if view is self.current_web_view():
            self.setWindowTitle(f"{title or 'New tab'} — Prism")

    def update_tab_icon(self, view: QWebEngineView, icon):
        """Refresh a tab's favicon in the sidebar delegate."""
        item = self._item_for_view(view)
        if item is not None:
            item.setIcon(icon)
            self.tab_list.viewport().update()

    def update_address_bar(self, view: QWebEngineView, qurl: QUrl):
        if view is self.current_web_view():
            self.search_bar.setText(qurl.toString())
            self.update_bookmark_button()
            self.back_button.setEnabled(view.history().canGoBack())
            self.forward_button.setEnabled(view.history().canGoForward())

    def go_back(self):
        view = self.current_web_view()
        if view:
            view.back()

    def go_forward(self):
        view = self.current_web_view()
        if view:
            view.forward()

    def reload_page(self):
        view = self.current_web_view()
        if view:
            view.reload()

    def load_url(self):
        view = self.current_web_view()
        text = self.search_bar.text().strip()
        if view is None or not text:
            return
        self.navigate_home_search(view, text)

    def navigate_home_search(self, view: QWebEngineView, text: str):
        """Navigate a tab using the browser's standard address/search behavior."""
        text = text.strip()
        if not text:
            return
        if " " in text or "." not in text:
            query = QUrl.toPercentEncoding(text).data().decode("ascii")
            url = QUrl(f"https://www.google.com/search?q={query}")
        else:
            url = QUrl.fromUserInput(text)
        view.load(url)

    def focus_address_bar(self):
        self.search_bar.setFocus()
        self.search_bar.selectAll()

    def close_current_tab(self):
        item = self.tab_list.currentItem()
        if item is not None:
            self.close_tab(self.tab_list.row(item))

    def close_view(self, view):
        """Close a tab requested by its inline sidebar close affordance."""
        item = self._item_for_view(view)
        if item is not None:
            self.close_tab(self.tab_list.row(item))

    def close_tab(self, index: int):
        item = self.tab_list.item(index)
        if item is None:
            return
        view = item.data(Qt.ItemDataRole.UserRole)
        if self.tab_list.count() == 1:
            self.add_new_tab()
        self.tab_list.takeItem(index)
        if view in self.views:
            self.views.remove(view)
        self.pinned_views.discard(view)
        self._tab_urls.pop(view, None)
        self._home_bridges.pop(view, None)
        self._home_channels.pop(view, None)
        self._spectrum_bridges.pop(view, None)
        self._spectrum_channels.pop(view, None)
        self._spectrum_tab_ids.pop(view, None)
        self.pages.removeWidget(view)
        view.deleteLater()
        self._save_session_state()
        self.apply_sidebar_mode()

    def show_tab_menu(self, position):
        item = self.tab_list.itemAt(position)
        if item is None:
            return
        view = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pin_action = menu.addAction(
            "Unpin tab" if view in self.pinned_views else "Pin tab"
        )
        close_action = menu.addAction("Close tab")
        menu.addSeparator()
        create_spectrum_action = menu.addAction("Create Spectrum from tab")
        add_spectrum_action = menu.addAction("Add tab to existing Spectrum")
        add_selection_action = menu.addAction("Add selection to Spectrum")
        is_spectrum = view in self._spectrum_tab_ids
        create_spectrum_action.setEnabled(not is_spectrum)
        add_spectrum_action.setEnabled(not is_spectrum)
        add_selection_action.setEnabled(not is_spectrum)
        selected = menu.exec(self.tab_list.mapToGlobal(position))
        if selected is pin_action:
            self.toggle_pin(view)
        elif selected is close_action:
            self.close_tab(self.tab_list.row(item))
        elif selected is create_spectrum_action:
            self.create_spectrum_from_current_tab(view)
        elif selected is add_spectrum_action:
            self.add_current_tab_to_spectrum(view)
        elif selected is add_selection_action:
            self.add_selection_to_spectrum(view)

    def create_empty_spectrum(self):
        """Create and open a blank, immediately persisted Spectrum."""
        spectrum_id = self._persist_spectrum(None, "Untitled Spectrum", "", [])
        if spectrum_id is not None:
            self.add_spectrum_tab(spectrum_id)

    def open_spectrum_dialog(self):
        """Choose source tabs for a new Spectrum, or create an empty one."""
        dialog = SpectrumDialog(
            self.views, self.current_web_view(), parent=self
        )
        if dialog.exec() != SpectrumDialog.DialogCode.Accepted:
            return
        if dialog.create_empty:
            self.create_empty_spectrum()
            return
        selected_views = dialog.selected_views()
        self.create_spectrum_from_tabs(selected_views, dialog.research_focus)

    def create_spectrum_from_tabs(
        self, source_views: list[QWebEngineView], research_focus: str = ""
    ) -> None:
        """Create a focused AI-curated Spectrum from the selected source tabs."""
        if not source_views:
            return
        collector = HtmlCollector(source_views, parent=self)
        self._html_collectors.add(collector)
        collector.finished.connect(
            lambda sources, missing, task=collector, focus=research_focus:
                self._spectrum_sources_collected(task, sources, missing, focus)
        )
        collector.start()

    def _spectrum_sources_collected(
        self,
        collector: HtmlCollector,
        sources: list[dict[str, str]],
        missing: list[str],
        research_focus: str,
    ) -> None:
        """Curate gathered page HTML off-thread and report skipped tabs."""
        self._html_collectors.discard(collector)
        collector.deleteLater()
        if missing:
            QMessageBox.warning(
                self,
                "Some tabs could not be read",
                "Continuing without these tabs:\n" + "\n".join(missing),
            )
        if not sources:
            QMessageBox.warning(
                self, "Spectrum", "No selected tabs could be read."
            )
            return
        worker = DistillWorker(sources, "spectrum", research_focus)
        self._distill_workers[id(worker)] = worker
        worker.signals.finished.connect(self._spectrum_curation_succeeded)
        worker.signals.error.connect(self._spectrum_curation_failed)
        self.thread_pool.start(worker)

    @pyqtSlot(int, str, str, str, str, str, str)
    def _spectrum_curation_succeeded(
        self,
        task_id: int,
        _worker_title: str,
        _source_url: str,
        _mode: str,
        summary_markdown: str,
        _summary_html: str,
        sources_json: str,
    ) -> None:
        """Persist the relevant AI-curated findings as an editable note block."""
        self._distill_workers.pop(task_id, None)
        try:
            sources = json.loads(sources_json)
            if not isinstance(sources, list) or not sources:
                raise ValueError("Spectrum source details were not returned.")
            if not summary_markdown.strip():
                raise ValueError("No relevant findings were returned for this Spectrum.")
        except (json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(self, "Spectrum creation failed", str(exc))
            return

        source_titles = [
            str(source.get("title", "")).strip()
            for source in sources
            if isinstance(source, dict) and source.get("title")
        ]
        if len(source_titles) == 1:
            title = source_titles[0]
        elif len(source_titles) <= 3:
            title = " + ".join(source_titles) or "Research Spectrum"
        else:
            title = f"{source_titles[0]} + {len(source_titles) - 1} more"
        source_url = str(sources[0].get("url", ""))
        spectrum_id = self._persist_spectrum(
            None,
            title,
            source_url,
            [
                {
                    "kind": "text",
                    "content": summary_markdown.strip(),
                    "source_url": source_url,
                }
            ],
        )
        if spectrum_id is not None:
            self.add_spectrum_tab(spectrum_id)

    @pyqtSlot(int, str)
    def _spectrum_curation_failed(self, task_id: int, message: str) -> None:
        """Report AI curation failures without creating an incomplete Spectrum."""
        self._distill_workers.pop(task_id, None)
        QMessageBox.warning(self, "Spectrum creation failed", message)

    def create_spectrum_from_current_tab(self, view=None):
        """Extract a page into ordered, source-linked Spectrum blocks."""
        source_view = view or self.current_web_view()
        if source_view is None or source_view in self._spectrum_tab_ids:
            return
        self._extract_spectrum_blocks(
            source_view,
            lambda blocks: self._create_spectrum_from_blocks(source_view, blocks),
        )

    def _create_spectrum_from_blocks(
        self, source_view: QWebEngineView, blocks: list[dict[str, str]]
    ):
        if not blocks:
            QMessageBox.information(
                self, "Spectrum", "No readable page content was found."
            )
            return
        source_url = self._tab_urls.get(source_view, source_view.url()).toString()
        title = source_view.title().strip() or "Untitled Spectrum"
        spectrum_id = self._persist_spectrum(None, title, source_url, blocks)
        if spectrum_id is not None:
            self.add_spectrum_tab(spectrum_id)

    def add_current_tab_to_spectrum(self, view=None):
        """Append extracted page blocks to a selected saved Spectrum."""
        source_view = view or self.current_web_view()
        if source_view is None or source_view in self._spectrum_tab_ids:
            return
        spectrum_id = self._choose_existing_spectrum()
        if spectrum_id is None:
            return
        self._extract_spectrum_blocks(
            source_view,
            lambda blocks: self._append_spectrum_blocks(
                spectrum_id, blocks, source_view
            ),
        )

    def add_selection_to_spectrum(self, view=None):
        """Append the selected text from a page as a cited text block."""
        source_view = view or self.current_web_view()
        if source_view is None or source_view in self._spectrum_tab_ids:
            return
        spectrum_id = self._choose_existing_spectrum()
        if spectrum_id is None:
            return

        def append_selection(selection):
            text = str(selection or "").strip()
            if not text:
                QMessageBox.information(
                    self, "Spectrum", "Select some page text before adding it."
                )
                return
            source_url = self._tab_urls.get(source_view, source_view.url()).toString()
            self._append_spectrum_blocks(
                spectrum_id,
                [{"kind": "text", "content": text, "source_url": source_url}],
                source_view,
            )

        source_view.page().runJavaScript(
            "window.getSelection ? window.getSelection().toString() : ''",
            append_selection,
        )

    def _choose_existing_spectrum(self) -> int | None:
        """Prompt for a saved Spectrum, returning its database ID."""
        try:
            records = self.spectrums.list_spectrums()
        except sqlite3.Error as exc:
            QMessageBox.warning(self, "Spectrum error", str(exc))
            return None
        if not records:
            QMessageBox.information(
                self, "Spectrum", "Create a Spectrum before adding content."
            )
            return None
        labels = [f"{record.title}  ·  {record.updated_at}" for record in records]
        selected, accepted = QInputDialog.getItem(
            self, "Choose Spectrum", "Add content to:", labels, 0, False
        )
        if not accepted:
            return None
        return records[labels.index(selected)].id

    def _append_spectrum_blocks(
        self,
        spectrum_id: int,
        blocks: list[dict[str, str]],
        source_view: QWebEngineView,
    ):
        if not blocks:
            QMessageBox.information(
                self, "Spectrum", "No readable page content was found."
            )
            return
        try:
            record = self.spectrums.get_spectrum(spectrum_id)
        except sqlite3.Error as exc:
            QMessageBox.warning(self, "Spectrum error", str(exc))
            return
        if record is None:
            QMessageBox.warning(
                self, "Spectrum", "The selected Spectrum no longer exists."
            )
            return
        all_blocks: list[dict[str, object]] = [
            {
                "id": block.id,
                "kind": block.kind,
                "content": block.content,
                "source_url": block.source_url,
            }
            for block in record.blocks
        ]
        all_blocks.extend(blocks)
        saved_id = self._persist_spectrum(
            spectrum_id,
            record.title,
            record.source_url
            or self._tab_urls.get(source_view, source_view.url()).toString(),
            all_blocks,
        )
        if saved_id is not None:
            self.add_spectrum_tab(saved_id)

    def _persist_spectrum(
        self,
        spectrum_id: int | None,
        title: str,
        source_url: str,
        blocks: list[dict[str, object]],
    ) -> int | None:
        """Save through the repository and report storage validation errors."""
        try:
            return self.spectrums.save_spectrum(
                spectrum_id, title, source_url, blocks
            )
        except (sqlite3.Error, ValueError) as exc:
            QMessageBox.warning(self, "Spectrum save error", str(exc))
            return None

    def _extract_spectrum_blocks(
        self,
        view: QWebEngineView,
        callback: Callable[[list[dict[str, str]]], None],
    ) -> None:
        """Collect readable DOM blocks asynchronously from the selected tab."""
        script = """
        (() => {
          const root = document.querySelector("article") ||
                       document.querySelector("main") || document.body;
          const nodes = root.querySelectorAll(
            "h1,h2,h3,h4,h5,h6,p,li,blockquote,img"
          );
          const blocks = [];
          for (const node of nodes) {
            if (!node.getClientRects().length ||
                node.closest("nav,footer,aside,[aria-hidden='true']")) continue;
            const tag = node.tagName.toLowerCase();
            let kind = "text";
            let content = "";
            if (tag === "img") {
              kind = "image";
              content = node.currentSrc || node.src || "";
            } else {
              if (tag[0] === "h") kind = "heading";
              if (tag === "blockquote") kind = "quote";
              if ((tag === "p" && node.closest("li,blockquote")) ||
                  (tag === "li" && node.parentElement?.closest("li"))) continue;
              content = (node.innerText || node.textContent || "").trim();
            }
            if (content && blocks.length < 120) blocks.push({kind, content});
          }
          return blocks;
        })()
        """

        def extracted(raw_blocks):
            if not isinstance(raw_blocks, list):
                callback([])
                return
            source_url = self._tab_urls.get(view, view.url()).toString()
            blocks: list[dict[str, str]] = []
            for block in raw_blocks:
                if not isinstance(block, dict):
                    continue
                kind = str(block.get("kind", "text"))
                content = str(block.get("content", "")).strip()
                if kind not in SpectrumRepository.BLOCK_KINDS or not content:
                    continue
                if kind == "image" and QUrl(content).scheme().lower() not in {
                    "http",
                    "https",
                }:
                    continue
                blocks.append(
                    {
                        "kind": kind,
                        "content": content[:12000],
                        "source_url": source_url,
                    }
                )
            callback(blocks)

        view.page().runJavaScript(script, extracted)

    def open_saved_spectrum(self):
        """Open an existing Spectrum by selecting it from the saved list."""
        spectrum_id = self._choose_existing_spectrum()
        if spectrum_id is not None:
            self.add_spectrum_tab(spectrum_id)

    def add_spectrum_tab(self, spectrum_id: int) -> QWebEngineView | None:
        """Open a saved Spectrum in a local editor tab, or focus it if open."""
        try:
            record = self.spectrums.get_spectrum(spectrum_id)
        except sqlite3.Error as exc:
            QMessageBox.warning(self, "Spectrum error", str(exc))
            return None
        if record is None:
            QMessageBox.warning(self, "Spectrum", "The selected Spectrum was not found.")
            return None
        for existing_view, existing_id in self._spectrum_tab_ids.items():
            if existing_id == spectrum_id:
                item = self._item_for_view(existing_view)
                if item is not None:
                    self.tab_list.setCurrentItem(item)
                return existing_view

        view = QWebEngineView()
        page = QWebEnginePage(self.web_profile, view)
        view.setPage(page)
        bridge = SpectrumBridge(
            self.spectrums, spectrum_id, self._home_appearance(), view
        )
        bridge.errorOccurred.connect(
            lambda message: QMessageBox.warning(self, "Spectrum save error", message)
        )
        bridge.chatRequested.connect(
            lambda content, paths, browser=view: self._start_spectrum_chat(
                browser, content, paths
            )
        )
        bridge.insertRequested.connect(
            lambda content, block_id, browser=view: self._request_spectrum_insert(
                browser, content, block_id
            )
        )
        channel = QWebChannel(page)
        channel.registerObject("spectrum", bridge)
        page.setWebChannel(channel)
        self._spectrum_bridges[view] = bridge
        self._spectrum_channels[view] = channel
        self._spectrum_tab_ids[view] = spectrum_id
        self.views.append(view)
        target_url = QUrl.fromLocalFile(str(SPECTRUM_PAGE))
        self._tab_urls[view] = target_url
        self.pages.addWidget(view)
        item = QListWidgetItem(f"◉  {record.title[:28]}")
        item.setData(Qt.ItemDataRole.UserRole, view)
        item.setToolTip(record.title)
        self.tab_list.addItem(item)
        self.tab_list.setCurrentItem(item)
        view.titleChanged.connect(
            lambda title, browser=view: self.update_tab_title(browser, title)
        )
        view.iconChanged.connect(
            lambda icon, browser=view: self.update_tab_icon(browser, icon)
        )
        view.urlChanged.connect(
            lambda qurl, browser=view: self.update_address_bar(browser, qurl)
        )
        view.load(target_url)
        self._save_session_state()
        self.apply_sidebar_mode()
        return view

    def _run_spectrum_js(self, view: QWebEngineView, function: str, *args) -> None:
        """Invoke a fixed Spectrum-page function with safely encoded arguments."""
        if view not in self.views:
            return
        encoded_args = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
        function_name = json.dumps(function)
        view.page().runJavaScript(
            f"window[{function_name}] && window[{function_name}]({encoded_args});"
        )

    def _start_spectrum_chat(
        self, view: QWebEngineView, content: str, image_paths_json: str
    ) -> None:
        """Persist a user turn and run Gemini chat on the shared thread pool."""
        spectrum_id = self._spectrum_tab_ids.get(view)
        if spectrum_id is None or view not in self.views:
            return
        try:
            image_paths = json.loads(image_paths_json)
            if not isinstance(image_paths, list) or len(image_paths) > 5:
                raise ValueError("Attach no more than five images to one chat message.")
            if not all(isinstance(path, str) for path in image_paths):
                raise ValueError("Chat image paths are invalid.")
            content = content.strip()
            if len(content) > 12_000:
                raise ValueError("Chat messages are limited to 12,000 characters.")
            if not content and not image_paths:
                return
            self.spectrums.save_chat_message(
                spectrum_id, "user", content, image_paths
            )
            history = [
                {
                    "role": message.role,
                    "content": message.content,
                    "image_paths": message.image_paths,
                }
                for message in self.spectrums.list_chat_messages(spectrum_id)
            ]
            record = self.spectrums.get_spectrum(spectrum_id)
        except (json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
            self._run_spectrum_js(view, "prismChatError", str(exc))
            return
        if record is None:
            self._run_spectrum_js(view, "prismChatError", "Spectrum no longer exists.")
            return
        if spectrum_id in self._spectrum_chat_workers:
            self._run_spectrum_js(view, "prismChatError", "A chat response is already running.")
            return

        context_lines = [
            f"Spectrum: {record.title}",
            f"Source: {record.source_url}",
        ]
        context_lines.extend(
            f"[{block.kind}] {block.content[:1200]} (source: {block.source_url})"
            for block in record.blocks
        )
        worker = SpectrumChatWorker(history, "\n\n".join(context_lines))
        self._spectrum_chat_workers[spectrum_id] = worker
        worker.signals.started.connect(
            lambda browser=view: self._run_spectrum_js(browser, "prismChatStarted")
        )
        worker.signals.chunk.connect(
            lambda text, browser=view: self._run_spectrum_js(
                browser, "prismChatChunk", text
            )
        )
        worker.signals.resetStream.connect(
            lambda browser=view: self._run_spectrum_js(
                browser, "prismChatResetStream"
            )
        )
        worker.signals.toolRequested.connect(
            lambda request_id, name, args, browser=view, chat_worker=worker:
                self._handle_spectrum_tool_request(
                    browser, chat_worker, request_id, name, args
                )
        )
        worker.signals.finished.connect(
            lambda answer, browser=view, chat_worker=worker, note_id=spectrum_id:
                self._spectrum_chat_finished(
                    browser, chat_worker, note_id, answer
                )
        )
        worker.signals.error.connect(
            lambda message, browser=view, chat_worker=worker, note_id=spectrum_id:
                self._spectrum_chat_failed(
                    browser, chat_worker, note_id, message
                )
        )
        self.thread_pool.start(worker)

    def _spectrum_chat_finished(
        self,
        view: QWebEngineView,
        worker: SpectrumChatWorker,
        spectrum_id: int,
        answer: str,
    ) -> None:
        """Persist and display a completed assistant response."""
        self._spectrum_chat_workers.pop(spectrum_id, None)
        try:
            self.spectrums.save_chat_message(spectrum_id, "assistant", answer)
        except (sqlite3.Error, ValueError) as exc:
            self._run_spectrum_js(
                view, "prismChatError", f"Reply generated but could not be saved: {exc}"
            )
            return
        self._run_spectrum_js(view, "prismChatFinished", answer)

    def _spectrum_chat_failed(
        self,
        view: QWebEngineView,
        worker: SpectrumChatWorker,
        spectrum_id: int,
        message: str,
    ) -> None:
        """Show a visible error after a background chat request fails."""
        self._spectrum_chat_workers.pop(spectrum_id, None)
        self._run_spectrum_js(view, "prismChatError", message)

    def _request_spectrum_insert(
        self, view: QWebEngineView, content: str, block_id: str
    ) -> None:
        """Insert or replace a note block from a rendered assistant response."""
        self._run_spectrum_js(view, "prismInsertChat", content, block_id)

    def _handle_spectrum_tool_request(
        self,
        view: QWebEngineView,
        worker: SpectrumChatWorker,
        request_id: str,
        name: str,
        arguments_json: str,
    ) -> None:
        """Validate and execute one model-requested action on the GUI thread."""
        try:
            arguments = json.loads(arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object.")
        except (json.JSONDecodeError, ValueError) as exc:
            worker.provide_tool_result(request_id, {"error": str(exc)})
            return
        if view not in self.views:
            worker.provide_tool_result(request_id, {"error": "Spectrum tab was closed."})
            return

        labels = {
            "list_open_tabs": "Listing open tabs",
            "read_tab": "Reading an open tab",
            "open_url": "Opening a URL",
            "search_web": "Searching the web",
            "add_to_spectrum": "Adding content to Spectrum",
            "distill_tabs": "Distilling selected tabs",
        }
        if name not in labels:
            worker.provide_tool_result(request_id, {"error": "Unknown Prism tool."})
            return
        self._run_spectrum_js(view, "prismChatStep", labels[name] + "…")
        if name in {"open_url", "search_web", "distill_tabs"}:
            if not self._confirm_spectrum_tool(name, arguments):
                worker.provide_tool_result(
                    request_id, {"cancelled": True, "message": "User declined the action."}
                )
                self._run_spectrum_js(view, "prismChatStep", "Action cancelled")
                return

        if name == "list_open_tabs":
            worker.provide_tool_result(
                request_id,
                {
                    "tabs": [
                        {
                            "tab_id": index,
                            "title": tab.title() or "Untitled tab",
                            "url": self._tab_urls.get(tab, tab.url()).toString(),
                        }
                        for index, tab in enumerate(self.views)
                    ]
                },
            )
            return

        if name == "read_tab":
            tab = self._tool_tab(arguments.get("tab_id"))
            if tab is None:
                worker.provide_tool_result(request_id, {"error": "Tab ID was not found."})
                return

            def read_html(raw_html: str) -> None:
                text = extract_text_from_html(raw_html, max_chars=12_000)
                worker.provide_tool_result(
                    request_id,
                    {
                        "title": tab.title() or "Untitled tab",
                        "url": self._tab_urls.get(tab, tab.url()).toString(),
                        "text": text,
                    },
                )

            tab.page().toHtml(read_html)
            return

        if name == "open_url":
            raw_url = arguments.get("url")
            url = QUrl.fromUserInput(str(raw_url or "").strip())
            if url.scheme().lower() not in {"http", "https"} or not url.host():
                worker.provide_tool_result(
                    request_id, {"error": "Only valid HTTP or HTTPS URLs can be opened."}
                )
                return
            self.add_new_tab(url, url.host())
            worker.provide_tool_result(request_id, {"opened": url.toString()})
            return

        if name == "search_web":
            query = str(arguments.get("query", "")).strip()
            if not query or len(query) > 1000:
                worker.provide_tool_result(request_id, {"error": "Search query is empty or too long."})
                return
            encoded = QUrl.toPercentEncoding(query).data().decode("ascii")
            url = QUrl(f"https://www.google.com/search?q={encoded}")
            self.add_new_tab(url, f"Search: {query[:24]}")
            worker.provide_tool_result(request_id, {"search_url": url.toString()})
            return

        if name == "add_to_spectrum":
            self._tool_add_to_spectrum(view, worker, request_id, arguments)
            return

        if name == "distill_tabs":
            self._tool_distill_tabs(worker, request_id, arguments)

    def _confirm_spectrum_tool(self, name: str, arguments: dict[str, object]) -> bool:
        """Require user approval before a model tool opens tabs or navigates."""
        if name == "open_url":
            description = f"Open this URL in a new Prism tab?\n\n{arguments.get('url', '')}"
        elif name == "search_web":
            description = f"Open a Google search tab for:\n\n{arguments.get('query', '')}"
        else:
            description = (
                "Read the selected tabs, generate a distillation, save it, "
                "and open the result in a new tab?"
            )
        return (
            QMessageBox.question(
                self,
                "Prism assistant confirmation",
                description,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _tool_tab(self, raw_tab_id: object) -> QWebEngineView | None:
        """Resolve the current numeric tab ID supplied to the model."""
        if isinstance(raw_tab_id, bool):
            return None
        if not isinstance(raw_tab_id, (int, str)):
            return None
        if isinstance(raw_tab_id, str) and not raw_tab_id.isdecimal():
            return None
        try:
            index = int(raw_tab_id)
        except (TypeError, ValueError):
            return None
        return self.views[index] if 0 <= index < len(self.views) else None

    def _tool_add_to_spectrum(
        self,
        view: QWebEngineView,
        worker: SpectrumChatWorker,
        request_id: str,
        arguments: dict[str, object],
    ) -> None:
        """Append one text block to the Spectrum being chatted about."""
        spectrum_id = self._spectrum_tab_ids.get(view)
        text = str(arguments.get("text", "")).strip()
        if spectrum_id is None or not text or len(text) > 12_000:
            worker.provide_tool_result(
                request_id, {"error": "Text must be 1–12,000 characters."}
            )
            return
        try:
            record = self.spectrums.get_spectrum(spectrum_id)
        except sqlite3.Error as exc:
            worker.provide_tool_result(request_id, {"error": str(exc)})
            return
        if record is None:
            worker.provide_tool_result(request_id, {"error": "Spectrum no longer exists."})
            return
        source_url = str(arguments.get("source_url") or record.source_url)
        if source_url:
            source = QUrl(source_url)
            if source.scheme().lower() not in {"http", "https"} or not source.host():
                worker.provide_tool_result(
                    request_id,
                    {"error": "Source URL must use HTTP or HTTPS."},
                )
                return
        blocks: list[dict[str, object]] = [
            {
                "id": block.id,
                "kind": block.kind,
                "content": block.content,
                "source_url": block.source_url,
            }
            for block in record.blocks
        ]
        blocks.append(
            {
                "kind": "text",
                "content": text,
                "source_url": source_url,
            }
        )
        saved = self._persist_spectrum(
            spectrum_id, record.title, record.source_url, blocks
        )
        if saved is not None:
            self._run_spectrum_js(view, "prismReloadSpectrum")
            worker.provide_tool_result(request_id, {"added": True, "source_url": source_url})
        else:
            worker.provide_tool_result(request_id, {"error": "Could not save this block."})

    def _tool_distill_tabs(
        self,
        worker: SpectrumChatWorker,
        request_id: str,
        arguments: dict[str, object],
    ) -> None:
        """Collect selected pages and run the existing asynchronous distiller."""
        raw_ids = arguments.get("tab_ids")
        mode = arguments.get("mode")
        if (
            not isinstance(raw_ids, list)
            or not raw_ids
            or not isinstance(mode, str)
            or mode not in {"summary", "compare"}
            or len(raw_ids) > len(self.views)
        ):
            worker.provide_tool_result(request_id, {"error": "Tab IDs or mode are invalid."})
            return
        tabs: list[QWebEngineView] = []
        for raw_id in raw_ids:
            tab = self._tool_tab(raw_id)
            if (
                tab is None
                or not self._is_web_url(self._tab_urls.get(tab, tab.url()))
                or tab in tabs
            ):
                worker.provide_tool_result(
                    request_id, {"error": "Every selected ID must be a unique HTTP(S) tab."}
                )
                return
            tabs.append(tab)
        if mode == "compare" and len(tabs) < 2:
            worker.provide_tool_result(
                request_id, {"error": "Compare mode requires at least two tabs."}
            )
            return

        collector = HtmlCollector(tabs, parent=self)
        self._html_collectors.add(collector)

        def collected(sources, missing):
            self._html_collectors.discard(collector)
            collector.deleteLater()
            if not sources:
                worker.provide_tool_result(
                    request_id, {"error": "No selected tabs could be read."}
                )
                return
            if missing:
                self._run_spectrum_js(
                    next(
                        (
                            browser
                            for browser, browser_id in self._spectrum_tab_ids.items()
                            if self._spectrum_chat_workers.get(browser_id) is worker
                        ),
                        None,
                    ),
                    "prismChatStep",
                    f"Continuing without {len(missing)} unreadable tab(s)",
                )
            distill_worker = DistillWorker(sources, str(mode))
            self._distill_workers[id(distill_worker)] = distill_worker
            distill_worker.signals.finished.connect(
                lambda *result, task=distill_worker:
                    self._agent_distillation_finished(task, worker, request_id, result)
            )
            distill_worker.signals.error.connect(
                lambda task_id, message, task=distill_worker:
                    self._agent_distillation_failed(task, worker, request_id, message)
            )
            self.thread_pool.start(distill_worker)

        collector.finished.connect(collected)
        collector.start()

    def _agent_distillation_finished(
        self,
        distill_worker: DistillWorker,
        chat_worker: SpectrumChatWorker,
        request_id: str,
        result: tuple[object, ...],
    ) -> None:
        """Open/save a tool-generated distillation and return its text to chat."""
        self._distillation_succeeded(*result)
        chat_worker.provide_tool_result(
            request_id,
            {
                "title": result[1],
                "summary": result[4],
                "source_url": result[2],
            },
        )

    def _agent_distillation_failed(
        self,
        distill_worker: DistillWorker,
        chat_worker: SpectrumChatWorker,
        request_id: str,
        message: str,
    ) -> None:
        """Return a distillation failure as a tool result without hiding it."""
        self._distill_workers.pop(id(distill_worker), None)
        chat_worker.provide_tool_result(request_id, {"error": message})

    def toggle_pin(self, view: QWebEngineView):
        if view in self.pinned_views:
            self.pinned_views.remove(view)
        else:
            self.pinned_views.add(view)
        self._reorder_tabs()

    def _reorder_tabs(self):
        current = self.current_web_view()
        ordered = [v for v in self.views if v in self.pinned_views]
        ordered += [v for v in self.views if v not in self.pinned_views]
        self.tab_list.blockSignals(True)
        self.tab_list.clear()
        for view in ordered:
            title = view.title().strip() or "New tab"
            prefix = "◆" if view in self.pinned_views else "◉"
            item = QListWidgetItem(f"{prefix}  {title[:28]}")
            item.setData(Qt.ItemDataRole.UserRole, view)
            item.setToolTip(title)
            item.setIcon(view.icon())
            self.tab_list.addItem(item)
            if view is current:
                self.tab_list.setCurrentItem(item)
        self.tab_list.blockSignals(False)
        self._save_session_state()
        self.apply_sidebar_mode()

    def _tab_order_changed(self, *_args):
        """Keep browser view order synchronized with dragged sidebar rows."""
        self.views = [
            self.tab_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.tab_list.count())
        ]
        self._save_session_state()

    def _splitter_moved(self, position: int, _index: int):
        """Remember the sidebar size and apply icon-only compact mode."""
        self.library.set_setting("sidebar_width", str(position))
        self.apply_sidebar_mode()

    def _restore_sidebar_width(self):
        """Restore the saved sidebar width, using the default on invalid values."""
        try:
            width = max(
                68, min(360, int(self.library.get_setting("sidebar_width", "248")))
            )
        except ValueError:
            width = 248
        self.splitter.setSizes([width, max(600, self.width() - width)])
        self.apply_sidebar_mode()

    def apply_sidebar_mode(self):
        """Switch sidebar labels and bookmark list for compact widths."""
        compact = self.sidebar.width() < 126
        self.tabs_label.setVisible(not compact)
        self.bookmarks_header.setVisible(not compact)
        self.bookmark_list.setVisible(not compact)
        self.brand_name.setVisible(not compact)
        self.tab_list.compact = compact
        self.tab_list.viewport().update()
        for index in range(self.tab_list.count()):
            item = self.tab_list.item(index)
            view = item.data(Qt.ItemDataRole.UserRole)
            title = view.title().strip() or "New tab"
            prefix = "◆" if view in self.pinned_views else "◉"
            item.setText(f"{prefix}  {title[:28]}")
            item.setIcon(view.icon())

    def toggle_bookmark(self):
        view = self.current_web_view()
        if view is None or not view.url().isValid():
            return
        url = view.url().toString()
        existing = next((entry for entry in self.bookmarks if entry["url"] == url), None)
        if existing:
            self.bookmarks.remove(existing)
        else:
            self.bookmarks.append(
                {"title": view.title() or url, "url": url}
            )
        self._save_bookmarks()
        self.refresh_bookmarks()
        self.update_bookmark_button()

    def update_bookmark_button(self):
        view = self.current_web_view()
        bookmarked = bool(
            view and any(entry["url"] == view.url().toString() for entry in self.bookmarks)
        )
        self.bookmark_button.setText("★" if bookmarked else "☆")
        self.bookmark_button.setToolTip(
            "Remove bookmark" if bookmarked else "Bookmark this page"
        )

    def refresh_bookmarks(self):
        if not hasattr(self, "bookmark_list"):
            return
        self.bookmark_list.clear()
        for entry in self.bookmarks:
            item = QListWidgetItem(f"★  {entry['title'][:24]}")
            item.setData(Qt.ItemDataRole.UserRole, entry["url"])
            item.setToolTip(entry["url"])
            self.bookmark_list.addItem(item)

    def open_bookmark(self, item: QListWidgetItem):
        view = self.current_web_view()
        if view:
            view.load(QUrl(item.data(Qt.ItemDataRole.UserRole)))

    def _item_for_view(self, view: QWebEngineView) -> QListWidgetItem | None:
        for index in range(self.tab_list.count()):
            item = self.tab_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) is view:
                return item
        return None

    def _load_bookmarks(self) -> list[dict[str, str]]:
        try:
            entries = json.loads(self.settings.value("bookmarks", "[]"))
            return [
                {"title": str(entry["title"]), "url": str(entry["url"])}
                for entry in entries
                if isinstance(entry, dict) and entry.get("url")
            ]
        except (TypeError, ValueError, KeyError):
            return []

    def _save_bookmarks(self):
        self.settings.setValue("bookmarks", json.dumps(self.bookmarks))

    def _save_session_state(self):
        pinned_urls = [
            self._tab_urls.get(view, view.url()).toString()
            for view in self.views
            if view in self.pinned_views
            and self._is_web_url(self._tab_urls.get(view, view.url()))
        ]
        session_urls = [
            self._tab_urls.get(view, view.url()).toString()
            for view in self.views
            if view not in self.pinned_views
            and self._is_web_url(self._tab_urls.get(view, view.url()))
        ]
        current = self.current_web_view()
        current_url = (
            self._tab_urls.get(current, current.url())
            if current is not None
            else QUrl()
        )
        active_url = (
            current_url.toString()
            if self._is_web_url(current_url)
            else ""
        )
        self.settings.setValue("pinned_tabs", json.dumps(pinned_urls))
        self.settings.setValue(
            "session",
            json.dumps({"tabs": session_urls, "active_url": active_url}),
        )

    @staticmethod
    def _is_web_url(url: QUrl) -> bool:
        return url.scheme().lower() in {"http", "https"} and url.isValid()

    def _load_session(self) -> dict[str, object]:
        try:
            session = json.loads(self.settings.value("session", "{}"))
            tabs = session.get("tabs", [])
            active_url = session.get("active_url", "")
            return {
                "tabs": [
                    url
                    for url in tabs
                    if isinstance(url, str) and self._is_web_url(QUrl(url))
                ],
                "active_url": (
                    active_url
                    if isinstance(active_url, str)
                    and self._is_web_url(QUrl(active_url))
                    else ""
                ),
            }
        except (TypeError, ValueError, AttributeError):
            return {"tabs": [], "active_url": ""}

    def _load_pinned_urls(self) -> list[str]:
        try:
            urls = json.loads(self.settings.value("pinned_tabs", "[]"))
            return [
                url
                for url in urls
                if isinstance(url, str) and self._is_web_url(QUrl(url))
            ]
        except (TypeError, ValueError):
            return []

    def distill_tab(self):
        dialog = DistillDialog(self.views, self.current_web_view(), self)
        if dialog.exec() != DistillDialog.DialogCode.Accepted:
            return
        selected_views = dialog.selected_views()
        mode = dialog.mode
        research_focus = dialog.research_focus
        if not selected_views:
            return
        self.distill_button.setEnabled(False)
        self.distill_button.setText("Distilling…")
        collector = HtmlCollector(selected_views, parent=self)
        self._html_collectors.add(collector)
        collector.finished.connect(
            lambda sources, missing, collector=collector, selected_mode=mode,
            focus=research_focus:
                self._html_collection_finished(
                    collector, sources, missing, selected_mode, focus
                )
        )
        collector.start()

    def _html_collection_finished(
        self,
        collector: HtmlCollector,
        sources: list[dict[str, str]],
        missing: list[str],
        mode: str,
        research_focus: str = "",
    ):
        self._html_collectors.discard(collector)
        collector.deleteLater()
        if missing:
            QMessageBox.warning(
                self,
                "Some tabs could not be read",
                "Continuing without these tabs:\n" + "\n".join(missing),
            )
        if not sources:
            self._finish_distillation()
            QMessageBox.warning(
                self,
                "Distill failed",
                "No selected tabs could be read before the collection timeout.",
            )
            return
        worker = DistillWorker(sources, mode, research_focus)
        self._distill_workers[id(worker)] = worker
        worker.signals.finished.connect(self._distillation_succeeded)
        worker.signals.error.connect(self._distillation_failed)
        self.thread_pool.start(worker)

    @pyqtSlot(int, str, str, str, str, str, str)
    def _distillation_succeeded(
        self,
        task_id: int,
        title: str,
        source_url: str,
        mode: str,
        summary_markdown: str,
        summary_html: str,
        sources_json: str,
    ):
        self._distill_workers.pop(task_id, None)
        try:
            title = title or "Distilled page"
            try:
                self.library.save_distillation(
                    title=title,
                    mode=mode,
                    markdown=summary_markdown,
                    html=summary_html,
                    sources=json.loads(sources_json),
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Library save failed",
                    f"The summary was created but could not be saved:\n{exc}",
                )
            new_view = self.add_new_tab(QUrl("about:blank"), f"Distilled: {title[:18]}")
            assets_base = QUrl.fromLocalFile(f"{ASSET_DIR}/")
            themed_html = self._apply_theme_to_html(
                summary_html, self._theme_variables()
            )
            new_view.setHtml(themed_html, baseUrl=assets_base)
        finally:
            self._finish_distillation()

    @pyqtSlot(int, str)
    def _distillation_failed(self, task_id: int, message: str):
        self._distill_workers.pop(task_id, None)
        self._finish_distillation()
        QMessageBox.warning(self, "Distill failed", message)

    def _finish_distillation(self):
        self.distill_button.setEnabled(True)
        self.distill_button.setText("✦  Distill")

    def _resolved_theme(self) -> str:
        """Resolve the System theme preference to the current OS color scheme."""
        if self.theme in {"light", "dark"}:
            return self.theme
        scheme = QApplication.styleHints().colorScheme()
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"

    def _home_appearance(self) -> dict[str, str]:
        """Build appearance values shared with the homepage and generated pages."""
        background_url = ""
        if self.background_path and Path(self.background_path).is_file():
            background_url = QUrl.fromLocalFile(self.background_path).toString()
        return {
            "theme": self._resolved_theme(),
            "accent": ACCENTS.get(self.accent, ACCENTS["violet"]),
            "backgroundUrl": background_url,
        }

    def _theme_variables(self) -> str:
        """Return CSS variables for distill and future local web surfaces."""
        if self._resolved_theme() == "dark":
            colors = {
                "page-bg": "#17181d",
                "card-bg": "#202127",
                "text": "#e9e9ee",
                "muted": "#a2a4af",
                "border": "#373943",
                "code-bg": "#292b33",
                "quote-bg": "#292738",
            }
        else:
            colors = {
                "page-bg": "#f5f6f8",
                "card-bg": "#ffffff",
                "text": "#24252b",
                "muted": "#737681",
                "border": "#e6e7eb",
                "code-bg": "#f1f2f5",
                "quote-bg": "#f7f6ff",
            }
        colors["accent"] = ACCENTS.get(self.accent, ACCENTS["violet"])
        declarations = ";".join(
            f"--{name}:{value}" for name, value in colors.items()
        )
        return f":root{{{declarations}}}"

    @staticmethod
    def _apply_theme_to_html(page_html: str, variables: str) -> str:
        """Inject the current Prism color tokens into a generated page."""
        return page_html.replace(
            "</head>", f"<style>{variables}</style></head>", 1
        )

    def apply_theme(self):
        """Apply selected colors to browser chrome and local pages."""
        dark = self._resolved_theme() == "dark"
        self.setStyleSheet(
            self._stylesheet(dark, ACCENTS.get(self.accent, ACCENTS["violet"]))
        )
        appearance = self._home_appearance()
        for bridge in self._home_bridges.values():
            bridge.set_appearance(appearance)
        for bridge in self._spectrum_bridges.values():
            bridge.set_appearance(appearance)

    def open_settings(self):
        """Open appearance settings and persist any confirmed changes."""
        dialog = SettingsDialog(self.theme, self.accent, self.background_path, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        background_path = dialog.background_path
        if background_path:
            try:
                source = Path(background_path)
                if not source.is_file():
                    raise FileNotFoundError("Selected homepage image no longer exists.")
                data_dir = Path(
                    QStandardPaths.writableLocation(
                        QStandardPaths.StandardLocation.AppDataLocation
                    )
                )
                image_dir = data_dir / "images"
                image_dir.mkdir(parents=True, exist_ok=True)
                destination = image_dir / f"home-background{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                background_path = str(destination)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "Background image error",
                    f"Could not save the selected image:\n{exc}",
                )
                return

        try:
            self.library.set_setting("theme", dialog.theme)
            self.library.set_setting("accent", dialog.accent)
            self.library.set_setting("home_background", background_path)
        except Exception as exc:
            QMessageBox.warning(self, "Settings error", str(exc))
            return
        self.theme = dialog.theme
        self.accent = dialog.accent
        self.background_path = background_path
        self.apply_theme()

    def open_library(self):
        """Show saved distillations and reopen a selected library entry."""
        try:
            dialog = LibraryDialog(self.library, self)
        except Exception as exc:
            QMessageBox.warning(self, "Library error", str(exc))
            return
        if dialog.exec() != LibraryDialog.DialogCode.Accepted:
            return
        record = dialog.selected_record
        if record is None:
            return
        view = self.add_new_tab(
            QUrl("about:blank"), f"Distilled: {record.title[:18]}"
        )
        themed_html = self._apply_theme_to_html(
            record.html, self._theme_variables()
        )
        view.setHtml(themed_html, baseUrl=QUrl.fromLocalFile(f"{ASSET_DIR}/"))

    def closeEvent(self, event):
        self._save_session_state()
        super().closeEvent(event)

    @staticmethod
    def _stylesheet(dark: bool, accent: str) -> str:
        """Build native browser chrome styles from one light/dark token set."""
        if dark:
            window = "#191a20"
            sidebar = "#202127"
            surface = "#25262d"
            text = "#e9e9ee"
            muted = "#a2a4af"
            border = "#373943"
            hover = "#30313a"
            selected = "#33304a"
            selected_text = "#d1caff"
        else:
            window = "#f7f7f8"
            sidebar = "#f0f0f2"
            surface = "#ffffff"
            text = "#292932"
            muted = "#85858f"
            border = "#e4e4e8"
            hover = "#e8e7ed"
            selected = "#e9e6ff"
            selected_text = "#4439a9"
        return f"""
            QMainWindow, QWidget#pages {{ background: {window}; }}
            QWidget#sidebar {{
                background: {sidebar}; border-right: 1px solid {border};
            }}
            QSplitter::handle {{ background: {border}; width: 5px; }}
            QSplitter::handle:hover {{ background: {accent}; }}
            QLabel#brandName {{ color: {text}; font-size: 20px; font-weight: 700; }}
            QLabel#sectionLabel {{
                color: {muted}; font-size: 10px; font-weight: 700;
                letter-spacing: 1px; padding: 8px 4px 2px;
            }}
            QListWidget {{
                background: transparent; border: 0; outline: 0;
                color: {text}; font-size: 13px; padding: 0;
            }}
            QListWidget::item {{
                border-radius: 7px; padding: 9px 10px; margin: 1px 0;
            }}
            QListWidget::item:hover {{ background: {hover}; }}
            QListWidget::item:selected {{
                background: {selected}; color: {selected_text};
            }}
            QToolButton#sidebarAddButton {{
                color: {muted}; background: transparent; border: 0;
                border-radius: 6px; font-size: 18px;
                min-width: 26px; min-height: 26px;
            }}
            QToolButton#sidebarAddButton:hover {{ background: {hover}; }}
            QToolButton#chromeButton, QPushButton#chromeButton {{
                color: {text}; background: {surface}; border: 1px solid {border};
                border-radius: 9px; min-width: 34px; min-height: 34px;
                font-size: 13px; padding: 0 10px;
            }}
            QToolButton#chromeButton:hover, QPushButton#chromeButton:hover {{
                background: {hover};
            }}
            QLineEdit#addressBar {{
                background: {surface}; border: 1px solid {border};
                border-radius: 11px; padding: 9px 14px; color: {text};
                font-size: 13px; selection-background-color: {selected};
            }}
            QLineEdit#addressBar:focus {{ border: 1px solid {accent}; }}
            QPushButton#distillButton {{
                color: white; background: {accent}; border: 0;
                border-radius: 10px; padding: 0 15px; min-height: 36px;
                font-size: 13px; font-weight: 600;
            }}
            QPushButton#distillButton:hover {{ background: {accent}; }}
            QPushButton#distillButton:disabled {{ background: {muted}; }}
            QWebEngineView {{ background: {surface}; }}
        """


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Prism")
    app.setOrganizationName("Prism")
    app.setWindowIcon(load_prism_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
