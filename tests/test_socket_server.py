"""Unit tests for SocketServer — requires PyGObject (skip on Windows/no-gi env)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("gi", reason="PyGObject (gi) not available in this environment")


def test_socket_path_format() -> None:
    from app.core.socket_server import _socket_path

    path = _socket_path()
    assert path.endswith("gse-profiler.sock")
    assert os.path.isabs(path)


def test_send_noop_when_not_connected() -> None:
    from app.core.socket_server import SocketServer

    server = SocketServer()
    # Must not raise even when no client is connected
    server.send({"type": "test", "data": 42})


def test_is_client_connected_initial_state() -> None:
    from app.core.socket_server import SocketServer

    server = SocketServer()
    assert server.is_client_connected is False


def test_message_received_signal_on_dispatch() -> None:
    from app.core.socket_server import SocketServer

    server = SocketServer()
    received: list[object] = []
    server.connect("message-received", lambda _s, msg: received.append(msg))

    server._dispatch({"type": "hello", "version": "1", "uuid": "test@example.com"})

    assert len(received) == 1
    assert received[0]["type"] == "hello"
    assert received[0]["uuid"] == "test@example.com"


def test_dispatch_unknown_type_still_emits_signal() -> None:
    from app.core.socket_server import SocketServer

    server = SocketServer()
    received: list[object] = []
    server.connect("message-received", lambda _s, msg: received.append(msg))

    server._dispatch({"type": "profile_event", "extensionUuid": "ext@x.com"})

    assert len(received) == 1
    assert received[0]["type"] == "profile_event"


def test_stop_without_start_does_not_raise() -> None:
    from app.core.socket_server import SocketServer

    server = SocketServer()
    server.stop()  # Must not raise


def test_socket_server_start_creates_socket(tmp_path: "pytest.TempPathFactory") -> None:
    """Start the server and verify the socket file appears on disk."""
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    from app.core.socket_server import SocketServer, _socket_path

    # Redirect socket to a temp directory so we don't pollute the real runtime dir
    original_runtime = GLib.get_user_runtime_dir()

    # Patch the runtime dir env var so _socket_path() returns a test path
    test_sock = str(tmp_path / "gse-profiler.sock")

    import unittest.mock as mock

    with mock.patch("app.core.socket_server._socket_path", return_value=test_sock):
        server = SocketServer()
        server.start()
        assert os.path.exists(test_sock), "Socket file not created after start()"
        server.stop()
        assert not os.path.exists(test_sock), "Socket file not removed after stop()"

    _ = original_runtime  # keep reference to suppress unused warning


def test_unlink_socket_tolerates_missing_file() -> None:
    from app.core.socket_server import _unlink_socket

    # Should not raise when path does not exist
    _unlink_socket("/tmp/nonexistent-gse-profiler-test.sock")
