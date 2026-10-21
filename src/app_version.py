"""The app's release version, from ``config/version.json``.

Bumped by hand at a production build (tools/generate_executable.py), which
writes the repo copy and ships it in the build. A missing or broken file means
"dev" (running from source, no release to name).
"""

import json
from datetime import datetime
from pathlib import Path

VERSION_FILENAME = "version.json"
UNKNOWN = "dev"


def version_file_path() -> Path:
    """config/version.json: in the repo from source, in ``_internal/config`` in
    the exe (``parents[1]`` is ``_internal`` there, as for db_config.json)."""
    return Path(__file__).resolve().parents[1] / "config" / VERSION_FILENAME


def read_version_info() -> dict:
    """{"version": str, "released_at": str}; a dev build has no file."""
    path = version_file_path()
    if not path.exists():
        return {"version": UNKNOWN, "released_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": UNKNOWN, "released_at": ""}
    return {"version": str(data.get("version", UNKNOWN)),
            "released_at": str(data.get("released_at", ""))}


def current_version() -> str:
    return read_version_info()["version"]


def next_version(previous: str | None) -> str:
    """Bump the minor part: 1.0 -> 1.1, 1.9 -> 1.10. Starts at 1.0."""
    if not previous:
        return "1.0"
    try:
        major, minor = previous.strip().split(".", 1)
        return f"{int(major)}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        return "1.0"


def write_version_file(path: Path, version: str) -> dict:
    """Write the version and the moment of release; returns what was written."""
    info = {"version": version,
            "released_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info
