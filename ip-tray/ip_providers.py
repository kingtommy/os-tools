"""IP address providers — local, UPnP, DNS, and VPN detection."""

import re
import socket
import struct
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.request import Request, urlopen


@dataclass
class AdapterInfo:
    name: str
    ip: str
    subnet: str = ""
    gateway: str = ""
    is_vpn: bool = False
    vpn_type: str = ""


@dataclass
class IPSnapshot:
    adapters: list[AdapterInfo] = field(default_factory=list)
    public_ip_upnp: str = ""
    public_ip_dns: str = ""
    vpn_active: bool = False
    vpn_name: str = ""
    alert_apps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def primary_local_ip(self) -> str:
        """Best local IP — first non-VPN adapter with a gateway, else first with an IP."""
        for a in self.adapters:
            if not a.is_vpn and a.gateway:
                return a.ip
        for a in self.adapters:
            if not a.is_vpn and a.ip:
                return a.ip
        return "unknown"

    @property
    def public_ip(self) -> str:
        """Best public IP — prefer UPnP, fall back to DNS."""
        return self.public_ip_upnp or self.public_ip_dns or "unknown"

    @property
    def vpn_ip(self) -> str:
        for a in self.adapters:
            if a.is_vpn:
                return a.ip
        return ""


# --- VPN adapter / process patterns ---

VPN_ADAPTER_PATTERNS = [
    # Order matters — more specific patterns first
    (r"AWS Client VPN", "AWS VPN"),
    (r"Amazon VPN", "AWS VPN"),
    (r"TAP-NordVPN", "NordVPN"),
    (r"NordLynx", "NordVPN (NordLynx)"),
    (r"TAP-Windows", "TAP VPN"),
    (r"WireGuard", "WireGuard"),
    (r"Cisco AnyConnect", "Cisco AnyConnect"),
    (r"Wintun", "WireGuard/VPN"),
    (r"tun\d+", "VPN Tunnel"),
    (r"GlobalProtect", "Palo Alto GlobalProtect"),
    (r"Fortinet", "FortiClient VPN"),
]

VPN_PROCESS_NAMES = {
    "nordvpn.exe": "NordVPN",
    "nordlynx.exe": "NordVPN",
    "openvpn.exe": "OpenVPN",
    "wireguard.exe": "WireGuard",
    "amazonvpnclient.exe": "AWS VPN",
    "vpnui.exe": "Cisco AnyConnect",
    "pangpa.exe": "Palo Alto GlobalProtect",
    "fortisslvpnclient.exe": "FortiClient VPN",
}


def get_local_adapters() -> list[AdapterInfo]:
    """Parse ipconfig /all for adapter IPs."""
    try:
        raw = subprocess.check_output(
            ["ipconfig", "/all"], text=True, creationflags=0x08000000  # CREATE_NO_WINDOW
        )
    except Exception:
        return []

    adapters = []
    current_name = ""
    current_ip = ""
    current_subnet = ""
    current_gateway = ""
    is_vpn = False
    vpn_type = ""

    def _flush():
        nonlocal current_name, current_ip, current_subnet, current_gateway, is_vpn, vpn_type
        if current_name and current_ip:
            adapters.append(AdapterInfo(
                name=current_name, ip=current_ip, subnet=current_subnet,
                gateway=current_gateway, is_vpn=is_vpn, vpn_type=vpn_type,
            ))
        current_name = current_ip = current_subnet = current_gateway = vpn_type = ""
        is_vpn = False

    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Adapter header — not indented, ends with ':'
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            _flush()
            current_name = line.rstrip(": \t").split("adapter")[-1].strip()
            # Check VPN patterns
            for pattern, vtype in VPN_ADAPTER_PATTERNS:
                if re.search(pattern, current_name, re.IGNORECASE):
                    is_vpn = True
                    vpn_type = vtype
                    break
        elif "IPv4 Address" in line or "IPv4" in line:
            m = re.search(r":\s*([\d.]+)", line)
            if m:
                current_ip = m.group(1)
        elif "Subnet Mask" in line:
            m = re.search(r":\s*([\d.]+)", line)
            if m:
                current_subnet = m.group(1)
        elif "Default Gateway" in line:
            # Gateway may be on this line or a continuation line (IPv6 first, IPv4 below)
            ipv4_re = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
            m = re.search(ipv4_re, line)
            if m:
                current_gateway = m.group(1)
            else:
                # Check continuation lines for an IPv4 address
                j = i + 1
                while j < len(lines) and lines[j].startswith("             "):
                    m = re.search(ipv4_re, lines[j])
                    if m:
                        current_gateway = m.group(1)
                        break
                    j += 1
        i += 1

    _flush()
    return adapters


ALERT_PROCESS_NAMES = {
    "battle.net.exe": "Battle.net",
    "discord.exe": "Discord",
    "steam.exe": "Steam",
}


def _get_tasklist() -> str:
    """Get tasklist output (cached per snapshot)."""
    try:
        return subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True, creationflags=0x08000000,
        )
    except Exception:
        return ""


def detect_vpn_processes(tasklist: str) -> tuple[bool, str]:
    """Check running processes for known VPN clients."""
    if not tasklist:
        return False, ""

    raw_lower = tasklist.lower()
    for proc, name in VPN_PROCESS_NAMES.items():
        if proc in raw_lower:
            return True, name
    return False, ""


