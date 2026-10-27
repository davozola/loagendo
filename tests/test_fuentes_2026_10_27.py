"""Recuperación de fuentes (27-10-2026): actos anulados o solo para socios, página que se queda sin actos,
JSON-LD con apóstrofos escapados al estilo PHP y agendas configuradas."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import ai_agenda
from src.venue_feeds import jsonld_events
from tests.test_ai_agenda import AGENDA, GOOD, TODAY, answer, fetcher

PAGE = """<html><body>
<div><h3>[Acte ajornat] Presentació de 'Història de la filosofia política'</h3><p>Dimarts 27 d'octubre de 2026 - 18:30 h</p></div>
<div><h3>La congelació d'òvuls i el descens de natalitat</h3><p>Exclusiu per a socis</p><p>Dimarts 27 d'octubre de 2026 - 18:30 h</p></div>
<div><h3>La vida secreta del cervell multilingüe</h3><p>Dijous 29 d'octubre de 2026 - 18:30 h</p></div>
</body></html>"""


class AnuladosYSocios(unittest.TestCase):
    def test_solo_el_acto_publico(self):
        text, links = ai_agenda.clean(PAGE, 'https://ateneu.test/')
        item = lambda t, d, q: {'titulo': t, 'sesiones': [{'fecha': d, 'cita_fecha': q}]}
        anulado = ai_agenda.verify(item("[Acte ajornat] Presentació de 'Història de la filosofia política'", '2026-10-27', "Dimarts 27 d'octubre"), text, links, TODAY)
        socios = ai_agenda.verify(item("La congelació d'òvuls i el descens de natalitat", '2026-10-27', "Dimarts 27 d'octubre"), text, links, TODAY)
        publico = ai_agenda.verify(item('La vida secreta del cervell multilingüe', '2026-10-29', "Dijous 29 d'octubre"), text, links, TODAY)
        self.assertIsNone(anulado[0]); self.assertIn('anulado', anulado[1][0])
        self.assertIsNone(socios[0]); self.assertIn('socios', socios[1][0])
        self.assertEqual(publico[0]['sesiones'], [('2026-10-29', '')])


class PaginaSinActos(unittest.TestCase):
    def test_web_caida_no_borra_y_falla(self):
        from mvp import catalog
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            first = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=fetcher, requester=answer(GOOD))
            self.assertEqual(first['rows_received'], 3)
            down = lambda url, timeout: (200, url, '<p>El web està temporalment fora de servei per tasques de manteniment.</p>')
            out = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=down, requester=answer([]))
            self.assertEqual(out['status'], 'failed'); self.assertIn('no trae ningún acto', out['error'])
            alive = conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_ia_prova' AND eligibility<>'exclude'").fetchone()[0]
            self.assertEqual(alive, 3)

    def test_sala_pequena_sin_programacion_no_es_fallo(self):
        from mvp import catalog
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            empty = lambda url, timeout: (200, url, '<p>No hi ha esdeveniments pròxims.</p>')
            out = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=empty, requester=answer([]))
            self.assertEqual(out['status'], 'completed')


class JsonLdConApostrofos(unittest.TestCase):
    def test_apostrofo_escapado(self):
        page = '<script type="application/ld+json">{"@type": "Event", "name": "SCREAMIN MEEMIES", "startDate": "2026-10-30", "description": "amb SCREAMIN\\\' MEEMIES"}</script>'
        self.assertEqual([e['name'] for e in jsonld_events(page)], ['SCREAMIN MEEMIES'])
        self.assertEqual(jsonld_events('<script type="application/ld+json">{"@type": "Event", "name": "X", "startDate": "2026-10-30",}</script>'), [])


class Configuracion(unittest.TestCase):
    def test_agendas(self):
        agendas = {a['slug']: a for a in json.loads(Path('config/agendas_ia.json').read_text(encoding='utf-8'))['agendas']}
        self.assertEqual(agendas['zumzeig']['urls'], ['https://zumzeigcine.coop/cinema/sessions/'])
        self.assertNotIn('calendari', agendas['el_malda']['urls'][0])
        for slug in ('23robadors', 'deskomunal', 'la_caldera', 'documenta', 'cinema_malda'):
            self.assertTrue(agendas[slug]['address'] and agendas[slug]['urls'])


if __name__ == '__main__':
    unittest.main()


class RespuestaDeIASobreTituloArreglado(unittest.TestCase):
    def test_titulo_de_la_fuente_y_respuestas_anteriores(self):
        from unittest import mock
        from src import ai_assist
        raw = {'title': 'MEMORIAL JOAQUIM SERRA 2026', 'source_venue': 'Casino', 'category': 'Comunidad y encuentros', 'format': 'program', 'summary': 'Cobles'}
        final = {**raw, 'source_title': raw['title'], 'title': 'Memorial Joaquim Serra 2026'}
        self.assertEqual(ai_assist.category_payload(raw), ai_assist.category_payload(final))   # candidatos y clasificación ven lo mismo
        old = ai_assist._hash(ai_assist._legacy_category_payload(final))                         # respuesta dada con el título arreglado
        s = {('categoria', 'k'): {'answer': 'musica', 'confidence': 0.85, 'input_hash': old, 'prompt_version': ai_assist.prompt_version('categoria')}}
        with mock.patch.object(ai_assist, 'suggestions', return_value=s):
            self.assertEqual(ai_assist.category_for(None, 'k', raw)['answer'], 'musica')

    def test_sin_resumen_usa_la_descripcion(self):
        from src import ai_assist
        self.assertEqual(ai_assist.category_payload({'title': 'Bivac 2026', 'description': 'Festival de pensament jove'})['extracto'], 'Festival de pensament jove')


class EspaciosDeArteParaExpos(unittest.TestCase):
    def test_lista(self):
        from src.venue_prestige import art_space
        for name in ('Disseny Hub Barcelona', 'Fundació Privada Foto Colectania', 'àngels barcelona', 'Galeria H2O', 'KBr - Fundación Mapfre'):
            self.assertTrue(art_space([name]), name)
        for name in ('Casal  Mas Guinardó', 'MOCO Museum', 'Centre Cívic Navas', 'Casa Amatller'):
            self.assertFalse(art_space([name]), name)

    def test_expo_rank_admite_galeria(self):
        from src.publish_static import expo_rank
        ev = {'key': 'g', 'source': 'web_graf', 'id': 'g', 'kind': 'exhibition', 'format': 'exhibition', 'start': '2026-10-01', 'end': '2026-12-01',
              'venue_names': ['Galeria H2O'], 'eligibility': 'review', 'media': [{'url': 'x'}], 'has_description': True, 'coordinates': {'lat': 1, 'lon': 2},
              'time': '11:00', 'occurrences': []}
        self.assertIn('g', expo_rank([ev], '2026-10-29'))
        self.assertNotIn('c', expo_rank([{**ev, 'key': 'c', 'id': 'c', 'venue_names': ['Centre Cívic Navas']}], '2026-10-29'))
