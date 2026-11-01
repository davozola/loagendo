"""Auditoría de las fichas del 6-11-2026 (1-11-2026, David): patrones corregidos.

1. Una ficha retirada por su fuente (agenda con IA desactivada, acto que ya no está en la página) no puede ser la
   canónica de su grupo: se llevaba con ella las sesiones buenas (64 de In-Edit desde Codetickets).
2. Edades: la de una tarifa o la de los artistas no es la edad del público.
3. Duplicados: artículos («L’Atlàntida» / «La Atlántida»), la obra entre comillas simples tras «Exposició», un lugar
   con dos nombres (Sidecar / Club Sauvage) y apertura de puertas frente a inicio (20:30 / 21:00).
"""
import json
import sqlite3
import unittest

from mvp.catalog import MULTI_SITE, clean, outside_city
from src import dedupe
from src.ai_extract import ages_by_rule
from src.publish_static import short_price


def _db():
    conn = sqlite3.connect(':memory:')
    conn.executescript("""CREATE TABLE source_records(source,id,title,start_date,end_date,kind,eligibility,raw_json);
        CREATE TABLE source_venues(source,id,seq,venue,lat,lon,address);
        CREATE TABLE candidate_occurrences(source,id,local_date,local_time);
        CREATE TABLE review_flags(source,id,issue);
        CREATE TABLE match_candidates(a,b,score,reason,generated_by,generated_at,evidence_json);""")
    return conn


def _record(conn, source, rid, title, day, eligibility='review', venue='MOOBY Aribau', time=None):
    conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?,'single',?,'{}')", (source, rid, title, day, day, eligibility))
    conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,NULL,NULL,'')", (source, rid, venue))
    if time: conn.execute("INSERT INTO candidate_occurrences VALUES(?,?,?,?)", (source, rid, day, time))


class RetiredCanonicalTests(unittest.TestCase):
    def test_retired_ai_record_does_not_take_the_codetickets_session_with_it(self):
        conn = _db()
        _record(conn, 'venue_ia_in_edit', 'old', 'Agridulce', '2099-11-06', eligibility='exclude')
        _record(conn, 'venue_in_edit_festival', 'new', 'Agridulce', '2099-11-06', time='18:15')
        conn.execute("INSERT INTO review_flags VALUES('venue_ia_in_edit','old','SUPERSEDED_BY_CODETICKETS')")
        conn.execute("INSERT INTO match_candidates VALUES('venue_ia_in_edit:old','venue_in_edit_festival:new',1.0,'TITLE_SIMILARITY_IS_NOT_IDENTITY','t','','{}')")
        groups = dedupe.canonical_groups(conn)
        self.assertEqual(groups.get('venue_ia_in_edit:old'), 'venue_in_edit_festival:new')
        self.assertNotIn('venue_in_edit_festival:new', groups)

    def test_cancelled_act_still_hides_its_twins(self):
        conn = _db()
        _record(conn, 'venue_ia_upload', 'x', 'CANCELADO: Geordie Greep', '2099-11-23', eligibility='exclude', venue='Sala Upload')
        _record(conn, 'venue_dice', 'y', 'Geordie Greep', '2099-11-23', venue='Sala Upload')
        conn.execute("INSERT INTO match_candidates VALUES('venue_dice:y','venue_ia_upload:x',1.0,'TITLE_SIMILARITY_IS_NOT_IDENTITY','t','','{}')")
        self.assertEqual(dedupe.canonical_groups(conn).get('venue_dice:y'), 'venue_ia_upload:x')

    def test_suspended_by_the_source_still_hides_its_twins(self):
        conn = _db()
        _record(conn, 'opendatabcn_agenda', '1', 'Taller "Glitch Cam"', '2099-11-10', eligibility='exclude', venue='Centre Cívic X')
        _record(conn, 'guiabcn', '1', 'Taller "Glitch Cam"', '2099-11-10', venue='Centre Cívic X')
        conn.execute("INSERT INTO review_flags VALUES('opendatabcn_agenda','1','EVENT_STATUS_SUSPENDED')")
        conn.execute("INSERT INTO match_candidates VALUES('guiabcn:1','opendatabcn_agenda:1',1.0,'TITLE_SIMILARITY_IS_NOT_IDENTITY','t','','{}')")
        self.assertEqual(dedupe.canonical_groups(conn).get('guiabcn:1'), 'opendatabcn_agenda:1')


