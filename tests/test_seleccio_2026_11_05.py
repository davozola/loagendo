"""Incidente del 5-11-2026: la campaña en catalán se creó 42 veces porque la de castellano fallaba (lista vacía, HTTP 400) y
no se guardaba nada entre pasadas. Programar tiene que ser idempotente."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from src import seleccio
from tests import test_seleccio_2026_11_04 as base


class Brevo400:
    """Brevo de mentira: guarda las campañas creadas por nombre; la lista 2 (es) está vacía y rechaza campañas como el real."""
    def __init__(self, sizes=None, reject=()):
        self.created, self.calls, self.sizes, self.reject = {}, [], sizes or {1: 2, 2: 0, 3: 2}, set(reject)

    def __call__(self, req, timeout):
        m, u = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append((m, u, body))
        if '/acciones' in u: return {'actions': [{'seq': 1, 'type': 'approve'}]} if not any('/acciones' in x[1] for x in self.calls[:-1]) else {'actions': []}
        if m == 'GET' and '/emailCampaigns?' in u: return {'campaigns': [{'id': i, 'name': n} for n, i in self.created.items()]}
        if m == 'GET' and '/contacts/lists/' in u: return {'uniqueSubscribers': self.sizes[int(u.rsplit('/', 1)[1])]}
        if m == 'POST' and u.endswith('/emailCampaigns'):
            lid = body['recipients']['listIds'][0]
            if lid in self.reject or not self.sizes[lid]:
                raise urllib.error.HTTPError(u, 400, 'Bad Request', {}, io.BytesIO(b'{"code":"invalid_parameter","message":"list is empty"}'))
            self.created[body['name']] = 500 + len(self.created); return {'id': self.created[body['name']]}
        return {}

    def posts(self, lid=None):
        return [b for m, u, b in self.calls if m == 'POST' and u.endswith('/emailCampaigns') and (lid is None or b['recipients']['listIds'] == [lid])]


class Idempotente(base.Semana):
    locals().update({n: None for n in dir(base.Semana) if n.startswith('test_')})   # no repetir las pruebas de la clase base

    def pasadas(self, op, n=6):
        self.run_at(self.at(2026, 11, 4, 9, 5), op)
        return [self.run_at(self.at(2026, 11, 4, 10 + i, 0), op) for i in range(n)]

    def test_lista_vacia_no_repite_las_demas(self):
        op = Brevo400()
        self.pasadas(op)
        self.assertEqual(len(op.posts(1)), 1); self.assertEqual(len(op.posts(3)), 1); self.assertEqual(op.posts(2), [])
        ed = seleccio.load(self.conn, '2026-11-05')
        self.assertEqual(ed['status'], 'scheduled'); self.assertEqual(ed['campaigns']['empty'], ['es'])
        self.assertEqual(sorted(ed['campaigns']['ids']), ['ca', 'en'])

    def test_rechazo_tres_intentos_y_un_aviso(self):
        op = Brevo400(sizes={1: 2, 2: 5, 3: 2}, reject={2})
        self.sent.reset_mock()
        self.pasadas(op, 8)
        self.assertEqual(len(op.posts(1)), 1); self.assertEqual(len(op.posts(2)), seleccio.MAX_TRIES)
        ed = seleccio.load(self.conn, '2026-11-05')
        self.assertIn('list is empty', ed['campaigns']['errors']['es'])
        alerts = [c for c in self.sent.call_args_list if 'rechazó' in c[0][0]]
        self.assertEqual(len(alerts), 1)

    def test_si_se_pierde_lo_guardado_el_nombre_evita_el_duplicado(self):
        op = Brevo400(sizes={1: 2, 2: 2, 3: 2})
        self.pasadas(op, 1)
        ed = seleccio.load(self.conn, '2026-11-05'); ed['campaigns'] = None; ed['status'] = 'approved'; seleccio.save(self.conn, ed)
        self.pasadas(op, 2)
        self.assertEqual(len(op.posts()), 3)

    def test_error_con_detalle(self):
        op = Brevo400()
        with mock.patch.object(seleccio, 'env', return_value='k'):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 400 .*list is empty'):
                seleccio.brevo('POST', '/emailCampaigns', {'recipients': {'listIds': [2]}}, op)


if __name__ == '__main__':
    unittest.main()
