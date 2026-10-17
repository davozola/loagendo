import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.automation import initialize, is_due, load_config, run_due, status
from src.pipeline import connect


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp.name) / 'automation.sqlite3')
        initialize(self.conn)

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()

    def test_validates_config_and_tracks_disabled_job(self):
        config = {'jobs': [{'name':'disabled','kind':'web','source':'web_macba','every_minutes':60,'enabled':False}]}
        value = run_due(self.conn, config, Path(self.temp.name), now=dt.datetime(2026,10,12,tzinfo=dt.timezone.utc))
        self.assertEqual(value['outcomes'][0]['status'], 'disabled')
        with self.assertRaises(ValueError): load_config(Path(self.temp.name) / 'missing.json')

    def test_failed_job_is_recorded_and_retries_at_configured_delay(self):
        job = {'name':'broken','kind':'api','source':'generalitat','endpoint':'','every_minutes':60,'enabled':True}
        now=dt.datetime(2026,10,12,tzinfo=dt.timezone.utc)
        value=run_due(self.conn, {'jobs':[job]}, Path(self.temp.name), now=now)
        self.assertEqual(value['outcomes'][0]['status'],'failed')
        finished=dt.datetime.fromisoformat(self.conn.execute("SELECT finished_at FROM automation_runs WHERE job_name='broken'").fetchone()[0])
        self.assertFalse(is_due(self.conn,job,finished+dt.timedelta(minutes=59)))
        self.assertTrue(is_due(self.conn,job,finished+dt.timedelta(minutes=60)))
        health=status(self.conn)['health'][0]
        self.assertEqual((health['source'],health['consecutive_failures']),('generalitat',1))

    def test_recovers_abandoned_running_job_before_retry(self):
        self.conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,status) VALUES ('old','guiabcn','api','2026-10-12T00:00:00+00:00','running')")
        job={'name':'disabled','kind':'web','source':'web_macba','every_minutes':60,'enabled':False}
        run_due(self.conn, {'jobs':[job]}, Path(self.temp.name), now=dt.datetime(2026,10,12,tzinfo=dt.timezone.utc))
        self.assertEqual(self.conn.execute("SELECT status FROM automation_runs WHERE job_name='old'").fetchone()[0],'interrupted')

    def test_returns_busy_when_another_engine_holds_the_lock(self):
        self.conn.execute("INSERT INTO automation_locks(name,held_at) VALUES ('engine','2026-10-12T00:00:00+00:00')")
        result=run_due(self.conn, {'jobs':[]}, Path(self.temp.name), now=dt.datetime(2026,10,12,0,1,tzinfo=dt.timezone.utc))
        self.assertEqual(result['status'],'engine_busy')


if __name__ == '__main__': unittest.main()


class VolumeAnomalyTests(unittest.TestCase):
    def test_collapsed_row_count_marks_run_suspect_and_source_unhealthy(self):
        import sqlite3, tempfile, datetime as dt
        from pathlib import Path
        from src.automation import initialize, run_due, status, volume_check
        from src.sync import initialize as init_sync
        with tempfile.TemporaryDirectory() as folder:
            conn = sqlite3.connect(Path(folder) / 'a.sqlite3'); init_sync(conn); initialize(conn)
            for n, rows in enumerate((120, 118, 122, 119, 121)):
                conn.execute("INSERT INTO sync_runs(source,started_at,finished_at,status,rows_received) VALUES('web_cccb','2026-10-0%dT00:00:00+00:00','2026-10-0%dT00:00:00+00:00','completed',?)" % (n + 1, n + 1), (rows,))
            conn.commit()
            self.assertIsNone(volume_check(conn, 'web_cccb', {'status': 'completed', 'rows_received': 100}))
            self.assertTrue(volume_check(conn, 'web_cccb', {'status': 'completed', 'rows_received': 4}).startswith('LOW_VOLUME'))
            self.assertIsNone(volume_check(conn, 'web_new', {'status': 'completed', 'rows_received': 1}))
            import src.automation as automation
            original = automation.execute
            automation.execute = lambda conn, job, media_root: {'status': 'completed', 'rows_received': 4, 'source': 'web_cccb'}
            try:
                out = run_due(conn, {'jobs': [{'name': 'web-cccb', 'kind': 'web', 'source': 'web_cccb', 'every_minutes': 60}]}, Path(folder), force=True, now=dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc))
            finally:
                automation.execute = original
            self.assertEqual(out['outcomes'][0]['status'], 'suspect')
            health = status(conn)['health'][0]
            self.assertEqual((health['source'], health['last_status'], health['consecutive_failures']), ('web_cccb', 'suspect', 1))
            conn.close()


class DedupeJobTests(unittest.TestCase):
    def test_dedupe_job_refreshes_candidate_pairs_before_publishing(self):
        import json, tempfile
        from pathlib import Path
        from src.automation import execute, load_config
        from src.pipeline import connect
        from mvp import catalog
        config = load_config(Path(__file__).resolve().parents[1] / 'config' / 'automation.json')
        names = [j['name'] for j in config['jobs']]
        self.assertLess(names.index('duplicados-entre-fuentes'), names.index('publicar-web'))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            for source, id in (('venue_songkick', 'a'), ('web_conciertos_club', 'b')):
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, id, 'The Lemon Twigs', '2026-10-15', '2026-10-15', 'single', 'review', 'x', 'https://x.test/' + id, 'h', '{}'))
                conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (source, id, 0, 'Paral·lel 62', '', None, None))
            conn.commit()
            out = execute(conn, {'name': 'duplicados-entre-fuentes', 'kind': 'dedupe'}, Path(folder))
            self.assertEqual((out['status'], out['pairs']), ('completed', 1))
            conn.close()
