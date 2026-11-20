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
from branch_access import accessible_locations, connection_id, require_location_access
from sync_from_altegio import DATA_DIR, PORTAL_PATH, ensure_seed, portal_path_for, sync_location  # noqa: E402
from altegio_client import AltegioClient  # noqa: E402
from upsell_categories import list_categories, assign_category  # noqa: E402
from mailing_campaigns import load_campaigns, create_campaign, mark_sent, refresh_campaign, set_campaign_criteria  # noqa: E402
from automation_worker import AutomationStore, AutomationWorker  # noqa: E402

SYNC_LOCK = threading.Lock()
LAST_SYNC: dict = {"ok": True, "message": "ready"}
AUTOMATION_STORE = AutomationStore(DATA_DIR)
AUTOMATION_WORKER = AutomationWorker(AUTOMATION_STORE, AUTOMATION_STORE.configured_locations, SYNC_LOCK)


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

    def send_head(self):
        path = __import__('urllib.parse', fromlist=['unquote']).unquote(urlparse(self.path).path)
        asset = (ROOT / path.lstrip('/')).resolve()
        if ROOT / 'dashboards' not in asset.parents or asset.suffix not in {'.html', '.js', '.css', '.svg', '.ico'} or not asset.is_file():
            self.send_error(404)
            return None
        return super().send_head()

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
        if path == '/api/upsell/campaigns':
            try:
                location_id = require_location_access((query.get('location_id') or ['0'])[0])
                self._json(200, {'ok': True, 'items': load_campaigns(location_id)})
            except ValueError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception:
                self._json(500, {'ok': False, 'error': 'Не удалось прочитать сохранённые рассылки'})
            return
        if path == '/api/automation/settings':
            if self.client_address[0] not in {'127.0.0.1', '::1'}:
                self._json(403, {'ok': False, 'error': 'Локальный доступ обязателен.'})
                return
            try:
                location_id = require_location_access((query.get('location_id') or ['0'])[0])
                config = AUTOMATION_STORE.settings(location_id)
                config.pop('connection_fingerprint', None)
                self._json(200, {'ok': True, 'config': config,
                                 'status': AUTOMATION_STORE.status(location_id)})
            except (ValueError, PermissionError) as exc:
                self._json(403, {'ok': False, 'error': str(exc)})
            except Exception:
                self._json(500, {'ok': False, 'error': 'Не удалось прочитать локальные настройки автоматизации.'})
            return
        if path == '/api/client-categories':
            try:
                location_id = require_location_access((query.get('location_id') or ['0'])[0])
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
                    "location_id": get_env("ALTEGIO_LOCATION_ID") or None,
                    "last_sync": LAST_SYNC,
                },
            )
            return
        if path == "/api/locations":
            try:
                self._json(200, {"ok": True, "items": accessible_locations()})
            except Exception:
                self._json(401, {"ok": False, "items": [], "error": "Подключите свой аккаунт Altegio. Проверьте токены в .env."})
            return
        if path == "/api/data":
            try:
                location_id = require_location_access((query.get("location_id") or [get_env("ALTEGIO_LOCATION_ID")])[0])
                selected_path = portal_path_for(location_id)
                data = json.loads(selected_path.read_text(encoding="utf-8")) if selected_path.exists() else {}
                if data.get("connection_id") != connection_id() or int((data.get("location") or {}).get("id") or 0) != location_id:
                    data = sync_location(location_id)
                self._json(200, data)
            except (PermissionError, ValueError) as exc:
                self._json(403, {"ok": False, "error": str(exc)})
            except Exception:
                self._json(502, {"ok": False, "error": "Не удалось загрузить данные из вашего аккаунта Altegio."})
            return
        # Never expose .env, snapshots, logs, source files or directory listings.
        asset = (ROOT / __import__('urllib.parse', fromlist=['unquote']).unquote(path).lstrip('/')).resolve()
        if ROOT / 'dashboards' not in asset.parents or asset.suffix not in {'.html', '.js', '.css', '.svg', '.ico'} or not asset.is_file():
            self.send_error(404)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == '/api/automation/settings':
            origin = self.headers.get('Origin')
            if self.client_address[0] not in {'127.0.0.1', '::1'} or (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get_content_type() != 'application/json':
                self._json(403, {'ok': False, 'error': 'Только локальный same-origin запрос разрешён.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ValueError('Некорректный размер настроек.')
                payload = json.loads(self.rfile.read(length))
                location_id = require_location_access(payload.get('location_id'))
                config = AUTOMATION_STORE.save_settings(location_id, payload, connection_id())
                config.pop('connection_fingerprint', None)
                self._json(200, {'ok': True, 'config': config, 'status': AUTOMATION_STORE.status(location_id)})
            except (ValueError, TypeError, PermissionError) as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception:
                self._json(502, {'ok': False, 'error': 'Не удалось сохранить настройки автоматизации.'})
            return
        if path in {'/api/upsell/campaigns/create', '/api/upsell/campaigns/sent', '/api/upsell/campaigns/refresh', '/api/upsell/campaigns/criteria'}:
            origin = self.headers.get('Origin')
            if (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get_content_type() != 'application/json':
                self._json(403, {'ok': False, 'error': 'Same-origin JSON request required'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(length))
                location_id = require_location_access(payload.get('location_id'))
                # Validate branch before constructing an authenticated API client.
                load_campaigns(location_id)
                if path.endswith('/create'):
                    item = create_campaign(location_id, payload)
                elif path.endswith('/criteria'):
                    item = set_campaign_criteria(location_id, payload)
                elif path.endswith('/sent'):
                    item = mark_sent(AltegioClient(location_id=location_id), payload)
                else:
                    item = refresh_campaign(AltegioClient(location_id=location_id), payload)
                self._json(200, {'ok': True, 'item': item})
            except (ValueError, TypeError) as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception:
                self._json(502, {'ok': False, 'error': 'Не удалось получить записи Altegio. Сохранённые данные не изменены; повторите обновление.'})
            return
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
                location_id = require_location_access(payload['location_id'])
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
        default_id = get_env("ALTEGIO_LOCATION_ID")
        try:
            location_id = require_location_access((query.get("location_id") or [default_id])[0])
        except (ValueError, PermissionError) as exc:
            self._json(403, {"ok": False, "error": str(exc)})
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    host = get_env("HOST", "127.0.0.1") or "127.0.0.1"
    port = int(get_env("PORT", "8765") or "8765")
    server = ReportsHTTPServer((host, port), Handler)
    AUTOMATION_WORKER.start()
    print(f"Altegio reports server: http://{host}:{port}/dashboards/index.html", flush=True)
    print("API: GET /api/data  POST /api/sync  GET /api/health", flush=True)
    print("First-time User Token: python scripts/auth_user_token.py", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped", flush=True)
    finally:
        AUTOMATION_WORKER.stop()


if __name__ == "__main__":
    main()
