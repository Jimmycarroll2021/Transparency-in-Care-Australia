#!/usr/bin/env python3
"""PreToolUse hook: block Claude from editing or deleting immutable data.

Protected: data/raw/ and data/evidence/. Scripts (python3 scrapers/...) may still
write new snapshots there; this hook only stops direct edits by Claude's file tools
and destructive shell commands that name a protected path.

Reads the hook event as JSON on stdin. Exit 2 blocks the call; stderr is shown to Claude.
"""

import json
import os
import re
import sys

PROTECTED = ("data/raw/", "data/evidence/")

# Shell verbs that modify or remove files.
DESTRUCTIVE = re.compile(
    r"(^|[\s;&|(])(rm|rmdir|mv|truncate|shred|unlink|chmod|chown|tee|dd|cp)\s"
    r"|sed\s+(-[a-zA-Z]*i|--in-place)"
    r"|>>?\s*['\"]?\S*data/(raw|evidence)"
)


def is_protected(path: str, project_dir: str) -> bool:
    if not path:
        return False
    norm = os.path.normpath(os.path.join(project_dir, path))
    rel = os.path.relpath(norm, project_dir).replace(os.sep, "/") + "/"
    return any(rel.startswith(p) for p in PROTECTED)


def block(reason: str) -> None:
    print(f"Blocked by protect_raw hook: {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}
    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    )

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_protected(path, project_dir):
            block(
                f"{path} is immutable source data. Write new snapshots with a script in "
                "scrapers/, or write derived data to data/processed/."
            )

    if tool == "Bash":
        cmd = tool_input.get("command", "")
        names_protected = any(p.rstrip("/") in cmd for p in PROTECTED)
        runs_scraper = re.match(r"^\s*python3?\s+scrapers/", cmd) is not None
        if names_protected and DESTRUCTIVE.search(cmd) and not runs_scraper:
            block(
                "this shell command could modify or delete data/raw/ or data/evidence/. "
                "Raw data is append-only and written by scrapers only."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
