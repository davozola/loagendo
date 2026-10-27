import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.dedupe import candidate_pairs, duplicates_for, refresh_match_candidates
from src.pipeline import connect


def record(source, id, title, start, end, venue='', coords=None, kind='single'):
    return {'source': source, 'id': id, 'key': f'{source}:{id}', 'title': title, 'start': start, 'end': end, 'kind': kind,
            'eligibility': 'review', 'venues': [{'name': venue, 'coords': coords}] if venue or coords else []}


class DedupeTests(unittest.TestCase):
    def test_cross_source_pair_with_venue_alias_and_no_coordinates(self):
        a = record('web_cccb', 'x', 'Conversa "Pensar la ciutat" amb Marina Garcés', '2026-10-20', '2026-10-20', 'CCCB')
        b = record('guiabcn', '1', "Conversa 'Pensar la ciutat' amb Marina Garcés", '2026-10-20', '2026-10-20', 'Centre de Cultura Contemporània de Barcelona (CCCB)', (41.383, 2.167))
        pairs = candidate_pairs([a, b])
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0]['a'], pairs[0]['b']), ('guiabcn:1', 'web_cccb:x'))
        self.assertIn('VENUE_MATCHED_BY_NAME_ONLY', pairs[0]['risks'])
        self.assertTrue(pairs[0]['review_only'])

    def test_blocking_rejects_different_dates_far_venues_and_generic_titles(self):
        a = record('web_cccb', 'x', 'Concert de tardor', '2026-10-20', '2026-10-20', 'CCCB', (41.383, 2.167))
        later = record('guiabcn', '1', 'Concert de tardor', '2026-11-02', '2026-11-02', 'CCCB', (41.383, 2.167))
        far = record('guiabcn', '2', 'Concert de tardor', '2026-10-20', '2026-10-20', 'Auditori de Sant Martí', (41.41, 2.20))
        same_source = record('web_cccb', 'y', 'Concert de tardor', '2026-10-20', '2026-10-20', 'CCCB', (41.383, 2.167))
        pairs = candidate_pairs([a, later, far, same_source])
        self.assertEqual(pairs, [])

    def test_refresh_is_idempotent_and_keeps_snapshot_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            rows = [('web_cccb', 'x', 'Projecció "Nostalgia de la luz"', '2026-10-20', '2026-10-20'),
                    ('guiabcn', '1', "Projecció 'Nostalgia de la luz'", '2026-10-20', '2026-10-20'),
                    ('guiabcn', '9', 'Taller de ceràmica', '2026-10-21', '2026-10-21')]
            for source, id, title, start, end in rows:
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, id, title, start, end, 'single', 'review', 'x', '', 'h', '{}'))
                conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (source, id, 0, 'CCCB', '', 41.383, 2.167))
            conn.execute("INSERT INTO match_candidates VALUES ('old:a','old:b',0.9,'SNAPSHOT')")
            conn.commit()
            first = refresh_match_candidates(conn, since='2026-10-01', now='2026-10-12T00:00:00+00:00')
            second = refresh_match_candidates(conn, since='2026-10-01', now='2026-10-13T00:00:00+00:00')
            self.assertEqual((first['pairs'], second['pairs']), (1, 1))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM match_candidates').fetchone()[0], 2)
            generated = conn.execute("SELECT generated_by,generated_at FROM match_candidates WHERE a='guiabcn:1'").fetchone()
            self.assertEqual(generated, ('dedupe-blocked-v1', '2026-10-13T00:00:00+00:00'))
            self.assertEqual(conn.execute("SELECT generated_by FROM match_candidates WHERE a='old:a'").fetchone()[0], 'snapshot-pipeline')
            dup = duplicates_for(conn, 'web_cccb', 'x')
            self.assertEqual([d['key'] for d in dup], ['guiabcn:1'])
            self.assertEqual(dup[0]['title'], "Projecció 'Nostalgia de la luz'")
            conn.close()


