import logging
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from app.core.dbus_client import DBusClient
from app.core.socket_server import SocketServer

_log = logging.getLogger(__name__)

_INVALID_POS = GLib.MAXUINT

_TYPE_CSS: dict[str, str] = {
    "function": "dim-label",
    "null": "dim-label",
    "undefined": "dim-label",
    "error": "error",
    "getter": "dim-label",
    "info": "dim-label",
}


class PropertyItem(GObject.Object):
    """One row in the Inspector property table."""

    __gtype_name__ = "InspectorPropertyItem"

    def __init__(
        self,
        name: str,
        type_str: str,
        value_str: str,
        writable: bool,
        depth: int = 0,
        parent_name: str = "",
    ) -> None:
        super().__init__()
        self.name = name
        self.type_str = type_str
        self.value_str = value_str
        self.writable = writable
        self.depth = depth
        self.parent_name = parent_name
        self.has_children = False
        self.expanded = False
        self.children_data: list[dict[str, Any]] = []


class InspectorView(Gtk.Stack):
    """Live extension stateObj inspector — Phase 5."""

    def __init__(self, dbus_client: DBusClient, socket_server: SocketServer) -> None:
        super().__init__()
        self._dbus = dbus_client
        self._socket = socket_server
        self._current_uuid: str | None = None
        self._store = Gio.ListStore(item_type=PropertyItem)
        self._current_path: list[str] = []
        # handler IDs for expand/drill buttons, keyed by id(button widget)
        self._expand_handlers: dict[int, int] = {}
        self._drill_handlers: dict[int, int] = {}

        self._build_ui()

        socket_server.connect("message-received", self._on_message)
        socket_server.connect("client-connected", self._on_client_connected)
        socket_server.connect("client-disconnected", self._on_disconnected)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        no_selection = Adw.StatusPage()
        no_selection.set_icon_name("edit-find-symbolic")
        no_selection.set_title("No Extension Selected")
        no_selection.set_description("Select an enabled extension from the list to inspect its state object.")
        self.add_named(no_selection, "no-selection")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add_named(content, "content")
        self.set_visible_child_name("no-selection")

        # ── Toolbar ────────────────────────────────────────────────────────
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh properties")
        refresh_btn.connect("clicked", self._on_refresh)

        self._copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        self._copy_btn.set_tooltip_text("Copy selected value to clipboard")
        self._copy_btn.set_sensitive(False)
        self._copy_btn.connect("clicked", self._on_copy)

        self._status_lbl = Gtk.Label()
        self._status_lbl.set_hexpand(True)
        self._status_lbl.set_halign(Gtk.Align.END)
        self._status_lbl.add_css_class("dim-label")

        toolbar.append(refresh_btn)
        toolbar.append(self._copy_btn)
        toolbar.append(self._status_lbl)

        # ── Column view ─────────────────────────────────────────────────────
        self._selection = Gtk.SingleSelection.new(self._store)
        self._selection.connect("selection-changed", self._on_selection_changed)

        col_view = Gtk.ColumnView(model=self._selection)
        col_view.set_vexpand(True)
        col_view.set_show_row_separators(True)
        col_view.set_show_column_separators(True)
        col_view.connect("activate", self._on_row_activate)
        self._col_view = col_view

        # Name column
        name_fac = Gtk.SignalListItemFactory()
        name_fac.connect("setup", self._name_setup)
        name_fac.connect("bind", self._name_bind)
        name_fac.connect("unbind", self._name_unbind)
        name_col = Gtk.ColumnViewColumn(title="Property", factory=name_fac)
        name_col.set_fixed_width(260)
        name_col.set_resizable(True)
        col_view.append_column(name_col)

        # Type column
        type_fac = Gtk.SignalListItemFactory()
        type_fac.connect("setup", self._type_setup)
        type_fac.connect("bind", self._type_bind)
        type_col = Gtk.ColumnViewColumn(title="Type", factory=type_fac)
        type_col.set_fixed_width(90)
        type_col.set_resizable(True)
        col_view.append_column(type_col)

        # Value column
        value_fac = Gtk.SignalListItemFactory()
        value_fac.connect("setup", self._value_setup)
        value_fac.connect("bind", self._value_bind)
        value_col = Gtk.ColumnViewColumn(title="Value", factory=value_fac)
        value_col.set_expand(True)
        value_col.set_resizable(True)
        col_view.append_column(value_col)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(col_view)

        # ── Placeholder ─────────────────────────────────────────────────────
        self._placeholder = Adw.StatusPage()
        self._placeholder.set_icon_name("edit-find-symbolic")
        self._placeholder.set_title("No Properties")
        self._placeholder.set_description(
            "Select an extension and click Refresh to inspect its state object."
        )
        self._placeholder.set_vexpand(True)

        # ── Main stack ──────────────────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.add_named(self._placeholder, "placeholder")
        self._stack.add_named(scrolled, "table")

        # ── Breadcrumb bar ───────────────────────────────────────────────────
        self._breadcrumb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._breadcrumb_box.set_margin_start(6)
        self._breadcrumb_box.set_margin_end(6)
        self._breadcrumb_box.set_margin_top(2)
        self._breadcrumb_box.set_margin_bottom(2)

        self._breadcrumb_revealer = Gtk.Revealer()
        self._breadcrumb_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._breadcrumb_revealer.set_reveal_child(False)
        self._breadcrumb_revealer.set_child(self._breadcrumb_box)

        content.append(toolbar)
        content.append(self._breadcrumb_revealer)
        content.append(Gtk.Separator())
        content.append(self._stack)

    # ── Name column factory ────────────────────────────────────────────────

    def _name_setup(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        expand_btn = Gtk.Button()
        expand_btn.add_css_class("flat")
        expand_btn.set_can_focus(False)
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        label.add_css_class("monospace")
        drill_btn = Gtk.Button(icon_name="go-next-symbolic")
        drill_btn.add_css_class("flat")
        drill_btn.set_can_focus(False)
        drill_btn.set_tooltip_text("Inspect subtree")
        box.append(expand_btn)
        box.append(label)
        box.append(drill_btn)
        list_item.set_child(box)

    def _name_bind(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item: PropertyItem = list_item.get_item()
        box = list_item.get_child()
        expand_btn = box.get_first_child()
        label = expand_btn.get_next_sibling()
        drill_btn = label.get_next_sibling()

        box.set_margin_start(item.depth * 24)

        # Expand toggle — only for depth-0 items with children
        expand_btn.set_visible(item.has_children and item.depth == 0)
        if item.has_children and item.depth == 0:
            expand_btn.set_icon_name(
                "pan-down-symbolic" if item.expanded else "pan-end-symbolic"
            )

        label.set_label(item.name)

        # Drill button — any depth-0 object/array (bridge resolves path fresh on demand)
        drillable = item.depth == 0 and item.type_str in ("object", "array")
        drill_btn.set_visible(drillable)

        # Rebind expand handler
        btn_id = id(expand_btn)
        if btn_id in self._expand_handlers:
            expand_btn.disconnect(self._expand_handlers[btn_id])
        self._expand_handlers[btn_id] = expand_btn.connect(
            "clicked", self._on_expand_clicked, item
        )

        # Rebind drill handler
        d_id = id(drill_btn)
        if d_id in self._drill_handlers:
            drill_btn.disconnect(self._drill_handlers[d_id])
        if drillable:
            self._drill_handlers[d_id] = drill_btn.connect(
                "clicked", self._on_drill_in, item
            )

    def _name_unbind(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        box = list_item.get_child()
        if not box:
            return
        expand_btn = box.get_first_child()
        label = expand_btn.get_next_sibling()
        drill_btn = label.get_next_sibling()

        for widget, store in ((expand_btn, self._expand_handlers), (drill_btn, self._drill_handlers)):
            wid = id(widget)
            if wid in store:
                try:
                    widget.disconnect(store.pop(wid))
                except Exception:
                    pass

    # ── Type column factory ────────────────────────────────────────────────

    def _type_setup(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        list_item.set_child(label)

    def _type_bind(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item: PropertyItem = list_item.get_item()
        label: Gtk.Label = list_item.get_child()
        for cls in _TYPE_CSS.values():
            label.remove_css_class(cls)
        label.set_label(item.type_str)
        if css := _TYPE_CSS.get(item.type_str):
            label.add_css_class(css)

    # ── Value column factory ───────────────────────────────────────────────

    def _value_setup(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        label.add_css_class("monospace")
        list_item.set_child(label)

    def _value_bind(self, _fac: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item: PropertyItem = list_item.get_item()
        label: Gtk.Label = list_item.get_child()
        label.set_label(item.value_str)

    # ── Expand / collapse ──────────────────────────────────────────────────

    def _on_expand_clicked(self, btn: Gtk.Button, item: PropertyItem) -> None:
        item.expanded = not item.expanded
        btn.set_icon_name(
            "pan-down-symbolic" if item.expanded else "pan-end-symbolic"
        )
        if item.expanded:
            self._insert_children(item)
        else:
            self._remove_children(item)

    def _insert_children(self, parent: PropertyItem) -> None:
        parent_pos = self._find_item_pos(parent)
        if parent_pos is None:
            return
        children = [
            PropertyItem(
                name=c.get("name", ""),
                type_str=c.get("type", "unknown"),
                value_str=str(c.get("value", "")),
                writable=c.get("writable", False),
                depth=1,
                parent_name=parent.name,
            )
            for c in parent.children_data
        ]
        if children:
            self._store.splice(parent_pos + 1, 0, children)

    def _remove_children(self, parent: PropertyItem) -> None:
        parent_pos = self._find_item_pos(parent)
        if parent_pos is None:
            return
        n = self._store.get_n_items()
        count = 0
        for i in range(parent_pos + 1, n):
            child = self._store.get_item(i)
            if child.depth == 1 and child.parent_name == parent.name:
                count += 1
            else:
                break
        if count > 0:
            self._store.splice(parent_pos + 1, count, [])

    def _find_item_pos(self, target: PropertyItem) -> int | None:
        n = self._store.get_n_items()
        for i in range(n):
            if self._store.get_item(i) is target:
                return i
        return None

    # ── Drill-in / breadcrumb navigation ──────────────────────────────────

    def _on_drill_in(self, _btn: Gtk.Button, item: PropertyItem) -> None:
        self._navigate_to(self._current_path + [item.name])

    def _navigate_to(self, path: list[str]) -> None:
        self._current_path = path
        self._update_breadcrumb()
        if self._current_uuid:
            self._socket.send({"type": "inspect", "uuid": self._current_uuid, "path": path})
            self._status_lbl.set_label("Loading…")

    def _on_back(self, _btn: Gtk.Button) -> None:
        self._navigate_to(self._current_path[:-1])

    def _update_breadcrumb(self) -> None:
        # Clear existing breadcrumb widgets
        child = self._breadcrumb_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._breadcrumb_box.remove(child)
            child = nxt

        if not self._current_path:
            self._breadcrumb_revealer.set_reveal_child(False)
            return

        self._breadcrumb_revealer.set_reveal_child(True)

        # Back button
        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.add_css_class("flat")
        back_btn.set_tooltip_text("Go up one level")
        back_btn.connect("clicked", self._on_back)
        self._breadcrumb_box.append(back_btn)

        # Segments: "stateObj › _fetcher › _client"
        segments = ["stateObj"] + self._current_path
        for i, seg in enumerate(segments):
            if i > 0:
                sep = Gtk.Label(label=" › ")
                sep.add_css_class("dim-label")
                self._breadcrumb_box.append(sep)
            if i < len(segments) - 1:
                target = self._current_path[:i]
                btn = Gtk.Button(label=seg)
                btn.add_css_class("flat")
                btn.add_css_class("monospace")
                btn.connect("clicked", lambda _b, p=target: self._navigate_to(p))
                self._breadcrumb_box.append(btn)
            else:
                lbl = Gtk.Label(label=seg)
                lbl.add_css_class("monospace")
                lbl.add_css_class("heading")
                self._breadcrumb_box.append(lbl)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_target_extension(self, uuid: str | None) -> None:
        """Set the extension to inspect. Resets path and auto-loads if connected."""
        if uuid != self._current_uuid:
            self._current_uuid = uuid
            self._current_path = []
            self._update_breadcrumb()
            self._store.splice(0, self._store.get_n_items(), [])
            self._stack.set_visible_child_name("placeholder")
            self._status_lbl.set_label("")
        self.set_visible_child_name("content" if uuid else "no-selection")
        if uuid and self._socket.is_client_connected:
            self._socket.send({"type": "inspect", "uuid": uuid, "path": self._current_path})
            self._status_lbl.set_label("Loading…")

    # ── Toolbar actions ────────────────────────────────────────────────────

    def _on_refresh(self, _btn: object) -> None:
        uuid = self._current_uuid
        if not uuid:
            return
        self._socket.send({"type": "inspect", "uuid": uuid, "path": self._current_path})
        self._status_lbl.set_label("Refreshing…")

    def _on_copy(self, _btn: Gtk.Button) -> None:
        pos = self._selection.get_selected()
        if pos == _INVALID_POS:
            return
        item: PropertyItem | None = self._store.get_item(pos)
        if not item:
            return
        text = f"{item.name}\t{item.type_str}\t{item.value_str}"
        self.get_clipboard().set(text)

    def _on_selection_changed(self, _sel: Gtk.SingleSelection, _pos: int, _n: int) -> None:
        self._copy_btn.set_sensitive(self._selection.get_selected() != _INVALID_POS)

    # ── Inline editing ─────────────────────────────────────────────────────

    def _on_row_activate(self, _col_view: Gtk.ColumnView, pos: int) -> None:
        item: PropertyItem | None = self._store.get_item(pos)
        if not item or not item.writable or item.depth != 0:
            return
        if item.type_str not in ("string", "number", "boolean"):
            return
        self._show_edit_dialog(item)

    def _show_edit_dialog(self, item: PropertyItem) -> None:
        dialog = Adw.AlertDialog(
            heading=f"Edit: {item.name}",
            body=f"Current type: {item.type_str}",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("apply", "Apply")
        dialog.set_default_response("apply")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.Entry()
        entry.set_text(item.value_str)
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response != "apply" or not self._current_uuid:
                return
            raw = entry.get_text()
            if item.type_str == "number":
                try:
                    f = float(raw)
                    parsed: Any = int(f) if f == int(f) else f
                except ValueError:
                    return
            elif item.type_str == "boolean":
                parsed = raw.lower() in ("true", "1", "yes")
            else:
                parsed = raw
            self._socket.send({
                "type": "set_property",
                "uuid": self._current_uuid,
                "name": item.name,
                "value": parsed,
            })

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    # ── Socket message handling ────────────────────────────────────────────

    def _on_message(self, _server: SocketServer, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "inspect_result":
            self._on_inspect_result(msg)
        elif msg_type == "set_property_result":
            self._on_set_property_result(msg)

    def _on_inspect_result(self, msg: dict[str, Any]) -> None:
        if msg.get("extensionUuid") != self._current_uuid:
            return
        if msg.get("path", []) != self._current_path:
            return  # stale response from a previous navigation
        properties: list[dict[str, Any]] = msg.get("properties", [])

        items: list[PropertyItem] = []
        for prop in properties:
            pi = PropertyItem(
                name=prop.get("name", ""),
                type_str=prop.get("type", "unknown"),
                value_str=str(prop.get("value", "")),
                writable=prop.get("writable", False),
            )
            children = prop.get("children")
            if children:
                pi.has_children = True
                pi.children_data = children
            items.append(pi)

        self._store.splice(0, self._store.get_n_items(), items)

        count = len(items)
        word = "property" if count == 1 else "properties"
        self._status_lbl.set_label(f"{count} {word}")

        if count > 0:
            self._stack.set_visible_child_name("table")
        else:
            self._placeholder.set_description(
                f"No inspectable properties found for {self._current_uuid}."
            )
            self._stack.set_visible_child_name("placeholder")

    def _on_set_property_result(self, msg: dict[str, Any]) -> None:
        if msg.get("ok"):
            self._navigate_to(self._current_path)
        else:
            _log.warning(
                "set_property failed for %s: %s",
                msg.get("name", ""),
                msg.get("error", "unknown error"),
            )

    def _on_client_connected(self, _server: SocketServer) -> None:
        if self._current_uuid:
            self._socket.send({
                "type": "inspect",
                "uuid": self._current_uuid,
                "path": self._current_path,
            })
            self._status_lbl.set_label("Loading…")

    def _on_disconnected(self, _server: SocketServer) -> None:
        self._status_lbl.set_label("Disconnected")
