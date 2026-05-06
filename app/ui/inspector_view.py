import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class InspectorView(Gtk.Box):
    """Live extension stateObj inspector — Phase 5."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("edit-find-symbolic")
        placeholder.set_title("Inspector")
        placeholder.set_description("Browse live properties and methods of a running extension's state object.\nImplemented in Phase 5.")
        placeholder.set_vexpand(True)

        self.append(placeholder)
