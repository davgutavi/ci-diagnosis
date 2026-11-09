"""tools/ci-diagnosis-admin: argumentos, silos y máquinas del alumno, directorio
y la orden de sudo. No ejecuta sudo: se comprueba la orden que se lanzaría."""

import ast
import importlib.machinery
import importlib.util
import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import comun  # noqa: F401  (prepara sys.dont_write_bytecode)
import falso_libvirt as fl

ADMIN = os.path.join(comun.RAIZ, "tools", "ci-diagnosis-admin")
UVUS = comun.UVUS


def cargar_admin():
    cargador = importlib.machinery.SourceFileLoader("ci_diagnosis_admin", ADMIN)
    spec = importlib.util.spec_from_loader("ci_diagnosis_admin", cargador)
    modulo = importlib.util.module_from_spec(spec)
    cargador.exec_module(modulo)
    return modulo


adm = cargar_admin()


class TestArgumentos(unittest.TestCase):
    def test_ayuda(self):
        self.assertEqual(adm.analizar_argumentos([]), ("ayuda",))
        self.assertEqual(adm.analizar_argumentos(["--ayuda"]), ("ayuda",))

    def test_actualizar(self):
        self.assertEqual(adm.analizar_argumentos(["--actualizar"]), ("actualizar",))
        with self.assertRaises(adm.ErrorDeUso):
            adm.analizar_argumentos(["--actualizar", UVUS])

    def test_alumno_y_resto_tal_cual(self):
        self.assertEqual(adm.analizar_argumentos([UVUS, "server2", "--acceso", "--ip", "1.2.3.4"]),
                         (UVUS, None, ["server2", "--acceso", "--ip", "1.2.3.4"]))

    def test_dir(self):
        self.assertEqual(adm.analizar_argumentos([UVUS, "--dir", "/x/y", "1"]),
                         (UVUS, "/x/y", ["1"]))
        with self.assertRaises(adm.ErrorDeUso):
            adm.analizar_argumentos([UVUS, "--dir"])

    def test_uvus_obligatorio_y_valido(self):
        for malo in (["--antes"], ["Alu 0"], ["alu;rm"], ["../x"]):
            with self.assertRaises(adm.ErrorDeUso, msg=malo):
                adm.analizar_argumentos(malo)


class TestLibvirt(unittest.TestCase):
    def conexion(self):
        home = "/home/" + UVUS
        return fl.Conexion(
            silos=[fl.Silo(UVUS + "-imagenesMV", home + "/imagenesMV"),
                   fl.Silo("imagenesMV-2", home + "/descargas", activo=False),
                   fl.Silo("alu0001-imagenesMV", "/home/alu0001/imagenesMV"),
                   fl.Silo("default", "/var/lib/libvirt/images")],
            dominios=[fl.Dominio(UVUS + "-server1", activo=True),
                      fl.Dominio(UVUS + "-server2"),
                      fl.Dominio("alu0001-server1", activo=True),
                      fl.Dominio("oautoconsole")])

    def test_silos_por_nombre_y_por_ruta(self):
        silos = adm.silos_del_alumno(self.conexion(), UVUS, "/home/" + UVUS)
        self.assertEqual(silos, [
            (UVUS + "-imagenesMV", "/home/%s/imagenesMV" % UVUS, True),
            ("imagenesMV-2", "/home/%s/descargas" % UVUS, False)])

    def test_no_confunde_un_home_con_otro_que_empieza_igual(self):
        conn = fl.Conexion(silos=[fl.Silo("x", "/home/%s1/imagenesMV" % UVUS)])
        self.assertEqual(adm.silos_del_alumno(conn, UVUS, "/home/" + UVUS), [])

    def test_maquinas(self):
        self.assertEqual(adm.maquinas_del_alumno(self.conexion(), UVUS),
                         [(UVUS + "-server1", True), (UVUS + "-server2", False)])


