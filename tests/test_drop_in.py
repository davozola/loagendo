"""Sesiones sueltas (25-10-2026): la fuente dice que se puede ir a cualquier sesión."""
import unittest
from mvp.catalog import drop_in, needs_signup


class DropInTests(unittest.TestCase):
    def test_source_phrases(self):
        # 99400576434, observaciones de GuiaBCN
        self.assertTrue(drop_in("Joc familiar 'Jugatecambiental'", '', "Espai de joc lliure. · La reserva de l'activitat es realitza de manera presencial el mateix dia de l'activitat."))
        for text in ('Cada sessió és independent.', 'Las sesiones son independientes.', 'No cal reserva.', 'Accés lliure fins a completar aforament.'):
            self.assertTrue(drop_in('Taller', text), text)

    def test_weak_signal_needs_no_signup(self):
        self.assertEqual(drop_in('Taller de ioga', 'Taller trimestral. Cal inscripció prèvia.', 'Entrada lliure'), '')
        self.assertEqual(drop_in('Curs de dibuix', 'Matrícula: 45 €. Places limitades.'), '')

    def test_only_courses_and_workshops_need_signup(self):
        self.assertTrue(needs_signup({'kind': 'course', 'format': 'course'}))
        self.assertTrue(needs_signup({'kind': 'program', 'format': 'workshop'}))
        self.assertFalse(needs_signup({'kind': 'program', 'format': 'program'}))
        self.assertFalse(needs_signup({'kind': 'program', 'format': 'one_shot'}))
        self.assertFalse(needs_signup({'kind': 'program', 'format': 'workshop', 'drop_in': 'Cada sessió és independent.'}))
        self.assertFalse(needs_signup({'kind': 'course', 'format': 'course', 'open_enrollment': 'Inscripció oberta tot l\'any'}))


if __name__ == '__main__':
    unittest.main()
