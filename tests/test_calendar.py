"""Añadir al calendario (22-10-2026): el hueco de cada día sale solo de lo que publica la fuente."""
import datetime as dt
import unittest

from src.publish_static import _slot, calendar_days, packed_calendar, share_card

TODAY = dt.date(2026, 10, 22)


class SlotTest(unittest.TestCase):
    def test_published_range(self):
        self.assertEqual(_slot('19:00–21:00'), '19:00-21:00')
        self.assertEqual(_slot('22:00–03:00'), '22:00-03:00')  # pasa la medianoche: lo resuelve la función

    def test_start_only_has_no_invented_end(self):
        self.assertEqual(_slot('20:30'), '20:30')
        self.assertEqual(_slot('a las 20:30h'), '20:30')

    def test_several_sessions_are_all_day_with_the_times(self):
        self.assertEqual(_slot('19:00 · 21:00'), 'S19:00,21:00')

    def test_no_time_is_all_day(self):
        self.assertEqual(_slot(''), '')
        self.assertEqual(_slot('mañana'), '')
        self.assertEqual(_slot('Entrada 12.50 €'), '')  # un precio no es una hora

    def test_range_only_if_it_matches_the_session(self):
        self.assertEqual(_slot('19:00–21:00', ['19:00']), '19:00-21:00')
        self.assertEqual(_slot('19:00–21:00', ['20:00']), '20:00')


class CalendarDaysTest(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(calendar_days({'start': '2026-10-23', 'end': '2026-10-23', 'time': '19:00', 'time_label': '19:00–21:00'}, TODAY), {'2026-10-23': '19:00-21:00'})
        self.assertEqual(calendar_days({'start': '2026-10-23', 'end': '2026-10-23', 'time_label': 'Hora no indicada'}, TODAY), {'2026-10-23': ''})

    def test_dated_sessions_decide_the_days(self):
        e = {'start': '2026-10-23', 'end': '2026-10-30', 'time_label': 'Varios días',
             'occurrences': [{'date': '2026-10-23', 'time': '18:00'}, {'date': '2026-10-23', 'time': '20:30'}, {'date': '2026-10-25', 'time': '18:00'}]}
        self.assertEqual(calendar_days(e, TODAY), {'2026-10-23': 'S18:00,20:30', '2026-10-25': '18:00'})

    def test_official_hours_by_day(self):
        e = {'start': '2026-10-01', 'end': '2026-11-30', 'hours_by_day': {'2026-10-20': '10:00–20:00', '2026-10-23': '10:00–20:00', '2026-10-24': ''}}
        self.assertEqual(calendar_days(e, TODAY), {'2026-10-23': '10:00-20:00', '2026-10-24': ''})  # el 20 ya pasó

    def test_exhibition_without_hours_is_all_day_from_today(self):
        days = calendar_days({'start': '2026-09-01', 'end': '2026-10-25', 'time_label': 'Exposición'}, TODAY)
        self.assertEqual(list(days), ['2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25'])
        self.assertEqual(set(days.values()), {''})

    def test_past_event_has_no_days(self):
        self.assertEqual(calendar_days({'start': '2026-10-01', 'end': '2026-10-02'}, TODAY), {})

    def test_packed_runs(self):
        self.assertEqual(packed_calendar({'start': '2026-09-01', 'end': '2026-12-26', 'time_label': 'Exposición'}, TODAY), {'': [[51, 116]]})
        e = {'start': '2026-10-01', 'end': '2026-11-26', 'hours_by_day': {'2026-10-23': '10:00–20:00', '2026-10-24': '10:00–20:00', '2026-10-25': '', '2026-10-26': '10:00–20:00'}}
        self.assertEqual(packed_calendar(e, TODAY), {'10:00-20:00': [[22, 23], 25], '': [24]})

    def test_share_card_carries_calendar_and_official_link(self):
        card = share_card({'title': 'Concierto', 'start': '2026-10-23', 'end': '2026-10-23', 'time': '21:00', 'time_label': '21:00',
                           'official_page': {'url': 'https://www.sala-apolo.com/x'}}, TODAY)
        self.assertEqual(card['k'], {'21:00': [0]})
        self.assertEqual(card['o'], 'https://www.sala-apolo.com/x')
        self.assertEqual(share_card({'title': 'X', 'start': '2026-10-23', 'end': '2026-10-23', 'official_page': {'url': 'http://inseguro'}}, TODAY)['o'], '')


if __name__ == '__main__':
    unittest.main()