class TitleKeyTests(unittest.TestCase):
    def test_articles_do_not_hide_the_same_work(self):
        self.assertEqual(dedupe._title_key('La Atlántida de Falla'), 'atlantida de falla')
        self.assertIn(' atlantida de falla ', ' %s ' % dedupe._title_key('L’Atlàntida de Falla, amb Kent Nagano i OCNE'))

    def test_quoted_work_after_exposicio_with_single_quotes(self):
        keys = dedupe._title_keys("Exposició 'Aigua freda', del Col·lectiu Pelussa")
        self.assertIn('aigua freda', keys)
        self.assertIn('viviendo a todo gas', dedupe._title_keys('Espectacle"Viviendo a todo gas", amb Pepi Labrador'))

    def test_straight_and_curly_apostrophes_are_the_same(self):
        self.assertEqual(dedupe._title_key("Exposició \"Enjoia't 2026\""), dedupe._title_key('Exposició "Enjoia’t 2026"'))


class SameDayTests(unittest.TestCase):
    def setUp(self):
        dedupe._PLACES['places'] = {'sidecar': ('Plaça Reial 7', 41.3805, 2.1752, 3), 'club sauvage': ('Plaça Reial 7', 41.3805, 2.1752, 3),
                                    'sauvage club': ('Plaça Reial 7', 41.3805, 2.1752, 3)}

    def tearDown(self):
        dedupe._PLACES['places'] = None

    def item(self, source, title, venue, times):
        return dedupe.same_day_item(source, title[:3], title, venue, None, None, times)

    def test_doors_and_show_at_the_same_hall_with_two_names(self):
        a = self.item('venue_sidecar', 'TAY OSKEE + Gabriel Kazz', 'Sidecar', '20:30')
        b = self.item('web_conciertos_club', 'Tay Oskee', 'Sauvage Club', '21:00')
        self.assertTrue(dedupe.same_day_match(a, b))

    def test_two_sessions_far_apart_stay_apart(self):
        a = self.item('venue_sidecar', 'TAY OSKEE + Gabriel Kazz', 'Sidecar', '18:00')
        b = self.item('web_conciertos_club', 'Tay Oskee', 'Sauvage Club', '21:00')
        self.assertFalse(dedupe.same_day_match(a, b))

    def test_doors_gap_needs_the_whole_short_title(self):
        a = self.item('venue_apolo', 'Camellos', 'Sala Apolo', '20:00')
        b = self.item('web_conciertos_club', 'Santero y Los Muchachos', 'Sala Apolo', '20:30')
        self.assertFalse(dedupe.same_day_match(a, b))


