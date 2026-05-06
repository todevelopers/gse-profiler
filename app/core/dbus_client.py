from gi.repository import GObject


class DBusClient(GObject.Object):
    """Async D-Bus proxy for org.gnome.Shell.Extensions.

    Implemented in Phase 1. All methods are stubs until then.
    """

    __gtype_name__ = "DBusClient"

    def list_extensions(self) -> None:
        """List all installed GNOME Shell extensions."""

    def enable_extension(self, uuid: str) -> None:
        """Enable a GNOME Shell extension by UUID."""

    def disable_extension(self, uuid: str) -> None:
        """Disable a GNOME Shell extension by UUID."""
