"""Clasificación pública: 8 categorías, 5 canales, correcciones editoriales e informe (19-10-2026)."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import taxonomy
from src.pipeline import connect

ROOT = Path(__file__).resolve().parents[1]


def ev(title, **kw):
    base = {'title': title, 'source': 'guiabcn', 'kind': 'single', 'format': 'one_shot', 'category': '', 'venue_names': [],
            'classification_paths': [], 'start': '2026-10-20', 'end': '2026-10-20', 'family_audience': False, 'lineup': []}
    return {**base, **kw}


class ClassifyTests(unittest.TestCase):
    def cat(self, *a, **kw): return taxonomy.classify(ev(*a, **kw))

    def test_genre_at_title_start_decides_and_is_confirmed(self):
        for title, want in (("Concert de jazz 'Trio X'", 'musica'), ('Espectacle de dansa "Assembly Hall"', 'escena'),
                            ('Projecció "Miss Carbón"', 'cine'), ("Taller 'Ceràmica'", 'talleres'), ("Xerrada 'Dones i ciutat'", 'charlas'),
                            ('Itinerari de ciutat "Les tradicions de Nadal"', 'charlas'), ('Festa Major de Sants', 'fiestas'),
                            ('Mercat de Nadal', 'fiestas'), ('Cursa popular de Nou Barris', 'deporte')):
            out = self.cat(title)
            self.assertEqual((title, out['category'], out['status']), (title, want, 'confirmada'))
            self.assertTrue(out['evidence'])

    def test_every_exhibition_is_arte_including_science_and_history(self):
        for title in ("Exposició 'Fotografies de Gràcia'", "Exposició 'La vellesa a l'antic Egipte'", 'Mostra de biodiversitat urbana'):
            self.assertEqual(self.cat(title, kind='exhibition', format='exhibition')['category'], 'arte')

    def test_segment_after_programme_name_carries_the_genre(self):
        self.assertEqual(self.cat("Cicle 'Tardor Solidària': Xerrada 'La recepta'")['category'], 'charlas')
        self.assertEqual(self.cat('Barcelona Districte Cultural - Cicle \'Pantalla\': Cinema "Miss Carbón"')['category'], 'cine')

    def test_source_category_and_music_sources_give_probable(self):
        out = self.cat('L.E.O. + CHICO JORGE', source='venue_songkick')
        self.assertEqual((out['category'], out['status']), ('musica', 'probable'))
        out = self.cat('Miguel Miguel', source='web_teatre_lliure', category='Artes escénicas')
        self.assertEqual(out['category'], 'escena')

    def test_no_signal_or_services_stay_pending_never_others(self):
        for title in ('Grabada, escrita, pronunciada', 'Las piezas hablan'):
            out = self.cat(title, source='web_cccb')
            self.assertEqual((out['category'], out['status'], out['method']), ('pendiente', 'pendiente', 'sin_senal'))
        self.assertNotIn('otros', taxonomy.CATEGORIES)

    def test_editorial_rules_of_20_october(self):
        # Patios escolares abiertos: Talleres y experiencias, canal En familia.
        patis = ev('Patis escolars oberts: Escola Mireia')
        out = taxonomy.classify(patis)
        self.assertEqual((out['category'], out['method']), ('talleres', 'regla_editorial'))
        self.assertIn('familia', taxonomy.channels(patis, out['category']))
        # Servicios y ocio social: fuera de la agenda (no a la cola de pendientes).
        for title, source in (('Campanya de donació de sang', 'guiabcn'), ("Servei Punt TIC", 'guiabcn'),
                              ('Singles Night - Cocktails & Chemistry', 'venue_eventbrite'), ('Barcelona Pub Crawl: 3 Hosted Bars', 'venue_eventbrite'),
                              ('Barcelona Tech Job Fair 2027', 'venue_eventbrite')):
            self.assertEqual(self.cat(title, source=source)['category'], 'excluida', title)
        # Un género cultural explícito manda sobre la palabra suelta.
        self.assertEqual(self.cat("Concert 'Campanya de Nadal'")['category'], 'musica')
        # Grupos de apoyo: fuera (servicio, no plan).
        for title in ('Grup de suport per a persones cuidadores de persones amb demència', "'El barri proposa': Espai d'acompanyament al dol (Ens cuidem)"):
            self.assertEqual(self.cat(title)['category'], 'excluida', title)
        self.assertEqual(taxonomy.series_of('Patis escolars oberts al barri - Escola Bogatell'), 'patis-escolars-oberts')
        self.assertEqual(taxonomy.series_of('Concert de jazz'), '')
        # Comunidad y cuidados: Talleres + Vida de barrio.
        group = ev("'El barri proposa': Grup de dones autogestionat", venue_names=['Casal de Barri Comunitari'])
        out = taxonomy.classify(group)
        self.assertEqual((out['category'], out['method']), ('talleres', 'comunidad_y_cuidados'))
        self.assertIn('barrio', taxonomy.channels(group, 'talleres'))

    def test_conflicting_signals_are_flagged_ambiguous_but_published(self):
        out = self.cat("Taller 'Galetes de Nadal'", category='Fiestas y tradiciones')
        self.assertEqual(out['category'], 'talleres')
        out = self.cat('Visita dinamitzada "Fàbriques en joc"', kind='exhibition', format='exhibition')
        self.assertEqual((out['category'], out['ambiguous']), ('charlas', True))  # la visita es la actividad

    def test_precision_fixes_of_20_october(self):
        for title, kind, want in (("“Festes de Tardor de la Sagrada Família”: Visites a la tomba d’Antoni Gaudí", 'program', 'charlas'),
                                  ('Festa Major de Gràcia: Concert de la Cobla', 'single', 'musica'), ('Festa Major de Sants', 'program', 'fiestas'),
                                  ('Lletra petita - Sac de rondalles: Marató de contes infantils', 'single', 'escena'),
                                  ('Zurich Marató de Barcelona', 'single', 'deporte'), ('Cicle Coll Fantasy: Torneig de magic', 'single', 'talleres'),
                                  ('La Rauxa - Presentació de LP', 'single', 'musica'), ('Dissabtes familiars: Sessió de contes', 'single', 'escena'),
                                  ('Upgrade MEET&GREET Synthony', 'single', 'excluida')):
            self.assertEqual(self.cat(title, kind=kind)['category'], want, title)

    def test_editorial_override_wins(self):
        out = taxonomy.classify(ev('Grabada, escrita, pronunciada'), {'category': 'charlas', 'note': 'Ciclo de lecturas del CCCB'})
        self.assertEqual((out['category'], out['status'], out['method'], out['evidence']), ('charlas', 'editorial', 'correccion_editorial', 'Ciclo de lecturas del CCCB'))

    def test_override_can_exclude_and_services_and_news_are_excluded(self):
        out = taxonomy.classify(ev('Concert X'), {'category': 'excluida', 'note': 'No es en Barcelona'})
        self.assertEqual((out['category'], out['method']), ('excluida', 'correccion_editorial'))
        self.assertEqual(self.cat("Activitats Laborals Joves de Barcelona: Activa't per treballar!")['category'], 'excluida')
        self.assertEqual(self.cat('Cinc itineraris sorprenents amb el CC Urgell', source='web_centres_civics')['category'], 'excluida')
        self.assertEqual(self.cat("Concert 'Sons d'Horta'", source='web_centres_civics')['category'], 'musica')

    def test_legacy_filters_map_to_new_keys(self):
        self.assertEqual(taxonomy.legacy_filter('Conciertos'), ('musica', ''))
        self.assertEqual(taxonomy.legacy_filter('Familia'), ('', 'familia'))
        self.assertEqual(taxonomy.legacy_filter('arte', 'galerias'), ('arte', 'galerias'))
        with self.assertRaises(ValueError): taxonomy.legacy_filter('Otros')
        with self.assertRaises(ValueError): taxonomy.legacy_filter('', 'nocturno')


class ChannelTests(unittest.TestCase):
    def test_channels_are_multi_membership_with_evidence(self):
        e = ev('Festa Major de Gràcia: concert a la plaça', family_audience=True, venue_names=['Plaça del Sol'])
        out = taxonomy.channels(e, 'fiestas')
        self.assertEqual(set(out), {'familia', 'barrio', 'aire'})
        self.assertTrue(all(out.values()))

    def test_weekly_courses_at_civic_centres_are_not_neighbourhood_life(self):
        course = ev("Taller 'Pilates'", venue_names=['Centre Cívic Navas'], start='2026-10-01', end='2026-12-20', format='course')
        self.assertNotIn('barrio', taxonomy.channels(course, 'talleres'))
        # Endurecido 20-10: un centre cívic por sí solo no es vida de barrio; una entidad vecinal o el título sí.
        self.assertNotIn('barrio', taxonomy.channels(ev("Xerrada 'Gestió del temps'", venue_names=['Centre Cívic Navas']), 'charlas'))
        self.assertIn('barrio', taxonomy.channels(ev("Xerrada 'Gestió del temps'", venue_names=['Casal de Barri Comunitari Espai 210']), 'charlas'))
        self.assertIn('barrio', taxonomy.channels(ev("Cicle 'Fet al barri': Concert"), 'musica'))
        self.assertIn('barrio', taxonomy.channels(ev('Castanyada', venue_names=['Plaça del Diamant']), 'fiestas'))
        self.assertNotIn('barrio', taxonomy.channels(ev('Concert de jazz', venue_names=['Biblioteca Jaume Fuster']), 'musica'))

    def test_galleries_take_art_not_science_or_history_exhibitions(self):
        art = ev("Exposició 'Paisatges'", kind='exhibition', venue_names=['Galeria Joan Prats'])
        self.assertIn('galerias', taxonomy.channels(art, 'arte'))
        science = ev("Exposició 'Història de la ciència a Barcelona'", kind='exhibition', venue_names=['Museu de Ciències'])
        self.assertNotIn('galerias', taxonomy.channels(science, 'arte'))
        opening = ev("Inauguració 'Nous treballs'", venue_names=['Espai X'])
        self.assertIn('galerias', taxonomy.channels(opening, 'arte'))

    def test_festival_channel_takes_the_festival_not_each_show(self):
        self.assertIn('festivales', taxonomy.channels(ev('Festival Grec 2026', format='festival'), 'escena'))
        self.assertNotIn('festivales', taxonomy.channels(ev("Mostra de Teatre d'Horta: Teatre 'BNT'"), 'escena'))

    def test_override_adds_and_removes_channels(self):
        e = ev("Xerrada 'X'", family_audience=True)
        out = taxonomy.channels(e, 'charlas', {'channels_add': ['aire'], 'channels_remove': ['familia']})
        self.assertEqual(out, {'aire': 'Corrección editorial'})


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.conn = connect(Path(self.temp.name) / 't.sqlite3'); catalog.initialize(self.conn)
        for id, title in (('1', "Concert 'Cor de cambra'"), ('2', 'Grabada, escrita, pronunciada')):
            self.insert(id, title)
        catalog.invalidate_cache()

    def insert(self, id, title, h='h'):
        raw = {'name': title, 'addresses': [{'address_name': 'x', 'district_name': 'Eixample'}], 'loagendo': {}}
        self.conn.execute('INSERT OR REPLACE INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          ('opendatabcn_agenda', id, title, '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', h, json.dumps(raw)))
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def items(self, **kw): return {e['id']: e for e in catalog.query_events(self.conn, day='2026-10-20', **kw)['items']}

    def test_pending_records_are_kept_but_not_published(self):
        self.assertEqual(set(self.items()), {'1', '2'})                       # el panel ve todo
        self.assertEqual(set(self.items(public=True)), {'1'})                 # la web no muestra la pendiente
        self.assertEqual(self.items()['2']['public_category'], 'pendiente')

    def test_editorial_correction_survives_a_reimport_and_is_logged(self):
        taxonomy.set_override(self.conn, 'opendatabcn_agenda', '2', 'charlas', ['barrio'], [], 'Lectura pública')
        catalog.invalidate_cache()
        self.assertEqual(self.items(public=True)['2']['public_category'], 'charlas')
        self.insert('2', 'Grabada, escrita, pronunciada (nova data)', h='h2')  # la sincronización reescribe el registro
        catalog.invalidate_cache()
        got = self.items(public=True)['2']
        self.assertEqual((got['public_category'], got['category_status'], 'barrio' in got['channels']), ('charlas', 'editorial', True))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM classification_override_log').fetchone()[0], 1)
        with self.assertRaises(ValueError): taxonomy.set_override(self.conn, 'opendatabcn_agenda', '2', 'otros')

    def test_record_is_idempotent_and_logs_real_changes_only(self):
        events = catalog.all_events(self.conn)
        self.assertEqual(taxonomy.record(self.conn, events, now='t1'), 0)     # primera vez: alta, no cambio
        self.assertEqual(taxonomy.record(self.conn, events, now='t2'), 0)     # mismos datos: nada
        rows = self.conn.execute('SELECT COUNT(*), MAX(computed_at) FROM event_classification').fetchone()
        self.assertEqual(rows, (2, 't1'))
        taxonomy.set_override(self.conn, 'opendatabcn_agenda', '2', 'charlas'); catalog.invalidate_cache()
        self.assertEqual(taxonomy.record(self.conn, catalog.all_events(self.conn), now='t3'), 1)
        self.assertEqual(self.conn.execute('SELECT old_category,new_category FROM classification_changes').fetchall(), [('pendiente', 'charlas')])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM source_records').fetchone()[0], 2)  # nada importado se toca

    def test_report_counts_queue_and_coverage(self):
        rep = taxonomy.report(self.conn, catalog.all_events(self.conn), '2026-10-19')
        self.assertEqual((rep['eligible'], rep['published'], rep['pending']), (2, 1, 1))
        self.assertEqual(rep['categories']['musica']['count'], 1)
        self.assertEqual([q['id'] for q in rep['queue']], ['2'])
        self.assertEqual(rep['coverage'][0]['pct'], 50.0)


class PublicUiTests(unittest.TestCase):
    def test_front_end_labels_match_the_taxonomy_and_old_controls_are_gone(self):
        js = (ROOT / 'static' / 'public.js').read_text(); html = (ROOT / 'static' / 'index.html').read_text()
        for key, (es, ca) in {**taxonomy.CATEGORIES, **taxonomy.CHANNELS}.items():
            self.assertRegex(js, re.escape(f"{key}: ['{es}', '{ca}']") + '|' + re.escape(f'{key}: [\'{es}\', "{ca}"]'))
        self.assertNotIn('kidsOnly', html); self.assertNotIn('id="subtypes"', html); self.assertIn('id="channels"', html)
        self.assertNotIn('Otros', js)


if __name__ == '__main__':
    unittest.main()
