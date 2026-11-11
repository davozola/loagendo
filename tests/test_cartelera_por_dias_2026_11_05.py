"""Cartelera por días (5-11-2026, Espai Texas): una fecha cerca del título pero en el bloque de otro día no es de ese acto."""
import datetime as dt
import unittest

from src import ai_agenda

TODAY = dt.date(2026, 11, 5)
GRID = ("Cartellera Teatre novembre Dl Dt Dc Dj Dv Ds Dg 01 Dl 02 Dt 03 Dc 04 Dj 05 Dv 06 nov. Dv 06 RITA 19:00 BIOPIC 21:30 "
        "Ds 07 nov. Ds 07 RITA 17:30 RITA 19:30 AUTÓNOMOS EL MUSICAL 22:15 Dg 08 nov. Dg 08 RITA 17:30 Dl 09 Dt 10 "
        "Ds 12 des. Ds 12 ACORAR 12:30 RITA 17:30 RITA 19:30 Dg 13 des. Dg 13 ACORAR 12:30 RITA 17:30 Dl 14 Dt 15 Dc 16 des. "
        "Dc 16 L'ESTIUEIG 20:00 Dj 17 des. Dj 17 L'ESTIUEIG 19:00 Dc 23 des. Dc 23 L'ESTIUEIG 20:00 Dj 24")


def ses(day, quote, hour=''):
    return {'fecha': day, 'cita_fecha': quote, **({'hora': hour, 'cita_hora': hour} if hour else {})}


class CarteleraPorDias(unittest.TestCase):
    def setUp(self): self.text, self.links = ai_agenda.clean(f'<p>{GRID}</p>', 'https://espaitexas.cat/teatre/')

    def test_funciones_de_otra_obra_no_pasan(self):
        item = {'titulo': 'RITA', 'sesiones': [ses('2026-11-06', 'Dv 06 nov.', '19:00'), ses('2026-11-07', 'Ds 07 nov.', '17:30'),
                                               ses('2026-12-13', 'Dg 13 des.', '17:30'), ses('2026-12-16', 'Dc 16 des.', '20:00'),
                                               ses('2026-12-23', 'Dc 23 des.', '20:00')]}
        act, why = ai_agenda.verify(item, self.text, self.links, TODAY)
        self.assertEqual([d for d, _ in act['sesiones']], ['2026-11-06', '2026-11-07', '2026-12-13'])
        self.assertTrue(any('otro día' in w for w in why))

    def test_varias_obras_el_mismo_dia(self):
        act, _ = ai_agenda.verify({'titulo': 'AUTÓNOMOS EL MUSICAL', 'sesiones': [ses('2026-11-07', 'Ds 07 nov.', '22:15')]}, self.text, self.links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '22:15')])
        act, _ = ai_agenda.verify({'titulo': "L'ESTIUEIG", 'sesiones': [ses('2026-12-16', 'Dc 16 des.', '20:00'), ses('2026-12-23', 'Dc 23 des.', '20:00')]}, self.text, self.links, TODAY)
        self.assertEqual([d for d, _ in act['sesiones']], ['2026-12-16', '2026-12-23'])

    def test_lista_de_dias_detras_del_titulo_sigue_valiendo(self):
        text, links = ai_agenda.clean('<p>Jazz a la fresca: dv 20, ds 21 i dg 22 de novembre</p>', 'https://x.test/')
        act, _ = ai_agenda.verify({'titulo': 'Jazz a la fresca', 'sesiones': [ses('2026-11-20', 'dv 20'), ses('2026-11-21', 'ds 21'), ses('2026-11-22', 'dg 22 de novembre')]}, text, links, TODAY)
        self.assertEqual(len(act['sesiones']), 3)


    def test_periodo_de_la_obra_siguiente_no_pasa(self):
        text, links = ai_agenda.clean("<p>RITA / UNA COMÈDIA DE MARTA BUCHACA Comprar 06/11/26 - 13/12/26 BIOPIC / NITS D'IMPRO BARCELONA Comprar 18/09/26 - 29/01/27</p>", 'https://espaitexas.cat/teatre/')
        bad, why = ai_agenda.verify({'titulo': 'RITA', 'periodo': {'inicio': '2026-09-18', 'fin': '2027-01-29', 'cita': '18/09/26 - 29/01/27'}}, text, links, TODAY)
        self.assertIsNone(bad)
        ok, _ = ai_agenda.verify({'titulo': 'RITA', 'periodo': {'inicio': '2026-11-06', 'fin': '2026-12-13', 'cita': '06/11/26 - 13/12/26'}}, text, links, TODAY)
        self.assertEqual(ok['periodo'], ('2026-11-06', '2026-12-13'))
        ok, _ = ai_agenda.verify({'titulo': 'BIOPIC', 'periodo': {'inicio': '2026-09-18', 'fin': '2027-01-29', 'cita': '18/09/26 - 29/01/27'}}, text, links, TODAY)
        self.assertEqual(ok['periodo'], ('2026-09-18', '2027-01-29'))


    def test_guion_tipografico_en_la_cita(self):
        text, links = ai_agenda.clean('<p>Tot allò que balla · 7–8 nov 2026 · Nau de La Caldera</p>', 'https://www.lacaldera.info/')
        act, why = ai_agenda.verify({'titulo': 'Tot allò que balla', 'sesiones': [ses('2026-11-07', '7–8 nov 2026'), ses('2026-11-08', '7–8 nov 2026')]}, text, links, TODAY)
        self.assertEqual([d for d, _ in act['sesiones']], ['2026-11-07', '2026-11-08'], why)


