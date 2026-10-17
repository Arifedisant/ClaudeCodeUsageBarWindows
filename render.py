"""Pillow drawing for the bar and its detail panel.

Shapes are drawn on a 3x layer and resampled down, so the rounded corners and
the thin progress tracks come out smooth at any DPI; text is drawn afterwards
at final size, where Pillow's own hinting is sharper than anything a downscale
would leave behind.

Every function returns `(image, hitboxes)`. A hitbox is
`(name, x0, y0, x1, y1)` in final pixels, which is what the window layer needs
to turn a click into an action.
"""

from __future__ import annotations

import datetime
import time

from PIL import Image, ImageDraw, ImageFont

import providers

# The colour punched out to transparency by the window layer. Kept almost
# black so the anti-aliased rim of a rounded corner fades into a dark taskbar
# rather than glowing against it.
KEY = (1, 2, 3)

SS = 3                                   # supersampling factor for shapes

SHELL_BG = (16, 20, 28)
SHELL_EDGE = (38, 47, 63)
SHELL_TOP = (54, 66, 88)
PANEL_BG = (21, 27, 38)
PANEL_EDGE = (39, 49, 66)
SEPARATOR = (32, 40, 54)
TRACK = (38, 47, 63)

TEXT = (240, 244, 249)
MUTED = (150, 165, 184)
DIM = (98, 112, 130)
OFFLINE = (86, 98, 114)

AMBER = (245, 173, 66)
RED = (240, 92, 92)

FONT_FILES = {
    "regular": "C:/Windows/Fonts/segoeui.ttf",
    "semibold": "C:/Windows/Fonts/seguisb.ttf",
    "bold": "C:/Windows/Fonts/segoeuib.ttf",
}

_font_cache: dict = {}


def font(weight: str, size: float):
    key = (weight, round(size))
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(FONT_FILES[weight], round(size))
        except OSError:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _hex(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def level_colour(accent, pct):
    """Brand colour normally, a warning colour once the allowance is nearly out."""
    if pct is None:
        return OFFLINE
    if pct >= 90:
        return RED
    if pct >= 70:
        return AMBER
    return accent


def _wrap(draw, text, fnt, width):
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            probe = line + " " + word
            if draw.textlength(probe, font=fnt) <= width:
                line = probe
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _ellipsise(draw, text, fnt, width):
    if draw.textlength(text, font=fnt) <= width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > width:
        text = text[:-1]
    return text + "…"


class Canvas:
    """A shape layer at SS scale plus the text layer that lands on top of it.

    Shape coordinates are given in the same logical units the layouts are
    written in; `scale` (display DPI) and `SS` (supersampling) are applied
    here so no caller has to remember either.
    """

    def __init__(self, width, height, scale):
        self.width = round(width * scale)
        self.height = round(height * scale)
        self.k = scale * SS
        self.layer = Image.new("RGB", (self.width * SS, self.height * SS), KEY)
        self.shapes = ImageDraw.Draw(self.layer)
        self._image = None
        self.text = None

    def rounded(self, box, radius, fill=None, outline=None, thickness=1):
        x0, y0, x1, y1 = (round(v * self.k) for v in box)
        self.shapes.rounded_rectangle(
            (x0, y0, x1 - 1, y1 - 1), radius=round(radius * self.k),
            fill=fill, outline=outline, width=max(1, round(thickness * self.k)))

    def line(self, box, fill):
        x0, y0, x1, y1 = (round(v * self.k) for v in box)
        self.shapes.rectangle((x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)), fill=fill)

    def circle(self, cx, cy, r, fill):
        cx, cy, r = cx * self.k, cy * self.k, r * self.k
        self.shapes.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)

    def bar(self, x, y, width, height, pct, colour, track=TRACK):
        radius = height / 2.0
        self.rounded((x, y, x + width, y + height), radius, fill=track)
        if pct is None or pct <= 0:
            return
        filled = max(height, width * min(pct, 100.0) / 100.0)
        self.rounded((x, y, x + filled, y + height), radius, fill=colour)

    def spark(self, x, baseline, width, height, values, colour, empty):
        """A column chart in the space a progress track would have used.

        Deliberately a different shape from `bar`: this is activity, not an
        allowance, and it must not be misread as a percentage.
        """
        if not values:
            return
        slot = width / len(values)
        column = max(1.6, slot - 2.2)
        peak = max(values) or 1
        for index, value in enumerate(values):
            top = baseline - (max(1.4, height * value / peak) if value else 1.4)
            left = x + index * slot
            self.rounded((left, top, left + column, baseline),
                         min(1.2, column / 2.0),
                         fill=colour if value else empty)

    def finish(self):
        self._image = self.layer.resize((self.width, self.height), Image.LANCZOS)
        self.text = ImageDraw.Draw(self._image)
        return self.text

    @property
    def image(self):
        return self._image


