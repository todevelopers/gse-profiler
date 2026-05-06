from gi.repository import GObject


class GitManager(GObject.Object):
    """Subprocess wrapper for git clone/pull operations.

    Implemented in Phase 6. All methods are stubs until then.
    """

    __gtype_name__ = "GitManager"

    def clone(self, url: str, target_path: str) -> None:
        """Clone a git repository, streaming output as a GObject signal."""

    def pull(self, path: str) -> None:
        """Pull latest changes in a cloned repository."""
