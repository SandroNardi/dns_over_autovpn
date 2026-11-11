"""Read-only Auto VPN and VLAN 1 DHCP DNS inventory for one organization."""

from __future__ import annotations

import time

import meraki
from rich.markup import escape

from checks import (
    MX_DHCP_MODES,
    SWITCH_DHCP_MODES,
    api_error_text,
    mx_dns,
    option6_note,
    split_servers,
    switch_dns,
)
from core.logger import logger

API_CALL_COUNTER = 0
VPN_ROLES = {"hub": "Hub", "spoke": "Spoke", "none": "Off"}


def _call(endpoint, method, *args, **kwargs):
    global API_CALL_COUNTER
    API_CALL_COUNTER += 1
    logger.debug(f"[API CALL #{API_CALL_COUNTER}] {endpoint}")
    return method(*args, **kwargs)


def _status(exc):
    return getattr(exc, "status", None)


def list_organizations(dashboard):
    return _call("organizations.getOrganizations", dashboard.organizations.getOrganizations) or []


def _not_checked(reason):
    return {
        "mx": {
            "status": f"Not checked ({reason})",
            "dhcp": "",
            "dns_type": "",
            "dns": "",
            "servers": [],
            "subnet": "",
        },
        "switch": {
            "l3": "Not checked",
            "summary": "",
            "vlan1": "",
            "dhcp": "",
            "dns_type": "",
            "dns": "",
            "servers": [],
            "interfaces": [],
        },
    }


def read_vpn(dashboard, network_id, names):
    """Return (role, hubs). Hubs keep the configured order, which is their priority."""
    vpn = _call(
        "appliance.getNetworkApplianceVpnSiteToSiteVpn",
        dashboard.appliance.getNetworkApplianceVpnSiteToSiteVpn,
        network_id,
    ) or {}
    mode = str(vpn.get("mode") or "none").strip().lower()
    role = VPN_ROLES.get(mode, mode.title() or "Off")
    hubs = []
    for priority, hub in enumerate(vpn.get("hubs") or [], start=1):
        hub_id = hub.get("hubId") or ""
        hubs.append(
            {
                "priority": priority,
                "hub_id": hub_id,
                "hub_name": names.get(hub_id) or f"Unknown network ({hub_id})",
                "default_route": bool(hub.get("useDefaultRoute")),
                "tunnel": "",
            }
        )
    return role, hubs


def _mx_from_vlan(vlan):
    handling = vlan.get("dhcpHandling") or ""
    result = {
        "status": "",
        "dhcp": MX_DHCP_MODES.get(handling, handling or "Unknown"),
        "dns_type": "",
        "dns": "",
        "servers": [],
        "subnet": vlan.get("subnet") or "",
        "notes": [],
    }
    if handling == "Run a DHCP server":
        parsed = mx_dns(vlan.get("dnsNameservers"))
        result.update(
            status="DHCP server",
            dns_type=parsed["type"],
            dns=parsed["label"],
            servers=parsed["servers"],
        )
        note = option6_note(vlan.get("dhcpOptions"))
        if note:
            result["notes"].append(f"MX VLAN 1: {note}")
    elif handling == "Relay DHCP to another server":
        relays = ", ".join(split_servers(vlan.get("dhcpRelayServerIps") or [])) or "no relay IPs"
        result.update(status="DHCP relay", dns_type="n/a", dns=f"n/a (relays to {relays})")
    elif handling == "Do not respond to DHCP requests":
        result.update(status="DHCP disabled", dns_type="n/a", dns="n/a")
    else:
        result.update(status=f"Unrecognized DHCP mode: {handling or 'none'}", dns_type="n/a", dns="n/a")
    return result


def _mx_result(status, dns_type="n/a", dns="n/a", subnet="", notes=None):
    return {
        "status": status,
        "dhcp": "",
        "dns_type": dns_type,
        "dns": dns,
        "servers": [],
        "subnet": subnet,
        "notes": list(notes or []),
    }


