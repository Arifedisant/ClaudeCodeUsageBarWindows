"""Sign-in state and usage readings for Claude Code, Codex and Antigravity.

Every number here comes from a file one of the three CLIs already writes on
this machine. Nothing calls a vendor API, and nothing reads a credential
store or a browser cookie jar -- the presence of a credentials file is used
as a sign-in flag, never its contents.

Where a provider simply does not publish its quota to disk (Antigravity keeps
it in the running process) the reading says so instead of inventing a number.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import time
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())

CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
AGY_DIR = HOME / ".gemini" / "antigravity-cli"

# A hook reading older than this is shown as an age instead of a countdown:
# the writer only runs while its CLI is rendering, so silence is not zero use.
STALE_AFTER = 45 * 60


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _epoch(value):
    """Accept the unix seconds and the ISO strings both writers produce."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            moment = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return moment.timestamp()
    return None


def _tail(path: Path, limit: int) -> str:
    """Last `limit` bytes of a file, decoded loosely."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            raw = fh.read()
    except OSError:
        return ""
    return raw.decode("utf-8", "replace")


def _scan_object(text: str, start: int):
    """Return the JSON object starting at `start`, or None if it is truncated."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _last_object_for(text: str, key: str):
    """Newest `"key": { ... }` in a blob, ignoring the `"key": null` writes.

    Codex rollout files run to tens of megabytes and a single line can be
    larger than any tail window, so this searches raw text rather than
    assuming it can split on newlines.
    """
    marker = '"%s"' % key
    idx = text.rfind(marker)
    while idx != -1:
        cursor = idx + len(marker)
        while cursor < len(text) and text[cursor] in " \t:":
            cursor += 1
        if cursor < len(text) and text[cursor] == "{":
            body = _scan_object(text, cursor)
            if body:
                try:
                    return json.loads(body)
                except ValueError:
                    pass
        idx = text.rfind(marker, 0, idx)
    return None


def _newest(paths):
    best = None
    best_mtime = -1.0
    for path in paths:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = Path(path), mtime
    return best


