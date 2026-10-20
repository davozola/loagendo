"""GRAF (graf.cat): agenda de espacios de arte contemporáneo, solo Barcelona (20-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import web_agendas
from src.pipeline import connect

PAGE = """<section><div class="agenda-grid-item"> <a target="_self" href="https://graf.cat/events/event/codi-font-audiovisual-cinema-indigena/"> <div class="entry-date">20.10.2026</div> <h3 class="entry-author"> Santa Mònica </h3> <h4 class="entry-title"> Codi Font Audiovisual: Cinema Indígena </h4> <div class="small"> <div class="entry-time"> <span class="time-start">19</span> – <span class="time_end">20:15</span> h </div> </div> <div class="entry-price small"> Activitat gratuïta </div> </a> <div class="small"> <div class="entry-terms"><a class="underline-1" href="https://graf.cat/events/category/screening/">Screening</a></div> </div> </div>
<div class="agenda-grid-item"> <a target="_self" href="https://graf.cat/events/event/hacerse-rala/"> <div class="entry-date">22.10.2026</div> <h3 class="entry-author"> Galeria H2O </h3> <h4 class="entry-title"> Ho has vist? Ho vaig veure, però ja no hi era. Marian Brea </h4> <div class="small"> <div class="entry-time"> <span class="time-start">18</span> – <span class="time_end">21</span> h </div> </div> <div class="entry-price small"> Activitat gratuïta </div> </a> <div class="small"> <div class="entry-terms"><a class="underline-1" href="https://graf.cat/events/category/inauguracio/">Inauguració</a></div> </div> </div>
<div class="agenda-grid-item"> <a target="_self" href="https://graf.cat/events/event/trobada-open-studio/"> <div class="entry-date">20.10.2026</div> <h3 class="entry-author"> Bòlit, Centre d'Art Contemporani. Girona </h3> <h4 class="entry-title"> Trobada / Open Studio </h4> <h4 class="entry-title"><mark>● <u>Lloc</u>: Centre Cultural La Mercè</mark></h4> <div class="small"> <div class="entry-time"> <span class="time-start">19</span> – <span class="time_end">20:30</span> h </div> </div> <div class="entry-price small"> Activitat gratuïta </div> </a> <div class="small"> <div class="entry-terms"><a class="underline-1" href="https://graf.cat/events/category/trobada/">Trobada</a></div> </div> </div>
<div class="agenda-grid-item"> <a target="_self" href="https://graf.cat/events/event/projecte-extramurs-2026-dora-garcia/"> <div class="entry-date">04.07 – 13.12</div> <h3 class="entry-author"> Museu Tàpies </h3> <h4 class="entry-title"> Projecte Extramurs 2026. Dora García </h4> </a> <div class="small"> <div class="entry-terms"><a href="https://graf.cat/events/category/exposicio/">Exposició</a></div> </div> </div></section>"""
DETAIL = {
    'https://graf.cat/events/event/codi-font-audiovisual-cinema-indigena/': '<div class="entry-venue-address themed"> La Rambla, 7 08002 Barcelona </div><a href="https://www.santamonica.cat/x" target="_blank" class="entry-website underline-1">Pàgina web</a>',
    'https://graf.cat/events/event/hacerse-rala/': '<div class="entry-venue-address themed"> Carrer de Joaquín Costa, 30 08001 Barcelona </div>',
    'https://graf.cat/events/event/trobada-open-studio/': '<div class="entry-venue-address themed"> Plaça de l’Oli, 1 17004 Girona </div>',
    'https://graf.cat/events/event/projecte-extramurs-2026-dora-garcia/': '<div class="entry-venue-address themed"> Carrer d’Aragó, 255 08007 Barcelona </div>',
}


class GrafTests(unittest.TestCase):
    def test_listing_parses_facts_without_texts_or_images(self):
        rows = web_agendas.parse_graf(PAGE, today=dt.date(2026, 10, 19))
        self.assertEqual([r['title'] for r in rows][:2], ['Codi Font Audiovisual: Cinema Indígena', 'Ho has vist? Ho vaig veure, però ja no hi era. Marian Brea'])
        first = rows[0]
        self.assertEqual((first['start'], first['time_text'], first['raw']['item']['time_end'], first['price_text'], first['raw']['item']['graf_category']),
                         ('2026-10-20', '19:00', '20:15', 'Activitat gratuïta', 'Screening'))
        self.assertEqual(rows[2]['venues'][0]['name'], 'Centre Cultural La Mercè')  # «Lloc» manda sobre el nombre del espacio
        self.assertEqual((rows[3]['start'], rows[3]['end'], rows[3]['kind']), ('2026-07-04', '2026-12-13', 'exhibition'))
        self.assertFalse(any(r['raw'].get('image') for r in rows))

    def test_only_barcelona_addresses_are_eligible(self):
        self.assertTrue(web_agendas.in_barcelona('La Rambla, 7 08002 Barcelona'))
        self.assertFalse(web_agendas.in_barcelona("Plaça de l'Oli, 1 17004 Girona"))
        self.assertFalse(web_agendas.in_barcelona('Carrer Major, 1 08172 Sant Cugat del Vallès'))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            web_agendas.SOURCES['web_graf']  # fuente registrada
            calls = []
            def fetcher(url, timeout):
                calls.append(url); return PAGE if url == web_agendas.SOURCES['web_graf']['url'] else DETAIL[url]
            out = web_agendas.sync(conn, 'web_graf', fetcher=fetcher)
            self.assertEqual(out['status'], 'completed')
            rows = {r[0]: (r[1], json.loads(r[2])['item']['graf_address']) for r in conn.execute("SELECT title,eligibility,raw_json FROM source_records WHERE source='web_graf'")}
            self.assertEqual(rows['Trobada / Open Studio'][0], 'exclude')
            self.assertNotEqual(rows['Codi Font Audiovisual: Cinema Indígena'][0], 'exclude')
            # Segunda pasada: la dirección ya conocida no se vuelve a pedir.
            calls.clear(); web_agendas.sync(conn, 'web_graf', fetcher=fetcher)
            self.assertEqual(calls, [web_agendas.SOURCES['web_graf']['url']])
            catalog.invalidate_cache()
            items = {e['title']: e for e in catalog.query_events(conn, date_from='2026-10-19', date_to='2026-10-30', public=True)['items']}
            opening = items['Ho has vist? Ho vaig veure, però ja no hi era. Marian Brea']
            self.assertEqual((opening['public_category'], 'galerias' in opening['channels']), ('arte', True))
            self.assertEqual(items['Codi Font Audiovisual: Cinema Indígena']['public_category'], 'cine')
            self.assertNotIn('Trobada / Open Studio', items)


if __name__ == '__main__':
    unittest.main()
