"""IP Widget — always-on-top taskbar widget showing local, public, and VPN IPs."""

import ctypes
import ctypes.wintypes
import threading
import tkinter as tk
from tkinter import font as tkfont

from ip_providers import IPSnapshot, collect_snapshot

REFRESH_INTERVAL_MS = 30_000  # 30 seconds
BG_COLOR = "#1e1e2e"
TEXT_COLOR = "#cdd6f4"
LABEL_COLOR = "#7f849c"
VPN_COLOR = "#fab387"
CHANGED_COLOR = "#f38ba8"
OK_COLOR = "#a6e3a1"
BORDER_COLOR = "#45475a"
FONT_FAMILY = "Segoe UI"
FONT_SIZE = 9


class MonitorInfo:
    """Full and work-area rects for a single monitor."""
    __slots__ = ("left", "top", "right", "bottom",
                 "work_left", "work_top", "work_right", "work_bottom", "primary")

    def __init__(self, full: tuple, work: tuple, primary: bool):
        self.left, self.top, self.right, self.bottom = full
        self.work_left, self.work_top, self.work_right, self.work_bottom = work
        self.primary = primary


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def get_monitors() -> list[MonitorInfo]:
    """Return MonitorInfo for each display, sorted left-to-right."""
    monitors: list[MonitorInfo] = []

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        m = info.rcMonitor
        w = info.rcWork
        monitors.append(MonitorInfo(
            full=(m.left, m.top, m.right, m.bottom),
            work=(w.left, w.top, w.right, w.bottom),
            primary=bool(info.dwFlags & 1),
        ))
        return True

    proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HMONITOR, ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT), ctypes.wintypes.LPARAM,
    )
    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    monitors.sort(key=lambda m: (m.left, m.top))
    return monitors


