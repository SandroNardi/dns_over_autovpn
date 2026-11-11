"""Loopback page and JSON API for the read-only Auto VPN DNS inventory.

The browser sends an organization id and options. The Dashboard API key comes
from MK_CSM_KEY, or from one paste into the page that core.api keeps in memory.
It is never returned to the browser and never logged.
"""

from __future__ import annotations

import argparse
import csv
import errno
import io
import json
import re
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.markup import escape

import logic
from core.api import session
from core.logger import logger

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 65536
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
DEFAULT_PORT = 8772
PORT_SPAN = 50
MISSING_KEY = (
    "No Dashboard API key yet. Paste a read-only key in the page for this run, "
    "or set the MK_CSM_KEY environment variable and start the app again."
)

CSV_COLUMNS = [
    ("Network", "network_name"),
    ("Network ID", "network_id"),
    ("Template", "template"),
    ("Auto VPN role", "vpn_role"),
    ("Hub count", "hub_count"),
    ("Hubs in priority order", "hubs_csv"),
    ("Tunnels", "tunnels_label"),
    ("MX VLAN 1 status", "mx_status"),
    ("MX VLAN 1 subnet", "mx_subnet"),
    ("MX VLAN 1 DNS type", "mx_dns_type"),
    ("MX VLAN 1 DNS", "mx_dns"),
    ("Switches", "switch_summary"),
    ("Switch L3 routing", "l3_routing"),
    ("Switch VLAN 1 interface", "sw_vlan1"),
    ("Switch VLAN 1 DHCP", "sw_dhcp"),
    ("Switch VLAN 1 DNS type", "sw_dns_type"),
    ("Switch VLAN 1 DNS", "sw_dns"),
    ("Notes", "notes_label"),
]


def idle_progress():
    return {"done": 0, "total": 0, "label": "", "state": "idle", "error": ""}


class AppState:
    """Scan state shared by request threads. lock guards the fields; operation is held for a whole scan."""

    def __init__(self):
        self.lock = threading.Lock()
        self.operation = threading.Lock()
        self.progress = idle_progress()
        self.orgs = {}
        self.org_id = None
        self.rows = None
        self.result = {}


def key_is_set():
    return session.configured()


def csv_cell(value):
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def hubs_csv(row):
    parts = []
    for hub in row.get("hubs") or []:
        text = f"{hub['priority']}:{hub['hub_name']}"
        if hub.get("default_route"):
            text += " [default route]"
        if hub.get("tunnel"):
            text += f" ({hub['tunnel']})"
        parts.append(text)
    return " | ".join(parts) or row.get("hubs_label") or ""


def rows_to_csv(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for label, _key in CSV_COLUMNS])
    for row in rows:
        values = {**row, "hubs_csv": hubs_csv(row)}
        writer.writerow([csv_cell(values.get(key)) for _label, key in CSV_COLUMNS])
    return buffer.getvalue()


