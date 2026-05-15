import json
import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, GObject, Gtk

from app.core.dbus_client import DBusClient
from app.core.socket_server import SocketServer

_log = logging.getLogger(__name__)

# Bar colours per call depth (RGB, cycled).
_DEPTH_COLORS: list[tuple[float, float, float]] = [
    (0.22, 0.48, 0.85),
    (0.18, 0.70, 0.42),
    (0.85, 0.50, 0.10),
    (0.70, 0.22, 0.55),
    (0.55, 0.72, 0.18),
]

# Idle periods longer than this collapse into a visual break on the timeline.
_GAP_THRESHOLD_S = 2.0
# Pixel width of the collapsed-gap break drawn between segments.
_GAP_BREAK_PX = 22


class FunctionStat(GObject.Object):
    """Aggregated timing statistics for a single profiled function."""

    __gtype_name__ = "FunctionStat"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.count: int = 0
        self.total_ms: float = 0.0
        self.self_ms: float = 0.0
        self.max_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    def record(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms


class ProfilerView(Gtk.Stack):
    """Live function timing profiler."""

    def __init__(self, dbus_client: DBusClient, socket_server: SocketServer) -> None:
        super().__init__()
        self._socket = socket_server
        self._profiling = False
        self._refresh_pending = False
        self._target_uuid: str | None = None

        # Data model
        self._stats: dict[str, FunctionStat] = {}
        self._raw_events: list[dict[str, Any]] = []

        self._store = Gio.ListStore(item_type=FunctionStat)
        self._build_ui()

        socket_server.connect("message-received", self._on_message)
        socket_server.connect("client-disconnected", self._on_client_disconnected)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("power-profile-performance-symbolic")
        placeholder.set_title("No Extension Selected")
        placeholder.set_description("Select an enabled extension from the list to start profiling.")
        self.add_named(placeholder, "placeholder")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add_named(content, "content")
        self.set_visible_child_name("placeholder")

        # ── Toolbar ────────────────────────────────────────────────────────
        self._start_btn = Gtk.Button(label="Start profiling")
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
        col_view.append_column(self._make_col("Self ms", "self_ms", lambda v: f"{v:.3f}"))
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
        timeline_scroll.set_vexpand(True)
        timeline_scroll.set_child(self._timeline)

        tl_label = Gtk.Label(label="Timeline")
        tl_label.set_xalign(0.0)
        tl_label.set_margin_start(6)
        tl_label.set_margin_top(6)
        tl_label.add_css_class("heading")

        timeline_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        timeline_box.set_vexpand(True)
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

        content.append(toolbar)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        content.append(paned)

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

    def _visible_segments(self) -> list[tuple[float, float]]:
        """Return active-time segments separated by collapsed idle gaps.

        Iterates events in start-order, tracking the running max end-time
        seen so far. A segment closes when the next event's start is more
        than ``_GAP_THRESHOLD_S`` past that max — this correctly handles
        long-running parents whose end time follows several shorter
        children in start-order.
        """
        if not self._raw_events:
            return []
        ordered = sorted(self._raw_events, key=lambda e: e["start"])
        segments: list[tuple[float, float]] = []
        seg_start = ordered[0]["start"]
        running_end = ordered[0]["end"]
        for e in ordered[1:]:
            if e["start"] - running_end > _GAP_THRESHOLD_S:
                segments.append((seg_start, running_end))
                seg_start = e["start"]
                running_end = e["end"]
            else:
                if e["end"] > running_end:
                    running_end = e["end"]
        segments.append((seg_start, running_end))
        return segments

    @staticmethod
    def _format_gap(seconds: float) -> str:
        if seconds < 1.0:
            return f"+{seconds * 1000:.0f}ms"
        if seconds < 60.0:
            return f"+{seconds:.1f}s"
        return f"+{seconds / 60:.1f}m"

    def _draw_timeline(
        self,
        _area: Gtk.DrawingArea,
        cr: Any,
        width: int,
        _height: int,
    ) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        if dark:
            c_bg       = (0.12, 0.12, 0.15)
            c_row_alt  = (0.18, 0.18, 0.23)
            c_text     = (0.88, 0.88, 0.88)
            c_tick     = (0.55, 0.55, 0.55)
            c_gap_bg   = (0.08, 0.08, 0.10)
        else:
            c_bg       = (0.96, 0.96, 0.97)
            c_row_alt  = (0.90, 0.90, 0.95)
            c_text     = (0.12, 0.12, 0.12)
            c_tick     = (0.35, 0.35, 0.35)
            c_gap_bg   = (0.82, 0.82, 0.84)

        if not self._raw_events:
            cr.set_source_rgb(*c_tick)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(12)
            text = "No profiling data — start profiling to see the timeline"
            extents = cr.text_extents(text)
            cr.move_to((width - extents[2]) / 2, 60)
            cr.show_text(text)
            return

        segments = self._visible_segments()
        active_total = sum(e - s for s, e in segments) or 1e-9
        n_breaks = len(segments) - 1

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
        seg_total_px = max(chart_w - n_breaks * _GAP_BREAK_PX, 10)
        needed_h = PAD_TOP + len(seen) * ROW_H + PAD_BOT

        # Expand drawing area to fit all rows.
        self._timeline.set_content_height(max(needed_h, 120))

        # Lay out each segment in display space: (seg_start, seg_end, x0, w_px).
        seg_layout: list[tuple[float, float, float, float]] = []
        x_cursor = float(LABEL_W)
        for seg_s, seg_e in segments:
            seg_w_px = (seg_e - seg_s) / active_total * seg_total_px
            seg_layout.append((seg_s, seg_e, x_cursor, seg_w_px))
            x_cursor += seg_w_px + _GAP_BREAK_PX

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)

        # Background.
        cr.set_source_rgb(*c_bg)
        cr.paint()

        # Alternating row backgrounds and function labels.
        for fn, row in seen.items():
            y = PAD_TOP + row * ROW_H
            if row % 2 == 0:
                cr.set_source_rgb(*c_row_alt)
                cr.rectangle(0, y, width, ROW_H)
                cr.fill()
            label = fn if len(fn) <= 23 else f"…{fn[-22:]}"
            cr.set_source_rgb(*c_text)
            cr.move_to(4, y + ROW_H - 5)
            cr.show_text(label)

        # Shade the collapsed-gap "break" columns.
        for i in range(n_breaks):
            _, _, x0_prev, w_prev = seg_layout[i]
            break_x = x0_prev + w_prev
            cr.set_source_rgb(*c_gap_bg)
            cr.rectangle(break_x, PAD_TOP, _GAP_BREAK_PX, needed_h - PAD_TOP - PAD_BOT)
            cr.fill()

        # Event bars — split across every segment they overlap.
        for e in self._raw_events:
            row = seen[e["function"]]
            y = PAD_TOP + row * ROW_H + 3
            r, g, b = _DEPTH_COLORS[e.get("depth", 0) % len(_DEPTH_COLORS)]
            cr.set_source_rgba(r, g, b, 0.82)
            for seg_s, seg_e, x0, w in seg_layout:
                if e["end"] <= seg_s or e["start"] >= seg_e:
                    continue
                seg_dur = seg_e - seg_s
                if seg_dur <= 0 or w <= 0:
                    continue
                piece_s = max(e["start"], seg_s)
                piece_e = min(e["end"], seg_e)
                x = x0 + (piece_s - seg_s) / seg_dur * w
                bar_w = max((piece_e - piece_s) / seg_dur * w, 2.0)
                cr.rectangle(x, y, bar_w, ROW_H - 6)
                cr.fill()

        # Segment-break visuals: two dashed verticals + gap-duration label.
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(1.0)
        for i in range(n_breaks):
            _, prev_end, x0_prev, w_prev = seg_layout[i]
            next_start = seg_layout[i + 1][0]
            break_x = x0_prev + w_prev
            cr.set_dash([3, 3])
            for dx in (3, _GAP_BREAK_PX - 3):
                cr.move_to(break_x + dx, PAD_TOP)
                cr.line_to(break_x + dx, needed_h - PAD_BOT)
                cr.stroke()
            cr.set_dash([])
            gap_label = self._format_gap(next_start - prev_end)
            cr.set_font_size(9)
            ext = cr.text_extents(gap_label)
            cr.move_to(break_x + (_GAP_BREAK_PX - ext[2]) / 2, PAD_TOP - 4)
            cr.show_text(gap_label)
            cr.set_font_size(10)

        # Time axis: per-segment start/end labels (relative to overall start).
        t0 = segments[0][0]
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(0.5)
        for seg_s, seg_e, x0, w in seg_layout:
            for frac, t_real in ((0.0, seg_s), (1.0, seg_e)):
                x = x0 + frac * w
                cr.move_to(x, PAD_TOP - 1)
                cr.line_to(x, needed_h - PAD_BOT)
                cr.stroke()
                t_ms = (t_real - t0) * 1000.0
                # Skip the end tick of one segment when the next starts very
                # close on screen — only the gap-break draws between them.
                label = f"{t_ms:.1f}ms"
                ext = cr.text_extents(label)
                # Right-align end labels so they don't overflow the segment.
                lx = x + 2 if frac == 0.0 else x - ext[2] - 2
                cr.move_to(lx, PAD_TOP - 4)
                cr.show_text(label)

    # ── Signal handlers ────────────────────────────────────────────────────

    # ── Public API ─────────────────────────────────────────────────────────

    def set_target_extension(self, uuid: str | None) -> None:
        """Set the extension to profile. Stops ongoing profiling if UUID changes."""
        if self._profiling and uuid != self._target_uuid:
            self._socket.send({"type": "stop_profiling"})
            self._set_stopped()
        self._target_uuid = uuid
        self.set_visible_child_name("content" if uuid else "placeholder")
        self._start_btn.set_sensitive(uuid is not None and not self._profiling)

    # ── Button handlers ────────────────────────────────────────────────────

    def _on_start(self, _btn: Gtk.Button) -> None:
        uuid = self._target_uuid
        _log.debug("Start clicked — uuid=%r connected=%s", uuid, self._socket.is_client_connected)
        if not uuid:
            _log.warning("Start clicked but no target extension set")
            return
        self._socket.send({"type": "start_profiling", "uuid": uuid})
        self._profiling = True
        self._start_btn.set_sensitive(False)
        self._stop_btn.set_sensitive(True)

    def _on_stop(self, _btn: Gtk.Button) -> None:
        _log.debug("Stop clicked")
        self._socket.send({"type": "stop_profiling"})
        self._set_stopped()

    def _set_stopped(self) -> None:
        self._profiling = False
        self._start_btn.set_sensitive(self._target_uuid is not None)
        self._stop_btn.set_sensitive(False)

    def _on_save(self, _btn: Gtk.Button) -> None:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        if self._target_uuid:
            short = self._target_uuid.split("@")[0]
            filename = f"gse-profile_{short}_{ts}.json"
        else:
            filename = f"gse-profile_{ts}.json"

        dialog = Gtk.FileDialog()
        dialog.set_title("Save Profile")
        dialog.set_initial_name(filename)
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
                self._set_stopped()
        elif msg_type == "profiling_stopped":
            _log.debug("profiling_stopped received")
            self._set_stopped()
        else:
            _log.debug("message received from bridge: type=%s", msg_type)

    def _on_client_disconnected(self, _server: SocketServer) -> None:
        if self._profiling:
            self._set_stopped()

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
        self._recompute_self_times()
        # Fresh FunctionStat instances every refresh: GtkColumnView skips
        # unbind+bind when the same GObject pointer reappears at a given
        # position, which otherwise leaves stale counts in the table cells
        # whenever a stat updates in place between flushes.
        snapshots = [self._stat_snapshot(s) for s in self._stats.values()]
        self._store.splice(0, self._store.get_n_items(), snapshots)
        self._timeline.queue_draw()

    @staticmethod
    def _stat_snapshot(stat: FunctionStat) -> FunctionStat:
        snap = FunctionStat(stat.name)
        snap.count = stat.count
        snap.total_ms = stat.total_ms
        snap.self_ms = stat.self_ms
        snap.max_ms = stat.max_ms
        return snap

    def _recompute_self_times(self) -> None:
        """Aggregate per-function self-time = total minus direct children.

        Uses a stack-based pass over events sorted by (start ASC, end DESC)
        so that parents are visited before their children. Each event's
        full duration is added to its own self bucket, then its parent's
        bucket is decremented by that duration — leaving each event with
        exclusive (non-callee) wall-clock time. Results are summed per
        function name into ``FunctionStat.self_ms``.
        """
        for s in self._stats.values():
            s.self_ms = 0.0
        if not self._raw_events:
            return
        ordered = sorted(self._raw_events, key=lambda e: (e["start"], -e["end"]))
        stack: list[dict[str, Any]] = []
        event_self: dict[int, float] = {}
        for e in ordered:
            while stack and stack[-1]["end"] <= e["start"]:
                stack.pop()
            dur_ms = (e["end"] - e["start"]) * 1000.0
            event_self[id(e)] = dur_ms
            if stack:
                event_self[id(stack[-1])] -= dur_ms
            stack.append(e)
        for e in ordered:
            stat = self._stats.get(e["function"])
            if stat is not None:
                stat.self_ms += event_self[id(e)]

    def _clear_data(self) -> None:
        self._stats.clear()
        self._raw_events.clear()
