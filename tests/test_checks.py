from checks import api_error_text, mx_dns, option6_note, switch_dns
from tests.fakes import api_error


def test_mx_custom_list_keeps_order():
    parsed = mx_dns("10.9.0.11\n10.9.0.10")
    assert parsed["type"] == "Custom"
    assert parsed["servers"] == ["10.9.0.11", "10.9.0.10"]
    assert parsed["label"] == "10.9.0.11, 10.9.0.10"


def test_mx_presets_and_empty():
    assert mx_dns("upstream_dns")["label"] == "Preset: Proxy to upstream DNS (upstream_dns)"
    assert mx_dns("google_dns")["type"] == "Preset"
    assert "OpenDNS" in mx_dns("opendns")["label"]
    assert mx_dns("")["label"] == "Not set"
    assert mx_dns(None)["type"] == "Not set"


def test_switch_dns_options():
    assert switch_dns("custom", ["10.9.0.10", "1.1.1.1"])["label"] == "10.9.0.10, 1.1.1.1"
    assert switch_dns("custom", [])["label"] == "Custom (empty)"
    assert switch_dns("googlePublicDns", None)["label"] == "Preset: Google Public DNS (googlePublicDns)"
    assert switch_dns("openDns", None)["type"] == "Preset"
    assert switch_dns("upstream", None)["label"] == "Preset: upstream"
    assert switch_dns(None, None)["label"] == "Not set"


def test_api_error_dict_message_becomes_text():
    exc = api_error(400, "VLANs are not enabled for this network")
    assert api_error_text(exc) == "VLANs are not enabled for this network"
    assert api_error_text(ValueError("boom")) == "boom"


def test_option6_note():
    assert option6_note([{"code": "6", "type": "ip", "value": "10.0.0.1"}])
    assert option6_note([{"code": "15", "value": "corp"}]) == ""
