"""Formato de la salida, código de salida y opciones."""

import contextlib
import io
import os
import re
import subprocess
import tempfile
import unittest
from unittest import mock

import falso_libvirt as fl
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

    def preparar_alumno(self, home):
        """Un alumno que lo ha hecho todo bien: claves, silo, red, imagen,
        disco y los tres archivos. Devuelve la conexión simulada."""
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
        base = os.path.join(silo, cd.IMAGEN_BASE)
        for args in (["-f", "qcow2", base, "3758096384"],
                     [os.path.join(silo, "server1.qcow2"), "-f", "qcow2", "-b",
                      cd.IMAGEN_BASE, "-F", "qcow2", "40G"]):
            subprocess.run(["qemu-img", "create", "-q"] + args, check=True)
        os.chmod(base, 0o644)
        os.chmod(os.path.join(silo, "server1.qcow2"), 0o644)
        return silo, fl.Conexion(
            silos=[fl.Silo("alu0000-imagenesMV", silo,
                           volumenes=[fl.Volumen(cd.IMAGEN_BASE)])],
            redes=[fl.Red("alu0000-red")],
            dominios=[fl.Dominio("zzz9999-server1", ["/home/zzz9999/server1.qcow2"])])

    def ejecutar_en(self, home, silo, conn, argv=(), puerto="sin ruta", ping=False,
                    ssh=(255, "", "Permission denied (publickey).\n"), disco=None):
        """main() en el silo, con libvirt, la red, ssh y guestfish simulados."""
        entorno = {"HOME": home, "CI_DIAGNOSIS_USUARIO": "alu0000"}
        anterior = os.getcwd()
        disco = disco or ({}, None, cd.error("guestfish simulado: sin disco"))
        try:
            os.chdir(silo)
            with mock.patch.dict(os.environ, entorno), fl.instalado(conn), \
                    mock.patch.object(cd, "responde_ping", return_value=ping), \
                    mock.patch.object(cd, "probar_puerto", return_value=puerto), \
                    mock.patch.object(cd, "_ssh", return_value=ssh), \
                    mock.patch.object(cd, "leer_disco", return_value=disco):
                return self.ejecutar_main(list(argv))
        finally:
            os.chdir(anterior)

    @necesita_yaml
    def test_de_principio_a_fin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.preparar_alumno(home)
            codigo, salida, _ = self.ejecutar_en(home, silo, conn)
        self.assertEqual(codigo, 0, salida)
        self.assertIn("máquina: alu0000-server1", salida)
        self.assertIn("Resultado: todo correcto.", salida)
        self.assertNotIn("ERROR", salida)
        self.assertNotIn("\033[", salida)
        self.assertTrue(conn.cerrada)
        orden = [l for l in salida.splitlines() if l and l == l.upper() and l[0].isalpha()]
        self.assertEqual(orden, ["ENTORNO COMPARTIDO", "DIRECTORIO Y SILO", "RED",
                                 "IMAGEN Y DISCO", "ARCHIVOS DE CLOUD-INIT", "CLAVES SSH",
                                 "NOMBRES LIBRES", "PERMISOS"])

    @necesita_yaml
    def test_con_errores_sale_con_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.preparar_alumno(home)
            conn.redes = []
            codigo, salida, _ = self.ejecutar_en(home, silo, conn)
        self.assertEqual(codigo, 1)
        self.assertIn("No existe la red alu0000-red", salida)

    def test_la_maquina_ya_existe(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.preparar_alumno(home)
            conn.dominios.append(fl.Dominio("alu0000-server1",
                                            [os.path.join(silo, "server1.qcow2")]))
            codigo, salida, _ = self.ejecutar_en(home, silo, conn, ["server1"])
        self.assertEqual(codigo, 1)
        self.assertIn("La máquina ya existe", salida)
        self.assertIn("(--acceso)", salida)

    def con_maquina(self, home, **kw):
        silo, conn = self.preparar_alumno(home)
        kw.setdefault("red", "alu0000-red")
        conn.dominios.append(fl.Dominio("alu0000-server1",
                                        [os.path.join(silo, "server1.qcow2")], **kw))
        return silo, conn

    @necesita_yaml
    def test_acceso_puede_entrar(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.con_maquina(home, activo=True)
            codigo, salida, _ = self.ejecutar_en(home, silo, conn, puerto="abierto",
                                                 ping=True, ssh=(0, "", ""))
        self.assertEqual(codigo, 0, salida)
        self.assertIn("Modo: no puede entrar en la máquina (--acceso)", salida)
        self.assertIn("IP 192.168.7.2 (de network-config)", salida)
        self.assertIn("Puede entrar", salida)
        self.assertNotIn("DISCO DE LA MÁQUINA", salida)

    @necesita_yaml
    def test_acceso_encendida_sin_entrar_pide_apagarla(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.con_maquina(home, activo=True)
            codigo, salida, _ = self.ejecutar_en(home, silo, conn, puerto="abierto", ping=True)
        self.assertEqual(codigo, 1)
        self.assertIn("rechaza su clave", salida)
        self.assertIn("virsh shutdown alu0000-server1", salida)
        self.assertIn("ORDEN DE VIRT-INSTALL", salida)

    @necesita_yaml
    def test_acceso_apagada_lee_el_disco(self):
        from test_acceso import disco_bueno
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.con_maquina(home)
            codigo, salida, _ = self.ejecutar_en(
                home, silo, conn, disco=(disco_bueno(), ["alu0000-server1"], None))
        self.assertIn("Disco leído", salida)
        self.assertIn("La máquina tiene su clave", salida)
        self.assertIn("la máquina está apagada", salida)
        self.assertEqual(codigo, 0, salida)

    @necesita_yaml
    def test_acceso_sin_ip(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.con_maquina(home, activo=True)
            escribir(os.path.join(silo, "meta-data"),
                     META_DATA.replace("server1", "server2"))
            codigo, salida, _ = self.ejecutar_en(home, silo, conn, ["server1"])
            self.assertIn("Indíquela con --ip", salida)
            codigo, salida, _ = self.ejecutar_en(home, silo, conn,
                                                 ["server1", "--ip", "192.168.7.5"],
                                                 puerto="abierto", ssh=(0, "", ""))
        self.assertIn("IP 192.168.7.5 (de --ip)", salida)
        self.assertEqual(codigo, 0, salida)

    def test_acceso_sin_maquina(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            silo, conn = self.preparar_alumno(home)
            os.remove(os.path.join(silo, "meta-data"))
            codigo, _, errores = self.ejecutar_en(home, silo, conn, ["--acceso"])
        self.assertEqual(codigo, 2)
        self.assertIn("indique qué máquina", errores)

    def test_sin_libvirt(self):
        with mock.patch.dict("sys.modules", {"libvirt": None}):
            codigo, _, errores = self.ejecutar_main([])
        self.assertEqual(codigo, 2)
        self.assertIn("avise al profesor", errores)


if __name__ == "__main__":
    unittest.main()
