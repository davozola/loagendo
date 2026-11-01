"""SEO (1-11-2026): páginas de entrada de todas las categorías, gratis y distritos; portada con planes de hoy y menú
completo; fichas con migas y enlaces a su categoría, día y distrito."""
import datetime as dt
import unittest
from pathlib import Path

from src import landings

TODAY = dt.date(2026, 11, 1)
ROOT = Path(__file__).resolve().parents[1]


def item(**kw):
    return {'s': 'x', 'i': kw.pop('i', '1'), 't': kw.pop('t', 'Acto'), 'a': '2026-11-01', 'b': '2026-11-01', 'tm': '20:00', **kw}


class Paginas(unittest.TestCase):
    def test_todas_las_categorias_tienen_pagina(self):
        paths = {p['path'] for p in landings.pages(TODAY)}
        for path in landings.CAT_PAGE.values(): self.assertIn('/es' + path, paths)
        for path in ('/es/gratis', '/es/gratis/fin-de-semana', '/es/distrito/gracia', '/es/distrito/sant-marti/fin-de-semana'): self.assertIn(path, paths)

    def test_filtros_gratis_y_distrito(self):
        self.assertTrue(landings._matches(item(fr=1), {'free': True}))
        self.assertFalse(landings._matches(item(), {'free': True}))
        self.assertTrue(landings._matches(item(d='Gràcia'), {'district': 'Gràcia'}))
        self.assertFalse(landings._matches(item(d='Eixample'), {'district': 'Gràcia'}))

    def test_portada_con_planes_de_hoy_y_menu(self):
        block = landings.home_block(TODAY, {'2026-11-01': {'items': [item(t='Concierto de prueba', pc='musica')]}})
        self.assertIn('id="seoLista"', block); self.assertIn('Concierto de prueba', block); self.assertNotIn('<h1', block)
        for path in ('/es/cine', '/es/gratis', '/es/distrito/eixample', '/es/conciertos/fin-de-semana'): self.assertIn(f'href="{path}"', block)

    def test_la_app_conoce_las_paginas_nuevas(self):
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn("LANDING.district", js); self.assertIn("LANDING.free === true", js)
        for path in landings.CAT_PAGE.values(): self.assertIn(f"'/es{path}'", js)

    def test_la_ficha_enlaza_y_quita_la_lista_de_la_portada(self):
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertIn("BreadcrumbList", fn); self.assertIn("'#seoLista'", fn); self.assertIn("/distrito/", fn); self.assertIn("og:type\" content=\"${card.x ? 'website' : 'event'}", fn)
        for path in landings.CAT_PAGE.values(): self.assertIn(f"'/es{path}'", fn)
        for slug in landings.DISTRICTS: self.assertIn(f"'{slug}'", fn)


class Idiomas(unittest.TestCase):
    def test_tres_versiones_con_direcciones_propias(self):
        es = {p['base']: p for p in landings.pages(TODAY, 'es')}; ca = {p['base']: p for p in landings.pages(TODAY, 'ca')}; en = {p['base']: p for p in landings.pages(TODAY, 'en')}
        self.assertEqual(ca['/conciertos/fin-de-semana']['path'], '/concerts/cap-de-setmana')   # el catalán en la raíz (1-11-2026)
        self.assertEqual(en['/con-ninos/noviembre-2026']['path'], '/en/with-kids/november-2026')
        self.assertEqual(ca['/hoy']['title'], 'Què fer avui a Barcelona · Ontoca')
        self.assertEqual(es['/gratis']['alts'], {'es': '/es/gratis', 'ca': '/gratis', 'en': '/en/free'})
        paths = [p['path'] for p in landings.all_pages(TODAY)]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(landings.file_for('/'), 'index.html'); self.assertEqual(landings.file_for('/es/'), 'es/index.html')

    def test_render_con_hreflang_e_idioma(self):
        from tests.test_landings import INDEX
        page = next(p for p in landings.pages(TODAY, 'en') if p['base'] == '/gratis')
        doc = landings.render(INDEX, page, {}, 'https://ontoca.com')
        self.assertIn('<html lang="en"', doc); self.assertIn('data-lang="en" data-base="/en"', doc)
        for l, u in (('es', '/es/gratis'), ('ca', '/gratis'), ('en', '/en/free'), ('x-default', '/gratis')):
            self.assertIn(f'hreflang="{l}" href="https://ontoca.com{u}"', doc)
        self.assertIn('href="/en/e/', landings.home_block(TODAY, {'2026-11-01': {'items': [item()]}}, 'en'))

    def test_mes(self):
        page = next(p for p in landings.pages(TODAY) if p['base'] == '/noviembre-2026')
        self.assertEqual(page['landing']['range'], 'm2026-11'); self.assertEqual(page['days'][-1], dt.date(2026, 11, 30))
        self.assertEqual(page['title'], 'Qué hacer en Barcelona en noviembre de 2026 · Ontoca')
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn('m(\\d{4})-(\\d{2})', js)

    def test_la_app_y_la_ficha_conocen_los_idiomas(self):
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn('dataset.lang', js); self.assertIn('dataset.base', js); self.assertIn('hreflang="${next}"', js)
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertIn('alias_of', fn); self.assertIn('301', fn); self.assertIn('venue_upcoming', fn); self.assertIn('hreflang="x-default"', fn)
        for l in ('es', 'en'):
            self.assertIn("from '../../e/[[path]].js'", (ROOT / 'functions' / l / 'e' / '[[path]].js').read_text(encoding='utf-8'))
        self.assertIn('301', (ROOT / 'functions' / 'ca' / 'e' / '[[path]].js').read_text(encoding='utf-8'))   # /ca/e/… → /e/…


