"""Catalán en la raíz (1-11-2026, 21:25): ontoca.com/ en catalán, /es/ y /en/; las direcciones de antes redirigen."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src import landings

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 1)


class CatalanEnLaRaiz(unittest.TestCase):
    def test_direcciones(self):
        self.assertEqual(landings.localize('/', 'ca'), '/'); self.assertEqual(landings.localize('/', 'es'), '/es/')
        self.assertEqual(landings.localize('/hoy', 'ca'), '/avui'); self.assertEqual(landings.localize('/hoy', 'es'), '/es/hoy')
        self.assertEqual(landings.localize('/con-ninos/noviembre-2026', 'en'), '/en/with-kids/november-2026')
        self.assertIn('hreflang="x-default" href="https://ontoca.com/avui"', landings.alternates({l: landings.localize('/hoy', l) for l in landings.LANGS}, 'https://ontoca.com'))

    def test_redirecciones_de_las_direcciones_de_antes(self):
        r = landings.redirects(TODAY).splitlines()
        for line in ('/hoy /es/hoy 301', '/conciertos/fin-de-semana /es/conciertos/fin-de-semana 301', '/ca / 301', '/ca/ / 301', '/ca/* /:splat 301', '/v2 / 301'):
            self.assertIn(line, r)
        self.assertEqual(r[-1], '/ca/* /:splat 301')   # la regla general, al final
        # La dirección antigua castellana que hoy es una página catalana no se redirige (/gratis, /dia/…, /sala/…).
        self.assertFalse([l for l in r if l.startswith(('/gratis ', '/dia/', '/sala/'))])
        self.assertLess(len(r), 2000)   # límite de Cloudflare Pages

    def test_publicar_borra_las_paginas_de_antes_y_escribe_redirects(self):
        from tests.test_landings import INDEX
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'hoy.html').write_text('vieja'); (out / 'ca').mkdir(); (out / 'ca' / 'avui.html').write_text('vieja')
            landings.write_all(out, INDEX, {}, 'https://ontoca.com', TODAY)
            self.assertFalse((out / 'hoy.html').exists()); self.assertFalse((out / 'ca').exists())
            self.assertTrue((out / 'avui.html').exists()); self.assertTrue((out / 'es' / 'hoy.html').exists()); self.assertTrue((out / 'es' / 'index.html').exists())
            self.assertIn('/hoy /es/hoy 301', (out / '_redirects').read_text())
            self.assertIn('<html lang="ca" data-lang="ca" data-base=""', (out / 'index.html').read_text())

    def test_funciones_y_app(self):
        fn = (ROOT / 'functions' / 'e' / '[[path]].js').read_text(encoding='utf-8')
        self.assertIn("const PREFIX = {es: '/es', ca: '', en: '/en'};", fn); self.assertIn("eventPath(key, 'ca')", fn)
        self.assertIn('Response.redirect', (ROOT / 'functions' / 'ca' / 'e' / '[[path]].js').read_text(encoding='utf-8'))
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        self.assertIn("const pre = {es: '/es', ca: '', en: '/en'}", js); self.assertIn('\\/es|\\/en)?\\/e\\/', js)



class CatalanaEnAlma(unittest.TestCase):
    def test_404_en_catalan(self):
        from tests.test_landings import INDEX
        doc = landings.not_found(INDEX, TODAY)
        self.assertIn('<title>Pàgina no trobada · Ontoca</title>', doc); self.assertIn('Aquesta pàgina ja no existeix', doc)
        self.assertIn('data-lang="ca" data-base=""', doc); self.assertNotIn('Esta página ya no existe', doc)

    def test_interfaz_traducida_en_el_html(self):
        index = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        ca = landings.translate_shell(index, 'ca'); en = landings.translate_shell(index, 'en')
        self.assertIn('data-i18n="Saltar a la agenda">Salta a l', ca); self.assertIn('placeholder="Artista, sala, barri, obra…"', ca)
        self.assertIn('aria-label="Canvia la data o l’horari"', ca); self.assertIn('aria-label="Seccions"', ca)
        self.assertIn('placeholder="Artist, venue, neighbourhood, show…"', en)
        self.assertEqual(landings.translate_shell(index, 'es'), index)
        self.assertNotIn('Buscar en la agenda<', ca)


    def test_paginas_legales_por_idioma(self):
        from src import legal_pages
        ca = legal_pages.page_html('privacidad', lang='ca', site_url='https://ontoca.com')
        self.assertIn('<html lang="ca"', ca); self.assertIn('<title>Privacitat · Ontoca</title>', ca); self.assertNotIn('<section lang="es">', ca)
        self.assertIn('rel="canonical" href="https://ontoca.com/privacitat"', ca); self.assertIn('hreflang="x-default" href="https://ontoca.com/privacitat"', ca)
        r = landings.redirects(TODAY).splitlines()
        for line in ('/aviso-legal /es/aviso-legal 301', '/privacidad /es/privacidad 301', '/creditos /es/creditos 301'): self.assertIn(line, r)
        index = landings.translate_shell((ROOT / 'static' / 'index.html').read_text(encoding='utf-8'), 'ca')
        self.assertIn('href="/es/privacidad" data-legal="privacidad"', (ROOT / 'static' / 'index.html').read_text(encoding='utf-8'))
        doc = landings._lang_attrs((ROOT / 'static' / 'index.html').read_text(encoding='utf-8'), 'ca')
        self.assertIn('href="/privacitat" data-legal="privacidad"', doc); self.assertIn('>Avís legal<', doc)


if __name__ == '__main__':
    unittest.main()
