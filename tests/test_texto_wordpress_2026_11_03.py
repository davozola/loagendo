"""Texto del acto en webs WordPress/Divi con el título después del contenido (3-11-2026, La Violeta: «En Patufet»)."""
import unittest

from src import organizer_text as ot

PAGE = ('<html><head><meta property="og:description" content="En Patufet és tan petit que sembla un cigronet, quan va pel carrer va vigilant que no el trapitgin."></head><body>'
        '<div id="gal-post-content" class="et_pb_with_border et_pb_module et_pb_post_content et_pb_post_content_0_tb_body">'
        '<p class="has-text-align-center"><a href="https://www.entrapolis.com/x"><strong>FES-TE AMB LA TEVA ENTRADA!</strong></a></p>'
        '<p class="wp-block-paragraph">Patim, patam, pat&#8230;uff! és una adaptació d&#8217;uns 45 minuts de durada inspirat en el conte tradicional català d&#8217;en Patufet '
        'L’espectacle: barreja titelles, cançons, humor i una alta dosi d&#8217;improvisació i participació del públic.<br>El personatge es diu Miquel Llopis.</p></div>'
        '<div class="et_pb_post_title"><h1>En Patufet</h1></div><footer><p>Uneix-te al nostre butlletí i rep les novetats de La Violeta cada mes, sense compromís.</p></footer></body></html>')


class TextoWordPress(unittest.TestCase):
    def test_lee_el_bloque_de_contenido(self):
        text, _ = ot.body_text(PAGE, 'En Patufet')
        self.assertIn('barreja titelles, cançons, humor', text); self.assertNotIn('FES-TE', text); self.assertNotIn('butlletí', text)

    def test_vuelve_a_leer_los_textos_cortos(self):
        self.assertIn("o.status='ok' AND length(o.text)<?", open('src/organizer_text.py', encoding='utf-8').read())


if __name__ == '__main__':
    unittest.main()
