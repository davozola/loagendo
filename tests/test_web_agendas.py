import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.pipeline import connect
from src.web_agendas import parse_cccb, parse_conciertos_club, parse_macba, parse_teatre_lliure, sync
from src.guia_detail import MetaParser, detail_facts, enrich_sources, relevant_links


MACBA = '''<div class="w-100 macba-fitxa activitat-card"><a href="https://www.macba.cat/es/actividades/demo/" class="text-decoration-none" aria-label="Visita demo"><img src="https://img.macba.cat/demo.jpg"></a><a href="https://calendar.google.com/calendar/render?action=TEMPLATE&amp;text=Visita+demo&amp;dates=20261012T180000/20261012T190000&amp;location=MACBA"></a>'''
CCCB = '''<h2>octubre 2026</h2><div class="mp-component mp-component-agenda-card"><span class="agenda-card-date-num">13</span><li class="agenda-card-item"><a href="https://www.cccb.org/es/w/demo" title="Demo CCCB"><p class="agenda-card-title">Demo CCCB</p><span class="agenda-card-date-time">18:30</span></a></li>'''
LLIURE = '''<li class=" filter-show-1"><h3><a href="/es/demo" title="Demo Lliure">Demo</a></h3><dl><dt>##general.period##:</dt><dd class="outcome">01/10 — 25/10/26</dd><dt>##general.room##:</dt><dd class="outcome">GRÀCIA</dd></dl></li>'''
CONCERTS = '''<div itemscope itemprop="item" itemtype="http://schema.org/MusicEvent"><div class="time">L12/10/26<br />21:00</div><meta itemprop="name" content="Demo Band" /><meta itemprop="url" content="https://conciertos.club/barcelona/conciertos/demo" /><meta itemprop="image" content="https://images.example/demo.jpg" /><div itemprop="location"><meta itemprop="name" content="Sala Demo" /><div itemprop="address"><meta itemprop="addressLocality" content="Barcelona, Barcelona" /></div></div><meta itemprop="startDate" content="2026-09-01T21:00" /><meta itemprop="endDate" content="2026-10-12T22:30" /></div><div itemscope itemprop="item" itemtype="http://schema.org/MusicEvent"><div class="time">L12/10/26<br />21:00</div><meta itemprop="name" content="Fuera" /><meta itemprop="url" content="https://conciertos.club/barcelona/conciertos/fuera" /><div itemprop="location"><meta itemprop="name" content="Otra Sala" /><div itemprop="address"><meta itemprop="addressLocality" content="Badalona, Barcelona" /></div></div><meta itemprop="startDate" content="2026-10-12T21:00" /></div>'''


