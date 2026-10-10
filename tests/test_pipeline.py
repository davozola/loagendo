import json,sqlite3,tempfile,unittest
from pathlib import Path
from src.pipeline import ROOT,build_records,candidate_sessions,day,geo_meters,match_pairs,norm,run,simple_times,title_similarity

class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=build_records(ROOT/'data')
        cls.byid={(r['source'],r['id']):r for r in cls.records}
    def test_source_count(self):
        self.assertEqual(len(self.records),369)
    def test_source_ids_unique(self):
        self.assertEqual(len(self.records),len(self.byid))
    def test_gencat_multi_venue(self):
        festival=self.byid['generalitat','20260210006']
        self.assertGreater(len(festival['venues']),1)
        self.assertEqual(candidate_sessions(festival),[])
    def test_exhibition_open_hours_not_occurrences(self):
        exhibition=self.byid['generalitat','20251217007']
        self.assertEqual(candidate_sessions(exhibition),[])
        self.assertEqual(exhibition['kind'],'exhibition')
    def test_generator_non_fictional_single_time(self):
        f=self.byid['generalitat','2026092300038']
        self.assertEqual(candidate_sessions(f)[0]['local_time'],'19:00')
        self.assertIsNone(candidate_sessions(f)[0]['end_time'])
    def test_timestamps_are_not_open_end_times(self):
        a=self.byid['diba_bibliotecas','agendabiblioteques460864789']
        self.assertEqual(candidate_sessions(a)[0]['local_date'],'2026-10-30')
        self.assertEqual(candidate_sessions(a)[0]['end_time'],None)
        self.assertIn('ADMINISTRATIVE_DAY_END_NOT_SESSION_TIME',a['alerts'])
    def test_recurrence_never_expands(self):
        a=self.byid['diba_bibliotecas','agendabiblioteques448522989']
        self.assertEqual(candidate_sessions(a),[])
        self.assertEqual(a['eligibility'],'exclude')
    def test_monthly_club_not_expanded(self):
        a=self.byid['diba_bibliotecas','agendabiblioteques438666679']
        self.assertEqual(candidate_sessions(a),[])
    def test_tour_without_time_not_midnight_event(self):
        a=self.byid['diba_turismo','agendaturisme459415208']
        self.assertEqual(candidate_sessions(a),[])
    def test_unknown_price_not_free(self):
        a=self.byid['diba_bibliotecas','agendabiblioteques460864789']
        self.assertEqual(a['price_text'],'')
        self.assertIn('UNKNOWN_PRICE_NOT_FREE',a['alerts'])
    def test_approximate_end(self):
        a=self.byid['generalitat','20251024004']
        self.assertIn('END_DATE_APPROXIMATE',a['alerts'])
    def test_explicit_time_formats(self):
        self.assertEqual(simple_times('19 h'),['19:00'])
        self.assertEqual(simple_times('A les 18.30 h'),['18:30'])
        self.assertEqual(simple_times('Dues funcions: 11 h 13 h'),['11:00','13:00'])
    def test_opening_hours_strict_rejection(self):
        for x in ('De 10 a 20 h','Dilluns 5, dimecres 7 i dissabte 10 a les 20 h',
                  'Consultar el programa','Tot el dia','De dilluns a divendres: 19 h'):
            self.assertEqual(simple_times(x),[],x)
    def test_bad_hours(self):
        self.assertEqual(simple_times('25 h'),[])
        self.assertEqual(simple_times('19:85 h'),[])
    def test_evidence_urls_preserved(self):
        a=self.byid['guiabcn','G39']
        self.assertTrue(a['url'].startswith('https://guia.barcelona.cat/'))
        self.assertIn('NO_PRIMARY_PAGE_SNAPSHOT',a['alerts'])
    def test_known_cross_source(self):
        pairs=match_pairs(self.records)
        self.assertTrue(any('2026071700013' in str(x) and 'G19' in str(x) for x in pairs))
    def test_known_diba_duplicated_session(self):
        pairs=match_pairs(self.records)
        self.assertTrue(any('456941545' in str(x) and '448613868' in str(x) for x in pairs))
    def test_generic_program_not_duplicate(self):
        pairs=match_pairs(self.records)
        self.assertFalse(any('423353450' in (x['a']+' '+x['b']) for x in pairs))
    def test_geo(self):
        self.assertAlmostEqual(geo_meters((41.39,2.17),(41.39,2.17)),0)
    def test_eligible_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);run(out=out)
            conn=sqlite3.connect(out/'loagendo_v12.sqlite3')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM publication_approved').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM candidate_occurrences').fetchone()[0],41)
            conn.close()
    def test_idempotency_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);m1=run(out=out);m2=run(out=out)
            self.assertEqual(m1['database_row_counts'],m2['database_row_counts'])
            self.assertEqual(m2['database_row_counts']['source_records'],369)
            db=sqlite3.connect(out/'loagendo_v12.sqlite3')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM source_records WHERE LENGTH(raw_sha256)=64').fetchone()[0],369)
            db.close()
    def test_source_sample_2026_horizon(self):
        for x in self.records:
            self.assertTrue(day(x['end'])>=day('2026-10-10') and day(x['start'])<day('2027-01-08'))

if __name__=='__main__':unittest.main()
