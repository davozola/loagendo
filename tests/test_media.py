import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import media
from src.pipeline import connect


class MediaRightsPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / 'registry.json'
        self.registry.write_text(json.dumps({
            'opendatabcn_agenda': {'image_reuse_confirmed': True, 'image_reuse_basis': 'decisión editorial de prueba'},
            'web_cccb': {'image_reuse_confirmed': False},
        }), encoding='utf-8')
        self.conn = connect(self.root / 't.sqlite3'); catalog.initialize(self.conn)
        for source, id in (('opendatabcn_agenda', '1'), ('web_cccb', '2')):
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, id, 'Acte', '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', 'h', '{}'))
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def test_policy_comes_from_registry_and_backfill_is_logged_and_idempotent(self):
        self.assertEqual(media.source_rights_policy('opendatabcn_agenda', self.registry), 'authorized')
        self.assertEqual(media.source_rights_policy('web_cccb', self.registry), 'unknown')
        self.assertEqual(media.source_rights_policy('missing', self.registry), 'unknown')
        media.register(self.conn, 'opendatabcn_agenda', '1', 'https://img.test/a.jpg', rights_status='unknown')
        media.register(self.conn, 'web_cccb', '2', 'https://img.test/b.jpg', rights_status='unknown')
        self.conn.commit()
        first = media.apply_rights_policy(self.conn, self.registry); second = media.apply_rights_policy(self.conn, self.registry)
        self.assertEqual((first, second), ({'opendatabcn_agenda': 1}, {}))
        self.assertEqual(dict(self.conn.execute('SELECT source,rights_status FROM media_assets')), {'opendatabcn_agenda': 'authorized', 'web_cccb': 'unknown'})
        self.assertEqual(self.conn.execute('SELECT source,assets,basis FROM media_rights_log').fetchone(), ('opendatabcn_agenda', 1, 'decisión editorial de prueba'))

    def test_authorized_assets_are_listed_before_download_and_fetched_on_first_use(self):
        media.register(self.conn, 'opendatabcn_agenda', '1', 'https://img.test/a.jpg', rights_status='authorized')
        media.register(self.conn, 'web_cccb', '2', 'https://img.test/b.jpg', rights_status='unknown')
        self.conn.commit(); catalog.invalidate_cache()
        listing = {e['key']: e for e in catalog.query_events(self.conn, day='2026-10-20')['items']}
        self.assertEqual(len(listing['opendatabcn_agenda:1']['media']), 1)
        self.assertEqual(listing['web_cccb:2']['media'], [])  # unknown rights and not on disk: not served
        asset_id = self.conn.execute('SELECT asset_id FROM media_assets WHERE source=?', ('opendatabcn_agenda',)).fetchone()[0]
        calls = []
        def fake_download(conn, aid, directory):
            calls.append(aid); path = Path(directory) / 'a.jpg'; path.parent.mkdir(exist_ok=True); path.write_bytes(b'x')
            conn.execute('UPDATE media_assets SET local_path=?,content_type=? WHERE asset_id=?', (str(path), 'image/jpeg', aid)); conn.commit(); return path
        original = media._download; media._download = fake_download
        try:
            path, ctype = media.ensure_local(self.conn, asset_id, self.root / 'media')
            again = media.ensure_local(self.conn, asset_id, self.root / 'media')
        finally:
            media._download = original
        self.assertEqual((ctype, calls), ('image/jpeg', [asset_id])); self.assertEqual(path, again[0])
        other = self.conn.execute('SELECT asset_id FROM media_assets WHERE source=?', ('web_cccb',)).fetchone()[0]
        self.assertEqual(media.ensure_local(self.conn, other, self.root / 'media'), (None, None))

    def test_failed_fetch_is_recorded_and_not_retried_on_every_request(self):
        media.register(self.conn, 'opendatabcn_agenda', '1', 'https://img.test/a.jpg', rights_status='authorized'); self.conn.commit()
        asset_id = self.conn.execute('SELECT asset_id FROM media_assets').fetchone()[0]
        attempts = []
        def failing(conn, aid, directory): attempts.append(aid); raise ValueError('boom')
        original = media._download; media._download = failing
        try:
            self.assertEqual(media.ensure_local(self.conn, asset_id, self.root / 'media'), (None, None))
            self.assertEqual(media.ensure_local(self.conn, asset_id, self.root / 'media'), (None, None))
        finally:
            media._download = original
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.conn.execute('SELECT download_error FROM media_assets').fetchone()[0], 'boom')


if __name__ == '__main__':
    unittest.main()
