"""Actos ya celebrados: su ficha /e/* se conserva 6 meses con «Ya se celebró» (23-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.publish_static import keep_past_cards, shard_of, PAST_KEEP_DAYS

TODAY = dt.date(2026, 10, 23)


class PastCardsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.out = Path(self.temp.name) / 'dist'; self.out.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, events):
        cards = {}
        for k, card in events.items(): cards.setdefault(shard_of(k), {})[k] = card
        keep_past_cards(self.out, cards, TODAY)
        return {k: v for records in cards.values() for k, v in records.items()}

    def test_only_past_events_come_back_marked_and_without_calendar(self):
        self.publish({'web_auditori:1': {'t': 'Ya pasó', 'a': '2026-10-20', 'b': '2026-10-20', 'k': 'x'},
                      'web_auditori:2': {'t': 'Cancelado', 'a': '2026-11-02', 'b': '2026-11-02', 'k': 'x'},
                      'ticketmaster:3': {'t': 'Ticketmaster', 'a': '2026-10-01', 'b': '2026-10-01'},
                      'web_auditori:4': {'t': 'Sigue', 'a': '2026-10-01', 'b': '2026-12-01'}})
        again = self.publish({'web_auditori:4': {'t': 'Sigue', 'a': '2026-10-01', 'b': '2026-12-01'}})
        self.assertEqual(again['web_auditori:1']['x'], 1); self.assertEqual(again['web_auditori:1']['k'], '')
        self.assertNotIn('web_auditori:2', again)   # desapareció sin haberse celebrado: no se conserva
        self.assertNotIn('ticketmaster:3', again)    # los caducados de Ticketmaster se borran
        self.assertNotIn('x', again['web_auditori:4'])
        archive = json.loads((self.out.parent / 'data' / 'share_archive.json').read_text(encoding='utf-8'))
        self.assertIn('web_auditori:2', archive)     # el archivo no borra nada

    def test_older_than_six_months_is_not_published(self):
        old = (TODAY - dt.timedelta(days=PAST_KEEP_DAYS + 1)).isoformat()
        self.publish({'web_auditori:9': {'t': 'Antiguo', 'a': old, 'b': old}})
        self.assertNotIn('web_auditori:9', self.publish({}))


if __name__ == '__main__':
    unittest.main()