class WebAgendaTests(unittest.TestCase):
    def test_parsers_keep_source_url_dates_and_schedule(self):
        macba=parse_macba(MACBA); cccb=parse_cccb(CCCB)
        self.assertEqual((macba[0]['start'],macba[0]['time_text'],macba[0]['url']),('2026-10-12','', 'https://www.macba.cat/es/actividades/demo/'))
        self.assertEqual((cccb[0]['start'],cccb[0]['time_text']),('2026-10-13','18:30'))
        lliure=parse_teatre_lliure(LLIURE)
        self.assertEqual((lliure[0]['start'],lliure[0]['end'],lliure[0]['venues'][0]['name']),('2026-10-01','2026-10-25','Teatre Lliure - Sala Lliure de Gràcia'))

    def test_web_sync_is_idempotent_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as folder:
            conn=connect(Path(folder)/'test.sqlite3')
            first=sync(conn,'web_macba',fetcher=lambda *_:MACBA)
            second=sync(conn,'web_macba',fetcher=lambda *_:MACBA)
            self.assertEqual((first['rows_mutated'],second['rows_mutated']),(1,0))
            self.assertEqual(conn.execute("SELECT count(*) FROM source_records WHERE source='web_macba'").fetchone()[0],1)
            conn.close()

    def test_concert_discovery_keeps_city_sessions_and_preview_reference(self):
        records=parse_conciertos_club(CONCERTS)
        self.assertEqual(records[0]['raw']['image'],'https://images.example/demo.jpg')
        self.assertEqual(len(records),1)
        self.assertEqual((records[0]['title'],records[0]['time_text'],records[0]['evidence_level']),('Demo Band','21:00','third_party_listing_unverified'))
        with tempfile.TemporaryDirectory() as folder:
            conn=connect(Path(folder)/'test.sqlite3')
            sync(conn,'web_conciertos_club',fetcher=lambda *_:CONCERTS)
            self.assertEqual(conn.execute("SELECT local_date,local_time FROM candidate_occurrences WHERE source='web_conciertos_club'").fetchone(),('2026-10-12','21:00'))
            self.assertEqual(conn.execute("SELECT original_url FROM media_assets WHERE source='web_conciertos_club'").fetchone()[0],'https://images.example/demo.jpg')
            conn.close()

    def test_detail_enrichment_archives_description_links_and_image_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            conn=connect(Path(folder)/'test.sqlite3')
            sync(conn,'web_macba',fetcher=lambda *_:MACBA)
            page='''<meta property="og:description" content="Una descripción completa de la actividad."><meta property="og:image" content="/photo.jpg"><img src="/assets/images/brand/banner/logo-ajbcn.svg" alt="Logo Ajuntament de Barcelona"><a href="/tickets">Entradas</a><div id="horari"><table><tr><td>a les 19.00 h</td></tr></table></div>'''
            result=enrich_sources(conn,10,sources=('web_macba',),fetcher=lambda *_:page)
            self.assertEqual((result['enriched'],result['media_references']),(1,1))
            self.assertEqual(conn.execute("SELECT description FROM source_enrichments WHERE source='web_macba'").fetchone()[0],'Una descripción completa de la actividad.')
            self.assertEqual(conn.execute("SELECT schedule_time FROM source_enrichments WHERE source='web_macba'").fetchone()[0],'19:00')
            urls={r[0] for r in conn.execute("SELECT original_url FROM media_assets WHERE source='web_macba'")}
            self.assertIn('https://www.macba.cat/photo.jpg',urls)
            self.assertNotIn('https://www.macba.cat/assets/images/brand/banner/logo-ajbcn.svg',urls)
            conn.close()

    def test_guia_metadata_description_uses_substantive_body_and_skips_navigation(self):
        parser=MetaParser()
        parser.feed('<meta name="description" content="Quan: 15/10/2026 - On: Centre"><p>Per districte Selecciona el districte Ciutat Vella Eixample i altres opcions.</p><div class="cos"><p>Una explicació completa i útil de l’activitat cultural prevista.</p></div>')
        self.assertEqual(parser.description,'Una explicació completa i útil de l’activitat cultural prevista.')
        links=relevant_links('https://guia.barcelona.cat/ca/detall/demo.html',['/ca','#horari','https://tickets.example/entrada','/ca/detall/demo.html'])
        self.assertEqual(links,['https://tickets.example/entrada'])

    def test_detail_facts_preserve_schedule_price_registration_venue_and_organizer(self):
        page='''<div id="horari"><table><tr><td class="content-info"><div>Dissabte</div></td><td class="content-info"><div>de 09.30 h a 17.30 h</div></td><td class="content-info"><div>Entrada Gratuïta</div></td><td class="content-info"><p>Cal inscripció prèvia</p></td></tr></table><dt>Se celebra a: </dt><dd><a>Sant Pau Recinte Modernista</a>.</dd><dt>Organitzat per: </dt><dd><a>Fundació Villavecchia</a>.</dd><dt>Adreça:</dt><dd>Carrer de Sant Antoni Maria Claret, 167</dd><script>loadmapdetall(41.412416,2.175760,'')</script>'''
        facts=detail_facts(page)
        self.assertEqual((facts['schedule_hours'],facts['price_text'],facts['venue'],facts['organizer']),('de 09.30 h a 17.30 h','Entrada Gratuïta','Sant Pau Recinte Modernista','Fundació Villavecchia'))
        self.assertTrue(facts['registration_required'])
        self.assertEqual(facts['coordinates'],{'lat':41.412416,'lon':2.17576})


if __name__ == '__main__': unittest.main()


CIVIC_ITEM = '''<li class="views-row"><div class="views-field views-field-field-imatge"><div class="field-content"><div class="tematica-129 {state}"><img typeof="foaf:Image" src="https://ajuntament.barcelona.cat/centrescivics/sites/default/files/x{n}.jpg" alt=""></div></div></div><div class="views-field views-field-title-field"><div class="field-content"><a href="/centrescivics/ca/activitat/acte-{n}">Acte {n}</a></div></div><div class="views-field views-field-field-activitat-on"><div class="field-content">CC Demo</div></div><div class="views-field views-field-field-activitat-quan"><div class="field-content">{when}</div></div></li>'''


