"""Local reports server: dashboard + live Altegio sync API (no AI tokens).

  python scripts/server.py

Then open http://127.0.0.1:8765/dashboards/index.html
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from env_loader import get_env  # noqa: E402
from sync_from_altegio import PORTAL_PATH, ensure_seed, sync_now  # noqa: E402

SYNC_LOCK = threading.Lock()
LAST_SYNC: dict = {"ok": True, "message": "ready"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self.send_response(302)
            self.send_header("Location", "/dashboards/index.html")
            self.end_headers()
            return
        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "portal_exists": PORTAL_PATH.exists(),
                    "has_partner_token": bool(get_env("ALTEGIO_PARTNER_TOKEN")),
                    "has_user_token": bool(get_env("ALTEGIO_USER_TOKEN")),
                    "location_id": get_env("ALTEGIO_LOCATION_ID", "764940"),
                    "last_sync": LAST_SYNC,
                },
            )
            return
        if path == "/api/data":
            ensure_seed()
            data = json.loads(PORTAL_PATH.read_text(encoding="utf-8"))
            self._json(200, data)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/sync":
            self._json(404, {"ok": False, "error": "Not found"})
            return
        if not get_env("ALTEGIO_USER_TOKEN"):
            self._json(
                400,
                {
                    "ok": False,
                    "error": "ALTEGIO_USER_TOKEN missing. Run: python scripts/auth_user_token.py",
                },
            )
            return
        if not SYNC_LOCK.acquire(blocking=False):
            self._json(409, {"ok": False, "error": "Sync already running"})
            return
        try:
            data = sync_now()
            summary = {
                "ok": True,
                "synced_at": data.get("synced_at"),
                "as_of": data.get("as_of"),
                "campaign_clients": len(data.get("clients", [])),
                "raw_clients": (data.get("overview") or {}).get("raw_clients"),
                "raw_records": (data.get("overview") or {}).get("raw_records"),
                "source": data.get("source"),
            }
            LAST_SYNC.clear()
            LAST_SYNC.update(summary)
            self._json(200, summary)
        except Exception as exc:  # noqa: BLE001
            LAST_SYNC.clear()
            LAST_SYNC.update({"ok": False, "error": str(exc), "trace": traceback.format_exc()})
            self._json(500, {"ok": False, "error": str(exc)})
        finally:
            SYNC_LOCK.release()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    ensure_seed()
    host = get_env("HOST", "127.0.0.1") or "127.0.0.1"
    port = int(get_env("PORT", "8765") or "8765")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Altegio reports server: http://{host}:{port}/dashboards/index.html", flush=True)
    print("API: GET /api/data  POST /api/sync  GET /api/health", flush=True)
    print("First-time User Token: python scripts/auth_user_token.py", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped", flush=True)


if __name__ == "__main__":
    main()