def detect_alert_apps(tasklist: str) -> list[str]:
    """Check for running apps that warrant a warning (e.g. gaming, chat)."""
    if not tasklist:
        return []

    raw_lower = tasklist.lower()
    found = []
    for proc, name in ALERT_PROCESS_NAMES.items():
        if proc in raw_lower:
            found.append(name)
    return found


# --- UPnP IGD (router WAN IP) ---

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST:239.255.255.250:1900\r\n"
    'MAN:"ssdp:discover"\r\n'
    "MX:2\r\n"
    "ST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
    "\r\n"
)

SOAP_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
    ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>"
    "<u:GetExternalIPAddress"
    ' xmlns:u="urn:schemas-upnp-org:service:{service_type}" />'
    "</s:Body>"
    "</s:Envelope>"
)

SERVICE_TYPES = [
    "WANIPConnection:1",
    "WANPPPConnection:1",
]


def _ssdp_discover(timeout: float = 3.0) -> str | None:
    """Discover IGD device, return its LOCATION URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 2))
    sock.settimeout(timeout)
    try:
        sock.sendto(SSDP_SEARCH.encode(), (SSDP_ADDR, SSDP_PORT))
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                text = data.decode(errors="replace")
                if "InternetGatewayDevice" in text:
                    for line in text.splitlines():
                        if line.upper().startswith("LOCATION:"):
                            return line.split(":", 1)[1].strip()
            except socket.timeout:
                break
    finally:
        sock.close()
    return None


def _find_control_url(desc_url: str) -> tuple[str, str] | None:
    """Fetch device description XML, find WANIPConnection control URL."""
    try:
        req = Request(desc_url, headers={"User-Agent": "IPTray/1.0"})
        with urlopen(req, timeout=5) as resp:
            xml_data = resp.read()
    except Exception:
        return None

    # Parse XML — strip namespaces for easier searching
    xml_text = re.sub(r' xmlns="[^"]+"', "", xml_data.decode(errors="replace"))
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # Search for WANIPConnection or WANPPPConnection service
    for svc_type in SERVICE_TYPES:
        full_type = f"urn:schemas-upnp-org:service:{svc_type}"
        for svc in root.iter("service"):
            st = svc.findtext("serviceType", "")
            if svc_type in st:
                control = svc.findtext("controlURL", "")
                if control:
                    # Build absolute URL
                    from urllib.parse import urljoin
                    base = desc_url
                    return urljoin(base, control), svc_type
    return None


def get_upnp_external_ip(timeout: float = 3.0) -> str:
    """Get external IP from router via UPnP IGD."""
    location = _ssdp_discover(timeout)
    if not location:
        return ""

    result = _find_control_url(location)
    if not result:
        return ""

    control_url, svc_type = result
    soap = SOAP_BODY.format(service_type=svc_type)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"urn:schemas-upnp-org:service:{svc_type}#GetExternalIPAddress"',
        "User-Agent": "IPTray/1.0",
    }

    try:
        req = Request(control_url, data=soap.encode(), headers=headers, method="POST")
        with urlopen(req, timeout=5) as resp:
            body = resp.read().decode(errors="replace")
    except Exception:
        return ""

    m = re.search(r"<NewExternalIPAddress>([^<]+)</NewExternalIPAddress>", body)
    return m.group(1) if m else ""


# --- DNS-based public IP ---

def get_dns_external_ip(timeout: float = 3.0) -> str:
    """Get public IP via DNS query to OpenDNS."""
    try:
        result = subprocess.check_output(
            ["nslookup", "myip.opendns.com", "resolver1.opendns.com"],
            text=True, timeout=timeout, creationflags=0x08000000,
            stderr=subprocess.DEVNULL,
        )
        # The answer is the last IP in the output
        ips = re.findall(r"\d+\.\d+\.\d+\.\d+", result)
        # Filter out the resolver IP (208.67.222.222)
        for ip in reversed(ips):
            if not ip.startswith("208.67."):
                return ip
    except Exception:
        pass
    return ""


# --- Full snapshot ---

def collect_snapshot(skip_upnp: bool = False) -> IPSnapshot:
    """Collect all IP information into a snapshot."""
    snap = IPSnapshot()

    # Local adapters
    snap.adapters = get_local_adapters()

    # VPN from adapters
    for a in snap.adapters:
        if a.is_vpn:
            snap.vpn_active = True
            snap.vpn_name = a.vpn_type
            break

    # Process checks (single tasklist call)
    tasklist = _get_tasklist()

    # VPN from processes (if not already detected)
    if not snap.vpn_active:
        snap.vpn_active, snap.vpn_name = detect_vpn_processes(tasklist)

    # Alert apps
    snap.alert_apps = detect_alert_apps(tasklist)

    # UPnP external IP (skip in fast mode to avoid hammering router)
    if not skip_upnp:
        try:
            snap.public_ip_upnp = get_upnp_external_ip()
        except Exception as e:
            snap.errors.append(f"UPnP: {e}")

    # DNS external IP
    try:
        snap.public_ip_dns = get_dns_external_ip()
    except Exception as e:
        snap.errors.append(f"DNS: {e}")

    return snap
