from pathlib import Path
import json
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import gateway
from workload import Configuration


class GatewayIsolation(unittest.TestCase):
    def test_proxy_observation_records_categories_without_client_addresses(self):
        with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[2]), *sys.path]), \
                patch.dict(os.environ, {'COUCHSIDE_TRUSTED_PROXY_IPS': '172.16.0.1'}):
            scope = {'client': ('172.16.0.1', 90), 'headers': [
                (b'x-forwarded-for', b'8.8.8.8'), (b'cookie', b'private-session')]}
            observed = gateway.proxy_shape(scope)
        self.assertEqual(observed['forwarded'], ['public'])
        self.assertEqual(observed['selected'], 'public')
        self.assertFalse(observed['selected_equals_peer'])
        text = json.dumps(observed)
        for secret in ('8.8.8.8', '172.16.0.1', 'private-session'):
            self.assertNotIn(secret, text)

    def test_unsigned_or_wrong_signatures_never_change_real_client_identity(self):
        scope = {'client': ('198.51.100.9', 90), 'headers': [(b'x-couchside-load-identity', b'one')]}
        self.assertIs(gateway.signed_scope(scope, 'a'*64), scope)
        scope['headers'].append((b'x-couchside-load-signature', b'bad'))
        self.assertIs(gateway.signed_scope(scope, 'a'*64), scope)

    def test_signed_identity_is_stable_and_ignores_supplied_forwarded_addresses(self):
        key, identity = 'a'*64, 'user-123'
        scope = {'client': ('198.51.100.9',90), 'headers': [(b'x-forwarded-for', b'evil'),
            (b'x-couchside-load-identity', identity.encode()),
            (b'x-couchside-load-signature', gateway.signature(key,identity).encode())]}
        signed = gateway.signed_scope(scope,key)
        self.assertEqual(signed['client'], ('127.0.0.1',0))
        self.assertEqual(dict(signed['headers'])[b'x-forwarded-for'], gateway.forwarded(identity).encode())
        self.assertNotEqual(gateway.forwarded(identity), gateway.forwarded('other'))

    def test_remote_fixture_requires_explicit_isolation_and_exact_audience(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'private.json'
            path.write_text(json.dumps({'key':'a'*64,'origin':'https://capacity.example'}))
            configuration = Configuration(synthetic_identities=True,gateway_key_path=str(path))
            configuration.validate('https://capacity.example',isolated=True)
            with self.assertRaises(ValueError):
                configuration.validate('https://capacity.example',isolated=False)
            with self.assertRaises(ValueError):
                configuration.validate('https://production.example',isolated=True)


if __name__ == '__main__':
    unittest.main()
