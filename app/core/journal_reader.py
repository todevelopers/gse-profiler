import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib, GObject

_log = logging.getLogger(__name__)

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


@dataclass
class LogEntry:
    timestamp: datetime
    priority: int
    priority_name: str
    identifier: str
    message: str
    raw: dict[str, Any]


class JournalReader(GObject.Object):
    """Async reader for journalctl --follow output.

    Spawns journalctl as a subprocess and emits a GObject signal per log entry.
    Filters to gjs and gnome-shell identifiers to capture extension-relevant logs.
    """

    __gtype_name__ = "JournalReader"

    __gsignals__ = {
        "log-entry": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._proc: Gio.Subprocess | None = None
        self._stream: Gio.DataInputStream | None = None
        self._cancellable: Gio.Cancellable | None = None
        self._running = False

    def start(self, uuid_filter: str | None = None) -> None:
        """Start tailing the journal, optionally filtered by extension UUID."""
        if self._running:
            return
        self._running = True

        cmd = [
            "journalctl",
            "--follow",
            "-o", "json",
            "-n", "200",
            "-t", "gnome-shell",
            "-t", "gjs",
        ]

        try:
            self._proc = Gio.Subprocess.new(
                cmd,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error as exc:
            _log.error("Failed to spawn journalctl: %s", exc)
            self._running = False
            return

        self._cancellable = Gio.Cancellable.new()
        stdout = self._proc.get_stdout_pipe()
        self._stream = Gio.DataInputStream.new(stdout)
        self._stream.set_buffer_size(65536)
        self._read_next_line()
        _log.info("JournalReader started")

    def stop(self) -> None:
        """Stop reading and terminate the journalctl subprocess."""
        self._running = False
        if self._cancellable:
            self._cancellable.cancel()
            self._cancellable = None
        if self._proc is not None:
            try:
                self._proc.force_exit()
            except Exception:
                pass
            self._proc = None
        self._stream = None
        _log.info("JournalReader stopped")

    # ── Private ───────────────────────────────────────────────────────────────

    def _read_next_line(self) -> None:
        if not self._running or self._stream is None:
            return
        self._stream.read_line_async(
            GLib.PRIORITY_LOW,
            self._cancellable,
            self._on_line_ready,
            None,
        )

    def _on_line_ready(
        self,
        stream: Gio.DataInputStream,
        result: Gio.AsyncResult,
        _user_data: None,
    ) -> None:
        try:
            line_bytes, _ = stream.read_line_finish(result)
        except GLib.Error as exc:
            if exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                _log.debug("JournalReader read cancelled")
            elif self._running:
                _log.error("journalctl read error: %s", exc)
            self._running = False
            return

        if line_bytes is None:
            _log.info("journalctl EOF — reader stopped")
            self._running = False
            return

        line = line_bytes.decode("utf-8", errors="replace").strip()
        if line:
            entry = self._parse_line(line)
            if entry is not None:
                self.emit("log-entry", entry)

        self._read_next_line()

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