def _classify_missing_vlan1(dashboard, network_id, exc):
    """VLAN 1 read returned 400 or 404. Decide between passthrough, single LAN, and no VLAN 1."""
    try:
        settings = _call(
            "appliance.getNetworkApplianceSettings",
            dashboard.appliance.getNetworkApplianceSettings,
            network_id,
        ) or {}
    except meraki.APIError as settings_exc:
        return _mx_result("Read error", notes=[f"MX VLAN 1: {api_error_text(settings_exc)}"])
    if str(settings.get("deploymentMode") or "").strip().lower() == "passthrough":
        return _mx_result("Passthrough mode (no MX LAN)")

    try:
        vlan_settings = _call(
            "appliance.getNetworkApplianceVlansSettings",
            dashboard.appliance.getNetworkApplianceVlansSettings,
            network_id,
        ) or {}
        vlans_enabled = bool(vlan_settings.get("vlansEnabled", True))
    except meraki.APIError as vlan_exc:
        if "not enabled" not in api_error_text(vlan_exc).lower():
            return _mx_result("Read error", notes=[f"MX VLAN settings: {api_error_text(vlan_exc)}"])
        vlans_enabled = False

    if not vlans_enabled:
        subnet = ""
        notes = []
        try:
            single = _call(
                "appliance.getNetworkApplianceSingleLan",
                dashboard.appliance.getNetworkApplianceSingleLan,
                network_id,
            ) or {}
            subnet = single.get("subnet") or ""
        except meraki.APIError as single_exc:
            notes.append(f"Single LAN: {api_error_text(single_exc)}")
        return _mx_result(
            "VLANs disabled (single LAN)",
            dns_type="Not exposed",
            dns="Not returned by the API in single-LAN mode",
            subnet=subnet,
            notes=notes,
        )
    if _status(exc) == 404:
        return _mx_result("VLAN 1 not configured")
    return _mx_result("Read error", notes=[f"MX VLAN 1: {api_error_text(exc)}"])


def read_mx_vlan1(dashboard, network_id):
    try:
        vlan = _call(
            "appliance.getNetworkApplianceVlan",
            dashboard.appliance.getNetworkApplianceVlan,
            network_id,
            "1",
        ) or {}
    except meraki.APIError as exc:
        if _status(exc) in (400, 404):
            return _classify_missing_vlan1(dashboard, network_id, exc)
        return _mx_result("Read error", notes=[f"MX VLAN 1: {api_error_text(exc)}"])
    return _mx_from_vlan(vlan)


def _interface_record(kind, owner, serial, stack_id, interface):
    return {
        "kind": kind,
        "owner": owner,
        "serial": serial,
        "stack_id": stack_id,
        "interface_id": interface.get("interfaceId") or "",
        "interface": interface.get("name") or "",
        "vlan_id": interface.get("vlanId"),
        "subnet": interface.get("subnet") or "",
        "ip": interface.get("interfaceIp") or "",
        "dhcp": "",
        "dns_type": "",
        "dns": "",
        "servers": [],
    }


def _read_interface_dhcp(dashboard, network_id, record, notes):
    try:
        if record["kind"] == "stack":
            dhcp = _call(
                "switch.getNetworkSwitchStackRoutingInterfaceDhcp",
                dashboard.switch.getNetworkSwitchStackRoutingInterfaceDhcp,
                network_id,
                record["stack_id"],
                record["interface_id"],
            ) or {}
        else:
            dhcp = _call(
                "switch.getDeviceSwitchRoutingInterfaceDhcp",
                dashboard.switch.getDeviceSwitchRoutingInterfaceDhcp,
                record["serial"],
                record["interface_id"],
            ) or {}
    except meraki.APIError as exc:
        record.update(dhcp="Read error", dns_type="n/a", dns="n/a")
        notes.append(f"{record['owner']} VLAN 1 DHCP: {api_error_text(exc)}")
        return
    mode = dhcp.get("dhcpMode") or ""
    record["dhcp"] = SWITCH_DHCP_MODES.get(mode, mode or "Unknown")
    if mode == "dhcpServer":
        parsed = switch_dns(dhcp.get("dnsNameserversOption"), dhcp.get("dnsCustomNameservers"))
        record.update(dns_type=parsed["type"], dns=parsed["label"], servers=parsed["servers"])
        note = option6_note(dhcp.get("dhcpOptions"))
        if note:
            notes.append(f"{record['owner']} VLAN 1: {note}")
    elif mode == "dhcpRelay":
        relays = ", ".join(split_servers(dhcp.get("dhcpRelayServerIps") or [])) or "no relay IPs"
        record.update(dns_type="n/a", dns=f"n/a (relays to {relays})")
    else:
        record.update(dns_type="n/a", dns="n/a")


