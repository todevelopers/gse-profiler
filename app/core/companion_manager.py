import logging
import shutil
import subprocess
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from app.core.dbus_client import DBusClient

_log = logging.getLogger(__name__)

COMPANION_UUID = "gse-profiler-bridge@todevelopers"
_INSTALL_PATH = Path(GLib.get_user_data_dir()) / "gnome-shell" / "extensions" / COMPANION_UUID


class CompanionManager:
    """Manages installation and lifecycle of the companion GNOME Shell extension."""

    def __init__(self, project_root: Path, dbus_client: DBusClient) -> None:
        self._root = project_root
        self._source = project_root / "companion-extension"
        self._dbus = dbus_client

    def ensure_installed(self, parent_window: Gtk.Window | None = None) -> None:
        """Install companion if missing; enable it if already installed but disabled."""
        if not _INSTALL_PATH.exists():
            self._do_install(parent_window)
        else:
            self._dbus.enable_extension(COMPANION_UUID)

    def reinstall(self, parent_window: Gtk.Window | None = None) -> None:
        """Force-reinstall the companion extension."""
        self._do_install(parent_window)

    # ── Private ───────────────────────────────────────────────────────────

    def _do_install(self, parent_window: Gtk.Window | None) -> None:
        try:
            if _INSTALL_PATH.exists():
                shutil.rmtree(_INSTALL_PATH)
            _INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self._source, _INSTALL_PATH)
            _log.info("Companion installed to %s", _INSTALL_PATH)
        except OSError as exc:
            _log.error("Companion install failed: %s", exc)
            _show_error(parent_window, str(exc))
            return
        self._prompt_restart(parent_window)

    def _prompt_restart(self, parent_window: Gtk.Window | None) -> None:
        wayland = (
            bool(GLib.getenv("WAYLAND_DISPLAY"))
            or GLib.getenv("XDG_SESSION_TYPE") == "wayland"
        )
        if wayland:
            dialog = Adw.AlertDialog.new(
                "Shell Restart Required",
                "The bridge extension was installed.\n\n"
                "On Wayland, GNOME Shell requires a full logout to reload extensions.\n"
                "Log out now?",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("logout", "Log Out")
            dialog.set_response_appearance("logout", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect("response", self._on_restart_response)
            if parent_window:
                dialog.present(parent_window)
        else:
            self._restart_shell()

    def _on_restart_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response == "logout":
            self._restart_shell()

    def _restart_shell(self) -> None:
        script = self._root / "scripts" / "restart-shell.sh"
        if script.exists():
            subprocess.Popen(["bash", str(script)])  # noqa: S603
        else:
            _log.warning("restart-shell.sh not found at %s", script)


def _show_error(parent_window: Gtk.Window | None, message: str) -> None:
    dialog = Adw.AlertDialog.new("Installation Failed", message)
    dialog.add_response("ok", "OK")
    if parent_window:
        dialog.present(parent_window)
