import logging
from typing import Any

import gi

gi.require_version("GObject", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GObject, Gtk, Pango

from app.core.bridge_manager import BRIDGE_UUID
from app.core.dbus_client import DBusClient, ExtensionState

_log = logging.getLogger(__name__)

_ALL_DOT_CSS = ("success", "error", "dim-label", "warning")


class _ExtRow(Gtk.ListBoxRow):
    def __init__(self, uuid: str, info: dict[str, Any]) -> None:
        super().__init__()
        self.uuid = uuid

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(7)
        box.set_margin_bottom(7)

        self._dot = Gtk.Label(label="●")
        self._dot.set_valign(Gtk.Align.CENTER)
        box.append(self._dot)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)

        self._name_label = Gtk.Label()
        self._name_label.set_halign(Gtk.Align.START)
        self._name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._name_label.set_hexpand(True)
        text_box.append(self._name_label)

        self._uuid_label = Gtk.Label()
        self._uuid_label.set_halign(Gtk.Align.START)
        self._uuid_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._uuid_label.set_hexpand(True)
        self._uuid_label.add_css_class("caption")
        self._uuid_label.add_css_class("dim-label")
        text_box.append(self._uuid_label)

        box.append(text_box)
        self.set_child(box)
        self.update(info)

    def update(self, info: dict[str, Any]) -> None:
        name = info.get("name") or self.uuid
        state = info.get("state", ExtensionState.DISABLED)
        self._name_label.set_label(name)
        self._uuid_label.set_label(self.uuid)
        for css in _ALL_DOT_CSS:
            self._dot.remove_css_class(css)
        if state == ExtensionState.ENABLED:
            self._dot.add_css_class("success")
        elif state == ExtensionState.ERROR:
            self._dot.add_css_class("error")
        elif state in (ExtensionState.OUT_OF_DATE,):
            self._dot.add_css_class("warning")
        else:
            self._dot.add_css_class("dim-label")


class ExtensionListView(Gtk.Box):
    """Sidebar extension list grouped into User / System / Disabled sections."""

    __gtype_name__ = "ExtensionListView"

    __gsignals__ = {
        "extension-activated": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, dbus_client: DBusClient) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._dbus = dbus_client
        self._active_uuid: str | None = None
        self._rows: dict[str, _ExtRow] = {}
        self._search_text = ""
        self._in_restore = False  # suppress extension-activated during selection restore

        self._build_ui()
        dbus_client.connect("extensions-changed", self._on_extensions_changed)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Filter extensions…")
        self._search.set_margin_start(8)
        self._search.set_margin_end(8)
        self._search.set_margin_top(8)
        self._search.set_margin_bottom(4)
        self._search.connect("search-changed", self._on_search_changed)
        self.append(self._search)

        self._sections_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self._sections_box)
        self.append(scroll)

        self._user_section, self._user_lb = self._make_section("User Extensions")
        self._system_section, self._system_lb = self._make_section("System Extensions")
        self._disabled_section, self._disabled_lb = self._make_section("Disabled Extensions")

        for section in (self._user_section, self._system_section, self._disabled_section):
            self._sections_box.append(section)

        self._listboxes = [self._user_lb, self._system_lb, self._disabled_lb]

    def _make_section(self, title: str) -> tuple[Gtk.Box, Gtk.ListBox]:
        header = Gtk.Label(label=title)
        header.set_halign(Gtk.Align.START)
        header.set_margin_start(12)
        header.set_margin_top(10)
        header.set_margin_bottom(4)
        header.add_css_class("heading")
        header.add_css_class("dim-label")

        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
        lb.add_css_class("boxed-list")
        lb.set_margin_start(8)
        lb.set_margin_end(8)
        lb.set_margin_bottom(4)
        lb.connect("row-selected", self._on_row_selected)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_visible(False)
        box.append(header)
        box.append(lb)
        return box, lb

    # ── Public API ─────────────────────────────────────────────────────────

    def set_active_uuid(self, uuid: str | None) -> None:
        """Highlight the given extension without emitting extension-activated."""
        self._active_uuid = uuid
        self._restore_selection()

    # ── Signal handlers ────────────────────────────────────────────────────

    def _on_row_selected(self, lb: Gtk.ListBox, row: _ExtRow | None) -> None:
        if row is None or self._in_restore:
            return
        for other in self._listboxes:
            if other is not lb:
                other.unselect_all()
        self._active_uuid = row.uuid
        self.emit("extension-activated", row.uuid)

    def _on_extensions_changed(self, _dbus: DBusClient, extensions: dict[str, Any]) -> None:
        self._rebuild(extensions)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_text = entry.get_text().lower()
        self._apply_filter()

    # ── Internal helpers ───────────────────────────────────────────────────

    def _rebuild(self, extensions: dict[str, Any]) -> None:
        for lb in self._listboxes:
            child = lb.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                lb.remove(child)
                child = nxt
        self._rows.clear()

        user_items: list[tuple[str, dict]] = []
        system_items: list[tuple[str, dict]] = []
        disabled_items: list[tuple[str, dict]] = []

        for uuid, info in sorted(
            extensions.items(),
            key=lambda kv: (kv[1].get("name") or kv[0]).lower(),
        ):
            if uuid == BRIDGE_UUID:
                continue
            state = info.get("state", ExtensionState.DISABLED)
            ext_type = info.get("type", 2)  # 1=system, 2=user
            if state == ExtensionState.ENABLED:
                if ext_type == 1:
                    system_items.append((uuid, info))
                else:
                    user_items.append((uuid, info))
            else:
                disabled_items.append((uuid, info))

        for uuid, info in user_items:
            row = _ExtRow(uuid, info)
            self._user_lb.append(row)
            self._rows[uuid] = row

        for uuid, info in system_items:
            row = _ExtRow(uuid, info)
            self._system_lb.append(row)
            self._rows[uuid] = row

        for uuid, info in disabled_items:
            row = _ExtRow(uuid, info)
            self._disabled_lb.append(row)
            self._rows[uuid] = row

        self._user_section.set_visible(bool(user_items))
        self._system_section.set_visible(bool(system_items))
        self._disabled_section.set_visible(bool(disabled_items))

        self._apply_filter()
        self._restore_selection()

    def _apply_filter(self) -> None:
        text = self._search_text
        for uuid, row in self._rows.items():
            if text:
                name = (row._name_label.get_label() or "").lower()
                row.set_visible(text in name or text in uuid.lower())
            else:
                row.set_visible(True)

        for section, lb in (
            (self._user_section, self._user_lb),
            (self._system_section, self._system_lb),
            (self._disabled_section, self._disabled_lb),
        ):
            if not section.get_visible():
                continue
            child = lb.get_first_child()
            has_visible = False
            while child:
                if isinstance(child, _ExtRow) and child.get_visible():
                    has_visible = True
                    break
                child = child.get_next_sibling()
            section.set_visible(has_visible)

    def _restore_selection(self) -> None:
        self._in_restore = True
        try:
            if not self._active_uuid or self._active_uuid not in self._rows:
                for lb in self._listboxes:
                    lb.unselect_all()
                return
            target = self._rows[self._active_uuid]
            for lb in self._listboxes:
                if target.get_parent() is lb:
                    lb.select_row(target)
                else:
                    lb.unselect_all()
        finally:
            self._in_restore = False
