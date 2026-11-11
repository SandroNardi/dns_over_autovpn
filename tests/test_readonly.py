import re
from pathlib import Path

import pytest

from core.api import ReadOnlyDashboard


class _Section:
    def getThing(self):
        return "read"

    def updateThing(self):
        raise AssertionError("must never be reached")


class _Api:
    organizations = _Section()
    appliance = _Section()
    switch = _Section()
    networks = _Section()


def test_proxy_allows_gets_and_blocks_everything_else():
    dashboard = ReadOnlyDashboard(_Api())
    assert dashboard.appliance.getThing() == "read"
    with pytest.raises(PermissionError):
        dashboard.appliance.updateThing()
    with pytest.raises(PermissionError):
        dashboard.switch.createThing
    with pytest.raises(PermissionError):
        dashboard.networks


def test_production_code_has_no_dashboard_write_calls():
    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"\.(update|create|delete|claim|remove|provision|reboot|cycle|blink)[A-Z]\w*\(")
    offenders = []
    for path in [*root.glob("*.py"), *root.glob("core/*.py")]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []
