"""In-memory stand-ins for the Meraki Dashboard SDK. Only get* methods exist."""

import meraki


class _Response:
    def __init__(self, status, errors):
        self.status_code = status
        self.reason_phrase = "Bad Request" if status == 400 else "Not Found" if status == 404 else "Error"
        self._errors = errors

    def json(self):
        return {"errors": list(self._errors)}


def api_error(status, *errors, operation="getNetworkApplianceVlan"):
    return meraki.APIError({"tags": ["appliance"], "operation": operation}, _Response(status, errors))


def _answer(calls, name, value):
    calls.append(name)
    if isinstance(value, Exception):
        raise value
    return value


class _Section:
    def __init__(self, owner):
        self._owner = owner


class _Organizations(_Section):
    def getOrganizations(self):
        return _answer(self._owner.calls, "getOrganizations", self._owner.orgs)

    def getOrganizationNetworks(self, org_id, **kwargs):
        return _answer(self._owner.calls, "getOrganizationNetworks", self._owner.networks)

    def getOrganizationDevices(self, org_id, **kwargs):
        return _answer(self._owner.calls, "getOrganizationDevices", self._owner.switches)

    def getOrganizationConfigTemplates(self, org_id):
        return _answer(self._owner.calls, "getOrganizationConfigTemplates", self._owner.templates)


class _Appliance(_Section):
    def getNetworkApplianceVpnSiteToSiteVpn(self, network_id):
        return _answer(self._owner.calls, "getNetworkApplianceVpnSiteToSiteVpn", self._owner.vpn[network_id])

    def getNetworkApplianceVlan(self, network_id, vlan_id):
        assert vlan_id == "1"
        return _answer(self._owner.calls, "getNetworkApplianceVlan", self._owner.vlan1.get(network_id, api_error(404, "Not found")))

    def getNetworkApplianceSettings(self, network_id):
        return _answer(
            self._owner.calls,
            "getNetworkApplianceSettings",
            self._owner.appliance_settings.get(network_id, {"deploymentMode": "routed"}),
        )

    def getNetworkApplianceVlansSettings(self, network_id):
        return _answer(
            self._owner.calls,
            "getNetworkApplianceVlansSettings",
            self._owner.vlan_settings.get(network_id, {"vlansEnabled": True}),
        )

    def getNetworkApplianceSingleLan(self, network_id):
        return _answer(
            self._owner.calls,
            "getNetworkApplianceSingleLan",
            self._owner.single_lan.get(network_id, {"subnet": "192.168.128.0/24"}),
        )

    def getOrganizationApplianceVpnStatuses(self, org_id, **kwargs):
        return _answer(self._owner.calls, "getOrganizationApplianceVpnStatuses", self._owner.statuses)


class _Switch(_Section):
    def getNetworkSwitchStacks(self, network_id):
        return _answer(self._owner.calls, "getNetworkSwitchStacks", self._owner.stacks.get(network_id, []))

    def getNetworkSwitchStackRoutingInterfaces(self, network_id, stack_id):
        return _answer(
            self._owner.calls,
            "getNetworkSwitchStackRoutingInterfaces",
            self._owner.stack_interfaces.get(stack_id, []),
        )

    def getNetworkSwitchStackRoutingInterfaceDhcp(self, network_id, stack_id, interface_id):
        return _answer(
            self._owner.calls,
            "getNetworkSwitchStackRoutingInterfaceDhcp",
            self._owner.dhcp[(stack_id, interface_id)],
        )

    def getDeviceSwitchRoutingInterfaces(self, serial):
        return _answer(
            self._owner.calls,
            "getDeviceSwitchRoutingInterfaces",
            self._owner.device_interfaces.get(serial, []),
        )

    def getDeviceSwitchRoutingInterfaceDhcp(self, serial, interface_id):
        return _answer(
            self._owner.calls,
            "getDeviceSwitchRoutingInterfaceDhcp",
            self._owner.dhcp[(serial, interface_id)],
        )


class FakeDashboard:
    def __init__(self):
        self.calls = []
        self.orgs = [{"id": "111", "name": "Lab"}]
        self.networks = []
        self.switches = []
        self.templates = []
        self.vpn = {}
        self.vlan1 = {}
        self.appliance_settings = {}
        self.vlan_settings = {}
        self.single_lan = {}
        self.statuses = []
        self.stacks = {}
        self.stack_interfaces = {}
        self.device_interfaces = {}
        self.dhcp = {}
        self.organizations = _Organizations(self)
        self.appliance = _Appliance(self)
        self.switch = _Switch(self)

    def add_network(self, network_id, name, mode="spoke", hubs=None, **extra):
        self.networks.append({"id": network_id, "name": name, **extra})
        self.vpn[network_id] = {
            "mode": mode,
            "hubs": [{"hubId": hub, "useDefaultRoute": default} for hub, default in (hubs or [])],
        }


def spoke_org():
    """Two hubs, one spoke that uses both, one network with Auto VPN off."""
    dashboard = FakeDashboard()
    dashboard.add_network("N_HUB1", "DC East", mode="hub")
    dashboard.add_network("N_HUB2", "DC West", mode="hub")
    dashboard.add_network("N_SPOKE", "Branch 1", hubs=[("N_HUB2", False), ("N_HUB1", True)])
    dashboard.add_network("N_OFF", "Lab", mode="none")
    dashboard.vlan1["N_SPOKE"] = {
        "id": 1,
        "subnet": "10.1.0.0/24",
        "dhcpHandling": "Run a DHCP server",
        "dnsNameservers": "10.9.0.10\n10.9.0.11",
    }
    return dashboard