class Relecturas(unittest.TestCase):
    def setUp(self):
        import sqlite3
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE sync_runs(id INTEGER PRIMARY KEY, source TEXT, status TEXT, rows_received INTEGER, warning_json TEXT)')

    def add(self, warn):
        import json
        self.conn.execute("INSERT INTO sync_runs(source,status,rows_received,warning_json) VALUES('s','completed',5,?)", (json.dumps(warn),))

    def test_incompleta_una_relectura_y_basta(self):
        self.add([]); self.assertFalse(ai_agenda.needs_reread(self.conn, 's'))
        self.add([ai_agenda.INCOMPLETE_MARK + ': 20 actos']); self.assertTrue(ai_agenda.needs_reread(self.conn, 's'))
        self.add([ai_agenda.INCOMPLETE_MARK + ': 18 actos']); self.assertFalse(ai_agenda.needs_reread(self.conn, 's'))

    def test_retirada_frenada_siempre(self):
        self.add([ai_agenda.INCOMPLETE_MARK]); self.add([ai_agenda.RETIRE_HELD_MARK + ': 6 de 9']); self.assertTrue(ai_agenda.needs_reread(self.conn, 's'))


class CarteleraConReglas(unittest.TestCase):
    """10-11-2026: la cartelera por días de Espai Texas, con reglas y sin IA."""
    CINE = ("Dl Dt Dc Dj Dv Ds Dg 01 Dl 02 Dt 03 Dc 04 Dj 05 Dv 06 Ds 07 Dg 08 Dl 09 Dt 10 nov. Dt 10 VIATGE AL PAÍS DELS BLANCS [L4] 16:00 BLUE HERON 16:15 "
            "CRONOS 18:00 LA INVASIÓ DELS BÀRBARS 18:15 11 20:30 Dc 11 Dj 12 nov. Dj 12 LA INVASIÓ DELS BÀRBARS 16:00 BLUE HERON 16:15 Dv 13 Ds 14 "
            "Dl 30 nov. Dl 30 CICLE ARTEC 19:00 SNOWPIERCER 19:00 Dl Dt 01 Dc 02 Dt 01 des. Dt 01 UNA HISTÒRIA CERTA SOBRE LA MENTIDA 20:00 Dj")
    AG = {'slug': 'espai_texas', 'name': 'Espai Texas', 'address': 'Carrer de Bailèn 205, 08037 Barcelona', 'type': 'cinema', 'reglas': 'cartelera_por_dias'}

    def test_cada_funcion_con_su_dia_y_hora(self):
        nodes = ai_agenda.grid_nodes(self.CINE, self.AG, dt.date(2026, 11, 10), 'https://espaitexas.cat/cartellera-cinema/')
        got = [(n['startDate'], n['name']) for n in nodes]
        self.assertIn(('2026-11-10T20:30:00', '11'), got)
        self.assertIn(('2026-11-30T19:00:00', 'SNOWPIERCER'), got)
        self.assertNotIn('CICLE ARTEC', [n for _, n in got])                      # el ciclo y la película a la misma hora: la película
        self.assertEqual(len([1 for d, _ in got if d.startswith('2026-11-12')]), 2)   # los días sin funciones no se inventan
        self.assertIn(('2026-12-01T20:00:00', 'UNA HISTÒRIA CERTA SOBRE LA MENTIDA'), got)

    def test_sin_esa_forma_no_hay_nodos(self):
        self.assertEqual(ai_agenda.grid_nodes('Cicle de cinema: Wakolda, dimarts 27 a les 19:30', self.AG, TODAY, 'https://x.test/'), [])

    def test_fichas_desde_las_reglas(self):
        nodes = ai_agenda.grid_nodes(self.CINE, self.AG, dt.date(2026, 11, 10), 'https://espaitexas.cat/cartellera-cinema/')
        recs = ai_agenda.rules_records(self.AG, [(n, 'https://espaitexas.cat/cartellera-cinema/', 'h') for n in nodes])
        r = next(r for r in recs if r['title'] == 'SNOWPIERCER')
        self.assertEqual((r['start'], r['time_text']), ('2026-11-30', '19:00'))
        self.assertEqual(r['raw']['ai_agenda']['model'], 'reglas: cartelera por días')


