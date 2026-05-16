"""Profiler timeline views — shared constants, geometry helpers, tooltip popover.

Each timeline mode (Flamegraph / Swimlane / Histogram) is a `Gtk.DrawingArea`
subclass living in its own module. They share the depth-colour palette, the
gap-segment computation used by the Swimlane, and a single `TooltipPopover`
helper that wraps a `Gtk.Popover` for hover detail labels.
"""

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango

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
GAP_THRESHOLD_S = 2.0
# Pixel width of the collapsed-gap break drawn between segments.
GAP_BREAK_PX = 22


def visible_segments(events: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Active-time segments separated by collapsed idle gaps.

    Iterates events in start-order, tracking the running max end-time seen so
    far. A segment closes when the next event's start is more than
    ``GAP_THRESHOLD_S`` past that max — this correctly handles long-running
    parents whose end-time follows several shorter children in start-order.
    """
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e["start"])
    segments: list[tuple[float, float]] = []
    seg_start = ordered[0]["start"]
    running_end = ordered[0]["end"]
    for e in ordered[1:]:
        if e["start"] - running_end > GAP_THRESHOLD_S:
            segments.append((seg_start, running_end))
            seg_start = e["start"]
            running_end = e["end"]
        else:
            if e["end"] > running_end:
                running_end = e["end"]
    segments.append((seg_start, running_end))
    return segments


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
        self._pop.add_css_class("prof-tooltip")

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

    def show_at(self, x: float, y: float, title: str, rows: list[tuple[str, str]]) -> None:
        self._title.set_text(title)
        self._ensure_rows(len(rows))
        for (k, v), (lk, lv) in zip(rows, self._row_cache):
            lk.set_text(k)
            lv.set_text(v)
        rect = self._pop.get_pointing_to()[1]
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._pop.set_pointing_to(rect)
        if not self._pop.is_visible():
            self._pop.popup()

    def hide(self) -> None:
        if self._pop.is_visible():
            self._pop.popdown()


__all__ = [
    "DEPTH_COLORS",
    "GAP_THRESHOLD_S",
    "GAP_BREAK_PX",
    "visible_segments",
    "format_gap",
    "format_ms",
    "TooltipPopover",
]
