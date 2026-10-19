"""Cartel (lineup): se guarda, se agrupa entre fuentes y se busca por artista."""
import json
import unittest

from mvp.catalog import lineup_of, merge_lineups
from src.dice_sitemap import page_lineup


class LineupTests(unittest.TestCase):
    def test_sources_and_dedupe(self):
        raw = {'loagendo': {'performers': ['Max Cooper', 'Fennesz'], 'xceed': {'lineup': ['fennesz', 'Arca']},
                            'ticketmaster': {'attractions': [{'name': 'Arca'}]}}}
        self.assertEqual(lineup_of(raw)[0], ['Max Cooper', 'Fennesz', 'Arca'])

    def test_grouped_record_gets_the_lineup_of_its_twins(self):
        events = [{'key': 'guiabcn:1', 'lineup': [], 'lineup_times': []},
                  {'key': 'venue_dice:a', 'superseded_by': 'guiabcn:1', 'lineup': ['Fennesz', 'Max Cooper'], 'lineup_times': []}]
        merge_lineups(events)
        self.assertEqual(events[0]['lineup'], ['Fennesz', 'Max Cooper'])

    def test_dice_next_data_gives_full_lineup_and_times(self):
        state = {'event': {'lineup': [{'name': 'Anthony Rother', 'performing_time': None}, {'name': 'Fennesz', 'performing_time': '2026-11-06T23:30:00+01:00'}]}}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'initialState': json.dumps(state)}}}) + '</script>'
        names, times = page_lineup(page)
        self.assertEqual(names, ['Anthony Rother', 'Fennesz'])
        self.assertEqual(times, [{'name': 'Fennesz', 'time': '23:30', 'raw': '2026-11-06T23:30:00+01:00'}])


class FestivalPairsTests(unittest.TestCase):
    def db(self, rows):
        import sqlite3
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE source_records (source, id, title, start_date, end_date, eligibility, raw_json)')
        c.execute('CREATE TABLE source_venues (source, id, seq, venue, lat, lon)')
        for source, rid, title, a, b, venue, lat, lon, lineup in rows:
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?)', (source, rid, title, a, b, 'review', json.dumps({'loagendo': {'performers': lineup}})))
            c.execute('INSERT INTO source_venues VALUES (?,?,0,?,?,?)', (source, rid, venue, lat, lon))
        return c

    CARTEL = ['Anthony Rother', 'E.a.r', 'Fennesz', 'Machine Girl', 'Martin Rev', 'Max Cooper', 'ML Buch', 'Nicola Cruz', 'Shygirl', 'Tortoise']

    def test_headliner_listing_and_festival_twins_join_the_festival(self):
        from src.dedupe import festival_pairs
        c = self.db([
            ('opendatabcn_agenda', '1', 'MIRA Festival 2099', '2099-11-06', '2099-11-07', 'Fira Montjuïc', 41.3732, 2.1510, []),
            ('venue_dice', 'm', 'MIRA 2099', '2099-11-06', '2099-11-08', 'Fira Montjuïc (MIRA Festival)', 41.3732, 2.1509, self.CARTEL),
            # Songkick: título = cabeza de cartel, coordenadas aproximadas a 2 km.
            ('venue_songkick', 'r', 'Anthony Rother', '2099-11-06', '2099-11-06', 'Fira Montjuic', 41.38506, 2.1734, self.CARTEL),
            # Mismo artista, otra sala y fuera del recinto: no se toca.
            ('venue_songkick', 'x', 'Fennesz', '2099-11-07', '2099-11-07', 'Sala Apolo', 41.3744, 2.1697, ['Fennesz']),
        ])
        pairs = set(festival_pairs(c))
        self.assertIn(('opendatabcn_agenda:1', 'venue_dice:m'), pairs)
        self.assertIn(('venue_songkick:r', 'venue_dice:m'), pairs)
        self.assertFalse(any('venue_songkick:x' in p for p in pairs))

    def test_parties_inside_a_festival_and_presentations_stay_apart(self):
        from src.dedupe import festival_pairs
        c = self.db([
            ('guiabcn', '1', 'Balla Barcelona Festival', '2099-10-30', '2099-11-01', 'Barcelona', None, None, []),
            ('venue_xceed', 'a', 'AFRODISE Halloween [Balla Barcelona Festival]', '2099-10-30', '2099-10-30', 'Barcelona', None, None, []),
            ('venue_songkick', 'v', 'Vida Festival 2099', '2099-07-01', '2099-07-03', 'Vilanova i la Geltrú', None, None, []),
            ('venue_dice', 'p', 'Festa presentació Vida Festival 2099', '2099-07-01', '2099-07-01', 'Vilanova i la Geltrú', None, None, []),
        ])
        self.assertEqual(festival_pairs(c), [])


