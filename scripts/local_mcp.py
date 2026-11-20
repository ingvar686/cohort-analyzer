"""A deterministic read-only MCP client. No AI service or private partner key."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ISSUER = 'https://api.alteg.io'
RESOURCE = 'https://mcp.alteg.io/pro/readonly'
SCOPES = 'locations:read clients:read appointments:read services:read'
READ_TOOLS = {'locations_list', 'clients_list_profiles', 'clients_get_visit_history', 'services_list', 'service_categories_list', 'api_call_operation', 'appointments_list'}


class ConnectionRequired(RuntimeError):
    pass


class LocalMcp:
    def __init__(self, store, transport=None):
        self.store = store
        self.credentials = store.read()
        self.transport = transport or self._http
        self.lock = threading.RLock()
        self.metadata = None
        self.pending = None
        self.session_id = None
        self.protocol = '2025-03-26'
        self.rpc_id = 0
        self.available_tools = None

    @staticmethod
    def _http(method, url, body=None, headers=None):
        all_headers = {'User-Agent': 'AltegioAnalyticsLocal/1.0', 'Accept': 'application/json', **(headers or {})}
        raw = None
        if body is not None:
            if all_headers.get('Content-Type') == 'application/x-www-form-urlencoded':
                raw = urllib.parse.urlencode(body).encode()
            else:
                all_headers['Content-Type'] = 'application/json'
                raw = json.dumps(body).encode()
        request = urllib.request.Request(url, method=method, data=raw, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            # Do not expose upstream bodies that can contain credentials.
            raise RuntimeError(f'Altegio HTTP {error.code}') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Нет соединения с Altegio. Проверьте интернет и повторите.') from None

    def _json(self, method, url, body=None, headers=None):
        status, response_headers, raw = self.transport(method, url, body, headers)
        return json.loads(raw) if raw else {}, response_headers

    def discovery(self):
        if self.metadata:
            return self.metadata
        data, _ = self._json('GET', ISSUER + '/.well-known/oauth-authorization-server')
        if data.get('issuer') != ISSUER or 'S256' not in data.get('code_challenge_methods_supported', []):
            raise RuntimeError('Altegio вернул неподдерживаемые настройки входа.')
        for field in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'):
            parsed = urllib.parse.urlsplit(data.get(field, ''))
            if parsed.scheme != 'https' or parsed.netloc != 'api.alteg.io':
                raise RuntimeError('Некорректный адрес авторизации Altegio.')
        self.metadata = data
        return data

    def begin_login(self, redirect_uri, contacts=False):
        with self.lock:
            parsed = urllib.parse.urlsplit(redirect_uri)
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/oauth/callback':
                raise ValueError('Неверный локальный адрес возврата.')
            metadata = self.discovery()
            registration = self.credentials.get('registration') or {}
            if registration.get('redirect_uri') != redirect_uri:
                registration, _ = self._json('POST', metadata['registration_endpoint'], {
                    'client_name': 'Altegio Analytics Local', 'application_type': 'native',
                    'redirect_uris': [redirect_uri], 'token_endpoint_auth_method': 'none',
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                })
                if not registration.get('client_id'):
                    raise RuntimeError('Altegio не зарегистрировал локальное приложение.')
                registration = {'client_id': registration['client_id'], 'redirect_uri': redirect_uri}
                self.credentials['registration'] = registration
                self.store.write(self.credentials)
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            state = secrets.token_urlsafe(32)
            scope = SCOPES + (' clients:read_contact' if contacts else '')
            self.pending = {'state': state, 'verifier': verifier, 'created': time.time(), 'redirect_uri': redirect_uri, 'contacts': contacts}
            query = {'response_type': 'code', 'client_id': registration['client_id'], 'redirect_uri': redirect_uri,
                     'scope': scope, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'resource': RESOURCE}
            return metadata['authorization_endpoint'] + '?' + urllib.parse.urlencode(query)

    def complete_login(self, query):
        with self.lock:
            pending = self.pending
            self.pending = None
            if not pending or time.time() - pending['created'] > 600 or not hmac.compare_digest(str(query.get('state', '')), pending['state']):
                raise RuntimeError('Запрос входа устарел. Нажмите «Войти через Altegio» ещё раз.')
            if query.get('iss') != ISSUER or not query.get('code') or query.get('error'):
                raise RuntimeError('Вход не подтверждён на стороне Altegio.')
            token, _ = self._json('POST', self.discovery()['token_endpoint'], {
                'grant_type': 'authorization_code', 'client_id': self.credentials['registration']['client_id'],
                'code': query['code'], 'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['verifier'], 'resource': RESOURCE,
            }, {'Content-Type': 'application/x-www-form-urlencoded'})
            if not token.get('access_token'):
                raise RuntimeError('Altegio не выдал доступ к данным.')
            self.credentials.update(tokens={**token, 'expires_at': time.time() + float(token.get('expires_in', 3600))},
                                    connection_key=secrets.token_urlsafe(32), contacts=pending['contacts'])
            self.store.write(self.credentials)
            self.session_id = None

    def access_token(self):
        token = self.credentials.get('tokens') or {}
        if not token.get('access_token'):
            raise ConnectionRequired('Войдите через Altegio.')
        if token.get('expires_at', 0) < time.time() + 60:
            if not token.get('refresh_token'):
                raise ConnectionRequired('Сеанс завершён. Войдите через Altegio ещё раз.')
            fresh, _ = self._json('POST', self.discovery()['token_endpoint'], {
                'grant_type': 'refresh_token', 'refresh_token': token['refresh_token'],
                'client_id': self.credentials['registration']['client_id'], 'resource': RESOURCE,
            }, {'Content-Type': 'application/x-www-form-urlencoded'})
            if not fresh.get('access_token'):
                raise ConnectionRequired('Сеанс завершён. Войдите через Altegio ещё раз.')
            self.credentials['tokens'] = {**token, **fresh, 'expires_at': time.time() + float(fresh.get('expires_in', 3600))}
            self.store.write(self.credentials)
        return self.credentials['tokens']['access_token']

    def _rpc(self, method, params=None, notification=False):
        self.rpc_id += 1
        request = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            request['params'] = params
        if not notification:
            request['id'] = self.rpc_id
        headers = {'Authorization': 'Bearer ' + self.access_token(), 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': self.protocol}
        if self.session_id and self.session_id != 'stateless':
            headers['Mcp-Session-Id'] = self.session_id
        status, received_headers, raw = self.transport('POST', RESOURCE, request, headers)
        for key, value in received_headers.items():
            if key.lower() == 'mcp-session-id':
                self.session_id = value
        if notification or not raw:
            return {}
        if raw.lstrip().startswith(b'{'):
            response = json.loads(raw)
        else:
            response = None
            for line in raw.decode().splitlines():
                if line.startswith('data:'):
                    item = json.loads(line[5:].strip())
                    if item.get('id') == request['id']:
                        response = item
            if response is None:
                raise RuntimeError('Не удалось прочитать ответ Altegio MCP.')
        if response.get('error'):
            raise RuntimeError('Altegio MCP отклонил запрос чтения.')
        return response.get('result') or {}

    def call(self, name, arguments=None):
        if name not in READ_TOOLS or (name == 'api_call_operation' and (arguments or {}).get('operation_id') not in {'get_location', 'get_appointment'}):
            raise ValueError('Локальный отчёт разрешает только чтение данных.')
        with self.lock:
            if self.session_id is None:
                initialization = self._rpc('initialize', {'protocolVersion': self.protocol, 'capabilities': {}, 'clientInfo': {'name': 'altegio-analytics-local', 'version': '1.0'}})
                self.protocol = initialization.get('protocolVersion', self.protocol)
                self._rpc('notifications/initialized', notification=True)
                if self.session_id is None:
                    self.session_id = 'stateless'
                self.available_tools = set()
                cursor = None
                while True:
                    listing = self._rpc('tools/list', {'cursor': cursor} if cursor else {})
                    self.available_tools.update(tool['name'] for tool in listing.get('tools', []))
                    cursor = listing.get('nextCursor')
                    if not cursor:
                        break
            if name not in (self.available_tools or ()) and 'tools_call_read' in (self.available_tools or ()):
                call = {'name': 'tools_call_read', 'arguments': {'tool': name, 'arguments': arguments or {}}}
            else:
                call = {'name': name, 'arguments': arguments or {}}
            result = self._rpc('tools/call', call)
            if result.get('isError'):
                raise RuntimeError('Altegio MCP не смог прочитать данные. Проверьте права аккаунта и повторите.')
            data = result.get('structuredContent')
            if not isinstance(data, dict):
                raise RuntimeError('Altegio MCP не вернул структурированные данные отчёта.')
            return data

    def pages(self, name, arguments=None, page_size=50):
        page, seen = 1, set()
        while True:
            if page in seen:
                raise RuntimeError('Altegio повторил страницу данных; загрузка остановлена.')
            seen.add(page)
            result = self.call(name, {**(arguments or {}), 'page': page, 'page_size': page_size})
            yield from result.get('items', [])
            pagination = result.get('pagination') or {}
            next_page = pagination.get('next_page')
            if next_page is None:
                if pagination.get('has_more'):
                    raise RuntimeError('Altegio не указал следующую страницу.')
                break
            page = int(next_page)
            page_size = int(pagination.get('next_page_size') or pagination.get('page_size') or page_size)

    @property
    def connected(self):
        return bool(self.credentials.get('tokens', {}).get('access_token'))

    @property
    def connection_key(self):
        if not self.connected:
            raise ConnectionRequired('Войдите через Altegio.')
        return self.credentials['connection_key']

    def logout(self):
        with self.lock:
            token = self.credentials.get('tokens', {}).get('refresh_token')
            if token:
                try:
                    metadata = self.discovery()
                    url = metadata.get('revocation_endpoint')
                    if url == ISSUER + '/oauth/revoke':
                        self._json('POST', url, {'token': token, 'token_type_hint': 'refresh_token', 'client_id': self.credentials['registration']['client_id']}, {'Content-Type': 'application/x-www-form-urlencoded'})
                except RuntimeError:
                    pass
            self.credentials = {};self.pending = None;self.session_id = None
            self.store.clear()