def read_switch_l3(dashboard, network_id, devices):
    """Report Layer 3 routing on the network's switches and DHCP on any VLAN 1 interface."""
    result = {
        "l3": "No switches",
        "summary": "No switches",
        "vlan1": "n/a",
        "dhcp": "n/a",
        "dns_type": "n/a",
        "dns": "n/a",
        "servers": [],
        "interfaces": [],
        "notes": [],
    }
    if not devices:
        return result
    notes = result["notes"]
    failed_reads = 0
    try:
        stacks = _call(
            "switch.getNetworkSwitchStacks",
            dashboard.switch.getNetworkSwitchStacks,
            network_id,
        ) or []
    except meraki.APIError as exc:
        stacks = []
        failed_reads += 1
        notes.append(f"Switch stacks: {api_error_text(exc)}")

    stacked = {serial for stack in stacks for serial in stack.get("serials") or []}
    standalone = [device for device in devices if device.get("serial") not in stacked]
    result["summary"] = (
        f"{len(devices)} switch{'es' if len(devices) != 1 else ''}: "
        f"{len(stacks)} stack{'s' if len(stacks) != 1 else ''}, {len(standalone)} standalone"
    )

    interfaces = []
    for stack in stacks:
        owner = f"Stack {stack.get('name') or stack.get('id')}"
        try:
            found = _call(
                "switch.getNetworkSwitchStackRoutingInterfaces",
                dashboard.switch.getNetworkSwitchStackRoutingInterfaces,
                network_id,
                stack.get("id"),
            ) or []
        except meraki.APIError as exc:
            failed_reads += 1
            notes.append(f"{owner} routing interfaces: {api_error_text(exc)}")
            continue
        interfaces.extend(_interface_record("stack", owner, "", stack.get("id"), item) for item in found)

    for device in standalone:
        serial = device.get("serial") or ""
        owner = f"Switch {device.get('name') or serial} ({serial})"
        try:
            found = _call(
                "switch.getDeviceSwitchRoutingInterfaces",
                dashboard.switch.getDeviceSwitchRoutingInterfaces,
                serial,
            ) or []
        except meraki.APIError as exc:
            if _status(exc) == 400:
                notes.append(f"{owner}: Layer 3 routing not supported ({api_error_text(exc)})")
            else:
                failed_reads += 1
                notes.append(f"{owner} routing interfaces: {api_error_text(exc)}")
            continue
        interfaces.extend(_interface_record("switch", owner, serial, "", item) for item in found)

    result["interfaces"] = interfaces
    if interfaces:
        result["l3"] = "Yes"
    elif failed_reads:
        result["l3"] = "Unknown"
    else:
        result["l3"] = "No"

    vlan1 = [item for item in interfaces if str(item.get("vlan_id")) == "1"]
    if not vlan1:
        result["vlan1"] = {
            "Yes": "No VLAN 1 interface",
            "No": "None",
            "Unknown": "Unknown",
        }[result["l3"]]
        return result

    for record in vlan1:
        _read_interface_dhcp(dashboard, network_id, record, notes)
    if len(vlan1) == 1:
        only = vlan1[0]
        result.update(
            vlan1=only["owner"],
            dhcp=only["dhcp"],
            dns_type=only["dns_type"],
            dns=only["dns"],
            servers=only["servers"],
        )
    else:
        notes.append(f"Multiple VLAN 1 Layer 3 interfaces ({len(vlan1)})")
        result.update(
            vlan1=f"Multiple ({len(vlan1)})",
            dhcp="; ".join(f"{item['owner']}: {item['dhcp']}" for item in vlan1),
            dns_type="; ".join(item["dns_type"] for item in vlan1),
            dns="; ".join(f"{item['owner']}: {item['dns']}" for item in vlan1),
            servers=[ip for item in vlan1 for ip in item["servers"]],
        )
    return result


def _tunnel_map(dashboard, org_id):
    statuses = _call(
        "appliance.getOrganizationApplianceVpnStatuses",
        dashboard.appliance.getOrganizationApplianceVpnStatuses,
        org_id,
        total_pages="all",
    ) or []
    found = {}
    for status in statuses:
        peers = {}
        for peer in status.get("merakiVpnPeers") or []:
            if peer.get("networkId"):
                peers[peer["networkId"]] = peer.get("reachability") or "unknown"
        found[status.get("networkId")] = peers
    return found


