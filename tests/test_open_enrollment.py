import unittest
from mvp.catalog import open_enrollment


class OpenEnrollment(unittest.TestCase):
    def test_lo_dice_la_fuente(self):
        for text in ["Taller de ceràmica. Inscripció oberta tot l'any al centre cívic.",
                     'Curso de yoga. Puedes incorporarte en cualquier momento del curso.',
                     'Club de lectura. Activitat gratuïta, sense inscripció prèvia.',
                     'Matrícula abierta todo el año.']:
            self.assertTrue(open_enrollment('Taller', text), text)

    def test_no_lo_dice(self):
        for text in ['Inscripció prèvia obligatòria. Places limitades.', 'Inscripción abierta hasta el 3 de octubre.', 'Curs trimestral.']:
            self.assertEqual(open_enrollment('Curs', text), '', text)

    def test_guarda_la_cita(self):
        self.assertIn('qualsevol moment', open_enrollment('Ioga', 'Us podeu incorporar en qualsevol moment del trimestre.'))


if __name__ == '__main__': unittest.main()
