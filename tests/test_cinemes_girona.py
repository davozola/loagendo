"""Cinemes Girona: de noche la portada no trae sesiones; las fichas de película sí (23-10-2026)."""
import json
import unittest
from pathlib import Path

from mvp import catalog
from src.pipeline import connect
from src.sync import initialize as init_sync
from src.venue_feeds import sync_venue

VENUE = next(v for v in json.loads((Path(__file__).parent.parent / 'config' / 'venues.json').read_text(encoding='utf-8'))['venues'] if v['slug'] == 'cinemes_girona')
HOME = ('<html><body><a href="/cartellera">Cartellera</a><a href="/noticies">Notícies</a><a href="/blue-heron">Blue Heron</a>'
        '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"MovieTheater","name":"Cinemes Girona","event":[]}]}</script></body></html>')
FILM = ('<html><body><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"MovieTheater","name":"Cinemes Girona",'
        '"address":{"@type":"PostalAddress","streetAddress":"Carrer de Girona, 175","addressLocality":"Barcelona"},'
        '"event":[{"@type":"ScreeningEvent","name":"Blue Heron (VOSE)","startDate":"2099-10-24T18:40:00+02:00","location":{"@type":"MovieTheater","name":"Cinemes Girona"}},'
        '{"@type":"ScreeningEvent","name":"Blue Heron (VOSE)","startDate":"2099-10-25T20:30:00+02:00","location":{"@type":"MovieTheater","name":"Cinemes Girona"}}]}]}</script></body></html>')


class CinemesGironaTest(unittest.TestCase):
    def test_sigue_las_fichas_de_pelicula_aunque_la_portada_este_vacia(self):
        conn = connect(':memory:'); init_sync(conn); catalog.initialize(conn)
        visited = []
        def fetcher(url, timeout):
            visited.append(url)
            return (200, url, FILM if url.rstrip('/').endswith('blue-heron') else HOME)
        res = sync_venue(conn, VENUE, fetcher=fetcher)
        self.assertEqual(res['status'], 'completed', res)
        self.assertNotIn('https://www.cinemesgirona.cat/noticies', visited)
        self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_cinemes_girona'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