def _tunnels_label(hubs):
    if not hubs:
        return ""
    reachable = sum(1 for hub in hubs if hub["tunnel"] == "reachable")
    return f"{reachable}/{len(hubs)} reachable"


def _hubs_label(hubs):
    if not hubs:
        return ""
    return " | ".join(
        f"{hub['priority']}. {hub['hub_name']}{' (default route)' if hub['default_route'] else ''}"
        for hub in hubs
    )


def _base_row(network, templates):
    template_id = network.get("configTemplateId") or ""
    return {
        "network_id": network.get("id") or "",
        "network_name": network.get("name") or network.get("id") or "",
        "template": templates.get(template_id, template_id) if network.get("isBoundToConfigTemplate") else "",
        "vpn_role": "",
        "hubs": [],
        "hub_count": 0,
        "hubs_label": "",
        "tunnels_label": "",
        "notes": [],
    }


def _finish_row(row, mx, switch):
    row["notes"].extend(mx.pop("notes", []))
    row["notes"].extend(switch.pop("notes", []))
    row.update(
        {
            "mx_status": mx["status"],
            "mx_dhcp": mx["dhcp"],
            "mx_dns_type": mx["dns_type"],
            "mx_dns": mx["dns"],
            "mx_servers": mx["servers"],
            "mx_subnet": mx["subnet"],
            "l3_routing": switch["l3"],
            "switch_summary": switch["summary"],
            "sw_vlan1": switch["vlan1"],
            "sw_dhcp": switch["dhcp"],
            "sw_dns_type": switch["dns_type"],
            "sw_dns": switch["dns"],
            "sw_servers": switch["servers"],
            "interfaces": switch["interfaces"],
            "notes_label": "; ".join(row["notes"]),
        }
    )
    return row


def scan_network(dashboard, network, names, devices, templates, tunnels=None):
    row = _base_row(network, templates)
    network_id = row["network_id"]
    if row["template"]:
        row["notes"].append(f"Bound to configuration template {row['template']}")
    try:
        role, hubs = read_vpn(dashboard, network_id, names)
    except meraki.APIError as exc:
        row["vpn_role"] = "Error"
        row["notes"].append(f"Auto VPN read failed: {api_error_text(exc)}")
        skipped = _not_checked("Auto VPN read failed")
        return _finish_row(row, skipped["mx"], skipped["switch"])

    row["vpn_role"] = role
    if tunnels is not None:
        peers = tunnels.get(network_id)
        for hub in hubs:
            hub["tunnel"] = (peers or {}).get(hub["hub_id"], "not reported")
        row["tunnels_label"] = _tunnels_label(hubs) if peers is not None else ("No status" if hubs else "")
    row.update(hubs=hubs, hub_count=len(hubs), hubs_label=_hubs_label(hubs))

    if role != "Spoke":
        skipped = _not_checked("hub" if role == "Hub" else "Auto VPN off" if role == "Off" else role.lower())
        return _finish_row(row, skipped["mx"], skipped["switch"])
    if not hubs:
        row["hubs_label"] = "No hubs configured"
    mx = read_mx_vlan1(dashboard, network_id)
    switch = read_switch_l3(dashboard, network_id, devices)
    return _finish_row(row, mx, switch)


def _error_row(network, templates, exc):
    row = _base_row(network, templates)
    row["vpn_role"] = "Error"
    message = api_error_text(exc) if isinstance(exc, meraki.APIError) else str(exc) or exc.__class__.__name__
    row["notes"].append(f"Could not read this network: {message}")
    skipped = _not_checked("read failed")
    return _finish_row(row, skipped["mx"], skipped["switch"])


def _log_row(index, total, row):
    hubs = f" ({row['hub_count']} hub{'s' if row['hub_count'] != 1 else ''})" if row["vpn_role"] == "Spoke" else ""
    parts = [f"[{index}/{total}] {escape(row['network_name'])}", f"{row['vpn_role']}{hubs}"]
    if row["vpn_role"] == "Spoke":
        parts.append(f"MX VLAN 1: {escape(row['mx_status'])} {escape(row['mx_dns'])}".rstrip())
        parts.append(f"Switch L3: {row['l3_routing']}, VLAN 1: {escape(row['sw_vlan1'])} {escape(row['sw_dns'])}".rstrip())
    if row["notes"]:
        parts.append(f"{len(row['notes'])} note(s)")
    style = "red" if row["vpn_role"] == "Error" else "cyan" if row["vpn_role"] == "Spoke" else "white"
    logger.info(f"[{style}]" + " · ".join(parts) + "[/]")


