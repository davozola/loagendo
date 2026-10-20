"""GRAF (graf.cat): feed iCal + ficha de cada acto; solo Barcelona (20-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import web_agendas
from src.pipeline import connect

FEED = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//GRAF//NONSGML Events//EN\r\n"
        # sesión con hora (UTC → Madrid), sin LOCATION/GEO
        "BEGIN:VEVENT\r\nUID:X-EO-60244-1@x\r\nDTSTART:20261020T170000Z\r\nDTEND:20261020T181500Z\r\nSUMMARY: Codi Font Audiovisual: Cinema Indígena\r\n"
        "CATEGORIES:Screening\r\nORGANIZER;CN=\"Santa Mònica\":MAILTO:a@b.c\r\nURL;VALUE=URI:https://graf.cat/events/event/codi-font-audiovisual-cinema-indi\r\n gena/\r\n"
        "ATTACH;FMTTYPE=image/jpeg:https://graf.cat/wp-content/uploads/2026/09/cine.jpg\r\nEND:VEVENT\r\n"
        # inauguración en galería, con GEO
        "BEGIN:VEVENT\r\nUID:X-EO-61000-1@x\r\nDTSTART:20261022T160000Z\r\nDTEND:20261022T190000Z\r\nSUMMARY: Ho has vist? Marian Brea\r\nCATEGORIES:Inauguració\r\n"
        "LOCATION:Galeria H2O\r\nGEO:41.403;2.157\r\nORGANIZER;CN=\"Galeria H2O\":MAILTO:a@b.c\r\nURL;VALUE=URI:https://graf.cat/events/event/marian-brea-opening/\r\nEND:VEVENT\r\n"
        # exposición de día completo (DTEND exclusivo)
        "BEGIN:VEVENT\r\nUID:X-EO-57846-1@x\r\nDTSTART;VALUE=DATE:20260704\r\nDTEND;VALUE=DATE:20261214\r\nSUMMARY: Projecte Extramurs 2026. Dora García\r\nCATEGORIES:Exposició\r\n"
        "LOCATION:Museu Tàpies\r\nGEO:41.391606;2.163713\r\nORGANIZER;CN=\"Museu Tàpies\":MAILTO:a@b.c\r\nURL;VALUE=URI:https://graf.cat/events/event/extramurs/\r\n"
        "ATTACH;FMTTYPE=image/jpeg:https://graf.cat/wp-content/uploads/2026/06/dora.jpg\r\nEND:VEVENT\r\n"
        # fuera de Barcelona
        "BEGIN:VEVENT\r\nUID:X-EO-1-1@x\r\nDTSTART:20261020T170000Z\r\nDTEND:20261020T183000Z\r\nSUMMARY: Trobada / Open Studio\r\nCATEGORIES:Trobada\r\n"
        "ORGANIZER;CN=\"Bòlit\":MAILTO:a@b.c\r\nURL;VALUE=URI:https://graf.cat/events/event/trobada-open-studio/\r\nEND:VEVENT\r\n"
        # histórico: no entra
        "BEGIN:VEVENT\r\nUID:X-EO-2-1@x\r\nDTSTART;VALUE=DATE:20150118\r\nDTEND;VALUE=DATE:20150119\r\nSUMMARY: The Sign is the Circle\r\nCATEGORIES:Exposició\r\n"
        "ORGANIZER;CN=\"ProjecteSD\":MAILTO:a@b.c\r\nURL;VALUE=URI:https://graf.cat/events/event/old/\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
DETAIL = {
    'https://graf.cat/events/event/codi-font-audiovisual-cinema-indigena/':
        '<meta property="og:image" content="https://graf.cat/og.jpg"><div class="entry-venue-address themed"> La Rambla, 7 08002 Barcelona </div>'
        '<div class="entry-price"> Preu: Activitat gratuïta </div><a href="https://www.santamonica.cat/x" target="_blank" class="entry-website underline-1">Pàgina web</a>'
        '<div class="detail-section-main"> <p>DIMARTS DE VÍDEO amb Maria Ignacia Ibarra</p> <p><i>Codi font audiovisual</i>, projecció comentada.</p> </div> <div class="detail-section-image-col"></div>',
    'https://graf.cat/events/event/marian-brea-opening/': '<div class="entry-venue-address themed"> Carrer de Joaquín Costa, 30 08001 Barcelona </div><div class="detail-section-main"><p>Inauguració de la mostra.</p></div>',
    'https://graf.cat/events/event/extramurs/': '<div class="entry-venue-address themed"> Carrer d’Aragó, 255 08007 Barcelona </div><div class="detail-section-main"><p>Projecte a l’espai públic.</p></div>',
    'https://graf.cat/events/event/trobada-open-studio/': '<div class="entry-venue-address themed"> Plaça de l’Oli, 1 17004 Girona </div>',
}


class GrafTests(unittest.TestCase):
    def test_ical_feed_gives_sessions_times_ranges_and_images(self):
        rows = {r['title']: r for r in web_agendas.parse_graf(FEED, today=dt.date(2026, 10, 19))}
        self.assertNotIn('The Sign is the Circle', rows)  # histórico
        cine = rows['Codi Font Audiovisual: Cinema Indígena']
        self.assertEqual((cine['start'], cine['time_text'], cine['raw']['item']['time_end'], cine['raw']['image']),
                         ('2026-10-20', '19:00', '20:15', 'https://graf.cat/wp-content/uploads/2026/09/cine.jpg'))
        self.assertEqual(cine['url'], 'https://graf.cat/events/event/codi-font-audiovisual-cinema-indigena/')  # línea plegada
        self.assertEqual(rows['Ho has vist? Marian Brea']['venues'][0]['coords'], (41.403, 2.157))
        expo = rows['Projecte Extramurs 2026. Dora García']
        self.assertEqual((expo['start'], expo['end'], expo['kind'], expo['time_text']), ('2026-07-04', '2026-12-13', 'exhibition', ''))

    def test_detail_page_gives_address_text_price_and_web(self):
        d = web_agendas.graf_detail(DETAIL['https://graf.cat/events/event/codi-font-audiovisual-cinema-indigena/'])
        self.assertEqual((d['address'], d['price'], d['web'], d['image']), ('La Rambla, 7 08002 Barcelona', 'Activitat gratuïta', 'https://www.santamonica.cat/x', 'https://graf.cat/og.jpg'))
        self.assertEqual(d['description'], 'DIMARTS DE VÍDEO amb Maria Ignacia Ibarra\n\nCodi font audiovisual , projecció comentada.')

    def test_sync_keeps_only_barcelona_with_text_and_image_and_reuses_details(self):
        self.assertTrue(web_agendas.in_barcelona('La Rambla, 7 08002 Barcelona'))
        self.assertFalse(web_agendas.in_barcelona('Carrer Major, 1 08172 Sant Cugat del Vallès'))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            calls = []
            def fetcher(url, timeout):
                calls.append(url); return FEED if url == web_agendas.SOURCES['web_graf']['url'] else DETAIL[url]
            from unittest import mock
            fixed = lambda page: web_agendas.parse_graf(page, today=dt.date(2026, 10, 19))
            patch = mock.patch.dict(web_agendas.PARSERS, {'web_graf': fixed}); patch.start(); self.addCleanup(patch.stop)
            out = web_agendas.sync(conn, 'web_graf', fetcher=fetcher)
            self.assertEqual(out['status'], 'completed')
            rows = {r[0]: r[1] for r in conn.execute("SELECT title,eligibility FROM source_records WHERE source='web_graf'")}
            self.assertEqual(rows.get('Trobada / Open Studio'), 'exclude')
            calls.clear(); web_agendas.sync(conn, 'web_graf', fetcher=fetcher)
            self.assertEqual(calls, [web_agendas.SOURCES['web_graf']['url']])  # fichas ya leídas: no se piden otra vez
            assets = conn.execute("SELECT rights_status, credit FROM media_assets WHERE source='web_graf' ORDER BY credit").fetchall()
            self.assertIn(('authorized', 'Museu Tàpies · vía GRAF'), assets)
            catalog.invalidate_cache()
            key = conn.execute("SELECT id FROM source_records WHERE source='web_graf' AND title LIKE 'Projecte Extramurs%'").fetchone()[0]
            detail = catalog.event_detail(conn, 'web_graf', key)
            self.assertEqual((detail['description'], detail['public_category'], 'galerias' in detail['channels']), ('Projecte a l’espai públic.', 'arte', True))
            self.assertTrue(detail['media'])


if __name__ == '__main__':
    unittest.main()
