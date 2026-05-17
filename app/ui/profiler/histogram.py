"""Histogram view — top-N functions ranked by exclusive (self) time.

Drives off aggregated `FunctionStat`-like objects rather than raw events.
Hot bars (>70% of the visible max) are coloured with the system error tint
so the worst offenders pop without needing a legend.
"""

from typing import Any, Protocol

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GObject, Gtk

from . import TooltipPopover, desaturate_color, format_ms

_PAD_LEFT = 170
_PAD_RIGHT = 100
_PAD_TOP = 22
_PAD_BOT = 22
_ROW_H = 22
_TOP_N = 18


class _StatLike(Protocol):
    name: str
    count: int
    total_ms: float
    self_ms: float
    max_ms: float

    @property
    def avg_ms(self) -> float: ...


class HistogramView(Gtk.DrawingArea):
    """Horizontal bar chart of top-N functions by ``self_ms``."""

    __gtype_name__ = "HistogramView"

    __gsignals__ = {
        "function-selected": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._stats: list[_StatLike] = []
        self._selected_fn: str | None = None
        self._filter_text: str = ""

        self._bar_rects: list[tuple[float, float, float, float, _StatLike]] = []
        self._hovered_stat: _StatLike | None = None

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

    def set_stats(self, stats: list[_StatLike]) -> None:
        self._stats = stats
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
            c_bar      = desaturate_color(0.21, 0.52, 0.89)
            c_hot      = desaturate_color(0.90, 0.18, 0.20)
        else:
            c_bg       = (1.00, 1.00, 1.00)
            c_row_alt  = (0.96, 0.96, 0.98)
            c_text     = (0.12, 0.12, 0.12)
            c_tick     = (0.35, 0.35, 0.35)
            c_bar      = desaturate_color(0.21, 0.52, 0.89)
            c_hot      = desaturate_color(0.85, 0.10, 0.15)

        self._bar_rects.clear()

        if not self._stats:
            cr.set_source_rgb(*c_bg)
            cr.paint()
            cr.set_source_rgb(*c_tick)
            cr.select_font_face("sans", 0, 0)
            cr.set_font_size(12)
            text = "No profiling data — start profiling to see the histogram"
            extents = cr.text_extents(text)
            cr.move_to((width - extents[2]) / 2, 60)
            cr.show_text(text)
            return

        # Sort by self time, take top N. We always render the full top-N
        # (filter only dims rows so the picture stays stable as you type).
        top = sorted(self._stats, key=lambda s: s.self_ms, reverse=True)[:_TOP_N]
        max_self = max((s.self_ms for s in top), default=1.0) or 1.0

        chart_w = max(width - _PAD_LEFT - _PAD_RIGHT, 200)
        needed_h = _PAD_TOP + len(top) * _ROW_H + _PAD_BOT
        self.set_content_height(max(needed_h, 140))

        # Background.
        cr.set_source_rgb(*c_bg)
        cr.paint()

        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(10)

        # X-axis tick marks (5 intervals).
        ticks = 5
        cr.set_source_rgb(*c_tick)
        cr.set_line_width(0.5)
        cr.set_dash([2, 4])
        for i in range(ticks + 1):
            v = (i / ticks) * max_self
            x = _PAD_LEFT + (v / max_self) * chart_w
            cr.move_to(x, _PAD_TOP - 2)
            cr.line_to(x, needed_h - _PAD_BOT)
            cr.stroke()
            label = f"{v:.1f} ms"
            cr.move_to(x + 3, _PAD_TOP - 6)
            cr.show_text(label)
        cr.set_dash([])

        # Rows.
        for i, s in enumerate(top):
            y = _PAD_TOP + i * _ROW_H
            if i % 2 == 1:
                cr.set_source_rgb(*c_row_alt)
                cr.rectangle(0, y, width, _ROW_H)
                cr.fill()

            dimmed = self._is_dimmed(s.name)

            # Function name label (right-aligned to PAD_LEFT - 8 like a "axis").
            label = s.name if len(s.name) <= 22 else f"…{s.name[-21:]}"
            r, g, b = c_text
            cr.set_source_rgba(r, g, b, 0.30 if dimmed else 0.88)
            ext = cr.text_extents(label)
            cr.move_to(_PAD_LEFT - 8 - ext[2], y + _ROW_H - 7)
            cr.show_text(label)

            # Bar.
            is_hot = s.self_ms > max_self * 0.7
            br, bg, bb = c_hot if is_hot else c_bar
            alpha = 0.30 if dimmed else 1.0
            w = max((s.self_ms / max_self) * chart_w, 2.0)
            bar_y = y + 5
            bar_h = _ROW_H - 10
            cr.set_source_rgba(br, bg, bb, alpha)
            cr.rectangle(_PAD_LEFT, bar_y, w, bar_h)
            cr.fill()
            self._bar_rects.append((_PAD_LEFT, bar_y, w, bar_h, s))

            # Trailing ms · count label.
            suffix = f"{format_ms(s.self_ms)} · {s.count}×"
            cr.set_source_rgba(r, g, b, 0.30 if dimmed else 0.68)
            cr.move_to(_PAD_LEFT + w + 6, y + _ROW_H - 7)
            cr.show_text(suffix)

    # ── Interaction ──────────────────────────────────────────────────────

    def _is_dimmed(self, fn: str) -> bool:
        if self._filter_text and self._filter_text not in fn.lower():
            return True
        if self._selected_fn is not None and self._selected_fn != fn:
            return True
        return False

    def _hit_test(self, x: float, y: float) -> tuple[_StatLike, float] | None:
        for bx, by, bw, bh, s in self._bar_rects:
            # Hit the full row width, not just the drawn bar — UX clarity.
            if by <= y <= by + bh and x >= bx:
                if x <= bx + max(bw, 6):
                    return s, by + bh * 0.5
        return None

    def _on_motion(self, _ctrl: Gtk.EventControllerMotion, x: float, y: float) -> None:
        hit = self._hit_test(x, y)
        if hit is None:
            self._hovered_stat = None
            self._tooltip.hide()
            return
        s, bar_y = hit
        if s is self._hovered_stat:
            self._tooltip.update_position(x, bar_y)
            return
        self._hovered_stat = s
        self._tooltip.show_at(
            x,
            bar_y,
            s.name,
            [
                ("Total", format_ms(s.total_ms)),
                ("Self", format_ms(s.self_ms)),
                ("Avg", format_ms(s.avg_ms)),
                ("Max", format_ms(s.max_ms)),
                ("Calls", str(s.count)),
            ],
        )

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        self._hovered_stat = None
        self._tooltip.hide_immediate()

    def _on_click(self, _ctrl: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        hit = self._hit_test(x, y)
        if hit is None:
            return
        s, _ = hit
        new = "" if s.name == self._selected_fn else s.name
        self.emit("function-selected", new)
