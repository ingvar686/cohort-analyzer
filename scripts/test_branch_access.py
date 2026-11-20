"""Regression checks: no demo fallback, no cached data without current access."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import branch_access
import server
import sync_from_altegio


class ConnectionTests(unittest.TestCase):
    def test_location_list_never_uses_public_directory(self):
        api = branch_access.AltegioClient.__new__(branch_access.AltegioClient)
        api.request = Mock(side_effect=[{'data': [{'id': i} for i in range(100)]}, {'data': [{'id': 101}]}])
        self.assertEqual(len(api.locations()), 101)
        self.assertEqual([call.kwargs['params']['page'] for call in api.request.call_args_list], [1, 2])
        self.assertTrue(all(call.kwargs['params']['my'] == 1 for call in api.request.call_args_list))

    def test_credentials_required_and_identity_changes(self):
        with patch.object(branch_access, 'get_env', return_value=''):
            with self.assertRaises(PermissionError):
                branch_access.connection_id()
        values = {'ALTEGIO_PARTNER_TOKEN': 'partner', 'ALTEGIO_USER_TOKEN': 'a'}
        with patch.object(branch_access, 'get_env', side_effect=lambda key: values[key]):
            first = branch_access.connection_id()
            values['ALTEGIO_USER_TOKEN'] = 'b'
            self.assertNotEqual(first, branch_access.connection_id())

    def test_only_current_account_locations(self):
        with patch.object(branch_access, 'accessible_locations', return_value=[{'id': 2}]):
            self.assertEqual(branch_access.require_location_access('2'), 2)
            with self.assertRaises(PermissionError):
                branch_access.require_location_access(1)

    def test_starter_data_is_empty(self):
        data = sync_from_altegio.load_seed()
        self.assertFalse(data['clients'])
        self.assertFalse(data['location'])
        html = (server.ROOT / 'dashboards/index.html').read_text(encoding='utf-8')
        self.assertNotIn('Casa House', html)
        self.assertNotIn('BBF26 Emma Carter', html)
        self.assertIn('id="reportContent" hidden', html)

    def test_cache_requires_access_and_matching_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'portal_1.json'
            path.write_text(json.dumps({'connection_id': 'old-account', 'location': {'id': 1}, 'clients': [{'name': 'old private client'}]}))
            httpd = server.ReportsHTTPServer(('127.0.0.1', 0), server.Handler)
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{httpd.server_port}'
            fresh = {'connection_id': 'current-account', 'location': {'id': 1}, 'clients': []}
            try:
                with patch.object(server, 'portal_path_for', return_value=path), patch.object(server, 'connection_id', return_value='current-account'), patch.object(server, 'require_location_access', return_value=1), patch.object(server, 'sync_location', return_value=fresh) as sync:
                    with urllib.request.urlopen(url + '/api/data?location_id=1') as response:
                        self.assertEqual(json.load(response), fresh)
                    sync.assert_called_once_with(1)
                with patch.object(server, 'require_location_access', side_effect=PermissionError('No access')), patch.object(server, 'sync_location') as sync:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(url + '/api/data?location_id=1')
                    self.assertEqual(error.exception.code, 403)
                    sync.assert_not_called()
                with patch.object(server, 'accessible_locations', side_effect=PermissionError('Not connected')):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(url + '/api/locations')
                    self.assertEqual(error.exception.code, 401)
                for target in ('/.env', '/data/portal_1.json', '/scripts/server.py'):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(url + target)
                    self.assertEqual(error.exception.code, 404)
            finally:
                httpd.shutdown()
                worker.join(timeout=5)
                httpd.server_close()


if __name__ == '__main__':
    unittest.main()
