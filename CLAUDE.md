# os-tools

Windows productivity tools — small, always-visible widgets for dev workflows. The goal is a suite of lightweight, visually consistent taskbar-area widgets that reduce context-switching friction for a developer who wears many hats.

## Project goals

- Build small, glanceable widgets that sit near the Windows taskbar
- Prioritize "always visible" info that saves trips to ipconfig, browser, task manager, etc.
- Each widget should be self-contained but share visual style (neutral grays, Windows-native look)
- Python + tkinter for the widget UI (no heavy frameworks)
- Minimize external dependencies — prefer stdlib, win32 APIs via ctypes, subprocess calls

## What's built

### ip-tray (v1 — complete)

Taskbar widget showing network status at a glance. Single-line bar with:

- **Monitor selector** — canvas-drawn monitor icon + number, click to cycle between 3 monitors
- **Port watcher** — stoplight icon + count, click for flyout with enriched port list
- **LAN IP** — click to copy
- **PUB IP** — click to copy, orange when VPN active
- **VPN status** — shows "No VPN" / "OpenVPN" / "AWS VPN", click to open AWS VPN Client
- **Status dot** — green (normal), orange (VPN), triangle (#FFCC00) when gaming/chat apps detected

#### Port flyout features
- Fixed-size popup (420x310) with persistent background frame (no flash on toggle)
- Three columns: Process (240px), Bind (80px), Port (50px)
- Color-coded: blue = HTTP web app (click to open in browser), yellow = Docker container, white = native process
- HTTP detection via cached socket probe (HEAD request, threaded, 0.3s timeout)
- Docker container names via `wsl docker ps`
- Eye icon toggle to show/hide filtered processes
- Process whitelist: mysql, mysqld, postgres, node, wslrelay

#### VPN features
- Fast mode (2s polling, #FFCC00 border) when VPN state change anticipated
- Fast mode timer resets on each click, auto-disables after 2 min or VPN state settles
- Treats "OpenVPN" as transitional state (doesn't end fast mode prematurely)
- Hover status dot → X icon, click to disconnect via elevated `disconnect-vpn.bat`
- Alert app detection (Battle.net, Discord, Steam) — triangle wiggles instead of opening VPN

## Project structure

```
ip-tray/              # IP + port monitor taskbar widget
  widget.py           # Main UI — tkinter always-on-top widget (run this)
  ip_providers.py     # Data collection: ipconfig, UPnP, DNS, netstat, docker, process detection
  tray_app.py         # Original system tray app (superseded by widget.py)
  disconnect-vpn.bat  # Elevated VPN disconnect script (UAC)
  requirements.txt    # pystray, Pillow (tray_app only; widget.py uses only tkinter)
ideas.md              # Future tool ideas — prioritized wishlist
CLAUDE.md             # This file
```

## Running

```bash
cd ip-tray
pip install -r requirements.txt   # only needed for tray_app.py
python widget.py                  # widget.py uses only tkinter (stdlib)
```

## Architecture patterns

### widget.py

- Single `IPWidget` class, all state on the instance
- **Always-on-top borderless window** via `overrideredirect(True)` + `attributes("-topmost", True)`
- **Multi-monitor positioning** — `get_monitors()` uses `EnumDisplayMonitors` + `GetMonitorInfoW` (ctypes) for per-monitor work areas. Position uses `winfo_reqwidth()` after `update_idletasks()` and forces geometry with explicit `WxH` to handle shrink correctly
- **Background refresh** — `collect_snapshot()` runs in `threading.Thread`, results posted back via `root.after(0, callback)`
- **Fast mode** — 2s polling triggered by VPN actions. Skips UPnP to avoid hammering router. Timer stored as `time.monotonic()`, reset on each activation
- **Port flyout** — `Toplevel` with fixed `width`/`height` + `pack_propagate(False)` on background frame. Content frame destroyed/recreated on toggle, background stays static (prevents flash)
- **Drag tracking** — `_user_dragged` flag prevents auto-reposition after manual drag. Reset when cycling monitors
- **Canvas icons** — monitor (rectangle + stand + number), port (stoplight with 2 dots), eye (bezier curves + pupil + optional strike), all drawn programmatically

### ip_providers.py

- `collect_snapshot(skip_upnp=False)` → `IPSnapshot` dataclass with all data
- Single `tasklist` call shared across VPN detection, alert app detection, and port PID mapping
- `PortInfo` dataclass with `interesting` property (whitelist filter) and `is_http` (cached probe)
- HTTP probe cache (`_http_cache` dict) — only probes new ports, cleans up stale entries
- UPnP: raw SSDP multicast → parse device XML → SOAP GetExternalIPAddress (no library needed)
- `ipconfig` parser handles IPv6 gateway continuation lines (common on Windows)

## Known issues / rough edges

- UPnP external IP not returning on user's setup — likely needs UPnP enabled on Nighthawk router (ADVANCED > Advanced Setup > UPnP)
- VPN disconnect UAC prompt says "Windows Command Processor" — inherent to .bat elevation, mitigated by showing filename in "more details"
- `wslrelay.exe` ports without Docker container match show as "wslrelay" — these are WSL-forwarded services (postgres, redis, vite) running directly in WSL, not Docker
- Port flyout popup doesn't auto-close when clicking elsewhere (no focus-loss handling)

## Wishlist / next up (see ideas.md)

Priority ideas based on user interest:
1. **More port flyout features** — actions per row (restart, open logs), better Docker integration
2. **CPU/RAM/GPU mini-gauge** — tiny bars in the widget bar
3. **Docker status widget** — container count, names, log access
4. **Clipboard history ring** — hotkey to cycle recent copies
5. **Git branch ticker** — current branch + staleness for key repos
6. **AWS profile switcher** — show/switch active AWS profile
7. **Env indicator** — dev/staging/prod awareness, red for prod

## Environment

- Windows 11 Pro, Python 3.12, tkinter (stdlib)
- 3 monitors: 1080p | 1440p (primary) | 1080p
- AWS VPN Client (OpenVPN under the hood)
- Docker via WSL2
- Netgear Nighthawk router + Netgear modem

## Style guide

- **Colors**: neutral grays, no blue tint. bg=#1e1e1e, text=#cccccc, label=#808080, border=#3a3a3a
- **Accent colors**: VPN orange=#e8a040, alert/Docker yellow=#FFCC00, HTTP blue=#5c9aff, OK green=#60b060, error red=#e05050
- **Font**: Segoe UI, size 9 (size 8 for labels/headers)
- **Icons**: canvas-drawn, thin strokes (~1px), color #585b70 for icon outlines
- **UX**: click to copy, click to open, hover for actions. No tooltips needed — everything visible
- **Window**: 92% opacity, 1px border, draggable from background areas
- **No emojis** in UI or code
