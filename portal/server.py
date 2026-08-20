#!/usr/bin/env python3
"""EXECUTIVE REAL-TIME WEB PORTAL — entry point (requirement-traceability §47–§49).

    python portal/server.py                 # offline, recorded data, no credentials
    python portal/server.py --live          # reads Datadog with DD_API_KEY/DD_APP_KEY

Offline is the default on purpose. A portal that only works with production
credentials cannot be reviewed, demonstrated or tested, and the version that
nobody can run is the version nobody checks.

The process is read-only end to end: it serves GET and HEAD, issues only GET
requests to Datadog, and holds no database. Credentials are read from the
environment inside `app/datadog.py` and never reach the browser.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as a script (`python portal/server.py`) or as a module
# (`python -m portal.server`); the package import must work either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portal.app import config                              # noqa: E402
from portal.app.http_app import make_server                # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true",
                        help="read Datadog live; requires DD_API_KEY and DD_APP_KEY")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    settings = config.from_env()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port

    if args.live:
        if not config.credentials_present():
            # Fail loudly rather than silently serving fixtures under a --live
            # flag: an executive reading a recorded snapshot labelled "live" is
            # the worst outcome this application can produce.
            print("--live requires DD_API_KEY and DD_APP_KEY (use the "
                  "svc-observability service-account keys, never personal "
                  "credentials).", file=sys.stderr)
            return 2
        settings.mode = "live"

    httpd = make_server(settings)
    print(f"[portal] executive portal on http://{settings.host}:{settings.port}/")
    print(f"[portal] mode: {settings.mode}"
          + (f" (Datadog reads cached for {settings.cache_ttl_seconds}s)"
             if settings.live else " (recorded data — portal/fixtures/)"))
    print("[portal] read-only: GET/HEAD only, no write path, no portal database")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[portal] stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
