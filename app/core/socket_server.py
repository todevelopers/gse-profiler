from gi.repository import GObject


class SocketServer(GObject.Object):
    """Async Unix socket server for companion extension communication.

    Socket path: $XDG_RUNTIME_DIR/gse-profiler.sock
    Protocol: newline-delimited JSON messages.

    Implemented in Phase 2. All methods are stubs until then.
    """

    __gtype_name__ = "SocketServer"

    def start(self) -> None:
        """Start listening on the Unix socket."""

    def stop(self) -> None:
        """Stop the server and close all connections."""

    def send(self, message: dict) -> None:  # type: ignore[type-arg]
        """Send a JSON message to the companion extension."""
