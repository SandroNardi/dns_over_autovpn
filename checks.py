"""Turn Dashboard DHCP fields into report text. No Dashboard calls here."""

from __future__ import annotations

import ipaddress

MX_PRESETS = {
    "upstream_dns": "Proxy to upstream DNS",
    "google_dns": "Google Public DNS",
    "opendns": "Cisco Umbrella / OpenDNS",
}

SWITCH_PRESETS = {
    "googlePublicDns": "Google Public DNS",
    "openDns": "OpenDNS",
}

MX_DHCP_MODES = {
    "Run a DHCP server": "DHCP server",
    "Relay DHCP to another server": "DHCP relay",
    "Do not respond to DHCP requests": "DHCP disabled",
}

SWITCH_DHCP_MODES = {
    "dhcpServer": "DHCP server",
    "dhcpRelay": "DHCP relay",
    "dhcpDisabled": "DHCP disabled",
}


def api_error_text(exc):
    """Return the Dashboard error as plain text. The SDK message may be a dict or a list."""
    message = getattr(exc, "message", None)
    if isinstance(message, dict):
        errors = message.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(str(item) for item in errors)
        return str(message)
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    if message:
        return str(message)
    return str(exc) or exc.__class__.__name__


def normalize_ip(value):
    text = str(value or "").strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text


def split_servers(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = str(value).replace(",", "\n").splitlines()
    return [normalize_ip(part) for part in parts if part.strip()]


def mx_dns(value):
    """MX dnsNameservers is a preset name or newline-separated addresses."""
    text = str(value or "").strip()
    if not text:
        return {"type": "Not set", "servers": [], "label": "Not set"}
    if text in MX_PRESETS:
        return {"type": "Preset", "servers": [], "label": f"Preset: {MX_PRESETS[text]} ({text})"}
    servers = split_servers(text)
    return {"type": "Custom", "servers": servers, "label": ", ".join(servers)}


def switch_dns(option, custom):
    """Switch DHCP uses dnsNameserversOption plus dnsCustomNameservers when custom."""
    if option == "custom":
        servers = split_servers(custom or [])
        return {"type": "Custom", "servers": servers, "label": ", ".join(servers) or "Custom (empty)"}
    if option in SWITCH_PRESETS:
        return {"type": "Preset", "servers": [], "label": f"Preset: {SWITCH_PRESETS[option]} ({option})"}
    if not option:
        return {"type": "Not set", "servers": [], "label": "Not set"}
    return {"type": "Preset", "servers": [], "label": f"Preset: {option}"}


def option6_note(options):
    """Return a note when DHCP option 6 overrides the DNS list clients receive."""
    for option in options or []:
        if not isinstance(option, dict):
            continue
        if str(option.get("code")) == "6":
            return f"DHCP option 6 is also set ({option.get('value')}); clients may receive that DNS list instead."
    return ""
