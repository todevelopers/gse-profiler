import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class ProfilerView(Gtk.Box):
    """Live function timing profiler — Phase 4."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("utilities-system-monitor-symbolic")
        placeholder.set_title("Profiler")
        placeholder.set_description("Live function timing via monkey-patching. Save and load profile files.\nImplemented in Phase 4.")
        placeholder.set_vexpand(True)

        self.append(placeholder)
