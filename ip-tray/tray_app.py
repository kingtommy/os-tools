"""IP Tray — system tray app showing local, public, and VPN IP addresses."""

import threading
import time
from io import BytesIO

import pystray
from PIL import Image, ImageDraw, ImageFont

from ip_providers import IPSnapshot, collect_snapshot

REFRESH_INTERVAL = 30  # seconds


class IPTray:
    def __init__(self):
        self.snapshot: IPSnapshot | None = None
        self.prev_public_ip: str = ""
        self.prev_local_ip: str = ""
        self.ip_changed: bool = False
        self.icon: pystray.Icon | None = None
        self._stop = threading.Event()

    # --- Icon rendering ---

    def _make_icon(self) -> Image.Image:
        """Generate a 64x64 tray icon. Green=normal, orange=VPN, red=IP changed."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if self.ip_changed:
            bg = (220, 50, 50)     # red — IP changed
        elif self.snapshot and self.snapshot.vpn_active:
            bg = (240, 160, 30)    # orange — VPN active
        else:
            bg = (50, 180, 80)     # green — normal

        # Rounded-ish circle
        draw.ellipse([4, 4, size - 4, size - 4], fill=bg)

        # "IP" text
        try:
            font = ImageFont.truetype("arial.ttf", 26)
        except Exception:
            font = ImageFont.load_default()

        text = "IP"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((size - tw) / 2, (size - th) / 2 - 2),
            text, fill="white", font=font,
        )
        return img

    # --- Tooltip ---

    def _tooltip(self) -> str:
        if not self.snapshot:
            return "IP Tray — loading..."

        s = self.snapshot
        lines = [f"Local: {s.primary_local_ip}"]
        lines.append(f"Public: {s.public_ip}")

        if s.vpn_active:
            vpn_label = s.vpn_name or "VPN"
            vpn_ip = s.vpn_ip
            lines.append(f"{vpn_label}: {vpn_ip}" if vpn_ip else f"{vpn_label}: active")

        if s.public_ip_upnp and s.public_ip_dns and s.public_ip_upnp != s.public_ip_dns:
            lines.append(f"(UPnP: {s.public_ip_upnp} / DNS: {s.public_ip_dns})")

        if self.ip_changed:
            lines.append("⚠ IP changed!")

        return " | ".join(lines)

    # --- Menu ---

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard via PowerShell (no extra deps)."""
        import subprocess
        subprocess.run(
            ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
            creationflags=0x08000000,
        )

    def _menu_copy(self, label: str, value: str):
        def action(icon, item):
            self._copy_to_clipboard(value)
        return pystray.MenuItem(f"{label}: {value}", action)

    def _build_menu(self) -> pystray.Menu:
        items = []

        if self.snapshot:
            s = self.snapshot

            # Local IPs
            items.append(self._menu_copy("Local", s.primary_local_ip))

            # Public IP
            items.append(self._menu_copy("Public", s.public_ip))

            # UPnP vs DNS detail
            if s.public_ip_upnp:
                items.append(self._menu_copy("  Router (UPnP)", s.public_ip_upnp))
            if s.public_ip_dns:
                items.append(self._menu_copy("  DNS (OpenDNS)", s.public_ip_dns))

            # VPN
            if s.vpn_active:
                vpn_label = s.vpn_name or "VPN"
                vpn_ip = s.vpn_ip or "active"
                items.append(self._menu_copy(vpn_label, vpn_ip))

            items.append(pystray.Menu.SEPARATOR)

            # All adapters submenu
            adapter_items = []
            for a in s.adapters:
                prefix = f"[VPN: {a.vpn_type}] " if a.is_vpn else ""
                adapter_items.append(self._menu_copy(f"{prefix}{a.name}", a.ip))
            if adapter_items:
                items.append(pystray.MenuItem("All adapters", pystray.Menu(*adapter_items)))

            # Errors
            if s.errors:
                items.append(pystray.MenuItem(
                    "Errors", pystray.Menu(
                        *[pystray.MenuItem(e, None, enabled=False) for e in s.errors]
                    )
                ))

            items.append(pystray.Menu.SEPARATOR)

            # Change indicator
            if self.ip_changed:
                items.append(pystray.MenuItem("⚠ IP changed since last check", None, enabled=False))
                items.append(pystray.MenuItem(
                    "Dismiss change alert",
                    lambda icon, item: self._dismiss_change(),
                ))
                items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem("Refresh now", lambda icon, item: self._refresh()))
        items.append(pystray.MenuItem("Quit", lambda icon, item: self._quit()))

        return pystray.Menu(*items)

    def _dismiss_change(self):
        self.ip_changed = False
        self._update_icon()

    # --- Refresh loop ---

    def _refresh(self):
        new_snap = collect_snapshot()

        # Detect changes
        if self.snapshot:
            old_pub = self.snapshot.public_ip
            new_pub = new_snap.public_ip
            old_local = self.snapshot.primary_local_ip
            new_local = new_snap.primary_local_ip

            if (old_pub != "unknown" and new_pub != old_pub) or \
               (old_local != "unknown" and new_local != old_local):
                self.ip_changed = True

        self.snapshot = new_snap
        self._update_icon()

    def _update_icon(self):
        if self.icon:
            self.icon.icon = self._make_icon()
            self.icon.title = self._tooltip()
            self.icon.menu = self._build_menu()

    def _refresh_loop(self):
        while not self._stop.is_set():
            self._refresh()
            self._stop.wait(REFRESH_INTERVAL)

    # --- Lifecycle ---

    def _quit(self):
        self._stop.set()
        if self.icon:
            self.icon.stop()

    def run(self):
        # Initial snapshot
        self._refresh()

        self.icon = pystray.Icon(
            name="ip-tray",
            icon=self._make_icon(),
            title=self._tooltip(),
            menu=self._build_menu(),
        )

        # Start background refresh
        t = threading.Thread(target=self._refresh_loop, daemon=True)
        t.start()

        self.icon.run()


def main():
    app = IPTray()
    app.run()


if __name__ == "__main__":
    main()
