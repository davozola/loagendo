"""Mejoras del motor tras la auditoría del 26-10-2026 (docs/revision/auditoria-2026-10-26.md)."""
import unittest

from mvp.catalog import single_session
from src import taxonomy as T
from src.guia_schedule import weekly_rows, schedule_by_day
from src.organizer_text import excerpt_paragraphs


class HorariosDeUnaLinea(unittest.TestCase):
    def test_un_unico_pase(self):
        self.assertEqual(single_session('A las 19.30 h'), '19:30')
        self.assertEqual(single_session('a les 20.00 h'), '20:00')

    def test_no_confunde_apertura_duracion_ni_varios_pases(self):
        for text in ('De 10.00 h a 19.00 h', 'Durada aproximada: 105 minuts', 'Obertura de portes a les 19 h',
                     'a les 18 h i a les 21 h', 'Horaris i preus segons establiment', '', "Dissabte i diumenge: a les 12 h"):
            self.assertEqual(single_session(text), '', text)

    def test_horario_semanal_en_una_linea(self):
        rows = weekly_rows('De jueves a sábado a las 19.00 h')
        self.assertEqual(schedule_by_day(rows, '2026-12-17', '2026-12-19'), {'2026-12-17': '19:00', '2026-12-18': '19:00', '2026-12-19': '19:00'})
        rows = weekly_rows('Divendres 30: 22.30 h Dissabte 31: 21 h Durada aproximada: 105 minuts')
        self.assertEqual(schedule_by_day(rows, '2026-10-30', '2026-10-31'), {'2026-10-30': '22:30', '2026-10-31': '21:00'})

    def test_separador_entre_filas(self):
        rows = weekly_rows('Dijous, divendres i dissabte: a les 20.00 h · Diumenge: a les 18 h')
        hours = schedule_by_day(rows, '2026-11-26', '2026-11-29')
        self.assertEqual(hours, {'2026-11-26': '20:00', '2026-11-27': '20:00', '2026-11-28': '20:00', '2026-11-29': '18:00'})


class CategoriaDeRecinto(unittest.TestCase):
    AI = {'model': 'm', 'confidence': 0.85}

    def test_la_categoria_del_recinto_se_marca(self):
        r = T._classify_rules({'source': 'web_teatre_lliure', 'title': 'LA Ludwig Band', 'category': 'Artes escénicas'})
        self.assertEqual((r['category'], r['method']), ('escena', 'categoria_recinto'))
        r = T._classify_rules({'source': 'opendatabcn_agenda', 'title': 'Algo', 'category': 'Artes escénicas'})
        self.assertEqual(r['method'], 'categoria_fuente')

    def test_ia_con_respaldo_del_acto(self):
        ev = {'source': 'web_teatre_lliure', 'title': 'LA Ludwig Band', 'category': 'Artes escénicas',
              'description': 'La Ludwig Band cerrará nuestro aniversario con un concierto de canciones de su último disco.'}
        out = T.classify(ev, None, {**self.AI, 'answer': 'musica', 'reason': 'concierto'})
        self.assertEqual((out['category'], out['method']), ('musica', 'ia_con_senal'))

    def test_ia_sin_respaldo_no_cambia(self):
        ev = {'source': 'web_auditori', 'title': 'Mañana musical para embarazadas', 'category': 'Música y vida nocturna', 'description': ''}
        out = T.classify(ev, None, {**self.AI, 'confidence': 0.9, 'answer': 'talleres', 'reason': 'taller'})
        self.assertEqual(out['category'], 'musica')
        self.assertTrue(out['ai_disagrees'])

    def test_ia_no_excluye_por_esta_via(self):
        ev = {'source': 'web_auditori', 'title': 'Canta Gran', 'category': 'Música y vida nocturna', 'description': 'Programa de canto para mayores.'}
        self.assertEqual(T.classify(ev, None, {**self.AI, 'answer': T.EXCLUDED, 'reason': 'x'})['category'], 'musica')

    def test_fuente_con_categoria_por_acto_no_cambia(self):
        ev = {'source': 'opendatabcn_agenda', 'title': 'Algo', 'category': 'Artes escénicas', 'description': 'Un concierto.'}
        self.assertEqual(T.classify(ev, None, {**self.AI, 'answer': 'musica', 'reason': 'x'})['category'], 'escena')


class TextosYaDescargados(unittest.TestCase):
    EXCERPT = ('Dublon - Sala Razzmatazz\nAgenda\nLa sala\nAceptar cookies y continuar navegando por nuestra web, que usa cookies propias y de terceros para todo.\n'
               'Mié.28.Oct.2026\nMayores de 16 años, o menores acompañados de su progenitor o su tutor legal con documento de autorización\n'
               'Jazz-house elegante, grooves cálidos y una sensibilidad que conecta tanto con amantes del jazz como con cabezas del house. Así suena dublon.\nDublon')

    def test_parrafos_del_acto(self):
        text = excerpt_paragraphs(self.EXCERPT, 'Dublon')
        self.assertTrue(text.startswith('Jazz-house elegante'))
        self.assertNotIn('cookies', text); self.assertNotIn('Mayores de 16', text)

    def test_texto_de_otro_acto_no_vale(self):
        self.assertEqual(excerpt_paragraphs(self.EXCERPT.replace('dublon', 'otro').replace('Dublon', 'Otro'), 'Merino all night long'), '')


if __name__ == '__main__':
    unittest.main()


