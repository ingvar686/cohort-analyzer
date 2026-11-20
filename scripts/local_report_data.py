"""Convert read-only MCP responses into the existing dashboard data contract."""
import hashlib
import json
import math
import os
import threading
from datetime import date, datetime
from pathlib import Path


def currency_from_location(data):
    for key in ('currency_iso', 'currency_code', 'currency'):
        value = data.get(key)
        if isinstance(value, str) and len(value) == 3 and value.isalpha():
            return value.upper()
    # A bare dollar sign is ambiguous; ask the user rather than invent USD.
    return {'€': 'EUR', '£': 'GBP', '₴': 'UAH', '₽': 'RUB', 'zł': 'PLN', 'R$': 'BRL', '₸': 'KZT'}.get(data.get('currency_short_title'))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def history_visits(items, as_of):
    groups, seen = {}, set()
    for item in items:
        raw_date = str(item.get('date') or '')[:10]
        if not item.get('visit_id') or not item.get('services') or item.get('outcome') != 'arrived' or not raw_date or raw_date > as_of:
            continue
        date.fromisoformat(raw_date)
        signature = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            continue
        seen.add(signature)
        key = (int(item['visit_id']), raw_date)
        paid = item.get('total_paid')
        complete = item.get('payment_status') in {'fully_paid', 'overpaid'} and finite(paid) and paid >= 0
        row = groups.setdefault(key, {'visit_id': key[0], 'date': raw_date, 'attendance': 'arrived', 'services': [], 'revenue': 0, 'sold': 0, 'paid_in_full': True})
        row['paid_in_full'] = row['paid_in_full'] and complete
        row['revenue'] += paid if finite(paid) else 0
        row['sold'] += item['total_cost'] if finite(item.get('total_cost')) else 0
        row['services'].extend(s['title'] for s in item['services'] if s.get('title'))
    for row in groups.values():
        row['revenue'] = round(row['revenue'], 2)
        row['services'] = list(dict.fromkeys(row['services']))
        row['service'] = ', '.join(row['services'])
    return sorted(groups.values(), key=lambda row: (row['date'], row['visit_id']))


class LocalReportData:
    def __init__(self, mcp, folder):
        self.mcp = mcp
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.sync_lock = threading.Lock()
        self.status = {'running': False, 'message': '', 'current': 0, 'total': 0}

    @property
    def owner(self):
        return hashlib.sha256(self.mcp.connection_key.encode()).hexdigest()

    def locations(self):
        return [{'id': int(row['id']), 'title': row.get('title') or str(row['id'])} for row in self.mcp.pages('locations_list')]

    def require_access(self, location_id):
        location_id = int(location_id)
        if location_id <= 0 or location_id not in {row['id'] for row in self.locations()}:
            raise PermissionError('Этот филиал недоступен подключённому аккаунту Altegio.')
        return location_id

    def location_info(self, location_id):
        location_id = self.require_access(location_id)
        response = self.mcp.call('api_call_operation', {'operation_id': 'get_location', 'params': {'location_id': location_id}})
        raw = response.get('data') or {}
        if not isinstance(raw, dict) or int(raw.get('id') or 0) != location_id:
            raise RuntimeError('Altegio не подтвердил выбранный филиал.')
        return {'id': location_id, 'name': raw.get('title') or str(location_id), 'currency': currency_from_location(raw)}

    def _path(self, location_id):
        # Separate physical folders for different sign-ins, in addition to marker checks.
        folder = self.folder / self.owner
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f'portal_{int(location_id)}.json'

    def cached(self, location_id):
        path = self._path(location_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('connection_id') != self.owner or (data.get('location') or {}).get('id') != int(location_id):
            return None
        return data

    def synchronize(self, location_id, currency, progress=None):
        if not self.sync_lock.acquire(blocking=False):
            raise RuntimeError('Загрузка уже выполняется. Дождитесь её завершения.')
        try:
            location_id = self.require_access(location_id)
            if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
                raise ValueError('Выберите валюту филиала.')
            owner = self.owner
            self.status = {'running': True, 'message': 'Загружаем каталог и категории клиентов…', 'current': 0, 'total': 0}
            info = self.location_info(location_id)
            info['currency'] = currency.upper()
            service_categories = list(self.mcp.pages('service_categories_list', {'location_id': location_id}))
            services = list(self.mcp.pages('services_list', {'location_id': location_id}))
            profiles = list(self.mcp.pages('clients_list_profiles', {'location_id': location_id, 'include_contacts': bool(self.mcp.credentials.get('contacts'))}))
            as_of = date.today().isoformat()
            clients, counts = [], {}
            total = len(profiles)
            for number, profile in enumerate(profiles, 1):
                self.status = {'running': True, 'message': f'История клиентов: {number} из {total}', 'current': number, 'total': total}
                if progress:
                    progress(dict(self.status))
                tags = list(dict.fromkeys(tag['title'] for tag in profile.get('tags', []) if tag.get('title')))
                for tag in tags:
                    counts[tag] = counts.get(tag, 0) + 1
                history, cursor, cursors = [], as_of, set()
                # No skipping based on a possibly stale visit_count from the card.
                while True:
                    if cursor in cursors:
                        raise RuntimeError('Altegio повторил страницу истории; неполный отчёт не сохранён.')
                    cursors.add(cursor)
                    result = self.mcp.call('clients_get_visit_history', {'location_id': location_id, 'client_id': int(profile['id']), 'date_from': '2000-01-01', 'date_to': cursor, 'outcome': 'arrived'})
                    history.extend(result.get('items') or [])
                    pagination = result.get('pagination') or {}
                    if not pagination.get('has_more'):
                        break
                    cursor = pagination.get('next_date_to')
                    if not cursor:
                        raise RuntimeError('Altegio не указал следующую страницу истории.')
                visits = history_visits(history, as_of)
                clients.append({'id': int(profile['id']), 'name': profile.get('display_name') or profile.get('name') or str(profile['id']),
                                'phone': profile.get('phone') or '', 'categories': tags, 'campaign': tags[0] if tags else 'Без категории',
                                'first_visit': visits[0]['date'] if visits else '', 'visits': visits, 'visit_count': len(visits),
                                'revenue': round(sum(v['revenue'] for v in visits), 2)})
            if self.owner != owner:
                raise RuntimeError('Аккаунт изменился во время загрузки. Повторите подключение.')
            data = {'source': 'altegio_mcp', 'connection_id': owner, 'as_of': as_of, 'synced_at': datetime.now().isoformat(timespec='seconds'),
                    'location': info, 'clients': clients, 'directory': clients, 'campaigns': sorted(counts),
                    'categories': [{'title': key, 'client_count': value} for key, value in sorted(counts.items())], 'default_budgets': {},
                    'coverage': {'from': '2000-01-01', 'to': as_of, 'complete': True},
                    'service_catalog': {'categories': [{'id': int(row['id']), 'title': row.get('title') or str(row['id'])} for row in service_categories],
                                        'services': [{'id': int(row['id']), 'title': row.get('title') or str(row['id']), 'category_id': row.get('category_id'), 'active': bool(row.get('active', True))} for row in services]}}
            path = self._path(location_id)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, path)
            self.status = {'running': False, 'message': 'Данные обновлены', 'current': total, 'total': total}
            return data
        except Exception:
            self.status = {**self.status, 'running': False, 'message': 'Загрузка не завершена. Предыдущий отчёт сохранён.'}
            raise
        finally:
            self.sync_lock.release()
