"""Fechas de la web oficial de una exposición (src/official_dates.py, 21-10-2026)."""
import datetime as dt
import json
import sqlite3
import unittest

from src import official_dates as od

D = dt.date.fromisoformat


class RangeTests(unittest.TestCase):
    def test_formats_seen_on_museum_pages(self):
        cases = {
            '10 / 11 / 2026 - 14 / 03 / 2027': ('2026-11-10', '2027-03-14', 'day'),             # Disseny Hub
            '09/10/2026 — 28/02/2027': ('2026-10-09', '2027-02-28', 'day'),                     # Fundació Miró
            'Del 18 de setembre de 2026al 31 de desembre de 2026': ('2026-09-18', '2026-12-31', 'day'),  # Sagrada Família 2026
            'Del 9 de juliol de 2026 a juny 2027': ('2026-07-09', '2027-06-30', 'month'),        # MACBA
            "Del 3 d'octubre al 12 de gener de 2027": ('2026-10-03', '2027-01-12', 'day'),
            "10 al 25 d'octubre de 2026": ('2026-10-10', '2026-10-25', 'day'),
            'From 3 Oct to 12 Jan 2027': ('2026-10-03', '2027-01-12', 'day'),
        }
        for text, (a, b, p) in cases.items():
            got = od.ranges(text)
            self.assertTrue(got, text)
            self.assertEqual((got[0][0].isoformat(), got[0][1].isoformat(), got[0][2], got[0][3]), (a, b, p, text))

    def test_the_labelled_range_wins_over_other_activities(self):
        text = "EXPOSICIÓ\nEN CURS\nDATES\nDel 9 de juliol de 2026 a juny 2027\nACTIVITAT\nDEL 8 DE NOVEMBRE DE 2026 AL 23 DE MAIG DE 2027"
        got = od.choose(text, D('2026-07-09'), D('2027-01-11'))
        self.assertEqual((got[0], got[1], got[2]), (D('2026-07-09'), D('2027-06-30'), 'month'))

    def test_implausible_range_is_ignored(self):
        self.assertIsNone(od.choose('Del 1 de gener de 2024 al 3 de març de 2024', D('2026-10-09'), D('2027-02-28')))

    def test_links(self):
        raw = json.dumps({'a': 'https://guia.barcelona.cat/ca/detall/x_1.html', 'b': 'https://www.fmirobcn.org/ca/exposicions/7357/charlotte-perriand',
                          'c': 'https://www.instagram.com/fmirobcn', 'd': 'http://www.fmirobcn.org', 'e': 'https://www.fmirobcn.org/media/x.jpg'})
        self.assertEqual(od.links_of(raw, 'Exposició "Charlotte Perriand"'), ['https://www.fmirobcn.org/ca/exposicions/7357/charlotte-perriand'])


class RunTests(unittest.TestCase):
    def test_reads_the_official_page_and_keeps_the_quote(self):
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE source_records(source,id,title,start_date,end_date,kind,eligibility,raw_json)")
        raw = json.dumps({'url': 'https://www.fmirobcn.org/ca/exposicions/7357/charlotte-perriand'})
        conn.execute("INSERT INTO source_records VALUES('opendatabcn_agenda','1','Exposició \"Charlotte Perriand\"','2026-10-06','2027-03-28','exhibition','review',?)", (raw,))
        page = "<html><head><title>Charlotte Perriand | Fundació Joan Miró</title></head><body><nav>Exposicions</nav><h1>Charlotte Perriand. La llibertat de repensar el món</h1><p>09/10/2026 — 28/02/2027</p><p>Divided</p><p>14/07/2026 — 17/01/2027</p></body></html>"
        result = od.run(conn, fetcher=lambda url, timeout: (200, url, page), today=D('2026-10-21'))
        self.assertEqual(result['with_dates'], 1)
        got = od.official(conn)[('opendatabcn_agenda', '1')]
        self.assertEqual((got['start'], got['end'], got['quote']), ('2026-10-09', '2027-02-28', '09/10/2026 — 28/02/2027'))

    def test_a_page_about_something_else_is_not_used(self):
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE source_records(source,id,title,start_date,end_date,kind,eligibility,raw_json)")
        conn.execute("INSERT INTO source_records VALUES('guiabcn','2','Exposició \"Charlotte Perriand\"','2026-10-06','2027-03-28','exhibition','review',?)",
                     (json.dumps({'u': 'https://www.example.org/agenda/tardor'}),))
        page = "<html><title>Agenda de tardor</title><body>Del 1 d'octubre al 30 de novembre de 2026</body></html>"
        od.run(conn, fetcher=lambda url, timeout: (200, url, page), today=D('2026-10-21'))
        self.assertEqual(od.official(conn), {})


if __name__ == '__main__':
    unittest.main()


class CalendarSessionsTest(unittest.TestCase):
    def test_lee_los_pases_del_calendario_impreso(self):
        from src.official_dates import page_facts
        page = ('<div class="ticketsCalendar__sessions is-active" data-calendar-sessions="2026-10-23"><div class="ticketsCalendar__sessionTime"> <span>20:00</span> </div></div>'
                '<div class="ticketsCalendar__sessions" data-calendar-sessions="2026-10-24"><div class="ticketsCalendar__sessionTime"> <span>18:00</span></div>'
                '<div class="ticketsCalendar__sessionTime"> <span>21:00</span></div></div>')
        times, _, _ = page_facts(page, 'El Tenoriu', '2026-10-01', '2026-11-30', today=__import__('datetime').date(2026, 10, 20))
        self.assertEqual(times, {'2026-10-23': '20:00', '2026-10-24': '18:00'})


class SingleClockTest(unittest.TestCase):
    def _read(self, body):
        from src.official_dates import read_page
        page = f'<html><head><title>Joan Reggae Drummer All Stars - Sala Upload</title></head><body>{body}</body></html>'
        return read_page('https://sala-upload.com/conciertos/joan-reggae-drummer-all-stars/', 'Joan Reggae Drummer All Stars', '2026-10-23', '2026-10-23', lambda u, t: (200, u, page), 5)

    def test_una_sola_hora_en_la_pagina_es_la_del_acto(self):
        self.assertEqual(self._read('<p>Divendres 23 octubre</p><p>20:00</p><p>Entrades 15 €</p>')['times'], {'2026-10-23': '20:00'})

    def test_con_dos_horas_no_se_elige(self):
        self.assertEqual(self._read('<p>Portes 19:30</p><p>Concert 20:30</p>')['times'], {})
