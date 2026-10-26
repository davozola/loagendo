"""Festivales y eventos paraguas (src/festivals.py, 21-10-2026)."""
import json
import unittest

from src.festivals import Festivals, load
from src.venue_feeds import wp_openhouse_nodes, record_from_jsonld


class FestivalTests(unittest.TestCase):
    def setUp(self):
        titles = ['58è Festival Internacional de Jazz de Barcelona: Concert "A"', '58è Festival Internacional de Jazz de Barcelona: Concert "B"',
                  '58è Festival Internacional de Jazz de Barcelona: Concert "C"', '"Festa Major del Clot - Camp de l\'Arpa": Fira d\'artesans',
                  '"Festa Major del Clot - Camp de l\'Arpa": Ballada', '"Festa Major del Clot - Camp de l\'Arpa": Correfoc']
        self.f = Festivals(titles, config=load())

    def test_children_and_umbrellas(self):
        child = self.f.of('Festival d\'Arquitectura "48h Open House BCN": Visita al Mercat de Sagrada Família')
        self.assertEqual((child['slug'], child['umbrella']), ('48h-open-house-bcn', False))
        self.assertTrue(self.f.of('Festival 48h Open House BCN', venue='Diferents espais')['umbrella'])
        self.assertTrue(self.f.of('Festival d\'Arquitectura "48h Open House BCN". Cap de setmana de visites', venue='Diferents edificis')['umbrella'])
        self.assertFalse(self.f.of('48 H OPEN HOUSE | Visita a la Casa Bloc', venue='Disseny Hub Barcelona')['umbrella'])
        self.assertEqual(self.f.of('"Festa Major del Clot - Camp de l\'Arpa": Jamaiclot VI')['name'], "Festa Major del Clot - Camp de l'Arpa")
        self.assertFalse(self.f.of('58è Festival Internacional de Jazz de Barcelona: Concert "D"')['umbrella'])
        self.assertIsNone(self.f.of("Exposició 'Pau Casals a Puerto Rico. Un arxiu inèdit'"))

    def test_open_house_programme(self):
        items = [{"title": {"rendered": "MONESTIR DE SANT PERE"}, "link": "https://x/es/els-edificis/m/", "content": {"rendered": "<p>Text</p>"},
                  "class_list": ["obert_per-sabado-manana", "obert_per-sabado-tarde", "obert_per-domingo-manana", "zones-barcelona-es", "zones-sarria-sant-gervasi-es"]},
                 {"title": {"rendered": "Edifici de Sitges"}, "link": "https://x/s/", "class_list": ["obert_per-sabado-manana", "zones-sitges-es"]}]
        v = {'slug': 'openhouse_bcn', 'name': '48h Open House BCN', 'type': 'festival',
             'feed': {'url': 'https://x/api', 'zona': 'barcelona-es', 'dias': {'sabado': '2026-10-24', 'domingo': '2026-10-25'}, 'festival': {'slug': 'f', 'name': 'F'}}}
        nodes, _ = wp_openhouse_nodes(v, lambda u, t: (200, u, json.dumps(items)))
        self.assertEqual(len(nodes), 1)
        node = nodes[0][1]
        self.assertEqual((node['name'], node['x_parts'], node['x_district']), ('Monestir de Sant Pere', {'2026-10-24': 'mañana y tarde', '2026-10-25': 'mañana'}, 'Sarrià-Sant Gervasi'))
        r = record_from_jsonld(v, node, nodes[0][0])
        self.assertEqual((r['start'], r['end']), ('2026-10-24', '2026-10-25'))


if __name__ == '__main__':
    unittest.main()


class TribeRestTests(unittest.TestCase):
    def test_events_calendar_api(self):
        import datetime as dt
        from src.venue_feeds import tribe_rest_nodes
        data = {"total_pages": 1, "events": [
            {"title": "AR-DE", "url": "https://p/ar-de", "start_date": "2026-10-23 00:00:00", "end_date": "2026-10-25 23:59:59", "all_day": True, "venue": []},
            {"title": "Piramidón: Teresa Camacho &#8211; Punt i Coma", "url": "https://p/x", "start_date": "2026-09-18 13:57:00", "end_date": "2026-11-17 13:57:00", "venue": {"venue": "Piramidón", "city": "Barcelona"}},
            {"title": "URBAN TALKS", "url": "https://p/u", "start_date": "2026-10-24 11:00:00", "end_date": "2026-10-24 19:00:00", "venue": {"venue": "Museu del Disseny"}},
            {"title": "Vell", "url": "https://p/v", "start_date": "2026-01-01 10:00:00", "end_date": "2026-01-02 10:00:00"}]}
        v = {'slug': 'pud', 'name': 'Poblenou Urban District', 'type': 'culture', 'feed': {'url': 'x', 'lugar': 'Diversos espais del Poblenou'}}
        recs = [record_from_jsonld(v, n, u) for u, n in tribe_rest_nodes(v, lambda u, t: (200, u, json.dumps(data)), today=dt.date(2026, 10, 21))[0]]
        self.assertEqual([(r['title'], r['start'], r['time_text'], r['venues'][0]['name']) for r in recs],
                         [('AR-DE', '2026-10-23', '', 'Diversos espais del Poblenou'), ('Piramidón: Teresa Camacho – Punt i Coma', '2026-09-18', '', 'Piramidón'),
                          ('URBAN TALKS', '2026-10-24', '11:00', 'Museu del Disseny')])


