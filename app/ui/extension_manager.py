import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class ExtensionManagerView(Gtk.Box):
    """Extension list — Phase 1."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("application-x-addon-symbolic")
        placeholder.set_title("Extension Manager")
        placeholder.set_description("List, enable/disable, and clone GNOME Shell extensions.\nImplemented in Phase 1.")
        placeholder.set_vexpand(True)

        self.append(placeholder)
