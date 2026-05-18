"""Profiler timeline views — shared constants, geometry helpers, tooltip popover.

Each timeline mode (Flamegraph / Swimlane / Histogram) is a `Gtk.DrawingArea`
subclass living in its own module. They share the depth-colour palette, the
gap-segment computation used by the Swimlane, and a single `TooltipPopover`
helper that wraps a `Gtk.Popover` for hover detail labels.
"""

import math
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

# Bar colours per call depth (RGB, cycled).
DEPTH_COLORS: list[tuple[float, float, float]] = [
    (0.21, 0.52, 0.89),  # blue
    (0.18, 0.69, 0.41),  # green
    (0.93, 0.36, 0.00),  # orange
    (0.57, 0.25, 0.67),  # purple
    (0.13, 0.56, 0.64),  # teal
    (0.84, 0.38, 0.60),  # pink
    (0.78, 0.53, 0.04),  # yellow
]

# Idle periods longer than this collapse into a visual break on the timeline.
GAP_THRESHOLD_S = 0.05  # 50 ms — collapse all gaps larger than this
# Pixel width bounds for the collapsed-gap break column (log-scale).
GAP_BREAK_PX_MIN = 14
GAP_BREAK_PX_MAX = 60
GAP_BREAK_PX_BASE = 20


def desaturate_color(
    r: float, g: float, b: float, amount: float = 0.28
) -> tuple[float, float, float]:
    """Mix an RGB color toward its perceived gray by *amount* (0–1).

    Preserves hue while reducing chroma so saturated palette colors don't
    appear over-vivid against dark backgrounds.
    """
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    return (
        r + (gray - r) * amount,
        g + (gray - g) * amount,
        b + (gray - b) * amount,
    )


