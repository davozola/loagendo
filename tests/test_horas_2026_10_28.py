"""Recuperación de horas (28-10-2026, David, tras la auditoría de actividades sin hora)."""
import datetime as dt
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 28)


class AgendaIATests(unittest.TestCase):
    def test_numeros_de_elementos_distintos_no_se_pegan(self):
        from src import ai_agenda
        text, _ = ai_agenda.clean('<div><span>02/11/2026</span><span>19:00 h</span></div><p><b>B</b>arcelona</p>', 'https://x.test/')
        self.assertIn('02/11/2026 19:00 h', text); self.assertIn('Barcelona', text)

    def test_hora_pegada_a_la_fecha_y_enlace_del_acto(self):
        from src import ai_agenda
        html = ('<a href="/cinema/films/animals-bestials/"><h2>Animals bestials</h2><div>Ds 7.11.26 <span>(17:00)</span></div></a>'
                '<a href="/cinema/films/krakatoa/"><h2>Krakatoa</h2><div>Carlos Casas</div><div>Ds 7.11.26 <span>(19:00)</span>*</div></a>')
        text, links = ai_agenda.clean(html, 'https://zumzeigcine.coop/cinema/sessions/')
        act, why = ai_agenda.verify({'titulo': 'Krakatoa', 'enlace': 'L1', 'sesiones': [{'fecha': '2026-11-07', 'cita_fecha': 'Ds 7.11.26'}]}, text, links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '19:00')])
        self.assertEqual(act['url'], 'https://zumzeigcine.coop/cinema/films/krakatoa/')
        self.assertIn('(19:00)', act['quotes']['time'])

    def test_hora_equivocada_de_la_ia_no_se_sustituye(self):
        from src import ai_agenda
        text, links = ai_agenda.clean('<p>Krakatoa</p><p>Ds 7.11.26 (19:00)</p>', 'https://x.test/')
        act, _ = ai_agenda.verify({'titulo': 'Krakatoa', 'sesiones': [{'fecha': '2026-11-07', 'cita_fecha': 'Ds 7.11.26', 'hora': '21:00', 'cita_hora': '21:00'}]}, text, links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '')])


class PaginaDelActoTests(unittest.TestCase):
    def page(self, body, title):
        return lambda u, t: (200, u, f'<html><title>{title}</title><body>{body}</body></html>')

    def test_una_franja_y_madrugada(self):
        from src.official_dates import read_page
        f = self.page('<h1>THE UPSESSIONS</h1><p>00</p><p>hores</p><p>Data</p><p>20:00 - 23:30</p>', 'THE UPSESSIONS')
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-25', '2026-11-25', f, 5)['times'], {'2026-11-25': '20:00'})
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-13', '2026-11-14', f, 5)['times'], {'2026-11-13': '20:00'})
        f2 = self.page('<h1>THE UPSESSIONS</h1><p>Portes 19:00</p><p>20:00 - 23:30</p>', 'THE UPSESSIONS')
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-25', '2026-11-25', f2, 5)['times'], {})

    def test_horaris_tras_la_sinopsis_y_excepciones(self):
        from src.official_dates import read_page
        from src.guia_schedule import labeled_schedule
        f = self.page('<h1>Guillermotta</h1><p>' + 'sinopsi ' * 400 + '</p><p>HORARIS:</p><p>Dilluns a les 20h</p><p>(9 de novembre no hi ha funció)</p>', 'Guillermotta')
        ex = read_page('https://elmalda.cat/espectacle/guillermotta-5/', 'Guillermotta', '2026-10-19', '2026-11-23', f, 5)['excerpt']
        self.assertEqual(sorted(labeled_schedule(ex, '2026-10-19', '2026-11-23')), ['2026-10-19', '2026-10-26', '2026-11-02', '2026-11-16', '2026-11-23'])
        self.assertEqual(labeled_schedule("X\nHORARIS:\nDilluns a les 20h\nExcepte festius", '2026-10-19', '2026-11-23'), {})
        self.assertEqual(labeled_schedule("X\nHORARIS:\nDe dimarts a dissabte a les 20h.\nDiumenge a les 12h.", '2026-11-01', '2026-11-03'),
                         {'2026-11-01': '12:00', '2026-11-03': '20:00'})


class HigieneTests(unittest.TestCase):
    def test_prueba_y_fuera_de_barcelona(self):
        from src.taxonomy import hygiene_exclusion
        self.assertEqual(hygiene_exclusion({'title': 'Test 11068686 case', 'source': 'venue_ticketmaster_es'})['method'], 'ficha_de_prueba')
        self.assertEqual(hygiene_exclusion({'title': 'Castanyada Rock 2026', 'source': 'venue_songkick', 'venue_names': ['Montmeló, Spain']})['method'], 'fuera_de_barcelona')
        self.assertIsNone(hygiene_exclusion({'title': 'Allie X', 'source': 'venue_songkick', 'venue_names': ['La Nau']}))
        self.assertIsNone(hygiene_exclusion({'title': 'Testament en concert', 'source': 'venue_dice'}))

    def test_dj_repetido_de_songkick(self):
        from src.publish_static import songkick_repeats
        ev = lambda k, t, v, time=None: {'key': k, 'source': 'venue_songkick', 'title': t, 'venue_names': [v], 'occurrences': [{'date': '2026-11-03', 'time': time}], 'time': time}
        events = [ev('a', 'Hal9000', 'Jamboree'), ev('b', 'Hal9000', 'Safari'), ev('c', 'Hal9000', 'Arena'), ev('d', 'Hal9000', 'Monumental', '23:00'), ev('e', 'Allie X', 'La Nau')]
        self.assertEqual(songkick_repeats(events), {'a', 'b', 'c'})


class WebTests(unittest.TestCase):
    def test_horario_amplio_por_el_titulo_no_por_el_recinto(self):
        js = (ROOT / 'static' / 'public.js').read_text()
        self.assertNotIn('WIDE_SKIP_VENUE', js); self.assertIn("const WIDE_EVENT_WORD = ", js)
        self.assertNotIn("e.format !== 'course' && e.format !== 'workshop' && isDayPlan", js)

    def test_conflicto_resuelto_por_la_sala(self):
        src = (ROOT / 'mvp' / 'catalog.py').read_text()
        self.assertIn("same=lambda t:'00:00' if t=='23:59' else t", src); self.assertIn("o['evidence_field']='sala'", src)
