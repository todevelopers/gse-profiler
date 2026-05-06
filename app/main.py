import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from app.ui.extension_manager import ExtensionManagerView  # noqa: E402
from app.ui.inspector_view import InspectorView  # noqa: E402
from app.ui.log_viewer import LogViewerView  # noqa: E402
from app.ui.profiler_view import ProfilerView  # noqa: E402

APP_ID = "org.gnome.GSEProfiler"

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("extensions", "Extensions", "application-x-addon-symbolic"),
    ("logs", "Log Viewer", "text-x-log-symbolic"),
    ("profiler", "Profiler", "utilities-system-monitor-symbolic"),
    ("inspector", "Inspector", "edit-find-symbolic"),
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title("GSE Profiler")
        self.set_default_size(1100, 720)
        self._build_ui()

    def _build_ui(self) -> None:
        views: dict[str, Gtk.Widget] = {
            "extensions": ExtensionManagerView(),
            "logs": LogViewerView(),
            "profiler": ProfilerView(),
            "inspector": InspectorView(),
        }

        # ── Content stack ──────────────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        for key, view in views.items():
            self._stack.add_named(view, key)

        self._page_title = Gtk.Label(label="Extensions")
        self._page_title.add_css_class("title")

        content_header = Adw.HeaderBar()
        content_header.set_title_widget(self._page_title)
        content_header.set_show_start_title_buttons(False)

        content_view = Adw.ToolbarView()
        content_view.add_top_bar(content_header)
        content_view.set_content(self._stack)

        # ── Sidebar navigation ─────────────────────────────────────────────
        nav_list = Gtk.ListBox()
        nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        nav_list.add_css_class("navigation-sidebar")
        nav_list.connect("row-selected", self._on_row_selected)

        for _key, title, icon in _NAV_ITEMS:
            row = Adw.ActionRow()
            row.set_title(title)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            nav_list.append(row)

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Gtk.Label(label="GSE Profiler"))

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(nav_list)

        sidebar_view = Adw.ToolbarView()
        sidebar_view.add_top_bar(sidebar_header)
        sidebar_view.set_content(scrolled)

        # ── Split view ─────────────────────────────────────────────────────
        split = Adw.OverlaySplitView()
        split.set_sidebar_position(Gtk.PackType.START)
        split.set_sidebar(sidebar_view)
        split.set_content(content_view)
        split.set_collapsed(False)

        self.set_content(split)
        self._nav_list = nav_list

        nav_list.select_row(nav_list.get_row_at_index(0))

    def _on_row_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        idx = row.get_index()
        key, title, _ = _NAV_ITEMS[idx]
        self._stack.set_visible_child_name(key)
        self._page_title.set_label(title)


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: "Application") -> None:
        win = MainWindow(application=self)
        win.present()


def main() -> None:
    app = Application()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
