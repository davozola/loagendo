import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src.pipeline import connect
from src.place_images import fetch_place_images, image_from_page, place_of, places_needing_images

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ff9f0f000401007e9ce8e40000000049454e44ae426082')


class PlaceImageTests(unittest.TestCase):
    def test_place_is_read_from_both_municipal_sources_and_og_image_is_found(self):
        od = {'from_relationships': [{'entity_core_type': 'organization', 'entity_id': 1}, {'entity_core_type': 'place', 'entity_id': 92086011957, 'entity_name': 'Parc de la Guineueta', 'entity_canonical_url': 'https://www.barcelona.cat/ca/la-ciutat/parcs/parc-de-la-guineueta-92086011957'}]}
        self.assertEqual(place_of(od, 'opendatabcn_agenda'), ('92086011957', 'Parc de la Guineueta', 'https://www.barcelona.cat/ca/la-ciutat/parcs/parc-de-la-guineueta-92086011957'))
        self.assertEqual(place_of({'api_item': {'equipment_id': '92086011957', 'institutionname': 'Parc de la Guineueta'}}, 'guiabcn'), ('92086011957', 'Parc de la Guineueta', ''))
        self.assertIsNone(place_of({'api_item': {}}, 'guiabcn')); self.assertIsNone(place_of({}, 'generalitat'))
        self.assertEqual(image_from_page('<meta property="og:image" content="/img/parc.jpg">', 'https://www.barcelona.cat/x'), 'https://www.barcelona.cat/img/parc.jpg')
        self.assertEqual(image_from_page('<img src="/logo.png"><img src="/media/foto.jpg?w=800">', 'https://www.barcelona.cat/'), 'https://www.barcelona.cat/media/foto.jpg?w=800')
        self.assertIsNone(image_from_page('<p>sin imagen</p>', 'https://www.barcelona.cat/'))

    def test_candidate_pages_prefer_guiabcn_and_fall_back_to_the_canonical_page(self):
        from src.place_images import candidate_pages
        self.assertEqual(candidate_pages('92086002380', 'Centre Cívic Cotxeres de Sants', 'https://www.barcelona.cat/ca/la-ciutat/punts-interes/centre-civic-cotxeres-de-sants-92086002380'),
                         ['https://guia.barcelona.cat/ca/detall/centre-civic-cotxeres-de-sants_92086002380.html', 'https://www.barcelona.cat/ca/la-ciutat/punts-interes/centre-civic-cotxeres-de-sants-92086002380'])
        self.assertEqual(candidate_pages('92086011957', 'Parc de la Guineueta', ''), ['https://guia.barcelona.cat/ca/detall/parc-de-la-guineueta_92086011957.html'])

    def test_job_fetches_one_photo_per_venue_and_the_photo_backs_records_without_their_own(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); conn = connect(root / 't.sqlite3'); catalog.initialize(conn)
            rel = [{'entity_core_type': 'place', 'entity_id': 92086000555, 'entity_name': 'Centre Cívic Navas', 'entity_canonical_url': 'https://www.barcelona.cat/ca/la-ciutat/punts-interes/centre-civic-navas-92086000555'}]
            for id, title in (('1', 'Taller de dibuix'), ('2', 'Curs de ioga')):
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', id, title, '2026-10-20', '2026-12-20', 'course', 'review', 'x', '', 'h', json.dumps({'name': title, 'from_relationships': rel, 'addresses': [], 'loagendo': {}})))
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '3', 'Amb foto pròpia', '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', 'h', json.dumps({'name': 'Amb foto pròpia', 'from_relationships': rel, 'addresses': [], 'loagendo': {}})))
            from src import media as media_module
            media_module.register(conn, 'opendatabcn_agenda', '3', 'https://img.test/own.jpg', rights_status='authorized'); conn.commit()
            wanted = places_needing_images(conn, today=__import__('datetime').date(2026, 10, 13))
            self.assertEqual([(p['place_id'], p['records']) for p in wanted], [('92086000555', 2)])
            fetched = []
            def fetcher(url, timeout): fetched.append(url); return url, '<meta property="og:image" content="https://www.barcelona.cat/foto-navas.jpg">'
            def downloader(url, directory, timeout):
                path = Path(directory) / 'places' / 'abc.jpg'; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(PNG); return str(path), 'abc', 'image/jpeg'
            out = fetch_place_images(conn, root / 'media', fetcher=fetcher, downloader=downloader, today=__import__('datetime').date(2026, 10, 13))
            self.assertEqual((out['fetched'], out['failed'], fetched), (1, 0, ['https://guia.barcelona.cat/ca/detall/centre-civic-navas_92086000555.html']))  # the GuiaBCN page comes first
            self.assertEqual(places_needing_images(conn, today=__import__('datetime').date(2026, 10, 13)), [])  # done: not asked again
            catalog.invalidate_cache()
            items = {e['id']: e for e in catalog.query_events(conn, day='2026-10-20', public=True)['items']}
            self.assertEqual((items['1']['media'][0]['url'], items['1']['media'][0]['fallback'], items['1']['media'][0]['alt']), ('/media/place/92086000555', True, 'Imagen del equipamiento: Centre Cívic Navas'))
            self.assertEqual(items['3']['media'][0]['url'], '/media/1')  # a record's own image wins
            self.assertNotIn('imagen de la fuente', catalog.featured_score(items['1'], '2026-10-20')[1])
            detail = catalog.event_detail(conn, 'opendatabcn_agenda', '2'); self.assertTrue(detail['media'][0]['fallback'])
            # a failure is recorded and not retried for a month
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '4', 'Sense pàgina', '2026-10-20', '2026-12-31', 'program', 'review', 'x', '', 'h', json.dumps({'name': 'x', 'from_relationships': [{'entity_core_type': 'place', 'entity_id': 777, 'entity_name': 'Casal', 'entity_canonical_url': 'https://www.barcelona.cat/ca/casal-777'}], 'addresses': [], 'loagendo': {}}))); conn.commit()
            def failing(url, timeout): raise OSError('timeout')
            out = fetch_place_images(conn, root / 'media', fetcher=failing, downloader=downloader, today=__import__('datetime').date(2026, 10, 13))
            self.assertEqual((out['fetched'], out['failed']), (0, 1))
            self.assertEqual(places_needing_images(conn, today=__import__('datetime').date(2026, 10, 13)), [])
            self.assertEqual([p['place_id'] for p in places_needing_images(conn, today=__import__('datetime').date(2026, 11, 20))], ['777'])
            catalog.invalidate_cache(); conn.close()


if __name__ == '__main__':
    unittest.main()
