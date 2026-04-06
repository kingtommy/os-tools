# IP Widget

Always-on-top taskbar widget showing network status at a glance. Sits near the Windows taskbar as a slim, draggable bar.

## Features

- **LAN IP** / **Public IP** — click to copy
- **VPN status** — shows No VPN / OpenVPN / AWS VPN, click to open AWS VPN Client
- **Port watcher** — stoplight icon + count, click for flyout with enriched port list
- **Monitor selector** — click to cycle widget across monitors
- **Status dot** — green (normal), orange (VPN), triangle when gaming/chat apps detected
- **Auto-refresh** every 30 seconds (2s in fast mode after VPN actions)

## Running

```bash
python ip-tray/widget.py
```

Works from any directory. No dependencies beyond Python 3.12 + tkinter (stdlib).

### Windowless mode

To run without a terminal window:

```bash
pythonw ip-tray/widget.py
```

## Finding and stopping the process

List Python processes (may take several seconds on Windows — this is normal):

```bash
tasklist /FI "IMAGENAME eq python*" /V
```

The widget shows up as `pythonw.exe` with window title "IP Widget". Kill it by PID:

```bash
taskkill /F /PID <pid>
```

## Legacy

`tray_app.py` is the original system tray version (superseded by `widget.py`). It requires `pystray` and `Pillow`:

```bash
pip install -r requirements.txt
python ip-tray/tray_app.py
```

## UPnP Note

For public IP via UPnP, your router must have UPnP enabled. For Netgear Nighthawk:
ADVANCED > Advanced Setup > UPnP > Turn UPnP On
