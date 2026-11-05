"""Radar semanal de música con Mood (2-11-2026, src/radar_mood.py): solo informe, sin red en las pruebas."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import radar_mood


def page(*events):
    graph = [{'@type': 'MusicEvent', 'name': n, 'startDate': s, 'location': {'@type': 'Place', 'name': v}, 'performer': [{'name': p} for p in perf]} for n, s, v, perf in events]
    return '<html><script type="application/ld+json">%s</script></html>' % json.dumps({'@context': 'https://schema.org', '@graph': graph})


DAY = dt.date(2026, 11, 2)
MOOD = {f'{radar_mood.BASE}/date/2026-11-05': page(('Mouse on Mars', '2026-11-05T19:30:00+01:00', 'Sala Apolo', ['Mouse On Mars']),
                                                   ('Tardeo +40', '2026-11-05T19:00:00+01:00', 'Otto Zutz Club', []),
                                                   ('Candlelight: Rock Clásico en Cuerdas', '2026-11-05T19:00:00+01:00', 'Paraninfo', [])),
        f'{radar_mood.BASE}/date/2026-11-09': page(('Sigur Rós', '2026-11-09T21:00:00+01:00', 'Auditori Fòrum CCIB', ['Sigur Rós']),
                                                   ('23flamenco Live Flamenco', '2026-11-09T20:00:00+01:00', '23 Robadors', ['David de la Rambla']),
                                                   ('Oscar Sánchez: Caguamaconda', '2026-11-09T22:00:00+01:00', '23 Robadors', ['Oscar Sánchez']))}
OURS = [{'source': 'venue_sala_apolo', 'id': '1', 'key': 'venue_sala_apolo:1', 'title': 'Presentación Sistema de Sonido Inmersivo: Mouse On Mars Live!', 'start': '2026-11-05',
         'end': '2026-11-05', 'occurrences': [{'date': '2026-11-05', 'time': '19:30'}], 'eligibility': 'review', 'status': None, 'public_category': 'musica', 'venue_names': ['Sala Apolo']}]


class RadarTests(unittest.TestCase):
    def test_cuenta_lo_que_falta_por_sala_y_aparta_ocio_y_turismo(self):
        fetcher = lambda url, timeout=25: (200, url, MOOD.get(url, '<html></html>'))
        with tempfile.TemporaryDirectory() as folder:
            out = radar_mood.run(None, {'dias': 14}, fetcher=fetcher, today=DAY, out=folder, events=OURS)
            self.assertEqual((out['mood_events'], out['we_have'], out['missing']), (6, 1, 5))   # Mouse on Mars ya lo tenemos
            self.assertEqual(out['by_kind'], {'musica': 3, 'ocio_nocturno': 1, 'turistico': 1})
            self.assertEqual(out['top_venues'][:2], ['23 Robadors (2)', 'Auditori Fòrum CCIB (1)'])
            md = (Path(folder) / 'mood-2026-11-02.md').read_text(encoding='utf-8')
            self.assertIn('Sigur Rós', md); self.assertNotIn('Tardeo', md.split('## Todos')[1])   # el ocio nocturno no entra en la lista de conciertos
            self.assertEqual(radar_mood.latest(dt.date(2026, 11, 5), folder)['we_have'], 1)
            self.assertIsNone(radar_mood.latest(dt.date(2026, 11, 20), folder))   # más de 7 días: no sale en el parte

    def test_sin_respuesta_de_mood_falla_sin_escribir(self):
        with tempfile.TemporaryDirectory() as folder:
            out = radar_mood.run(None, {}, fetcher=lambda url, timeout=25: (403, url, ''), today=DAY, out=folder, events=OURS)
            self.assertEqual(out['status'], 'failed'); self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
