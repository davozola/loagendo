"""Traducciones (1-11-2026): el modelo devolvía el original en el campo «text»; ahora «translation» y una copia no vale."""
import json
import unittest

from src import ai_translate as t


class Traduccion(unittest.TestCase):
    def setUp(self):
        self.parse = t.parser_for('en')
        self.src = {'text': "Concert de jazz a la sala gran amb el quartet de la ciutat, entrada lliure fins a completar l'aforament."}

    def test_campo_nuevo(self):
        self.assertIn('translation', json.dumps(t.tool_for('en')))
        self.assertIn('never copy', t.system_for('en'))

    def test_copia_del_original_no_vale(self):
        out, score, note = self.parse({'n': 1, 'source_lang': 'ca', 'translation': self.src['text']}, self.src)
        self.assertEqual(score, 0.0); self.assertEqual(note, 'sin traducir')
        self.assertFalse(json.loads(out)['ok'])

    def test_traduccion_buena(self):
        en = 'Jazz concert in the main hall with the city quartet, free entry until full capacity.'
        out, score, _ = self.parse({'n': 1, 'source_lang': 'ca', 'translation': en}, self.src)
        self.assertEqual(json.loads(out)['text'], en)

    def test_respuesta_antigua_sigue_leyendose(self):
        en = 'Jazz concert in the main hall with the city quartet, free entry until full capacity.'
        out, _, _ = self.parse({'n': 1, 'source_lang': 'ca', 'text': en}, self.src)
        self.assertEqual(json.loads(out)['text'], en)


if __name__ == '__main__':
    unittest.main()
