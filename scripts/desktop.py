"""One-click Windows launcher with local storage and Altegio browser sign-in."""
import argparse
import hmac
import html
import json
import os
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from local_credentials import CredentialStore
from local_mcp import LocalMcp, ConnectionRequired
from local_report_data import LocalReportData

APP_BUILD = '2026.11.19-legacy-filters-2'

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'dashboards'
PUBLIC_ASSETS = {'index.html', 'upsell.js', 'mailings.js', 'monthly-budgets.js', 'campaign-comparison.js', 'desktop-bootstrap.js'}


def escape_automation_notice():
    page = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    :root{color-scheme:light;--bg:#f5f5f2;--panel:#fff;--ink:#202020;--muted:#65655d;--line:#deded5}
    :root[data-theme=dark]{color-scheme:dark;--bg:#111110;--panel:#1d1d1a;--ink:#f5f4ed;--muted:#b1b0a3;--line:#3d3d34}
    *{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--ink);font:14px/1.6 "Segoe UI",Arial,sans-serif}
    main{max-width:900px;border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:26px}h2{font-size:22px;margin:0 0 12px}p,li{color:var(--muted)}li{margin:8px 0}button{border:1px solid #e3bb00;background:#ffd100;color:#181818;border-radius:7px;padding:10px 15px;cursor:pointer;font:inherit}
    </style></head><body><main><h2>Категории клиентов назначаются вручную</h2>
    <p>В Windows-приложении подготовьте аудиторию и название категории, затем добавьте клиентов в неё в кабинете Altegio.</p>
    <ol><li>В «Возможностях допродаж» выберите нужную группу клиентов.</li><li>Скопируйте предлагаемое название категории и скачайте список клиентов.</li><li>Создайте категорию и добавьте клиентов в Altegio.</li><li>Сохраните рассылку в дашборде, чтобы отслеживать записи, покупки и выручку.</li></ol>
    <p>Автоматический обработчик правил работает в серверной версии с отдельным подключением. В этой Windows-сборке категории назначает сам пользователь.</p>
    <button id="openUpsell" type="button">Перейти к возможностям допродаж</button></main><script>
    const origin=parent.location.origin;
    addEventListener('message',event=>{if(event.source===parent&&event.origin===origin&&event.data?.channel==='altegio-dashboard'&&event.data.type==='theme')document.documentElement.dataset.theme=event.data.theme==='dark'?'dark':'light'});
    document.getElementById('openUpsell').onclick=()=>parent.postMessage({channel:'altegio-automation-sandbox',type:'open-upsell'},origin);
    parent.postMessage({channel:'altegio-automation-sandbox',type:'resize',height:document.documentElement.scrollHeight},origin);
    </script></body></html>'''
    return html.escape(page, quote=True)


def open_running_instance(profile, app_id='altegio-analytics-local'):
    """A second double-click reopens the same app instead of sharing refresh tokens."""
    path = Path(profile) / 'instance.json'
    if not path.exists():
        return False
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
        address = urllib.parse.urlsplit(previous['origin'])
        if address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port or not 1024 <= address.port <= 65535:
            return False
        request = urllib.request.Request(previous['origin'] + '/api/desktop/state', headers={'X-App-Token': previous['nonce']})
        with urllib.request.urlopen(request, timeout=1) as response:
            if json.load(response).get('app') != app_id:
                return False
        webbrowser.open(previous['origin'])
        return True
    except (OSError, ValueError, KeyError):
        return False


class DesktopServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DesktopApplication:
    app_id = 'altegio-analytics-local'
    name = 'Altegio Analytics'
    profile_name = 'AltegioAnalytics'
    preferred_port = 9473
    public_assets = PUBLIC_ASSETS
    has_mailings = True
    credential_store = CredentialStore

    def __init__(self, profile, mcp=None, port=0):
        self.profile = Path(profile)
        self.profile.mkdir(parents=True, exist_ok=True)
        self.mcp = mcp or LocalMcp(self.credential_store(self.profile))
        self.reports = LocalReportData(self.mcp, self.profile / 'data')
        if self.has_mailings:
            from desktop_mailings import DesktopMailings
            self.mailings = DesktopMailings(self.reports)
        self.nonce = secrets.token_urlsafe(32)
        self.settings_path = self.profile / 'settings.json'
        self.settings = json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        self.httpd = DesktopServer(('127.0.0.1', port), DesktopHandler)
        self.httpd.app = self
        self.origin = f'http://127.0.0.1:{self.httpd.server_port}'
        self.login_error = ''

    def save_settings(self):
        temporary = self.settings_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.settings), encoding='utf-8')
        os.replace(temporary, self.settings_path)

    @classmethod
    def dashboard_template(cls):
        return (ASSETS / 'index.html').read_text(encoding='utf-8')

    def index(self):
        html = self.dashboard_template()
        marker = 'const initialLoad=initializeLocations();'
        if marker not in html:
            raise RuntimeError('Версия интерфейса несовместима с приложением.')
        html = html.replace(marker, 'const initialLoad=initializeDesktopReport();')
        html = html.replace('<script src="upsell.js"></script>', '<script>window.__desktopToken=' + json.dumps(self.nonce) + ';</script><script src="desktop-bootstrap.js"></script><script src="upsell.js"></script>')
        # The REST automation worker is not part of the read-only desktop app.
        # Keep the navigation understandable instead of pointing at a missing
        # iframe route, which otherwise displays a JSON 404 inside the report.
        html = html.replace('src="automation-sandbox/index.html?embedded=1"',
                            'srcdoc="' + escape_automation_notice() + '"')
        return html.encode('utf-8')

    def state(self):
        return {'app': self.app_id, 'build': APP_BUILD, 'connected': self.mcp.connected, 'read_only': True,
                'capabilities': {'mailings': self.has_mailings, 'client_category_write': False},
                'contacts': bool(self.mcp.credentials.get('contacts')), 'selected_location': self.settings.get('location_id'),
                'progress': dict(self.reports.status), 'login_error': self.login_error}


class DesktopHandler(BaseHTTPRequestHandler):
    @property
    def app(self):
        return self.server.app

    def log_message(self, *args):
        # In particular, never log authorization codes from callback URLs.
        pass

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        raw = json.dumps(body, ensure_ascii=False).encode() if not isinstance(body, bytes) else body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def host_allowed(self):
        return self.headers.get('Host') == self.app.origin.removeprefix('http://')

    def authorized_api(self):
        return self.host_allowed() and hmac.compare_digest(self.headers.get('X-App-Token', ''), self.app.nonce)

    def do_GET(self):
        if not self.host_allowed():
            self.respond(403, {'ok': False, 'error': 'Invalid host'})
            return
        parsed = urllib.parse.urlsplit(self.path)
        query = {key: value[0] for key, value in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path == '/oauth/callback':
            try:
                self.app.mcp.complete_login(query)
                self.app.login_error = ''
            except Exception as error:
                self.app.login_error = str(error)
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            return
        if parsed.path.startswith('/api/'):
            if not self.authorized_api():
                self.respond(403, {'ok': False, 'error': 'Откройте отчёт из локального приложения.'})
                return
            try:
                if parsed.path == '/api/desktop/state':
                    self.respond(200, self.app.state())
                elif parsed.path == '/api/locations':
                    self.respond(200, {'ok': True, 'items': self.app.reports.locations()})
                elif parsed.path == '/api/desktop/location':
                    info = self.app.reports.location_info(query.get('location_id'))
                    info['currency'] = self.app.settings.get('currencies', {}).get(str(info['id'])) or info['currency']
                    self.respond(200, {'ok': True, 'location': info})
                elif parsed.path == '/api/data':
                    location_id = self.app.reports.require_access(query.get('location_id'))
                    data = self.app.reports.cached(location_id)
                    if data is None:
                        self.respond(404, {'ok': False, 'error': 'Нажмите «Загрузить мой отчёт».'})
                    else:
                        self.respond(200, data)
                elif self.app.has_mailings and parsed.path == '/api/upsell/campaigns':
                    location_id = int(query.get('location_id') or 0)
                    self.respond(200, {'ok': True, 'items': self.app.mailings.list(location_id)})
                elif parsed.path == '/api/health':
                    self.respond(200, {'ok': True, 'location_id': self.app.settings.get('location_id')})
                else:
                    self.respond(404, {'ok': False})
            except ConnectionRequired as error:
                self.respond(401, {'ok': False, 'error': str(error)})
            except (ValueError, PermissionError) as error:
                self.respond(403, {'ok': False, 'error': str(error)})
            except Exception as error:
                self.respond(502, {'ok': False, 'error': str(error)})
            return
        filename = 'index.html' if parsed.path in ('/', '/index.html', '/dashboards/index.html') else parsed.path.removeprefix('/dashboards/').lstrip('/')
        if filename not in self.app.public_assets:
            self.respond(404, {'ok': False})
            return
        raw = self.app.index() if filename == 'index.html' else (ASSETS / filename).read_bytes()
        mime = 'text/html; charset=utf-8' if filename.endswith('.html') else 'text/javascript; charset=utf-8'
        self.respond(200, raw, mime)

    def do_POST(self):
        if not self.authorized_api() or self.headers.get('Origin') != self.app.origin:
            self.respond(403, {'ok': False, 'error': 'Same-origin request required'})
            return
        parsed = urllib.parse.urlsplit(self.path)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 100000:
                raise ValueError('Request too large')
            if length and self.headers.get_content_type() != 'application/json':
                raise ValueError('JSON request required')
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict):
                raise ValueError('JSON object required')
            if parsed.path == '/api/desktop/login':
                self.app.login_error = ''
                url = self.app.mcp.begin_login(self.app.origin + '/oauth/callback', contacts=body.get('contacts') is True)
                self.respond(200, {'ok': True, 'url': url})
            elif parsed.path == '/api/desktop/logout':
                self.app.mcp.logout()
                self.app.settings = {}
                self.app.save_settings()
                self.respond(200, {'ok': True})
            elif self.app.has_mailings and parsed.path in ('/api/upsell/campaigns/create', '/api/upsell/campaigns/sent', '/api/upsell/campaigns/refresh', '/api/upsell/campaigns/criteria'):
                location_id = int(body.get('location_id') or 0)
                if parsed.path.endswith('/create'):
                    item = self.app.mailings.create(location_id, body)
                else:
                    item = self.app.mailings.update(location_id, parsed.path.rsplit('/', 1)[1], body)
                self.respond(200, {'ok': True, 'item': item})
            elif parsed.path in ('/api/desktop/open', '/api/sync'):
                query = urllib.parse.parse_qs(parsed.query)
                location_id = int(body.get('location_id') or (query.get('location_id') or [0])[0])
                currency = body.get('currency') or self.app.settings.get('currencies', {}).get(str(location_id))
                if parsed.path == '/api/desktop/open':
                    self.app.reports.require_access(location_id)
                    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
                        raise ValueError('Выберите валюту филиала.')
                    self.app.settings['location_id'] = location_id
                    self.app.settings.setdefault('currencies', {})[str(location_id)] = currency.upper()
                    self.app.save_settings()
                cached = self.app.reports.cached(location_id) if parsed.path == '/api/desktop/open' else None
                data = cached or self.app.reports.synchronize(location_id, currency)
                self.respond(200, {'ok': True, 'location_id': data['location']['id'], 'synced_at': data['synced_at']})
            else:
                self.respond(403, {'ok': False, 'error': 'Эта версия приложения имеет доступ только на чтение.'})
        except ConnectionRequired as error:
            self.respond(401, {'ok': False, 'error': str(error)})
        except (ValueError, PermissionError) as error:
            self.respond(400, {'ok': False, 'error': str(error)})
        except Exception as error:
            self.respond(502, {'ok': False, 'error': str(error)})


def main(application_type=DesktopApplication):
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--profile', type=Path)
    args = parser.parse_args()
    if args.smoke_test:
        # No browser, login, profile reads or network calls in packaged self-check.
        assert all((ASSETS / name).is_file() for name in application_type.public_assets)
        assert b'"clients":[]' in (ASSETS / 'index.html').read_bytes()
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            store = CredentialStore(folder)
            store.write({'self_test': True})
            assert store.read() == {'self_test': True}
        print('Desktop assets OK')
        return
    profile = args.profile or Path(os.environ['LOCALAPPDATA']) / application_type.profile_name
    if open_running_instance(profile, application_type.app_id):
        return
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    root.title(application_type.name)
    root.geometry('440x210')
    root.resizable(False, False)
    root.configure(background='#f5f5f2')
    try:
        # Prefer one stable loopback port; a busy port is never taken from another process.
        try:
            application = application_type(profile, port=application_type.preferred_port)
        except OSError:
            application = application_type(profile, port=0)
        threading.Thread(target=application.httpd.serve_forever, daemon=True).start()
        (profile / 'instance.json').write_text(json.dumps({'origin': application.origin, 'nonce': application.nonce}), encoding='utf-8')
        ttk.Label(root, text='Отчёт работает на этом компьютере', font=('Segoe UI', 13, 'bold')).pack(pady=(24, 8))
        ttk.Label(root, text='Войдите через Altegio в открывшемся браузере.\nДанные не отправляются в ИИ-чат.', justify='center').pack(pady=(0, 15))
        ttk.Button(root, text='Открыть отчёт', command=lambda: webbrowser.open(application.origin)).pack(ipadx=24, ipady=5)
        ttk.Label(root, text='Закройте это окно, чтобы остановить приложение.').pack(pady=14)
        def close():
            application.httpd.shutdown()
            application.httpd.server_close()
            instance = profile / 'instance.json'
            if instance.exists() and json.loads(instance.read_text(encoding='utf-8')).get('nonce') == application.nonce:
                instance.unlink()
            root.destroy()
        root.protocol('WM_DELETE_WINDOW', close)
        webbrowser.open(application.origin)
        root.mainloop()
    except Exception:
        messagebox.showerror(application_type.name, 'Не удалось запустить приложение. Проверьте доступ к папке профиля и повторите запуск.')
        root.destroy()


if __name__ == '__main__':
    main()
