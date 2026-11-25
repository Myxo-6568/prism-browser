import sys
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QTabWidget,
    QToolBar,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from distiller import distill_html_to_page


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Create a tab widget as the central widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.sync_active_tab)
        self.setCentralWidget(self.tabs)

        # Create a toolbar
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        # Add a back action to the toolbar
        self.back_action = QAction("Back", self)
        self.back_action.setShortcut(QKeySequence("Back"))
        toolbar.addAction(self.back_action)

        # Add a forward action to the toolbar
        self.forward_action = QAction("Forward", self)
        self.forward_action.setShortcut(QKeySequence("Forward"))
        toolbar.addAction(self.forward_action)

        # Add a reload action to the toolbar
        self.reload_action = QAction("Reload", self)
        self.reload_action.setShortcut(QKeySequence("Refresh"))
        toolbar.addAction(self.reload_action)

        # Add a search bar to the toolbar
        self.search_bar = QLineEdit()
        self.search_bar.returnPressed.connect(self.load_url)
        toolbar.addWidget(self.search_bar)

        # Add a Distill action to the toolbar
        self.distill_action = QAction("Distill", self)
        self.distill_action.triggered.connect(self.distill_tab)
        toolbar.addAction(self.distill_action)

        # Create the initial tab
        self.add_new_tab(QUrl("https://www.google.com/"), "New Tab")
        self.sync_active_tab()

    def current_web_view(self) -> QWebEngineView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, QWebEngineView) else None

    def sync_active_tab(self):
        """Point Back, Forward, Reload, and the search bar at the active tab."""
        for action in (self.back_action, self.forward_action, self.reload_action):
            try:
                action.triggered.disconnect()
            except TypeError:
                pass

        view = self.current_web_view()
        if view is not None:
            self.back_action.triggered.connect(view.back)
            self.forward_action.triggered.connect(view.forward)
            self.reload_action.triggered.connect(view.reload)
            self.search_bar.setText(view.url().toString())

    def add_new_tab(self, url: QUrl, label: str = "Tab") -> QWebEngineView:
        web_view = QWebEngineView()
        web_view.setUrl(url)

        index = self.tabs.addTab(web_view, label)
        self.tabs.setCurrentIndex(index)

        web_view.titleChanged.connect(
            lambda title, browser=web_view: self.update_tab_title(browser, title)
        )
        web_view.urlChanged.connect(
            lambda qurl, browser=web_view: self.update_search_bar(browser, qurl)
        )
        return web_view

    def distill_tab(self):
        """Extract HTML from the current tab, summarize via Gemini, and open a new tab."""
        current = self.current_web_view()
        if current is None:
            return

        page_title = current.title()
        source_url = current.url().toString()

        # Disable button briefly while distilling
        self.distill_action.setEnabled(False)
        self.distill_action.setText("Distilling...")

        def on_html_ready(raw_html: str):
            try:
                summary_html = distill_html_to_page(
                    raw_html,
                    page_title=page_title,
                    source_url=source_url,
                )
                new_view = self.add_new_tab(QUrl("about:blank"), f"Summary: {page_title[:18]}")
                new_view.setHtml(summary_html, baseUrl=QUrl(source_url))
            finally:
                self.distill_action.setEnabled(True)
                self.distill_action.setText("Distill")

        current.page().toHtml(on_html_ready)

    def update_tab_title(self, view: QWebEngineView, title: str):
        index = self.tabs.indexOf(view)
        if index != -1 and title:
            self.tabs.setTabText(index, title[:25])

    def update_search_bar(self, view: QWebEngineView, qurl: QUrl):
        if view is self.current_web_view():
            self.search_bar.setText(qurl.toString())

    def close_tab(self, index: int):
        if self.tabs.count() > 1:
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if widget is not None:
                widget.deleteLater()

    def load_url(self):
        view = self.current_web_view()
        if view is None:
            return

        url = self.search_bar.text().strip()
        if not url:
            return

        if not url.startswith(("http://", "https://")):
            if "." in url and " " not in url:
                url = "https://" + url
            else:
                url = f"https://www.google.com/search?q={url}"

        view.load(QUrl(url))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