def rounded_rect(cr: Any, x: float, y: float, w: float, h: float, r: float = 4.0) -> None:
    """Draw a rounded-rectangle path (does not fill or stroke — caller decides)."""
    r = min(r, w / 2.0, h / 2.0)
    cr.new_path()
    cr.move_to(x + r, y)
    cr.line_to(x + w - r, y)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.line_to(x + w, y + h - r)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.line_to(x + r, y + h)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.line_to(x, y + r)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def visible_segments(
    events: list[dict[str, Any]],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Active-time segments and the collapsed idle gaps between them.

    Returns ``(active_segments, collapsed_gaps)`` where each element is a list
    of ``(start, end)`` pairs. Iterates events in start-order, tracking the
    running max end-time seen so far. A segment closes when the next event's
    start is more than ``GAP_THRESHOLD_S`` past that max — this correctly
    handles long-running parents whose end-time follows several shorter
    children in start-order.
    """
    if not events:
        return [], []
    ordered = sorted(events, key=lambda e: e["start"])
    segments: list[tuple[float, float]] = []
    gaps: list[tuple[float, float]] = []
    seg_start = ordered[0]["start"]
    running_end = ordered[0]["end"]
    for e in ordered[1:]:
        if e["start"] - running_end > GAP_THRESHOLD_S:
            segments.append((seg_start, running_end))
            gaps.append((running_end, e["start"]))
            seg_start = e["start"]
            running_end = e["end"]
        else:
            if e["end"] > running_end:
                running_end = e["end"]
    segments.append((seg_start, running_end))
    return segments, gaps


def format_gap(seconds: float) -> str:
    if seconds < 1.0:
        return f"+{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"+{seconds:.1f}s"
    return f"+{seconds / 60:.1f}m"


def format_ms(v: float) -> str:
    """Compact ms formatter — switches to seconds above 1000 ms."""
    if v >= 1000.0:
        return f"{v / 1000.0:.2f} s"
    if v >= 1.0:
        return f"{v:.2f} ms"
    return f"{v:.3f} ms"


def gap_break_px(gap_duration_s: float, show_gaps: bool = True) -> float:
    """Width of a gap-break column in pixels (log-scale).

    ``show_gaps=False`` returns 0 so segments snap together.
    ``show_gaps=True`` scales logarithmically between GAP_BREAK_PX_MIN and MAX.
    """
    if not show_gaps:
        return 0.0
    ms = gap_duration_s * 1000.0
    w = GAP_BREAK_PX_MIN + math.log10(1.0 + ms / 50.0) * 14.0
    return max(GAP_BREAK_PX_MIN, min(GAP_BREAK_PX_MAX, w))


def compute_timeline_layout(
    events: list[dict[str, Any]],
    chart_w: float,
    show_gaps: bool = True,
) -> dict[str, Any]:
    """Compute display-space lane layout for Flamegraph and Swimlane.

    Returns a dict with:
    ``lanes``           — list of dicts: {kind: 'active'|'gap', s, e, x, w}
    ``t0``, ``t1``, ``span``
    ``x_for(t)``        — maps wall-clock time → x-offset within the chart area
    ``saved_s``         — total seconds collapsed into gap breaks
    ``collapsed_count`` — number of gaps
    """
    if not events:
        return {
            "lanes": [], "t0": 0.0, "t1": 0.0, "span": 0.0,
            "x_for": lambda t: 0.0, "saved_s": 0.0, "collapsed_count": 0,
        }

    t0 = min(e["start"] for e in events)
    t1 = max(e["end"] for e in events)
    span = (t1 - t0) or 1e-9
    segments, gaps = visible_segments(events)
    gap_px_list = [gap_break_px(g[1] - g[0], show_gaps) for g in gaps]
    total_gap_px = sum(gap_px_list)
    total_active_px = max(chart_w - total_gap_px, 100.0)
    total_active_s = sum(e - s for s, e in segments) or 1e-9

    lanes: list[dict[str, Any]] = []
    cursor = 0.0
    for i, (seg_s, seg_e) in enumerate(segments):
        seg_w = (seg_e - seg_s) / total_active_s * total_active_px
        lanes.append({"kind": "active", "s": seg_s, "e": seg_e, "x": cursor, "w": seg_w})
        cursor += seg_w
        if i < len(gaps):
            g_s, g_e = gaps[i]
            g_w = gap_px_list[i]
            lanes.append({"kind": "gap", "s": g_s, "e": g_e, "x": cursor, "w": g_w})
            cursor += g_w

    def x_for(t: float) -> float:
        for lane in lanes:
            if lane["s"] <= t <= lane["e"]:
                if lane["kind"] == "active":
                    frac = (t - lane["s"]) / max(lane["e"] - lane["s"], 1e-9)
                    return float(lane["x"]) + frac * float(lane["w"])
                return float(lane["x"]) + float(lane["w"]) / 2.0
        return 0.0 if t < t0 else cursor

    saved_s = sum(g[1] - g[0] for g in gaps)
    return {
        "lanes": lanes, "t0": t0, "t1": t1, "span": span,
        "x_for": x_for, "saved_s": saved_s, "collapsed_count": len(gaps),
    }


def draw_gap_break(
    cr: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    gap_s: float,
    dark: bool,
) -> None:
    """Draw a gap-break column: hatched background, dashed edges, zigzag, label."""
    cr.save()

    # Background fill.
    cr.set_source_rgba(0.5, 0.5, 0.5, 0.06 if dark else 0.04)
    cr.rectangle(x, y, w, h)
    cr.fill()

    # Diagonal hatching (clipped to column).
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    stripe_color = (0.9, 0.9, 0.9, 0.14) if dark else (0.1, 0.1, 0.1, 0.12)
    cr.set_source_rgba(*stripe_color)
    cr.set_line_width(1.0)
    spacing = 5.0
    for offset in range(-int(h), int(w + h), int(spacing)):
        cr.move_to(x + offset, y)
        cr.line_to(x + offset + h, y + h)
    cr.stroke()
    cr.restore()

    # Dashed vertical edges.
    cr.set_source_rgba(0.5, 0.5, 0.5, 0.22)
    cr.set_line_width(1.0)
    cr.set_dash([3.0, 3.0])
    for ex in (x + 0.5, x + w - 0.5):
        cr.move_to(ex, y)
        cr.line_to(ex, y + h)
        cr.stroke()
    cr.set_dash([])

    # Zigzag (torn-axis) in the vertical centre.
    if w >= 12:
        mid_y = y + h / 2.0
        amp = 2.5
        steps = max(4, int((w - 2) / 4))
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.40)
        cr.set_line_width(1.2)
        cr.move_to(x + 1, mid_y)
        for i in range(1, steps + 1):
            px = x + 1 + (i / steps) * (w - 2)
            py = mid_y + (amp if i % 2 == 0 else -amp)
            cr.line_to(px, py)
        cr.line_to(x + w - 1, mid_y)
        cr.stroke()

    # Duration label with pill background (only when the column is wide enough).
    if w >= 36:
        dur = gap_s
        if dur < 1.0:
            lbl = f"+{dur * 1000:.0f}ms"
        elif dur < 60.0:
            lbl = f"+{dur:.2f}s"
        else:
            lbl = f"+{dur / 60:.1f}m"
        cr.set_font_size(9)
        ext = cr.text_extents(lbl)
        lx = x + (w - ext[2]) / 2
        ly = y + h / 2 + 3
        pad = 4
        cr.set_source_rgba(
            0.10 if dark else 0.95,
            0.10 if dark else 0.95,
            0.10 if dark else 0.95,
            0.85,
        )
        rounded_rect(cr, lx - pad, ly - 10, ext[2] + pad * 2, 13, r=4.0)
        cr.fill()
        if dark:
            cr.set_source_rgba(0.7, 0.7, 0.7, 0.9)
        else:
            cr.set_source_rgba(0.3, 0.3, 0.3, 0.9)
        cr.move_to(lx, ly)
        cr.show_text(lbl)

    cr.restore()


class TooltipPopover:
    """Reusable Gtk.Popover for hover details on a timeline widget.

    The popover is anchored to the host drawing area via a 1×1 pointing-rect
    that the caller updates each motion event. Content is built once and
    refreshed in-place to avoid widget churn on every cursor move.
    """

    def __init__(self, parent: Gtk.Widget) -> None:
        self._pop = Gtk.Popover()
        self._pop.set_parent(parent)
        self._pop.set_autohide(False)
        self._pop.set_has_arrow(False)
        self._pop.set_can_target(False)
        self._pop.set_position(Gtk.PositionType.BOTTOM)
        self._pop.add_css_class("prof-tooltip")
        self._hide_timeout: int = 0

        self._title = Gtk.Label(xalign=0.0)
        self._title.add_css_class("prof-tooltip-fn")

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.append(self._title)
        box.append(self._rows_box)
        self._pop.set_child(box)

        self._row_cache: list[tuple[Gtk.Label, Gtk.Label]] = []

    def _ensure_rows(self, n: int) -> None:
        while len(self._row_cache) < n:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            lk = Gtk.Label(xalign=0.0)
            lk.add_css_class("prof-tooltip-key")
            lv = Gtk.Label(xalign=1.0)
            lv.set_hexpand(True)
            lv.set_ellipsize(Pango.EllipsizeMode.END)
            lv.add_css_class("prof-tooltip-val")
            row.append(lk)
            row.append(lv)
            self._rows_box.append(row)
            self._row_cache.append((lk, lv))
        # Hide extras
        for i, (lk, lv) in enumerate(self._row_cache):
            visible = i < n
            lk.get_parent().set_visible(visible)

    def _set_pointing_rect(self, x: float, y: float) -> None:
        rect = self._pop.get_pointing_to()[1]
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._pop.set_pointing_to(rect)

    def update_position(self, x: float, y: float) -> None:
        """Move only the horizontal anchor — Y is fixed per bar to keep popover above cursor."""
        rect = self._pop.get_pointing_to()[1]
        rect.x = int(x)
        self._pop.set_pointing_to(rect)

    def show_at(self, x: float, y: float, title: str, rows: list[tuple[str, str]]) -> None:
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
            self._hide_timeout = 0
        self._title.set_text(title)
        self._ensure_rows(len(rows))
        for (k, v), (lk, lv) in zip(rows, self._row_cache):
            lk.set_text(k)
            lv.set_text(v)
        self._set_pointing_rect(x, y)
        if not self._pop.is_visible():
            self._pop.popup()

    def hide(self) -> None:
        """Schedule hide after a short delay — absorbs brief boundary misses."""
        if self._pop.is_visible() and not self._hide_timeout:
            self._hide_timeout = GLib.timeout_add(80, self._do_hide)

    def hide_immediate(self) -> None:
        """Hide without delay — used when the cursor leaves the widget entirely."""
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
            self._hide_timeout = 0
        if self._pop.is_visible():
            self._pop.popdown()

    def _do_hide(self) -> bool:
        self._hide_timeout = 0
        self._pop.popdown()
        return False


__all__ = [
    "DEPTH_COLORS",
    "GAP_THRESHOLD_S",
    "GAP_BREAK_PX_MIN",
    "GAP_BREAK_PX_MAX",
    "GAP_BREAK_PX_BASE",
    "desaturate_color",
    "rounded_rect",
    "visible_segments",
    "gap_break_px",
    "compute_timeline_layout",
    "draw_gap_break",
    "format_gap",
    "format_ms",
    "TooltipPopover",
]
