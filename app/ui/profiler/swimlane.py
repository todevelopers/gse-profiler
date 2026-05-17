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
    TooltipPopover,
    compute_timeline_layout,
    desaturate_color,
    draw_gap_break,
    format_ms,
    rounded_rect,
)

_LABEL_W_MIN = 80
_LABEL_W_MAX = 220
_ROW_H = 28
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
        self._show_gaps: bool = True

        # Hit-test cache: (x, y, w, h, event)
        self._bar_rects: list[tuple[float, float, float, float, dict[str, Any]]] = []
        self._hovered_event: dict[str, Any] | None = None

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

    def set_show_gaps(self, show: bool) -> None:
        if show == self._show_gaps:
            return
        self._show_gaps = show
        self.queue_draw()

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw(self, _area: Gtk.DrawingArea, cr: Any, width: int, _height: int) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        if dark:
            c_bg      = (0.15, 0.15, 0.15)
            c_row_alt = (0.19, 0.19, 0.19)
            c_text    = (0.88, 0.88, 0.88)
            c_tick    = (0.55, 0.55, 0.55)
        else:
            c_bg      = (1.00, 1.00, 1.00)
            c_row_alt = (0.95, 0.95, 0.97)
            c_text    = (0.12, 0.12, 0.12)
            c_tick    = (0.35, 0.35, 0.35)

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

        # Unique function names in order of first appearance.
        seen: dict[str, int] = {}
        for e in self._events:
            fn = e["function"]
            if fn not in seen:
                seen[fn] = len(seen)

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)
        char_w = cr.text_extents("m")[2]
        max_name_px = max((cr.text_extents(fn)[2] for fn in seen), default=float(_LABEL_W_MIN))
        label_w = int(min(max_name_px, _LABEL_W_MAX)) + 16

        chart_w = max(width - label_w - 4, 1)
        needed_h = _PAD_TOP + len(seen) * _ROW_H + _PAD_BOT
        self.set_content_height(max(needed_h, 140))

        layout = compute_timeline_layout(
            self._events,
            chart_w=float(chart_w),
            show_gaps=self._show_gaps,
        )
        lanes = layout["lanes"]
        t0 = layout["t0"]
        active_lanes = [l for l in lanes if l["kind"] == "active"]
        gap_lanes = [l for l in lanes if l["kind"] == "gap"]

        # Background.
        cr.set_source_rgb(*c_bg)
        cr.paint()

        fn_first_event: dict[str, dict] = {}
        for e in self._events:
            if e["function"] not in fn_first_event:
                fn_first_event[e["function"]] = e

        # Alternating row backgrounds and function labels.
        for fn, row in seen.items():
            y = _PAD_TOP + row * _ROW_H
            if row % 2 == 0:
                cr.set_source_rgb(*c_row_alt)
                cr.rectangle(0, y, width, _ROW_H)
                cr.fill()
            avail_w = label_w - 8
            if cr.text_extents(fn)[2] <= avail_w:
                label = fn
            else:
                max_chars = max(1, int((avail_w - cr.text_extents("…")[2]) / char_w))
                label = fn[:max_chars] + "…"
            dimmed = self._is_dimmed(fn)
            r, g, b = c_text
            cr.set_source_rgba(r, g, b, 0.30 if dimmed else 0.95)
            cr.move_to(4, y + _ROW_H - 5)
            cr.show_text(label)
            self._bar_rects.append((0.0, float(y + 4), float(label_w), float(_ROW_H - 8), fn_first_event[fn]))

        # Event bars — split across active lanes.
        for e in self._events:
            row = seen[e["function"]]
            by = _PAD_TOP + row * _ROW_H + 4
            r, g, b = desaturate_color(*DEPTH_COLORS[e.get("depth", 0) % len(DEPTH_COLORS)])
            is_dimmed = self._is_dimmed(e["function"])
            alpha = 0.22 if is_dimmed else 0.85
            bar_h = _ROW_H - 8
            for lane in active_lanes:
                if e["end"] <= lane["s"] or e["start"] >= lane["e"]:
                    continue
                seg_dur = lane["e"] - lane["s"]
                if seg_dur <= 0 or lane["w"] <= 0:
                    continue
                piece_s = max(e["start"], lane["s"])
                piece_e = min(e["end"], lane["e"])
                bx = label_w + lane["x"] + (piece_s - lane["s"]) / seg_dur * lane["w"]
                bw = max((piece_e - piece_s) / seg_dur * lane["w"], 2.0)
                rounded_rect(cr, bx, by, bw, bar_h)
                cr.set_source_rgba(r, g, b, alpha)
                cr.fill_preserve()
                if not is_dimmed:
                    cr.set_source_rgba(r * 0.6, g * 0.6, b * 0.6, 0.5)
                    cr.set_line_width(0.5)
                    cr.stroke()
                else:
                    cr.new_path()
                if (self._hovered_event is not None
                        and e["function"] == self._hovered_event["function"]):
                    rounded_rect(cr, bx, by, bw, bar_h)
                    c_hi = (1.0, 1.0, 1.0) if dark else (0.05, 0.05, 0.05)
                    cr.set_source_rgba(*c_hi, 0.9)
                    cr.set_line_width(1.5)
                    cr.stroke()
                self._bar_rects.append((bx, by, bw, bar_h, e))

        # Gap-break columns (drawn on top of bars).
        for lane in gap_lanes:
            if lane["w"] <= 0:
                continue
            draw_gap_break(
                cr, label_w + lane["x"], _PAD_TOP,
                lane["w"], needed_h - _PAD_TOP - _PAD_BOT,
                lane["e"] - lane["s"], dark,
            )

        # Time axis: solid baseline per active lane + tick marks + dashed guides.
        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)
        for lane in active_lanes:
            x0 = label_w + lane["x"]
            cr.set_source_rgb(*c_tick)
            cr.set_line_width(0.75)
            cr.set_dash([])
            cr.move_to(x0, _PAD_TOP - 2)
            cr.line_to(x0 + lane["w"], _PAD_TOP - 2)
            cr.stroke()
            for frac, t_real in ((0.0, lane["s"]), (1.0, lane["e"])):
                x = x0 + frac * lane["w"]
                t_ms = (t_real - t0) * 1000.0
                label = f"{t_ms:.0f}ms"
                ext = cr.text_extents(label)
                lx = x + 2 if frac == 0.0 else x - ext[2] - 2
                cr.set_source_rgb(*c_tick)
                cr.set_line_width(0.75)
                cr.set_dash([])
                cr.move_to(x, _PAD_TOP - 7)
                cr.line_to(x, _PAD_TOP - 2)
                cr.stroke()
                cr.move_to(lx, _PAD_TOP - 9)
                cr.show_text(label)
                cr.set_source_rgba(*c_tick, 0.4)
                cr.set_line_width(0.4)
                cr.set_dash([2, 4])
                cr.move_to(x, _PAD_TOP)
                cr.line_to(x, needed_h - _PAD_BOT)
                cr.stroke()
        cr.set_dash([])

    # ── Interaction ──────────────────────────────────────────────────────

    def _is_dimmed(self, fn: str) -> bool:
        if self._filter_text and self._filter_text not in fn.lower():
            return True
        if self._selected_fn is not None and self._selected_fn != fn:
            return True
        return False

    def _hit_test(self, x: float, y: float) -> tuple[dict[str, Any], float] | None:
        for bx, by, bw, bh, e in self._bar_rects:
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return e, by + bh
        return None

    def _on_motion(self, _ctrl: Gtk.EventControllerMotion, x: float, y: float) -> None:
        hit = self._hit_test(x, y)
        if hit is None:
            if self._hovered_event is not None:
                self._hovered_event = None
                self.queue_draw()
            self._tooltip.hide()
            return
        e, bar_y = hit
        if e is self._hovered_event:
            self._tooltip.update_position(x, bar_y)
            return
        self._hovered_event = e
        self.queue_draw()
        dur_ms = (e["end"] - e["start"]) * 1000.0
        t0 = min((ev["start"] for ev in self._events), default=0.0)
        self._tooltip.show_at(
            x,
            bar_y,
            e["function"],
            [
                ("Duration", format_ms(dur_ms)),
                ("Depth", str(e.get("depth", 0))),
                ("Start", format_ms((e["start"] - t0) * 1000.0)),
                ("End", format_ms((e["end"] - t0) * 1000.0)),
            ],
        )

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        if self._hovered_event is not None:
            self._hovered_event = None
            self.queue_draw()
        self._tooltip.hide_immediate()

    def _on_click(self, _ctrl: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        hit = self._hit_test(x, y)
        if hit is None:
            return
        e, _ = hit
        fn = e["function"]
        new = "" if fn == self._selected_fn else fn
        self.emit("function-selected", new)