# --------------------------------------------------------------------------
# the strip
# --------------------------------------------------------------------------

CARDS = len(providers.READERS)


class Layout:
    """Logical geometry, drawn for a 42px-tall strip and centred in whatever
    height the taskbar actually leaves.

    Each card is two columns: a stack of name / progress / caption on the left,
    and the reading itself on the right, set large enough to be read without
    stopping to look. Keeping the number out of the left stack is what buys the
    progress track its own line on a strip this short.
    """

    design_h = 42
    shell_pad_x = 12
    card_w = 168
    card_gap = 16
    radius = 11

    dot_r = 3.2
    name_y = 9            # centre line of the provider name
    bar_y = 19            # top of the progress track
    bar_h = 5
    meta_y = 33           # centre line of the caption

    value_col = 46        # width reserved for the reading, flush right
    col_gap = 10
    value_y = 13          # centre line of the big number
    corner_y = 33         # centre line of the small figure beneath it

    @classmethod
    def track_w(cls):
        return cls.card_w - cls.value_col - cls.col_gap

    @classmethod
    def shell_width(cls):
        if CARDS == 1:
            return BADGE_W + COMPACT_W
        return cls.shell_pad_x * 2 + cls.card_w * CARDS + cls.card_gap * (CARDS - 1)


def _primary(entry):
    metrics = entry.get("metrics") or []
    return metrics[0] if metrics else None


def _secondary(entry):
    metrics = entry.get("metrics") or []
    return metrics[1] if len(metrics) > 1 else None


def _reset_text(metric, stale, updated_at, now):
    if stale:
        age = providers.humanise(now - updated_at) if updated_at else ""
        return ("basi %s lalu" % age) if age else "bacaan basi"
    resets = metric.get("resets_at") if metric else None
    if not resets:
        return ""
    return "reset %s (%s)" % (reset_clock(resets, now),
                              providers.humanise(resets - now))


_DAYS = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")


def reset_clock(resets, now):
    """The local wall-clock time of a reset, 12-hour like the taskbar clock
    (16 Okt 2026: Arif finds `2:30 PM` easier to read than `4j 20m`).
    Tomorrow gets `besok`, later a weekday."""
    at = time.localtime(resets)
    clock = "%d:%02d %s" % ((at.tm_hour + 11) % 12 + 1, at.tm_min,
                            "AM" if at.tm_hour < 12 else "PM")
    days = (datetime.date(*at[:3]) - datetime.date(*time.localtime(now)[:3])).days
    if days <= 0:
        return clock
    if days == 1:
        return "besok " + clock
    return "%s %s" % (_DAYS[at.tm_wday], clock)


def _card_texts(entry, now):
    """Everything the card says, decided before anything is drawn."""
    metric = _primary(entry)
    counter = entry.get("counter")

    if not entry.get("signed_in"):
        return {"value": "—", "unit": "", "meta": "belum login", "corner": None}

    if metric and metric.get("pct") is not None:
        value, unit = "%d" % round(metric["pct"]), "%"
    elif counter:
        value, unit = "%d" % counter["value"], counter["unit"]
    else:
        value, unit = "·", ""

    if metric:
        reset = _reset_text(metric, entry.get("stale"),
                            entry.get("updated_at"), now)
        meta = "%s · %s" % (metric["label"], reset) if reset else metric["label"]
    elif counter:
        meta = "%s · %d hari ini" % (counter["caption"], counter["today"])
    else:
        meta = "menunggu data"

    second = _secondary(entry)
    if second and second.get("pct") is not None:
        corner = "%s %d%%" % (providers.short_window(second.get("window_minutes"))
                              or second["label"], round(second["pct"]))
    else:
        corner = entry.get("plan") or None

    return {"value": value, "unit": unit, "meta": meta, "corner": corner}


