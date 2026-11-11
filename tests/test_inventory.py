import logic
from tests.fakes import FakeDashboard, api_error, spoke_org


def _rows(dashboard, **kwargs):
    result = logic.scan_organization(dashboard, "111", **kwargs)
    return {row["network_name"]: row for row in result["rows"]}, result


def test_roles_and_hub_priority_order():
    rows, result = _rows(spoke_org())
    assert rows["DC East"]["vpn_role"] == "Hub"
    assert rows["Lab"]["vpn_role"] == "Off"
    spoke = rows["Branch 1"]
    assert spoke["vpn_role"] == "Spoke"
    assert [hub["hub_name"] for hub in spoke["hubs"]] == ["DC West", "DC East"]
    assert [hub["priority"] for hub in spoke["hubs"]] == [1, 2]
    assert spoke["hubs"][1]["default_route"] is True
    assert spoke["hubs_label"] == "1. DC West | 2. DC East (default route)"
    assert result["counts"] == {
        "networks": 4, "spokes": 1, "hubs": 2, "off": 1, "errors": 0,
        "l3_yes": 0, "sw_vlan1_dhcp": 0, "with_notes": 0,
    }


def test_vlan1_and_switch_checks_run_on_spokes_only():
    dashboard = spoke_org()
    rows, _ = _rows(dashboard)
    assert dashboard.calls.count("getNetworkApplianceVlan") == 1
    assert rows["DC East"]["mx_status"] == "Not checked (hub)"
    assert rows["Lab"]["mx_status"] == "Not checked (Auto VPN off)"
    assert rows["Lab"]["l3_routing"] == "Not checked"
    spoke = rows["Branch 1"]
    assert spoke["mx_status"] == "DHCP server"
    assert spoke["mx_dns"] == "10.9.0.10, 10.9.0.11"
    assert spoke["l3_routing"] == "No switches"


def test_unknown_hub_and_spoke_without_hubs():
    dashboard = FakeDashboard()
    dashboard.add_network("N_A", "Branch A", hubs=[("N_GONE", False)])
    dashboard.add_network("N_B", "Branch B", hubs=[])
    dashboard.vlan1["N_A"] = {"dhcpHandling": "Do not respond to DHCP requests"}
    dashboard.vlan1["N_B"] = {"dhcpHandling": "Do not respond to DHCP requests"}
    rows, _ = _rows(dashboard)
    assert rows["Branch A"]["hubs"][0]["hub_name"] == "Unknown network (N_GONE)"
    assert rows["Branch B"]["hubs_label"] == "No hubs configured"
    assert rows["Branch A"]["mx_status"] == "DHCP disabled"


def test_mx_vlan1_corner_cases():
    dashboard = FakeDashboard()
    for network_id in ("N_PRESET", "N_EMPTY", "N_RELAY", "N_MISSING", "N_SINGLE", "N_PASS", "N_ERR"):
        dashboard.add_network(network_id, network_id, hubs=[("N_HUB", False)])
    dashboard.vlan1["N_PRESET"] = {"dhcpHandling": "Run a DHCP server", "dnsNameservers": "upstream_dns"}
    dashboard.vlan1["N_EMPTY"] = {"dhcpHandling": "Run a DHCP server", "dnsNameservers": ""}
    dashboard.vlan1["N_RELAY"] = {"dhcpHandling": "Relay DHCP to another server", "dhcpRelayServerIps": ["10.0.0.5"]}
    dashboard.vlan1["N_SINGLE"] = api_error(400, "VLANs are not enabled for this network")
    dashboard.vlan_settings["N_SINGLE"] = {"vlansEnabled": False}
    dashboard.single_lan["N_SINGLE"] = {"subnet": "192.168.5.0/24"}
    dashboard.vlan1["N_PASS"] = api_error(400, "Not available in passthrough mode")
    dashboard.appliance_settings["N_PASS"] = {"deploymentMode": "passthrough"}
    dashboard.vlan1["N_ERR"] = api_error(500, "Internal error")

    rows, _ = _rows(dashboard)
    assert rows["N_PRESET"]["mx_dns"] == "Preset: Proxy to upstream DNS (upstream_dns)"
    assert rows["N_EMPTY"]["mx_dns"] == "Not set"
    assert rows["N_RELAY"]["mx_status"] == "DHCP relay"
    assert rows["N_RELAY"]["mx_dns"] == "n/a (relays to 10.0.0.5)"
    assert rows["N_MISSING"]["mx_status"] == "VLAN 1 not configured"
    assert rows["N_SINGLE"]["mx_status"] == "VLANs disabled (single LAN)"
    assert rows["N_SINGLE"]["mx_subnet"] == "192.168.5.0/24"
    assert rows["N_SINGLE"]["mx_dns"] == "Not returned by the API in single-LAN mode"
    assert rows["N_PASS"]["mx_status"] == "Passthrough mode (no MX LAN)"
    assert rows["N_ERR"]["mx_status"] == "Read error"
    assert "Internal error" in rows["N_ERR"]["notes_label"]


