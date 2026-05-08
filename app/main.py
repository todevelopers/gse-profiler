import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk

from app.core.bridge_manager import BridgeManager
from app.core.dbus_client import DBusClient
from app.core.socket_server import SocketServer
from app.ui.extension_manager import ExtensionManagerView
from app.ui.inspector_view import InspectorView
from app.ui.log_viewer import LogViewerView
from app.ui.profiler_view import ProfilerView

APP_ID = "org.gnome.GSEProfiler"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("extensions", "Extensions", "application-x-addon-symbolic"),
    ("logs", "Log Viewer", "folder-open-symbolic"),
    ("profiler", "Profiler", "power-profile-performance-symbolic"),
    ("inspector", "Inspector", "edit-find-symbolic"),
]


class _ConnectionChip(Gtk.Label):
    """Header bar chip showing live socket connection state."""

    def __init__(self) -> None:
        super().__init__()
        self.set_connected(False)

    def set_connected(self, connected: bool) -> None:
        if connected:
            self.set_text("● Connected")
            self.remove_css_class("dim-label")
            self.add_css_class("success")
        else:
            self.set_text("● Disconnected")
            self.remove_css_class("success")
            self.add_css_class("dim-label")


class MainWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        dbus_client: DBusClient,
        socket_server: SocketServer,
        bridge: BridgeManager,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._dbus = dbus_client
        self._socket = socket_server
        self._bridge = bridge
        self.set_title("GSE Profiler")
        self.set_default_size(1100, 720)
        self._register_actions()
        self._build_ui()
        socket_server.connect("client-connected", self._on_client_connected)
        socket_server.connect("client-disconnected", self._on_client_disconnected)

    def _register_actions(self) -> None:
        install_action = Gio.SimpleAction.new("install-bridge", None)
        install_action.connect("activate", self._on_install_bridge)
        self.add_action(install_action)

        reinstall_action = Gio.SimpleAction.new("reinstall-bridge", None)
        reinstall_action.connect("activate", self._on_reinstall_bridge)
        self.add_action(reinstall_action)

        uninstall_action = Gio.SimpleAction.new("uninstall-bridge", None)
        uninstall_action.connect("activate", self._on_uninstall_bridge)
        self.add_action(uninstall_action)

    def _build_ui(self) -> None:
        views: dict[str, Gtk.Widget] = {
            "extensions": ExtensionManagerView(self._dbus),
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

        # App menu
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Install Bridge", "win.install-bridge")
        section.append("Reinstall Bridge", "win.reinstall-bridge")
        section.append("Uninstall Bridge", "win.uninstall-bridge")
        menu.append_section("Bridge Extension", section)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Application menu")
        menu_btn.set_menu_model(menu)

        # Connection status chip
        self._conn_chip = _ConnectionChip()

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Gtk.Label(label="GSE Profiler"))
        sidebar_header.pack_end(menu_btn)
        sidebar_header.pack_end(self._conn_chip)

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

    def _on_client_connected(self, _server: SocketServer) -> None:
        self._conn_chip.set_connected(True)

    def _on_client_disconnected(self, _server: SocketServer) -> None:
        self._conn_chip.set_connected(False)

    def _on_install_bridge(self, _action: Gio.SimpleAction, _param: object) -> None:
        self._bridge.ensure_installed(parent_window=self)

    def _on_reinstall_bridge(self, _action: Gio.SimpleAction, _param: object) -> None:
        self._bridge.reinstall(parent_window=self)

    def _on_uninstall_bridge(self, _action: Gio.SimpleAction, _param: object) -> None:
        self._bridge.uninstall(parent_window=self)


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)
        self._dbus_client = DBusClient()
        self._socket_server = SocketServer()
        self._bridge = BridgeManager(_PROJECT_ROOT, self._dbus_client)
        self._win: MainWindow | None = None
        self._bootstrap_handler: int = 0

    def _on_activate(self, _app: "Application") -> None:
        self._socket_server.start()
        self._win = MainWindow(
            application=self,
            dbus_client=self._dbus_client,
            socket_server=self._socket_server,
            bridge=self._bridge,
        )
        self._win.present()
        # Bootstrap after proxy is ready — first extensions-changed fires once the
        # D-Bus proxy has connected and fetched the extension list.
        self._bootstrap_handler = self._dbus_client.connect(
            "extensions-changed", self._on_ready_for_bootstrap
        )

    def do_shutdown(self) -> None:
        self._bridge.deactivate()
        self._socket_server.stop()
        Adw.Application.do_shutdown(self)

    def _on_ready_for_bootstrap(self, _dbus: DBusClient, _extensions: dict) -> None:
        self._dbus_client.disconnect(self._bootstrap_handler)
        self._bootstrap_handler = 0
        self._bridge.ensure_installed(parent_window=self._win)


def main() -> None:
    app = Application()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