def _config_templates(dashboard, org_id):
    try:
        templates = _call(
            "organizations.getOrganizationConfigTemplates",
            dashboard.organizations.getOrganizationConfigTemplates,
            org_id,
        ) or []
    except meraki.APIError as exc:
        logger.warning(f"Configuration template names could not be read: {escape(api_error_text(exc))}")
        return {}
    return {item.get("id"): item.get("name") or item.get("id") for item in templates if item.get("id")}


def _vlan1_dhcp_server(row):
    """True when any switch VLAN 1 interface runs a DHCP server, including a multi-interface spoke."""
    vlan1 = [
        item for item in row.get("interfaces") or []
        if str(item.get("vlan_id")) == "1" and item.get("dhcp")
    ]
    if vlan1:
        return any(item.get("dhcp") == "DHCP server" for item in vlan1)
    return row.get("sw_dhcp") == "DHCP server"


def scan_organization(dashboard, org_id, include_tunnels=False, progress=None):
    """Return {rows, counts, api_calls, elapsed}. One network failing never stops the scan."""
    started = time.monotonic()
    calls_before = API_CALL_COUNTER

    def report(done, total, label):
        if progress:
            progress(done, total, label)

    report(0, 0, "Reading appliance networks")
    logger.info("[bold]Reading appliance networks…[/]")
    networks = _call(
        "organizations.getOrganizationNetworks",
        dashboard.organizations.getOrganizationNetworks,
        org_id,
        productTypes=["appliance"],
        total_pages="all",
    ) or []
    names = {network.get("id"): network.get("name") or network.get("id") for network in networks}

    report(0, len(networks), "Reading switches")
    switches = _call(
        "organizations.getOrganizationDevices",
        dashboard.organizations.getOrganizationDevices,
        org_id,
        productTypes=["switch"],
        total_pages="all",
    ) or []
    by_network = {}
    for device in switches:
        by_network.setdefault(device.get("networkId"), []).append(device)
    templates = _config_templates(dashboard, org_id)

    tunnels = None
    if include_tunnels:
        report(0, len(networks), "Reading tunnel status")
        try:
            tunnels = _tunnel_map(dashboard, org_id)
        except meraki.APIError as exc:
            logger.warning(f"Tunnel status could not be read: {escape(api_error_text(exc))}")
            tunnels = {}

    total = len(networks)
    logger.info(f"[bold]Found {total} appliance network(s) and {len(switches)} switch(es).[/]")
    rows = []
    for index, network in enumerate(networks, start=1):
        name = network.get("name") or network.get("id") or ""
        report(index - 1, total, f"Network {index}/{total}: {name}")
        try:
            row = scan_network(
                dashboard,
                network,
                names,
                by_network.get(network.get("id"), []),
                templates,
                tunnels,
            )
        except Exception as exc:
            logger.warning(f"Network {escape(name)} failed: {escape(str(exc))}")
            row = _error_row(network, templates, exc)
        rows.append(row)
        _log_row(index, total, row)

    counts = {
        "networks": total,
        "spokes": sum(1 for row in rows if row["vpn_role"] == "Spoke"),
        "hubs": sum(1 for row in rows if row["vpn_role"] == "Hub"),
        "off": sum(1 for row in rows if row["vpn_role"] == "Off"),
        "errors": sum(1 for row in rows if row["vpn_role"] == "Error"),
        "l3_yes": sum(1 for row in rows if row["l3_routing"] == "Yes"),
        "sw_vlan1_dhcp": sum(1 for row in rows if _vlan1_dhcp_server(row)),
        "with_notes": sum(1 for row in rows if row["notes"]),
    }
    elapsed = time.monotonic() - started
    calls = API_CALL_COUNTER - calls_before
    report(total, total, "Finished")
    logger.info(
        f"[bold green]Scan finished: {total} networks, {counts['spokes']} spokes, "
        f"{counts['hubs']} hubs, {counts['off']} off, {counts['errors']} errors, "
        f"{calls} API calls in {elapsed:.1f}s.[/]"
    )
    return {"rows": rows, "counts": counts, "api_calls": calls, "elapsed": round(elapsed, 1)}