class TestDirectorio(unittest.TestCase):
    home = "/home/" + UVUS

    def elegir(self, silos, existen):
        return adm.elegir_directorio(UVUS, self.home, silos, existe=lambda r: r in existen)

    def test_su_silo_primero(self):
        silos = [(UVUS + "-imagenesMV", "/home/%s/imagenesMVl" % UVUS, True)]
        self.assertEqual(self.elegir(silos, {"/home/%s/imagenesMVl" % UVUS,
                                             self.home + "/imagenesMV"}),
                         "/home/%s/imagenesMVl" % UVUS)

    def test_sin_silo_con_su_nombre_imagenesMV(self):
        silos = [("imagenesMV-2", self.home + "/otro", True)]
        self.assertEqual(self.elegir(silos, {self.home + "/imagenesMV", self.home + "/otro"}),
                         self.home + "/imagenesMV")

    def test_su_unico_silo(self):
        silos = [("imagenesMV", self.home + "/vms", True)]
        self.assertEqual(self.elegir(silos, {self.home + "/vms"}), self.home + "/vms")

    def test_si_no_su_home(self):
        silos = [("a", self.home + "/a", True), ("b", self.home + "/b", True)]
        self.assertEqual(self.elegir(silos, {self.home + "/a", self.home + "/b"}), self.home)
        self.assertEqual(self.elegir([], set()), self.home)


class TestOrden(unittest.TestCase):
    def test_orden_sudo(self):
        orden = adm.orden_sudo(UVUS, "/home/alu0000/imagenesMV", ["server1", "--acceso"])
        self.assertEqual(orden[:6], ["sudo", "-u", UVUS, "-H", "--", "/bin/bash"])
        self.assertEqual(orden[-4:], ["ci-diagnosis", "/home/alu0000/imagenesMV",
                                      "server1", "--acceso"])

    def test_el_lanzador_entra_en_el_directorio_y_pasa_los_argumentos(self):
        # El lanzador, sin sudo y con un programa de prueba por la entrada estándar
        with tempfile.TemporaryDirectory() as d:
            lanzador = adm.LANZADOR.replace("/usr/bin/python3", shlex.quote(sys.executable))
            r = subprocess.run(["/bin/bash", "-c", lanzador, "ci-diagnosis", d, "a b", "--x"],
                               input=b"import os, sys; print(os.getcwd()); print(sys.argv[1:])",
                               stdout=subprocess.PIPE)
            salida = r.stdout.decode().splitlines()
            self.assertEqual(os.path.realpath(salida[0]), os.path.realpath(d))
            self.assertEqual(salida[1], "['a b', '--x']")

    def test_main_lanza_ci_diagnosis_como_el_alumno(self):
        conn = fl.Conexion(silos=[fl.Silo(UVUS + "-imagenesMV", "/no/existe")])
        usuario = mock.Mock(pw_dir="/home/" + UVUS)
        with fl.instalado(conn), \
                mock.patch.dict(os.environ, {"CI_DIAGNOSIS": comun.SCRIPT}), \
                mock.patch.object(adm.pwd, "getpwnam", return_value=usuario), \
                mock.patch.object(adm.subprocess, "run",
                                  return_value=mock.Mock(returncode=1)) as run, \
                redirect_stdout(io.StringIO()) as salida:
            codigo = adm.main([UVUS, "server1"])
        self.assertEqual(codigo, 1)
        orden = run.call_args[0][0]
        self.assertEqual(orden[2], UVUS)
        self.assertEqual(orden[-2:], ["/home/%s" % UVUS, "server1"])
        self.assertEqual(run.call_args[1]["stdin"].name, comun.SCRIPT)
        self.assertIn("Alumno: %s" % UVUS, salida.getvalue())
        self.assertTrue(conn.cerrada)

    def test_usuario_inexistente(self):
        with mock.patch.object(adm.pwd, "getpwnam", side_effect=KeyError), \
                mock.patch.object(adm.subprocess, "run") as run, \
                redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(adm.main(["alu9999"]), 2)
        run.assert_not_called()


class TestCompatibilidad(unittest.TestCase):
    def test_python_3_8(self):
        with open(ADMIN, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))

    def test_ejecutable(self):
        self.assertTrue(os.access(ADMIN, os.X_OK))


if __name__ == "__main__":
    unittest.main()
