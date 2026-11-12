"""Client tag assignment from a reviewed dashboard audience.

Contracts: developer.alteg.io/_bundle/en/b2b-v1/openapi.json (client PUT,
labels) and b2b-v2/openapi.json (location tags, entity=client).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from altegio_client import AltegioClient

DATA = Path(__file__).resolve().parent.parent / 'data'

def list_categories(api):
    base = api.api_base.rsplit('/api/', 1)[0] + '/api/v2'
    payload = api.request('GET', f'{base}/locations/{api.location_id}/tags', params={'entity': 'client'})
    rows = []
    for item in payload.get('data') or []:
        attrs = item.get('attributes') or item
        if attrs.get('is_deleted') or attrs.get('entity_type', 'client') not in ('client', 1, '1'):
            continue
        rows.append({'id': int(item['id']), 'title': attrs.get('title') or str(item['id'])})
    return rows

def assign_category(api, payload):
    ids = list(dict.fromkeys(payload.get('client_ids') or []))
    if not ids or len(ids) > 1000 or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError('Choose 1–1000 clients with valid IDs')
    snapshot = DATA / f'portal_{api.location_id}.json'
    db = json.loads(snapshot.read_text(encoding='utf-8'))
    allowed = {c.get('id') for c in db.get('clients', [])}
    if not set(ids) <= allowed:
        raise ValueError('Audience does not belong to the loaded branch snapshot. Refresh the report.')
    categories = list_categories(api)
    tag_id = payload.get('tag_id')
    if tag_id:
        category = next((c for c in categories if c['id'] == tag_id), None)
        if not category:
            raise ValueError('Client category not found in this branch')
    else:
        title = str(payload.get('new_title') or '').strip()
        if not title or len(title) > 100:
            raise ValueError('Category name must contain 1–100 characters')
        category = next((c for c in categories if c['title'] == title), None)
        if category is None:
            base = api.api_base.rsplit('/api/', 1)[0] + '/api/v2'
            api.request('POST', f'{base}/locations/{api.location_id}/tags', body={'title': title, 'color': '#f0b429', 'entity': 1}, retries=1)
            category = next((c for c in list_categories(api) if c['title'] == title), None)
            if category is None:
                raise RuntimeError('Created category could not be verified')
    result = {'ok': True, 'category': category, 'added': 0, 'existing': 0, 'failed': [], 'successful_ids': []}
    preserve = ('name','surname','patronymic','phone','email','sex_id','importance_id','discount','card','birth_date','comment','sms_check','sms_not','online_booking_ban','client_agreements','custom_fields')
    def card(cid):
        data = api.request('GET', f'client/{api.location_id}/{cid}').get('data')
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            raise RuntimeError('Client card is unavailable')
        return data
    def tags(raw):
        values = raw.get('categories', raw.get('labels'))
        if not isinstance(values, list):
            raise RuntimeError('Existing client categories are unavailable; update skipped')
        return {int(x['id'] if isinstance(x, dict) else x) for x in values}
    for cid in ids:
        try:
            raw = card(cid)
            old = tags(raw)
            if category['id'] in old:
                result['existing'] += 1
            else:
                if not raw.get('name') or not raw.get('phone') or any(c in str(raw['phone']) for c in '*•'):
                    raise RuntimeError('Full client edit access is required')
                body = {k: raw[k] for k in preserve if k in raw}
                body['labels'] = sorted(old | {category['id']})
                response = api.request('PUT', f'client/{api.location_id}/{cid}', body=body, retries=1)
                if response.get('success') is False:
                    raise RuntimeError('Altegio rejected the update')
                current = tags(card(cid))
                if not old | {category['id']} <= current:
                    raise RuntimeError('Client category update could not be verified')
                result['added'] += 1
            result['successful_ids'].append(cid)
        except Exception as exc:
            # Avoid returning entire API responses containing client contacts.
            result['failed'].append({'client_id': cid, 'error': str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__})
    baseline = {'created_at': datetime.now(timezone.utc).isoformat(), 'location_id': api.location_id,
                'offer': str(payload.get('offer') or '')[:200], 'snapshot_as_of': db.get('as_of'),
                'requested_ids': ids, **result}
    with (DATA / 'upsell_audiences.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(baseline, ensure_ascii=False) + '\n')
    return result
