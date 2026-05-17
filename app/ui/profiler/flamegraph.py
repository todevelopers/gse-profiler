"""Flamegraph timeline view — bars stacked by call depth on an absolute time axis.

Top row is depth 0; each child call sits on the row below its parent. Unlike
the swimlane, no idle gaps are collapsed — the X axis is the full wall-clock
span of the profile so a quiet stretch shows up as empty canvas.
"""

from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from . import DEPTH_COLORS, TooltipPopover, desaturate_color, format_ms

_PAD_LEFT = 8
_PAD_RIGHT = 8
_PAD_TOP = 22
_PAD_BOT = 8
_ROW_H = 22


class FlamegraphView(Gtk.DrawingArea):
    """Stacked-depth flamegraph with full time axis."""

    __gtype_name__ = "FlamegraphView"

    __gsignals__ = {
        "function-selected": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self._selected_fn: str | None = None
        self._filter_text: str = ""

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

    # ── Public setters ───────────────────────────────────────────────────

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
            c_label    = (1.00, 1.00, 1.00)
        else:
            c_bg       = (1.00, 1.00, 1.00)
            c_row_alt  = (0.97, 0.97, 0.98)
            c_text     = (0.12, 0.12, 0.12)
            c_tick     = (0.35, 0.35, 0.35)
            c_label    = (1.00, 1.00, 1.00)

        self._bar_rects.clear()

        if not self._events:
            cr.set_source_rgb(*c_bg)
            cr.paint()
            cr.set_source_rgb(*c_tick)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(12)
            text = "No profiling data — start profiling to see the flamegraph"
            extents = cr.text_extents(text)
            cr.move_to((width - extents[2]) / 2, 60)
            cr.show_text(text)
            return

        t0 = min(e["start"] for e in self._events)
        t1 = max(e["end"] for e in self._events)
        span = (t1 - t0) or 1e-9
        max_depth = max(e.get("depth", 0) for e in self._events) + 1

        chart_w = max(width - _PAD_LEFT - _PAD_RIGHT, 200)
        needed_h = _PAD_TOP + max_depth * _ROW_H + _PAD_BOT
        self.set_content_height(max(needed_h, 140))

        def x_for(t: float) -> float:
            return _PAD_LEFT + (t - t0) / span * chart_w

        # Background.
        cr.set_source_rgb(*c_bg)
        cr.paint()

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)

        # Alternating row backgrounds.
        for d in range(max_depth):
            if d % 2 == 1:
                y = _PAD_TOP + d * _ROW_H
                cr.set_source_rgb(*c_row_alt)
                cr.rectangle(_PAD_LEFT, y, chart_w, _ROW_H)
                cr.fill()

        # Time-axis tick marks (6 intervals).
        ticks = 6
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(0.5)
        cr.set_dash([2, 4])
        for i in range(ticks + 1):
            t = t0 + (i / ticks) * span
            x = x_for(t)
            cr.move_to(x, _PAD_TOP - 2)
            cr.line_to(x, needed_h - _PAD_BOT)
            cr.stroke()
            label = f"{(t - t0) * 1000.0:.0f} ms"
            ext = cr.text_extents(label)
            lx = x + 3 if i < ticks else x - ext[2] - 3
            cr.move_to(lx, _PAD_TOP - 6)
            cr.show_text(label)
        cr.set_dash([])

        # Event bars.
        for e in self._events:
            depth = e.get("depth", 0)
            x = x_for(e["start"])
            w = max(x_for(e["end"]) - x, 1.5)
            y = _PAD_TOP + depth * _ROW_H + 3
            h = _ROW_H - 6

            r, g, b = desaturate_color(*DEPTH_COLORS[depth % len(DEPTH_COLORS)])
            alpha = 0.25 if self._is_dimmed(e["function"]) else 0.92
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(x, y, w, h)
            cr.fill()
            self._bar_rects.append((x, y, w, h, e))

            # Inline label when the bar is wide enough.
            if w > 60 and alpha > 0.5:
                fn = e["function"]
                max_chars = max(int(w / 7) - 1, 1)
                label = fn if len(fn) <= max_chars else fn[: max_chars - 1] + "…"
                cr.set_source_rgba(*c_label, 0.95)
                cr.move_to(x + 5, y + h - 6)
                cr.show_text(label)

    # ── Interaction ──────────────────────────────────────────────────────

    def _is_dimmed(self, fn: str) -> bool:
        if self._filter_text and self._filter_text not in fn.lower():
            return True
        if self._selected_fn is not None and self._selected_fn != fn:
            return True
        return False

    def _hit_test(self, x: float, y: float) -> dict[str, Any] | None:
        # Search from the end so the most recently-drawn (topmost) bar wins.
        for bx, by, bw, bh, e in reversed(self._bar_rects):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return e
        return None

    def _on_motion(self, _ctrl: Gtk.EventControllerMotion, x: float, y: float) -> None:
        e = self._hit_test(x, y)
        if e is None:
            if self._hovered_event is not None:
                self._hovered_event = None
                self._tooltip.hide()
            return
        if e is self._hovered_event:
            return
        self._hovered_event = e
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
        self._hovered_event = None
        self._tooltip.hide()

    def _on_click(self, _ctrl: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        e = self._hit_test(x, y)
        if e is None:
            return
        fn = e["function"]
        new = "" if fn == self._selected_fn else fn
        self.emit("function-selected", new)
