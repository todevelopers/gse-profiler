"""Unit tests for DBusClient — requires PyGObject (skip on Windows/no-gi env)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Skip entire module when PyGObject is not available (e.g. Windows dev machines).
# Linux CI runners with GNOME have gi available and will execute all tests.
pytest.importorskip("gi", reason="PyGObject (gi) not available in this environment")


def test_extension_state_constants() -> None:
    from app.core.dbus_client import ExtensionState

    assert ExtensionState.ENABLED == 1
    assert ExtensionState.DISABLED == 2
    assert ExtensionState.ERROR == 3
    assert ExtensionState.OUT_OF_DATE == 4
    assert ExtensionState.UNINSTALLED == 99


def test_parse_info_minimal() -> None:
    from app.core.dbus_client import ExtensionState, _parse_info

    uuid = "test@example.com"
    result = _parse_info(uuid, {})

    assert result["uuid"] == uuid
    assert result["name"] == uuid  # falls back to uuid when name absent
    assert result["state"] == ExtensionState.DISABLED
    assert result["version"] == 0
    assert result["error"] == ""
    assert result["path"] == ""


def test_parse_info_full() -> None:
    from app.core.dbus_client import ExtensionState, _parse_info

    uuid = "my-ext@example.com"
    info = {
        "name": "My Extension",
        "description": "Does things",
        "version": 3,
        "state": 1,
        "path": "/home/user/.local/share/gnome-shell/extensions/my-ext@example.com",
        "error": "",
        "url": "https://example.com/my-ext",
    }
    result = _parse_info(uuid, info)

    assert result["name"] == "My Extension"
    assert result["state"] == ExtensionState.ENABLED
    assert result["version"] == 3
    assert result["path"] == info["path"]
    assert result["url"] == info["url"]


def test_parse_info_float_state_and_version() -> None:
    """State and version can arrive as floats from some D-Bus implementations."""
    from app.core.dbus_client import ExtensionState, _parse_info

    result = _parse_info("x@x", {"state": 1.0, "version": 2.0})

    assert result["state"] == ExtensionState.ENABLED
    assert isinstance(result["state"], int)
    assert result["version"] == 2
    assert isinstance(result["version"], int)


def test_parse_info_error_state() -> None:
    from app.core.dbus_client import ExtensionState, _parse_info

    result = _parse_info("err@x", {"state": 3, "error": "SyntaxError: oops"})

    assert result["state"] == ExtensionState.ERROR
    assert result["error"] == "SyntaxError: oops"


@pytest.mark.parametrize(
    "state_val,expected",
    [
        (1, 1),
        (2, 2),
        (3, 3),
        (99, 99),
        ("2", 2),  # string variant should still coerce via int()
    ],
)
def test_parse_info_state_coercion(state_val: object, expected: int) -> None:
    from app.core.dbus_client import _parse_info

    result = _parse_info("u@u", {"state": state_val})
    assert result["state"] == expected
