#!/usr/bin/env python3
"""Recompute the bridge-extension bundle hash and write it into metadata.json.

Run manually or via the pre-commit hook whenever bridge JS files change.
"""
import hashlib
import json
from pathlib import Path

BRIDGE_DIR = Path(__file__).parent.parent / "bridge-extension"
META_PATH = BRIDGE_DIR / "metadata.json"


def compute_hash(bridge_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(bridge_dir.glob("*.js")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    new_hash = compute_hash(BRIDGE_DIR)
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    old_hash = meta.get("bundle-hash")
    meta["bundle-hash"] = new_hash
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    if old_hash != new_hash:
        print(f"bridge hash updated: {old_hash or '(none)'} -> {new_hash}")
    else:
        print(f"bridge hash unchanged: {new_hash}")


if __name__ == "__main__":
    main()