class IPWidget:
    def __init__(self):
        self.snapshot: IPSnapshot | None = None
        self.prev_public_ip: str = ""
        self.prev_local_ip: str = ""
        self.ip_changed: bool = False
        self.monitors: list[MonitorInfo] = get_monitors()
        self.current_monitor: int = 0  # start on primary
        self._user_dragged: bool = False
        self._build_ui()

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("IP Widget")
        self.root.overrideredirect(True)       # borderless
        self.root.attributes("-topmost", True)  # always on top
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg=BG_COLOR)

        # Make window click-through-able for the taskbar beneath, but still interactive
        # We'll use a thin border to make it feel like a widget
        self.frame = tk.Frame(
            self.root, bg=BG_COLOR,
            highlightbackground=BORDER_COLOR, highlightthickness=1,
        )
        self.frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Inner content with padding
        self.inner = tk.Frame(self.frame, bg=BG_COLOR)
        self.inner.pack(padx=6, pady=3)

        label_font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE - 1)
        value_font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE, weight="bold")

        col = 0

        # Monitor cycle button — canvas-drawn monitor icon with stand
        self._mon_canvas_w = 24
        self._mon_canvas_h = 16
        self.monitor_btn = tk.Canvas(
            self.inner, width=self._mon_canvas_w, height=self._mon_canvas_h,
            bg=BG_COLOR, highlightthickness=0, cursor="hand2",
        )
        self.monitor_btn.grid(row=0, column=col, padx=(0, 2))
        self.monitor_btn.bind("<Button-1>", lambda e: self._cycle_monitor())
        self._draw_monitor_icon()
        col += 1

        tk.Frame(self.inner, bg=BORDER_COLOR, width=1).grid(
            row=0, column=col, rowspan=2, sticky="ns", padx=4,
        )
        col += 1

        # Local IP
        tk.Label(self.inner, text="LAN", font=label_font, fg=LABEL_COLOR,
                 bg=BG_COLOR).grid(row=0, column=col, sticky="e", padx=(0, 4))
        col += 1
        self.local_label = tk.Label(
            self.inner, text="...", font=value_font, fg=TEXT_COLOR,
            bg=BG_COLOR, cursor="hand2",
        )
        self.local_label.grid(row=0, column=col, sticky="w")
        self.local_label.bind("<Button-1>", lambda e: self._copy(self._local_ip()))
        col += 1

        # Separator
        tk.Frame(self.inner, bg=BORDER_COLOR, width=1).grid(
            row=0, column=col, rowspan=2, sticky="ns", padx=6,
        )
        col += 1

        # Public IP
        tk.Label(self.inner, text="PUB", font=label_font, fg=LABEL_COLOR,
                 bg=BG_COLOR).grid(row=0, column=col, sticky="e", padx=(0, 4))
        col += 1
        self.public_label = tk.Label(
            self.inner, text="...", font=value_font, fg=TEXT_COLOR,
            bg=BG_COLOR, cursor="hand2",
        )
        self.public_label.grid(row=0, column=col, sticky="w")
        self.public_label.bind("<Button-1>", lambda e: self._copy(self._public_ip()))
        col += 1

        # VPN indicator
        tk.Frame(self.inner, bg=BORDER_COLOR, width=1).grid(
            row=0, column=col, rowspan=2, sticky="ns", padx=6,
        )
        col += 1
        self.vpn_label = tk.Label(
            self.inner, text="", font=label_font, fg=VPN_COLOR,
            bg=BG_COLOR, cursor="hand2",
        )
        self.vpn_label.grid(row=0, column=col, sticky="w")
        self.vpn_label.bind("<Button-1>", lambda e: self._copy(self._vpn_ip()))
        col += 1

        # Status dot — shows green/orange/red
        self.status_dot = tk.Canvas(
            self.inner, width=8, height=8, bg=BG_COLOR,
            highlightthickness=0, cursor="hand2",
        )
        self.status_dot.grid(row=0, column=col, padx=(6, 0))
        self._draw_dot(LABEL_COLOR)
        self.status_dot.bind("<Button-1>", lambda e: self._dismiss_change())

        # Drag support — drag from anywhere on the frame
        self._drag_data = {"x": 0, "y": 0}
        for w in [self.frame, self.inner]:
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_motion)

        # Right-click to quit
        self.root.bind("<Button-3>", self._show_context_menu)

        # Copied toast label (hidden by default)
        self.toast_label = tk.Label(
            self.root, text="Copied!", font=label_font,
            fg=OK_COLOR, bg=BG_COLOR,
        )

        # Start refresh cycle — position after first data arrives
        self._refresh()

    def _draw_monitor_icon(self):
        """Draw a small monitor with stand, number to the right."""
        c = self.monitor_btn
        cw, ch = self._mon_canvas_w, self._mon_canvas_h
        c.delete("all")

        color = "#585b70"
        num = str(self.current_monitor + 1)

        # Screen — small rectangle on the left side
        sx1, sy1 = 1, 3
        sx2, sy2 = 14, 13
        c.create_rectangle(sx1, sy1, sx2, sy2, outline=color, width=1)

        # Neck
        mid_x = (sx1 + sx2) // 2
        c.create_line(mid_x, sy2, mid_x, sy2 + 2, fill=color, width=1)

        # Base
        c.create_line(mid_x - 4, sy2 + 2, mid_x + 4, sy2 + 2, fill=color, width=1)

        # Number to the right of the icon
        c.create_text(sx2 + 6, (sy1 + sy2) / 2, text=num, fill=LABEL_COLOR,
                      font=(FONT_FAMILY, FONT_SIZE - 2), anchor="w")

    def _cycle_monitor(self):
        """Move widget to the next monitor (1 → 2 → 3 → 1 ...)."""
        self.monitors = get_monitors()  # refresh in case monitors changed
        if not self.monitors:
            return
        self.current_monitor = (self.current_monitor + 1) % len(self.monitors)
        self._user_dragged = False
        self._draw_monitor_icon()
        self._position_widget()

    def _position_widget(self):
        """Position widget at bottom-right of current monitor's work area."""
        # Force full layout pass so sizes are accurate
        self.root.update_idletasks()

        if self.monitors and self.current_monitor < len(self.monitors):
            mon = self.monitors[self.current_monitor]
        else:
            self.root.geometry("+100+100")
            return

        # Use actual rendered size (more reliable than reqwidth after updates)
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        # Fall back to requested size if window hasn't been mapped yet
        if w <= 1:
            w = self.root.winfo_reqwidth()
        if h <= 1:
            h = self.root.winfo_reqheight()

        x = mon.work_right - w - 8
        y = mon.work_bottom - h - 4
        self.root.geometry(f"+{x}+{y}")

    # --- Drag ---

    def _drag_start(self, event):
        self._drag_data["x"] = event.x_root - self.root.winfo_x()
        self._drag_data["y"] = event.y_root - self.root.winfo_y()

    def _drag_motion(self, event):
        x = event.x_root - self._drag_data["x"]
        y = event.y_root - self._drag_data["y"]
        self.root.geometry(f"+{x}+{y}")
        self._user_dragged = True

    # --- Context menu ---

    def _show_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Refresh now", command=self._refresh)
        if self.ip_changed:
            menu.add_command(label="Dismiss alert", command=self._dismiss_change)
        menu.add_separator()
        menu.add_command(label="Quit", command=self.root.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    # --- Copy ---

    def _local_ip(self) -> str:
        return self.snapshot.primary_local_ip if self.snapshot else ""

    def _public_ip(self) -> str:
        return self.snapshot.public_ip if self.snapshot else ""

    def _vpn_ip(self) -> str:
        return self.snapshot.vpn_ip if self.snapshot else ""

    def _copy(self, text: str):
        if not text or text == "unknown":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        # Show toast
        self.toast_label.place(relx=0.5, rely=0.5, anchor="center")
        self.root.after(800, lambda: self.toast_label.place_forget())

    # --- Status dot ---

    def _draw_dot(self, color: str):
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 7, 7, fill=color, outline=color)

    def _dismiss_change(self):
        self.ip_changed = False
        self._update_display()

    # --- Refresh ---

    def _refresh(self):
        def _do():
            snap = collect_snapshot()
            self.root.after(0, lambda: self._on_snapshot(snap))

        threading.Thread(target=_do, daemon=True).start()

    def _on_snapshot(self, snap: IPSnapshot):
        # Detect changes
        if self.snapshot:
            old_pub = self.snapshot.public_ip
            new_pub = snap.public_ip
            old_local = self.snapshot.primary_local_ip
            new_local = snap.primary_local_ip
            if (old_pub != "unknown" and new_pub != old_pub) or \
               (old_local != "unknown" and new_local != old_local):
                self.ip_changed = True

        self.snapshot = snap
        self._update_display()

        # Reposition after layout settles (labels may have changed width)
        if not self._user_dragged:
            self.root.after(50, self._position_widget)

        # Schedule next refresh
        self.root.after(REFRESH_INTERVAL_MS, self._refresh)

    def _update_display(self):
        if not self.snapshot:
            return
        s = self.snapshot

        self.local_label.config(text=s.primary_local_ip)
        self.public_label.config(text=s.public_ip)

        # VPN
        if s.vpn_active:
            vpn_text = s.vpn_name or "VPN"
            if s.vpn_ip:
                vpn_text += f"  {s.vpn_ip}"
            self.vpn_label.config(text=vpn_text, fg=VPN_COLOR)
        else:
            self.vpn_label.config(text="No VPN", fg=LABEL_COLOR)

        # Status dot
        if self.ip_changed:
            self._draw_dot(CHANGED_COLOR)
        elif s.vpn_active:
            self._draw_dot(VPN_COLOR)
        else:
            self._draw_dot(OK_COLOR)

        # If UPnP and DNS disagree, tint public IP
        if s.public_ip_upnp and s.public_ip_dns and s.public_ip_upnp != s.public_ip_dns:
            self.public_label.config(fg=CHANGED_COLOR)
        else:
            self.public_label.config(fg=TEXT_COLOR)

    def run(self):
        self.root.mainloop()


def main():
    # DPI awareness for crisp text on HiDPI displays
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    app = IPWidget()
    app.run()


if __name__ == "__main__":
    main()