def civic_page(items):
    return '<ul>' + ''.join(CIVIC_ITEM.format(n=n, state=state, when=when) for n, state, when in items) + '</ul>'


class CentresCivicsPaginationTests(unittest.TestCase):
    def test_follows_drupal_pager_and_stops_at_first_archived_page(self):
        import datetime as dt
        from src.web_agendas import SOURCES, fetch_pages, parse_centres_civics
        pages = {
            'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural': civic_page([(1, 'vigent', 'Fins al 31/10/2026'), (2, 'vigent', '23/10, 20/11 i 18/12/2026')]),
            'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural/p/page/1': civic_page([(3, 'vigent', 'Del 08/10 al 27/11/2026'), (4, '', 'Tot l\'any')]),
            'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural/p/page/2': civic_page([(5, '', '17/12/2018')]),
            'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural/p/page/3': civic_page([(6, 'vigent', '01/01/2027')]),
        }
        fetched = []
        def fetcher(url, timeout):
            fetched.append(url); return pages[url]
        got = fetch_pages(SOURCES['web_centres_civics'], fetcher, 5)
        self.assertEqual(len(got), 3)  # page 2 has no `vigent` item: stop there, never reach page 3
        self.assertEqual(fetched[1], 'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural/p/page/1')
        records = parse_centres_civics('\n'.join(body for _, body in got))
        self.assertEqual(len(records), 4)  # «Tot l'any» has no date and is skipped, not guessed
        by_title = {r['title']: r for r in records}
        today = dt.date.today().isoformat()
        self.assertEqual((by_title['Acte 1']['start'], by_title['Acte 1']['end']), (min(today, '2026-10-31'), '2026-10-31'))
        self.assertEqual((by_title['Acte 2']['start'], by_title['Acte 2']['end']), ('2026-10-23', '2026-12-18'))
        self.assertEqual((by_title['Acte 3']['start'], by_title['Acte 3']['end']), ('2026-10-08', '2026-11-27'))
        self.assertEqual(by_title['Acte 3']['raw']['image'], 'https://ajuntament.barcelona.cat/centrescivics/sites/default/files/x3.jpg')
        self.assertIn('SOURCE_PAGE_NOT_MARKED_CURRENT', by_title['Acte 5']['alerts'])
        self.assertNotIn('SOURCE_PAGE_NOT_MARKED_CURRENT', by_title['Acte 1']['alerts'])

    def test_identical_pages_mean_broken_pagination_and_stop(self):
        from src.web_agendas import fetch_pages
        same = civic_page([(1, 'vigent', '01/11/2026')])
        got = fetch_pages({'url': 'https://x/base', 'page_url': 'https://x/p/{page}', 'pages': 12, 'first_page': 0, 'continue_marker': 'vigent'}, lambda u, t: same, 5)
        self.assertEqual(len(got), 2)


class AuditoriTimeTests(unittest.TestCase):
    def test_next_date_timestamp_becomes_local_wallclock_time_and_candidate(self):
        import json as _json
        from urllib.parse import quote
        from src.pipeline import candidate_sessions
        from src.web_agendas import parse_auditori
        import datetime as dt
        from zoneinfo import ZoneInfo
        stamp = int(dt.datetime(2026, 11, 13, 19, 0, tzinfo=ZoneInfo('Europe/Madrid')).timestamp())
        payload = {'events': [{'wp_post': {'post_title': 'OBC demo'}, 'event_next_date': stamp, 'link': 'https://www.auditori.cat/es/obc-demo', 'hall_obj': {'wp_post': {'post_title': 'Sala 1 Pau Casals'}}, 'image_html': '<img src="https://www.auditori.cat/demo.jpg">', 'price_text': '20 €'}]}
        page = "<script>window.aPnextevents = JSON.parse(decodeURIComponent('%s'));</script>" % quote(_json.dumps(payload))
        records = parse_auditori(page)
        self.assertEqual((records[0]['start'], records[0]['time_text'], records[0]['venues'][0]['name']), ('2026-11-13', '19:00', 'Sala 1 Pau Casals'))
        sessions = candidate_sessions(records[0])
        self.assertEqual([(s['local_date'], s['local_time'], s['evidence_field']) for s in sessions], [('2026-11-13', '19:00', 'event_next_date')])
        cccb = parse_cccb(CCCB)
        self.assertEqual([(s['local_time'], s['evidence_field']) for s in candidate_sessions(cccb[0])], [('18:30', 'listing_time')])
