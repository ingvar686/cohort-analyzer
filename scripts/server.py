"""Local reports server: dashboard + live Altegio sync API (no AI tokens).

  python scripts/server.py

Then open http://127.0.0.1:8765/dashboards/index.html
"""

from __future__ import annotations

import json
import socket
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
from sync_from_altegio import DATA_DIR, PORTAL_PATH, ensure_seed, portal_path_for, sync_location  # noqa: E402
from altegio_client import AltegioClient  # noqa: E402
from upsell_categories import list_categories, assign_category  # noqa: E402

SYNC_LOCK = threading.Lock()
LAST_SYNC: dict = {"ok": True, "message": "ready"}


class ReportsHTTPServer(ThreadingHTTPServer):
    # Windows otherwise permits two Python servers to bind the same port,
    # leaving browsers connected to an older copy of the application.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = __import__("urllib.parse", fromlist=["parse_qs"]).parse_qs(parsed.query)
        if path == '/api/client-categories':
            try:
                location_id = int((query.get('location_id') or ['0'])[0])
                if not portal_path_for(location_id).exists():
                    raise ValueError('Unknown branch')
                items = list_categories(AltegioClient(location_id=location_id))
                self._json(200, {'ok': True, 'items': items})
            except Exception:
                self._json(400, {'ok': False, 'error': 'Не удалось прочитать категории клиентов. Проверьте доступ к филиалу и токены Altegio.'})
            return
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
        if path == "/api/locations":
            # Prefer locations with snapshots already associated with this dashboard.
            # Some API credentials can expose a broad demo/partner directory; those
            # unrelated branches must not replace the user's configured locations.
            snapshot_items = []
            seen_location_ids = set()
            snapshot_files = sorted(DATA_DIR.glob("portal_*.json"))
            preferred_snapshots = []
            configured_id = str(get_env("ALTEGIO_LOCATION_ID", "") or "")
            for snapshot in snapshot_files:
                try:
                    data = json.loads(snapshot.read_text(encoding="utf-8"))
                    loc = data.get("location") or {}
                    if str(loc.get("id", "")) == configured_id or data.get("source") == "altegio_mcp":
                        preferred_snapshots.append((snapshot, data))
                except Exception:  # noqa: BLE001
                    continue
            candidates = preferred_snapshots or [
                (snapshot, None) for snapshot in snapshot_files
            ]
            for snapshot, cached_data in candidates:
                try:
                    data = cached_data or json.loads(snapshot.read_text(encoding="utf-8"))
                    loc = data.get("location") or {}
                    location_id = loc.get("id")
                    if location_id is not None and str(location_id) not in seen_location_ids:
                        seen_location_ids.add(str(location_id))
                        snapshot_items.append({
                            "id": location_id,
                            "title": loc.get("name") or f"Location {location_id}",
                        })
                except Exception:  # noqa: BLE001
                    continue
            if snapshot_items:
                self._json(200, {"ok": True, "items": snapshot_items})
                return
            try:
                locations = AltegioClient().locations()
                items = [
                    {"id": x.get("id"), "title": x.get("title") or x.get("name") or f"Location {x.get('id')}", "address": x.get("address")}
                    for x in locations if x.get("id") is not None
                ]
                if not items:
                    raise RuntimeError("The API returned no locations")
                self._json(200, {"ok": True, "items": [
                    *items
                ]})
            except Exception as exc:  # noqa: BLE001
                items = []
                for snapshot in DATA_DIR.glob("portal_*.json"):
                    try:
                        data = json.loads(snapshot.read_text(encoding="utf-8"))
                        loc = data.get("location") or {}
                        if loc.get("id") is not None:
                            items.append({"id": loc["id"], "title": loc.get("name") or f"Location {loc['id']}"})
                    except Exception:  # noqa: BLE001
                        continue
                if not items and PORTAL_PATH.exists():
                    try:
                        data = json.loads(PORTAL_PATH.read_text(encoding="utf-8"))
                        loc = data.get("location") or {}
                        if loc.get("id") is not None:
                            items.append({"id": loc["id"], "title": loc.get("name") or f"Location {loc['id']}"})
                    except Exception:  # noqa: BLE001
                        pass
                self._json(200, {"ok": bool(items), "items": items, "error": str(exc)})
            return
        if path == "/api/data":
            default_id = int(get_env("ALTEGIO_LOCATION_ID", "764940") or "764940")
            try:
                location_id = int((query.get("location_id") or [default_id])[0])
            except ValueError:
                self._json(400, {"ok": False, "error": "Invalid location_id"})
                return
            selected_path = portal_path_for(location_id)
            if not selected_path.exists() and location_id == default_id and PORTAL_PATH.exists():
                selected_path = PORTAL_PATH
            if not selected_path.exists() and get_env("ALTEGIO_USER_TOKEN"):
                data = sync_location(location_id)
            elif selected_path.exists():
                data = json.loads(selected_path.read_text(encoding="utf-8"))
            elif location_id == default_id:
                ensure_seed()
                data = json.loads(PORTAL_PATH.read_text(encoding="utf-8"))
            else:
                self._json(404, {"ok": False, "error": "No local data for this location. Sync the selected branch."})
                return
            self._json(200, data)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == '/api/upsell/assign-category':
            # JSON-only, same-origin writes; no API credentials reach the browser.
            origin = self.headers.get('Origin')
            if (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get_content_type() != 'application/json':
                self._json(403, {'ok': False, 'error': 'Same-origin JSON request required'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(length))
                location_id = int(payload['location_id'])
                if not SYNC_LOCK.acquire(blocking=False):
                    self._json(409, {'ok': False, 'error': 'Другая операция ещё выполняется'})
                    return
                try:
                    result = assign_category(AltegioClient(location_id=location_id), payload)
                finally:
                    SYNC_LOCK.release()
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception:
                self._json(502, {'ok': False, 'error': 'Не удалось выполнить операцию в Altegio. Проверьте категорию и повторите: уже добавленные клиенты будут пропущены.'})
            return
        if path != "/api/sync":
            self._json(404, {"ok": False, "error": "Not found"})
            return
        parsed = urlparse(self.path)
        query = __import__("urllib.parse", fromlist=["parse_qs"]).parse_qs(parsed.query)
        default_id = int(get_env("ALTEGIO_LOCATION_ID", "764940") or "764940")
        try:
            location_id = int((query.get("location_id") or [default_id])[0])
        except ValueError:
            self._json(400, {"ok": False, "error": "Invalid location_id"})
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
            data = sync_location(location_id)
            summary = {
                "ok": True,
                "synced_at": data.get("synced_at"),
                "as_of": data.get("as_of"),
                "clients": len(data.get("clients", [])),
                "location_id": location_id,
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
    server = ReportsHTTPServer((host, port), Handler)
    print(f"Altegio reports server: http://{host}:{port}/dashboards/index.html", flush=True)
    print("API: GET /api/data  POST /api/sync  GET /api/health", flush=True)
    print("First-time User Token: python scripts/auth_user_token.py", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped", flush=True)


if __name__ == "__main__":
    main()
