import logging

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk

from app.core.dbus_client import DBusClient, ExtensionState

_log = logging.getLogger(__name__)

# (label text, CSS class or None)
_STATE_LABELS: dict[int, tuple[str, str | None]] = {
    ExtensionState.ENABLED: ("Enabled", "success"),
    ExtensionState.DISABLED: ("Disabled", "dim-label"),
    ExtensionState.ERROR: ("Error", "error"),
    ExtensionState.OUT_OF_DATE: ("Out of date", "warning"),
    ExtensionState.DOWNLOADING: ("Downloading", None),
    ExtensionState.INITIALIZED: ("Initialized", "dim-label"),
    ExtensionState.DISABLING: ("Disabling", "dim-label"),
    ExtensionState.ENABLING: ("Enabling", None),
    ExtensionState.UNINSTALLED: ("Uninstalled", "dim-label"),
}

_TRANSIENT_STATES = {
    ExtensionState.DOWNLOADING,
    ExtensionState.ENABLING,
    ExtensionState.DISABLING,
}

_ALL_STATE_CSS = {css for _, css in _STATE_LABELS.values() if css}


class ExtensionManagerView(Gtk.Box):
    """Extension list with enable/disable toggles and folder access."""

    def __init__(self, dbus_client: DBusClient) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._dbus = dbus_client
        self._rows: dict[str, Adw.ActionRow] = {}
        self._row_extras: dict[str, tuple[Gtk.Label, Gtk.Switch]] = {}
        self._pending_disables: set[str] = set()
        self._build_ui()
        dbus_client.connect("extensions-changed", self._on_extensions_changed)
        dbus_client.connect("operation-error", self._on_operation_error)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.add_css_class("flat")
        refresh_btn.set_tooltip_text("Refresh extension list")
        refresh_btn.connect("clicked", lambda _: self._dbus.list_extensions())

        self._group = Adw.PreferencesGroup()
        self._group.set_title("Installed Extensions")
        self._group.set_header_suffix(refresh_btn)

        self._empty_row = Adw.ActionRow()
        self._empty_row.set_title("No extensions found")
        self._empty_row.set_subtitle(
            "Extensions appear here when GNOME Shell is running"
        )
        self._group.add(self._empty_row)

        page = Adw.PreferencesPage()
        page.set_vexpand(True)
        page.add(self._group)

        self.append(page)

    # ── Signal handlers ───────────────────────────────────────────────────

    def _on_extensions_changed(self, _dbus: DBusClient, extensions: dict) -> None:
        current_uuids = set(self._rows)
        new_uuids = set(extensions)

        if current_uuids != new_uuids:
            # Set of extensions changed — full rebuild to keep sorted order.
            for row in self._rows.values():
                self._group.remove(row)
            self._rows.clear()
            self._row_extras.clear()
            self._pending_disables.clear()

            if not extensions:
                self._empty_row.set_visible(True)
                return

            self._empty_row.set_visible(False)
            for uuid, info in sorted(extensions.items(), key=lambda kv: kv[1]["name"].lower()):
                self._add_row(uuid, info)
        else:
            # Same extensions — update state badges and switches in-place.
            if not extensions:
                self._empty_row.set_visible(True)
                return
            self._empty_row.set_visible(False)
            for uuid, info in extensions.items():
                self._refresh_row(uuid, info)

    def _on_operation_error(self, _dbus: DBusClient, uuid: str, message: str) -> None:
        _log.warning("Extension operation failed [%s]: %s", uuid, message)

    # ── Row construction ──────────────────────────────────────────────────

    def _add_row(self, uuid: str, info: dict) -> None:
        row = Adw.ActionRow()
        row.set_title(info["name"])
        row.set_subtitle(uuid)

        badge = _make_state_badge(info["state"], info.get("error", ""))
        row.add_suffix(badge)

        if info.get("path"):
            open_btn = Gtk.Button(icon_name="folder-open-symbolic")
            open_btn.add_css_class("flat")
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.set_tooltip_text("Open extension folder")
            path = info["path"]
            open_btn.connect("clicked", lambda _, p=path: _open_folder(p))
            row.add_suffix(open_btn)

        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.set_active(info["state"] == ExtensionState.ENABLED)
        switch.set_sensitive(info["state"] not in _TRANSIENT_STATES)
        switch.connect("notify::active", self._on_switch_toggled, uuid)
        row.add_suffix(switch)
        row.set_activatable_widget(switch)

        self._group.add(row)
        self._rows[uuid] = row
        self._row_extras[uuid] = (badge, switch)

    def _refresh_row(self, uuid: str, info: dict) -> None:
        """Update badge and switch on an existing row without recreating widgets."""
        badge, switch = self._row_extras[uuid]
        state = info["state"]
        text, css = _STATE_LABELS.get(state, ("Unknown", "dim-label"))

        badge.set_text(text)
        for cls in _ALL_STATE_CSS:
            badge.remove_css_class(cls)
        if css:
            badge.add_css_class(css)
        badge.set_tooltip_text(info.get("error", "") if state == ExtensionState.ERROR else "")

        # GNOME 48 fires a spurious state=1 (ENABLED) immediately after
        # DisableExtension. Clear the pending-disable flag when DISABLING (7)
        # arrives — that's when the spurious window ends.
        if state == ExtensionState.DISABLING:
            self._pending_disables.discard(uuid)
        elif state == ExtensionState.DISABLED:
            self._pending_disables.discard(uuid)

        prev_active = switch.get_active()
        new_active = state == ExtensionState.ENABLED
        if new_active and uuid in self._pending_disables:
            new_active = False
        new_sensitive = state not in _TRANSIENT_STATES
        _log.debug(
            "_refresh_row: uuid=%s state=%s switch active %s→%s sensitive=%s",
            uuid, state, prev_active, new_active, new_sensitive,
        )
        switch.handler_block_by_func(self._on_switch_toggled)
        switch.set_active(new_active)
        switch.set_sensitive(new_sensitive)
        switch.handler_unblock_by_func(self._on_switch_toggled)

    def _on_switch_toggled(self, switch: Gtk.Switch, _pspec: object, uuid: str) -> None:
        active = switch.get_active()
        _log.debug("_on_switch_toggled: uuid=%s active=%s", uuid, active)
        if active:
            self._pending_disables.discard(uuid)
            self._dbus.enable_extension(uuid)
        else:
            self._pending_disables.add(uuid)
            self._dbus.disable_extension(uuid)


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_state_badge(state: int, error: str) -> Gtk.Label:
    text, css = _STATE_LABELS.get(state, ("Unknown", "dim-label"))
    label = Gtk.Label(label=text)
    label.set_valign(Gtk.Align.CENTER)
    if css:
        label.add_css_class(css)
    if state == ExtensionState.ERROR and error:
        label.set_tooltip_text(error)
    return label


def _open_folder(path: str) -> None:
    uri = Gio.File.new_for_path(path).get_uri()
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error as exc:
        _log.warning("Failed to open folder %s: %s", path, exc)
