# IP Tray

System tray app that shows your IP addresses at a glance — local, public (via UPnP + DNS), and VPN status.

## Features

- **Local IP** from active network adapters
- **Public IP** via UPnP query to your router (no HTTP APIs) + DNS fallback via OpenDNS
- **VPN detection** — recognizes NordVPN, AWS VPN, WireGuard, OpenVPN, Cisco AnyConnect, and more
- **Auto-refresh** every 30 seconds
- **Click to copy** any IP to clipboard
- **Change detection** — icon turns red when your IP changes (VPN connect/disconnect, etc.)

## Icon colors

- 🟢 Green — normal
- 🟠 Orange — VPN active
- 🔴 Red — IP changed since last check

## Setup

```bash
cd ip-tray
pip install -r requirements.txt
python tray_app.py
```

## UPnP Note

Your router must have UPnP enabled. For Netgear Nighthawk:
ADVANCED > Advanced Setup > UPnP > Turn UPnP On
