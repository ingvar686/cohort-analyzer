"""Bind local snapshots to the currently configured Altegio connection."""
import hashlib

from altegio_client import AltegioClient
from env_loader import get_env


def connection_id():
    partner, user = get_env('ALTEGIO_PARTNER_TOKEN'), get_env('ALTEGIO_USER_TOKEN')
    if not partner or not user:
        raise PermissionError('Подключите свой аккаунт Altegio: заполните .env и получите User Token.')
    return hashlib.sha256((partner + '\0' + user).encode()).hexdigest()


def accessible_locations():
    connection_id()
    rows = AltegioClient().locations()
    return [{'id': int(row['id']), 'title': row.get('title') or row.get('name') or str(row['id'])}
            for row in rows if row.get('id')]


def require_location_access(location_id):
    if not str(location_id).isdigit() or int(location_id) <= 0:
        raise ValueError('Выберите свой филиал Altegio.')
    location_id = int(location_id)
    if location_id not in {row['id'] for row in accessible_locations()}:
        raise PermissionError('У текущего аккаунта Altegio нет доступа к этому филиалу.')
    return location_id
