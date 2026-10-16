"""AI Usage Bar — a strip in the empty left end of the Windows 11 taskbar
showing how much of your Claude Code, Codex and Antigravity allowance is gone,
and letting you sign in or out of each.

Run it with pythonw so no console appears:

    pythonw.exe C:\\Users\\<you>\\AIUsageBar\\aiusagebar.pyw

The window is a borderless always-on-top Tk window whose background colour is
punched out to transparency, with the whole design drawn by Pillow (see
render.py) rather than by Tk widgets — that is what makes rounded corners and
hairline progress tracks possible at any DPI.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import ImageTk                                     # noqa: E402

import providers                                            # noqa: E402
import render                                               # noqa: E402

APP_NAME = "AIUsageBar"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
CONFIG_PATH = DATA_DIR / "config.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

KEY_HEX = "#%02x%02x%02x" % render.KEY

POLL_SECONDS = 8            # how often the files are re-read
TOPMOST_MS = 700            # how often z-order is checked
RELAYOUT_MS = 30000         # how often the dock is re-measured
PANEL_CLOSE_MS = 1200       # grace period after the pointer leaves the panel

user32 = ctypes.windll.user32

# Without these, ctypes truncates returned HWNDs to 32 bits, which turns a
# valid handle into a silent no-op on 64-bit Windows.
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.FindWindowW.restype = wintypes.HWND
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
ctypes.windll.gdi32.GetPixel.restype = wintypes.DWORD
ctypes.windll.gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]

HWND_TOP = 0
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT = 2

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------
# Windows plumbing
# --------------------------------------------------------------------------

def make_dpi_aware():
    """Per-monitor v2, so Tk geometry is in real pixels and text stays sharp."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def taskbar_rect():
    """(left, top, right, bottom) of the primary taskbar, or None."""
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def display_scale():
    """Display scaling, with fallbacks for the seconds before the shell exists.

    At sign-in this can run before Shell_TrayWnd is created; taking 96 dpi
    then would draw the strip at two-thirds size and leave it there, so the
    system DPI is asked next and the device context last.
    """
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    dpi = 0
    if hwnd:
        try:
            dpi = user32.GetDpiForWindow(hwnd)
        except Exception:
            dpi = 0
    if not dpi:
        try:
            dpi = user32.GetDpiForSystem()
        except Exception:
            dpi = 0
    if not dpi:
        try:
            dc = user32.GetDC(None)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)   # LOGPIXELSX
            user32.ReleaseDC(None, dc)
        except Exception:
            dpi = 0
    return (dpi or 96) / 96.0


def as_toolwindow(hwnd):
    """Keep the strip out of Alt-Tab and off the taskbar's own button row."""
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
    except Exception:
        pass