class CollapseTests(unittest.TestCase):
    def test_same_day_same_place_pairs_with_lower_title_bar_and_collapses_to_licensed_source(self):
        from src.dedupe import canonical_groups
        a = record('generalitat', 'g1', 'Gustavo Dudamel – Filharmònica de Nova York', '2026-10-12', '2026-10-12', "L'Auditori", (41.399, 2.185))
        b = record('opendatabcn_agenda', '99', 'Concert "Gustavo Dudamel", amb la Filarmònica de Nova York', '2026-10-12', '2026-10-12', 'Sala 1 Pau Casals', (41.3990, 2.1851))
        c = record('web_auditori', 'w1', 'Gustavo Dudamel - Filarmónica de Nueva York', '2026-10-12', '2026-10-12', 'Sala 1 Pau Casals')
        other_day = record('guiabcn', 'x', 'Gustavo Dudamel – Filharmònica de Nova York', '2026-10-13', '2026-10-13', "L'Auditori", (41.399, 2.185))
        pairs = candidate_pairs([a, b, c, other_day])
        keys = {(p['a'], p['b']) for p in pairs}
        self.assertIn(('generalitat:g1', 'opendatabcn_agenda:99'), keys)
        self.assertIn(('opendatabcn_agenda:99', 'web_auditori:w1'), keys)
        self.assertNotIn(('guiabcn:x', 'opendatabcn_agenda:99'), keys)
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for r in (a, b, c, other_day):
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (r['source'], r['id'], r['title'], r['start'], r['end'], 'single', 'review', 'x', '', 'h', '{}'))
                for v in r['venues']:
                    conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (r['source'], r['id'], 0, v['name'], '', *(v['coords'] or (None, None))))
            conn.commit()
            refresh_match_candidates(conn, since='2026-10-01')
            groups = canonical_groups(conn)
            # Desde el 26-10-2026 manda la web propia de la sala (L'Auditori); las demás rellenan lo que le falta.
            self.assertEqual(groups, {'generalitat:g1': 'web_auditori:w1', 'opendatabcn_agenda:99': 'web_auditori:w1'})
            from mvp import catalog
            catalog.initialize(conn); catalog.invalidate_cache()
            public = catalog.query_events(conn, day='2026-10-12', public=True)
            self.assertEqual([e['key'] for e in public['items']], ['web_auditori:w1'])
            self.assertEqual(sorted(public['items'][0]['also_in']), ['generalitat:g1', 'opendatabcn_agenda:99'])
            self.assertIsNotNone(public['items'][0]['coordinates'])   # la web no las da: de un gemelo
            everything = catalog.query_events(conn, day='2026-10-12')
            hidden = next(e for e in everything['items'] if e['key'] == 'generalitat:g1')
            self.assertEqual(hidden['superseded_by'], 'web_auditori:w1')
            self.assertEqual(everything['total'], 3)
            catalog.invalidate_cache(); conn.close()


if __name__ == '__main__':
    unittest.main()


