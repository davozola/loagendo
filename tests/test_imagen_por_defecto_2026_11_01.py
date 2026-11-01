"""Imagen por defecto de la web (1-11-2026): no es la del acto; Filmoteca lleva la foto en la cabecera."""
import sqlite3
import unittest

from src import ai_agenda, official_images
from src.media import is_event_image, is_site_default

FILM = ('<html><head><meta property="og:image" content="http://cultura.gencat.cat/web/resources/fwk/comuns/img/avatar.jpg"></head><body>'
        '<img src="/web/themes/custom/filmoteca/dist/images/logo-filmoteca.png" alt="Filmoteca de Catalunya">'
        '<img class="img-responsive w100" src="/web/sites/default/files/styles/subcapcalera_continguts_1900x660/public/2026-10/007_lo.jpg?itok=x" alt="24 eyes">'
        '</body></html>')


class PorDefecto(unittest.TestCase):
    def test_imagenes_de_la_web(self):
        for url in ('http://cultura.gencat.cat/web/resources/fwk/comuns/img/avatar.jpg', 'https://salavol.com/wp-content/themes/vol/public/imgs/thumbnail.png',
                    'https://espaitexas.cat/wp-content/uploads/2023/10/espai-texas-imatge-rrss-copia.png', 'https://teatremuntaner.com/og.jpg',
                    'https://zumzeigcine.coop//site/templates/img/sm.jpg'):
            self.assertTrue(is_site_default(url), url); self.assertFalse(is_event_image(url, 'x'))

    def test_imagenes_de_acto(self):
        for url in ('https://www.palaumusica.cat/images/1657731/production_listing.jpg', 'https://jamboreejazz.com/wp-content/uploads/2026/10/04-2026-Jamboree.jpg',
                    'https://www.filmoteca.cat/web/sites/default/files/styles/subcapcalera_continguts_1900x660/public/2026-10/007_lo.jpg'):
            self.assertFalse(is_site_default(url), url)

    def test_filmoteca_cabecera(self):
        conn = sqlite3.connect(':memory:'); ai_agenda.initialize(conn)
        conn.execute("INSERT INTO ai_agenda_images(url,image,fetched_at) VALUES(?,?,?)",
                     ('https://www.filmoteca.cat/web/ca/film/nijushi-no-hitomi', 'http://cultura.gencat.cat/web/resources/fwk/comuns/img/avatar.jpg', '2026-11-01T17:00:00+00:00'))
        image, fetched = ai_agenda._image(conn, 'https://www.filmoteca.cat/web/ca/film/nijushi-no-hitomi',
                                          lambda u, t: (200, u, FILM), 10, 'Nijushi no hitomi')
        self.assertTrue(fetched)   # la imagen por defecto guardada se vuelve a mirar
        self.assertIn('/styles/subcapcalera_continguts_1900x660/', image)

    def test_ficha_con_imagen_por_defecto_la_busca(self):
        d = {'title': 'X', 'media': [{'url': '/img/1.jpg', 'credit': {'original_url': 'http://cultura.gencat.cat/web/resources/fwk/comuns/img/avatar.jpg'}}]}
        self.assertTrue(official_images.needs_image(d))
        d['media'][0]['credit']['original_url'] = 'https://www.palaumusica.cat/images/1/production_listing.jpg'
        self.assertFalse(official_images.needs_image(d))


if __name__ == '__main__':
    unittest.main()