def test_vlan_settings_400_also_means_single_lan():
    dashboard = FakeDashboard()
    dashboard.add_network("N_S", "Single", hubs=[("N_HUB", False)])
    dashboard.vlan1["N_S"] = api_error(400, "VLANs are not enabled for this network")
    dashboard.vlan_settings["N_S"] = api_error(400, "VLANs are not enabled for this network")
    rows, _ = _rows(dashboard)
    assert rows["Single"]["mx_status"] == "VLANs disabled (single LAN)"


def _switch_org():
    dashboard = FakeDashboard()
    dashboard.add_network("N_S", "Branch", hubs=[("N_HUB", False)])
    dashboard.vlan1["N_S"] = {"dhcpHandling": "Relay DHCP to another server", "dhcpRelayServerIps": ["10.1.0.2"]}
    dashboard.switches = [
        {"serial": "Q-A", "name": "Core A", "networkId": "N_S"},
        {"serial": "Q-B", "name": "Core B", "networkId": "N_S"},
        {"serial": "Q-C", "name": "Access", "networkId": "N_S"},
    ]
    dashboard.stacks["N_S"] = [{"id": "ST1", "name": "Core", "serials": ["Q-A", "Q-B"]}]
    return dashboard


def test_stack_vlan1_dhcp_server_and_member_not_double_counted():
    dashboard = _switch_org()
    dashboard.stack_interfaces["ST1"] = [
        {"interfaceId": "I1", "name": "Users", "vlanId": 1, "subnet": "10.1.0.0/24", "interfaceIp": "10.1.0.2"},
        {"interfaceId": "I2", "name": "Voice", "vlanId": 20, "subnet": "10.20.0.0/24", "interfaceIp": "10.20.0.1"},
    ]
    dashboard.dhcp[("ST1", "I1")] = {
        "dhcpMode": "dhcpServer",
        "dnsNameserversOption": "custom",
        "dnsCustomNameservers": ["10.9.0.10", "10.9.0.11"],
    }
    rows, result = _rows(dashboard)
    row = rows["Branch"]
    assert row["l3_routing"] == "Yes"
    assert row["switch_summary"] == "3 switches: 1 stack, 1 standalone"
    assert row["sw_vlan1"] == "Stack Core"
    assert row["sw_dhcp"] == "DHCP server"
    assert row["sw_dns"] == "10.9.0.10, 10.9.0.11"
    assert dashboard.calls.count("getDeviceSwitchRoutingInterfaces") == 1
    assert dashboard.calls.count("getNetworkSwitchStackRoutingInterfaceDhcp") == 1
    assert len(row["interfaces"]) == 2
    assert result["counts"]["sw_vlan1_dhcp"] == 1


def test_standalone_vlan1_relay_and_preset():
    dashboard = _switch_org()
    dashboard.device_interfaces["Q-C"] = [{"interfaceId": "X1", "name": "Mgmt", "vlanId": 1}]
    dashboard.dhcp[("Q-C", "X1")] = {"dhcpMode": "dhcpRelay", "dhcpRelayServerIps": ["10.0.0.9"]}
    rows, _ = _rows(dashboard)
    assert rows["Branch"]["sw_vlan1"] == "Switch Access (Q-C)"
    assert rows["Branch"]["sw_dhcp"] == "DHCP relay"
    assert rows["Branch"]["sw_dns"] == "n/a (relays to 10.0.0.9)"

    dashboard = _switch_org()
    dashboard.device_interfaces["Q-C"] = [{"interfaceId": "X1", "name": "Mgmt", "vlanId": 1}]
    dashboard.dhcp[("Q-C", "X1")] = {"dhcpMode": "dhcpServer", "dnsNameserversOption": "googlePublicDns"}
    rows, _ = _rows(dashboard)
    assert rows["Branch"]["sw_dns"] == "Preset: Google Public DNS (googlePublicDns)"


def test_l3_without_vlan1_and_no_l3():
    dashboard = _switch_org()
    dashboard.device_interfaces["Q-C"] = [{"interfaceId": "X1", "name": "Voice", "vlanId": 20}]
    rows, _ = _rows(dashboard)
    assert rows["Branch"]["l3_routing"] == "Yes"
    assert rows["Branch"]["sw_vlan1"] == "No VLAN 1 interface"
    assert "getDeviceSwitchRoutingInterfaceDhcp" not in dashboard.calls

    rows, _ = _rows(_switch_org())
    assert rows["Branch"]["l3_routing"] == "No"
    assert rows["Branch"]["sw_vlan1"] == "None"


