"""Vigilancia de fuentes, aviso por correo y parte diario (25-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import automation, daily_report, source_watch


def _conn(folder):
    from src.pipeline import connect
    conn = connect(Path(folder) / 't.sqlite3'); automation.initialize(conn); source_watch.initialize(conn)
    return conn


def _records(conn, source, n, day):
    conn.execute('DELETE FROM source_records WHERE source=?', (source,))
    for i in range(n):
        conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility,source_url) VALUES(?,?,?,?,?,?,?,?)",
                     (source, str(i), 'Acte %d' % i, day.isoformat(), day.isoformat(), '{}', 'review', ''))
    conn.commit()


class VolumeTests(unittest.TestCase):
    def test_drop_opens_one_email_and_recovery_closes(self):
        sent = []
        send = lambda *a: sent.append(a) or {'status': 'sent'}
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder); start = dt.date(2026, 10, 1)
            for i in range(5):
                day = start + dt.timedelta(days=i); _records(conn, 'web_x', 40, day)
                r = source_watch.check(conn, today=day, now=dt.datetime(2026, 10, 1 + i, 8, tzinfo=dt.timezone.utc), notify=None, send=send)
                self.assertEqual(r['opened'], [])
            day = start + dt.timedelta(days=5); _records(conn, 'web_x', 0, day)   # la fuente deja de traer actos
            now = dt.datetime(2026, 10, 6, 8, tzinfo=dt.timezone.utc)
            r = source_watch.check(conn, today=day, now=now, notify=None, send=send)
            self.assertEqual([(a['source'], a['kind']) for a in r['opened']], [('web_x', 'ACTS_DROP')])
            self.assertIn('no llega nada', r['opened'][0]['detail'])
            self.assertEqual(len(sent), 1); self.assertIn('web_x', sent[0][0])
            source_watch.check(conn, today=day, now=now + dt.timedelta(minutes=15), notify=None, send=send)
            self.assertEqual(len(sent), 1)  # cada alerta se avisa una vez
            _records(conn, 'web_x', 38, day)
            r = source_watch.check(conn, today=day, now=now + dt.timedelta(hours=1), notify=None, send=send)
            self.assertEqual(r['resolved'], [{'source': 'web_x', 'kind': 'ACTS_DROP'}])

    def test_without_key_nothing_is_marked_sent(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder)
            conn.execute("INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES('web_y','ACTS_DROP','x','2026-10-06T08:00:00+00:00','2026-10-06T08:00:00+00:00')")
            r = source_watch.email_new_alerts(conn, dt.datetime(2026, 10, 6, 9, tzinfo=dt.timezone.utc), send=lambda *a: {'status': 'skipped'})
            self.assertEqual(r['status'], 'skipped')
            self.assertIsNone(conn.execute('SELECT emailed_at FROM source_alerts').fetchone()[0])


class JobTests(unittest.TestCase):
    def test_three_failures_open_job_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder)
            for i in range(3):
                conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status,error) VALUES('web-cccb','web_cccb','web',?,?,'failed','HTTP 500')",
                             ('2026-10-06T0%d:00:00+00:00' % i, '2026-10-06T0%d:01:00+00:00' % i))
            config = {'jobs': [{'name': 'web-cccb', 'kind': 'web', 'source': 'web_cccb', 'every_minutes': 360}]}
            r = source_watch.check(conn, config, today=dt.date(2026, 10, 6), now=dt.datetime(2026, 10, 6, 4, tzinfo=dt.timezone.utc), notify=None, send=lambda *a: {'status': 'skipped'})
            self.assertEqual([(a['source'], a['kind']) for a in r['opened']], [('web-cccb', 'JOB_FAILING')])


class ScheduleTests(unittest.TestCase):
    def test_report_runs_once_a_day_from_its_hour(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder); job = {'name': 'parte-diario', 'kind': 'report', 'every_minutes': 1440, 'at': '08:00'}
            utc = lambda h, d=26: dt.datetime(2026, 10, d, h, 0, tzinfo=dt.timezone.utc)   # Madrid = UTC+1 en invierno
            self.assertFalse(automation.is_due(conn, job, utc(6)))
            self.assertTrue(automation.is_due(conn, job, utc(7)))
            conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status) VALUES('parte-diario','','report',?,?,'completed')", (utc(7).isoformat(), utc(7).isoformat()))
            self.assertFalse(automation.is_due(conn, job, utc(12)))
            self.assertTrue(automation.is_due(conn, job, utc(7, 27)))


class ReportTests(unittest.TestCase):
    def test_report_renders_and_is_saved_without_key(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder); day = dt.date(2026, 10, 26)
            _records(conn, 'guiabcn', 30, day)
            source_watch.check(conn, today=day, now=dt.datetime(2026, 10, 26, 7, tzinfo=dt.timezone.utc), notify=None, send=lambda *a: {'status': 'skipped'})
            conn.execute("INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES('web_y','ACTS_DROP','0 actos','2026-10-26T06:00:00+00:00','2026-10-26T06:00:00+00:00')")
            conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status,result_json) VALUES('publicar-web','','publish','2026-10-26T05:00:00+00:00','2026-10-26T05:30:00+00:00','completed',?)",
                         (json.dumps({'counts': {'events': 9623, 'upcoming_14_days': 4100}, 'deploy': {'status': 'completed'}}),))
            data = daily_report.collect(conn, today=day, now=dt.datetime(2026, 10, 26, 7, tzinfo=dt.timezone.utc), first_seen_path=Path(folder) / 'no.json', matomo=False)
            subject, body, text = daily_report.render(data)
            self.assertIn('1 para revisar', subject); self.assertIn('9.623', body); self.assertIn('web_y', body)   # parte breve (26-10-2026)
            r = daily_report.run(conn, {'to': 'hola@ontoca.com'}, today=day, send=lambda *a: {'status': 'skipped'}, out_dir=Path(folder) / 'partes')
            self.assertEqual(r['status'], 'completed'); self.assertTrue(Path(r['file']).is_file())


if __name__ == '__main__':
    unittest.main()


class FestivalEndTests(unittest.TestCase):
    def test_festival_terminado_no_se_lee_ni_alerta(self):
        from unittest import mock
        from src import venue_feeds
        called = []
        venues = [{"slug": "f1", "name": "F1", "type": "festival", "url": "https://x/", "enabled": True, "feed": {"kind": "accelevents", "hasta": "2000-01-01"}},
                  {"slug": "f2", "name": "F2", "type": "festival", "url": "https://y/", "enabled": True, "feed": {"kind": "accelevents", "hasta": "2999-01-01"}}]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(venue_feeds, "sync_venue", lambda c, v, f, t: called.append(v["slug"]) or {"status": "completed", "rows_received": 0, "rows_mutated": 0}), \
             mock.patch.object(venue_feeds, "migrate_record_ids", lambda c, v: {}), mock.patch.object(venue_feeds, "exclude_online_events", lambda c: {}):
            venue_feeds.sync_enabled(None, venues=venues, census_path=Path(folder) / "no.json")
        self.assertEqual(called, ["f2"])
        self.assertIn("venue_mozilla_festival", source_watch._festival_sources())


class AiBlockTests(unittest.TestCase):
    def test_bloque_ia_y_muestra_del_lunes(self):
        from src import ai_assist
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder); ai_assist.initialize(conn)
            _records(conn, 'guiabcn', 1, dt.date(2026, 10, 26)); _records(conn, 'generalitat', 1, dt.date(2026, 10, 26))
            log = "INSERT INTO ai_suggestion_log(task,item,input_hash,model,prompt_version,answer,confidence,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
            conn.execute(log, ('categoria', 'guiabcn:0', 'h', 'm', 1, 'musica', 0.9, 'concierto', '2026-10-26T05:00:00+00:00'))
            conn.execute(log, ('duplicado', 'guiabcn:0|generalitat:0', 'h', 'm', 1, 'mismo', 0.95, 'misma sala y hora', '2026-10-26T05:00:00+00:00'))
            conn.execute(log, ('datos', 'guiabcn:0', 'h', 'm', 1, '{}', 1.0, '2 datos descartados por no pasar la comprobación de cita', '2026-10-26T05:00:00+00:00'))
            conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status,result_json) VALUES('ia-asistente','','ai','2026-10-26T04:00:00+00:00','2026-10-26T04:10:00+00:00','completed',?)",
                         (json.dumps({'usage': {'input_tokens': 1200, 'output_tokens': 300}}),))
            data = daily_report.collect(conn, today=dt.date(2026, 10, 26), now=dt.datetime(2026, 10, 26, 7, tzinfo=dt.timezone.utc), first_seen_path=Path(folder) / 'x', matomo=False)
            ai = data['ai']
            self.assertEqual((ai['tokens']['input_tokens'], ai['categories'], ai['merges'], ai['dropped']), (1200, 1, 1, 1))
            self.assertEqual(len(ai['sample']), 1)   # 26-10-2026 es lunes
            _, body, _ = daily_report.render(data)
            self.assertIn('IA 24 h', body); self.assertIn('misma sala y hora', body)


class TriageTests(unittest.TestCase):
    """Clasificación de alertas en el parte (26-10-2026), con los casos reales del 26-10."""
    def test_casos(self):
        t = daily_report.triage
        self.assertEqual(t('JOB_FAILING', 'Últimas 3 pasadas: partial. HTTP 500 tras reintentos', 1)[0], 'esperar')
        self.assertEqual(t('JOB_FAILING', 'HTTP 500 tras reintentos', 4)[0], 'revisar')
        self.assertEqual(t('JOB', 'HTTP Error 500: Internal Server Error')[0], 'esperar')
        self.assertEqual(t('JOB', '1 de 14 fallan · venue_ia_caixaforum: HTTP 403; HTTP 404')[0], 'revisar')
        self.assertEqual(t('JOB', '1 de 14 fallan · venue_ia_la_nau: robots.txt no lo permite')[0], 'revisar')
        self.assertEqual(t('JOB', '1 de 14 fallan · venue_ia_poliorama: HTTP 0')[0], 'esperar')
        self.assertEqual(t('SUSPECT', 'LOW_VOLUME: 4 filas frente a una mediana reciente de 99')[0], 'revisar')
        self.assertEqual(t('JOB', 'HTTP 403', recovered=True)[0], 'suelto')
        self.assertEqual(t('PUBLISH_STALE', '')[0], 'revisar')

    def test_parte_muestra_la_clase_y_ordena(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder); day = dt.date(2026, 10, 26)
            ins = "INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES(?,?,?,?,?)"
            conn.execute(ins, ('api-diba-turismo', 'JOB_FAILING', 'Últimas 3 pasadas: partial, partial, partial. HTTP 500 tras reintentos', '2026-10-25T06:00:00+00:00', '2026-10-26T06:00:00+00:00'))
            conn.execute(ins, ('web_cccb', 'ACTS_DROP', '4 actos frente a 99', '2026-10-26T06:00:00+00:00', '2026-10-26T06:00:00+00:00'))
            run = "INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status,error) VALUES(?,?,?,?,?,?,?)"
            conn.execute(run, ('web-teatre-lliure', 'web_teatre_lliure', 'web', '2026-10-26T01:00:00+00:00', '2026-10-26T01:01:00+00:00', 'failed', 'HTTP Error 500: Internal Server Error'))
            conn.execute(run, ('agendas-ia', '', 'ai_agenda', '2026-10-26T02:00:00+00:00', '2026-10-26T02:10:00+00:00', 'partial', '1 de 14 fallan · venue_ia_x: HTTP 403'))
            conn.execute(run, ('agendas-ia', '', 'ai_agenda', '2026-10-26T05:00:00+00:00', '2026-10-26T05:10:00+00:00', 'completed', ''))
            data = daily_report.collect(conn, today=day, now=dt.datetime(2026, 10, 26, 7, tzinfo=dt.timezone.utc), first_seen_path=Path(folder) / 'x', matomo=False)
            self.assertEqual([a['triage']['class'] for a in data['alerts']], ['revisar', 'esperar'])
            self.assertEqual({f['job']: f['triage']['class'] for f in data['failing']}, {'web-teatre-lliure': 'esperar', 'agendas-ia': 'suelto'})
            subject, body, text = daily_report.render(data)
            self.assertIn('1 para revisar', subject)
            self.assertIn('Avería suya · esperar', body); self.assertIn('Fallo suelto', body); self.assertIn('[Revisar] web_cccb', text)


class FestivalWatchTests(unittest.TestCase):
    def test_nuevos_y_sin_horario_sin_repetir(self):
        items = [{'s': 'guiabcn', 'i': '1', 't': 'In-Edit', 'a': '2026-10-29', 'b': '2026-11-08', 'fs': ['auto-in', 'In-Edit', 1], 'kd': 'program', 'f': 'festival'},
                 {'s': 'opendatabcn_agenda', 'i': '2', 't': 'MIRA Festival 2026', 'a': '2026-11-06', 'b': '2026-11-07', 'fs': ['mira', 'MIRA', 1], 'hb': {'17:30': [0, 1]}, 'kd': 'program', 'f': 'festival'},
                 {'s': 'guiabcn', 'i': '3', 't': 'Festival de Jazz', 'a': '2026-04-18', 'b': '2026-12-23', 'fs': ['jazz', 'Jazz', 1], 'kd': 'program', 'f': 'festival'},
                 {'s': 'x', 'i': '4', 't': 'World Press Photo', 'a': '2026-11-06', 'b': '2026-11-20', 'f': 'exhibition', 'kd': 'exhibition'}]
        with tempfile.TemporaryDirectory() as folder:
            cat = Path(folder) / 'catalog.json'; cat.write_text(json.dumps({'items': items}))
            conn = _conn(folder)
            tue = dt.date(2026, 10, 27); now = dt.datetime(2026, 10, 27, 7, tzinfo=dt.timezone.utc)
            w = daily_report._festival_watch(conn, tue, now, cat)
            self.assertEqual(sorted(n['name'] for n in w['new']), ['In-Edit', 'MIRA Festival 2026'])   # sin temporadas ni exposiciones
            self.assertEqual(([p['name'] for p in w['listed']], w['pending']), (['In-Edit'], 1))
            w2 = daily_report._festival_watch(conn, dt.date(2026, 10, 20), now, cat)   # sin novedades y lejos: no se repite
            self.assertEqual((w2['new'], w2['listed'], w2['pending']), ([], [], 1))
            items[0]['mh'] = {'2026-10-29': {'time': '17:00'}}; cat.write_text(json.dumps({'items': items}))
            w3 = daily_report._festival_watch(conn, tue, now, cat)
            self.assertEqual(w3['pending'], 0)   # resuelto con la hora puesta a mano
