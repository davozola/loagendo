import json
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src.html_agenda import events_from_html, parse_date, parse_price
from src.pipeline import connect
from src.venue_feeds import sync_venue

SIDECAR = '''<html><body><div class="items concerts">
<div class="info-box"><div class="inner-content"><a class="category" href="#">Concert</a><a class="date" href="#">Dijous 15.10.2026 20:30</a><div class="info"><div class="meta"><a class="title" href="https://sidecar.test/mc-luanna/">MC LUANNA</a><a class="style" href="#">rap carioca</a></div><div class="tickets"><a class="button" href="https://dice.fm/event/luanna"><span>12+€</span></a></div></div></div></div>
<div class="info-box"><div class="inner-content"><a class="category" href="#">DJ session</a><a class="date" href="#">Divendres 16.10.2026 23:59</a><div class="info"><div class="meta"><a class="title" href="https://sidecar.test/dj/">DJ NIGHT</a></div></div></div></div>
<div class="info-box"><div class="inner-content"><a class="category" href="#">Concert</a><a class="date" href="#">Dilluns 01.09.2026 20:00</a><div class="info"><div class="meta"><a class="title" href="https://sidecar.test/past/">PASADO</a></div></div></div></div>
</div></body></html>'''
VOL = '''<html><body><a class="dataModule" href="/agenda/acopia"><div class="dataModule__col dataModule__col--left"><div>Dissabte</div><div>06/09/2025 20:00</div><div> 15/17€</div></div><div class="dataModule__col dataModule__col--right"><div>Acopia</div><div>SDH</div></div></a>
<a class="dataModule" href="/agenda/humo"><div class="dataModule__col dataModule__col--left"><div>Divendres</div><div>02/10/2026 20:00</div><div> 12/15€</div></div><div class="dataModule__col dataModule__col--right"><div>Humo Internacional presenta: From</div></div></a></body></html>'''
SIDECAR_FEED = {'kind': 'html', 'url': 'https://sidecar.test/programacio/', 'item': 'div.info-box', 'fields': {'title': 'a.title', 'url': 'a.title@href', 'date': 'a.date', 'category': 'a.category', 'style': 'a.style', 'price': 'div.tickets span', 'tickets': 'div.tickets a@href'}, 'skip': {'category': ['DJ session']}}
VOL_FEED = {'kind': 'html', 'url': 'https://vol.test/agenda/', 'item': 'a.dataModule', 'fields': {'title': 'div.dataModule__col--right div', 'url': '.@href'}}


class HtmlAgendaTests(unittest.TestCase):
    def test_dates_and_prices_as_printed(self):
        self.assertEqual(parse_date('Dijous 15.10.2026 20:30'), ('2026-10-15', '20:30'))
        self.assertEqual(parse_date('Diumenge 15.11.2026 | 20:30'), ('2026-11-15', '20:30'))
        self.assertEqual(parse_date('06/09/2025'), ('2025-09-06', ''))
        self.assertIsNone(parse_date('sense data'))
        self.assertEqual(parse_price('Dissabte 06/09/2025 20:00 15/17€ Acopia'), '15/17€')

    def test_sidecar_blocks_skip_dj_sessions_and_past_dates(self):
        nodes = events_from_html(SIDECAR, SIDECAR_FEED, 'https://sidecar.test/programacio/', today=dt.date(2026, 10, 13))
        self.assertEqual([(n['name'], n['startDate'], n['offers']['price'], n['offers']['url'], n['genre']) for n in nodes], [('MC LUANNA', '2026-10-15T20:30:00', '12+€', 'https://dice.fm/event/luanna', 'Concert · rap carioca')])

    def test_vol_blocks_join_acts_and_read_date_from_text(self):
        nodes = events_from_html(VOL, VOL_FEED, 'https://vol.test/agenda/', today=dt.date(2025, 9, 1))
        self.assertEqual([(n['name'], n['startDate'], n['url'], n['offers']['price']) for n in nodes],
                         [('Acopia + SDH', '2025-09-06T20:00:00', 'https://vol.test/agenda/acopia', '15/17€'), ('Humo Internacional presenta: From', '2026-10-02T20:00:00', 'https://vol.test/agenda/humo', '12/15€')])

    def test_sync_reads_the_listing_and_the_event_pages(self):
        pages = {'https://sidecar.test/programacio/': (200, 'https://sidecar.test/programacio/', SIDECAR.replace('15.10.2026', '15.10.2099')),
                 'https://sidecar.test/mc-luanna/': (200, 'https://sidecar.test/mc-luanna/', '<html><head><meta property="og:image" content="https://sidecar.test/img/luanna.jpg" /></head></html>')}
        fetcher = lambda url, timeout: pages.get(url, (404, url, ''))
        venue = {'slug': 'sidecar', 'name': 'Sidecar', 'type': 'music', 'url': 'https://sidecar.test/', 'enabled': True, 'feed': SIDECAR_FEED}
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            result = sync_venue(conn, venue, fetcher=fetcher)
            self.assertEqual(result['status'], 'completed', result.get('error'))
            rows = conn.execute("SELECT title,start_date,source_url FROM source_records WHERE source='venue_sidecar'").fetchall()
            self.assertEqual(rows, [('MC LUANNA', '2099-10-15', 'https://sidecar.test/mc-luanna/')])
            self.assertEqual(conn.execute("SELECT original_url FROM media_assets WHERE source='venue_sidecar'").fetchone()[0], 'https://sidecar.test/img/luanna.jpg')
            raw = json.loads(conn.execute("SELECT raw_json FROM source_records WHERE source='venue_sidecar'").fetchone()[0])
            self.assertEqual(raw['loagendo']['tickets_url'], 'https://dice.fm/event/luanna')
            catalog.invalidate_cache(); conn.close()
