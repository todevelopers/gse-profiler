import logging
import re

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, GObject, Gtk

from app.core.dbus_client import DBusClient
from app.core.journal_reader import JournalReader, LogEntry

_log = logging.getLogger(__name__)

MAX_ENTRIES = 5000

# Priority threshold for each level filter option.
# "Show entries at this level and above" = priority <= threshold.
_LEVEL_OPTIONS: list[tuple[str, int | None]] = [
    ("All Levels", None),
    ("DEBUG", 7),
    ("INFO", 6),
    ("WARNING", 4),
    ("ERROR", 3),
    ("CRITICAL", 2),
]

_LEVEL_NAMES = [label for label, _ in _LEVEL_OPTIONS]
_LEVEL_THRESHOLDS = {label: threshold for label, threshold in _LEVEL_OPTIONS}

# GtkTextBuffer tag names per priority range
_PRIORITY_TAG: dict[int, str] = {
    7: "tag-debug",
    6: "tag-info",
    5: "tag-info",   # NOTICE → INFO display
    4: "tag-warning",
    3: "tag-error",
    2: "tag-error",
    1: "tag-error",
    0: "tag-error",
}

# Parses GJS log() format: optional "JS LOG: " prefix, then [tag] body
_MSG_TAG_RE = re.compile(r'^(?:JS LOG:\s*)?\[([^\]]+)\]\s*(.*)', re.DOTALL)


def _extract_log_tag(message: str) -> tuple[str | None, str]:
    """Return (tag, body) if message starts with [tag], else (None, message)."""
    m = _MSG_TAG_RE.match(message)
    if m:
        return m.group(1), m.group(2)
    return None, message