class AgeTests(unittest.TestCase):
    def test_reduced_price_bands_are_not_the_audience(self):
        text = "Entrada general: 5,2 €. Reduïda (caldrà acreditar la condició): 3,70 €. - Persones de 16 a 29 anys. - Persones de 65 anys o més."
        self.assertIsNone(ages_by_rule("Exposició 'Gaudí, orígens'", text))
        self.assertIsNone(ages_by_rule('Cicle de concerts "Friday Blues"', "Entrada general: 18 €. Entrada Menors de 4 a 10 anys + Concert: 8 €"))
        self.assertIsNone(ages_by_rule('Dinosaurium', "Entrada reduïda: de 12 a 18,50 € · Junior (4 a 12 anys) · Senior (+65)"))
        self.assertIsNone(ages_by_rule('Espais esportius', "Entrada gratuïta: nens fins a 7 anys, majors a partir de 65 anys"))

    def test_the_performers_age_is_not_the_audience(self):
        self.assertIsNone(ages_by_rule('Múltipla', "Fer, Nico y Marcos (guitarra, bajo y batería) tienen entre 19 y 21 años cuando dan su primer concierto"))

    def test_the_audience_age_survives(self):
        self.assertEqual(ages_by_rule('Contacontes', "Recomanat per a infants d'entre 1 i 8 anys.")[:2], (1, 8))
        self.assertEqual(ages_by_rule('Joc del Fantasma', "Activitat gratuïta amb aforament limitat per infants de 0 a 14 anys")[:2], (0, 14))
        self.assertEqual(ages_by_rule('Mou-te', "Activitat dirigida a joves de 16 a 35 anys. Gratuïta")[:2], (16, 35))
        self.assertEqual(ages_by_rule('Festa', "Entrada general: 8 € (preu de la gorra) · A partir de 3 anys")[:2], (3, None))
        self.assertEqual(ages_by_rule('Taller per a joves (15 a 18 anys)', '')[:2], (15, 18))


class ExhibitionTwinTests(unittest.TestCase):
    def _items(self, rows):
        conn = _db()
        for source, rid, title, a, b, venue in rows:
            conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?,'exhibition','review','{}')", (source, rid, title, a, b))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,41.3925,2.1620,'')", (source, rid, venue))
        return dedupe.exhibition_pairs(conn)

    def test_same_exhibition_two_subtitles_same_dates(self):
        pairs = self._items([('generalitat', 'a', 'Exposició "Pau Casals, un músic al servei de la pau"', '2099-10-21', '2100-01-10', 'Palau Robert'),
                             ('opendatabcn_agenda', 'b', 'Exposició "Pau Casals, música per la pau"', '2099-10-21', '2100-01-10', "Palau Robert · Sala d'Exposicions")])
        self.assertEqual(len(pairs), 1)

    def test_quoted_work_in_single_quotes(self):
        pairs = self._items([('opendatabcn_agenda', 'a', "Exposició 'Aigua freda', del Col·lectiu Pelussa", '2099-09-17', '2099-11-11', 'Centre Cívic Convent de Sant Agustí'),
                             ('web_graf', 'b', 'Aigua freda. Col·lectiu Pelussa (Mireia Garcia i Anna Llimós)', '2099-09-17', '2099-11-11', 'CC Convent de Sant Agustí')])
        self.assertEqual(len(pairs), 1)

    def test_two_different_shows_same_hall_same_dates_stay_apart(self):
        pairs = self._items([('generalitat', 'a', 'Exposició "Paisatges del Montseny"', '2099-10-01', '2099-12-01', 'Palau Robert'),
                             ('opendatabcn_agenda', 'b', 'Exposició "Retrats de Miró"', '2099-10-01', '2099-12-01', 'Palau Robert')])
        self.assertEqual(pairs, [])


class PriceTests(unittest.TestCase):
    def test_general_price_not_the_discount(self):
        self.assertEqual(short_price('Entrada general: 19 € · Entrada Reduïda: 16 € · Majors de 65'), [19.0, 0])
        self.assertEqual(short_price('Entrada general: 4.2 € · Amics i Amigues del Museu: 2,90 €'), [4.2, 0])

    def test_ranges_and_desde(self):
        self.assertEqual(short_price('Entrada general de: 25 a 45 € (+ despeses de gestió)'), [25.0, 1])
        self.assertEqual(short_price('Desde 22,49 €'), [22.49, 1])
        self.assertEqual(short_price('20.03 €'), [20.03, 0])

    def test_only_a_discount_gives_no_short_price(self):
        self.assertIsNone(short_price('Reduïda: 7 €'))


