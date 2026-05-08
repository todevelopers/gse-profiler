import json
import logging
import os
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
from gi.repository import Gio, GLib, GObject

_log = logging.getLogger(__name__)
_SOCKET_NAME = "gse-profiler.sock"


def _socket_path() -> str:
    return os.path.join(GLib.get_user_runtime_dir(), _SOCKET_NAME)


class SocketServer(GObject.Object):
    """Async Unix socket server for bridge extension communication.

    Socket path: $XDG_RUNTIME_DIR/gse-profiler.sock
    Protocol: newline-delimited JSON messages.
    """

    __gtype_name__ = "SocketServer"

    __gsignals__ = {
        "client-connected": (GObject.SignalFlags.RUN_LAST, None, ()),
        "client-disconnected": (GObject.SignalFlags.RUN_LAST, None, ()),
        "message-received": (GObject.SignalFlags.RUN_LAST, None, (object,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._service: Gio.SocketService | None = None
        self._output: Gio.DataOutputStream | None = None
        self._cancellable: Gio.Cancellable | None = None

    @property
    def is_client_connected(self) -> bool:
        return self._output is not None

    def start(self) -> None:
        """Start listening on the Unix socket."""
        sock_path = _socket_path()
        _unlink_socket(sock_path)

        self._service = Gio.SocketService.new()
        addr = Gio.UnixSocketAddress.new(sock_path)
        try:
            self._service.add_address(
                addr,
                Gio.SocketType.STREAM,
                Gio.SocketProtocol.DEFAULT,
                None,
            )
        except GLib.Error as exc:
            _log.error("Failed to bind socket at %s: %s", sock_path, exc)
            self._service = None
            return

        self._service.connect("incoming", self._on_incoming)
        self._service.start()
        _log.info("Socket server listening at %s", sock_path)

    def stop(self) -> None:
        """Stop the server and close all connections."""
        if self._cancellable:
            self._cancellable.cancel()
            self._cancellable = None
        if self._service:
            self._service.stop()
            self._service.close()
            self._service = None
        self._output = None
        _unlink_socket(_socket_path())

    def send(self, message: dict[str, Any]) -> None:
        """Send a JSON message to the bridge extension."""
        if not self._output:
            return
        try:
            data = (json.dumps(message) + "\n").encode()
            self._output.write_all(data, None)
            self._output.flush(None)
        except GLib.Error as exc:
            _log.warning("Failed to send message: %s", exc)

    # ── Private ───────────────────────────────────────────────────────────

    def _on_incoming(
        self,
        _service: Gio.SocketService,
        connection: Gio.SocketConnection,
        _source: object,
    ) -> bool:
        _log.info("Bridge connected")
        self._cancellable = Gio.Cancellable.new()
        self._output = Gio.DataOutputStream.new(connection.get_output_stream())

        istream = Gio.DataInputStream.new(connection.get_input_stream())
        istream.set_newline_type(Gio.DataStreamNewlineType.LF)
        self._read_next(istream)

        self.emit("client-connected")
        return True

    def _read_next(self, stream: Gio.DataInputStream) -> None:
        stream.read_line_async(
            GLib.PRIORITY_DEFAULT,
            self._cancellable,
            self._on_line_read,
            None,
        )

    def _on_line_read(
        self,
        stream: Gio.DataInputStream,
        result: Gio.AsyncResult,
        _user_data: object,
    ) -> None:
        try:
            line_bytes, _length = stream.read_line_finish(result)
        except GLib.Error as exc:
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                _log.info("Bridge read error: %s", exc)
            self._output = None
            self.emit("client-disconnected")
            return

        if line_bytes is None:
            _log.info("Bridge disconnected (EOF)")
            self._output = None
            self.emit("client-disconnected")
            return

        line = line_bytes.decode("utf-8", errors="replace").strip()
        if line:
            try:
                msg = json.loads(line)
                self._dispatch(msg)
            except json.JSONDecodeError as exc:
                _log.warning("Invalid JSON from bridge: %s — %r", exc, line)

        self._read_next(stream)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "hello":
            _log.info(
                "Handshake received: bridge v%s uuid=%s",
                msg.get("version"),
                msg.get("uuid"),
            )
        self.emit("message-received", msg)


def _unlink_socket(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log.warning("Could not remove socket file %s: %s", path, exc)
