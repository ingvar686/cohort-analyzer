"""Mailing audiences stay local; outcomes are read through the signed-in MCP user."""
import mailing_campaigns as campaigns


class McpCampaignReader:
    def __init__(self, mcp, location_id, campaign):
        self.mcp = mcp
        self.location_id = location_id
        self.client_ids = set(campaign.get('recipient_ids') or campaign['client_ids'])
        self.service_ids = {s['id'] for s in campaign['services']}

    def iter_records(self, start, end):
        for item in self.mcp.pages('appointments_list', {
            'location_id': self.location_id, 'date_from': start, 'date_to': end,
            'include_contacts': False, 'include_deleted': True,
        }):
            if item.get('client_id') not in self.client_ids:
                continue
            if not any(s.get('id') in self.service_ids for s in item.get('services', [])):
                continue
            response = self.mcp.call('api_call_operation', {
                'operation_id': 'get_appointment',
                'params': {'location_id': self.location_id, 'appointment_id': int(item['id'])},
            })
            raw = response.get('data')
            if not isinstance(raw, dict) or raw.get('id') != item['id'] or raw.get('location_id') != self.location_id:
                raise RuntimeError('Altegio не подтвердил запись; прежний результат сохранён.')
            # Full appointment details include creation time and final service-line
            # prices, which the compact appointments_list response can omit.
            record = dict(raw)
            record['company_id'] = self.location_id
            record['client_id'] = (raw.get('client') or {}).get('id')
            record['attendance'] = {'arrived': 1, 'confirmed': 2, 'waiting': 0,
                                    'no_show': -1, 'cancelled': -1}.get(raw.get('status'), 'unknown')
            if record['client_id'] != item['client_id']:
                raise RuntimeError('Клиент записи изменился; повторите обновление результата.')
            yield record


class DesktopMailings:
    def __init__(self, reports):
        self.reports = reports

    def folder(self, location_id):
        location_id = self.reports.require_access(location_id)
        if self.reports.cached(location_id) is None:
            raise ValueError('Сначала загрузите отчёт выбранного филиала.')
        return self.reports._path(location_id).parent

    def list(self, location_id):
        return campaigns.load_campaigns(location_id, folder=self.folder(location_id))

    def create(self, location_id, payload):
        return campaigns.create_campaign(location_id, payload, folder=self.folder(location_id))

    def update(self, location_id, action, payload):
        folder = self.folder(location_id)
        if action == 'criteria':
            return campaigns.set_campaign_criteria(location_id, payload, folder=folder)
        owner = self.reports.owner
        campaign = campaigns.find_campaign(campaigns.load_campaigns(location_id, folder=folder), payload.get('campaign_id'))
        reader = McpCampaignReader(self.reports.mcp, location_id, campaign)
        # The connection is rechecked before every MCP read. A new sign-in never
        # writes results into the previous connection's campaign directory.
        original = reader.iter_records

        def records(start, end):
            if owner != self.reports.owner:
                raise RuntimeError('Аккаунт изменился; повторите открытие отчёта.')
            rows = list(original(start, end))
            if owner != self.reports.owner:
                raise RuntimeError('Аккаунт изменился; прежний результат сохранён.')
            return rows

        reader.iter_records = records
        if action == 'sent':
            return campaigns.mark_sent(reader, payload, folder=folder)
        if action == 'refresh':
            return campaigns.refresh_campaign(reader, payload, folder=folder)
        raise ValueError('Неизвестное действие с рассылкой.')
