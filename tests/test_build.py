"""El archivo distribuible: al día, compatible con Python 3.8 y solo de lectura."""

import ast
import os
import subprocess
import sys
import tempfile
import unittest

from comun import RAIZ, SCRIPT, cd, leer


class TestDistribuible(unittest.TestCase):

    def test_al_dia_con_los_fuentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            salida = os.path.join(tmp, "ci-diagnosis")
            subprocess.run([sys.executable, os.path.join(RAIZ, "tools", "build.py"), salida],
                           check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(leer(salida), leer(SCRIPT),
                             "ci-diagnosis no está al día: ejecute python3 tools/build.py")

    def test_primera_linea(self):
        # El python3 del sistema, que es el que tiene el módulo libvirt
        self.assertEqual(leer(SCRIPT).split("\n", 1)[0], "#!/usr/bin/python3")

    def test_ejecutable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_sintaxis_de_python_3_8(self):
        ast.parse(leer(SCRIPT), feature_version=(3, 8))


# Llamadas que escribirían o cambiarían algo
PROHIBIDAS_OS = {"remove", "unlink", "rename", "replace", "rmdir", "mkdir", "makedirs",
                 "chmod", "chown", "lchown", "link", "symlink", "truncate", "system",
                 "popen", "kill", "utime", "removedirs", "renames"}


class TestSoloLee(unittest.TestCase):
    """Revisión estática: el programa no tiene con qué escribir."""

    @classmethod
    def setUpClass(cls):
        cls.arbol = ast.parse(leer(SCRIPT))

    def test_sin_llamadas_de_os_que_escriben(self):
        for nodo in ast.walk(self.arbol):
            if (isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name)
                    and nodo.value.id == "os"):
                self.assertNotIn(nodo.attr, PROHIBIDAS_OS, "os.%s en la línea %d"
                                 % (nodo.attr, nodo.lineno))

    def test_sin_shutil_ni_tempfile(self):
        texto = leer(SCRIPT)
        self.assertNotIn("import shutil", texto)
        self.assertNotIn("import tempfile", texto)

    def test_open_solo_para_leer(self):
        for nodo in ast.walk(self.arbol):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id == "open"):
                modos = [a for a in nodo.args[1:2]] + [k.value for k in nodo.keywords
                                                         if k.arg == "mode"]
                for m in modos:
                    self.assertIsInstance(m, ast.Constant, "modo de open no literal")
                    self.assertNotRegex(m.value, "[wax+]", "open para escribir, línea %d"
                                        % nodo.lineno)

    def test_subprocess_solo_en_ejecutar(self):
        for funcion in ast.walk(self.arbol):
            if not isinstance(funcion, ast.FunctionDef) or funcion.name == "ejecutar":
                continue
            for nodo in ast.walk(funcion):
                if isinstance(nodo, ast.Name):
                    self.assertNotEqual(nodo.id, "subprocess",
                                        "subprocess fuera de ejecutar(), en %s" % funcion.name)

    def test_ejecutar_rechaza_ordenes_fuera_de_la_lista(self):
        for orden in (["virsh", "list"], ["rm", "-f", "x"], ["sh", "-c", "true"]):
            with self.assertRaises(ValueError):
                cd.ejecutar(orden)

    def test_ejecutar_con_lc_all_c(self):
        # ssh-keygen sin argumentos válidos: el mensaje sale en inglés
        codigo, _, err = cd.ejecutar(["ssh-keygen", "-l", "-f", "/no/existe"])
        self.assertNotEqual(codigo, 0)
        self.assertIn("No such file", err)


if __name__ == "__main__":
    unittest.main()