class LogViewerView(Gtk.Box):
    """Live journalctl log viewer with filtering and toolbar actions."""

    def __init__(self, dbus_client: DBusClient) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._dbus = dbus_client
        self._reader = JournalReader()
        self._entries: list[LogEntry] = []

        # Filter state
        self._uuid_filter: str | None = None
        self._ext_uuids: list[str] = []
        self._level_threshold: int | None = None
        self._search_text = ""
        self._auto_scroll = True
        self._skip_filter_update = False

        self._build_ui()
        self._setup_tags()

        dbus_client.connect("extensions-changed", self._on_extensions_changed)
        self._reader.connect("log-entry", self._on_log_entry)
        self._reader.start()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Filter bar ──────────────────────────────────────────────────────
        self._uuid_list = Gtk.StringList.new(["All Extensions"])
        self._uuid_dropdown = Gtk.DropDown.new(self._uuid_list, None)
        self._uuid_dropdown.set_tooltip_text("Filter by extension UUID")
        self._uuid_handler = self._uuid_dropdown.connect(
            "notify::selected", self._on_uuid_changed
        )

        level_list = Gtk.StringList.new(_LEVEL_NAMES)
        self._level_dropdown = Gtk.DropDown.new(level_list, None)
        self._level_dropdown.set_tooltip_text("Minimum log level to display")
        self._level_dropdown.connect("notify::selected", self._on_level_changed)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_hexpand(True)
        self._search_entry.set_placeholder_text("Search logs…")
        self._search_entry.connect("search-changed", self._on_search_changed)

        self._auto_scroll_btn = Gtk.ToggleButton()
        self._auto_scroll_btn.set_icon_name("go-bottom-symbolic")
        self._auto_scroll_btn.set_tooltip_text("Auto-scroll to bottom")
        self._auto_scroll_btn.set_active(True)
        self._auto_scroll_btn.connect("toggled", self._on_auto_scroll_toggled)

        clear_btn = Gtk.Button(icon_name="edit-clear-all-symbolic")
        clear_btn.add_css_class("flat")
        clear_btn.set_tooltip_text("Clear log")
        clear_btn.connect("clicked", self._on_clear)

        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.add_css_class("flat")
        copy_btn.set_tooltip_text("Copy selected text")
        copy_btn.connect("clicked", self._on_copy)

        export_btn = Gtk.Button(icon_name="document-save-symbolic")
        export_btn.add_css_class("flat")
        export_btn.set_tooltip_text("Export visible log to .txt")
        export_btn.connect("clicked", self._on_export)

        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_bar.set_margin_start(6)
        filter_bar.set_margin_end(6)
        filter_bar.set_margin_top(6)
        filter_bar.set_margin_bottom(6)
        filter_bar.append(self._uuid_dropdown)
        filter_bar.append(self._level_dropdown)
        filter_bar.append(self._search_entry)
        filter_bar.append(self._auto_scroll_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        filter_bar.append(sep)
        filter_bar.append(copy_btn)
        filter_bar.append(export_btn)
        filter_bar.append(clear_btn)

        # ── Text view ───────────────────────────────────────────────────────
        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_monospace(True)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_vexpand(True)
        self._text_view.set_hexpand(True)
        self._text_view.add_css_class("log-view")

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(self._text_view)
        vadj = self._scroll.get_vadjustment()
        vadj.connect("changed", self._on_scroll_adjusted)

        self.append(filter_bar)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.append(self._scroll)

    def _setup_tags(self) -> None:
        buf = self._text_view.get_buffer()
        buf.create_tag("tag-error", foreground="#E01B24")
        buf.create_tag("tag-warning", foreground="#E5A50A")
        buf.create_tag("tag-info")
        buf.create_tag("tag-debug", foreground="#888888")
        # Created last so it has highest priority for background rendering
        buf.create_tag("tag-search", background="#F6D32D", foreground="#000000")

    # ── Signal handlers — filters ──────────────────────────────────────────

    def _on_extensions_changed(self, _dbus: DBusClient, extensions: dict) -> None:
        self._skip_filter_update = True
        current_uuid = self._uuid_filter
        uuids = sorted(extensions.keys())
        names = [extensions[u].get("name") or u for u in uuids]
        self._ext_uuids = uuids
        items = ["All Extensions"] + names
        self._uuid_list.splice(0, self._uuid_list.get_n_items(), items)
        if current_uuid and current_uuid in self._ext_uuids:
            self._uuid_dropdown.set_selected(self._ext_uuids.index(current_uuid) + 1)
        else:
            self._uuid_dropdown.set_selected(0)
            self._uuid_filter = None
        self._skip_filter_update = False
        self._rebuild_buffer()

    def _on_uuid_changed(self, dropdown: Gtk.DropDown, _pspec: GObject.ParamSpec) -> None:
        if self._skip_filter_update:
            return
        idx = dropdown.get_selected()
        if idx == 0 or idx == Gtk.INVALID_LIST_POSITION:
            self._uuid_filter = None
        else:
            uuid_idx = idx - 1
            self._uuid_filter = self._ext_uuids[uuid_idx] if 0 <= uuid_idx < len(self._ext_uuids) else None
        self._rebuild_buffer()

    def _on_level_changed(self, dropdown: Gtk.DropDown, _pspec: GObject.ParamSpec) -> None:
        item = dropdown.get_selected_item()
        label = item.get_string() if item else "All Levels"
        self._level_threshold = _LEVEL_THRESHOLDS.get(label)
        self._rebuild_buffer()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_text = entry.get_text()
        self._rebuild_buffer()

    def _on_auto_scroll_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._auto_scroll = btn.get_active()
        if self._auto_scroll:
            self._scroll_to_end()

    # ── Signal handlers — toolbar ──────────────────────────────────────────

    def _on_clear(self, _btn: Gtk.Button) -> None:
        self._entries.clear()
        self._text_view.get_buffer().set_text("")

    def _on_copy(self, _btn: Gtk.Button) -> None:
        self._text_view.emit("copy-clipboard")

    def _on_export(self, _btn: Gtk.Button) -> None:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        if self._uuid_filter:
            # Strip domain suffix for brevity: "my-ext@example.com" → "my-ext"
            short = self._uuid_filter.split("@")[0]
            filename = f"gse-log_{short}_{ts}.txt"
        else:
            filename = f"gse-log_{ts}.txt"

        dialog = Gtk.FileDialog()
        dialog.set_title("Export Log")
        dialog.set_initial_name(filename)
        dialog.save(self.get_root(), None, self._on_export_save, None)  # type: ignore[arg-type]

    def _on_export_save(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        _user_data: None,
    ) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return
        buf = self._text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        gfile.replace_contents_bytes_async(
            GLib.Bytes.new(text.encode("utf-8")),
            None,
            False,
            Gio.FileCreateFlags.REPLACE_DESTINATION,
            None,
            self._on_file_written,
            None,
        )

    def _on_file_written(
        self,
        gfile: Gio.File,
        result: Gio.AsyncResult,
        _user_data: None,
    ) -> None:
        try:
            gfile.replace_contents_finish(result)
        except GLib.Error as exc:
            _log.error("Log export failed: %s", exc)

    # ── Journal entry handling ─────────────────────────────────────────────

    def _on_log_entry(self, _reader: JournalReader, entry: LogEntry) -> None:
        if len(self._entries) >= MAX_ENTRIES:
            self._entries.pop(0)
        self._entries.append(entry)

        if self._entry_matches(entry):
            self._append_to_buffer(entry)
            if self._auto_scroll:
                self._scroll_to_end()

    def _entry_matches(self, entry: LogEntry) -> bool:
        if self._level_threshold is not None and entry.priority > self._level_threshold:
            return False
        if self._uuid_filter:
            # Match only messages with [short-name] bracket tag to exclude gnome-shell
            # system messages that mention the UUID without a bracket prefix.
            short = self._uuid_filter.split("@")[0]
            if f"[{short}]" not in entry.message:
                return False
        if self._search_text and self._search_text.lower() not in entry.message.lower():
            return False
        return True

    # ── Buffer management ──────────────────────────────────────────────────

    def _rebuild_buffer(self) -> None:
        buf = self._text_view.get_buffer()
        buf.set_text("")
        for entry in self._entries:
            if self._entry_matches(entry):
                self._append_to_buffer(entry)
        self._apply_search_highlight()
        if self._auto_scroll:
            self._scroll_to_end()

    def _append_to_buffer(self, entry: LogEntry) -> None:
        buf = self._text_view.get_buffer()
        tag, body = _extract_log_tag(entry.message)
        identifier = tag if tag else entry.identifier
        line = (
            f"{entry.timestamp.strftime('%H:%M:%S')} "
            f"[{entry.priority_name:<7}] "
            f"[{identifier}] "
            f"{body}\n"
        )
        tag_name = _PRIORITY_TAG.get(entry.priority, "tag-info")
        end = buf.get_end_iter()
        mark_start = buf.get_char_count()
        buf.insert(end, line)
        # Re-acquire iters after modification
        start_iter = buf.get_iter_at_offset(mark_start)
        end_iter = buf.get_end_iter()
        buf.apply_tag_by_name(tag_name, start_iter, end_iter)

        if self._search_text:
            self._highlight_in_range(start_iter, end_iter)

    def _apply_search_highlight(self) -> None:
        buf = self._text_view.get_buffer()
        buf.remove_tag_by_name("tag-search", buf.get_start_iter(), buf.get_end_iter())
        if not self._search_text:
            return
        self._highlight_in_range(buf.get_start_iter(), buf.get_end_iter())

    def _highlight_in_range(
        self, range_start: Gtk.TextIter, range_end: Gtk.TextIter
    ) -> None:
        buf = self._text_view.get_buffer()
        search = self._search_text
        it = range_start.copy()
        while True:
            found, match_start, match_end = it.forward_search(
                search,
                Gtk.TextSearchFlags.CASE_INSENSITIVE | Gtk.TextSearchFlags.TEXT_ONLY,
                range_end,
            )
            if not found:
                break
            buf.apply_tag_by_name("tag-search", match_start, match_end)
            it = match_end

    # ── Scroll helpers ─────────────────────────────────────────────────────

    def _scroll_to_end(self) -> None:
        buf = self._text_view.get_buffer()
        end = buf.get_end_iter()
        self._text_view.scroll_to_iter(end, 0.0, False, 0.0, 1.0)

    def _on_scroll_adjusted(self, adj: Gtk.Adjustment) -> None:
        if self._auto_scroll:
            GLib.idle_add(self._do_scroll_to_end)

    def _do_scroll_to_end(self) -> bool:
        self._scroll_to_end()
        return False
