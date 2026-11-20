"""Regression checks for attribution and persistent mailing lifecycle; no API writes."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mailing_campaigns as m

SENT = '2026-11-01T10:00:00+00:00'
NOW = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)


def record(rid, cid=1, *, created='2026-11-02T12:00:00+01:00',
           visit='2026-11-04T12:00:00+01:00', attendance=1, paid=1, cost=40):
    return {'id': rid, 'client': {'id': cid}, 'create_date': created, 'datetime': visit,
            'attendance': attendance, 'paid_full': paid,
            'services': [{'id': 10, 'title': 'Nails', 'cost': cost},
                         {'id': 20, 'title': 'Haircut', 'cost': 100}]}


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.campaign = {'recipient_ids': [1, 2, 3, 4], 'sent_at': SENT,
                         'window_days': 30, 'cost': 10,
                         'services': [{'id': 10, 'title': 'Nails'}]}

    def test_unique_buyers_only_offered_revenue_and_existing_bookings(self):
        records = [record(1), record(1), record(2, cost=30), record(3, cid=2, paid=0),
                   record(4, cid=3, created='2026-10-30T12:00:00+01:00'),
                   record(5, cid=4, cost=0), record(6, cid=99)]
        result = m.evaluate_campaign(self.campaign, records, NOW)
        self.assertEqual((result['recipients'], result['booked'], result['buyers']), (4, 3, 2))
        self.assertEqual(result['conversion'], 50)
        self.assertEqual(result['revenue'], 70)  # Haircuts and duplicate records excluded.
        self.assertEqual(result['cost_per_buyer'], 5)
        self.assertEqual(result['excluded']['preexisting'], 1)
        self.assertEqual(len(result['clients'][0]['records']), 2)
        self.assertEqual(result['clients'][3]['revenue'], 0)  # Free service stays zero.

    def test_future_unpaid_cancelled_and_unknown_times_are_not_purchases(self):
        records = [record(1, visit='2026-11-20T12:00:00+01:00'),
                   record(2, cid=2, attendance=0), record(3, cid=3, attendance=-1),
                   record(4, cid=4, created='2026-11-02 12:00:00')]
        result = m.evaluate_campaign(self.campaign, records, NOW)
        self.assertEqual((result['booked'], result['buyers'], result['revenue']), (2, 0, 0))
        self.assertEqual(result['excluded']['unknown_dates'], 1)
        self.assertEqual(result['excluded']['cancelled'], 1)
        self.assertFalse(result['complete'])

    def test_exact_window_and_offsets(self):
        records = [record(1, created='2026-11-01T11:00:00+01:00', visit='2026-11-01T11:00:00+01:00'),
                   record(2, cid=2, visit='2026-12-01T11:00:00+01:00'),
                   record(3, cid=3, visit='2026-11-01T10:59:59+01:00'),
                   record(4, cid=4, created='2026-12-01T11:00:00+01:00')]
        result = m.evaluate_campaign(self.campaign, records, NOW)
        self.assertEqual((result['buyers'], result['revenue']), (1, 40))

    def test_missing_price_warns_instead_of_using_catalog_or_other_service(self):
        row = record(1)
        del row['services'][0]['cost']
        result = m.evaluate_campaign(self.campaign, [row], NOW)
        self.assertEqual(result['buyers'], 1)
        self.assertEqual(result['revenue'], 0)
        self.assertEqual(result['excluded']['unknown_revenue'], 1)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        db = {'as_of': '2026-10-31', 'location': {'id': 1, 'currency': 'EUR'},
              'clients': [{'id': 1}, {'id': 2}],
              'service_catalog': {'categories': [{'id': 100, 'title': 'Haircuts'}, {'id': 200, 'title': 'Manicure'}],
                                  'services': [{'id': 10, 'title': 'Nails', 'category_id': 200},
                                               {'id': 11, 'title': 'Haircut', 'category_id': 100}]}}
        (self.data / 'portal_1.json').write_text(json.dumps(db), encoding='utf-8')
        self.data_patch = patch.object(m, 'DATA', self.data)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.temporary.cleanup)
        self.payload = {'name': 'Nails offer', 'client_ids': [1, 2, 1], 'service_ids': [10],
                        'window_days': 30, 'cost': 10}

    def criteria(self):
        return {'version': 1, 'source_category': {'id': 100, 'title': 'Incorrect user label'},
                'source_services': [{'id': 11, 'title': 'Incorrect service label'}],
                'source_minimum_visits': 10, 'target': {'kind': 'category', 'id': 200},
                'target_maximum_visits_exclusive': 1, 'as_of': '2026-10-31'}

    def test_filter_snapshot_survives_reload_and_uses_original_catalog_names(self):
        criteria = self.criteria()
        created = m.create_campaign(1, {**self.payload, 'criteria': criteria})
        criteria['source_minimum_visits'] = 50
        path = self.data / 'portal_1.json'
        db = json.loads(path.read_text(encoding='utf-8'))
        db['service_catalog']['categories'][0]['title'] = 'Renamed later'
        path.write_text(json.dumps(db), encoding='utf-8')
        saved = m.load_campaigns(1)[0]['criteria']
        self.assertEqual(saved['source_category'], {'id': 100, 'title': 'Haircuts'})
        self.assertEqual(saved['source_services'], [{'id': 11, 'title': 'Haircut'}])
        self.assertEqual(saved['source_minimum_visits'], 10)
        self.assertEqual(saved['target_maximum_visits_exclusive'], 1)
        self.assertTrue(saved['source_all_services'])
        self.assertEqual(created['criteria'], saved)

    def test_invalid_filter_scope_is_rejected_and_legacy_filters_are_not_invented(self):
        for update in ({'source_minimum_visits': 0}, {'target_maximum_visits_exclusive': True},
                       {'source_services': [{'id': 10}]}, {'target': {'kind': 'service', 'id': 11}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                m.create_campaign(1, {**self.payload, 'criteria': {**self.criteria(), **update}})
        created = m.create_campaign(1, self.payload)
        self.assertNotIn('criteria', created)

    def test_legacy_description_can_be_added_once_without_changing_audience_or_results(self):
        campaign = m.create_campaign(1, self.payload)
        campaign.update(status='sent', sent_at=SENT, recipient_ids=[1], result={'buyers': 1, 'revenue': 40})
        m.save_campaigns(1, [campaign])
        updated = m.set_campaign_criteria(1, {'campaign_id': campaign['id'], 'criteria': self.criteria()})
        self.assertEqual(updated['criteria_origin'], 'manual')
        self.assertTrue(updated['criteria_recorded_at'])
        for field in ('client_ids', 'recipient_ids', 'result', 'status', 'sent_at', 'name'):
            self.assertEqual(updated[field], campaign[field])
        with self.assertRaises(ValueError):
            m.set_campaign_criteria(1, {'campaign_id': campaign['id'], 'criteria': {**self.criteria(), 'source_minimum_visits': 20}})
        self.assertEqual(m.load_campaigns(1)[0]['criteria']['source_minimum_visits'], 10)

    def test_immutable_audience_sent_once_refresh_and_branch_isolation(self):
        with patch.object(m, 'now_utc', return_value=datetime(2026, 11, 1, 9, tzinfo=timezone.utc)):
            campaign = m.create_campaign(1, self.payload)
        self.assertEqual(campaign['client_ids'], [1, 2])
        calls = []

        class FakeAPI:
            location_id = 1

            def iter_records(self, start, end):
                calls.append((start, end))
                return [record(100)]

        with patch.object(m, 'now_utc', return_value=NOW):
            sent = m.mark_sent(FakeAPI(), {'campaign_id': campaign['id'], 'recipient_ids': [1], 'sent_at': SENT})
            self.assertEqual(sent['result']['buyers'], 1)
            self.assertEqual(sent['result']['conversion'], 100)
            with self.assertRaises(ValueError):
                m.mark_sent(FakeAPI(), {'campaign_id': campaign['id'], 'recipient_ids': [2], 'sent_at': SENT})
            updated = m.refresh_campaign(FakeAPI(), {'campaign_id': campaign['id']})
        self.assertEqual(updated['recipient_ids'], [1])
        self.assertEqual(updated['client_ids'], [1, 2])
        self.assertTrue(calls)
        self.assertEqual(m.load_campaigns(1)[0]['services'], campaign['services'])
        self.assertEqual(m.load_campaigns(1)[0]['result']['revenue'], 40)
        with self.assertRaises(ValueError):
            m.load_campaigns(2)

    def test_invalid_input_does_not_create_any_file(self):
        for overrides in ({'client_ids': [999]}, {'service_ids': [999]}, {'cost': float('nan')},
                          {'window_days': 0}, {'name': ''}, {'client_ids': [True]}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                m.create_campaign(1, {**self.payload, **overrides})
        self.assertFalse((self.data / 'mailing_campaigns_1.json').exists())

    def test_failure_reading_altegio_does_not_record_sending(self):
        with patch.object(m, 'now_utc', return_value=datetime(2026, 11, 1, 9, tzinfo=timezone.utc)):
            campaign = m.create_campaign(1, self.payload)

        class UnavailableAPI:
            location_id = 1

            def iter_records(self, *args):
                raise RuntimeError('Offline')

        with self.assertRaises(RuntimeError), patch.object(m, 'now_utc', return_value=NOW):
            m.mark_sent(UnavailableAPI(), {'campaign_id': campaign['id'], 'recipient_ids': [1], 'sent_at': SENT})
        self.assertEqual(m.load_campaigns(1)[0]['status'], 'draft')

    def test_http_lifecycle_and_cross_origin_write_rejection(self):
        import server

        # This fixture is an already-authorized branch; authorization failures
        # and cross-account cache rejection are covered by test_branch_access.
        access = patch.object(server, 'require_location_access', side_effect=lambda value: int(value))
        access.start()
        self.addCleanup(access.stop)

        class ReadOnlyAPI:
            def __init__(self, location_id):
                self.location_id = location_id

            def iter_records(self, start, end):
                return [record(100)]

        httpd = server.ReportsHTTPServer(('127.0.0.1', 0), server.Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{httpd.server_port}'

        def call(path, body=None, origin_header=origin):
            headers = {'Content-Type': 'application/json', 'Origin': origin_header}
            req = urllib.request.Request(origin + '/api/upsell/campaigns' + path,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)

        try:
            self.assertEqual(call('?location_id=1')['items'], [])
            with self.assertRaises(urllib.error.HTTPError) as error:
                call('/create', {'location_id': 1, **self.payload}, 'https://another-site.example')
            self.assertEqual(error.exception.code, 403)
            with patch.object(m, 'now_utc', return_value=datetime(2026, 11, 1, 9, tzinfo=timezone.utc)):
                created = call('/create', {'location_id': 1, **self.payload})['item']
            with patch.object(server, 'AltegioClient', ReadOnlyAPI), patch.object(m, 'now_utc', return_value=NOW):
                sent = call('/sent', {'location_id': 1, 'campaign_id': created['id'],
                                      'recipient_ids': [1], 'sent_at': SENT})['item']
                self.assertEqual(sent['result']['buyers'], 1)
                refreshed = call('/refresh', {'location_id': 1, 'campaign_id': created['id']})['item']
                self.assertEqual(refreshed['result']['revenue'], 40)
            self.assertEqual(call('?location_id=1')['items'][0]['recipient_ids'], [1])
        finally:
            httpd.shutdown()
            worker.join(timeout=5)
            httpd.server_close()


if __name__ == '__main__':
    unittest.main()
