from gi.repository import GObject


class JournalReader(GObject.Object):
    """Async reader for journalctl --follow output.

    Spawns journalctl as a subprocess and emits a GObject signal per log entry.
    Implemented in Phase 3. All methods are stubs until then.
    """

    __gtype_name__ = "JournalReader"

    def start(self, uuid_filter: str | None = None) -> None:
        """Start tailing the journal, optionally filtered by extension UUID."""

    def stop(self) -> None:
        """Stop reading and terminate the journalctl subprocess."""
