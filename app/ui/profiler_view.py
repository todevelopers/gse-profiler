import json
import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, GObject, Gtk

from app.core.dbus_client import DBusClient
from app.core.journal_reader import JournalReader, LogEntry
from app.core.socket_server import SocketServer

_log = logging.getLogger(__name__)

# Bridge UUID excluded from the target dropdown.
_BRIDGE_UUID = "gse-profiler-bridge@todevelopers"

# Bar colours per call depth (RGB, cycled).
_DEPTH_COLORS: list[tuple[float, float, float]] = [
    (0.22, 0.48, 0.85),
    (0.18, 0.70, 0.42),
    (0.85, 0.50, 0.10),
    (0.70, 0.22, 0.55),
    (0.55, 0.72, 0.18),
]


class FunctionStat(GObject.Object):
    """Aggregated timing statistics for a single profiled function."""

    __gtype_name__ = "FunctionStat"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.count: int = 0
        self.total_ms: float = 0.0
        self.max_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    def record(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms


class ProfilerView(Gtk.Box):
    """Live function timing profiler — Phase 4."""

    def __init__(self, dbus_client: DBusClient, socket_server: SocketServer) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._dbus = dbus_client
        self._socket = socket_server
        self._profiling = False
        self._refresh_pending = False

        # Data model
        self._stats: dict[str, FunctionStat] = {}
        self._raw_events: list[dict[str, Any]] = []
        self._ext_uuids: list[str] = []

        self._store = Gio.ListStore(item_type=FunctionStat)
        self._journal = JournalReader()
        self._journal.connect("log-entry", self._on_bridge_log)
        self._build_ui()

        socket_server.connect("message-received", self._on_message)
        socket_server.connect("client-disconnected", self._on_client_disconnected)
        dbus_client.connect("extensions-changed", self._on_extensions_changed)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Toolbar ────────────────────────────────────────────────────────
        self._ext_dropdown = Gtk.DropDown()
        self._ext_dropdown.set_tooltip_text("Target extension to profile")
        self._ext_string_list = Gtk.StringList.new([])
        self._ext_dropdown.set_model(self._ext_string_list)
        self._ext_dropdown.set_hexpand(False)

        self._start_btn = Gtk.Button(label="Start")
        self._start_btn.set_tooltip_text("Start profiling selected extension")
        self._start_btn.add_css_class("suggested-action")
        self._start_btn.connect("clicked", self._on_start)

        self._stop_btn = Gtk.Button(label="Stop")
        self._stop_btn.set_tooltip_text("Stop profiling")
        self._stop_btn.add_css_class("destructive-action")
        self._stop_btn.set_sensitive(False)
        self._stop_btn.connect("clicked", self._on_stop)

        save_btn = Gtk.Button()
        save_btn.set_icon_name("document-save-symbolic")
        save_btn.set_tooltip_text("Save profile to JSON file")
        save_btn.connect("clicked", self._on_save)

        load_btn = Gtk.Button()
        load_btn.set_icon_name("document-open-symbolic")
        load_btn.set_tooltip_text("Load profile from JSON file")
        load_btn.connect("clicked", self._on_load)

        clear_btn = Gtk.Button()
        clear_btn.set_icon_name("edit-clear-symbolic")
        clear_btn.set_tooltip_text("Clear all profiling data")
        clear_btn.connect("clicked", self._on_clear)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(4)
        sep.set_margin_end(4)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        toolbar.append(self._ext_dropdown)
        toolbar.append(self._start_btn)
        toolbar.append(self._stop_btn)
        toolbar.append(sep)
        toolbar.append(save_btn)
        toolbar.append(load_btn)
        toolbar.append(clear_btn)

        # ── Call table (GtkColumnView) ─────────────────────────────────────
        sort_model = Gtk.SortListModel(model=self._store)
        selection = Gtk.SingleSelection(model=sort_model)
        col_view = Gtk.ColumnView(model=selection)
        col_view.set_show_column_separators(True)
        col_view.set_show_row_separators(True)
        col_view.set_vexpand(True)
        sort_model.set_sorter(col_view.get_sorter())

        col_view.append_column(self._make_col("Function", "name", str, expand=True))
        col_view.append_column(self._make_col("Calls", "count", str))
        col_view.append_column(self._make_col("Total ms", "total_ms", lambda v: f"{v:.3f}"))
        col_view.append_column(self._make_col("Avg ms", "avg_ms", lambda v: f"{v:.3f}"))
        col_view.append_column(self._make_col("Max ms", "max_ms", lambda v: f"{v:.3f}"))

        table_scroll = Gtk.ScrolledWindow()
        table_scroll.set_vexpand(True)
        table_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        table_scroll.set_child(col_view)

        # ── Timeline (DrawingArea) ─────────────────────────────────────────
        self._timeline = Gtk.DrawingArea()
        self._timeline.set_draw_func(self._draw_timeline)
        self._timeline.set_content_height(120)
        self._timeline.set_hexpand(True)

        timeline_scroll = Gtk.ScrolledWindow()
        timeline_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        timeline_scroll.set_min_content_height(120)
        timeline_scroll.set_max_content_height(400)
        timeline_scroll.set_child(self._timeline)

        tl_label = Gtk.Label(label="Timeline")
        tl_label.set_xalign(0.0)
        tl_label.set_margin_start(6)
        tl_label.set_margin_top(6)
        tl_label.add_css_class("heading")

        timeline_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        timeline_box.append(tl_label)
        timeline_box.append(timeline_scroll)

        # ── Paned split ────────────────────────────────────────────────────
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_start_child(table_scroll)
        paned.set_end_child(timeline_box)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(True)
        paned.set_position(300)
        paned.set_vexpand(True)

        # ── Bridge log panel ───────────────────────────────────────────────
        self._bridge_log_view = Gtk.TextView()
        self._bridge_log_view.set_editable(False)
        self._bridge_log_view.set_cursor_visible(False)
        self._bridge_log_view.set_monospace(True)
        self._bridge_log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        bridge_log_scroll = Gtk.ScrolledWindow()
        bridge_log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        bridge_log_scroll.set_min_content_height(80)
        bridge_log_scroll.set_max_content_height(160)
        bridge_log_scroll.set_child(self._bridge_log_view)

        bridge_log_label = Gtk.Label(label="Bridge logs")
        bridge_log_label.set_xalign(0.0)
        bridge_log_label.set_margin_start(6)
        bridge_log_label.set_margin_top(4)
        bridge_log_label.add_css_class("caption-heading")
        bridge_log_label.add_css_class("dim-label")

        bridge_log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bridge_log_box.append(bridge_log_label)
        bridge_log_box.append(bridge_log_scroll)

        self.append(toolbar)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.append(paned)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.append(bridge_log_box)

    # ── Column helpers ─────────────────────────────────────────────────────

    def _make_col(
        self,
        title: str,
        attr: str,
        fmt: Callable[..., str] = str,
        *,
        expand: bool = False,
    ) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._col_setup, attr)
        factory.connect("bind", self._col_bind, attr, fmt)

        sorter = Gtk.CustomSorter.new(self._sorter_func, attr)
        col = Gtk.ColumnViewColumn(title=title, factory=factory, sorter=sorter)
        col.set_expand(expand)
        return col

    @staticmethod
    def _col_setup(
        _factory: Gtk.SignalListItemFactory,
        item: Gtk.ListItem,
        attr: str,
    ) -> None:
        label = Gtk.Label()
        label.set_xalign(0.0 if attr == "name" else 1.0)
        label.set_margin_start(4)
        label.set_margin_end(4)
        item.set_child(label)

    @staticmethod
    def _col_bind(
        _factory: Gtk.SignalListItemFactory,
        item: Gtk.ListItem,
        attr: str,
        fmt: Callable[..., str],
    ) -> None:
        stat: FunctionStat = item.get_item()
        label: Gtk.Label = item.get_child()  # type: ignore[assignment]
        label.set_text(fmt(getattr(stat, attr)))

    @staticmethod
    def _sorter_func(a: FunctionStat, b: FunctionStat, attr: str) -> int:
        va = getattr(a, attr)
        vb = getattr(b, attr)
        if va < vb:
            return -1
        if va > vb:
            return 1
        return 0

    # ── Timeline drawing ───────────────────────────────────────────────────

    def _draw_timeline(
        self,
        _area: Gtk.DrawingArea,
        cr: Any,
        width: int,
        _height: int,
    ) -> None:
        if not self._raw_events:
            cr.set_source_rgb(0.55, 0.55, 0.55)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(12)
            text = "No profiling data — start profiling to see the timeline"
            extents = cr.text_extents(text)
            cr.move_to((width - extents[2]) / 2, 60)
            cr.show_text(text)
            return

        min_t = min(e["start"] for e in self._raw_events)
        max_t = max(e["end"] for e in self._raw_events)
        time_span = max_t - min_t or 1e-9

        # Unique function names in order of first appearance.
        seen: dict[str, int] = {}
        for e in self._raw_events:
            fn = e["function"]
            if fn not in seen:
                seen[fn] = len(seen)

        LABEL_W = 160
        ROW_H = 22
        PAD_TOP = 18  # space for time axis labels
        PAD_BOT = 4
        chart_w = max(width - LABEL_W - 4, 1)
        needed_h = PAD_TOP + len(seen) * ROW_H + PAD_BOT

        # Expand drawing area to fit all rows.
        self._timeline.set_content_height(max(needed_h, 120))

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)

        # Background.
        cr.set_source_rgb(0.96, 0.96, 0.97)
        cr.paint()

        # Alternating row backgrounds.
        for fn, row in seen.items():
            y = PAD_TOP + row * ROW_H
            if row % 2 == 0:
                cr.set_source_rgb(0.90, 0.90, 0.95)
                cr.rectangle(0, y, width, ROW_H)
                cr.fill()

            # Function label (truncated).
            label = fn if len(fn) <= 23 else f"…{fn[-22:]}"
            cr.set_source_rgb(0.12, 0.12, 0.12)
            cr.move_to(4, y + ROW_H - 5)
            cr.show_text(label)

        # Event bars.
        for e in self._raw_events:
            row = seen[e["function"]]
            y = PAD_TOP + row * ROW_H + 3
            x = LABEL_W + (e["start"] - min_t) / time_span * chart_w
            bar_w = max((e["end"] - e["start"]) / time_span * chart_w, 2.0)
            r, g, b = _DEPTH_COLORS[e.get("depth", 0) % len(_DEPTH_COLORS)]
            cr.set_source_rgba(r, g, b, 0.82)
            cr.rectangle(x, y, bar_w, ROW_H - 6)
            cr.fill()

        # Time axis ticks (5 evenly-spaced).
        cr.set_source_rgb(0.35, 0.35, 0.35)
        cr.set_line_width(0.5)
        for tick in range(5):
            x = LABEL_W + tick / 4 * chart_w
            cr.move_to(x, PAD_TOP - 1)
            cr.line_to(x, needed_h - PAD_BOT)
            cr.stroke()
            t_ms = (min_t + tick / 4 * time_span) * 1000
            cr.move_to(x + 2, PAD_TOP - 4)
            cr.show_text(f"{t_ms:.1f}ms")

    # ── Signal handlers ────────────────────────────────────────────────────

    def _on_start(self, _btn: Gtk.Button) -> None:
        uuid = self._selected_uuid()
        _log.debug(
            "Start clicked — uuid=%r connected=%s ext_count=%d",
            uuid,
            self._socket.is_client_connected,
            len(self._ext_uuids),
        )
        if not uuid:
            _log.warning("Start clicked but no extension selected (ext_uuids=%r)", self._ext_uuids)
            return
        self._clear_bridge_log()
        self._journal.start()
        self._socket.send({"type": "start_profiling", "uuid": uuid})
        self._profiling = True
        self._start_btn.set_sensitive(False)
        self._stop_btn.set_sensitive(True)
        self._ext_dropdown.set_sensitive(False)

    def _on_stop(self, _btn: Gtk.Button) -> None:
        _log.debug("Stop clicked")
        self._socket.send({"type": "stop_profiling"})
        self._set_stopped()

    def _set_stopped(self) -> None:
        self._profiling = False
        self._journal.stop()
        self._start_btn.set_sensitive(True)
        self._stop_btn.set_sensitive(False)
        self._ext_dropdown.set_sensitive(True)

    def _on_save(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Profile")
        dialog.set_initial_name("profile.json")
        dialog.save(self.get_root(), None, self._on_save_response)

    def _on_save_response(
        self, dialog: Gtk.FileDialog, result: Gio.AsyncResult
    ) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return
        payload = {
            "events": self._raw_events,
            "stats": {
                name: {
                    "count": s.count,
                    "total_ms": s.total_ms,
                    "max_ms": s.max_ms,
                }
                for name, s in self._stats.items()
            },
        }
        try:
            gfile.replace_contents(
                json.dumps(payload, indent=2).encode(),
                None,
                False,
                Gio.FileCreateFlags.REPLACE_DESTINATION,
                None,
            )
        except GLib.Error as exc:
            _log.error("Failed to save profile: %s", exc)

    def _on_load(self, _btn: Gtk.Button) -> None:
        filt = Gtk.FileFilter()
        filt.set_name("JSON files")
        filt.add_pattern("*.json")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(filt)

        dialog = Gtk.FileDialog()
        dialog.set_title("Load Profile")
        dialog.set_filters(filters)
        dialog.open(self.get_root(), None, self._on_load_response)

    def _on_load_response(
        self, dialog: Gtk.FileDialog, result: Gio.AsyncResult
    ) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        try:
            _ok, contents, _etag = gfile.load_contents(None)
            data = json.loads(contents.decode())
        except (GLib.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
            _log.error("Failed to load profile: %s", exc)
            return

        self._clear_data()
        for event in data.get("events", []):
            self._ingest_event(event, schedule_refresh=False)
        self._flush_refresh()

    def _on_clear(self, _btn: Gtk.Button) -> None:
        self._clear_data()
        self._flush_refresh()

    def _on_message(self, _server: SocketServer, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "profile_event":
            _log.debug("profile_event: fn=%s dur=%.3fms", msg.get("function"), (msg.get("end", 0) - msg.get("start", 0)) * 1000)
            self._ingest_event(msg)
        elif msg_type == "profiling_started":
            _log.info("profiling_started: uuid=%s ok=%s", msg.get("uuid"), msg.get("ok"))
            if not msg.get("ok"):
                _log.warning("Bridge could not find stateObj for %s — no functions patched", msg.get("uuid"))
        elif msg_type == "profiling_stopped":
            _log.debug("profiling_stopped received")
            self._set_stopped()
        else:
            _log.debug("message received from bridge: type=%s", msg_type)

    def _on_client_disconnected(self, _server: SocketServer) -> None:
        if self._profiling:
            self._set_stopped()

    def _on_bridge_log(self, _reader: JournalReader, entry: LogEntry) -> None:
        if "gse-profiler-bridge" not in entry.message:
            return
        buf = self._bridge_log_view.get_buffer()
        end = buf.get_end_iter()
        buf.insert(end, f"{entry.timestamp.strftime('%H:%M:%S')} {entry.message}\n")
        # Auto-scroll bridge log to bottom.
        vadj = self._bridge_log_view.get_parent().get_vadjustment()  # type: ignore[union-attr]
        vadj.set_value(vadj.get_upper())

    def _clear_bridge_log(self) -> None:
        self._bridge_log_view.get_buffer().set_text("")

    def _on_extensions_changed(
        self, _dbus: DBusClient, extensions: dict[str, Any]
    ) -> None:
        selected = self._selected_uuid()
        self._ext_uuids = [u for u in extensions if u != _BRIDGE_UUID]
        names = [extensions[u].get("name") or u for u in self._ext_uuids]
        _log.debug("extensions_changed: %d available for profiling: %r", len(self._ext_uuids), self._ext_uuids)

        new_list = Gtk.StringList.new(names)
        self._ext_dropdown.set_model(new_list)
        self._ext_string_list = new_list

        if selected and selected in self._ext_uuids:
            self._ext_dropdown.set_selected(self._ext_uuids.index(selected))

    # ── Data management ────────────────────────────────────────────────────

    def _ingest_event(
        self, event: dict[str, Any], *, schedule_refresh: bool = True
    ) -> None:
        name = event.get("function", "?")
        duration_ms = (event.get("end", 0.0) - event.get("start", 0.0)) * 1000.0

        if name not in self._stats:
            self._stats[name] = FunctionStat(name)
        self._stats[name].record(duration_ms)
        self._raw_events.append(event)

        if schedule_refresh:
            self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Debounce store/timeline refresh to at most once per 80 ms."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        GLib.timeout_add(80, self._flush_refresh_cb)

    def _flush_refresh_cb(self) -> bool:
        self._flush_refresh()
        return bool(GLib.SOURCE_REMOVE)

    def _flush_refresh(self) -> None:
        self._refresh_pending = False
        self._store.splice(0, self._store.get_n_items(), list(self._stats.values()))
        self._timeline.queue_draw()

    def _clear_data(self) -> None:
        self._stats.clear()
        self._raw_events.clear()

    def _selected_uuid(self) -> str | None:
        idx = self._ext_dropdown.get_selected()
        if 0 <= idx < len(self._ext_uuids):
            return str(self._ext_uuids[idx])
        return None