def test_multiple_vlan1_interfaces_are_flagged():
    dashboard = _switch_org()
    dashboard.stack_interfaces["ST1"] = [{"interfaceId": "I1", "name": "Users", "vlanId": 1}]
    dashboard.device_interfaces["Q-C"] = [{"interfaceId": "X1", "name": "Users", "vlanId": 1}]
    dashboard.dhcp[("ST1", "I1")] = {"dhcpMode": "dhcpServer", "dnsNameserversOption": "custom", "dnsCustomNameservers": ["10.9.0.10"]}
    dashboard.dhcp[("Q-C", "X1")] = {"dhcpMode": "dhcpDisabled"}
    rows, result = _rows(dashboard)
    assert rows["Branch"]["sw_vlan1"] == "Multiple (2)"
    assert "Multiple VLAN 1 Layer 3 interfaces (2)" in rows["Branch"]["notes"]
    assert result["counts"]["sw_vlan1_dhcp"] == 1
    assert "DHCP server" in rows["Branch"]["sw_dhcp"]
    assert rows["Branch"]["sw_dhcp"] != "DHCP server"


def test_switch_read_errors():
    dashboard = _switch_org()
    dashboard.stacks["N_S"] = api_error(500, "stack failure")
    dashboard.device_interfaces.update({
        "Q-A": api_error(500, "down"),
        "Q-B": api_error(500, "down"),
        "Q-C": api_error(400, "This switch does not support Layer 3"),
    })
    rows, _ = _rows(dashboard)
    row = rows["Branch"]
    assert row["l3_routing"] == "Unknown"
    assert any("Layer 3 routing not supported" in note for note in row["notes"])
    assert any("stack failure" in note for note in row["notes"])


def test_one_failing_network_does_not_stop_the_scan():
    dashboard = spoke_org()
    dashboard.vpn["N_HUB1"] = api_error(500, "VPN read failed")
    dashboard.add_network("N_LAST", "Branch Last", hubs=[("N_HUB1", False)])
    dashboard.vlan1["N_LAST"] = {"dhcpHandling": "Run a DHCP server", "dnsNameservers": "google_dns"}
    rows, result = _rows(dashboard)
    assert rows["DC East"]["vpn_role"] == "Error"
    assert "VPN read failed" in rows["DC East"]["notes_label"]
    assert rows["Branch Last"]["mx_dns"].startswith("Preset: Google")
    assert result["counts"]["errors"] == 1


def test_unexpected_exception_becomes_an_error_row():
    dashboard = spoke_org()
    dashboard.vpn["N_SPOKE"] = RuntimeError("socket closed")
    rows, _ = _rows(dashboard)
    assert rows["Branch 1"]["vpn_role"] == "Error"
    assert "socket closed" in rows["Branch 1"]["notes_label"]
    assert rows["Lab"]["vpn_role"] == "Off"


def test_tunnel_status_is_optional():
    dashboard = spoke_org()
    _rows(dashboard)
    assert "getOrganizationApplianceVpnStatuses" not in dashboard.calls

    dashboard = spoke_org()
    dashboard.statuses = [{
        "networkId": "N_SPOKE",
        "merakiVpnPeers": [{"networkId": "N_HUB2", "reachability": "reachable"}],
    }]
    rows, _ = _rows(dashboard, include_tunnels=True)
    spoke = rows["Branch 1"]
    assert spoke["hubs"][0]["tunnel"] == "reachable"
    assert spoke["hubs"][1]["tunnel"] == "not reported"
    assert spoke["tunnels_label"] == "1/2 reachable"


def test_template_name_is_reported():
    dashboard = spoke_org()
    dashboard.networks[2].update(isBoundToConfigTemplate=True, configTemplateId="T1")
    dashboard.templates = [{"id": "T1", "name": "Branch template"}]
    rows, _ = _rows(dashboard)
    assert rows["Branch 1"]["template"] == "Branch template"


def test_scan_only_calls_get_methods():
    dashboard = _switch_org()
    dashboard.device_interfaces["Q-C"] = [{"interfaceId": "X1", "name": "Users", "vlanId": 1}]
    dashboard.dhcp[("Q-C", "X1")] = {"dhcpMode": "dhcpDisabled"}
    _rows(dashboard, include_tunnels=True)
    assert dashboard.calls
    assert all(name.startswith("get") for name in dashboard.calls)
