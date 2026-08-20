"""HTTP layer: a stdlib router, a static file server, and nothing else.

WHY stdlib http.server AND NOT FastAPI
  This repository's runtime dependency list is two lines long (PyYAML,
  requests), and every tool in tools/ is runnable from a bare Python. FastAPI
  brings starlette + pydantic + uvicorn + their transitive tree to serve nine
  read-only JSON endpoints and one HTML file — four new supply-chain surfaces
  for a portal whose entire threat model is "must not be able to change
  anything". None of what FastAPI is good at applies here: there are no request
  bodies to validate, no auth flows to implement (auth terminates at the proxy,
  see auth.py), no async fan-out worth the machinery, and no OpenAPI consumer.
  ThreadingHTTPServer handles concurrent readers, and the routing table below
  is thirty lines. If the portal ever grows a write path or a websocket, that
  is the moment to revisit this — and the router is small enough to replace.

  The cost is real and accepted: no automatic validation, no built-in docs, and
  a hand-written router. `route()` is a pure function precisely so that cost is
  paid back in tests — portal/tests/ exercises every endpoint with no socket.

SECURITY POSTURE
  * GET and HEAD only; every other method is refused at the router.
  * A strict CSP with no external origins — the page loads its own CSS/JS and
    talks to its own API. No CDN, no telemetry, no fonts from the internet.
  * No credential, header or environment value reaches the browser: the only
    configuration serialised is `Settings.public()`.
  * Static file serving is path-confined to portal/static by resolution, not by
    string inspection.
"""
from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import auth, config
from .sources import SourceRegistry, TTLCache
from .view import ExecutiveView

JSON = "application/json; charset=utf-8"

SECURITY_HEADERS = {
    # `style-src` allows inline styles and nothing else does. The page sets bar
    # widths and meter fills from data, which are inline style attributes, and
    # CSP has no way to allow "computed widths" specifically. Script execution
    # stays locked to same-origin files, which is the control that actually
    # matters here: with `script-src 'self'` and `default-src 'none'` an
    # injected style attribute cannot execute anything or reach any other host.
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # The portal renders live operational state. A cached copy in a corporate
    # proxy is exactly the "confident but wrong" failure §49 is about.
    "Cache-Control": "no-store, max-age=0",
}


