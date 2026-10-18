"""Cartel (lineup): se guarda, se agrupa entre fuentes y se busca por artista."""
import json
import unittest

from mvp.catalog import lineup_of, merge_lineups
from src.dice_sitemap import page_lineup


class LineupTests(unittest.TestCase):
    def test_sources_and_dedupe(self):
        raw = {'loagendo': {'performers': ['Max Cooper', 'Fennesz'], 'xceed': {'lineup': ['fennesz', 'Arca']},
                            'ticketmaster': {'attractions': [{'name': 'Arca'}]}}}
        self.assertEqual(lineup_of(raw)[0], ['Max Cooper', 'Fennesz', 'Arca'])

    def test_grouped_record_gets_the_lineup_of_its_twins(self):
        events = [{'key': 'guiabcn:1', 'lineup': [], 'lineup_times': []},
                  {'key': 'venue_dice:a', 'superseded_by': 'guiabcn:1', 'lineup': ['Fennesz', 'Max Cooper'], 'lineup_times': []}]
        merge_lineups(events)
        self.assertEqual(events[0]['lineup'], ['Fennesz', 'Max Cooper'])

    def test_dice_next_data_gives_full_lineup_and_times(self):
        state = {'event': {'lineup': [{'name': 'Anthony Rother', 'performing_time': None}, {'name': 'Fennesz', 'performing_time': '2026-11-06T23:30:00+01:00'}]}}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'initialState': json.dumps(state)}}}) + '</script>'
        names, times = page_lineup(page)
        self.assertEqual(names, ['Anthony Rother', 'Fennesz'])
        self.assertEqual(times, [{'name': 'Fennesz', 'time': '23:30', 'raw': '2026-11-06T23:30:00+01:00'}])


if __name__ == '__main__': unittest.main()
