import datetime as dt
import json
import unittest
from pathlib import Path

from src.pipeline import candidate_sessions
from src.venue_feeds import record_from_jsonld, tribe_list_nodes

PAGE = (Path(__file__).parent / "fixtures" / "jamboree_agenda.html").read_text(encoding="utf-8")
VENUE = next(v for v in json.loads((Path(__file__).parent.parent / "config" / "venues.json").read_text(encoding="utf-8"))["venues"] if v["slug"] == "jamboree")


class TribeListTest(unittest.TestCase):
    def setUp(self):
        fetcher = lambda url, timeout: (200, url, PAGE)
        self.nodes, _ = tribe_list_nodes(VENUE, fetcher, today=dt.date(2026, 10, 20))
        self.records = [record_from_jsonld(VENUE, node, url) for url, node in self.nodes]

    def test_reads_sessions_room_price_and_skips_past(self):
        self.assertEqual([r["title"] for r in self.records], ["Chico Pinheiro Quartet", "Benziê", "Clarence Bekker Christmas Special"])
        chico, benzie, bekker = self.records
        # Un solo pase: la hora va en un segundo <time> sin datetime (23-10-2026).
        self.assertEqual((benzie["start"], benzie["time_text"]), ("2026-10-23", "23:00"))
        self.assertEqual([o["local_time"] for o in candidate_sessions(benzie)], ["23:00"])
        self.assertEqual((chico["start"], chico["time_text"], chico["price_text"]), ("2026-10-20", "19:00 · 20:30", "25€"))
        self.assertEqual(chico["raw"]["loagendo"]["room"], "Jamboree Sala 1")
        self.assertEqual(chico["raw"]["loagendo"]["tickets_url"], "https://tickets.oneboxtds.com/jamboree/events/53460?hl=ca-ES")
        self.assertTrue(chico["raw"]["image"].endswith(".jpg"))
        self.assertEqual((bekker["start"], bekker["time_text"]), ("2026-12-17", "21:00"))
        self.assertIn("Plaça Reial", chico["venues"][0]["address"])

    def test_each_session_is_an_occurrence(self):
        chico = self.records[0]
        self.assertEqual([o["local_time"] for o in candidate_sessions(chico)], ["19:00", "20:30"])


if __name__ == "__main__":
    unittest.main()


class UnconfirmedTest(unittest.TestCase):
    def test_third_party_date_missing_from_complete_agenda_is_flagged(self):
        import sqlite3
        from src.dedupe import unconfirmed_by_venue
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE source_records(source,id,title,start_date,end_date,eligibility)")
        conn.execute("CREATE TABLE source_venues(source,id,seq,venue)")
        rows = [("venue_jamboree", "j1", "Chico Pinheiro Quartet", "2026-10-20", "Jamboree Jazz Club"),
                ("venue_jamboree", "j2", "Clarence Bekker Christmas Special", "2026-12-17", "Jamboree Jazz Club"),
                ("venue_songkick", "s1", "Chico Pinheiro", "2026-10-20", "Jamboree Jazz Club"),      # casa con la agenda
                ("venue_songkick", "s2", "Clarence Bekker", "2026-11-19", "Jamboree Jazz Club"),     # la sala no lo tiene
                ("venue_songkick", "s3", "Lejano", "2027-03-01", "Jamboree Jazz Club"),              # más allá de la agenda
                ("venue_songkick", "s4", "Otro", "2026-11-19", "Sala Apolo")]                         # sala sin agenda completa
        for source, rid, title, day, venue in rows:
            conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?, 'publish')", (source, rid, title, day, day))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,?)", (source, rid, venue))
        venues = [{"slug": "jamboree", "name": "Jamboree Jazz Club", "aliases": ["Jamboree"], "enabled": True, "agenda_completa": True}]
        groups = {"venue_songkick:s1": "venue_jamboree:j1"}
        self.assertEqual(unconfirmed_by_venue(conn, groups, venues, today=dt.date(2026, 10, 20)), {"venue_songkick:s2": "Jamboree Jazz Club"})


class ApoloTitleTest(unittest.TestCase):
    def test_title_regex_keeps_the_act_name(self):
        apolo = next(v for v in json.loads((Path(__file__).parent.parent / "config" / "venues.json").read_text(encoding="utf-8"))["venues"] if v["slug"] == "sala_apolo")
        node = {"@type": "Event", "name": "Concierto de Yard Act en La (2) de Apolo - 20 de octubre 2026", "startDate": "2026-10-20 CEST 19:30", "url": "https://www.sala-apolo.com/es/evento/yard-act-20261020-7308"}
        record = record_from_jsonld(apolo, node, node["url"])
        self.assertEqual((record["title"], record["time_text"]), ("Yard Act", "19:30"))
        self.assertEqual(record_from_jsonld(apolo, {**node, "name": "Nitsa: Oscar Mulero"}, node["url"])["title"], "Nitsa: Oscar Mulero")


class JamboreeDetailTests(unittest.TestCase):
    def test_reads_text_once_and_keeps_listing_times(self):
        calls = []
        def fetcher(url, timeout):
            calls.append(url)
            if url.endswith('/agenda/'): return 200, url, PAGE
            return 200, url, '<meta property="og:description" content="Guitarrista de São Paulo."><script type="application/ld+json">{"@type":"Event","startDate":"2026-10-20T00:00"}</script>'
        venue = {**VENUE, 'feed': {**VENUE['feed'], 'details': True}}
        nodes, _ = tribe_list_nodes(venue, fetcher, today=dt.date(2026, 10, 20))
        chico = nodes[0][1]
        self.assertEqual((chico['description'], chico['startDate']), ('Guitarrista de São Paulo.', '2026-10-20T19:00'))
        calls.clear()
        known = {u: {'description': n['description']} for u, n in nodes}
        tribe_list_nodes(venue, fetcher, today=dt.date(2026, 10, 20), known=known)
        self.assertEqual(calls, ['https://jamboreejazz.com/agenda/'])   # ya leídas: no se piden otra vez
