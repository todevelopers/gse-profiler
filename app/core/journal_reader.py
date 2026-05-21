import json
import logging
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

_log = logging.getLogger(__name__)

# Detect Flatpak sandbox at import time — /.flatpak-info is created by the runtime.
_IN_FLATPAK: bool = os.path.exists("/.flatpak-info")


def _journalctl_prefix() -> list[str]:
    """Return the command prefix for invoking journalctl.

    Inside a Flatpak sandbox journalctl is not available directly, so we
    delegate to flatpak-spawn which runs the command on the host.
    """
    if _IN_FLATPAK:
        return ["flatpak-spawn", "--host", "journalctl"]
    return ["journalctl"]


PRIORITY_NAMES: dict[int, str] = {
    0: "EMERG",
    1: "ALERT",
    2: "CRIT",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}

# Flags that JournalReader controls internally — strip from user command strings
_OWNED_FLAGS = frozenset({"--follow", "-f", "--no-pager", "--output", "-o", "--lines", "-n"})
_OWNED_PREFIXES = ("--output=", "--lines=", "--after-cursor=")


def parse_extra_args(cmd_str: str) -> list[str]:
    """Extract pass-through journalctl args from a user-supplied command string.

    Strips 'journalctl' and flags owned by JournalReader (--follow/-f,
    --output/-o, --lines/-n, --after-cursor, --no-pager).
    Everything else (e.g. --user, -t, -u, --boot) is kept and forwarded.
    """
    try:
        parts = shlex.split(cmd_str)
    except ValueError:
        return []

    if parts and parts[0].split("/")[-1] == "journalctl":
        parts = parts[1:]

    result: list[str] = []
    skip_next = False
    for part in parts:
        if skip_next:
            skip_next = False
            continue
        if part in _OWNED_FLAGS:
            if part in ("--output", "-o", "--lines", "-n"):
                skip_next = True
            continue
        if any(part.startswith(p) for p in _OWNED_PREFIXES):
            continue
        result.append(part)

    return result


@dataclass
class LogEntry:
    timestamp: datetime
    priority: int
    priority_name: str
    identifier: str
    message: str
    raw: dict[str, Any]


class JournalReader(GObject.Object):
    """Polling journalctl reader using --after-cursor.

    Instead of --follow (which suffers from pipe-buffering issues), each poll
    spawns a short-lived journalctl process that exits cleanly and flushes all
    output. The cursor from the last seen entry is passed to the next invocation
    via --after-cursor so no entries are missed or duplicated.
    """

    __gtype_name__ = "JournalReader"

    __gsignals__ = {
        "log-entry": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._cursor: str | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._extra_args: list[str] = []
        # Generation counter lets idle callbacks discard stale batches after
        # stop+start without needing a join on the main thread.
        self._generation = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, extra_args: list[str] | None = None) -> None:
        if self._running:
            return
        self._extra_args = extra_args or []
        self._cursor = None
        self._generation += 1
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        _log.info("JournalReader started (polling, extra=%s)", self._extra_args)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        # Do not join here — avoids freezing the GTK main loop.
        # The thread is daemon=True and will exit within ≤ 1 second on its own.
        self._thread = None
        _log.info("JournalReader stop requested")

    # ── Poll loop (background thread) ─────────────────────────────────────────

    def _poll_loop(self) -> None:
        first = True
        gen = self._generation
        while not self._stop_event.is_set():
            self._do_poll(gen=gen, initial=first)
            first = False
            self._stop_event.wait(timeout=1.0)

    def _do_poll(self, gen: int, initial: bool = False) -> None:
        base = _journalctl_prefix()
        if self._cursor is None:
            cmd = base + ["--no-pager", "-o", "json", "-n", "200"] + self._extra_args
        else:
            cmd = base + [
                "--no-pager", "-o", "json",
                f"--after-cursor={self._cursor}",
            ] + self._extra_args

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            _log.warning("journalctl poll timed out")
            return
        except OSError as exc:
            _log.error("journalctl spawn failed: %s", exc)
            return

        entries: list[LogEntry] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            entry = self._parse_line(line)
            if entry is not None:
                cursor = entry.raw.get("__CURSOR")
                if cursor:
                    self._cursor = cursor
                entries.append(entry)

        if entries:
            GLib.idle_add(self._emit_batch, entries, gen)

    def _emit_batch(self, entries: list[LogEntry], gen: int) -> bool:
        # Discard if reader was stopped or restarted since this poll ran.
        if self._running and gen == self._generation:
            for entry in entries:
                self.emit("log-entry", entry)
        return bool(GLib.SOURCE_REMOVE)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_line(self, line: str) -> "LogEntry | None":
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        ts_raw = data.get("__REALTIME_TIMESTAMP", "0")
        try:
            timestamp = datetime.fromtimestamp(int(ts_raw) / 1_000_000)
        except (ValueError, OSError):
            timestamp = datetime.now()

        prio_raw = data.get("PRIORITY", "6")
        try:
            priority = max(0, min(7, int(prio_raw)))
        except (ValueError, TypeError):
            priority = 6

        return LogEntry(
            timestamp=timestamp,
            priority=priority,
            priority_name=PRIORITY_NAMES.get(priority, "INFO"),
            identifier=str(data.get("SYSLOG_IDENTIFIER", "")),
            message=str(data.get("MESSAGE", "")),
            raw=data,
        )
