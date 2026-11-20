import base64
import hashlib
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from desktop import DesktopApplication
from local_credentials import CredentialStore
from local_mcp import ISSUER, RESOURCE, LocalMcp, ConnectionRequired
from local_report_data import LocalReportData, currency_from_location, history_visits
from desktop_mailings import DesktopMailings
import mailing_campaigns


class MemoryStore:
    def __init__(self, value=None): self.value = value or {}
    def read(self): return self.value
    def write(self, value): self.value = json.loads(json.dumps(value))
    def clear(self): self.value = {}


class OAuthTransport:
    def __init__(self): self.calls = []
    def __call__(self, method, url, body=None, headers=None):
        self.calls.append((method, url, body, headers or {}))
        if url.endswith('/.well-known/oauth-authorization-server'):
            data = {'issuer': ISSUER, 'code_challenge_methods_supported': ['S256'],
                    'authorization_endpoint': ISSUER+'/oauth/authorize', 'registration_endpoint': ISSUER+'/oauth/register', 'token_endpoint': ISSUER+'/oauth/token'}
        elif url.endswith('/oauth/register'): data = {'client_id': 'public-local-client'}
        elif url.endswith('/oauth/token'): data = {'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_in': 3600}
        elif url == RESOURCE:
            if body['method'] == 'notifications/initialized': return 202, {}, b''
            if body['method'] == 'initialize': result = {'protocolVersion': '2025-03-26'}
            elif body['method'] == 'tools/list': result = {'tools': [{'name': 'tools_call_read'}]}
            else: result = {'structuredContent': {'items': [{'id': 1}], 'pagination': {'next_page': None}}}
            return 200, {'Content-Type':'text/event-stream'}, ('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\n\n').encode()
        else: raise AssertionError('Unexpected destination: '+url)
        return 200, {}, json.dumps(data).encode()