class Response:
    __slots__ = ("status", "body", "content_type", "headers")

    def __init__(self, status: int, body, content_type: str = JSON,
                 headers: dict | None = None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers or {}

    def payload(self) -> bytes:
        if isinstance(self.body, (bytes, bytearray)):
            return bytes(self.body)
        if self.content_type.startswith("application/json"):
            return json.dumps(self.body, default=str).encode("utf-8")
        return str(self.body).encode("utf-8")


def _error(status: int, message: str, **extra) -> Response:
    return Response(status, {"error": message, "status": status, **extra})


def _static(settings: config.Settings, relative: str) -> Response:
    root = settings.static_dir.resolve()
    target = (root / relative.lstrip("/")).resolve()
    # Containment by resolved path: `..` and symlinks are both defeated because
    # the check happens after resolution, not on the raw string.
    if root != target and root not in target.parents:
        return _error(403, "path outside the static root")
    if not target.is_file():
        return _error(404, f"no such asset: {relative}")
    ctype, _ = mimetypes.guess_type(target.name)
    return Response(200, target.read_bytes(), ctype or "application/octet-stream")


def route(path: str, query: dict, headers, settings: config.Settings,
          cache: TTLCache | None = None) -> Response:
    """The whole routing table. Pure: no sockets, no globals, fully testable."""
    principal = auth.identify(headers)
    allowed, reason = auth.authorize(principal)
    if not allowed and path.startswith("/api/") and path != "/api/healthz":
        return _error(403, reason, role=principal.role,
                      authenticated=principal.authenticated)

    if path in ("/", "/index.html"):
        return _static(settings, "index.html")
    if path.startswith("/static/"):
        return _static(settings, path[len("/static/"):])

    if path == "/api/healthz":
        # Liveness of the PORTAL, never a claim about the estate. Kept
        # separate so a load balancer's probe cannot be mistaken for, or
        # confused by, the health of what the portal is looking at.
        return Response(200, {"ok": True, "mode": settings.mode,
                              "component": "executive-portal"})
    if path == "/api/session":
        return Response(200, {"principal": principal.to_dict(),
                              "config": settings.public(),
                              "sso_required": auth.require_sso()})

    registry = SourceRegistry(settings, cache)
    view = ExecutiveView(registry)

    if path == "/api/overview":
        return Response(200, view.overview())
    if path == "/api/sources":
        registry.policy()
        for name, filename in ({"report.coverage": "coverage_report.json",
                                "report.reconciliation": "monitor_reconciliation.json",
                                "report.scorecard": "scorecard.json"}).items():
            registry.report(name, filename)
        for name in ("datadog.slos", "datadog.incidents", "datadog.events",
                     "datadog.oncall", "datadog.fleet", "datadog.cost"):
            view._dd(name)                                     # noqa: SLF001
        return Response(200, {"sources": registry.sources(),
                              "freshness": registry.freshness(),
                              "config": settings.public()})
    if path == "/api/systems":
        return Response(200, {"systems": view.systems(),
                              "sources": registry.sources(),
                              "freshness": registry.freshness()})
    if path.startswith("/api/systems/"):
        detail = view.system_detail(unquote(path[len("/api/systems/"):]))
        return Response(200, detail) if detail else _error(404, "unknown system")
    if path.startswith("/api/services/"):
        detail = view.service_detail(unquote(path[len("/api/services/"):]))
        return Response(200, detail) if detail else _error(404, "unknown service")
    if path == "/api/slos":
        rows, err = view.slos()
        return Response(200, {"slos": rows, "error": err,
                              "sources": registry.sources(),
                              "freshness": registry.freshness()})
    if path.startswith("/api/slos/"):
        detail = view.slo_detail(unquote(path[len("/api/slos/"):]))
        return Response(200, detail) if detail else _error(404, "unknown objective")
    if path.startswith("/api/incidents/"):
        detail = view.incident_detail(unquote(path[len("/api/incidents/"):]))
        return Response(200, detail) if detail else _error(404, "unknown incident")

    return _error(404, f"no route for {path}")


class Handler(BaseHTTPRequestHandler):
    server_version = "exec-portal"
    sys_version = ""                      # do not advertise the Python version
    settings: config.Settings
    cache: TTLCache | None

    def _respond(self, response: Response, body: bool = True) -> None:
        payload = response.payload()
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in {**SECURITY_HEADERS, **response.headers}.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(payload)

    def _handle(self, body: bool = True) -> None:
        parsed = urlparse(self.path)
        try:
            response = route(parsed.path, {}, self.headers, self.settings, self.cache)
        except Exception:                                          # noqa: BLE001
            # An unhandled server error must still produce an EXPLICIT failure
            # in the browser. The traceback goes to the process log, never to
            # the response — it can carry file paths and query fragments.
            traceback.print_exc()
            response = _error(500, "the portal failed to build this view; "
                                   "see the server log")
        self._respond(response, body=body)

    def do_GET(self):                                              # noqa: N802
        self._handle()

    def do_HEAD(self):                                             # noqa: N802
        self._handle(body=False)

    def _refuse(self):
        self._respond(_error(405, "the executive portal is read-only; only GET and "
                                  "HEAD are served"))

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse                # noqa: N815

    def log_message(self, fmt, *args):
        # Method, path and status only. No headers, so an SSO assertion never
        # lands in a log file.
        print(f"[portal] {self.address_string()} {fmt % args}")


def make_server(settings: config.Settings) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {
        "settings": settings,
        "cache": TTLCache(settings.cache_ttl_seconds) if settings.live else None,
    })
    return ThreadingHTTPServer((settings.host, settings.port), handler)