class SinRastro(unittest.TestCase):
    def test_direcciones_con_nombre_publico(self):
        self.assertEqual(landings.public_source('venue_ia_teatreneu'), 'sala_teatreneu')
        self.assertEqual(landings.public_source('guiabcn'), 'guiabcn')
        self.assertEqual(landings.event_path({'s': 'venue_ia_zumzeig', 'i': 'x1'}, 'en'), '/en/e/sala_zumzeig/x1')
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8'); fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertIn('toInternal', js); self.assertIn('toInternal', fn); self.assertIn("'sala_'", (ROOT / 'functions' / 'cal' / '[[path]].js').read_text(encoding='utf-8'))

    def test_campos_neutros_en_lo_publicado(self):
        from src import publish_static
        detail = {'ai_quotes': {'time': 'a les 19 h'}, 'price_source': 'ia_texto', 'age_source': 'ia', 'media': [], 'links': [], 'hours_by_day': {}, 'notes_by_day': {}}
        out = publish_static.public_detail(detail, None)
        self.assertFalse([k for k in out if 'ai' in k.split('_')]); self.assertEqual(out['quotes'], {'time': 'a les 19 h'})
        self.assertEqual((out['price_source'], out['age_source']), ('texto', 'texto'))

    def test_robots_y_minificado(self):
        from src import publish_static
        for bot in ('GPTBot', 'CCBot', 'ClaudeBot', 'Google-Extended'): self.assertIn(bot, publish_static.ROBOTS_BLOCKED)
        self.assertNotIn('Googlebot', publish_static.ROBOTS_BLOCKED); self.assertNotIn('OAI-SearchBot', publish_static.ROBOTS_BLOCKED)
        self.assertIn('public.js', publish_static.MINIFY)


class Renderizado(unittest.TestCase):
    """Lo que ve Google al ejecutar JavaScript con /data/ bloqueado (1-11-2026, revisión del consultor)."""
    def test_sin_datos_se_queda_el_html_sin_aviso_de_error(self):
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn("document.getElementById('seoLista') || document.getElementById('seoFicha') ? ''", js)
        self.assertIn('let fichaPending = false;', js); self.assertIn('if (fichaPending) return;', js)

    def test_404_de_verdad(self):
        from tests.test_landings import INDEX
        doc = landings.not_found(INDEX, TODAY)
        self.assertIn('<meta name="robots" content="noindex">', doc); self.assertNotIn('rel="canonical"', doc)
        self.assertIn('href="/avui"', doc); self.assertIn('<html lang="ca"', doc)   # en catalán (1-11-2026, 21:43)

    def test_un_solo_salto_en_duplicados(self):
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertLess(fn.index('detail.alias_of && detail.alias_of !== key'), fn.index('if (toPublic(shown) !== shown)'))