def render_strip(entries, scale, height, now, hover=None, bg=None):
    """The always-on-top strip: one card per provider."""
    if len(entries) == 1:
        return render_compact(entries[0], scale, height, now, hover, bg)
    L = Layout
    s = scale
    canvas = Canvas(L.shell_width(), height, s)
    width_px, height_px = canvas.width, canvas.height
    dy = (height - L.design_h) / 2.0             # centre the design in the strip
    hitboxes = []

    canvas.rounded((0, 0, L.shell_width(), height), L.radius, fill=SHELL_BG)
    canvas.rounded((0, 0, L.shell_width(), height), L.radius,
                   outline=SHELL_EDGE, thickness=1)
    # A one-pixel light rim along the top edge: the cue that reads as "raised"
    # against a flat taskbar without costing any vertical room.
    canvas.line((L.radius, 0, L.shell_width() - L.radius, 1), SHELL_TOP)

    f_name = font("semibold", 10 * s)
    f_value = font("bold", 18 * s)
    f_unit = font("semibold", 9.5 * s)
    f_meta = font("regular", 9.5 * s)
    f_corner = font("regular", 9 * s)
    f_pill = font("semibold", 9 * s)

    plan: list = []
    for index, entry in enumerate(entries):
        x = L.shell_pad_x + index * (L.card_w + L.card_gap)
        if index and hover not in (index, index - 1):
            gap_mid = x - L.card_gap / 2.0
            canvas.line((gap_mid, 10, gap_mid + 1, height - 10), SEPARATOR)
        if hover == index:
            canvas.rounded((x - 7, 4, x + L.card_w + 7, height - 4), 8,
                           fill=(25, 32, 44))

        accent = _hex(entry["accent"])
        online = entry.get("signed_in")
        metric = _primary(entry)
        pct = metric.get("pct") if metric else None
        counter = entry.get("counter")
        colour = level_colour(accent, pct) if online else OFFLINE

        canvas.circle(x + L.dot_r, dy + L.name_y, L.dot_r,
                      accent if online else OFFLINE)

        if online and pct is not None:
            canvas.bar(x, dy + L.bar_y, L.track_w(), L.bar_h, pct, colour)
        elif online and counter and counter.get("spark"):
            canvas.spark(x, dy + L.bar_y + L.bar_h + 1, L.track_w(), 8,
                         counter["spark"], accent, (34, 43, 58))
        else:
            # Nothing to plot: the track stays, dimmed, so the three cards keep
            # the same skeleton and the eye is not asked to re-learn it.
            canvas.bar(x, dy + L.bar_y, L.track_w(), L.bar_h, None, None,
                       track=(29, 36, 49))

        pill = None
        if not online:
            pill_w, pill_h = L.value_col, 16
            pill_x = x + L.card_w - pill_w
            pill_y = dy + L.corner_y - pill_h / 2.0
            canvas.rounded((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
                           pill_h / 2.0, fill=(32, 41, 55))
            canvas.rounded((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
                           pill_h / 2.0, outline=accent, thickness=1)
            hitboxes.append(("login:" + entry["id"],
                             round(pill_x * s), round(pill_y * s),
                             round((pill_x + pill_w) * s),
                             round((pill_y + pill_h) * s)))
            pill = (pill_x, pill_y, pill_w, pill_h)

        plan.append((entry, x, accent, colour, pill))
        hitboxes.append(("card:" + entry["id"], round(x * s), 0,
                         round((x + L.card_w) * s), height_px))

    draw = canvas.finish()

    for entry, x, accent, colour, pill in plan:
        online = entry.get("signed_in")
        text = _card_texts(entry, now)
        left = x * s
        right = (x + L.card_w) * s
        track_right = (x + L.track_w()) * s

        draw.text((left + 11 * s, (dy + L.name_y) * s), entry["name"],
                  font=f_name, fill=TEXT if online else OFFLINE, anchor="lm")

        unit_w = draw.textlength(text["unit"], font=f_unit) if text["unit"] else 0
        if text["unit"]:
            draw.text((right, (dy + L.value_y) * s), text["unit"], font=f_unit,
                      fill=colour if online else OFFLINE, anchor="rm")
        draw.text((right - unit_w - (1 * s if unit_w else 0),
                   (dy + L.value_y) * s), text["value"],
                  font=f_value, fill=colour, anchor="rm")

        draw.text((left, (dy + L.meta_y) * s),
                  _ellipsise(draw, text["meta"], f_meta, track_right - left),
                  font=f_meta, fill=DIM if entry.get("stale") else MUTED,
                  anchor="lm")

        if pill:
            px, py, pw, ph = pill
            draw.text(((px + pw / 2.0) * s, (py + ph / 2.0) * s), "Login",
                      font=f_pill, fill=accent, anchor="mm")
        elif text["corner"]:
            draw.text((right, (dy + L.corner_y) * s), text["corner"],
                      font=f_corner, fill=DIM, anchor="rm")

    return canvas.image, hitboxes


# --------------------------------------------------------------------------
# compact strip (10 Okt 2026): Arif wanted only the Claude Code number —
# a big percentage with a superscript "%", and the time left until the
# window resets in small type underneath. Used whenever one card is shown.
# --------------------------------------------------------------------------

COMPACT_W = 50
COMPACT_H = 32        # = TrafficMonitor's box (48 px at 150 %)
BADGE_W = 24          # 17 Okt 2026: account pill left of the number (2 accounts)


def _badge_text_colour(fill):
    luma = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return SHELL_BG if luma > 150 else TEXT


def render_compact(entry, scale, height, now, hover=None, bg=None):
    """No box: the background is the taskbar colour sampled behind the
    window, so it reads as transparent. A real transparent key would make
    the empty pixels click-through and the widget could not be hovered or
    dragged any more."""
    s = scale
    bg = tuple(bg) if bg else SHELL_BG
    width = BADGE_W + COMPACT_W
    canvas = Canvas(width, height, s)
    fill = _mix(bg, (255, 255, 255), 0.07) if hover == 0 else bg
    canvas.shapes.rectangle((0, 0, canvas.layer.width, canvas.layer.height),
                            fill=bg)
    if hover == 0:
        canvas.rounded((0, 0, width, height), 6, fill=fill)

    # Which Claude account is signed in, so two accounts can't be confused.
    dy = (height - COMPACT_H) / 2.0
    badge = entry.get("badge") if entry.get("signed_in") else None
    badge_fill = _hex(badge["color"]) if badge else None
    if badge:
        canvas.rounded((2, dy + 9, BADGE_W - 1, dy + 23), 4, fill=badge_fill)
    draw = canvas.finish()

    if badge:
        size = 7.5
        f_badge = font("bold", size * s)
        while size > 5 and draw.textlength(badge["label"], font=f_badge) > (BADGE_W - 6) * s:
            size -= 0.5
            f_badge = font("bold", size * s)
        draw.text(((2 + BADGE_W - 1) * s / 2.0, (dy + 16) * s), badge["label"],
                  font=f_badge, fill=_badge_text_colour(badge_fill), anchor="mm")

    online = entry.get("signed_in")
    metric = _primary(entry)
    pct = metric.get("pct") if metric else None
    accent = _hex(entry["accent"])
    colour = level_colour(accent, pct) if online else OFFLINE

    if not online:
        value, sub = "—", "login"
    elif pct is not None:
        value = "%d" % round(pct)
        resets = metric.get("resets_at")
        if entry.get("stale"):
            sub = "basi"
        else:
            sub = reset_clock(resets, now) if resets else ""
    else:
        value, sub = "·", "menunggu"

    f_value = font("bold", 17 * s)
    f_sup = font("semibold", 8 * s)
    f_sub = font("regular", 8.5 * s)

    show_sup = online and pct is not None
    value_w = draw.textlength(value, font=f_value)
    sup_w = draw.textlength("%", font=f_sup) if show_sup else 0
    gap = 1 * s if show_sup else 0
    left = BADGE_W * s + (COMPACT_W * s - (value_w + gap + sup_w)) / 2.0
    base = (dy + 18) * s                         # baseline of the big number

    draw.text((left, base), value, font=f_value, fill=colour, anchor="ls")
    if show_sup:
        cap_top = base + f_value.getbbox("8", anchor="ls")[1]
        draw.text((left + value_w + gap, cap_top), "%", font=f_sup,
                  fill=colour, anchor="lt")
    if sub:
        # `besok 3:50 AM` is wider than the strip; shrink it rather than let
        # it clip, so the clock stays centred under the number.
        room = (COMPACT_W - 3) * s
        size = 8.5
        while size > 6 and draw.textlength(sub, font=f_sub) > room:
            size -= 0.5
            f_sub = font("regular", size * s)
        draw.text(((BADGE_W + COMPACT_W / 2.0) * s, (dy + 26) * s), sub, font=f_sub,
                  fill=DIM if entry.get("stale") else MUTED, anchor="mm")

    hitboxes = [("card:" + entry["id"], 0, 0, canvas.width, canvas.height)]
    return canvas.image, hitboxes


# --------------------------------------------------------------------------
# the detail panel
# --------------------------------------------------------------------------

PANEL_W = 320


def render_panel(entry, scale, now):
    """The card's full story: every window, the account, and the two buttons."""
    s = scale
    pad = 16
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    f_title = font("semibold", 13 * s)
    f_badge = font("semibold", 9 * s)
    f_label = font("semibold", 10.5 * s)
    f_value = font("bold", 13 * s)
    f_small = font("regular", 10 * s)
    f_note = font("regular", 9.5 * s)
    f_btn = font("semibold", 10.5 * s)

    metrics = entry.get("metrics") or []
    counter = entry.get("counter")
    note = entry.get("note") or ""
    if not entry.get("signed_in"):
        note = "Login membuka jendela terminal; selesaikan di sana lalu bar ini ikut hidup."
    note_lines = _wrap(probe, note, f_note, (PANEL_W - pad * 2) * s) if note else []

    row_h = 34
    height = pad + 18                                     # header row
    height += 16 if entry.get("account") else 4           # account line
    height += 10                                          # divider
    if metrics:
        height += len(metrics) * row_h
    elif counter:
        height += row_h
    if note_lines:
        height += 6 + len(note_lines) * 13
    height += 8 + 12                                      # source line
    height += 10 + 28 + pad                               # buttons

    canvas = Canvas(PANEL_W, height, s)
    hitboxes = []
    accent = _hex(entry["accent"])
    online = entry.get("signed_in")

    canvas.rounded((0, 0, PANEL_W, height), 14, fill=PANEL_BG)
    canvas.rounded((0, 0, PANEL_W, height), 14, outline=PANEL_EDGE, thickness=1)
    canvas.line((14, 0, PANEL_W - 14, 1), (58, 71, 94))
    canvas.circle(pad + 4, pad + 8, 4, accent if online else OFFLINE)

    y = pad + 18
    if entry.get("account"):
        y += 16
    else:
        y += 4
    divider_y = y + 3
    canvas.line((pad, divider_y, PANEL_W - pad, divider_y + 1), (35, 44, 59))
    y = divider_y + 9

    rows = []
    if metrics:
        for metric in metrics:
            colour = level_colour(accent, metric.get("pct")) if online else OFFLINE
            canvas.bar(pad, y + 18, PANEL_W - pad * 2, 6, metric.get("pct"), colour)
            rows.append(("metric", metric, y, colour))
            y += row_h
    elif counter:
        if counter.get("spark"):
            canvas.spark(pad, y + 24, PANEL_W - pad * 2, 14, counter["spark"],
                         accent if online else OFFLINE, (32, 41, 55))
        else:
            canvas.bar(pad, y + 18, PANEL_W - pad * 2, 6, None, None,
                       track=(30, 38, 51))
        rows.append(("counter", counter, y, MUTED))
        y += row_h

    note_y = y
    if note_lines:
        y += 6 + len(note_lines) * 13
    source_y = y + 8
    y = source_y + 12

    button_y = y + 10
    button_h = 28
    # Signing in is the one thing an offline card needs, so it is the only
    # button that gets the accent; once signed in all three read equally.
    quiet_edge = (48, 60, 78)
    buttons = [("login", "Ganti akun" if online else "Login"),
               ("logout", "Logout"),
               ("refresh", "Muat ulang")]
    total_gap = 8 * (len(buttons) - 1)
    button_w = (PANEL_W - pad * 2 - total_gap) / len(buttons)
    laid = []
    for index, (name, label) in enumerate(buttons):
        highlight = name == "login" and not online
        bx = pad + index * (button_w + 8)
        box = (bx, button_y, bx + button_w, button_y + button_h)
        canvas.rounded(box, 8, fill=(36, 46, 62) if highlight else (28, 36, 48))
        canvas.rounded(box, 8, outline=accent if highlight else quiet_edge,
                       thickness=1)
        hitboxes.append(("%s:%s" % (name, entry["id"]),
                         round(bx * s), round(button_y * s),
                         round((bx + button_w) * s),
                         round((button_y + button_h) * s)))
        laid.append((label, box, accent if highlight else TEXT))

    draw = canvas.finish()

    draw.text(((pad + 14) * s, (pad + 8) * s), entry["name"].title(),
              font=f_title, fill=TEXT, anchor="lm")
    badge = entry.get("plan") or ("terhubung" if online else "offline")
    draw.text(((PANEL_W - pad) * s, (pad + 8) * s), badge.upper(),
              font=f_badge, fill=accent if online else OFFLINE, anchor="rm")
    if entry.get("account"):
        draw.text((pad * s, (pad + 26) * s),
                  _ellipsise(draw, entry["account"], f_small,
                             (PANEL_W - pad * 2) * s),
                  font=f_small, fill=MUTED, anchor="lm")

    for kind, payload, row_y, colour in rows:
        if kind == "metric":
            label = payload["label"]
            trailer = _reset_text(payload, entry.get("stale"),
                                  entry.get("updated_at"), now)
            pct = payload.get("pct")
            value = "—" if pct is None else "%d%%" % round(pct)
        else:
            label = payload["caption"]
            trailer = "%d hari ini" % payload["today"]
            value = "%d %s" % (payload["value"], payload["unit"])

        draw.text((pad * s, (row_y + 6) * s), label,
                  font=f_label, fill=TEXT, anchor="lm")
        if trailer:
            offset = draw.textlength(label, font=f_label) + 7 * s
            draw.text((pad * s + offset, (row_y + 6) * s), "· " + trailer,
                      font=f_note, fill=DIM, anchor="lm")
        draw.text(((PANEL_W - pad) * s, (row_y + 6) * s), value,
                  font=f_value, fill=colour, anchor="rm")

    for index, line in enumerate(note_lines):
        draw.text((pad * s, (note_y + 6 + index * 13) * s), line,
                  font=f_note, fill=DIM, anchor="lm")

    source = entry.get("source") or "tanpa sumber"
    updated = entry.get("updated_at")
    age = ("%s lalu" % providers.humanise(now - updated)) if updated else "belum pernah"
    draw.text((pad * s, source_y * s), "sumber: %s · %s" % (source, age),
              font=f_note, fill=(74, 86, 102), anchor="lm")

    for label, box, tint in laid:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        draw.text((cx * s, cy * s), label, font=f_btn, fill=tint, anchor="mm")

    return canvas.image, hitboxes
