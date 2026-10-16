"""Claude Code status line hook — the source of the bar's Claude card.

Claude Code pipes its session JSON to this on every status-line render and
prints whatever comes back. We use the call for its side effect: mirroring
`rate_limits` into `~/.claude/usage-state.json`, which providers.py polls.

Registered in `~/.claude/settings.json` as:

    "statusLine": {
      "type": "command",
      "command": "\"C:\\\\Program Files\\\\Python313\\\\python.exe\" \"C:\\\\Users\\\\<you>\\\\AIUsageBar\\\\statusline.py\"",
      "padding": 0
    }

Schema: https://code.claude.com/docs/en/statusline

Nothing in here may raise. A crashing hook would take the status line of every
Claude Code session with it, so every step is wrapped and a bad payload just
prints an empty line.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE_PATH = Path(os.environ.get("USERPROFILE") or Path.home()) / ".claude" / "usage-state.json"


def _obj(parent, name):
    value = parent.get(name) if isinstance(parent, dict) else None
    return value if isinstance(value, dict) else None


def _num(parent, name):
    value = parent.get(name) if isinstance(parent, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _window(limits, name):
    window = _obj(limits, name)
    pct = _num(window, "used_percentage")
    if pct is None:
        return None
    return {"used_percentage": pct, "resets_at": _num(window, "resets_at")}


def _write_state(five, week):
    # rate_limits is absent for API-key users and on a session's first render.
    # Writing zeroes then would flash a wrong number onto the bar.
    if five is None and week is None:
        return
    payload = {"ts": time.time()}
    for name, window in (("five_hour", five), ("seven_day", week)):
        if window is None:
            continue
        entry = {"used_percentage": window["used_percentage"]}
        if window["resets_at"] is not None:
            entry["resets_at"] = window["resets_at"]
        payload[name] = entry

    temp = STATE_PATH.with_suffix(".json.tmp")
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(temp, STATE_PATH)
    except OSError:
        # A read-only home directory must not take the status line down.
        try:
            temp.unlink()
        except OSError:
            pass


def _render(root, five, week):
    parts = []
    model = (_obj(root, "model") or {}).get("display_name")
    if isinstance(model, str) and model:
        parts.append("[%s]" % model)

    directory = (_obj(root, "workspace") or {}).get("current_dir") or root.get("cwd")
    if isinstance(directory, str) and directory:
        leaf = os.path.basename(directory.rstrip("\\/"))
        parts.append(leaf or directory)

    ctx = _num(_obj(root, "context_window"), "used_percentage")
    if ctx is not None:
        parts.append("ctx %d%%" % ctx)

    if five is not None:
        parts.append("5h %d%%" % round(five["used_percentage"]))
    if week is not None:
        parts.append("7d %d%%" % round(week["used_percentage"]))

    return " | ".join(parts)


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        root = json.loads(raw) if raw.strip() else {}
    except ValueError:
        root = {}
    if not isinstance(root, dict):
        root = {}

    limits = _obj(root, "rate_limits")
    five = _window(limits, "five_hour")
    week = _window(limits, "seven_day")

    try:
        _write_state(five, week)
    except Exception:
        pass

    sys.stdout.write(_render(root, five, week))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