class PlaceTests(unittest.TestCase):
    def test_outside_barcelona(self):
        self.assertTrue(outside_city({'venue_names': ['Auditorio Nacional de Música de Madrid'], 'coordinates': None}))
        self.assertTrue(outside_city({'venue_names': ['Auditori de Girona'], 'coordinates': None}))
        self.assertTrue(outside_city({'venue_names': ["Cafè del Teatre de l'Escorxador de Lleida"], 'coordinates': {'lat': 41.61, 'lon': 0.61}}))

    def test_barcelona_places_named_after_cities(self):
        self.assertFalse(outside_city({'venue_names': ['Cinemes Girona'], 'coordinates': {'lat': 41.3996, 'lon': 2.1646}}))
        self.assertFalse(outside_city({'venue_names': ['Plaça Sant Joaquim i carrer de Septimània, entre els carrers de Vallirana i de Saragossa'], 'coordinates': None}))
        self.assertFalse(outside_city({'venue_names': ['Cinemes Girona'], 'coordinates': None}))

    def test_city_wide_programmes_are_not_one_place(self):
        for v in ('Activitats a diferents equipaments de la ciutat', 'Diferents indrets de la ciutat', 'Barcelona', 'Diversos espais del Poblenou'):
            self.assertTrue(MULTI_SITE.match(clean(v)), v)
        self.assertFalse(MULTI_SITE.match(clean('Casal de Barri Congrés-Indians')))



class DecisionesDavidTests(unittest.TestCase):
    """Decisiones del 1-11-2026 (08:17): 1) la general no sale el día que su sesión está a la misma hora y sitio;
    2) grupos estables de barrio y formación básica fuera de la Agenda; 3) By Invitation se queda en Expos (sin cambio)."""
    def test_general_hidden_the_day_of_its_session(self):
        from src.publish_static import covered_by_sessions
        g = {'key': 'generalitat:1', 'title': 'InScena', 'start': '2099-11-04', 'end': '2099-11-08', 'venue_names': ["Golem'S"],
             'coordinates': {'lat': 41.40608, 'lon': 2.16142}, 'occurrences': [{'date': '2099-11-06', 'time': '19:00'}], 'hours_by_day': {}}
        s = {'key': 'guiabcn:2', 'title': 'Festival de teatro italiano de Barcelona In Scena: Espectacle "Toska"', 'start': '2099-11-06', 'end': '2099-11-06',
             'venue_names': ["Teatre Golem's"], 'coordinates': {'lat': 41.40612, 'lon': 2.16142}, 'occurrences': [], 'hours_by_day': {}, 'time': '19:00'}
        self.assertEqual(covered_by_sessions([g, s]), {'generalitat:1': ['2099-11-06']})
        other = dict(s, time='21:00')
        self.assertEqual(covered_by_sessions([g, other]), {})
        elsewhere = dict(s, venue_names=['Teatre Lliure'], coordinates={'lat': 41.37, 'lon': 2.16})
        self.assertEqual(covered_by_sessions([g, elsewhere]), {})

    def test_stable_groups_and_basic_skills_leave_the_agenda(self):
        from src.taxonomy import participation_exclusion
        base = {'start': '2099-09-18', 'end': '2099-12-18', 'kind': 'program', 'format': 'program'}
        teatre = dict(base, title="Trobada 'Teatre Il·lusió'", summary="Grup obert i autogestionat de veïns i veïnes del barri que es reuneixen per assajar textos.")
        self.assertEqual(participation_exclusion(teatre, 'charlas')['method'], 'grupo_o_servicio_estable')
        self.assertEqual(participation_exclusion(dict(base, title='Club de costura creativa'), 'charlas')['method'], 'grupo_o_servicio_estable')
        self.assertEqual(participation_exclusion(dict(base, title="Taller 'Lectoescriptura en català'"), 'talleres')['method'], 'formacion_basica')

    def test_a_show_by_a_group_stays(self):
        from src.taxonomy import participation_exclusion
        show = {'start': '2099-11-01', 'end': '2099-11-30', 'kind': 'program', 'format': 'program', 'title': 'Teatre "La casa de Bernarda Alba"',
                'summary': 'El grup obert de teatre del casal presenta la seva nova obra.'}
        self.assertIsNone(participation_exclusion(show, 'escena'))


if __name__ == '__main__':
    unittest.main()