def handler_for(state, dashboard_provider):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            logger.debug("HTTP " + (fmt % args))

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            if not self._host_allowed() or not self._origin_allowed(method):
                self._json(403, {"error": "This service accepts requests from this loopback page only."})
                return
            path = unquote(urlparse(self.path).path)
            try:
                if method == "GET" and path == "/":
                    self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                elif method == "GET" and path == "/favicon.ico":
                    self._file(
                        STATIC_DIR / "favicon.ico",
                        "image/x-icon",
                        cache_control="public, max-age=86400",
                    )
                elif method == "GET" and path.startswith("/static/"):
                    self._static(path[len("/static/") :])
                elif method == "GET" and path == "/api/session":
                    self._session()
                elif method == "GET" and path == "/api/progress":
                    self._progress()
                elif method == "GET" and path == "/api/organizations":
                    self._organizations()
                elif method == "GET" and path == "/api/result":
                    self._result()
                elif method == "GET" and path == "/api/export.csv":
                    self._export_csv()
                elif method == "POST" and path == "/api/key":
                    self._accept_key()
                elif method == "POST" and path == "/api/scan":
                    self._scan()
                else:
                    self._json(404, {"error": "Not found."})
            except Exception as exc:
                logger.error(f"Request failed: {escape(str(exc))}")
                self._json(500, {"error": "The request failed."})

        # Blocks DNS rebinding: only this server's own loopback Host values are served.
        def _host_allowed(self):
            host = (self.headers.get("Host") or "").split(",")[0].strip().lower()
            port = self.server.server_address[1]
            return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

        # Blocks cross-site requests: a POST must carry this page's own Origin.
        def _origin_allowed(self, method):
            if (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
                return False
            origin = self.headers.get("Origin")
            port = self.server.server_address[1]
            if not origin:
                return method == "GET"
            return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

        def _security_headers(self, cache_control="no-store"):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", cache_control)
            # No frame-ancestors directive: IDE preview browsers embed this page,
            # and a frame ban leaves that view blank.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'",
            )
            self.send_header("Connection", "close")

        def _send(self, status, raw, content_type, extra=None, cache_control="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self._security_headers(cache_control)
            self.end_headers()
            self.wfile.write(raw)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _file(self, path, content_type, cache_control="no-store"):
            if not path.is_file():
                self._json(404, {"error": "Not found."})
                return
            self._send(200, path.read_bytes(), content_type, cache_control=cache_control)

        def _static(self, name):
            allowed = {
                "app.css": "text/css; charset=utf-8",
                "app.js": "text/javascript; charset=utf-8",
                "favicon.png": "image/png",
            }
            if name not in allowed:
                self._json(404, {"error": "Not found."})
                return
            # Chrome only paints a tab icon it is allowed to store.
            cache_control = "public, max-age=86400" if name == "favicon.png" else "no-store"
            self._file(STATIC_DIR / name, allowed[name], cache_control=cache_control)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or "0")
            if length > MAX_BODY:
                raise ValueError("Request body is too large.")
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("Content-Type must be application/json.")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("The request body is not valid JSON.") from exc
            if not isinstance(body, dict):
                raise ValueError("The request body must be a JSON object.")
            return body

        def _set_progress(self, **fields):
            with state.lock:
                state.progress.update(fields)

        def _progress_callback(self, done, total, label):
            self._set_progress(done=done, total=total, label=label, state="running", error="")

        def _session(self):
            with state.lock:
                payload = {
                    "key_set": key_is_set(),
                    "scan_loaded": state.rows is not None,
                    "busy": state.operation.locked(),
                }
            if not payload["key_set"]:
                payload["error"] = MISSING_KEY
            self._json(200, payload)

        def _progress(self):
            with state.lock:
                payload = dict(state.progress)
            self._json(200, payload)

        def _accept_key(self):
            if key_is_set():
                self._json(409, {"error": "This server already has an API key."})
                return
            try:
                body = self._read_json()
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            pasted = body.pop("api_key", None)
            body.clear()
            try:
                session.use_key(pasted)
            except ValueError:
                self._json(400, {"error": "Enter a Meraki Dashboard API key. It was not saved."})
                return
            except RuntimeError:
                self._json(409, {"error": "This server already has an API key."})
                return
            except Exception:
                logger.error("The pasted API key could not be used. The value was not saved or logged.")
                session.forget()
                self._json(500, {"error": "The key was not accepted and was not saved."})
                return
            self._json(200, {"accepted": True})

        def _organizations(self):
            if not key_is_set():
                self._json(400, {"error": MISSING_KEY})
                return
            logger.info("Loading organizations available to this API key…")
            try:
                orgs = logic.list_organizations(dashboard_provider())
            except EnvironmentError:
                self._json(400, {"error": MISSING_KEY})
                return
            except Exception as exc:
                logger.error(f"Could not list organizations: {escape(str(exc))}")
                self._json(502, {"error": "Could not list organizations. Check the API key and network access."})
                return
            listed = [
                {"id": str(org.get("id")), "name": org.get("name") or str(org.get("id"))}
                for org in orgs
                if org.get("id")
            ]
            listed.sort(key=lambda org: org["name"].lower())
            with state.lock:
                state.orgs = {org["id"]: org["name"] for org in listed}
            logger.info(f"{len(listed)} organization(s) available.")
            self._json(200, {"organizations": listed})

        def _scan(self):
            if not key_is_set():
                self._json(400, {"error": MISSING_KEY})
                return
            try:
                body = self._read_json()
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            org_id = str(body.get("org_id") or "")
            include_tunnels = body.get("include_tunnels") is True
            with state.lock:
                org_name = state.orgs.get(org_id)
            if not org_name:
                self._json(400, {"error": "Choose an organization from the list."})
                return
            if not state.operation.acquire(blocking=False):
                self._json(409, {"error": "A scan is already running."})
                return
            try:
                self._set_progress(done=0, total=0, label="Starting", state="running", error="")
                logger.info(
                    f"[bold]Scanning organization {escape(org_name)}[/] "
                    f"(tunnel status: {'on' if include_tunnels else 'off'})"
                )
                try:
                    result = logic.scan_organization(
                        dashboard_provider(),
                        org_id,
                        include_tunnels=include_tunnels,
                        progress=self._progress_callback,
                    )
                except Exception as exc:
                    logger.error(f"Scan failed: {escape(str(exc))}")
                    self._set_progress(state="error", error="Could not read networks for this organization.")
                    self._json(502, {"error": "Could not read networks for this organization."})
                    return
                payload = {
                    "org_id": org_id,
                    "org_name": org_name,
                    "include_tunnels": include_tunnels,
                    "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    **result,
                }
                with state.lock:
                    state.org_id = org_id
                    state.rows = result["rows"]
                    state.result = payload
                    state.progress.update(state="done", label="Finished")
            finally:
                state.operation.release()
            self._json(200, payload)

        def _result(self):
            with state.lock:
                payload = dict(state.result)
            if not payload:
                self._json(404, {"error": "No scan yet."})
                return
            self._json(200, payload)

        def _export_csv(self):
            with state.lock:
                rows = list(state.rows or [])
                org_id = state.org_id or ""
                loaded = state.rows is not None
            if not loaded:
                self._json(400, {"error": "Run a scan before exporting."})
                return
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "", org_id) or "org"
            raw = rows_to_csv(rows).encode("utf-8-sig")
            self._send(
                200,
                raw,
                "text/csv; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="autovpn-dns-inventory-{safe_id}.csv"'},
            )

    return Handler


