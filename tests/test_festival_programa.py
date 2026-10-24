"""Programa oficial de un festival (24-10-2026): horarios de MIRA y su lugar en la agenda."""
import datetime as dt
import json
import unittest
from unittest import mock

from src import dedupe
from src.pipeline import connect
from src.sync import initialize as init_sync
from src.venue_feeds import festival_schedule_nodes, record_from_jsonld

ROW = ('<div class="col-8 subgrid schedule__row post-type-show schedule__row--clickable"> <!-- TIME --><div class="col-2 schedule__row-time"><p> {t}</p></div>'
       ' <!-- ARTIST --><div class="col-3 schedule__row-artists"> <a\n href="https://mirafestival.com/show/{slug}/"\n class="btn btn--light t-ui"\n > {name} </a></div>'
       ' <!-- IMAGE --><div class="col-1 schedule__row-image"> <a href="https://mirafestival.com/show/{slug}/"> <img\n width="300" src="https://mirafestival.com/wp-content/uploads/{slug}.jpg"\n alt="{name}"> </a></div>'
       ' <!-- TYPE --><div class="col-2 schedule__row-type"> <a href="https://mirafestival.com/categoria_show/x/"> {kind} </a></div></div>')


def page():
    def venue(stage, rows): return ('<div class="col-8 subgrid schedule__venue"><div class="col-8 schedule__venue-title"><h4 class="p-s"> ' + stage + '</h4></div>' +
                                    ''.join(ROW.format(**r) for r in rows) + '</div>')
    fri = venue('Voll-Damm', [dict(t='22:15 - 23:35', slug='tortoise', name='Tortoise', kind='Live'), dict(t='01:15 - 02:15', slug='arca', name='Arca', kind='Live AV Show'),
                              dict(t='02:30 - 03:30', slug='datapunk', name='DATAPUNK (Hybrid) presentado por Anthony Rother + VPM', kind='Hybrid Show')])
    fri += venue('Digital Art Area by Landscapes', [dict(t='17:30 - 05:30', slug='inst', name='Instalaciones', kind='')])
    sat = venue('DICE', [dict(t='19:25 - 20:30', slug='space-afrika', name='Space Afrika', kind='Live AV Show')])
    return ('<section class="schedule js-schedule"><button data-day-target="schedule-day-20261106"> Viernes 6 </button>'
            '<div\n id="schedule-day-20261106"\n class="col-8 subgrid schedule__group schedule__panel is-active"\n role="tabpanel"\n >' + fri + '</div>'
            '<div\n id="schedule-day-20261107"\n class="col-8 subgrid schedule__group schedule__panel"\n >' + sat + '</div></section>')


VENUE = {"slug": "mira_festival", "name": "MIRA Festival", "type": "festival",
         "feed": {"kind": "festival_schedule", "url": "https://mirafestival.com/horarios/", "lugar": "Fira de Barcelona - Montjuïc", "lat": 41.37272, "lon": 2.15021,
                  "festival": {"slug": "mira-festival", "name": "MIRA Festival"}}}


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.nodes, _ = festival_schedule_nodes(VENUE, fetcher=lambda u, t: (200, u, page()))

    def test_cada_actuacion_con_su_dia_hora_escenario_y_festival(self):
        got = [(n['name'], n['startDate'], n['x_room']) for _, n in self.nodes]
        self.assertEqual(got, [('Tortoise', '2026-11-06T22:15', 'Voll-Damm'), ('Arca', '2026-11-06T01:15', 'Voll-Damm'),
                               ('DATAPUNK (Hybrid) presentado por Anthony Rother + VPM', '2026-11-06T02:30', 'Voll-Damm'),
                               ('Instalaciones · Digital Art Area by Landscapes', '2026-11-06T17:30', 'Digital Art Area by Landscapes'),
                               ('Space Afrika', '2026-11-07T19:25', 'DICE')])
        self.assertTrue(all(n['x_festival']['slug'] == 'mira-festival' for _, n in self.nodes))

    def test_madrugada_dicha_y_ficha(self):
        arca = next(n for _, n in self.nodes if n['name'] == 'Arca')
        self.assertEqual(arca['x_time_text'], '01:15–02:15 (madrugada del sábado 7)')
        rec = record_from_jsonld(VENUE, arca, VENUE['feed']['url'])
        self.assertEqual((rec['start'], rec['end'], rec['time_text']), ('2026-11-06', '2026-11-06', '01:15–02:15 (madrugada del sábado 7)'))
        self.assertEqual(rec['raw']['image'], 'https://mirafestival.com/wp-content/uploads/arca.jpg')
        self.assertEqual(rec['url'], 'https://mirafestival.com/show/arca/')


class OfficialSetTest(unittest.TestCase):
    """El anuncio suelto de un artista del cartel va con su actuación del programa oficial, no con la ficha general."""
    def test_anuncio_de_songkick_con_la_actuacion(self):
        conn = connect(':memory:'); init_sync(conn)
        def add(source, rid, title, start, end, venue, raw=None):
            conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) "
                         "VALUES(?,?,?,?,?,'single','include','','',?,?)", (source, rid, title, start, end, rid, json.dumps(raw or {})))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',41.3727,2.1502)", (source, rid, venue))
            return f'{source}:{rid}'
        lineup = {'loagendo': {'performers': ['Arca', 'Tortoise', 'Anthony Rother', 'Max Cooper']}}
        fest = add('venue_dice', 'f', 'MIRA Festival 2026', '2026-11-06', '2026-11-07', 'Fira Montjuïc', lineup)
        songkick = add('venue_songkick', 's', 'Anthony Rother', '2026-11-06', '2026-11-06', 'Fira Montjuic', lineup)
        other = add('venue_songkick', 'm', 'Max Cooper', '2026-11-07', '2026-11-07', 'Fira Montjuic', lineup)
        official = add('venue_mira_festival', 'o', 'DATAPUNK (Hybrid) presentado por Anthony Rother + VPM', '2026-11-06', '2026-11-06', 'Fira de Barcelona - Montjuïc')
        fake = mock.Mock(wraps=dt.date); fake.today.return_value = dt.date(2026, 10, 24); fake.fromisoformat = dt.date.fromisoformat
        with mock.patch.object(dt, 'date', fake), mock.patch('src.venue_directory.venue_type', lambda slug: 'festival' if slug == 'mira_festival' else 'music'):
            pairs = {frozenset(p) for p in dedupe.festival_pairs(conn)}
            acts = {frozenset(p) for p in dedupe.act_pairs(conn)}
        self.assertNotIn(frozenset((songkick, fest)), pairs)       # no se esconde en la ficha general…
        self.assertIn(frozenset((songkick, official)), acts)        # …va con su actuación
        self.assertIn(frozenset((other, fest)), pairs)              # sin actuación oficial leída: como antes


if __name__ == '__main__':
    unittest.main()