class SourceRankTests(unittest.TestCase):
    def test_directories_rank_below_venues_and_ticketing(self):
        from src.dedupe import source_rank
        self.assertLess(source_rank('opendatabcn_agenda'), source_rank('venue_sala_apolo'))
        self.assertLess(source_rank('venue_sala_apolo'), source_rank('venue_eventbrite'))
        self.assertLess(source_rank('venue_eventbrite'), source_rank('venue_songkick'))
        self.assertLess(source_rank('venue_songkick'), source_rank('web_conciertos_club'))

    def test_two_directories_with_different_times_collapse_and_show_both_times(self):
        from src.dedupe import canonical_groups
        a = record('venue_songkick', 's1', 'The Lemon Twigs', '2026-10-15', '2026-10-15', 'Paral·lel 62')
        b = record('web_conciertos_club', 'c1', 'The Lemon Twigs', '2026-10-15', '2026-10-15', 'Sala Paral·lel 62')
        c = record('venue_songkick', 's2', 'Erik Urano', '2026-10-15', '2026-10-15', 'Upload')
        d = record('web_conciertos_club', 'c2', 'Erik Urano', '2026-10-15', '2026-10-15', 'Sala Upload Barcelona')
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for r, t in ((a, '19:00'), (b, '21:00'), (c, '20:30'), (d, '19:30')):
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (r['source'], r['id'], r['title'], r['start'], r['end'], 'single', 'review', 'x', 'https://x.test/' + r['id'], 'h', '{}'))
                conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (r['source'], r['id'], 0, r['venues'][0]['name'], '', None, None))
                conn.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)', (r['source'], r['id'], r['start'], t, 'single', 'schema.org/startDate'))
            conn.commit()
            refresh_match_candidates(conn, since='2026-10-01')
            self.assertEqual(canonical_groups(conn), {'web_conciertos_club:c1': 'venue_songkick:s1', 'web_conciertos_club:c2': 'venue_songkick:s2'})
            from mvp import catalog
            catalog.initialize(conn); catalog.invalidate_cache()
            public = catalog.query_events(conn, day='2026-10-15', public=True)
            by_title = {e['title']: e for e in public['items']}
            self.assertEqual(set(by_title), {'The Lemon Twigs', 'Erik Urano'})
            self.assertEqual((by_title['The Lemon Twigs']['time_label'], by_title['The Lemon Twigs']['time_conflicts']), ('Por confirmar · 19:00 / 21:00', {'2026-10-15': ['19:00', '21:00']}))
            self.assertEqual(by_title['Erik Urano']['confirmations'], 2)
            catalog.invalidate_cache(); conn.close()

    def test_same_dates_same_place_and_a_rare_name_collapse_despite_different_titles(self):
        from src.dedupe import canonical_groups
        a = record('generalitat', 'g', 'MIRA Digital Arts Festival', '2026-11-06', '2026-11-07', 'Fira de Barcelona-Recinte Montjuïc', (41.3739, 2.1505))
        b = record('opendatabcn_agenda', 'o', 'MIRA Festival 2026', '2026-11-06', '2026-11-07', 'Fira Barcelona', (41.3727, 2.1502))
        c = record('guiabcn', 'x', 'Festival de tardor', '2026-11-06', '2026-11-07', 'Fira Barcelona', (41.3727, 2.1502))
        pairs = candidate_pairs([a, b, c])
        keys = {(p['a'], p['b']): p for p in pairs}
        self.assertIn(('generalitat:g', 'opendatabcn_agenda:o'), keys); self.assertIn('SAME_DATES_SAME_PLACE_RARE_TOKEN', keys[('generalitat:g', 'opendatabcn_agenda:o')]['risks'])
        self.assertNotIn(('guiabcn:x', 'opendatabcn_agenda:o'), keys)  # "festival" alone is not a rare name
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for r in (a, b, c):
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (r['source'], r['id'], r['title'], r['start'], r['end'], 'program', 'review', 'x', '', 'h', '{}'))
                for v in r['venues']: conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (r['source'], r['id'], 0, v['name'], '', *(v['coords'] or (None, None))))
            conn.commit(); refresh_match_candidates(conn, since='2026-10-01')
            self.assertEqual(canonical_groups(conn), {'generalitat:g': 'opendatabcn_agenda:o'})
            conn.close()

    def test_sibling_groups_that_differ_only_in_a_number_never_collapse(self):
        a = record('guiabcn', '1', "Taller 'Dansa clàssica infantil (de 7 a 9 anys)'", '2026-10-01', '2026-12-20', 'Centre Cívic Navas', (41.42, 2.19))
        b = record('opendatabcn_agenda', '2', "Taller 'Dansa clàssica infantil (de 5 a 7 anys)'", '2026-10-01', '2026-12-20', 'Centre Cívic Navas', (41.42, 2.19))
        self.assertEqual(candidate_pairs([a, b]), [])
        c = record('web_auditori', 'w', 'Rèquiem de Verdi', '2026-11-02', '2026-11-02', 'Sala 1 Pau Casals')
        d = record('opendatabcn_agenda', '3', 'Concert "Rèquiem de Verdi", de Giuseppe Verdi', '2026-11-02', '2026-11-02', "L'Auditori", (41.399, 2.185))
        pairs = candidate_pairs([c, d])
        self.assertEqual(len(pairs), 1); self.assertIn('SAME_DAY_SAME_PLACE', pairs[0]['risks'])  # the hall's rooms resolve to the hall