def build_server(host="127.0.0.1", port=DEFAULT_PORT, dashboard_provider=None):
    if host not in LOOPBACK_HOSTS:
        raise ValueError("The server only binds to loopback.")
    provider = dashboard_provider or session.get_dashboard
    state = AppState()
    httpd = ThreadingHTTPServer((host, port), handler_for(state, provider))
    httpd.app_state = state
    return httpd


def port_band(start=DEFAULT_PORT):
    return list(range(start, start + PORT_SPAN))


def ports_to_try(requested):
    """Default walks the band. A port inside the band is tried first, then the rest. A port outside is tried once."""
    if requested is None:
        return port_band()
    if not isinstance(requested, int) or not 1024 <= requested <= 65535:
        raise ValueError("Choose a port from 1024 to 65535.")
    band = port_band()
    if requested in band:
        return [requested] + [port for port in band if port != requested]
    return [requested]


def address_in_use(exc):
    if getattr(exc, "winerror", None) == 10048:  # WSAEADDRINUSE
        return True
    return getattr(exc, "errno", None) == errno.EADDRINUSE


def bind_loopback(ports, bind):
    """Return (server, port, skipped). server is None when every port was busy."""
    skipped = []
    for port in ports:
        try:
            server = bind(port)
        except OSError as exc:
            if not address_in_use(exc):
                raise
            server = None
        if server is not None:
            return server, port, skipped
        skipped.append(port)
    return None, None, skipped


def startup_message(port, skipped):
    url = f"http://127.0.0.1:{port}/"
    lines = [f"Auto VPN DNS inventory at {url}"]
    if skipped:
        busy = ", ".join(str(item) for item in skipped)
        verb = "Port {} was" if len(skipped) == 1 else "Ports {} were"
        lines.append(f"{verb.format(busy)} busy. This server is using {port}.")
    return url, "\n".join(lines)


def band_busy_message(skipped):
    if skipped == port_band():
        span = f"{skipped[0]}-{skipped[-1]}"
    elif len(skipped) == 1:
        span = str(skipped[0])
    else:
        span = ", ".join(str(port) for port in skipped)
    subject = f"Port {span} is" if len(skipped) == 1 else f"Ports {span} are"
    return (
        f"{subject} in use.\n"
        "Start on another port with:\n"
        "python server.py --port 8900"
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Auto VPN DNS inventory")
    parser.add_argument("--port", type=int, default=None, help=f"Port to try first. Default band is {DEFAULT_PORT}-{DEFAULT_PORT + PORT_SPAN - 1}.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the page after the server binds.")
    return parser.parse_args(argv)


def open_browser(url):
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()


def main(argv=None):
    args = parse_args(argv)
    try:
        ports = ports_to_try(args.port)
    except ValueError as exc:
        print(exc)
        return 2

    def bind(port):
        return build_server(port=port)

    try:
        httpd, port, skipped = bind_loopback(ports, bind)
    except OSError as exc:
        print(f"Could not bind 127.0.0.1: {exc}")
        return 1
    if httpd is None:
        print(band_busy_message(skipped))
        return 1
    url, message = startup_message(port, skipped)
    if not key_is_set():
        logger.warning("No MK_CSM_KEY. The page will ask for a key and keep it in memory until you stop the server.")
    logger.info(f"[bold]Auto VPN DNS inventory[/] listening on {url} (read only)")
    print(message)
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
