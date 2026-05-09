import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, GObject

_log = logging.getLogger(__name__)

_BUS_NAME = "org.gnome.Shell"
_OBJ_PATH = "/org/gnome/Shell"
_INTERFACE = "org.gnome.Shell.Extensions"


class ExtensionState:
    ENABLED = 1
    DISABLED = 2
    ERROR = 3
    OUT_OF_DATE = 4
    DOWNLOADING = 5
    INITIALIZED = 6
    DISABLING = 7
    ENABLING = 8
    UNINSTALLED = 99


class DBusClient(GObject.Object):
    """Async D-Bus proxy for org.gnome.Shell.Extensions."""

    __gtype_name__ = "DBusClient"

    @GObject.Signal(arg_types=(object,))
    def extensions_changed(self, extensions: dict) -> None:
        """Emitted when the extension list is refreshed."""

    @GObject.Signal(arg_types=(str, str))
    def operation_error(self, uuid: str, message: str) -> None:
        """Emitted when an enable/disable call fails."""

    def __init__(self) -> None:
        super().__init__()
        self._proxy: Gio.DBusProxy | None = None
        self._extensions: dict[str, dict[str, Any]] = {}
        self._init_proxy()

    # ── Initialisation ────────────────────────────────────────────────────

    def _init_proxy(self) -> None:
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            _BUS_NAME,
            _OBJ_PATH,
            _INTERFACE,
            None,
            self._on_proxy_ready,
            None,
        )

    def _on_proxy_ready(
        self,
        _source: object,
        result: Gio.AsyncResult,
        _user_data: object,
    ) -> None:
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as exc:
            _log.error("D-Bus proxy init failed: %s", exc)
            return
        self._proxy.connect("g-signal", self._on_dbus_signal)
        self.list_extensions()

    # ── D-Bus signal handler ──────────────────────────────────────────────

    def _on_dbus_signal(
        self,
        _proxy: Gio.DBusProxy,
        _sender: str,
        signal_name: str,
        parameters: GLib.Variant,
    ) -> None:
        if signal_name != "ExtensionStateChanged":
            return
        # Signature is (sa{sv}) — uuid + full state-info dict, not (s, u).
        # Wrap in try/finally so extensions-changed always fires even if
        # parsing fails — otherwise the UI stays frozen in whatever state it was.
        try:
            uuid, info = parameters.unpack()
            new_state = int(info.get("state", ExtensionState.UNINSTALLED))
            if new_state == ExtensionState.UNINSTALLED:
                self._extensions.pop(uuid, None)
            else:
                self._extensions[uuid] = _parse_info(uuid, info)
        except Exception as exc:
            _log.error("ExtensionStateChanged parse error: %s", exc)
        finally:
            self.emit("extensions-changed", dict(self._extensions))

    # ── Public API ────────────────────────────────────────────────────────

    def list_extensions(self) -> None:
        """Async-refresh the list; emits extensions-changed when done."""
        if self._proxy is None:
            return
        self._proxy.call(
            "ListExtensions",
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_list_done,
            None,
        )

    def enable_extension(
        self, uuid: str, on_done: Callable[[GLib.Error | None], None] | None = None
    ) -> None:
        """Async-enable extension.

        If `on_done` is provided, it is invoked when the call completes, with
        the GLib.Error on failure or None on success.
        """
        self._call_toggle("EnableExtension", uuid, on_done)

    def disable_extension(
        self, uuid: str, on_done: Callable[[GLib.Error | None], None] | None = None
    ) -> None:
        """Async-disable extension.

        If `on_done` is provided, it is invoked when the call completes, with
        the GLib.Error on failure or None on success.
        """
        self._call_toggle("DisableExtension", uuid, on_done)

    def is_extension_known(self, uuid: str) -> bool:
        """Return True if gnome-shell has this extension in its registry."""
        return uuid in self._extensions

    def get_extension_state(self, uuid: str) -> int | None:
        """Return cached extension state, or None if unknown."""
        info = self._extensions.get(uuid)
        return int(info["state"]) if info else None

    # ── Private helpers ───────────────────────────────────────────────────

    def _call_toggle(
        self,
        method: str,
        uuid: str,
        on_done: Callable[[GLib.Error | None], None] | None = None,
    ) -> None:
        if self._proxy is None:
            if on_done:
                on_done(GLib.Error("D-Bus proxy not ready"))
            return
        self._proxy.call(
            method,
            GLib.Variant("(s)", (uuid,)),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_toggle_done,
            (uuid, on_done),
        )

    def _on_toggle_done(
        self,
        proxy: Gio.DBusProxy,
        result: Gio.AsyncResult,
        user_data: tuple[str, Callable[[GLib.Error | None], None] | None],
    ) -> None:
        uuid, on_done = user_data
        error: GLib.Error | None = None
        try:
            proxy.call_finish(result)
        except GLib.Error as exc:
            error = exc
            _log.error("Toggle %s failed: %s", uuid, exc)
            self.emit("operation-error", uuid, str(exc))
        if on_done is not None:
            on_done(error)
        # Only force-refresh the list on error. On success, the ExtensionStateChanged
        # D-Bus signal drives state updates via _on_dbus_signal. Calling list_extensions
        # unconditionally races with that signal: if the ListExtensions reply arrives
        # before ExtensionStateChanged, it overwrites the correct state with stale data,
        # leaving the switch permanently showing the wrong state.
        if error is not None:
            GLib.idle_add(self.list_extensions)

    def _on_list_done(
        self,
        proxy: Gio.DBusProxy,
        result: Gio.AsyncResult,
        _user_data: object,
    ) -> None:
        try:
            value = proxy.call_finish(result)
        except GLib.Error as exc:
            _log.error("ListExtensions failed: %s", exc)
            return
        raw: dict = value.unpack()[0]
        self._extensions = {uuid: _parse_info(uuid, info) for uuid, info in raw.items()}
        self.emit("extensions-changed", dict(self._extensions))


def _parse_info(uuid: str, info: dict) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "name": str(info.get("name", uuid)),
        "description": str(info.get("description", "")),
        "version": int(info.get("version", 0)),
        "state": int(info.get("state", ExtensionState.DISABLED)),
        "path": str(info.get("path", "")),
        "error": str(info.get("error", "")),
        "url": str(info.get("url", "")),
    }
