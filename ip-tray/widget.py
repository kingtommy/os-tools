"""IP Widget — always-on-top taskbar widget showing local, public, and VPN IPs."""

import ctypes
import ctypes.wintypes
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from ip_providers import IPSnapshot, collect_snapshot

REFRESH_INTERVAL_MS = 30_000       # 30 seconds — normal mode
FAST_REFRESH_INTERVAL_MS = 2_000   # 2 seconds — fast mode
FAST_MODE_TIMEOUT = 120            # 2 minutes
BG_COLOR = "#1e1e1e"
TEXT_COLOR = "#cccccc"
LABEL_COLOR = "#808080"
VPN_COLOR = "#e8a040"
CHANGED_COLOR = "#e05050"
OK_COLOR = "#60b060"
BORDER_COLOR = "#3a3a3a"
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
        self.monitors: list[MonitorInfo] = get_monitors()
        self.current_monitor: int = 0  # start on primary
        self._user_dragged: bool = False
        self._fast_mode: bool = False
        self._fast_mode_start: float = 0.0
        self._vpn_state_at_fast_start: bool = False
        self._dot_hovered: bool = False
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
        self.pub_tag = tk.Label(self.inner, text="PUB", font=label_font, fg=LABEL_COLOR,
                 bg=BG_COLOR)
        self.pub_tag.grid(row=0, column=col, sticky="e", padx=(0, 4))
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
        self.vpn_label.bind("<Button-1>", lambda e: self._vpn_click())
        col += 1

        # Status dot — shows green/orange/red, becomes X on hover when VPN active
        self._dot_size = 10
        self.status_dot = tk.Canvas(
            self.inner, width=self._dot_size, height=self._dot_size, bg=BG_COLOR,
            highlightthickness=0, cursor="hand2",
        )
        self.status_dot.grid(row=0, column=col, padx=(6, 0))
        self._draw_dot(LABEL_COLOR)
        self.status_dot.bind("<Enter>", self._dot_enter)
        self.status_dot.bind("<Leave>", self._dot_leave)
        self.status_dot.bind("<Button-1>", lambda e: self._dot_click())

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

    AWS_VPN_LNK = (
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
        r"\AWS VPN Client\AWS VPN Client.lnk"
    )

    def _vpn_click(self):
        """Open AWS VPN Client. If alert apps running and not connected, wiggle instead."""
        import os
        # If not connected and alert apps are running, wiggle the triangle
        if not (self.snapshot and self.snapshot.vpn_active):
            if self.snapshot and self.snapshot.alert_apps:
                self._wiggle_triangle()
                return
        if os.path.exists(self.AWS_VPN_LNK):
            os.startfile(self.AWS_VPN_LNK)
        self._enable_fast_mode()

    def _wiggle_triangle(self, count: int = 0):
        """Animate the status dot with a left-right wiggle."""
        if count >= 6:
            # Reset position
            self.status_dot.grid(padx=(6, 0))
            return
        # Alternate left/right offset
        offset = 3 if count % 2 == 0 else -3
        self.status_dot.grid(padx=(6 + offset, 0))
        self.root.after(60, self._wiggle_triangle, count + 1)

    # --- Fast mode ---

    def _enable_fast_mode(self):
        """Enable fast polling (2s) with visual indicator."""
        self._fast_mode = True
        self._fast_mode_start = time.monotonic()
        self._vpn_state_at_fast_start = (
            self.snapshot.vpn_active if self.snapshot else False
        )
        self.frame.config(highlightbackground="#FFCC00", highlightthickness=1)
        # Kick off a fast refresh immediately
        self._refresh()

    def _disable_fast_mode(self):
        """Return to normal polling."""
        self._fast_mode = False
        self.frame.config(highlightbackground=BORDER_COLOR, highlightthickness=1)

    def _check_fast_mode(self):
        """Auto-disable fast mode on timeout or VPN state change."""
        if not self._fast_mode:
            return

        # Timeout
        if time.monotonic() - self._fast_mode_start >= FAST_MODE_TIMEOUT:
            self._disable_fast_mode()
            return

        # VPN state fully changed — wait for a named VPN (not transitional like OpenVPN)
        if self.snapshot:
            current_vpn = self.snapshot.vpn_active
            vpn_name = self.snapshot.vpn_name or ""
            transitional = vpn_name.lower() in ("tap vpn", "openvpn")
            if current_vpn != self._vpn_state_at_fast_start and not transitional:
                self._disable_fast_mode()
                return

    def _copy(self, text: str):
        if not text or text == "unknown":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        # Show toast
        self.toast_label.place(relx=0.5, rely=0.5, anchor="center")
        self.root.after(800, lambda: self.toast_label.place_forget())

    # --- Status dot / disconnect X ---

    def _draw_dot(self, color: str):
        self.status_dot.delete("all")
        s = self._dot_size
        if self._dot_hovered and self.snapshot and self.snapshot.vpn_active:
            # Draw X for disconnect
            pad = 2
            self.status_dot.create_line(pad, pad, s - pad, s - pad, fill=CHANGED_COLOR, width=1.5)
            self.status_dot.create_line(s - pad, pad, pad, s - pad, fill=CHANGED_COLOR, width=1.5)
        elif self.snapshot and self.snapshot.alert_apps:
            # Warning triangle
            cx = s / 2
            self.status_dot.create_polygon(
                cx, 0, s, s, 0, s,
                outline="#FFCC00", fill="#FFCC00",
            )
        else:
            self.status_dot.create_oval(1, 1, s - 2, s - 2, fill=color, outline=color)

    def _dot_enter(self, event):
        self._dot_hovered = True
        self._redraw_dot()

    def _dot_leave(self, event):
        self._dot_hovered = False
        self._redraw_dot()

    def _redraw_dot(self):
        """Redraw dot with current state colors."""
        if not self.snapshot:
            self._draw_dot(LABEL_COLOR)
        elif self.snapshot.vpn_active:
            self._draw_dot(VPN_COLOR)
        else:
            self._draw_dot(OK_COLOR)

    def _dot_click(self):
        """Click: disconnect VPN if active."""
        if self.snapshot and self.snapshot.vpn_active:
            self._disconnect_vpn()

    def _disconnect_vpn(self):
        """Stop the AWS VPN service (requires UAC elevation) and kill the GUI."""
        import subprocess

        # Stop the service via elevated PowerShell (triggers UAC prompt)
        svc_name = "AWS VPN Client OpenVPN Service"
        ps_cmd = f"Stop-Service '{svc_name}' -Force; Start-Service '{svc_name}'"
        try:
            subprocess.Popen(
                [
                    "powershell", "-Command",
                    f"Start-Process powershell -Verb RunAs -WindowStyle Hidden "
                    f"-ArgumentList '-Command {ps_cmd}'"
                ],
                creationflags=0x08000000,
            )
        except Exception:
            pass

        # Kill the GUI
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "AWSVPNClient.exe"],
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

        # Enable fast mode to track the disconnect
        self._enable_fast_mode()

    # --- Refresh ---

    def _refresh(self):
        fast = self._fast_mode

        def _do():
            snap = collect_snapshot(skip_upnp=fast)
            self.root.after(0, lambda: self._on_snapshot(snap))

        threading.Thread(target=_do, daemon=True).start()

    def _on_snapshot(self, snap: IPSnapshot):
        self.snapshot = snap
        self._update_display()

        # Check if fast mode should end
        self._check_fast_mode()

        # Reposition after layout settles (labels may have changed width)
        if not self._user_dragged:
            self.root.after(50, self._position_widget)

        # Schedule next refresh at appropriate interval
        interval = FAST_REFRESH_INTERVAL_MS if self._fast_mode else REFRESH_INTERVAL_MS
        self.root.after(interval, self._refresh)

    def _update_display(self):
        if not self.snapshot:
            return
        s = self.snapshot

        self.local_label.config(text=s.primary_local_ip)
        self.public_label.config(text=s.public_ip)

        # VPN
        if s.vpn_active:
            self.vpn_label.config(text=s.vpn_name or "VPN", fg=VPN_COLOR)
        else:
            self.vpn_label.config(text="No VPN", fg=LABEL_COLOR)

        # Status dot — green/orange based on VPN state
        self._draw_dot(VPN_COLOR if s.vpn_active else OK_COLOR)

        # Public IP color — orange when VPN, red if UPnP/DNS disagree
        if s.public_ip_upnp and s.public_ip_dns and s.public_ip_upnp != s.public_ip_dns:
            self.pub_tag.config(fg=CHANGED_COLOR)
            self.public_label.config(fg=CHANGED_COLOR)
        elif s.vpn_active:
            self.pub_tag.config(fg=VPN_COLOR)
            self.public_label.config(fg=VPN_COLOR)
        else:
            self.pub_tag.config(fg=LABEL_COLOR)
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
