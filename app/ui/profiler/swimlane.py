"""Swimlane timeline view — one lane per unique function name, with idle gaps
collapsed into visual break columns.

Ports the legacy ``profiler_view._draw_timeline`` into a self-contained
``Gtk.DrawingArea`` subclass that supports hover tooltips, click selection,
and a filter-text dim.
"""

from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from . import (
    DEPTH_COLORS,
    GAP_BREAK_PX,
    GAP_THRESHOLD_S,
    TooltipPopover,
    desaturate_color,
    format_gap,
    format_ms,
    visible_segments,
)

_LABEL_W = 160
_ROW_H = 22
_PAD_TOP = 22
_PAD_BOT = 8


class SwimlaneView(Gtk.DrawingArea):
    """One row per function, idle gaps shown as collapsed break columns."""

    __gtype_name__ = "SwimlaneView"

    __gsignals__ = {
        # Empty string means "clear selection" (GLib signals can't pass None).
        "function-selected": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self._selected_fn: str | None = None
        self._filter_text: str = ""

        # Hit-test cache: (x, y, w, h, event)
        self._bar_rects: list[tuple[float, float, float, float, dict[str, Any]]] = []

        self.set_hexpand(True)
        self.set_content_height(140)
        self.set_draw_func(self._draw)

        self._tooltip = TooltipPopover(self)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        click = Gtk.GestureClick.new()
        click.connect("released", self._on_click)
        self.add_controller(click)

    # ── Public setters ────────────────────────────────────────────────────

    def set_events(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.queue_draw()

    def set_selected_fn(self, fn: str | None) -> None:
        if fn == self._selected_fn:
            return
        self._selected_fn = fn
        self.queue_draw()

    def set_filter_text(self, text: str) -> None:
        new = text.strip().lower()
        if new == self._filter_text:
            return
        self._filter_text = new
        self.queue_draw()

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw(self, _area: Gtk.DrawingArea, cr: Any, width: int, _height: int) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        if dark:
            c_bg       = (0.15, 0.15, 0.15)
            c_row_alt  = (0.19, 0.19, 0.19)
            c_text     = (0.88, 0.88, 0.88)
            c_tick     = (0.55, 0.55, 0.55)
            c_gap_bg   = (0.10, 0.10, 0.10)
        else:
            c_bg       = (1.00, 1.00, 1.00)
            c_row_alt  = (0.95, 0.95, 0.97)
            c_text     = (0.12, 0.12, 0.12)
            c_tick     = (0.35, 0.35, 0.35)
            c_gap_bg   = (0.88, 0.88, 0.90)

        self._bar_rects.clear()

        if not self._events:
            cr.set_source_rgb(*c_tick)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(12)
            text = "No profiling data — start profiling to see the swimlane"
            extents = cr.text_extents(text)
            cr.move_to((width - extents[2]) / 2, 60)
            cr.show_text(text)
            return

        segments = visible_segments(self._events)
        active_total = sum(e - s for s, e in segments) or 1e-9
        n_breaks = len(segments) - 1

        # Unique function names in order of first appearance.
        seen: dict[str, int] = {}
        for e in self._events:
            fn = e["function"]
            if fn not in seen:
                seen[fn] = len(seen)

        chart_w = max(width - _LABEL_W - 4, 1)
        seg_total_px = max(chart_w - n_breaks * GAP_BREAK_PX, 10)
        needed_h = _PAD_TOP + len(seen) * _ROW_H + _PAD_BOT
        self.set_content_height(max(needed_h, 140))

        # Lay out segments in display space: (seg_start, seg_end, x0, w_px).
        seg_layout: list[tuple[float, float, float, float]] = []
        x_cursor = float(_LABEL_W)
        for seg_s, seg_e in segments:
            seg_w_px = (seg_e - seg_s) / active_total * seg_total_px
            seg_layout.append((seg_s, seg_e, x_cursor, seg_w_px))
            x_cursor += seg_w_px + GAP_BREAK_PX

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)

        # Background.
        cr.set_source_rgb(*c_bg)
        cr.paint()

        # Alternating row backgrounds and function labels.
        for fn, row in seen.items():
            y = _PAD_TOP + row * _ROW_H
            if row % 2 == 0:
                cr.set_source_rgb(*c_row_alt)
                cr.rectangle(0, y, width, _ROW_H)
                cr.fill()
            label = fn if len(fn) <= 23 else f"…{fn[-22:]}"
            dimmed = self._is_dimmed(fn)
            r, g, b = c_text
            cr.set_source_rgba(r, g, b, 0.30 if dimmed else 0.95)
            cr.move_to(4, y + _ROW_H - 5)
            cr.show_text(label)

        # Shade the collapsed-gap "break" columns.
        for i in range(n_breaks):
            _, _, x0_prev, w_prev = seg_layout[i]
            break_x = x0_prev + w_prev
            cr.set_source_rgb(*c_gap_bg)
            cr.rectangle(break_x, _PAD_TOP, GAP_BREAK_PX, needed_h - _PAD_TOP - _PAD_BOT)
            cr.fill()

        # Event bars — split across every segment they overlap.
        for e in self._events:
            row = seen[e["function"]]
            y = _PAD_TOP + row * _ROW_H + 4
            r, g, b = desaturate_color(*DEPTH_COLORS[e.get("depth", 0) % len(DEPTH_COLORS)])
            alpha = 0.22 if self._is_dimmed(e["function"]) else 0.85
            cr.set_source_rgba(r, g, b, alpha)
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
                bar_h = _ROW_H - 8
                cr.rectangle(x, y, bar_w, bar_h)
                cr.fill()
                self._bar_rects.append((x, y, bar_w, bar_h, e))

        # Segment-break visuals: two dashed verticals + gap-duration label.
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(1.0)
        for i in range(n_breaks):
            _, prev_end, x0_prev, w_prev = seg_layout[i]
            next_start = seg_layout[i + 1][0]
            break_x = x0_prev + w_prev
            cr.set_dash([3, 3])
            for dx in (3, GAP_BREAK_PX - 3):
                cr.move_to(break_x + dx, _PAD_TOP)
                cr.line_to(break_x + dx, needed_h - _PAD_BOT)
                cr.stroke()
            cr.set_dash([])
            gap_label = format_gap(next_start - prev_end)
            cr.set_font_size(9)
            ext = cr.text_extents(gap_label)
            cr.move_to(break_x + (GAP_BREAK_PX - ext[2]) / 2, _PAD_TOP - 6)
            cr.show_text(gap_label)
            cr.set_font_size(10)

        # Time axis: per-segment start/end labels (relative to overall start).
        t0 = segments[0][0]
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(0.5)
        for seg_s, seg_e, x0, w in seg_layout:
            for frac, t_real in ((0.0, seg_s), (1.0, seg_e)):
                x = x0 + frac * w
                cr.move_to(x, _PAD_TOP - 2)
                cr.line_to(x, needed_h - _PAD_BOT)
                cr.stroke()
                t_ms = (t_real - t0) * 1000.0
                label = f"{t_ms:.1f}ms"
                ext = cr.text_extents(label)
                lx = x + 2 if frac == 0.0 else x - ext[2] - 2
                cr.move_to(lx, _PAD_TOP - 6)
                cr.show_text(label)

    # ── Interaction ──────────────────────────────────────────────────────

    def _is_dimmed(self, fn: str) -> bool:
        if self._filter_text and self._filter_text not in fn.lower():
            return True
        if self._selected_fn is not None and self._selected_fn != fn:
            return True
        return False

    def _hit_test(self, x: float, y: float) -> dict[str, Any] | None:
        for bx, by, bw, bh, e in self._bar_rects:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return e
        return None

    def _on_motion(self, _ctrl: Gtk.EventControllerMotion, x: float, y: float) -> None:
        e = self._hit_test(x, y)
        if e is None:
            self._tooltip.hide()
            return
        dur_ms = (e["end"] - e["start"]) * 1000.0
        t0 = min((ev["start"] for ev in self._events), default=0.0)
        self._tooltip.show_at(
            x,
            y,
            e["function"],
            [
                ("Duration", format_ms(dur_ms)),
                ("Depth", str(e.get("depth", 0))),
                ("Start", format_ms((e["start"] - t0) * 1000.0)),
                ("End", format_ms((e["end"] - t0) * 1000.0)),
            ],
        )

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        self._tooltip.hide()

    def _on_click(self, _ctrl: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        e = self._hit_test(x, y)
        if e is None:
            return
        fn = e["function"]
        new = "" if fn == self._selected_fn else fn
        self.emit("function-selected", new)
