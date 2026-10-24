"""Aplazados, cancelados, precio 0 y avisos de la fuente (24-10-2026)."""
import datetime as dt
import json
import unittest

from mvp import catalog
from src import event_status, official_dates
from src.pipeline import connect
from src.sync import initialize as init_sync

TODAY = dt.date(2026, 10, 24)


def _add(conn, source, rid, title, start, end, venue, raw):
    conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) "
                 "VALUES(?,?,?,?,?,'single','review','','',?,?)", (source, rid, title, start, end, rid, json.dumps(raw)))
    conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',NULL,NULL)", (source, rid, venue))


class EventStatusTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        # El caso real: GuiaBCN dice «Acte ajornat»; Open Data (mismo id) aún «ok»; Conciertos.Club sin estado.
        _add(self.conn, 'guiabcn', '99400747179', 'Concert "Dani Martin", dins la gira "25 P*t*s Años" *Ajornat', '2026-10-23', '2026-10-24', 'Palau Sant Jordi',
             {'api_item': {'status': {'item': {'code': '3', 'name': 'Acte ajornat'}}, 'warning': 'Ajornat. Properament es comunicaran les noves dates'}})
        _add(self.conn, 'opendatabcn_agenda', '99400747179', 'Concert "Dani Martin", dins la gira "25 P*t*s Años"', '2026-10-23', '2026-10-24', 'Palau Sant Jordi', {'event_status': 'ok'})
        _add(self.conn, 'web_conciertos_club', 'cc24', 'Dani Martín', '2026-10-24', '2026-10-24', 'Palau Sant Jordi', {})
        # Otro concierto en el mismo recinto y día, y el mismo artista en otro recinto: no se tocan.
        _add(self.conn, 'web_conciertos_club', 'otro', 'Fontaines D.C', '2026-10-24', '2026-10-24', 'Palau Sant Jordi', {})
        _add(self.conn, 'web_conciertos_club', 'lejos', 'Dani Martín', '2026-10-24', '2026-10-24', 'Sala Razzmatazz', {})
        _add(self.conn, 'web_conciertos_club', 'taller', 'Taller', '2026-11-05', '2026-11-05', 'Centre Cívic X', {})
        _add(self.conn, 'guiabcn', 'leds', 'Taller "Control de Leds amb touchdesigner" *Suspès', '2026-11-05', '2026-11-26', 'Centre Cívic X', {})

    def test_aplazado_en_todas_las_fichas_del_mismo_acto(self):
        got = event_status.compute(self.conn, TODAY)
        for key in (('guiabcn', '99400747179'), ('opendatabcn_agenda', '99400747179'), ('web_conciertos_club', 'cc24')):
            self.assertEqual(got[key]['estado'], 'aplazado', key)
        self.assertIn('Acte ajornat', got[('web_conciertos_club', 'cc24')]['evidencia'])
        for key in (('web_conciertos_club', 'otro'), ('web_conciertos_club', 'lejos'), ('web_conciertos_club', 'taller')):
            self.assertNotIn(key, got)
        self.assertEqual(got[('guiabcn', 'leds')]['estado'], 'cancelado')   # marca del título

    def test_open_data_deferred(self):
        _add(self.conn, 'opendatabcn_agenda', 'x', 'Concert X', '2026-11-01', '2026-11-01', 'Sala Apolo', {'event_status': 'deferred', 'event_status_name': 'Ajornat'})
        self.assertEqual(event_status.compute(self.conn, TODAY)[('opendatabcn_agenda', 'x')]['estado'], 'aplazado')


class PriceZeroTest(unittest.TestCase):
    def test_precio_cero_no_es_gratis(self):
        self.assertEqual(official_dates._price_of({'@type': 'Offer', 'price': '0'}), ('', False))
        self.assertEqual(official_dates._price_of([{'price': '0'}, {'price': '35'}]), ('0 € – 35 €', False))

    def test_gratis_solo_si_lo_dice(self):
        page = '<script type="application/ld+json">{"@type":"Event","name":"Gran Gala Flamenco","startDate":"2026-10-27T20:00","offers":{"price":"0"}}</script>'
        self.assertEqual(official_dates.page_facts(page, 'Gran Gala Flamenco', '2026-10-27', '2026-10-27')[1:], ('', False))
        page = page.replace('"offers"', '"isAccessibleForFree":true,"offers"')
        self.assertEqual(official_dates.page_facts(page, 'Gran Gala Flamenco', '2026-10-27', '2026-10-27')[1:], ('Gratis', True))


class NoticesTest(unittest.TestCase):
    def test_avisos_publicos_de_la_fuente(self):
        raw = {'warnings': [{'type': 'public', 'text': "<p>Entrades exhaurides pel concert del 24 d'octubre</p>"}, {'type': 'internal', 'text': 'preus?'}]}
        self.assertEqual(catalog.source_notices(raw, 'opendatabcn_agenda'), ["Aviso del Ajuntament: Entrades exhaurides pel concert del 24 d'octubre"])
        self.assertEqual(catalog.source_notices({}, 'venue_ia_poliorama'), [])


if __name__ == '__main__':
    unittest.main()