class DuplicadosConCiclo(unittest.TestCase):
    def test_obra_entre_comillas_tras_el_ciclo(self):
        from src.dedupe import _title_keys
        self.assertIn('navegar por el neva', _title_keys('Flaix de Tardor: Teatre "Navegar por el Neva", a partir de "Neva", de Guillermo Calderón'))
        self.assertIn('requiem de mozart', _title_keys('Cicle Simfònics al Palau: Concert "Requiem de Mozart"'))

    def test_sin_comillas_tras_el_ciclo_no_inventa_clave(self):
        from src.dedupe import _title_keys
        keys = _title_keys('Cicle Coincidents: concert de tardor amb la banda')
        self.assertNotIn('tardor', keys)

    def test_title_pairs_exige_fechas_y_sitio(self):
        import sqlite3
        from src.dedupe import title_pairs
        conn = sqlite3.connect(':memory:')
        conn.executescript("""CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT);
            CREATE TABLE source_venues(source TEXT,id TEXT,seq INTEGER,venue TEXT,address TEXT,lat REAL,lon REAL);""")
        rows = [('guiabcn', '1', 'Flaix de Tardor: Teatre "Navegar por el Neva", a partir de "Neva"', '2099-10-27', '2099-10-29', 'Teatre Lliure - Sala Espai Lliure'),
                ('web_teatre_lliure', '2', 'NAVEGAR POR EL NEVA', '2099-10-27', '2099-10-29', 'MONTJUÏC. ESPAI LLIURE'),
                ('web_teatre_lliure', '3', 'NAVEGAR POR EL NEVA', '2099-11-27', '2099-11-29', 'MONTJUÏC. ESPAI LLIURE'),
                ('guiabcn', '4', 'Cicle X: Teatre "Navegar por el Neva"', '2099-10-27', '2099-10-29', 'Teatre Nacional de Catalunya')]
        for s, i, t, a, b, v in rows:
            conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?,'single','review','','','','{}')", (s, i, t, a, b))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',NULL,NULL)", (s, i, v))
        pairs = {frozenset(p) for p in title_pairs(conn)}
        self.assertIn(frozenset({'guiabcn:1', 'web_teatre_lliure:2'}), pairs)
        self.assertFalse(any('web_teatre_lliure:3' in p or 'guiabcn:4' in p for p in pairs))


class FormatoPorLaNaturalezaDelActo(unittest.TestCase):
    def test_la_duracion_sola_no_cambia_el_formato(self):
        from mvp.catalog import format_of
        self.assertEqual(format_of('single', 'NAVEGAR POR EL NEVA', '2026-10-27', '2026-10-29'), 'ongoing')

    def test_sesiones_confirmadas(self):
        from mvp.catalog import has_sessions
        self.assertTrue(has_sessions([{'date': '2026-10-27', 'time': '17:30'}], {}))
        self.assertTrue(has_sessions([], {'2026-10-27': '16:30–19:00'}))
        self.assertTrue(has_sessions([], {'2026-10-27': '18:00'}))
        self.assertFalse(has_sessions([], {'2026-10-27': '09:30–14:00'}))   # apertura, no sesión
        self.assertFalse(has_sessions([{'date': '2026-10-27', 'time': None}], {'2026-10-27': ''}))

    def test_una_sola_noche_solo_con_las_dos_horas(self):
        from mvp.catalog import night_only
        self.assertTrue(night_only({'item': {'startDate': '2026-10-29T23:59:00+01:00', 'endDate': '2026-10-30T05:00:00+01:00'}}))
        self.assertFalse(night_only({'item': {'startDate': '2026-10-31', 'endDate': '2026-11-01'}}))           # sin horas
        self.assertFalse(night_only({'item': {'startDate': '2026-11-06T17:30', 'endDate': '2026-11-08T02:00'}}))  # festival de 3 días
        self.assertFalse(night_only({'item': {'startDate': '2026-11-06T10:00', 'endDate': '2026-11-07T20:00'}}))

    def test_dias_sin_pase_en_ficha_corta(self):
        from mvp.catalog import short_dated
        e = {'start': '2026-10-27', 'end': '2026-10-28', 'occurrences': [{'date': '2026-10-27', 'time': '17:30'}]}
        self.assertTrue(short_dated(e))
        self.assertFalse(short_dated({**e, 'end': '2026-11-30'}))
        self.assertFalse(short_dated({**e, 'occurrences': []}))
        self.assertFalse(short_dated({**e, 'kind': 'exhibition'}))   # la inauguración no limita los días de la exposición


class AnuncioDeSalaSinArtista(unittest.TestCase):
    def test_no_se_une_a_otra_sala_cercana(self):
        import sqlite3
        from src.dedupe import act_pairs
        conn = sqlite3.connect(':memory:')
        conn.executescript("""CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT);
            CREATE TABLE source_venues(source TEXT,id TEXT,seq INTEGER,venue TEXT,address TEXT,lat REAL,lon REAL);""")
        rows = [('venue_songkick', '1', 'Jamboree Jazz', 'Jamboree Jazz Club', 41.3800, 2.1754),
                ('generalitat', '2', 'Gran Gala Flamenc', 'Palau de la Música Catalana', 41.3876, 2.1753),   # ~850 m
                ('venue_jamboree', '3', 'Yves Brouqui Quartet', 'Jamboree Jazz Club', 41.3800, 2.1754)]
        for s, i, t, v, la, lo in rows:
            conn.execute("INSERT INTO source_records VALUES(?,?,?,'2099-11-13','2099-11-13','single','review','','','','{}')", (s, i, t))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',?,?)", (s, i, v, la, lo))
        pairs = act_pairs(conn)
        self.assertIn(('venue_songkick:1', 'venue_jamboree:3'), pairs)
        self.assertNotIn(('venue_songkick:1', 'generalitat:2'), pairs)
