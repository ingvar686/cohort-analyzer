"""Local, immutable mailing audiences and read-only Altegio outcome tracking.

This module never sends messages or changes Altegio records.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sync_from_altegio import client_id_of, record_is_fully_paid, record_revenue

DATA = Path(__file__).resolve().parent.parent / 'data'
LOCK = threading.RLock()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def now_utc():
    return datetime.now(timezone.utc)


def load_branch(location_id, *, folder=None):
    if type(location_id) is not int or location_id <= 0:
        raise ValueError('Некорректный филиал')
    path = Path(folder or DATA) / f'portal_{location_id}.json'
    if not path.exists():
        raise ValueError('Сначала загрузите данные этого филиала')
    db = json.loads(path.read_text(encoding='utf-8'))
    if (db.get('location') or {}).get('id') != location_id:
        raise ValueError('Филиал не совпадает со снимком')
    return db


def load_campaigns(location_id, *, folder=None):
    load_branch(location_id, folder=folder)
    path = Path(folder or DATA) / f'mailing_campaigns_{location_id}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def save_campaigns(location_id, campaigns, *, folder=None):
    path = Path(folder or DATA) / f'mailing_campaigns_{location_id}.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(campaigns, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def catalog_for(db, *, folder=None):
    catalog = db.get('service_catalog')
    if not catalog:
        catalogs = json.loads((Path(folder or DATA) / 'service_catalog.json').read_text(encoding='utf-8'))
        catalog = catalogs.get(str(db['location']['id']), {})
    return catalog


def valid_ids(values):
    if not isinstance(values, list) or not values or len(values) > 1000:
        raise ValueError('Выберите от 1 до 1000 клиентов')
    if any(type(x) is not int or x <= 0 for x in values):
        raise ValueError('Некорректные идентификаторы')
    return list(dict.fromkeys(values))


def normalize_criteria(value, db, offered_service_ids, *, folder=None):
    """Save the original selection, resolving names from its branch catalog."""
    if value is None:
        return None  # Older campaigns do not contain a recoverable filter snapshot.
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Некорректное описание фильтров рассылки')
    catalog = catalog_for(db, folder=folder)
    categories = {int(c['id']): c for c in catalog.get('categories', [])}
    services = {int(s['id']): s for s in catalog.get('services', [])}
    source, target = value.get('source_category'), value.get('target')
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError('Укажите категории лояльности и допродажи')
    source_id, target_id = source.get('id'), target.get('id')
    if type(source_id) is not int or source_id not in categories or type(target_id) is not int:
        raise ValueError('Категория фильтра отсутствует в каталоге филиала')
    minimum, maximum = value.get('source_minimum_visits'), value.get('target_maximum_visits_exclusive')
    if any(type(x) is not int or not 1 <= x <= 1000000 for x in (minimum, maximum)):
        raise ValueError('Некорректные пороги посещений')
    raw_services = value.get('source_services')
    if not isinstance(raw_services, list) or not raw_services or any(not isinstance(s, dict) for s in raw_services):
        raise ValueError('Укажите услуги для определения лояльности')
    source_ids = valid_ids([s.get('id') for s in raw_services])
    if any(sid not in services or str(services[sid].get('category_id')) != str(source_id) for sid in source_ids):
        raise ValueError('Услуги лояльности не соответствуют выбранной категории')
    kind = target.get('kind')
    if kind == 'category' and target_id in categories:
        target_category = target_id
        selected_target = categories[target_id]
        allowed_offers = {sid for sid, service in services.items() if str(service.get('category_id')) == str(target_id)}
    elif kind == 'service' and target_id in services:
        selected_target = services[target_id]
        target_category = int(selected_target['category_id'])
        allowed_offers = {target_id}
    else:
        raise ValueError('Услуга или категория допродажи отсутствует в каталоге')
    if target_category not in categories or not set(offered_service_ids) <= allowed_offers:
        raise ValueError('Предложенные услуги не соответствуют сохранённым фильтрам')
    parent_maximum = value.get('target_category_maximum_visits_exclusive')
    if parent_maximum is not None and (kind != 'service' or type(parent_maximum) is not int or parent_maximum != maximum):
        raise ValueError('Некорректный порог категории допродажи')
    as_of = value.get('as_of') or db.get('as_of')
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of or as_of > db.get('as_of', as_of):
        raise ValueError('Некорректная дата истории для отбора')
    all_source = {sid for sid, service in services.items() if str(service.get('category_id')) == str(source_id)}
    return {'version': 1, 'source_category': {'id': source_id, 'title': categories[source_id]['title']},
            'source_services': [{'id': sid, 'title': services[sid]['title']} for sid in source_ids],
            'source_all_services': set(source_ids) == all_source, 'source_minimum_visits': minimum,
            'target': {'kind': kind, 'id': target_id, 'title': selected_target['title'],
                       'category_id': target_category, 'category_title': categories[target_category]['title']},
            'target_maximum_visits_exclusive': maximum,
            'target_category_maximum_visits_exclusive': parent_maximum, 'as_of': as_of}


def create_campaign(location_id, payload, *, folder=None):
    db = load_branch(location_id, folder=folder)
    ids = valid_ids(payload.get('client_ids'))
    allowed = {c.get('id') for c in (db.get('directory') or []) + db.get('clients', [])}
    if not set(ids) <= allowed:
        raise ValueError('В списке есть клиенты другого филиала')
    selected_services = valid_ids(payload.get('service_ids'))
    catalog = {s['id']: s for s in catalog_for(db, folder=folder).get('services', [])}
    if not set(selected_services) <= catalog.keys():
        raise ValueError('Выберите услуги из каталога филиала')
    name = str(payload.get('name') or '').strip()
    days, cost = payload.get('window_days', 30), payload.get('cost', 0)
    if not name or len(name) > 160:
        raise ValueError('Название должно содержать от 1 до 160 символов')
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError('Срок оценки: от 1 до 365 дней')
    if type(cost) not in (int, float) or not math.isfinite(cost) or not 0 <= cost <= 10000000:
        raise ValueError('Укажите корректные расходы')
    criteria = normalize_criteria(payload.get('criteria'), db, selected_services, folder=folder)
    campaign = {'id': uuid.uuid4().hex, 'location_id': location_id, 'name': name,
                'created_at': now_utc().isoformat(), 'status': 'draft', 'client_ids': ids,
                'services': [{'id': sid, 'title': catalog[sid]['title']} for sid in selected_services],
                'window_days': days, 'cost': round(cost, 2),
                'currency': (db.get('location') or {}).get('currency') or 'EUR',
                'offer': str(payload.get('offer') or '')[:200], 'snapshot_as_of': db.get('as_of')}
    if criteria is not None:
        campaign['criteria'] = criteria
        campaign['criteria_origin'] = 'captured'
    with LOCK:
        campaigns = load_campaigns(location_id, folder=folder)
        campaigns.append(campaign)
        save_campaigns(location_id, campaigns, folder=folder)
    return campaign


def find_campaign(campaigns, campaign_id):
    found = next((c for c in campaigns if c['id'] == campaign_id), None)
    if found is None:
        raise ValueError('Рассылка не найдена в этом филиале')
    return found


def set_campaign_criteria(location_id, payload, *, folder=None):
    """Let the owner describe a legacy audience without changing its membership."""
    with LOCK:
        db = load_branch(location_id, folder=folder)
        items = load_campaigns(location_id, folder=folder)
        campaign = find_campaign(items, payload.get('campaign_id'))
        if campaign.get('criteria') is not None:
            raise ValueError('Фильтры этой рассылки уже сохранены и не изменяются')
        criteria = normalize_criteria(payload.get('criteria'), db,
                                      [s['id'] for s in campaign['services']], folder=folder)
        if criteria is None:
            raise ValueError('Укажите исходные фильтры отбора')
        campaign.update(criteria=criteria, criteria_origin='manual', criteria_recorded_at=now_utc().isoformat())
        save_campaigns(location_id, items, folder=folder)
        return campaign


def read_records(api, sent, days):
    # Include the full window, including future bookings. Completed revenue is
    # separately limited to the observation timestamp.
    start, end = sent.date() - timedelta(days=1), (sent + timedelta(days=days+1)).date()
    records = {}
    while start <= end:
        stop = min(start + timedelta(days=89), end)
        for record in api.iter_records(start.isoformat(), stop.isoformat()):
            if record.get('company_id') not in (None, api.location_id):
                continue
            if record.get('id') is not None:
                records[str(record['id'])] = record
        start = stop + timedelta(days=1)
    return list(records.values())


def evaluate_campaign(campaign, records, observed_at=None):
    now = observed_at or now_utc()
    sent = timestamp(campaign['sent_at'])
    end = sent + timedelta(days=campaign['window_days'])
    recipients = {cid: {'client_id': cid, 'booked': False, 'paid': False,
                        'revenue': 0, 'records': []} for cid in campaign['recipient_ids']}
    services = {str(s['id']) for s in campaign['services']}
    excluded = {'preexisting': 0, 'unknown_dates': 0, 'unknown_revenue': 0, 'cancelled': 0}
    seen = set()
    for record in records:
        rid = str(record.get('id') or '')
        if not rid or rid in seen:
            continue
        seen.add(rid)
        cid = client_id_of(record)
        if cid not in recipients:
            continue
        lines = [s for s in record.get('services') or [] if str(s.get('id')) in services]
        if not lines:
            continue
        visit = timestamp(record.get('datetime') or record.get('date'))
        created = timestamp(record.get('create_date') or record.get('created_at'))
        if visit and not sent <= visit < end:
            continue
        if not visit or not created:
            excluded['unknown_dates'] += 1
            continue
        if created < sent:
            excluded['preexisting'] += 1
            continue
        if created > now or created >= end:
            continue
        attendance = record.get('attendance', record.get('visit_attendance'))
        cancelled = bool(record.get('deleted')) or attendance in (-1, '-1', 'cancelled', 'client_cancelled', 'no_show')
        if cancelled:
            excluded['cancelled'] += 1
            continue
        attended = attendance in (1, '1', 'arrived', 'completed', 'client_came', 'success')
        paid = attended and visit <= now and record_is_fully_paid(record, record_revenue(record))
        revenue, unknown = 0, False
        if paid:
            for line in lines:
                # `cost` is the final service-line cost used by this API. Preserve
                # genuine zero prices; do not substitute a catalog/list price.
                try:
                    amount = float(line['cost'])
                    if not math.isfinite(amount) or amount < 0:
                        raise ValueError()
                    revenue += amount
                except (KeyError, ValueError, TypeError):
                    unknown = True
            if unknown:
                excluded['unknown_revenue'] += 1
        row = recipients[cid]
        row['booked'] = True
        row['paid'] |= paid
        row['revenue'] += revenue
        row['records'].append({'id': record['id'], 'created_at': created.isoformat(),
                               'visit_at': visit.isoformat(), 'paid': paid,
                               'revenue': round(revenue, 2), 'unknown_revenue': unknown,
                               'services': [s.get('title') or str(s['id']) for s in lines]})
    rows = list(recipients.values())
    buyers = sum(r['paid'] for r in rows)
    for row in rows:
        row['revenue'] = round(row['revenue'], 2)
    return {'observed_at': now.isoformat(), 'ends_at': end.isoformat(), 'complete': now >= end,
            'recipients': len(rows), 'booked': sum(r['booked'] for r in rows), 'buyers': buyers,
            'conversion': round(buyers / len(rows) * 100, 2) if rows else 0,
            'revenue': round(sum(r['revenue'] for r in rows), 2),
            'cost_per_buyer': round(campaign['cost'] / buyers, 2) if buyers else None,
            'excluded': excluded, 'clients': rows}


def mark_sent(api, payload, *, folder=None):
    with LOCK:
        campaigns = load_campaigns(api.location_id, folder=folder)
        campaign = find_campaign(campaigns, payload.get('campaign_id'))
        if campaign['status'] != 'draft':
            raise ValueError('Отправка уже зафиксирована; список и дата не меняются')
        ids = valid_ids(payload.get('recipient_ids'))
        if not set(ids) <= set(campaign['client_ids']):
            raise ValueError('Получатели должны входить в сохранённую группу')
        sent = timestamp(payload.get('sent_at'))
        now = now_utc()
        if not sent or sent > now or sent < timestamp(campaign['created_at']):
            raise ValueError('Дата отправки должна быть между созданием рассылки и текущим моментом')
        records = read_records(api, sent, campaign['window_days'])
        campaign.update(status='sent', sent_at=sent.isoformat(), recipient_ids=ids,
                        baseline_at=now.isoformat(), baseline_record_ids=[r['id'] for r in records])
        campaign['result'] = evaluate_campaign(campaign, records)
        save_campaigns(api.location_id, campaigns, folder=folder)
        return campaign


def refresh_campaign(api, payload, *, folder=None):
    with LOCK:
        campaigns = load_campaigns(api.location_id, folder=folder)
        campaign = find_campaign(campaigns, payload.get('campaign_id'))
        if campaign['status'] != 'sent':
            raise ValueError('Сначала отметьте фактическую отправку')
        records = read_records(api, timestamp(campaign['sent_at']), campaign['window_days'])
        campaign['result'] = evaluate_campaign(campaign, records)
        save_campaigns(api.location_id, campaigns, folder=folder)
        return campaign
