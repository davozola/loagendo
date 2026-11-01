"""Imagen de la página propia del acto sin og:image (1-11-2026, Filmoteca): la cabecera con el título como alt."""
import sqlite3
import unittest

from src import ai_agenda

PAGE = ('<html><head><title>One Battle After Another | Filmoteca</title></head><body>'
        '<img src="/web/themes/custom/filmoteca/dist/images/logo-filmoteca.png" alt="Filmoteca de Catalunya">'
        '<img src="/web/sites/default/files/styles/subcapcalera/public/2026-09/One%20Battle.jpg?itok=x" alt="One Battle After Another Una batalla tras otra">'
        '<img src="/web/sites/default/files/2024-02/twitterX.png" alt="X"></body></html>')
URL = 'https://www.filmoteca.cat/web/ca/film/one-battle-after-another'


class ImagenDeContenido(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:'); ai_agenda.initialize(self.conn); self.calls = 0

    def fetch(self, url, timeout):
        self.calls += 1; return 200, url, PAGE

    def test_cabecera_con_el_titulo(self):
        image, fetched = ai_agenda._image(self.conn, URL, self.fetch, 10, 'One Battle After Another')
        self.assertEqual(image, 'https://www.filmoteca.cat/web/sites/default/files/styles/subcapcalera/public/2026-09/One%20Battle.jpg?itok=x')
        self.assertTrue(fetched)
        self.assertEqual(ai_agenda._image(self.conn, URL, self.fetch, 10, 'One Battle After Another'), (image, False))
        self.assertEqual(self.calls, 1)

    def test_logos_e_imagenes_de_otro_acto_no(self):
        self.assertEqual(ai_agenda.content_image(PAGE, 'Filmoteca'), '')   # el logo, nunca
        self.assertEqual(ai_agenda.content_image(PAGE, 'Nijushi no hitomi'), '')

    def test_lo_vacio_de_antes_se_vuelve_a_mirar(self):
        self.conn.execute("INSERT INTO ai_agenda_images VALUES (?,?,?)", (URL, '', '2026-10-20T17:01:07+00:00'))
        image, fetched = ai_agenda._image(self.conn, URL, self.fetch, 10, 'One Battle After Another')
        self.assertTrue(image.endswith('One%20Battle.jpg?itok=x')); self.assertTrue(fetched)

    def test_sin_respuesta_no_se_guarda(self):
        image, _ = ai_agenda._image(self.conn, URL, lambda u, t: (0, u, ''), 10, 'One Battle After Another')
        self.assertEqual(image, ''); self.assertIsNone(self.conn.execute('SELECT 1 FROM ai_agenda_images').fetchone())


class OtrasSalas(unittest.TestCase):
    LISTING = ('<div><a href="x?evento=3046"><img id-ficha="3168" src="https://ph.test/eventos/JPg000a1.jpg" /></a><div>PREESTRENO: DUNE PARTE TRES (Proyección en Dolby Atmos, 4K y VOSE)</div></div>'
               '<div><a href="x?evento=3045"><img id-ficha="3213" src="https://ph.test/eventos/JPg000i7.jpg" /></a><!-- <div>SINOPSIS</div> --><div>DUNE (1984) (Proyección en 4K y VOSE)</div><b>1984</b></div>')

    def test_listado_imagen_seguida_de_su_titulo(self):   # Phenomena
        self.assertTrue(ai_agenda.content_image(self.LISTING, 'DUNE (1984) (Proyección en 4K y VOSE)', listing=True).endswith('i7.jpg'))
        self.assertTrue(ai_agenda.content_image(self.LISTING, 'PREESTRENO: DUNE PARTE TRES (Proyección en Dolby Atmos, 4K y VOSE)', listing=True).endswith('a1.jpg'))
        self.assertEqual(ai_agenda.content_image(self.LISTING, 'LA LLEGADA (Proyección en VOSE)', listing=True), '')

    def test_nombre_del_fichero(self):   # Santa Mònica, Disseny Hub
        self.assertTrue(ai_agenda.content_image('<img class="image" src="/content/dam/2026/ptitecouti.png"/>', 'Ptitécouti'))
        self.assertTrue(ai_agenda.content_image('<img src="/files/casa_bloc-interiorcomedor-f_xavi.jpg" alt="">', '48 H OPEN HOUSE | Visita a la Casa Bloc'))
        self.assertEqual(ai_agenda.content_image('<img src="/img/concert.jpg">', 'Concert'), '')   # palabra de cartel, no del acto


if __name__ == '__main__':
    unittest.main()
