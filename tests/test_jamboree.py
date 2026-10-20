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
        self.assertEqual([r["title"] for r in self.records], ["Chico Pinheiro Quartet", "Clarence Bekker Christmas Special"])
        chico, bekker = self.records
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