def mark_topmost(hwnd):
    """Put the window in the topmost band. Only needed once."""
    try:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def raise_above_taskbar(hwnd):
    """Lift the window to the front of the topmost band.

    HWND_TOPMOST is the wrong tool for this: on a window that already carries
    WS_EX_TOPMOST it is a no-op, so re-issuing it can never win the window back
    once Windows has raised Shell_TrayWnd over it. HWND_TOP moves the window to
    the front of the band it is already in, which is what actually re-raises it.
    """
    try:
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def covering_window(hwnd, rect):
    """Whatever is painted on top of the middle of `rect`, or None if we are."""
    try:
        point = wintypes.POINT((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        top = user32.WindowFromPoint(point)
        if not top or top == hwnd:
            return None
        return user32.GetAncestor(top, GA_ROOT) or top
    except Exception:
        return None


def window_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_taskbar(hwnd):
    """Does this window belong to the taskbar?

    Class name alone is not enough on Windows 11: the bar that actually paints
    over us is a top-level `Windows.UI.Core.CoreWindow` (the taskbar's XAML
    host), not `Shell_TrayWnd`. What they share is the process, so ownership is
    the test. Start menu and the notification flyouts live in their own
    processes, so this still leaves their windows alone.
    """
    try:
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return True
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return False
        return window_pid(hwnd) == window_pid(tray) != 0
    except Exception:
        return False


def in_terminal(command: str, preface: str = ""):
    """Open a console the user can actually type into, and run `command`."""
    body = command
    if preface:
        body = 'echo %s && echo. && %s' % (preface, command)
    subprocess.Popen(["cmd", "/c", "start", "AI Usage Bar", "cmd", "/k", body],
                     creationflags=CREATE_NO_WINDOW)


def quietly(command: list):
    subprocess.Popen(command, creationflags=CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------
# sign-in / sign-out
# --------------------------------------------------------------------------

# Claude and Codex both expose real auth subcommands. Antigravity does not:
# `agy --help` lists no auth verb, so the honest thing is to open the CLI and
# let its own interface handle it rather than pretend a switch exists here.
ACTIONS = {
    "claude": {
        "login": ("claude auth login", "Selesaikan login Claude di jendela ini."),
        "logout": ("claude auth logout", ""),
    },
    "codex": {
        "login": ("codex login", "Selesaikan login Codex di jendela ini."),
        "logout": ("codex logout", ""),
    },
    "antigravity": {
        "login": ("agy", "Antigravity tidak punya perintah login lewat argumen "
                         "CLI. Selesaikan autentikasi di dalam antarmuka agy."),
        "logout": ("agy", "Antigravity tidak punya perintah logout lewat "
                          "argumen CLI. Ganti akun dari dalam antarmuka agy."),
    },
}


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "x": None,
    "y": None,
    "opacity": 100,
    "limits": {},          # provider id -> self-declared cap, e.g. antigravity
}


def load_config():
    config = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            config.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return config


def save_config(config):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
    except OSError:
        pass


def pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        if enabled:
            command = '"%s" "%s"' % (pythonw(), APP_DIR / "aiusagebar.pyw")
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass


# --------------------------------------------------------------------------
# the reader thread
# --------------------------------------------------------------------------

class Reader(threading.Thread):
    """Re-reads the three providers off the UI thread.

    The Codex reading means tailing session files that run to tens of
    megabytes; doing that on the main loop would show up as a stutter every
    few seconds.
    """

    def __init__(self, config):
        super().__init__(daemon=True)
        self.config = config
        self.results = queue.Queue()
        self.wake = threading.Event()
        self.stopping = False

    def refresh_now(self):
        self.wake.set()

    def run(self):
        while not self.stopping:
            try:
                self.results.put(providers.read_all(self.config.get("limits")))
            except Exception:
                pass
            self.wake.wait(POLL_SECONDS)
            self.wake.clear()


# --------------------------------------------------------------------------
# the widget
# --------------------------------------------------------------------------

class UsageBar:

    def __init__(self):
        self.config = load_config()
        self.scale = display_scale()
        self.height = self._strip_height(self.scale)
        self.bg = None

        self.entries = []
        self.hover = None
        self.panel_for = None
        self.panel_hitboxes = []
        self.strip_hitboxes = []
        self.suppress_raise_until = 0.0
        self._panel_close_job = None
        self._drag = None
        self._strip_signature = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("AI Usage Bar")
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY_HEX)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", KEY_HEX)

        self.canvas = tk.Label(self.root, bd=0, highlightthickness=0, bg=KEY_HEX)
        self.canvas.pack()
        self._strip_photo = None

        self.panel = tk.Toplevel(self.root)
        self.panel.withdraw()
        self.panel.overrideredirect(True)
        self.panel.configure(bg=KEY_HEX)
        self.panel.attributes("-topmost", True)
        self.panel.wm_attributes("-transparentcolor", KEY_HEX)
        self.panel_canvas = tk.Label(self.panel, bd=0, highlightthickness=0,
                                     bg=KEY_HEX)
        self.panel_canvas.pack()
        self._panel_photo = None

        self._build_menu()
        self._bind()

        self.reader = Reader(self.config)
        self.reader.start()

        self.root.deiconify()
        self.root.update_idletasks()
        as_toolwindow(self._hwnd(self.root))
        as_toolwindow(self._hwnd(self.panel))
        self._apply_opacity()
        self._place()
        mark_topmost(self._hwnd(self.root))
        mark_topmost(self._hwnd(self.panel))

        self.root.after(120, self._drain)
        self.root.after(TOPMOST_MS, self._keep_on_top)
        # At sign-in this window can be up before the taskbar is, and the
        # screen can change resolution later, so the dock is re-checked --
        # eagerly for the first half minute, then just often enough to notice.
        for delay in (800, 2000, 5000, 12000, 25000):
            self.root.after(delay, self._relayout)
        self.root.after(RELAYOUT_MS, self._relayout_loop)

    # -- geometry ----------------------------------------------------------

    def _taskbar_height_for(self, scale):
        rect = taskbar_rect()
        if not rect:
            return round(48 * scale)
        height = rect[3] - rect[1]
        # A vertical or auto-hidden taskbar gives a useless height; fall back
        # to the standard one rather than drawing a sliver.
        return height if 24 < height < 200 else round(48 * scale)

    def _strip_height(self, scale):
        if render.CARDS == 1:
            return render.COMPACT_H
        return max(30, round(self._taskbar_height_for(scale) / scale) - 6)

    def _taskbar_height(self):
        return self._taskbar_height_for(self.scale)

    def _default_position(self):
        rect = taskbar_rect()
        width = round(render.Layout.shell_width() * self.scale)
        height = round(self.height * self.scale)
        if rect and 24 < rect[3] - rect[1] < 200:
            x = rect[0] + round(14 * self.scale)
            y = rect[1] + (rect[3] - rect[1] - height) // 2
        else:
            x = round(14 * self.scale)
            y = self.root.winfo_screenheight() - height - round(8 * self.scale)
        return self._clamp(x, y, width, height)

    def _clamp(self, x, y, width, height):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
        return x, y

    def _place(self):
        width = round(render.Layout.shell_width() * self.scale)
        height = round(self.height * self.scale)
        if self.config.get("x") is None or self.config.get("y") is None:
            x, y = self._default_position()
        else:
            x, y = self._clamp(int(self.config["x"]), int(self.config["y"]),
                               width, height)
            rect = taskbar_rect()
            if rect and rect[1] - height <= y <= rect[3]:
                y = rect[1] + (rect[3] - rect[1] - height) // 2
        self.root.geometry("%dx%d+%d+%d" % (width, height, x, y))

    def _relayout(self):
        """Re-measure the shell and re-dock, if anything about it moved."""
        scale = display_scale()
        height = self._strip_height(scale)
        changed = (abs(scale - self.scale) > 0.01) or (height != self.height)
        if changed:
            self.scale, self.height = scale, height
            self._strip_signature = None
            self._draw_strip()
        if changed or self.config.get("x") is None:
            self._place()
        else:
            # A resolution drop can leave a remembered position off-screen.
            x, y = self._clamp(self.root.winfo_x(), self.root.winfo_y(),
                               self.root.winfo_width(), self.root.winfo_height())
            if (x, y) != (self.root.winfo_x(), self.root.winfo_y()):
                self.root.geometry("+%d+%d" % (x, y))

    def _relayout_loop(self):
        self._relayout()
        self.root.after(RELAYOUT_MS, self._relayout_loop)

    def _hwnd(self, window):
        """The real top-level HWND behind a Tk window.

        `winfo_id()` hands back Tk's inner `TkChild`, not the `TkTopLevel` the
        window manager knows about. Z-order calls aimed at the child silently
        do nothing, which is exactly how the strip used to slip under the
        taskbar and stay there.
        """
        inner = ctypes.c_void_p(window.winfo_id()).value
        return user32.GetAncestor(inner, GA_ROOT) or inner

    def _apply_opacity(self):
        alpha = max(35, min(100, int(self.config.get("opacity", 100)))) / 100.0
        self.root.attributes("-alpha", alpha)
        self.panel.attributes("-alpha", alpha)

    # -- rendering ---------------------------------------------------------

    def _sample_bg(self):
        """Taskbar colour just above the widget, inside the taskbar."""
        rect = taskbar_rect()
        if not rect:
            return None
        x0 = self.root.winfo_rootx()
        w = self.root.winfo_width()
        y = max(rect[1] + 2, self.root.winfo_rooty() - 4)
        if y >= self.root.winfo_rooty():
            return self.bg
        dc = user32.GetDC(0)
        try:
            px = [ctypes.windll.gdi32.GetPixel(dc, x, y)
                  for x in (x0 + 4, x0 + w // 2, x0 + w - 4)]
        finally:
            user32.ReleaseDC(0, dc)
        px = [p for p in px if p != 0xFFFFFFFF]
        if not px:
            return self.bg
        rgb = sorted((p & 0xFF, (p >> 8) & 0xFF, (p >> 16) & 0xFF) for p in px)
        return rgb[len(rgb) // 2]

    def _draw_strip(self):
        if not self.entries:
            return
        now = time.time()
        self.bg = self._sample_bg() or self.bg
        signature = (self.hover, round(now / 30), self.bg,
                     tuple((e["id"], e["signed_in"], e.get("stale"),
                            tuple((m["label"], round(m["pct"] or -1, 1),
                                   m["resets_at"]) for m in e["metrics"]),
                            (e["counter"] or {}).get("value"))
                           for e in self.entries))
        if signature == self._strip_signature:
            return
        self._strip_signature = signature

        image, hitboxes = render.render_strip(self.entries, self.scale,
                                              self.height, now, self.hover,
                                              self.bg)
        self.strip_hitboxes = hitboxes
        self._strip_photo = ImageTk.PhotoImage(image)
        self.canvas.configure(image=self._strip_photo)

    def _draw_panel(self):
        entry = self._entry(self.panel_for)
        if not entry:
            self._hide_panel()
            return
        image, hitboxes = render.render_panel(entry, self.scale, time.time())
        self.panel_hitboxes = hitboxes
        self._panel_photo = ImageTk.PhotoImage(image)
        self.panel_canvas.configure(image=self._panel_photo)

        card = self._hitbox_for("card:" + entry["id"], self.strip_hitboxes)
        anchor_x = self.root.winfo_rootx() + (card[0] if card else 0)
        x = max(4, min(anchor_x - round(12 * self.scale),
                       self.root.winfo_screenwidth() - image.width - 4))
        y = self.root.winfo_rooty() - image.height - round(8 * self.scale)
        if y < 4:
            y = self.root.winfo_rooty() + self.root.winfo_height() + 8
        self.panel.geometry("%dx%d+%d+%d" % (image.width, image.height, x, y))
        self.panel.deiconify()
        raise_above_taskbar(self._hwnd(self.panel))

    def _entry(self, pid):
        for entry in self.entries:
            if entry["id"] == pid:
                return entry
        return None

    @staticmethod
    def _hitbox_for(name, hitboxes):
        for box in hitboxes:
            if box[0] == name:
                return box[1:]
        return None

    @staticmethod
    def _hit(hitboxes, x, y, prefix=None):
        # Later entries were drawn on top, so they win a tie.
        for name, x0, y0, x1, y1 in reversed(hitboxes):
            if prefix and not name.startswith(prefix):
                continue
            if x0 <= x < x1 and y0 <= y < y1:
                return name
        return None

    # -- event loop --------------------------------------------------------

    def _drain(self):
        latest = None
        try:
            while True:
                latest = self.reader.results.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self.entries = latest
            self._draw_strip()
            if self.panel_for:
                self._draw_panel()
        else:
            self._draw_strip()
        self.root.after(1000, self._drain)

    def _keep_on_top(self):
        # Paused right after a login console opens, so the strip does not
        # fight the terminal the user is typing into.
        if time.time() >= self.suppress_raise_until:
            hwnd = self._hwnd(self.root)
            rect = (self.root.winfo_rootx(), self.root.winfo_rooty(),
                    self.root.winfo_rootx() + self.root.winfo_width(),
                    self.root.winfo_rooty() + self.root.winfo_height())
            covered = covering_window(hwnd, rect)
            # Only fight the taskbar. If a Start menu, a flyout or another
            # topmost app is over the strip, that window has a better claim to
            # the pixels than a status widget does.
            if covered is not None and is_taskbar(covered):
                raise_above_taskbar(hwnd)
                if self.panel_for:
                    raise_above_taskbar(self._hwnd(self.panel))
        self.root.after(TOPMOST_MS, self._keep_on_top)

    # -- interaction -------------------------------------------------------

    def _bind(self):
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.panel_canvas.bind("<Button-1>", self._on_panel_click)
        self.panel_canvas.bind("<Enter>", lambda _e: self._cancel_panel_close())
        self.panel_canvas.bind("<Leave>", self._on_leave)

    def _on_motion(self, event):
        name = self._hit(self.strip_hitboxes, event.x, event.y, "card:")
        index = None
        if name:
            pid = name.split(":", 1)[1]
            index = next((i for i, e in enumerate(self.entries)
                          if e["id"] == pid), None)
        if index != self.hover:
            self.hover = index
            self._draw_strip()
        self._cancel_panel_close()

    def _on_leave(self, _event=None):
        if self.hover is not None:
            self.hover = None
            self._draw_strip()
        if self.panel_for:
            self._cancel_panel_close()
            self._panel_close_job = self.root.after(PANEL_CLOSE_MS,
                                                    self._hide_panel)

    def _cancel_panel_close(self):
        if self._panel_close_job is not None:
            try:
                self.root.after_cancel(self._panel_close_job)
            except Exception:
                pass
            self._panel_close_job = None

    def _on_press(self, event):
        self._drag = {"x": event.x_root, "y": event.y_root,
                      "ox": self.root.winfo_x(), "oy": self.root.winfo_y(),
                      "moved": False}

    def _on_drag(self, event):
        if not self._drag:
            return
        dx = event.x_root - self._drag["x"]
        dy = event.y_root - self._drag["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag["moved"] = True
            self._hide_panel()
        if self._drag["moved"]:
            x, y = self._clamp(self._drag["ox"] + dx, self._drag["oy"] + dy,
                               self.root.winfo_width(), self.root.winfo_height())
            self.root.geometry("+%d+%d" % (x, y))

    def _on_release(self, event):
        drag, self._drag = self._drag, None
        if not drag:
            return
        if drag["moved"]:
            self.config["x"] = self.root.winfo_x()
            self.config["y"] = self.root.winfo_y()
            save_config(self.config)
            return

        target = self._hit(self.strip_hitboxes, event.x, event.y, "login:")
        if target:
            self._act("login", target.split(":", 1)[1])
            return
        target = self._hit(self.strip_hitboxes, event.x, event.y, "card:")
        if target:
            pid = target.split(":", 1)[1]
            if self.panel_for == pid:
                self._hide_panel()
            else:
                self.panel_for = pid
                self._draw_panel()
        else:
            self._hide_panel()

    def _on_panel_click(self, event):
        name = self._hit(self.panel_hitboxes, event.x, event.y)
        if not name:
            return
        action, pid = name.split(":", 1)
        if action == "refresh":
            self.reader.refresh_now()
            self._strip_signature = None
            return
        self._act(action, pid)

    def _hide_panel(self):
        self._cancel_panel_close()
        self.panel_for = None
        self.panel.withdraw()

    # -- actions -----------------------------------------------------------

    def _act(self, action, pid):
        self._hide_panel()
        spec = ACTIONS.get(pid, {}).get(action)
        if not spec:
            return
        command, preface = spec
        in_terminal(command, preface)
        # Let the console take the foreground, then pick the change up.
        self.suppress_raise_until = time.time() + 25
        self.root.after(4000, self.reader.refresh_now)
        self.root.after(15000, self.reader.refresh_now)

    # -- menu --------------------------------------------------------------

    def _build_menu(self):
        style = {"tearoff": 0, "bg": "#171d28", "fg": "#e8edf4",
                 "activebackground": "#27324a", "activeforeground": "#ffffff",
                 "bd": 0, "relief": "flat"}
        self.menu = tk.Menu(self.root, **style)

        accounts = tk.Menu(self.menu, **style)
        for pid, label in (("claude", "Claude Code"),):
            sub = tk.Menu(accounts, **style)
            sub.add_command(label="Login…",
                            command=lambda p=pid: self._act("login", p))
            sub.add_command(label="Logout",
                            command=lambda p=pid: self._act("logout", p))
            accounts.add_cascade(label=label, menu=sub)
        self.menu.add_cascade(label="Akun", menu=accounts)

        self.menu.add_command(label="Muat ulang sekarang",
                              command=self.reader_refresh)
        self.menu.add_separator()

        opacity = tk.Menu(self.menu, **style)
        for value in (100, 90, 80, 70, 55):
            opacity.add_command(label="%d%%" % value,
                                command=lambda v=value: self._set_opacity(v))
        self.menu.add_cascade(label="Transparansi", menu=opacity)
        self.menu.add_command(label="Kembalikan ke pojok taskbar",
                              command=self._reset_position)
        self.menu.add_separator()

        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self.menu.add_checkbutton(label="Jalan saat Windows menyala",
                                  variable=self.autostart_var,
                                  command=self._toggle_autostart,
                                  selectcolor="#4c8df6")
        self.menu.add_separator()
        self.menu.add_command(label="Keluar", command=self.quit)

    def reader_refresh(self):
        self.reader.refresh_now()
        self._strip_signature = None

    def _on_menu(self, event):
        self._hide_panel()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _set_opacity(self, value):
        self.config["opacity"] = value
        save_config(self.config)
        self._apply_opacity()

    def _reset_position(self):
        self.config["x"] = self.config["y"] = None
        save_config(self.config)
        self._place()

    def _ask_limit(self):
        current = (self.config.get("limits") or {}).get("antigravity") or 0
        answer = simpledialog.askinteger(
            "Batas Antigravity",
            "Antigravity tidak membocorkan sisa kuotanya, jadi bar hanya bisa\n"
            "menghitung persen kalau kamu sendiri tahu batasnya.\n\n"
            "Berapa prompt per 5 jam? (0 = tampilkan jumlah saja)",
            initialvalue=current, minvalue=0, maxvalue=100000, parent=self.root)
        if answer is None:
            return
        limits = dict(self.config.get("limits") or {})
        if answer:
            limits["antigravity"] = answer
        else:
            limits.pop("antigravity", None)
        self.config["limits"] = limits
        self.reader.config = self.config
        save_config(self.config)
        self.reader_refresh()

    def _toggle_autostart(self):
        wanted = bool(self.autostart_var.get())
        try:
            set_autostart(wanted)
        except OSError as exc:
            messagebox.showerror("AI Usage Bar",
                                 "Gagal mengubah autostart: %s" % exc)
            self.autostart_var.set(not wanted)

    def quit(self):
        self.reader.stopping = True
        self.reader.refresh_now()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def main():
    make_dpi_aware()
    UsageBar().run()


if __name__ == "__main__":
    main()
