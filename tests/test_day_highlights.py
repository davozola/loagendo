import unittest
from src.publish_static import day_highlights


def ev(i, **kw):
    e = {'key': f's:{i}', 'source': 's', 'id': str(i), 'title': f'Acto {i}', 'start': '2026-10-24', 'end': '2026-10-24',
         'kind': 'event', 'format': 'one_shot', 'time': '20:00', 'occurrences': [], 'media': [{'url': 'x'}],
         'has_description': True, 'venue_names': [f'Sala {i}'], 'coordinates': [41.4, 2.1], 'eligibility': 'include'}
    e.update(kw); return e


class DayHighlights(unittest.TestCase):
    def test_reglas(self):
        items = [ev(1), ev(2, time=None), ev(3, kind='exhibition'), ev(4, eligibility='exclude'),
                 ev(5, title='Acto 1'), ev(6, media=[], has_description=False, venue_names=[], coordinates=None, format='program')]
        got = day_highlights(items, '2026-10-24')
        self.assertEqual(got, ['s:1'])  # sin hora, exposición, excluido, misma obra y puntuación baja fuera

    def test_tamano(self):
        items = [ev(i) for i in range(100)]
        self.assertEqual(len(day_highlights(items, '2026-10-24', size=40)), 40)

    def test_dia_de_la_sesion(self):
        e = ev(7, end='2026-10-30', occurrences=[{'date': '2026-10-25', 'time': '20:00'}])
        self.assertEqual(day_highlights([e], '2026-10-24'), [])


if __name__ == '__main__': unittest.main()
