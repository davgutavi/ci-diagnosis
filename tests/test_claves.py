"""Claves SSH del servidor: B7, B10 y D6 del catálogo."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from comun import Claves, cd, con_estado, escribir, leer, problemas, texto_de


class TestFormato(unittest.TestCase):

    def test_publica_y_huella(self):
        clave = cd.analizar_clave_publica(Claves.publica("sin_frase"))
        self.assertEqual(clave.tipo, "ssh-rsa")
        self.assertEqual(clave.comentario, "alu0000@avantasia")
        self.assertRegex(clave.huella, r"^SHA256:[A-Za-z0-9+/]{43}$")

    def test_huella_igual_que_ssh_keygen(self):
        _, salida, _ = cd.ejecutar(["ssh-keygen", "-l", "-f", Claves.preparar().sin_frase + ".pub"])
        clave = cd.analizar_clave_publica(Claves.publica("sin_frase"))
        self.assertIn(clave.huella, salida)

    def test_privada_openssh(self):
        for nombre, cifrada in (("sin_frase", False), ("con_frase", True)):
            with open(getattr(Claves.preparar(), nombre), "rb") as f:
                formato, es_cifrada, publica = cd.analizar_privada(f.read())
            self.assertEqual((formato, es_cifrada), ("openssh", cifrada))
            self.assertEqual(publica.blob,
                             cd.analizar_clave_publica(Claves.publica(nombre)).blob)

    def test_privada_pem(self):
        for nombre, cifrada in (("pem", False), ("pem_frase", True)):
            with open(getattr(Claves.preparar(), nombre), "rb") as f:
                self.assertEqual(cd.analizar_privada(f.read()), ("pem", cifrada, None))

    def test_texto_que_no_es_clave(self):
        self.assertIsNone(cd.analizar_clave_publica("ssh-rsa"))
        self.assertIsNone(cd.analizar_clave_publica("ssh-rsa no-es-base64!"))
        self.assertEqual(cd.analizar_privada(b"hola"), (None, None, None))


class TestComprobarClaves(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.ssh = os.path.join(self.home, ".ssh")
        os.mkdir(self.ssh, 0o700)
        entorno = {k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"}
        self.entorno = mock.patch.dict(os.environ, entorno, clear=True)
        self.entorno.start()

    def tearDown(self):
        self.entorno.stop()
        self.tmp.cleanup()

    def instalar(self, nombre, pub=None):
        """Copia la pareja de prueba como ~/.ssh/id_rsa(.pub)."""
        origen = getattr(Claves.preparar(), nombre)
        shutil.copy(origen, os.path.join(self.ssh, "id_rsa"))
        os.chmod(os.path.join(self.ssh, "id_rsa"), 0o600)
        shutil.copy(getattr(Claves, pub or nombre) + ".pub",
                    os.path.join(self.ssh, "id_rsa.pub"))

    def agente(self, codigo, salida=""):
        os.environ["SSH_AUTH_SOCK"] = "/tmp/agente-de-prueba"
        return mock.patch.object(cd, "ejecutar", return_value=(codigo, salida, ""))

    def test_sin_frase(self):
        self.instalar("sin_frase")
        rs, clave = cd.comprobar_claves(self.home)
        self.assertEqual(problemas(rs), [])
        self.assertIn("no tiene frase de paso", texto_de(rs))
        self.assertEqual(clave.comentario, "alu0000@avantasia")

    def test_no_son_pareja(self):
        self.instalar("sin_frase", pub="portatil")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.ERROR, "B7")])

    def test_no_son_pareja_aunque_tenga_frase(self):
        # La cabecera openssh-key-v1 da la pública sin pedir la frase
        self.instalar("con_frase", pub="sin_frase")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertIn("B7", [r.fallo for r in con_estado(rs, cd.ERROR)])

    def test_permisos_abiertos(self):
        self.instalar("sin_frase")
        os.chmod(os.path.join(self.ssh, "id_rsa"), 0o644)
        rs, _ = cd.comprobar_claves(self.home)
        errores = con_estado(rs, cd.ERROR)
        self.assertEqual([r.fallo for r in errores], ["B10"])
        self.assertIn("0644", errores[0].texto)

    def test_sin_publica_con_otra_de_otro_tipo(self):
        escribir(os.path.join(self.ssh, "id_ed25519.pub"), "ssh-ed25519 AAAA x\n")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertIn("id_ed25519.pub", texto_de(rs))
        self.assertEqual(rs[0].fallo, "B7")

    def test_sin_privada(self):
        self.instalar("sin_frase")
        os.rename(os.path.join(self.ssh, "id_rsa"), os.path.join(self.ssh, "otra"))
        rs, clave = cd.comprobar_claves(self.home)
        self.assertTrue(any("No existe ~/.ssh/id_rsa" in r.texto for r in rs))
        self.assertIsNotNone(clave)

    def test_sin_publica_vale_la_de_la_privada(self):
        self.instalar("sin_frase")
        os.rename(os.path.join(self.ssh, "id_rsa.pub"), os.path.join(self.ssh, "otra.pub"))
        _, clave = cd.comprobar_claves(self.home)
        self.assertEqual(clave.blob,
                         cd.analizar_clave_publica(Claves.publica("sin_frase")).blob)

    def test_pem_sin_frase_usa_ssh_keygen(self):
        self.instalar("pem")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertEqual(problemas(rs), [])
        self.assertIn("son pareja", texto_de(rs))

    def test_pem_con_frase_no_se_puede_comprobar(self):
        self.instalar("pem_frase")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertEqual(len(con_estado(rs, cd.OMITIDA)), 1)

    def test_frase_sin_agente(self):
        self.instalar("con_frase")
        rs, _ = cd.comprobar_claves(self.home)
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "D6")])

    def test_frase_con_la_clave_en_el_agente(self):
        self.instalar("con_frase")
        with self.agente(0, Claves.publica("con_frase") + "\n"):
            rs, _ = cd.comprobar_claves(self.home)
        self.assertEqual(problemas(rs), [])

    def test_agente_con_otras_claves(self):
        # Por ejemplo, el de su ordenador, si entró con ssh -A
        self.instalar("con_frase")
        with self.agente(0, Claves.publica("portatil") + "\n"):
            rs, _ = cd.comprobar_claves(self.home)
        self.assertIn("1 clave(s) de otro origen", texto_de(rs))

    def test_agente_vacio(self):
        self.instalar("con_frase")
        with self.agente(1, "The agent has no identities.\n"):
            rs, _ = cd.comprobar_claves(self.home)
        self.assertIn("ninguna clave cargada", texto_de(rs))

    def test_agente_inaccesible(self):
        self.instalar("con_frase")
        with self.agente(2):
            rs, _ = cd.comprobar_claves(self.home)
        self.assertIn("No se puede consultar el agente", texto_de(rs))

    def test_nunca_muestra_la_privada(self):
        self.instalar("con_frase", pub="sin_frase")
        rs, _ = cd.comprobar_claves(self.home)
        salida = texto_de(rs)
        for linea in leer(os.path.join(self.ssh, "id_rsa")).split("\n")[1:-2]:
            self.assertNotIn(linea[:20], salida)


if __name__ == "__main__":
    unittest.main()
