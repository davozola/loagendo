"""La Selecció, la newsletter de los jueves (4-11-2026): edición, comprobación de textos, revisión, envío y páginas."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import seleccio
from src.publish_static import shard_of
from src.pipeline import connect

THU = dt.date(2026, 11, 5)
JPEG_1200x675 = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffc0001108') + (675).to_bytes(2, 'big') + (1200).to_bytes(2, 'big') + bytes.fromhex('03012200021101031101ffd9')


def card(i, title, a, b, o=None, hb=None, pc='musica', img=True, venue='Sala X'):
    return {'s': 'opendatabcn_agenda', 'i': i, 't': title, 'a': a, 'b': b, 'o': o or [], 'hb': hb, 'pc': pc, 'd': 'Ciutat Vella', 'v': [venue],
            'fr': 0, 'mi': f'/img/{i}.jpg' if img else None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.dist = root / 'dist'; (self.dist / 'data' / 'detail').mkdir(parents=True); (self.dist / 'img').mkdir()
        cards = [card('1', 'El temps a través d’un forat', '2026-11-07', '2026-11-08', hb={'17:00 · 20:00': [0, 1]}, pc='escena'),
                 card('2', 'Vijay Iyer', '2026-11-06', '2026-11-06', o=[['2026-11-06', '20:30']]),
                 card('3', 'Jonathan Stout Quintet', '2026-11-08', '2026-11-08', o=[['2026-11-08', '19:00'], ['2026-11-08', '20:30']]),
                 card('4', 'Christian Blackshaw', '2026-11-09', '2026-11-09', o=[['2026-11-09', '20:00']]),
                 card('5', 'City Hall party', '2026-11-07', '2026-11-07', o=[['2026-11-07', '23:00']], venue='City Hall')]
        (self.dist / 'data' / 'catalog.json').write_text(json.dumps({'items': cards}), encoding='utf-8')
        details = {}
        texts = {'1': 'Una peça de teatre visual on les maquetes són la dramatúrgia, d’Aina Roca Mora.', '2': 'El pianista Vijay Iyer, un dels noms cabdals del jazz.',
                 '3': 'El guitarrista californià Jonathan Stout, del swing.', '4': 'Christian Blackshaw obre la integral de Mozart.', '5': 'Festa.'}
        for c in cards:
            k = f"opendatabcn_agenda:{c['i']}"
            details.setdefault(shard_of(k), {})[k] = {'title': c['t'], 'description': texts[c['i']], 'price_label': 'Entrada general: 17 € (+ despeses de gestió)', 'public_category': c['pc'], 'venue_names': c['v']}
            (self.dist / 'img' / f"{c['i']}.jpg").write_bytes(JPEG_1200x675)
        for shard, data in details.items(): (self.dist / 'data' / 'detail' / f'{shard}.json').write_text(json.dumps(data), encoding='utf-8')
        self.conn = connect(root / 't.sqlite3')
        self.conn.execute('CREATE TABLE ai_selection (day TEXT, scope TEXT, created_at TEXT, model TEXT, prompt_version TEXT, candidates_json TEXT, picks_json TEXT, usage_json TEXT, popular_json TEXT, extra_json TEXT, PRIMARY KEY(day, scope))')
        picks = {'2026-11-06': ['2'], '2026-11-07': ['5', '1'], '2026-11-08': ['3', '1'], '2026-11-09': ['4']}
        for day, keys in picks.items():
            self.conn.execute("INSERT INTO ai_selection(day,scope,picks_json) VALUES (?, 'day', ?)", (day, json.dumps([{'key': f'opendatabcn_agenda:{k}', 'motivo': 'buen plan'} for k in keys])))
        self.conn.commit()
        self.rules = root / 'excl.json'; self.rules.write_text(json.dumps({'venues': ['City Hall']}), encoding='utf-8')
        self.patch_rules = mock.patch('src.selection_rules.rules', lambda path=None: (set(), [__import__('re').compile('city hall')]))
        self.patch_rules.start()
        self.mail = mock.patch('src.mailer.send', return_value={'status': 'sent'}); self.sent = self.mail.start()
        self.envp = mock.patch.object(seleccio, 'env', lambda name: {'SELECCIO_TOKEN': 'tok', 'BREVO_API_KEY': 'k'}.get(name, '')); self.envp.start()
        self.cfg = {**seleccio.config('/nonexistent'), 'enabled': True, 'lists': {'ca': 1, 'es': 2, 'en': 3}}

    def tearDown(self):
        self.patch_rules.stop(); self.mail.stop(); self.envp.stop(); self.conn.close(); self.tmp.cleanup()

    def ai(self, out):
        return lambda *a, **k: {'content': [{'type': 'tool_use', 'name': 'redactar', 'input': out}], 'usage': {'input_tokens': 1}}


GOOD = {'titular': {'ca': 'Maquetes i swing', 'es': 'Maquetas y swing', 'en': 'Scale models and swing'},
        'intro': {'ca': 'El temps a través d’un forat i Vijay Iyer.', 'es': 'Maquetas en escena y Vijay Iyer.', 'en': 'Scale models and Vijay Iyer.'},
        'protagonista': 1,
        'planes': [{'n': 0, 'ca': 'Un dels noms cabdals del jazz.', 'es': 'Uno de los nombres del jazz.', 'en': 'A key name in jazz.'},
                   {'n': 1, 'ca': 'Maquetes com a dramatúrgia.', 'es': 'Maquetas como dramaturgia.', 'en': 'Scale models as dramaturgy.'},
                   {'n': 2, 'ca': 'Swing amb Wynton Marsalis i 1937.', 'es': 'Swing californiano.', 'en': 'Californian swing.'}]}


class Datos(Base):
    def test_sesiones_y_fechas(self):
        days = [dt.date(2026, 11, 6), dt.date(2026, 11, 7), dt.date(2026, 11, 8)]
        s = seleccio.sessions(card('9', 'x', '2026-11-07', '2026-11-08', hb={'17:00 · 20:00': [0, 1]}), days)
        self.assertEqual(s, {'2026-11-07': ['17:00', '20:00'], '2026-11-08': ['17:00', '20:00']})
        self.assertEqual(seleccio.when_label(s, 'ca'), 'Ds 7 i dg 8 · 17:00 i 20:00')
        s2 = {'2026-11-06': ['19:00'], '2026-11-07': ['19:00'], '2026-11-08': ['11:00']}
        self.assertEqual(seleccio.when_label(s2, 'es'), 'Vie 6 y sáb 7 · 19:00 · dom 8 · 11:00')

    def test_eleccion_sin_salas_excluidas_y_por_partes(self):
        items, total = seleccio.choose(self.conn, THU, self.dist)
        keys = [(i['key'].split(':')[1], i['part']) for i in items]
        self.assertEqual(keys, [('2', 'weekend'), ('1', 'weekend'), ('3', 'weekend'), ('4', 'next')])
        self.assertTrue(all(i['img_ok'] for i in items))
        self.assertEqual(items[0]['price'], '17 €')

    def test_comprobacion_de_textos(self):
        facts = 'El guitarrista californià Jonathan Stout, del swing.'
        self.assertEqual(seleccio.unknown_terms('Swing de Jonathan Stout.', facts), [])
        self.assertIn('Wynton', seleccio.unknown_terms('Swing amb Wynton Marsalis.', facts))
        self.assertIn('1937', seleccio.unknown_terms('Swing de 1937.', facts))
        self.assertEqual(seleccio.check_text('head', 'x' * 80, facts), 'titular demasiado largo')


class Edicion(Base):
    def build(self, out=GOOD):
        return seleccio.build(self.conn, THU, self.dist, requester=self.ai(out))

    def test_textos_que_no_cuadran_se_descartan(self):
        ed = self.build()
        stout = next(i for i in ed['data']['items'] if i['title'].startswith('Jonathan'))
        self.assertEqual(stout['why']['ca'], '')            # Wynton Marsalis y 1937 no están en la ficha
        self.assertEqual(stout['why']['es'], 'Swing californiano.')
        self.assertEqual(ed['data']['hero'], 'opendatabcn_agenda:1')
        self.assertTrue(ed['ai'][0]['rejected'])
        self.assertEqual(seleccio.load(self.conn, '2026-11-05')['status'], 'draft')

    def test_correo(self):
        ed = self.build()
        html = seleccio.render(ed, 'ca', 'email', 'https://ontoca.com')
        for x in ('La Selecció · núm. 1', 'Cap de setmana del 6 al 8 de novembre', 'El temps a través d’un forat', 'Els dies següents', '{{ unsubscribe }}',
                  'https://ontoca.com/img/1.jpg', 'mtm_campaign=seleccio', 'Ds 7 i dg 8 · 17:00 i 20:00', 'background:#23CED9'):
            self.assertIn(x, html)
        web = seleccio.render(ed, 'es', 'web', 'https://ontoca.com')
        self.assertNotIn('{{', web); self.assertIn('/es/e/opendatabcn_agenda/1', web); self.assertIn('Fin de semana del 6 al 8 de noviembre', web)

    def test_pocos_planes_no_hay_edicion(self):
        self.conn.execute("DELETE FROM ai_selection WHERE day IN ('2026-11-07','2026-11-08')"); self.conn.commit()
        ed = seleccio.build(self.conn, THU, self.dist, requester=self.ai(GOOD))
        self.assertEqual(ed['status'], 'empty')

    def test_cambios_de_la_revision_con_historial(self):
        ed = self.build()
        tr = lambda *a, **k: {'content': [{'type': 'tool_use', 'name': 'traducir', 'input': {'textos': {'es': 'Jazz de Vijay Iyer.', 'en': 'Jazz by Vijay Iyer.'}}}]}
        acts = [{'seq': 1, 'type': 'remove', 'item': 'opendatabcn_agenda:3'}, {'seq': 2, 'type': 'hero', 'item': 'opendatabcn_agenda:2'},
                {'seq': 3, 'type': 'edit', 'item': 'opendatabcn_agenda:2', 'lang': 'ca', 'text': 'El jazz de Vijay Iyer.'}, {'seq': 4, 'type': 'approve'}]
        seleccio.apply_actions(ed, acts, requester=tr)
        d = ed['data']; vijay = next(i for i in d['items'] if i['key'] == 'opendatabcn_agenda:2')
        self.assertEqual(d['hero'], 'opendatabcn_agenda:2')
        self.assertTrue(next(i for i in d['items'] if i['key'] == 'opendatabcn_agenda:3')['removed'])
        self.assertEqual((vijay['why']['ca'], vijay['why_src']['ca'], vijay['why']['es'], vijay['why_src']['es']), ('El jazz de Vijay Iyer.', 'david', 'Jazz de Vijay Iyer.', 'traducido'))
        self.assertEqual(ed['status'], 'approved'); self.assertEqual(ed['actions_seq'], 4)
        self.assertEqual([h['action'] for h in ed['history']], ['remove', 'hero', 'edit', 'approve'])
        self.assertEqual(ed['history'][2]['before']['ca'], 'Un dels noms cabdals del jazz.')


class Semana(Base):
    def opener(self, actions):
        calls = []
        def op(req, timeout):
            calls.append((req.get_method(), req.full_url, json.loads(req.data) if req.data else None))
            if '/acciones' in req.full_url: return {'actions': actions.pop(0) if actions else []}
            if '/emailCampaigns' in req.full_url and req.get_method() == 'POST': return {'id': 100 + len(calls)}
            return {}
        return op, calls

    def at(self, y, m, d, h, mi): return dt.datetime(y, m, d, h, mi, tzinfo=seleccio.MADRID)

    def run_at(self, when, op):
        return seleccio.run(self.conn, now=when, dist=self.dist, requester=self.ai(GOOD), opener=op, cfg=self.cfg)

    def test_semana_aprobada(self):
        op, calls = self.opener([[], [{'seq': 1, 'type': 'approve', 'at': '2026-11-04T20:00:00+00:00'}]])
        self.assertEqual(self.run_at(self.at(2026, 11, 4, 8, 0), op)['step'], 'esperando al miércoles')
        r = self.run_at(self.at(2026, 11, 4, 9, 5), op)
        self.assertEqual(r['step'], 'prueba enviada')
        subj, html = self.sent.call_args[0][0], self.sent.call_args[0][1]
        self.assertIn('[Prueba]', subj); self.assertIn('/seleccio/revisar?id=2026-11-05&k=', html); self.assertNotIn('{{', html)
        self.assertTrue(any(u.endswith('/edicion') for _, u, _ in calls))
        self.assertEqual(self.run_at(self.at(2026, 11, 4, 12, 0), op)['step'], 'draft')
        r = self.run_at(self.at(2026, 11, 4, 21, 0), op)
        self.assertEqual(r['step'], 'scheduled')
        posts = [b for m, u, b in calls if m == 'POST' and u.endswith('/emailCampaigns')]
        self.assertEqual(len(posts), 3); self.assertEqual(posts[0]['scheduledAt'], '2026-11-05T09:00:00+01:00'); self.assertEqual(posts[1]['recipients'], {'listIds': [2]})
        self.assertIn('{{ unsubscribe }}', posts[0]['htmlContent'])
        self.assertEqual(self.run_at(self.at(2026, 11, 5, 8, 50), op)['step'], 'programada')
        with mock.patch.object(seleccio, 'ARCHIVE', Path(self.tmp.name) / 'archivo'):
            with mock.patch('src.seleccio.archive') as arch:
                self.assertEqual(self.run_at(self.at(2026, 11, 5, 9, 5), op)['step'], 'enviada'); arch.assert_called_once()

    def test_cambio_despues_de_aprobar_quita_las_campanas(self):
        op, calls = self.opener([[{'seq': 1, 'type': 'approve'}], [{'seq': 2, 'type': 'remove', 'item': 'opendatabcn_agenda:3'}, {'seq': 3, 'type': 'unapprove'}]])
        self.run_at(self.at(2026, 11, 4, 9, 5), op)
        self.assertEqual(self.run_at(self.at(2026, 11, 4, 10, 0), op)['step'], 'scheduled')
        self.assertEqual(self.run_at(self.at(2026, 11, 4, 11, 0), op)['step'], 'draft')
        self.assertEqual(len([1 for m, u, _ in calls if m == 'DELETE']), 3)

    def test_sin_aprobar_no_sale_y_avisa(self):
        op, calls = self.opener([])
        self.run_at(self.at(2026, 11, 4, 9, 5), op)
        r = self.run_at(self.at(2026, 11, 5, 8, 46), op)
        self.assertEqual(r['step'], 'no enviada')
        self.assertIn('no sale esta semana', self.sent.call_args[0][0])
        self.assertFalse([1 for m, u, _ in calls if '/emailCampaigns' in u])
        self.assertEqual(seleccio.load(self.conn, '2026-11-05')['status'], 'not_sent')

    def test_apagada(self):
        self.assertEqual(seleccio.run(self.conn, cfg={**self.cfg, 'enabled': False})['status'], 'skipped')


class Paginas(Base):
    def test_archivo_y_confirmacion(self):
        root = Path(self.tmp.name) / 'archivo'; out = Path(self.tmp.name) / 'out'
        seleccio.write_pages(out, root)
        self.assertIn('Fet. Ens veiem dijous.', (out / 'seleccio' / 'confirmada' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('La primera edición sale pronto.', (out / 'es' / 'seleccio' / 'index.html').read_text(encoding='utf-8'))
        ed = seleccio.build(self.conn, THU, self.dist, requester=self.ai(GOOD))
        seleccio.archive(ed, self.cfg, root); seleccio.write_pages(out, root)
        self.assertIn('El temps a través', (out / 'en' / 'seleccio' / '2026-11-05' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('El temps a través', (out / 'seleccio' / 'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
