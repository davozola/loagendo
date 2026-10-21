"""Fuente oficial primero (21-10-2026): agendas con schema.org sin IA, página oficial del acto y origen de los datos."""
import datetime as dt
import json
import sqlite3
import unittest
from unittest import mock

from src import ai_agenda, data_origin, official_dates as od

PAGE = """<html><head><title>Agenda | Sala X</title><script type="application/ld+json">[
 {"@type":"MusicEvent","name":"Mishima Tornada","startDate":"2099-11-02T21:00","url":"https://salax.cat/a","location":{"@type":"Place","name":"Sala X","address":{"@type":"PostalAddress","addressLocality":"Barcelona"}},"offers":{"@type":"Offer","price":"15"}},
 {"@type":"MusicEvent","name":"Manel Girona","startDate":"2099-11-03T20:00","location":{"@type":"Place","name":"Sala X","address":{"@type":"PostalAddress","addressLocality":"Girona"}}},
 {"@type":"MusicEvent","name":"Antic Passat","startDate":"2000-01-01T20:00","location":{"@type":"Place","name":"Sala X"}}]</script></head><body>Agenda</body></html>"""


class RulesFirstTests(unittest.TestCase):
    def test_schema_org_agenda_is_read_without_ai(self):
        agenda = {'slug': 'sala_x', 'name': 'Sala X', 'address': 'Carrer 1, Barcelona', 'type': 'music', 'urls': ['https://salax.cat/agenda']}
        requester = mock.Mock(side_effect=AssertionError('no se llama a la IA'))
        with mock.patch('src.venue_feeds.robots_allows', return_value=True):
            res = ai_agenda.read_agenda(agenda, dt.date(2099, 10, 21), 'key', fetcher=lambda url, timeout: (200, url, PAGE), requester=requester)
        self.assertEqual([n['name'] for n, _, _ in res['rules_nodes']], ['Mishima Tornada'])   # Girona y pasados fuera
        records = ai_agenda.rules_records(agenda, res['rules_nodes'])
        self.assertEqual(records[0]['source'], 'venue_ia_sala_x')
        self.assertEqual(records[0]['raw']['loagendo']['source_label'], 'Datos de la sala')
        requester.assert_not_called()


class OfficialPageTests(unittest.TestCase):
    def test_hour_and_price_from_the_act_page(self):
        times, price, free = od.page_facts(PAGE, 'Concert "Mishima Tornada"', '2099-11-02', '2099-11-02')
        self.assertEqual((times, price, free), ({'2099-11-02': '21:00'}, '15 €', False))

    def test_page_about_another_act_is_not_used(self):
        page = "<html><title>Agenda general</title><body>Res</body></html>"
        res = od.read_page('https://salax.cat/agenda', 'Mishima Tornada', '2099-11-02', '2099-11-02', lambda u, t: (200, u, page), 10)
        self.assertEqual(res['status'], 'no_es_del_acto')


class OriginTests(unittest.TestCase):
    def test_origin_ranking(self):
        with mock.patch('src.venue_directory.venue_type', return_value='music'):
            self.assertEqual(data_origin.of_source('venue_ia_palau_musica'), 'centro')
        self.assertEqual(data_origin.of_source('opendatabcn_agenda', 'Centre Cívic Sant Andreu'), 'red_publica')
        self.assertEqual(data_origin.of_source('opendatabcn_agenda', 'Palau de la Música Catalana'), 'agenda')
        with mock.patch('src.venue_directory.venue_type', return_value='aggregator'):
            self.assertEqual(data_origin.of_source('venue_songkick'), 'directorio')
        self.assertEqual(data_origin.best(['agenda', 'web_oficial', 'directorio']), 'web_oficial')


if __name__ == '__main__':
    unittest.main()


class VenueJsonFeedTests(unittest.TestCase):
    def test_palau_programme_json(self):
        from src.venue_feeds import palau_json_nodes, record_from_jsonld
        data = {"productions": {"1": {"title": "<p>Buhos</p>", "url": "https://www.palaumusica.cat/ca/buhos_1", "price": "32 €", "listing_image": 9}},
                "stages": {"1272": {"title": "Sala de Concerts"}, "5": {"title": "Sala Petit Palau"}},
                "sessions": {"a": {"production": 1, "start_date": {"value": "2099-11-14 20:30"}, "stage": 1272},
                             "b": {"production": 1, "start_date": {"value": "2099-11-14 22:30"}, "stage": 1272},
                             "c": {"production": 1, "start_date": {"value": "2099-11-15 19:00"}, "stage": 5},
                             "d": {"production": 1, "expired": True, "start_date": {"value": "2020-01-01 19:00"}, "stage": 5}}}
        v = {'slug': 'palau_musica', 'name': 'Palau de la Música Catalana', 'type': 'music', 'feed': {'url': 'x'}}
        recs = [record_from_jsonld(v, n, u) for u, n in palau_json_nodes(v, lambda u, t: (200, u, json.dumps(data)))[0]]
        self.assertEqual([(r['start'], r['time_text'], r['price_text'], r['venues'][0]['name']) for r in recs],
                         [('2099-11-14', '20:30 · 22:30', '32 €', 'Palau de la Música Catalana'), ('2099-11-15', '19:00', '32 €', 'Palau de la Música Catalana · Sala Petit Palau')])

    def test_liceu_programme_json_in_barcelona_time(self):
        from src.venue_feeds import liceu_json_nodes
        data = {"productions": {"1": {"title": {"ca": "La clemenza di Tito"}, "url": {"ca": "/ca/clemenza-tito"}, "sessions": [{"date": 1795627800}]}}}
        v = {'slug': 'liceu', 'name': 'Gran Teatre del Liceu', 'site': 'https://www.liceubarcelona.cat/', 'feed': {'url': 'x'}}
        (url, node), = liceu_json_nodes(v, lambda u, t: (200, u, json.dumps(data)), today=dt.date(2026, 10, 21))[0]
        self.assertEqual((node['startDate'], url), ('2026-11-25T18:30', 'https://www.liceubarcelona.cat/ca/clemenza-tito'))