class DesktopAuthTests(unittest.TestCase):
    def test_tokens_are_encrypted_for_current_windows_user(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CredentialStore(folder)
            store.write({'tokens':{'access_token':'unique-fake-secret'}})
            self.assertNotIn(b'unique-fake-secret',store.path.read_bytes())
            self.assertEqual(store.read()['tokens']['access_token'],'unique-fake-secret')
            store.clear();self.assertFalse(store.path.exists())

    def test_browser_login_pkce_issuer_and_read_only_rpc(self):
        transport=OAuthTransport();store=MemoryStore();client=LocalMcp(store,transport)
        url=client.begin_login('http://127.0.0.1:9473/oauth/callback')
        query=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertEqual(query['resource'],[RESOURCE])
        self.assertNotIn('write',query['scope'][0]);self.assertNotIn('clients:read_contact',query['scope'][0])
        verifier=client.pending['verifier']
        expected=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(query['code_challenge'],[expected])
        client.complete_login({'state':query['state'][0],'iss':ISSUER,'code':'valid-code'})
        self.assertTrue(client.connected)
        self.assertEqual(client.call('locations_list')['items'],[{'id':1}])
        rpc=transport.calls[-1][2]
        self.assertEqual(rpc['params']['name'],'tools_call_read')
        self.assertEqual(rpc['params']['arguments']['tool'],'locations_list')
        with self.assertRaises(ValueError):client.call('visits_add_payment',{})
        with self.assertRaises(ValueError):client.call('api_call_operation',{'operation_id':'delete_appointment'})

    def test_wrong_state_never_exchanges_code(self):
        transport=OAuthTransport();client=LocalMcp(MemoryStore(),transport)
        client.begin_login('http://127.0.0.1:9473/oauth/callback')
        with self.assertRaises(RuntimeError):client.complete_login({'state':'wrong','iss':ISSUER,'code':'x'})
        self.assertFalse(any(url.endswith('/oauth/token') for _,url,_,_ in transport.calls))
        self.assertFalse(client.connected)

    def test_refresh_keeps_snapshot_identity(self):
        transport=OAuthTransport();store=MemoryStore({'registration':{'client_id':'public'},'connection_key':'owner-a',
            'tokens':{'access_token':'old','refresh_token':'refresh','expires_at':0}})
        client=LocalMcp(store,transport);self.assertEqual(client.access_token(),'fake-access')
        self.assertEqual(client.connection_key,'owner-a')

    def test_pagination_follows_effective_page_size(self):
        client=LocalMcp(MemoryStore())
        calls=[]
        def call(name,args):
            calls.append(args)
            return {'items':[{'id':args['page']}],'pagination':{'next_page':2,'next_page_size':10}} if args['page']==1 else {'items':[],'pagination':{'next_page':None}}
        client.call=call
        self.assertEqual(len(list(client.pages('clients_list_profiles'))),1)
        self.assertEqual(calls[1]['page_size'],10)


class FakeMcp:
    connected=True
    credentials={'contacts':False}
    connection_key='owner-a'
    def pages(self,name,args=None):
        rows={'locations_list':[{'id':1,'title':'Own Salon'}],
              'service_categories_list':[{'id':10,'title':'Hair'}],
              'services_list':[{'id':11,'title':'Haircut','category_id':10,'active':True}],
              'clients_list_profiles':[{'id':2,'name':'Customer','tags':[{'title':'Google Maps'}]}]}
        yield from rows[name]
    def call(self,name,args):
        if name=='api_call_operation':return {'data':{'id':1,'title':'Own Salon','currency_short_title':'€'}}
        return {'items':[{'visit_id':5,'date':'2026-01-02 10:00:00','outcome':'arrived','payment_status':'fully_paid',
                          'total_cost':100,'total_paid':80,'services':[{'title':'Haircut','cost':100}]}], 'pagination':{'has_more':False}}


class ReportTests(unittest.TestCase):
    def test_actual_paid_is_used_and_accounts_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            mcp=FakeMcp();reports=LocalReportData(mcp,folder)
            data=reports.synchronize(1,'EUR')
            visit=data['clients'][0]['visits'][0]
            self.assertEqual(visit['revenue'],80);self.assertEqual(visit['sold'],100)
            self.assertEqual(data['clients'][0]['categories'],['Google Maps'])
            self.assertTrue(reports.cached(1))
            mcp.connection_key='owner-b'
            self.assertIsNone(reports.cached(1))

    def test_partial_history_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            mcp=FakeMcp();reports=LocalReportData(mcp,folder);reports.synchronize(1,'EUR')
            previous=reports._path(1).read_bytes();original=mcp.call
            mcp.call=lambda name,args: {'items':[],'pagination':{'has_more':True,'next_date_to':None}} if name=='clients_get_visit_history' else original(name,args)
            with self.assertRaises(RuntimeError):reports.synchronize(1,'EUR')
            self.assertEqual(reports._path(1).read_bytes(),previous)

    def test_duplicate_history_and_unknown_currency(self):
        item=FakeMcp().call('clients_get_visit_history',{})['items'][0]
        self.assertEqual(len(history_visits([item,item],'2026-11-17')),1)
        self.assertIsNone(currency_from_location({'currency_short_title':'$'}))
        item['payment_status']='partly_paid'
        self.assertFalse(history_visits([item],'2026-11-17')[0]['paid_in_full'])

    def test_desktop_http_requires_local_nonce_and_blocks_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            app=DesktopApplication(folder,FakeMcp())
            worker=threading.Thread(target=app.httpd.serve_forever,daemon=True);worker.start()
            try:
                def get(path,token=True):
                    request=urllib.request.Request(app.origin+path,headers={'X-App-Token':app.nonce} if token else {})
                    return urllib.request.urlopen(request,timeout=5)
                with get('/') as response:
                    html=response.read().decode();self.assertIn('initializeDesktopReport()',html);self.assertNotIn('Casa House',html)
                    self.assertIn('srcdoc=', html)
                    self.assertIn('Категории клиентов назначаются вручную', html)
                    self.assertNotIn('src="automation-sandbox/index.html?embedded=1"', html)
                with self.assertRaises(urllib.error.HTTPError) as error:get('/api/locations',False)
                self.assertEqual(error.exception.code,403)
                with get('/api/locations') as response:self.assertEqual(json.load(response)['items'][0]['id'],1)
                for path in ('/.env','/data/connection.bin','/scripts/desktop.py'):
                    with self.assertRaises(urllib.error.HTTPError) as error:get(path)
                    self.assertEqual(error.exception.code,404)
                request=urllib.request.Request(app.origin+'/api/desktop/logout',method='POST',data=b'{}',headers={'X-App-Token':app.nonce,'Origin':'https://other.example','Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,403)
            finally:
                app.httpd.shutdown();worker.join(5);app.httpd.server_close()


class MailingMcp(FakeMcp):
    def __init__(self):
        self.details_requested = []

    def pages(self, name, args=None):
        if name == 'appointments_list':
            # Compact lists may show zero even when the full appointment has a
            # final line price. The tracker must obtain authoritative details.
            yield {'id': 71, 'client_id': 2, 'services': [{'id': 11, 'cost': 0}]}
            yield {'id': 72, 'client_id': 999, 'services': [{'id': 11, 'cost': 200}]}
        else:
            yield from super().pages(name, args)

    def call(self, name, args):
        if name == 'api_call_operation' and args['operation_id'] == 'get_appointment':
            self.details_requested.append(args['params']['appointment_id'])
            return {'data': {'id': 71, 'location_id': 1, 'client': {'id': 2}, 'status': 'arrived',
                             'datetime': '2026-11-04T12:00:00+01:00', 'create_date': '2026-11-03T12:00:00+01:00',
                             'paid_in_full': True, 'services': [{'id': 11, 'title': 'Haircut', 'cost': 60},
                                                               {'id': 99, 'title': 'Other', 'cost': 90}]}}
        return super().call(name, args)


class DesktopMailingTests(unittest.TestCase):
    def test_local_campaigns_read_only_mcp_refresh_and_connection_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            mcp = MailingMcp()
            reports = LocalReportData(mcp, folder)
            reports.synchronize(1, 'EUR')
            store = DesktopMailings(reports)
            with patch.object(mailing_campaigns, 'now_utc', return_value=datetime(2026, 11, 1, 9, tzinfo=timezone.utc)):
                campaign = store.create(1, {'name': 'Offer', 'client_ids': [2], 'service_ids': [11], 'window_days': 30, 'cost': 10})
            with patch.object(mailing_campaigns, 'now_utc', return_value=datetime(2026, 11, 18, tzinfo=timezone.utc)):
                sent = store.update(1, 'sent', {'campaign_id': campaign['id'], 'recipient_ids': [2], 'sent_at': '2026-11-01T10:00:00Z'})
                self.assertEqual(sent['result']['buyers'], 1)
                self.assertEqual(sent['result']['revenue'], 60)  # Not the compact zero or the other service.
                refreshed = store.update(1, 'refresh', {'campaign_id': campaign['id']})
            self.assertEqual(refreshed['result']['conversion'], 100)
            self.assertEqual(mcp.details_requested, [71, 71])
            self.assertEqual(store.list(1)[0]['recipient_ids'], [2])
            updated = store.update(1, 'criteria', {'campaign_id': campaign['id'], 'criteria': {
                'version': 1, 'source_category': {'id': 10}, 'source_services': [{'id': 11}],
                'source_minimum_visits': 10, 'target': {'kind': 'service', 'id': 11},
                'target_maximum_visits_exclusive': 1, 'as_of': '2026-11-01'}})
            self.assertEqual(updated['criteria_origin'], 'manual')
            self.assertEqual(updated['result']['revenue'], 60)
            self.assertEqual(mcp.details_requested, [71, 71])  # Metadata causes no appointment reads/writes.
            self.assertFalse((Path(folder) / 'mailing_campaigns_1.json').exists())
            with self.assertRaises(PermissionError):
                store.list(2)
            mcp.connection_key = 'another-owner'
            reports.synchronize(1, 'EUR')
            self.assertEqual(store.list(1), [])

    def test_desktop_http_exposes_campaigns_with_nonce_and_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            app = DesktopApplication(folder, MailingMcp())
            app.reports.synchronize(1, 'EUR')
            worker = threading.Thread(target=app.httpd.serve_forever, daemon=True)
            worker.start()

            def request(path, body=None, origin=None):
                req = urllib.request.Request(app.origin + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-App-Token': app.nonce, 'Origin': origin or app.origin, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.load(response)

            try:
                self.assertTrue(request('/api/desktop/state')['capabilities']['mailings'])
                self.assertFalse(request('/api/desktop/state')['capabilities']['client_category_write'])
                payload = {'location_id': 1, 'name': 'Offer', 'client_ids': [2], 'service_ids': [11], 'window_days': 30, 'cost': 0}
                created = request('/api/upsell/campaigns/create', payload)['item']
                self.assertEqual(request('/api/upsell/campaigns?location_id=1')['items'][0]['id'], created['id'])
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/upsell/campaigns/create', payload, 'https://other.example')
                self.assertEqual(error.exception.code, 403)
            finally:
                app.httpd.shutdown();worker.join(5);app.httpd.server_close()


if __name__=='__main__':unittest.main()
