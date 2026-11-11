import csv
import http.client
import io
import json
import logging
import os
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from core.api import session
from core.logger import logger
from server import build_server, csv_cell
from tests.fakes import spoke_org

SENTINEL = "SENTINEL_KEY_VALUE_1234"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("MK_CSM_KEY", SENTINEL)
    dashboard = spoke_org()
    server = build_server("127.0.0.1", 0, dashboard_provider=lambda: dashboard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield server, base, dashboard
    server.shutdown()
    server.server_close()


def call(base, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(base + path, data=data, method=method)
    if method == "POST":
        request.add_header("Origin", base)
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urlopen(request) as response:
            return response.status, response.read().decode("utf-8-sig"), dict(response.headers)
    except HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def test_page_and_assets_are_served_with_security_headers(app):
    _server, base, _dashboard = app
    status, text, headers = call(base, "GET", "/")
    assert status == 200
    assert "Auto VPN DNS inventory" in text
    assert 'type="password"' in text
    assert 'rel="icon"' in text
    assert 'href="/static/favicon.png"' in text
    assert "no-store" in headers["Cache-Control"]
    with urlopen(base + "/favicon.ico") as icon:
        assert icon.status == 200
        assert icon.headers["Content-Type"] == "image/x-icon"
        assert "no-store" not in icon.headers["Cache-Control"]
        assert icon.read(4) == b"\x00\x00\x01\x00"
    with urlopen(base + "/static/favicon.png") as icon:
        assert icon.status == 200
        assert icon.headers["Content-Type"] == "image/png"
        assert "no-store" not in icon.headers["Cache-Control"]
        assert icon.read(8) == b"\x89PNG\r\n\x1a\n"
    assert "frame-ancestors" not in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    for path in ("/static/app.js", "/static/app.css"):
        assert call(base, "GET", path)[0] == 200
    assert call(base, "GET", "/static/../server.py")[0] == 404


def test_scan_flow_and_csv_export(app):
    _server, base, dashboard = app
    status, text, _ = call(base, "GET", "/api/organizations")
    assert status == 200
    assert json.loads(text)["organizations"] == [{"id": "111", "name": "Lab"}]

    status, text, _ = call(base, "POST", "/api/scan", {"org_id": "111"})
    assert status == 200
    payload = json.loads(text)
    assert payload["counts"]["spokes"] == 1
    assert payload["include_tunnels"] is False
    assert all(name.startswith("get") for name in dashboard.calls)

    status, text, headers = call(base, "GET", "/api/export.csv")
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    table = list(csv.reader(io.StringIO(text)))
    assert table[0][0] == "Network"
    spoke = next(row for row in table if row[0] == "Branch 1")
    assert "1:DC West | 2:DC East [default route]" in spoke

    _, progress, _ = call(base, "GET", "/api/progress")
    assert json.loads(progress)["state"] == "done"

    status, text, _ = call(base, "GET", "/api/result")
    assert status == 200
    assert json.loads(text)["org_name"] == "Lab"


def test_scan_rejects_an_unlisted_organization(app):
    _server, base, _dashboard = app
    call(base, "GET", "/api/organizations")
    status, _, _ = call(base, "POST", "/api/scan", {"org_id": "999"})
    assert status == 400


def test_key_never_leaves_the_server(app):
    _server, base, _dashboard = app
    call(base, "GET", "/api/organizations")
    call(base, "POST", "/api/scan", {"org_id": "111", "include_tunnels": True})
    for path in ("/", "/static/app.js", "/api/session", "/api/progress", "/api/organizations", "/api/result", "/api/export.csv"):
        status, text, headers = call(base, "GET", path)
        assert SENTINEL not in text
        assert SENTINEL not in json.dumps(headers)


def test_missing_key_still_serves_the_page(monkeypatch, app):
    _server, base, _dashboard = app
    monkeypatch.delenv("MK_CSM_KEY")
    assert call(base, "GET", "/")[0] == 200
    status, text, _ = call(base, "GET", "/api/session")
    assert json.loads(text)["key_set"] is False
    assert "MK_CSM_KEY" in json.loads(text)["error"]
    assert call(base, "GET", "/api/organizations")[0] == 400


def test_rebinding_host_cross_site_and_missing_origin_are_rejected(app):
    server, base, _dashboard = app
    port = server.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/", headers={"Host": f"evil.example:{port}"})
    assert connection.getresponse().status == 403
    connection.close()

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", "/api/scan", body=b"{}", headers={"Content-Type": "application/json"})
    assert connection.getresponse().status == 403
    connection.close()

    status, _, _ = call(base, "POST", "/api/scan", {"org_id": "111"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403


def test_unknown_routes_return_404(app):
    _server, base, _dashboard = app
    for path in ("/api/audit", "/api/apply", "/api/hub", "/api/sites", "/api/clear"):
        assert call(base, "POST", path, {})[0] == 404
    assert call(base, "GET", "/api/status.json")[0] == 404


def test_csv_formula_guard():
    assert csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert csv_cell("@cmd") == "'@cmd"
    assert csv_cell("10.0.0.1") == "10.0.0.1"


PASTED_KEY = "ab" * 20


def _no_secret(blob, secret=PASTED_KEY):
    assert secret not in blob, "secret appeared in output"


def test_environment_key_refuses_a_second_key(app):
    _server, base, _dashboard = app
    status, text, _headers = call(base, "POST", "/api/key", {"api_key": PASTED_KEY})
    assert status == 409
    _no_secret(text)


def test_pasted_key_is_kept_in_memory_only(monkeypatch):
    monkeypatch.delenv("MK_CSM_KEY", raising=False)
    session.forget()
    server = build_server("127.0.0.1", 0, dashboard_provider=lambda: spoke_org())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    captured = []

    class Grab(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    grab = Grab()
    logger.addHandler(grab)
    try:
        status, text, headers = call(base, "POST", "/api/key", {"api_key": PASTED_KEY})
        assert status == 200
        assert json.loads(text) == {"accepted": True}
        _no_secret(text)
        _no_secret(json.dumps(headers))
        assert os.getenv("MK_CSM_KEY") is None
        assert session.from_paste is True
        assert session.configured() is True
        assert all(PASTED_KEY not in message for message in captured)

        status, text, _headers = call(base, "POST", "/api/key", {"api_key": PASTED_KEY})
        assert status == 409
        _no_secret(text)

        session.forget()
        status, text, _headers = call(base, "POST", "/api/key", {"api_key": "not-a-real-key"})
        assert status == 400
        assert "not-a-real-key" not in text
        assert session.api is None
        assert os.getenv("MK_CSM_KEY") is None
    finally:
        logger.removeHandler(grab)
        session.forget()
        server.shutdown()
        server.server_close()
