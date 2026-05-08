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

BRIDGE_UUID = "gse-profiler-bridge@todevelopers"
_INSTALL_PATH = Path(GLib.get_user_data_dir()) / "gnome-shell" / "extensions" / BRIDGE_UUID


class BridgeManager:
    """Manages installation and lifecycle of the bridge GNOME Shell extension."""

    def __init__(self, project_root: Path, dbus_client: DBusClient) -> None:
        self._root = project_root
        self._source = project_root / "bridge-extension"
        self._dbus = dbus_client

    def ensure_installed(self, parent_window: Gtk.Window | None = None) -> None:
        """Prompt to install if missing; enable if already installed and known."""
        if not _INSTALL_PATH.exists():
            self._prompt_install(parent_window)
        elif not self._dbus.is_extension_known(BRIDGE_UUID):
            # Files exist but gnome-shell hasn't loaded them yet (e.g. shell restart
            # was cancelled after a previous install).
            self._prompt_restart(parent_window)
        else:
            self._dbus.enable_extension(BRIDGE_UUID)

    def deactivate(self) -> None:
        """Disable the bridge extension without removing it."""
        self._dbus.disable_extension(BRIDGE_UUID)

    def reinstall(self, parent_window: Gtk.Window | None = None) -> None:
        """Force-reinstall the bridge extension."""
        self._do_install(parent_window)

    def uninstall(self, parent_window: Gtk.Window | None = None) -> None:
        """Disable and remove the bridge extension, then prompt for shell restart."""
        if not _INSTALL_PATH.exists():
            _show_error(parent_window, "Bridge extension is not installed.")
            return
        self._dbus.disable_extension(BRIDGE_UUID)
        try:
            shutil.rmtree(_INSTALL_PATH)
            _log.info("Bridge extension removed from %s", _INSTALL_PATH)
        except OSError as exc:
            _log.error("Bridge uninstall failed: %s", exc)
            _show_error(parent_window, str(exc))
            return
        self._prompt_restart(parent_window, uninstall=True)

    # ── Private ───────────────────────────────────────────────────────────

    def _prompt_install(self, parent_window: Gtk.Window | None) -> None:
        dialog = Adw.AlertDialog.new(
            "Bridge Extension Required",
            "GSE Profiler uses a bridge GNOME Shell extension to enable profiling "
            "and inspection features.\n\n"
            "The extension will be installed and GNOME Shell will need to restart. "
            "Install now?",
        )
        dialog.add_response("cancel", "Not Now")
        dialog.add_response("install", "Install")
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("install")
        dialog.connect("response", self._on_install_response, parent_window)
        if parent_window:
            dialog.present(parent_window)

    def _on_install_response(
        self, _dialog: Adw.AlertDialog, response: str, parent_window: Gtk.Window | None
    ) -> None:
        if response == "install":
            self._do_install(parent_window)

    def _do_install(self, parent_window: Gtk.Window | None) -> None:
        try:
            if _INSTALL_PATH.exists():
                shutil.rmtree(_INSTALL_PATH)
            _INSTALL_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self._source, _INSTALL_PATH)
            _log.info("Bridge installed to %s", _INSTALL_PATH)
        except OSError as exc:
            _log.error("Bridge install failed: %s", exc)
            _show_error(parent_window, str(exc))
            return
        self._prompt_restart(parent_window)

    def _prompt_restart(self, parent_window: Gtk.Window | None, *, uninstall: bool = False) -> None:
        wayland = (
            bool(GLib.getenv("WAYLAND_DISPLAY"))
            or GLib.getenv("XDG_SESSION_TYPE") == "wayland"
        )
        action = "removed" if uninstall else "installed"

        if wayland:
            body = (
                f"The bridge extension was {action}.\n\n"
                "On Wayland, GNOME Shell requires a full logout to reload extensions.\n"
                "Log out now?"
            )
            restart_label = "Log Out"
            response_key = "restart"
        elif uninstall:
            # X11 uninstall: ask before restarting — auto-restart would freeze the
            # screen without warning.
            body = (
                "The bridge extension was removed.\n\n"
                "GNOME Shell must restart to fully unload it.\n"
                "Restart now?"
            )
            restart_label = "Restart Shell"
            response_key = "restart"
        else:
            # X11 install: restart immediately, no dialog needed.
            self._restart_shell()
            return

        dialog = Adw.AlertDialog.new("Shell Restart Required", body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response(response_key, restart_label)
        dialog.set_response_appearance(response_key, Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_restart_response, response_key)
        if parent_window:
            dialog.present(parent_window)

    def _on_restart_response(self, _dialog: Adw.AlertDialog, response: str, restart_key: str) -> None:
        if response == restart_key:
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