class ValidacionProduccion(unittest.TestCase):
    """Lo encontrado al validar en producción (1-11-2026)."""
    def test_paginas_con_filtro_usan_el_catalogo(self):
        days = {'2026-11-01': {'items': [item(i='1', pc='musica')]}}
        cat = [{'s': 'x', 'i': '2', 't': 'Expo larga', 'a': '2026-09-01', 'b': '2027-01-01', 'kd': 'exhibition', 'pc': 'arte'},
               {'s': 'x', 'i': '3', 't': 'Taller de un día', 'a': '2026-11-01', 'b': '2026-11-01', 'kd': 'single', 'pc': 'talleres'},
               {'s': 'x', 'i': '4', 't': 'Curso largo', 'a': '2026-10-01', 'b': '2027-06-01', 'kd': 'course', 'pc': 'talleres'}]
        dd = landings.with_catalog(days, cat)
        expos = next(p for p in landings.pages(TODAY) if p['base'] == '/exposiciones/hoy')
        talleres = next(p for p in landings.pages(TODAY) if p['base'] == '/talleres/hoy')
        hoy = next(p for p in landings.pages(TODAY) if p['base'] == '/hoy')
        self.assertIn('Expo larga', landings.listing(expos, dd))
        self.assertIn('Taller de un día', landings.listing(talleres, dd)); self.assertNotIn('Curso largo', landings.listing(talleres, dd))
        self.assertNotIn('Taller de un día', landings.listing(hoy, dd))   # sin filtro, la primera página del día tal cual

    def test_event_proxima_sesion_y_sin_hreflang_si_ya_paso(self):
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertIn('Programación larga ya empezada', fn); self.assertIn("const alternates = card.x ? '' :", fn)


class EnlacesDeLaApp(unittest.TestCase):
    def test_filas_y_seleccion_son_enlaces(self):
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn('<a class="ev-main" href="${esc(eventPath(k))}" data-open=', js)
        self.assertIn('<a class="pick-small" href="${esc(eventPath(key(e)))}" data-open=', js)
        self.assertIn("a[data-quickcat],a[data-period],a[data-open]')) { if (e.metaKey", js)


class CalidadEntradas(unittest.TestCase):
    def test_dia_de_hoy_y_manana_apuntan_a_hoy_y_manana(self):
        ps = {p['base']: p for p in landings.pages(TODAY, 'en')}
        self.assertEqual(ps['/dia/2026-11-01']['canonical'], '/en/today'); self.assertEqual(ps['/dia/2026-11-02']['canonical'], '/en/tomorrow')
        self.assertEqual(ps['/dia/2026-11-03']['canonical'], '/en/day/2026-11-03')

    def test_sin_actos_noindex_y_fuera_del_sitemap(self):
        from tests.test_landings import INDEX
        page = next(p for p in landings.pages(TODAY) if p['base'] == '/gratis')
        self.assertIn('noindex,follow', landings.render(INDEX, page, {}, 'https://ontoca.com'))
        days = {'2026-11-01': {'items': [item(fr=1)]}}
        paths = landings.indexable_paths(TODAY, days)
        self.assertIn('/es/gratis/hoy', paths); self.assertIn('/gratis/avui', paths); self.assertNotIn('/es/cine/hoy', paths); self.assertNotIn('/es/dia/2026-11-01', paths)


class PilotoSalas(unittest.TestCase):
    CAT = [{'s': 'x', 'i': str(n), 't': f'Concierto {n}', 'a': f'2026-11-{n + 2:02d}', 'b': f'2026-11-{n + 2:02d}', 'kd': 'single', 'pc': 'musica',
            'v': ['Sala Apolo' if n % 2 else 'Sala Apolo · La [2]'], 'd': 'Sants-Montjuïc'} for n in range(6)]

    def test_paginas_de_sala_en_tres_idiomas(self):
        pages = {p['path']: p for p in landings.venue_pages(TODAY, self.CAT)}
        self.assertEqual(pages['/es/sala/sala-apolo']['count'], 6)
        self.assertIn('/en/venue/sala-apolo', pages); self.assertIn('/sala/sala-apolo', pages)   # catalán en la raíz
        self.assertEqual(pages['/es/sala/sala-apolo']['landing']['q'], 'Sala Apolo')
        self.assertIn('Sobre todo conciertos y música (6 de 6', pages['/es/sala/sala-apolo']['lead'])
        self.assertEqual(pages['/es/sala/liceu']['count'], 0)
        idx = landings.indexable_paths(TODAY, {}, self.CAT)
        self.assertIn('/es/sala/sala-apolo', idx); self.assertNotIn('/es/sala/liceu', idx)

    def test_la_ficha_enlaza_con_su_sala(self):
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        for slug, name, _ in landings.VENUES: self.assertIn(f"'{slug}'", fn)
        self.assertIn("venue: v => `Programación de ${v}`", fn)


if __name__ == '__main__':
    unittest.main()