def window_label(minutes) -> str:
    """`300` -> `5 jam`, `43200` -> `30 hari`."""
    if not minutes:
        return ""
    minutes = int(minutes)
    if minutes % 1440 == 0:
        return "%d hari" % (minutes // 1440)
    if minutes % 60 == 0:
        return "%d jam" % (minutes // 60)
    return "%d mnt" % minutes


def short_window(minutes) -> str:
    """Compact form for the corner of a card: `5j`, `7hr`, `30hr`."""
    if not minutes:
        return ""
    minutes = int(minutes)
    if minutes % 1440 == 0:
        return "%dhr" % (minutes // 1440)
    if minutes % 60 == 0:
        return "%dj" % (minutes // 60)
    return "%dm" % minutes


def humanise(seconds) -> str:
    """A duration a glance can read: `2j 14m`, `18j`, `3hr 4j`."""
    if seconds is None:
        return ""
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%dhr %dj" % (days, hours) if hours else "%dhr" % days
    if hours:
        return "%dj %dm" % (hours, minutes) if minutes else "%dj" % hours
    if minutes:
        return "%dm" % minutes
    return "<1m"


def metric(label, pct, resets_at=None, window_minutes=None):
    return {
        "label": label,
        "pct": None if pct is None else max(0.0, min(100.0, float(pct))),
        "resets_at": resets_at,
        "window_minutes": window_minutes,
    }


def _blank(pid, name, accent, note):
    return {
        "id": pid,
        "name": name,
        "accent": accent,
        "signed_in": False,
        "account": "",
        "plan": "",
        "metrics": [],
        "counter": None,
        "updated_at": None,
        "source": "",
        "note": note,
    }


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------

_claude_profile_cache = {"mtime": None, "value": ("", "")}

_PLAN_NAMES = {
    "claude_pro": "Pro",
    "claude_max": "Max",
    "claude_team": "Team",
    "claude_enterprise": "Enterprise",
}


def _claude_profile():
    """Account e-mail and plan from ~/.claude.json, re-read only when it moves."""
    path = HOME / ".claude.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return "", ""
    if _claude_profile_cache["mtime"] == mtime:
        return _claude_profile_cache["value"]

    data = _load_json(path) or {}
    account = data.get("oauthAccount") or {}
    email = account.get("emailAddress") or ""
    plan = _PLAN_NAMES.get(account.get("organizationType") or "", "")
    _claude_profile_cache["mtime"] = mtime
    _claude_profile_cache["value"] = (email, plan)
    return email, plan


def _claude_window(state, key, label, minutes):
    window = (state or {}).get(key) or {}
    pct = window.get("used_percentage")
    if pct is None:
        pct = window.get("utilization")
    return metric(label, pct, _epoch(window.get("resets_at")), minutes)


def read_claude():
    result = _blank("claude", "CLAUDE CODE", "#E0795A", "")

    creds = CLAUDE_DIR / ".credentials.json"
    try:
        result["signed_in"] = creds.stat().st_size > 0
    except OSError:
        result["signed_in"] = False

    email, plan = _claude_profile()
    result["account"] = email
    result["plan"] = plan
    if email and not result["signed_in"]:
        # Windows keeps the token in Credential Manager on some installs, so a
        # missing file is not proof of a sign-out when a profile is present.
        result["signed_in"] = True

    # Two writers feed the same shape; whichever ran last is the truer number.
    hook = _load_json(CLAUDE_DIR / "usage-state.json")
    bridge = _load_json(CLAUDE_DIR / "usage-state-bridge.json")
    candidates = [(s, tag) for s, tag in ((hook, "hook Claude Code"),
                                          (bridge, "QuotaBar bridge")) if s]
    if not candidates:
        result["note"] = ("Belum ada bacaan. Pasang status line hook QuotaBar, "
                          "lalu jalankan satu sesi Claude Code.")
        return result

    state, source = max(candidates, key=lambda item: item[0].get("ts") or 0)
    result["source"] = source
    result["updated_at"] = _epoch(state.get("ts"))
    result["metrics"] = [
        _claude_window(state, "five_hour", "5 jam", 300),
        _claude_window(state, "seven_day", "7 hari", 10080),
    ]
    if source.startswith("hook"):
        result["note"] = ("Hook hanya melihat pemakaian lewat Claude Code; "
                          "chat di claude.ai memakai jatah yang sama.")
    return result


# --------------------------------------------------------------------------
# Codex
# --------------------------------------------------------------------------

_codex_cache = {"key": None, "value": None}

_CODEX_PLANS = {"go": "Go", "plus": "Plus", "pro": "Pro", "team": "Team",
                "business": "Business", "enterprise": "Enterprise", "edu": "Edu"}


def _codex_rollouts(limit=4):
    pattern = str(CODEX_DIR / "sessions" / "*" / "*" / "*" / "rollout-*.jsonl")
    files = glob.glob(pattern)
    files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
               reverse=True)
    return files[:limit]


def _codex_rate_limits():
    """Newest `rate_limits` payload across the most recent session files."""
    files = _codex_rollouts()
    if not files:
        return None
    key = tuple((f, os.path.getmtime(f)) for f in files if os.path.exists(f))
    if _codex_cache["key"] == key:
        return _codex_cache["value"]

    found = None
    for path in files:
        payload = _last_object_for(_tail(Path(path), 512 * 1024), "rate_limits")
        if payload:
            found = payload
            break
    _codex_cache["key"] = key
    _codex_cache["value"] = found
    return found


def _codex_metric(window, label_fallback):
    if not isinstance(window, dict):
        return None
    minutes = window.get("window_minutes")
    label = window_label(minutes) or label_fallback
    return metric(label, window.get("used_percent"),
                  _epoch(window.get("resets_at")), minutes)


def read_codex():
    result = _blank("codex", "CODEX", "#19C37D", "")

    auth = _load_json(CODEX_DIR / "auth.json") or {}
    tokens = auth.get("tokens") or {}
    result["signed_in"] = bool(tokens.get("access_token")
                               or auth.get("OPENAI_API_KEY"))
    if auth.get("auth_mode") == "chatgpt":
        result["account"] = "akun ChatGPT"
    elif auth.get("OPENAI_API_KEY"):
        result["account"] = "API key"

    limits = _codex_rate_limits()
    if not limits:
        if result["signed_in"]:
            result["note"] = ("Codex baru mengirim angka limit setelah balasan "
                              "pertama di sebuah sesi. Jalankan satu prompt.")
        return result

    result["source"] = "sesi Codex"
    result["plan"] = _CODEX_PLANS.get(limits.get("plan_type") or "",
                                      (limits.get("plan_type") or "").title())
    result["metrics"] = [m for m in (
        _codex_metric(limits.get("primary"), "utama"),
        _codex_metric(limits.get("secondary"), "sekunder"),
    ) if m]

    credits = limits.get("credits") or {}
    if credits.get("unlimited"):
        result["note"] = "Kredit tanpa batas."
    elif credits.get("balance") is not None:
        result["note"] = "Sisa kredit: %s" % credits["balance"]

    newest = _newest(_codex_rollouts(1))
    if newest:
        try:
            result["updated_at"] = newest.stat().st_mtime
        except OSError:
            pass
    return result


# --------------------------------------------------------------------------
# Antigravity (agy)
# --------------------------------------------------------------------------

_AGY_EMAIL = re.compile(r"applyAuthResult: email=([^\s,]+)")
_AGY_SIGNED_OUT = re.compile(r"not logged in|not logged into Antigravity",
                             re.IGNORECASE)


def _agy_logs(limit=3):
    files = glob.glob(str(AGY_DIR / "log" / "cli-*.log"))
    cli_log = AGY_DIR / "cli.log"
    if cli_log.exists():
        files.append(str(cli_log))
    files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
               reverse=True)
    return files[:limit]


def _agy_auth():
    """Latest sign-in verdict the CLI recorded, newest log first."""
    for path in _agy_logs():
        text = _tail(Path(path), 256 * 1024)
        email_at = -1
        email = ""
        match = None
        for match in _AGY_EMAIL.finditer(text):
            pass
        if match:
            email_at = match.start()
            email = match.group(1)
        signed_out_at = -1
        for match in _AGY_SIGNED_OUT.finditer(text):
            signed_out_at = match.start()
        if email_at < 0 and signed_out_at < 0:
            continue
        return (email_at > signed_out_at), email
    return False, ""


SPARK_BUCKETS = 10           # 30-minute slots across the 5-hour window


def _agy_activity():
    """Prompts sent in the last 5 hours and today, from the CLI's own history.

    Also buckets the recent ones into a sparkline. Antigravity publishes no
    quota locally, so the card shows the shape of your own activity rather
    than an empty gauge pretending to be one.
    """
    path = AGY_DIR / "history.jsonl"
    now = time.time()
    span = 5 * 3600
    window_start = now - span
    midnight = dt.datetime.now().replace(hour=0, minute=0, second=0,
                                         microsecond=0).timestamp()
    recent = today = 0
    last = None
    spark = [0] * SPARK_BUCKETS
    for line in _tail(path, 512 * 1024).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        stamp = entry.get("timestamp")
        if not isinstance(stamp, (int, float)):
            continue
        stamp = stamp / 1000.0 if stamp > 1e11 else float(stamp)
        last = stamp if last is None else max(last, stamp)
        if stamp >= window_start:
            recent += 1
            slot = int((stamp - window_start) / span * SPARK_BUCKETS)
            spark[min(SPARK_BUCKETS - 1, max(0, slot))] += 1
        if stamp >= midnight:
            today += 1
    return recent, today, last, spark


def read_antigravity():
    result = _blank("antigravity", "ANTIGRAVITY", "#6C9BFF", "")
    if not AGY_DIR.exists():
        result["note"] = "Antigravity CLI belum terpasang di komputer ini."
        return result

    signed_in, email = _agy_auth()
    result["signed_in"] = signed_in
    result["account"] = email if signed_in else ""
    if signed_in:
        result["plan"] = "Google"

    recent, today, last, spark = _agy_activity()
    result["counter"] = {"value": recent, "unit": "prompt",
                         "caption": "5 jam terakhir", "today": today,
                         "spark": spark}
    result["updated_at"] = last
    result["source"] = "history CLI"
    result["note"] = ("Antigravity tidak menulis sisa kuotanya ke disk — angka "
                      "itu hanya hidup di dalam CLI/IDE yang sedang jalan. Yang "
                      "ditampilkan di sini adalah jumlah prompt yang kamu kirim.")
    return result


# --------------------------------------------------------------------------

READERS = (read_claude,)  # 10 Okt 2026: Arif minta sisakan Claude Code saja


def _is_stale(entry) -> bool:
    """How old is too old depends on the window the number describes.

    A 5-hour figure from an hour ago may already be wrong; a 30-day figure
    from an hour ago is still essentially current.
    """
    updated = entry.get("updated_at")
    if not updated:
        return False
    metrics = entry.get("metrics") or []
    minutes = metrics[0].get("window_minutes") if metrics else None
    tolerance = 12 * 3600 if (minutes or 0) >= 1440 else STALE_AFTER
    return time.time() - updated > tolerance


def read_all(limits=None):
    """All three providers, in the order they appear on the bar.

    `limits` optionally maps a provider id to a self-declared cap, which turns
    a bare activity counter into a real gauge (Antigravity's case).
    """
    limits = limits or {}
    providers = []
    for reader in READERS:
        try:
            entry = reader()
        except Exception as exc:                     # never let one reader win
            entry = _blank("error", "ERROR", "#8894A6", "Gagal membaca: %s" % exc)
        cap = limits.get(entry["id"])
        counter = entry.get("counter")
        if cap and counter and not entry["metrics"]:
            entry["metrics"] = [metric("5 jam", 100.0 * counter["value"] / cap,
                                       None, 300)]
            entry["note"] = ("Persen dihitung dari batas %s prompt/5 jam yang "
                             "kamu isi sendiri, bukan dari Google." % cap)
        entry["stale"] = _is_stale(entry)
        providers.append(entry)
    return providers


if __name__ == "__main__":
    for item in read_all():
        print(json.dumps(item, indent=2, ensure_ascii=False))
