import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class LogViewerView(Gtk.Box):
    """Live journalctl log viewer — Phase 3."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("text-x-log-symbolic")
        placeholder.set_title("Log Viewer")
        placeholder.set_description("Live journalctl stream filtered by extension UUID and log level.\nImplemented in Phase 3.")
        placeholder.set_vexpand(True)

        self.append(placeholder)
