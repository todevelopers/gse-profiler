import logging
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, GObject, Gtk

from app.core.dbus_client import DBusClient, ExtensionState

_log = logging.getLogger(__name__)

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
_ALL_STATE_CSS = {css for _, css in _STATE_LABELS.values() if css}

_TRANSIENT_STATES = {ExtensionState.DOWNLOADING, ExtensionState.ENABLING, ExtensionState.DISABLING}


class DetailsView(Gtk.Stack):
    """Extension details panel: metadata, enable/disable, open folder/prefs."""

    __gtype_name__ = "DetailsView"

    __gsignals__ = {
        "favorite-toggled": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, dbus_client: DBusClient) -> None:
        super().__init__()
        self._dbus = dbus_client
        self._active_uuid: str | None = None
        self._all_extensions: dict[str, Any] = {}
        self._pending_disable = False
        self._switch_handler: int = 0

        self._build_ui()
        dbus_client.connect("extensions-changed", self._on_extensions_changed)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("application-x-addon-symbolic")
        placeholder.set_title("No Extension Selected")
        placeholder.set_description("Select an extension from the list on the left.")
        placeholder.set_vexpand(True)
        self.add_named(placeholder, "placeholder")

        page = Adw.PreferencesPage()
        page.set_vexpand(True)

        # ── Header row ──────────────────────────────────────────────────────
        header_group = Adw.PreferencesGroup()
        self._header_row = Adw.ActionRow()
        self._header_row.set_icon_name("application-x-addon-symbolic")
        self._state_badge = Gtk.Label()
        self._state_badge.set_valign(Gtk.Align.CENTER)
        self._header_row.add_suffix(self._state_badge)

        self._star_btn = Gtk.ToggleButton()
        self._star_btn.set_icon_name("non-starred-symbolic")
        self._star_btn.add_css_class("flat")
        self._star_btn.set_valign(Gtk.Align.CENTER)
        self._star_btn.set_tooltip_text("Add to favorites")
        self._star_handler = self._star_btn.connect("toggled", self._on_star_toggled)
        self._header_row.add_suffix(self._star_btn)

        header_group.add(self._header_row)
        page.add(header_group)

        # ── Details group ───────────────────────────────────────────────────
        details_group = Adw.PreferencesGroup()
        details_group.set_title("Details")

        self._uuid_row = Adw.ActionRow()
        self._uuid_row.set_title("UUID")
        details_group.add(self._uuid_row)

        self._desc_row = Adw.ActionRow()
        self._desc_row.set_title("Description")
        details_group.add(self._desc_row)

        self._url_row = Adw.ActionRow()
        self._url_row.set_title("Homepage")
        self._url_link = Gtk.LinkButton()
        self._url_link.set_valign(Gtk.Align.CENTER)
        self._url_row.add_suffix(self._url_link)
        details_group.add(self._url_row)

        page.add(details_group)

        # ── Actions group ───────────────────────────────────────────────────
        actions_group = Adw.PreferencesGroup()
        actions_group.set_title("Actions")

        enable_row = Adw.ActionRow()
        enable_row.set_title("Enabled")
        enable_row.set_subtitle("Enable or disable this extension")
        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch_handler = self._switch.connect("notify::active", self._on_switch_toggled)
        enable_row.add_suffix(self._switch)
        enable_row.set_activatable_widget(self._switch)
        actions_group.add(enable_row)

        self._folder_row = Adw.ActionRow()
        self._folder_row.set_title("Open Folder")
        self._folder_row.set_subtitle("Open extension directory in file manager")
        folder_btn = Gtk.Button(icon_name="folder-open-symbolic")
        folder_btn.add_css_class("flat")
        folder_btn.set_valign(Gtk.Align.CENTER)
        folder_btn.set_tooltip_text("Open extension folder")
        folder_btn.connect("clicked", self._on_open_folder)
        self._folder_row.add_suffix(folder_btn)
        actions_group.add(self._folder_row)

        self._prefs_row = Adw.ActionRow()
        self._prefs_row.set_title("Preferences")
        self._prefs_row.set_subtitle("Open extension settings dialog")
        prefs_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        prefs_btn.add_css_class("flat")
        prefs_btn.set_valign(Gtk.Align.CENTER)
        prefs_btn.set_tooltip_text("Open extension preferences")
        prefs_btn.connect("clicked", self._on_open_prefs)
        self._prefs_row.add_suffix(prefs_btn)
        actions_group.add(self._prefs_row)

        page.add(actions_group)
        self.add_named(page, "content")
        self.set_visible_child_name("placeholder")

    # ── Public API ─────────────────────────────────────────────────────────

    def set_active_extension(self, uuid: str | None) -> None:
        self._pending_disable = False
        self._active_uuid = uuid
        if uuid is None:
            self.set_visible_child_name("placeholder")
            return
        info = self._all_extensions.get(uuid, {})
        self._populate(uuid, info)
        self.set_visible_child_name("content")

    def set_favorite_state(self, is_fav: bool) -> None:
        self._star_btn.handler_block_by_func(self._on_star_toggled)
        self._star_btn.set_active(is_fav)
        self._star_btn.set_icon_name("starred-symbolic" if is_fav else "non-starred-symbolic")
        self._star_btn.set_tooltip_text("Remove from favorites" if is_fav else "Add to favorites")
        self._star_btn.handler_unblock_by_func(self._on_star_toggled)

    # ── Signal handlers ────────────────────────────────────────────────────

    def _on_star_toggled(self, btn: Gtk.ToggleButton) -> None:
        is_fav = btn.get_active()
        btn.set_icon_name("starred-symbolic" if is_fav else "non-starred-symbolic")
        btn.set_tooltip_text("Remove from favorites" if is_fav else "Add to favorites")
        self.emit("favorite-toggled")

    def _on_extensions_changed(self, _dbus: DBusClient, extensions: dict[str, Any]) -> None:
        self._all_extensions = extensions
        if self._active_uuid and self._active_uuid in extensions:
            self._refresh_in_place(self._active_uuid, extensions[self._active_uuid])

    def _on_switch_toggled(self, switch: Gtk.Switch, _pspec: object) -> None:
        if not self._active_uuid:
            return
        if switch.get_active():
            self._pending_disable = False
            self._dbus.enable_extension(self._active_uuid)
        else:
            self._pending_disable = True
            self._dbus.disable_extension(self._active_uuid)

    def _on_open_folder(self, _btn: Gtk.Button) -> None:
        if not self._active_uuid:
            return
        info = self._all_extensions.get(self._active_uuid, {})
        path = info.get("path", "")
        if path:
            uri = Gio.File.new_for_path(path).get_uri()
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            except GLib.Error as exc:
                _log.warning("Failed to open folder %s: %s", path, exc)

    def _on_open_prefs(self, _btn: Gtk.Button) -> None:
        if self._active_uuid:
            self._dbus.launch_extension_prefs(self._active_uuid)

    # ── Populate / refresh ─────────────────────────────────────────────────

    def _populate(self, uuid: str, info: dict[str, Any]) -> None:
        name = info.get("name") or uuid
        state = info.get("state", ExtensionState.DISABLED)
        description = info.get("description", "")
        url = info.get("url", "")
        path = info.get("path", "")
        has_prefs = info.get("hasPrefs", False)

        self._header_row.set_title(name)
        self._header_row.set_subtitle(uuid)

        self._uuid_row.set_subtitle(uuid)
        self._desc_row.set_subtitle(description or "—")
        self._desc_row.set_visible(True)

        if url:
            self._url_link.set_uri(url)
            self._url_link.set_label(url)
            self._url_row.set_visible(True)
        else:
            self._url_row.set_visible(False)

        # State badge
        text, css = _STATE_LABELS.get(state, ("Unknown", "dim-label"))
        self._state_badge.set_label(text)
        for c in _ALL_STATE_CSS:
            self._state_badge.remove_css_class(c)
        if css:
            self._state_badge.add_css_class(css)

        # Switch
        self._switch.handler_block_by_func(self._on_switch_toggled)
        self._switch.set_active(state == ExtensionState.ENABLED)
        self._switch.set_sensitive(state not in _TRANSIENT_STATES)
        self._switch.handler_unblock_by_func(self._on_switch_toggled)

        self._folder_row.set_visible(bool(path))
        self._prefs_row.set_visible(has_prefs)

    def _refresh_in_place(self, uuid: str, info: dict[str, Any]) -> None:
        state = info.get("state", ExtensionState.DISABLED)

        if state == ExtensionState.DISABLING:
            self._pending_disable = False
        elif state == ExtensionState.DISABLED:
            self._pending_disable = False

        text, css = _STATE_LABELS.get(state, ("Unknown", "dim-label"))
        self._state_badge.set_label(text)
        for c in _ALL_STATE_CSS:
            self._state_badge.remove_css_class(c)
        if css:
            self._state_badge.add_css_class(css)

        new_active = state == ExtensionState.ENABLED
        if new_active and self._pending_disable:
            new_active = False

        self._switch.handler_block_by_func(self._on_switch_toggled)
        self._switch.set_active(new_active)
        self._switch.set_sensitive(state not in _TRANSIENT_STATES)
        self._switch.handler_unblock_by_func(self._on_switch_toggled)

