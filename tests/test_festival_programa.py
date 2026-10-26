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


class AcceleventsTest(unittest.TestCase):
    """Programa en Accelevents (Mozilla Festival, 25-10-2026)."""
    def test_sesiones_con_hora_sala_y_festival(self):
        from src.venue_feeds import accelevents_nodes
        ev = {"name": "Mozilla Festival 2026", "address": "RECINTE FABRA I COATS, Carrer de Sant Adrià, Barcelona, Spain", "latitude": "41.4333", "longitude": "2.1914"}
        sessions = {"recordsTotal": 3, "data": [
            {"sessionId": 1, "title": "Attack the AI. Then Defend It.", "startTime": "2026/10/28 10:00", "endTime": "2026/10/28 11:00", "locationName": "B1 Room",
             "format": "WORKSHOP", "sessionVisibilityType": "PUBLIC", "sessionStatus": "VISIBLE"},
            {"sessionId": 2, "title": "Oculta", "startTime": "2026/10/28 12:00", "endTime": "2026/10/28 13:00", "sessionVisibilityType": "PRIVATE", "sessionStatus": "VISIBLE"},
            {"sessionId": 3, "title": "Sin hora", "startTime": None}]}
        def fetcher(url, timeout):
            return (200, url, json.dumps(ev if "/rest/cache/event/" in url else sessions))
        v = {"slug": "mozilla_festival", "name": "Mozilla Festival", "type": "festival",
             "feed": {"kind": "accelevents", "event": "mozilla-festival-2026", "url": "https://e/schedule", "lugar": "Fabra i Coats",
                      "festival": {"slug": "mozilla-festival", "name": "Mozilla Festival"}}}
        nodes, fetched = accelevents_nodes(v, fetcher)
        self.assertEqual(len(nodes), 1)
        r = record_from_jsonld(v, nodes[0][1], nodes[0][0])
        self.assertEqual((r['title'], r['start'], r['time_text'], r['venues'][0]['name']), ('Attack the AI. Then Defend It.', '2026-10-28', '10:00', 'Fabra i Coats'))
        self.assertEqual(nodes[0][1]['x_festival']['slug'], 'mozilla-festival')
        self.assertIn('B1 Room', nodes[0][1]['description'])


class AbonoTest(unittest.TestCase):
    """Festival con abono (25-10-2026): los actos van al programa de la ficha del festival, no tienen ficha propia."""
    def test_programa_en_la_ficha(self):
        import tempfile
        from pathlib import Path
        from src.venue_feeds import accelevents_nodes
        from src.festivals import programs
        ev = {"address": "RECINTE FABRA I COATS, Carrer de Sant Adrià, Barcelona", "latitude": "41.43", "longitude": "2.19"}
        sessions = {"recordsTotal": 2, "data": [
            {"sessionId": 1, "title": "Wild AI", "startTime": "2026/10/28 10:00", "endTime": "2026/10/28 11:00", "locationName": "E1 Stage", "requiredTicketTypeIds": []},
            {"sessionId": 2, "title": "Taller de pago aparte", "startTime": "2026/10/28 12:00", "endTime": "2026/10/28 13:00", "requiredTicketTypeIds": [99]}]}
        fetcher = lambda url, t: (200, url, json.dumps(ev if "/rest/cache/event/" in url else sessions))
        v = {"slug": "mozilla_festival", "name": "Mozilla Festival", "type": "festival",
             "feed": {"kind": "accelevents", "venta": "abono", "event": "x", "url": "https://e/s", "lugar": "Fabra i Coats", "festival": {"slug": "mozilla-festival", "name": "Mozilla Festival"}}}
        nodes, _ = accelevents_nodes(v, fetcher)
        recs = [record_from_jsonld(v, n, u) for u, n in nodes]
        self.assertEqual([r['eligibility'] for r in recs][0], 'exclude')          # con el abono: sin ficha propia
        self.assertNotEqual(recs[1]['eligibility'], 'exclude')                     # entrada propia: ficha propia
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for r in recs:
                conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility,source_url) VALUES(?,?,?,?,?,?,?,?)",
                             (r['source'], r['id'], r['title'], r['start'], r['end'], json.dumps(r['raw']), r['eligibility'], ''))
            prog = programs(conn, '2026-10-25')
            self.assertEqual([(p['date'], p['time'], p['title'], p['room']) for p in prog['mozilla-festival']], [('2026-10-28', '10:00', 'Wild AI', 'E1 Stage')])


class CriterioProgramaTest(unittest.TestCase):
    """Precio del festival = abono (25-10-2026): al programa salvo entrada propia; «por_acto», ficha propia."""
    def test_por_defecto_programa_y_entrada_propia(self):
        from src.venue_feeds import festival_nodes
        v = {"feed": {"festival": {"slug": "f", "name": "F"}, "desde": "2026-11-06", "hasta": "2026-11-07"}}
        nodes = [("u", {"name": "A", "startDate": "2026-11-06T22:00"}), ("u", {"name": "B", "startDate": "2026-11-07T20:00", "offers": {"price": "12"}}),
                 ("u", {"name": "C", "startDate": "2026-12-01T20:00"})]
        out = festival_nodes(v, nodes)
        self.assertEqual([(n["name"], n["x_programa"]) for _, n in out], [("A", True), ("B", False)])   # C, fuera de fechas
        v["feed"]["venta"] = "por_acto"
        self.assertEqual([n["x_programa"] for _, n in festival_nodes(v, [("u", {"name": "D", "startDate": "2026-11-06"})])], [False])


class MidnightTest(unittest.TestCase):
    """Auditoría 25-10-2026: 00:00 sin fin coherente no es una hora de la fuente."""
    def test_medianoche(self):
        v = {"slug": "dice", "name": "Dice", "type": "ticketing"}
        r = lambda n: record_from_jsonld(v, {"name": "X", "location": {"name": "Sala", "address": {"addressLocality": "Barcelona"}}, **n}, "https://d/x")
        self.assertEqual(r({"startDate": "2027-02-05T00:00", "endDate": "2027-02-05T23:59"})["time_text"], "")
        self.assertEqual(r({"startDate": "2027-02-05T00:00"})["time_text"], "")
        self.assertEqual(r({"startDate": "2026-11-06T00:00", "endDate": "2026-11-06T06:00"})["time_text"], "00:00")   # sesión de club
        self.assertEqual(r({"startDate": "2026-11-06T00:00", "x_time_verified": True})["time_text"], "00:00")          # cita comprobada
        self.assertEqual(r({"startDate": "2026-11-06T21:00"})["time_text"], "21:00")
