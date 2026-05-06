"""Phase 0 smoke tests — no GTK display required."""


def test_phase0_placeholder() -> None:
    """Verify the project skeleton is importable without a display."""
    # Core stubs can be imported from the project root.
    # GTK/Adw imports are deferred inside each module, so this works headlessly.
    import importlib
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for module in [
        "app",
        "app.ui",
        "app.core",
    ]:
        assert importlib.util.find_spec(module) is not None, f"Module {module!r} not found"


def test_nav_items_consistent() -> None:
    """All nav keys must be unique and non-empty."""
    nav_items = [
        ("extensions", "Extensions", "application-x-addon-symbolic"),
        ("logs", "Log Viewer", "text-x-log-symbolic"),
        ("profiler", "Profiler", "utilities-system-monitor-symbolic"),
        ("inspector", "Inspector", "edit-find-symbolic"),
    ]
    keys = [k for k, *_ in nav_items]
    assert len(keys) == len(set(keys)), "Duplicate nav keys"
    assert all(k for k in keys), "Empty nav key"