class SoloPrimeraYUltima(unittest.TestCase):
    """10-11-2026, Disseny Hub: el listado da «28/10/2026 - 18:30 - 26/05/2027 - 19:30»; la página del acto, el programa."""
    LIST = '<p><a href="https://dh.test/act/club">Club Llegim el Museu</a> CONFERÈNCIES 28/10/2026 - 18:30 - 26/05/2027 - 19:30</p>'
    PAGE = ('<h1>Club Llegim el Museu</h1><p>CONFERÈNCIES 28/10/2026 - 18:30 - 26/05/2027 - 19:30</p><p>PROGRAMA</p>'
            '<p>25 de novembre de 2026, 18:30 h. La teranyina, de Jaume Cabré</p><p>27 de gener de 2027, 18:30 h. Manual anticapitalista</p>')
    AG = {'slug': 'dh', 'name': 'Disseny Hub Barcelona', 'type': 'culture', 'urls': ['https://dh.test/agenda'], 'seguir_actos': 6}

    def test_lee_la_pagina_del_acto(self):
        def fetch(url, timeout): return (200, url, self.LIST if url.endswith('/agenda') else self.PAGE)
        def ai(method, url, key, body=None, timeout=60, raw=False):
            import json
            text = json.loads(body['messages'][0]['content'])['texto']
            if 'PROGRAMA' in text:
                items = [{'titulo': 'Club Llegim el Museu', 'sesiones': [{'fecha': '2026-11-25', 'cita_fecha': '25 de novembre de 2026', 'hora': '18:30', 'cita_hora': '18:30 h'},
                                                                        {'fecha': '2027-01-27', 'cita_fecha': '27 de gener de 2027', 'hora': '18:30', 'cita_hora': '18:30 h'}]}]
            else:
                items = [{'titulo': 'Club Llegim el Museu', 'enlace': 'L1', 'sesiones': [{'fecha': '2027-05-26', 'cita_fecha': '28/10/2026 - 18:30 - 26/05/2027', 'hora': '19:30', 'cita_hora': '26/05/2027 - 19:30'}]}]
            return {'content': [{'type': 'tool_use', 'name': 'actos', 'input': {'actos': items}}], 'usage': {}}
        res = ai_agenda.read_agenda(self.AG, dt.date(2026, 11, 10), 'k', fetcher=fetch, requester=ai)
        club = [a for a in res['accepted'] if a['titulo'] == 'Club Llegim el Museu']
        self.assertEqual(len(club), 1)
        self.assertEqual([d for d, _ in club[0]['sesiones']], ['2026-11-25', '2027-01-27'])


if __name__ == '__main__':
    unittest.main()
