#!/usr/bin/env python3
"""PostToolUse hook for Edit/Write.

- Python files: run `ruff format` (skipped quietly if ruff is not installed).
- data/gap-ledger.json: validate against the schema. On failure, exit 2 so the
  errors are fed back to Claude to fix.
"""

import json
import os
import shutil
import subprocess
import sys


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    path = (event.get("tool_input") or {}).get("file_path", "")
    if not path:
        sys.exit(0)

    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    )
    abs_path = os.path.normpath(os.path.join(project_dir, path))
    rel = os.path.relpath(abs_path, project_dir).replace(os.sep, "/")

    if abs_path.endswith(".py") and shutil.which("ruff"):
        subprocess.run(["ruff", "format", "--quiet", abs_path], check=False)

    if rel == "data/gap-ledger.json":
        validator = os.path.join(project_dir, ".claude", "hooks", "validate_ledger.py")
        result = subprocess.run(
            [sys.executable, validator, abs_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                "gap-ledger.json failed validation:\n" + result.stdout + result.stderr,
                file=sys.stderr,
            )
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
