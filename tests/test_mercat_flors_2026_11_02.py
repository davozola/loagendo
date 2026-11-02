"""Mercat de les Flors (2-11-2026): sesiones desde el JSON de «Añadir al calendario» de cada ficha del sitemap."""
import datetime as dt
import json
import sqlite3
import unittest

from src import venue_feeds as vf

VENUE = next(v for v in json.load(open('config/venues.json', encoding='utf-8'))['venues'] if v['slug'] == 'mercat_flors')
INDEX = ('<sitemapindex><sitemap><loc>https://mercatflors.cat/espectacle-sitemap.xml</loc><lastmod>2026-10-30T10:47:09+00:00</lastmod></sitemap>'
         '<sitemap><loc>https://mercatflors.cat/espectacle-sitemap2.xml</loc><lastmod>2023-01-24T08:29:29+00:00</lastmod></sitemap>'
         '<sitemap><loc>https://mercatflors.cat/post-sitemap.xml</loc><lastmod>2026-10-30T10:47:09+00:00</lastmod></sitemap></sitemapindex>')
MAP = ('<urlset><url><loc>https://mercatflors.cat/es/espectacle/rave-familiar-26-27/</loc><lastmod>2026-10-21T09:47:02+00:00</lastmod></url>'
       '<url><loc>https://mercatflors.cat/espectacle/rave-familiar-26-27/</loc><lastmod>2026-10-21T09:40:16+00:00</lastmod></url>'
       '<url><loc>https://mercatflors.cat/es/espectacle/vieja/</loc><lastmod>2022-12-01T13:29:28+00:00</lastmod></url></urlset>')
PAGE = ('<meta property="og:image" content="https://mercatflors.cat/wp-content/uploads/2025/06/RAVE_380x230.webp">'
        '<meta property="og:description" content="Edad recomendada: de 2 a 7 años.">'
        '<div class="atcb" style="display:none;">\r\n\t{"name":"RAVE FAMILIAR - Dory S\\u00e1nchez","location":"Sala MAC","startDate":"2026-11-07","endDate":"2026-11-07","startTime":"10:30","endTime":"12:30"}\t</div>'
        '<div class="atcb" style="display:none;">\r\n\t{"name":"RAVE FAMILIAR - Dory S\\u00e1nchez","location":"Sala MAC","dates":[{"startDate":"2026-11-07","endDate":"2026-11-07","startTime":"10:30","endTime":"12:30"},'
        '{"startDate":"2026-11-07","endDate":"2026-11-07","startTime":"17:00","endTime":"19:00"}]}\t</div>'
        '<ul class="blk-full-btns"><li><div class="insc-escol insc-gris"><div class="inscri-cnt"><h4></h4><p><strong>INFORMACIÓN PRÁCTICA Y ACCESIBILIDAD</strong></p>'
        '<p><strong>Espacio:</strong> función sin butacas.<br /> <strong>Luz:</strong> luz intermitente.</p></div></div></li>'
        '<li><a class="blk-btn" style="margin-top: 1em;" href="https://es.patronbase.com/_MercatFlorsEs/Productions/2382/Performances" target="_blank">COMPRAR ENTRADAS</a></li></ul>'
        '<li class=""><a href="https://es.patronbase.com/x?perf_id=1"> <h4><span>sábado, 7 noviembre</span> (10:30h)</h4> </a> <p class="exhaurides-alt">Entrades exhaurides</p></li>'
        '<li class=""><a href="https://es.patronbase.com/x?perf_id=2"> <h4><span>sábado, 7 noviembre</span> (17:00h)</h4> </a> <p class="exhaurides-alt">Entrades exhaurides</p></li>'
        '<li><div class="esp-det-lft"><h3>Tarifa</h3></div><div class="esp-det-rgt"><p class="desk-para">6 €</p></div></li>'
        '<li><div class="esp-det-lft"><h3>Espacio</h3></div><div class="esp-det-rgt"><p class="desk-para"> <a href="/sala-mac/"> Sala MAC </a> </p></div></li>'
        '<div class="espect-rgt"><div class="espect-cnt-area"><div class="sino-sec" id="sinopsis-sec"><p><strong>Edad recomendada: de 2 a 7 años</strong></p>'
        '<p>Las artistas han creado un espacio pensado para que podamos bailar juntas adultos/as y niños/as.</p></div><div id="descomptes" class="popup"></div>')
PAGES = {'https://mercatflors.cat/sitemap_index.xml': INDEX, 'https://mercatflors.cat/espectacle-sitemap.xml': MAP,
         'https://mercatflors.cat/es/espectacle/rave-familiar-26-27/': PAGE}
SEEN = []


def fetcher(url, timeout):
    SEEN.append(url)
    return (200, url, PAGES[url]) if url in PAGES else (404, url, '')


class MercatFlors(unittest.TestCase):
    def test_sesiones(self):
        SEEN.clear()
        nodes, fetched = vf.sitemap_calendar_nodes(VENUE, fetcher, 5, today=dt.date(2026, 11, 2))
        self.assertNotIn('https://mercatflors.cat/espectacle-sitemap2.xml', SEEN)   # mapa viejo: no se pide
        self.assertNotIn('https://mercatflors.cat/espectacle/rave-familiar-26-27/', SEEN)   # otra lengua
        starts = [n['startDate'] for _, n in nodes]
        self.assertEqual(starts, ['2026-11-07T10:30:00']); self.assertEqual(nodes[0][1]['x_sessions'], ['10:30', '17:00'])
        node = nodes[0][1]
        self.assertEqual(node['name'], 'RAVE FAMILIAR - Dory Sánchez'); self.assertTrue(node['image'].endswith('RAVE_380x230.webp'))
        self.assertIn('Edad recomendada: de 2 a 7 años', node['description']); self.assertIn('INFORMACIÓN PRÁCTICA Y ACCESIBILIDAD', node['description'])
        self.assertIn('Espacio: función sin butacas.', node['description']); self.assertEqual(node['x_room'], 'Sala MAC')
        self.assertEqual(node['offers']['price'], '6 €'); self.assertTrue(node['offers']['url'].endswith('/2382/Performances'))
        self.assertEqual(node['offers']['availability'], 'https://schema.org/SoldOut')
        rec = vf.record_from_jsonld(VENUE, node, nodes[0][0])
        self.assertEqual(rec['price_text'], '6 €')
        self.assertEqual(rec['start'], '2026-11-07'); self.assertEqual(rec['title'][:12], 'RAVE FAMILIA')

    def test_sync(self):
        import tempfile
        from pathlib import Path
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            r = vf.sync_venue(conn, VENUE, fetcher, 5)
            self.assertEqual(r['status'], 'completed', r); self.assertEqual(r['rows_received'], 1)
            (raw,) = conn.execute("SELECT raw_json FROM source_records WHERE source='venue_mercat_flors'").fetchone()
            self.assertIn('10:30 · 17:00', raw)
            conn.close()


if __name__ == '__main__':
    unittest.main()
