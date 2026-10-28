from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.test import SimpleTestCase


class RequisitosContrasenaTests(SimpleTestCase):
    def test_rechaza_falta_de_mayuscula_numero_o_simbolo(self):
        for clave in ('palabrasegura123!', 'PalabraSegura!', 'PalabraSegura123'):
            with self.subTest(clave=clave), self.assertRaises(ValidationError):
                validate_password(clave)

    def test_rechaza_similitud_con_nombre(self):
        usuario = User(username='municipalidad', first_name='Vicente')
        with self.assertRaises(ValidationError):
            validate_password('Municipalidad123!', usuario)

    def test_acepta_clave_que_cumple_requisitos(self):
        validate_password('BosqueAzul739!')
