"""Formato de la salida, código de salida y opciones."""

import contextlib
import io
import os
import re
import tempfile
import unittest
from unittest import mock

from comun import (META_DATA, NETWORK_CONFIG, SCRIPT, USER_DATA, Claves, cd, escribir,
                   leer, necesita_yaml)


class TestFormato(unittest.TestCase):

    def test_ok_en_una_linea(self):
        r = cd.ok("Existe user-data", arreglo="nada", seccion="preliminar")
        self.assertEqual(cd.formatear_resultado(r), ["  OK     Existe user-data"])

    def test_error_completo(self):
        r = cd.error("La clave no es la del servidor", fallo="B5", detalle=["huella"],
                     efecto="no entrará.", arreglo="cópiela.", seccion="preliminar")
        self.assertEqual(cd.formatear_resultado(r), [
            "  ERROR  La clave no es la del servidor [B5]",
            "         huella",
            "         Efecto: no entrará.",
            "         Cómo arreglarlo: cópiela.",
            "         Manual: sección 5.4.1 (Pasos preliminares)",
        ])

    def test_sin_arreglo_si_solo_se_senala(self):
        r = cd.aviso("Algo", arreglo="hágalo así.")
        with mock.patch.object(cd, "MOSTRAR_ARREGLO", False):
            self.assertEqual(cd.formatear_resultado(r), ["  AVISO  Algo"])

    def test_lineas_largas_con_sangria(self):
        r = cd.error("x" * 10, efecto=" ".join(["palabra"] * 30))
        lineas = cd.formatear_resultado(r)
        self.assertTrue(all(len(l) <= cd.ANCHO for l in lineas))
        self.assertTrue(all(l.startswith(" " * 9) for l in lineas[1:]))

    def test_todas_las_secciones_citadas_existen(self):
        citadas = set(re.findall(r'seccion="([^"]+)"', leer(SCRIPT)))
        citadas |= set(re.findall(r'"([a-z-]+)",\s*"meta-data": "', leer(SCRIPT)))
        self.assertTrue(citadas)
        for clave in citadas | set(cd.SECCION_DE.values()):
            self.assertIn(clave, cd.SECCIONES)

    def test_resumen_y_codigo(self):
        informe = cd.Informe()
        informe.bloque("Uno", [cd.ok("a"), cd.aviso("b")])
        self.assertEqual(informe.codigo_salida(), 0)
        self.assertIn("ningún ERROR y 1 AVISO", cd.formatear_informe(informe)[-1])
        informe.bloque("Dos", [cd.error("c"), cd.omitida("d")])
        self.assertEqual(informe.codigo_salida(), 1)
        self.assertIn("1 ERROR, 1 AVISO", cd.formatear_informe(informe)[-1])

    def test_omitida_no_cuenta(self):
        informe = cd.Informe()
        informe.bloque("Uno", [cd.omitida("d")])
        self.assertEqual(informe.codigo_salida(), 0)


class TestOpciones(unittest.TestCase):

    def test_maquina(self):
        for arg in ("server3", "3", "alu0000-server3"):
            self.assertEqual(cd.normalizar_maquina(arg, "alu0000"), "server3")

    def test_ip(self):
        self.assertEqual(str(cd.analizar_argumentos(["--ip", "192.168.7.9"])["ip"]),
                         "192.168.7.9")
        self.assertEqual(str(cd.analizar_argumentos(["--ip=192.168.7.9"])["ip"]),
                         "192.168.7.9")

    def test_errores_de_uso(self):
        for argv in (["--ip"], ["--ip", "nada"], ["--antes", "--acceso"],
                     ["-noautoconsole"], ["server1", "server2"]):
            with self.assertRaises(cd.ErrorDeUso):
                cd.analizar_argumentos(argv)

    def ejecutar_main(self, argv):
        salida, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = cd.main(argv)
        return codigo, salida.getvalue(), errores.getvalue()

    def test_version_y_ayuda(self):
        self.assertEqual(self.ejecutar_main(["--version"])[:2],
                         (0, "ci-diagnosis %s\n" % cd.VERSION))
        codigo, salida, _ = self.ejecutar_main(["--ayuda"])
        self.assertEqual(codigo, 0)
        self.assertIn("Uso: ci-diagnosis", salida)
        self.assertNotIn("prompt", salida.lower())

    def test_opcion_desconocida(self):
        codigo, _, errores = self.ejecutar_main(["--nada"])
        self.assertEqual(codigo, 2)
        self.assertIn("--ayuda", errores)

    @necesita_yaml
    def test_de_principio_a_fin(self):
        with tempfile.TemporaryDirectory() as home:
            os.mkdir(os.path.join(home, ".ssh"), 0o700)
            silo = os.path.join(home, "imagenesMV")
            os.mkdir(silo)
            Claves.preparar()
            with open(Claves.sin_frase, "rb") as f:
                escribir(os.path.join(home, ".ssh", "id_rsa"), f.read(), 0o600)
            escribir(os.path.join(home, ".ssh", "id_rsa.pub"), Claves.publica("sin_frase"))
            escribir(os.path.join(silo, "user-data"),
                     USER_DATA.format(clave=Claves.publica("sin_frase")))
            escribir(os.path.join(silo, "meta-data"), META_DATA)
            escribir(os.path.join(silo, "network-config"), NETWORK_CONFIG)
            entorno = {"HOME": home, "CI_DIAGNOSIS_USUARIO": "alu0000"}
            anterior = os.getcwd()
            try:
                os.chdir(silo)
                with mock.patch.dict(os.environ, entorno):
                    codigo, salida, _ = self.ejecutar_main([])
            finally:
                os.chdir(anterior)
        self.assertEqual(codigo, 0, salida)
        self.assertIn("máquina: alu0000-server1", salida)
        self.assertIn("Resultado: todo correcto.", salida)
        self.assertNotIn("\033[", salida)


if __name__ == "__main__":
    unittest.main()