class CriterioTests(unittest.TestCase):
    """Criterio del 25-10-2026: unir ficha general y actividades, desde 2, fuera lo que no es festival."""
    def setUp(self):
        recs = [('25è Festival de Creació Contemporània "Escena Poblenou": Teatre "Torcidxs"', '2026-10-24', '2026-11-08'),
                ('25è Festival de Creació Contemporània "Escena Poblenou": Espectacle "Clam"', '2026-10-25', '2026-10-25'),
                ('25è Festival de Creació Contemporània "Escena Poblenou": Espectacle "Imagiro"', '2026-10-25', '2026-10-25'),
                ('Festival Escena Poblenou 2026', '2026-10-22', '2026-10-25'),
                ('Festival "Flaix de tardor - BCN": Teatre "Petróleo"', '2026-10-26', '2026-10-27'),
                ('Festival "Flaix de tardor - BCN": Espectacle "Šventoji"', '2026-10-28', '2026-10-29'),
                ('Caps de setmana singulars: Visita guiada a la Casa Rocamora', '2026-10-04', '2027-01-09'),
                ('Caps de setmana singulars: Visita guiada a la Casa Llotja', '2026-10-04', '2027-01-09'),
                ('CLOSA SELECTS w/ MRAK - Halloween [Balla Festival]', '2026-10-30', '2026-10-30'),
                ('Throwback Open Air Halloween [Balla Festival]', '2026-10-31', '2026-10-31'),
                ('Balla Barcelona Festival', '2026-10-30', '2026-10-31'),
                ('"Festa Major del Clot - Camp de l\'Arpa": Ballada', '2026-11-01', '2026-11-01'),
                ('"Festa Major del Clot - Camp de l\'Arpa": Correfoc', '2026-11-02', '2026-11-02')]
        self.f = Festivals(recs, config=load())

    def test_ficha_general_se_une(self):
        child = self.f.of('25è Festival de Creació Contemporània "Escena Poblenou": Espectacle "Clam"')
        umb = self.f.of('Festival Escena Poblenou 2026', start='2026-10-22', end='2026-10-25')
        self.assertEqual(child['slug'], umb['slug']); self.assertTrue(umb['umbrella']); self.assertFalse(child['umbrella'])
        self.assertEqual(self.f.of('Balla Barcelona Festival')['slug'], self.f.of('Throwback Open Air Halloween [Balla Festival]')['slug'])

    def test_desde_dos_y_exclusiones(self):
        self.assertIsNotNone(self.f.of('Festival "Flaix de tardor - BCN": Teatre "Petróleo"'))
        self.assertIsNone(self.f.of('Caps de setmana singulars: Visita guiada a la Casa Rocamora'))
        self.assertIsNone(self.f.of("Taller 'Bombolles per a les Festes!'"))
        self.assertIsNone(self.f.of('Budapest Festival Orchestra & fischer - Simfonia núm. 9', start='2027-04-08', end='2027-04-08'))

    def test_ficha_general_sola_y_fiestas(self):
        moz = self.f.of('Mozilla Festival', start='2026-10-28', end='2026-10-30')
        self.assertTrue(moz['umbrella']); self.assertEqual(moz['kind'], 'festival')
        self.assertIsNone(self.f.of('Festival "Grunge Is Not Dead XXL"', start='2026-11-07', end='2026-11-07'))  # una noche
        a, b = self.f.of('Asian Film Festival Barcelona', start='2026-10-22', end='2026-11-01'), self.f.of('14è Asian Film Festival Barcelona', start='2026-10-22', end='2026-11-01')
        self.assertEqual(a['slug'], b['slug'])
        self.assertEqual(self.f.of('"Festa Major del Clot - Camp de l\'Arpa": Ballada')['kind'], 'fiesta')

    def test_mira_week(self):
        self.assertEqual(self.f.of('MIRA WEEK: MIRA.exe')['slug'], 'mira-festival')


class SimplificacionTests(unittest.TestCase):
    """26-10-2026: un acto de un día no es ficha general; horas a mano por día, sin extrapolar."""
    def test_acto_de_un_dia_no_es_ficha_general(self):
        f = Festivals([], config=load())
        self.assertIsNone(f.of('49è Correfoc de Festa Major', start='2026-11-14', end='2026-11-14'))
        self.assertTrue(f.of('Festival Feroe 2026', start='2026-11-13', end='2026-11-14')['umbrella'])

    def test_horas_a_mano(self):
        import tempfile
        from pathlib import Path
        from src.festivals import manual_hours
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'h.json'
            p.write_text(json.dumps({'horarios': [{'ficha': 'guiabcn:1', 'dias': {'2026-10-29': '17:00', 'mal': '9'}, 'tipo': 'primera sesión', 'fuente': 'https://x'}]}))
            self.assertEqual(manual_hours(p), {'guiabcn:1': {'2026-10-29': {'time': '17:00', 'kind': 'primera', 'source': 'https://x'}}})