class ActPairsTests(unittest.TestCase):
    def test_artist_listing_joins_the_full_concert_same_day_and_room(self):
        import sqlite3
        from src.dedupe import act_pairs
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE source_records (source, id, title, start_date, end_date, eligibility)')
        c.execute('CREATE TABLE source_venues (source, id, seq, venue, lat, lon)')
        for row in [('venue_songkick', 'a', 'Melendi', 'Palau Sant Jordi'), ('guiabcn', '1', 'Concert "Melendi"', 'Palau Sant Jordi'),
                    ('venue_songkick', 'j', 'Jamboree Jazz', 'Jamboree Jazz Club'), ('guiabcn', '2', 'Jamboree Jazz Night', 'Jamboree Jazz Club'),
                    ('venue_songkick', 'x', 'Fennesz', 'Sala Apolo'), ('guiabcn', '3', 'Concert "Fennesz"', 'Razzmatazz')]:
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?)', (row[0], row[1], row[2], '2099-11-01', '2099-11-01', 'review'))
            c.execute('INSERT INTO source_venues VALUES (?,?,0,?,NULL,NULL)', (row[0], row[1], row[3]))
        self.assertEqual(act_pairs(c), [('venue_songkick:a', 'guiabcn:1'), ('venue_songkick:j', 'guiabcn:2')])   # «Jamboree Jazz»: anuncio de la sala


class ConciertosClubTests(unittest.TestCase):
    def test_price_and_vendor_ticket_without_affiliate(self):
        from src.web_agendas import parse_conciertos_club
        page = ('<div itemscope itemprop="item" itemtype="http://schema.org/MusicEvent"><div class="time">S24/10/26<br>17:00</div>'
                '<span class="precio_wrap"><span class="precio" title="Precio entrada desde 28&euro;">28&euro;</span> '
                '<a class="comprarentradas" href="https://fever.pxf.io/c/3875474/1928078/16345?u=https%3A%2F%2Ffeverup.com%2Fm%2F592334">Comprar</a></span>'
                '<meta itemprop="startDate" content="2026-10-24T17:00"><meta itemprop="name" content="Ed Sheeran &amp; Coldplay. Candlelight. "><meta itemprop="url" content="https://conciertos.club/barcelona/conciertos/123461-x">'
                '<div itemprop="location" itemscope itemtype="http://schema.org/Place"><meta itemprop="name" content="Real Círculo Artístico de Barcelona">'
                '<meta itemprop="addressLocality" content="Barcelona, Barcelona"></div></div>')
        record = parse_conciertos_club(page)[0]
        self.assertEqual(record['price_text'], 'Desde 28 €')
        self.assertEqual(record['raw']['item']['ticket_url'], 'https://feverup.com/m/592334')


class TitlePairsTests(unittest.TestCase):
    def test_same_title_same_site_but_not_same_class_elsewhere(self):
        import sqlite3
        from src.dedupe import title_pairs
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE source_records (source, id, title, start_date, end_date, eligibility)')
        c.execute('CREATE TABLE source_venues (source, id, seq, venue, lat, lon)')
        c.execute('CREATE TABLE candidate_occurrences (source, id, local_date, local_time)')
        rows = [('generalitat', 'g', 'El Mago Pop', 'Teatre Victòria', 41.3740, 2.1680),
                ('guiabcn', '1', 'Espectacle "El Mago Pop"', 'Teatre Victòria', 41.3741, 2.1681),
                ('opendatabcn_agenda', 'a', "Taller 'Ioga'", 'Centre Cívic Can Felipa', 41.4040, 2.1990),
                ('opendatabcn_agenda', 'b', "Taller 'Ioga'", 'Centre Cívic El Carmel', 41.4220, 2.1550),
                ('guiabcn', 'r1', 'Itinerari de ciutat "La rosa de foc"', 'Centre Cívic Casa Golferichs', 41.3808, 2.1564),
                ('guiabcn', 'r2', "Itinerari de ciutat 'La rosa de foc'", 'Centre Cívic Ateneu Fort Pienc', 41.3970, 2.1820)]
        for source, rid, title, venue, lat, lon in rows:
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?)', (source, rid, title, '2099-11-01', '2099-11-01', 'review'))
            c.execute('INSERT INTO source_venues VALUES (?,?,0,?,?,?)', (source, rid, venue, lat, lon))
        for rid in ('r1', 'r2'): c.execute("INSERT INTO candidate_occurrences VALUES ('guiabcn',?,'2099-11-01','10:30')", (rid,))
        pairs = set(title_pairs(c))
        self.assertEqual(pairs, {('generalitat:g', 'guiabcn:1'), ('guiabcn:r1', 'guiabcn:r2')})


if __name__ == '__main__': unittest.main()
