"""Comprobación de la traducción automática (23-10-2026)."""
import unittest

from src.ai_translate import check


class TranslateCheckTest(unittest.TestCase):
    SRC = "El MIRA és un festival d'arts digitals que es celebra a Barcelona des de 2011. Amb Max Cooper i Fennesz. Entrades a https://mirafestival.com"

    def test_faithful_translation_passes(self):
        en = "MIRA is a digital arts festival held in Barcelona since 2011. With Max Cooper and Fennesz. Tickets at https://mirafestival.com"
        self.assertEqual(check(self.SRC, en), (True, []))

    def test_lost_number_name_or_link_fails(self):
        ok, problems = check(self.SRC, "MIRA is a digital arts festival held in Barcelona. With Max Cooper and friends. Tickets online.")
        self.assertFalse(ok)
        self.assertTrue(any('números' in p for p in problems)); self.assertTrue(any('enlaces' in p for p in problems))

    def test_invented_number_fails(self):
        ok, problems = check("Taller per a infants amb la Laia.", "Workshop for children aged 6 to 10 with Laia.")
        self.assertFalse(ok); self.assertTrue(any('nuevos' in p for p in problems))

    def test_empty_and_length(self):
        self.assertFalse(check(self.SRC, '')[0])
        self.assertFalse(check(self.SRC, 'MIRA festival, Barcelona 2011, Max Cooper, Fennesz, https://mirafestival.com')[0])


if __name__ == '__main__':
    unittest.main()
