"""Libvirt y el silo: A1, A2, A3, B2, B3, B8, B9, C1, C2, D5 y la sección 0."""

import ipaddress
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import falso_libvirt as fl
from comun import UVUS, cd, con_estado, necesita_yaml, problemas, texto_de


def qemu_img(*args):
    subprocess.run(["qemu-img", "create", "-q"] + list(args), check=True,
                   stdout=subprocess.DEVNULL)


class ConHome(unittest.TestCase):
    """Un home de mentira con su silo ~/imagenesMV (trayectos reales: en macOS
    /var es un enlace a /private/var)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self.tmp.name)
        self.silo = os.path.join(self.home, "imagenesMV")
        os.mkdir(self.silo)

    def tearDown(self):
        self.tmp.cleanup()

    def mi_silo(self, **kw):
        return fl.Silo("%s-imagenesMV" % UVUS, self.silo, **kw)


class TestEntornoCompartido(ConHome):

    def revisar(self, *silos):
        return cd.comprobar_entorno_compartido(
            cd.leer_silos(fl.Conexion(silos=silos)), self.home)

    def test_ninguno_falla(self):
        rs = self.revisar(self.mi_silo(volumenes=[fl.Volumen("a.img")]),
                          fl.Silo("otro", "/home/otro", activo=False))
        self.assertEqual(problemas(rs), [])
        self.assertIn("1 silos activos", rs[0].texto)

    def test_silo_de_otro_usuario(self):
        # A1 visto en warcry: un silo sobre el home de otro alumno
        rs = self.revisar(self.mi_silo(),
                          fl.Silo("zzz9999", "/home/zzz9999",
                                  volumenes=[fl.Volumen("ok"), fl.Volumen("x", roto=True)]))
        self.assertEqual([(r.estado, r.fallo) for r in rs], [(cd.ERROR, "A1")])
        self.assertIn("zzz9999", rs[0].texto)
        self.assertIn("No es culpa suya", texto_de(rs))
        self.assertIn("avise al profesor", texto_de(rs))

    def test_silo_propio(self):
        rs = self.revisar(fl.Silo(UVUS, self.home, volumenes=[fl.Volumen("x", roto=True)]))
        self.assertIn("Su silo", rs[0].texto)

    def test_inactivos_no_cuentan(self):
        rs = self.revisar(fl.Silo("otro", "/home/otro", activo=False,
                                  volumenes=[fl.Volumen("x", roto=True)]))
        self.assertEqual(problemas(rs), [])


class TestSilo(ConHome):

    def revisar(self, *silos, directorio=None):
        return cd.comprobar_silo(cd.leer_silos(fl.Conexion(silos=silos)), UVUS,
                                 self.home, directorio or self.silo)

    def test_correcto(self):
        rs = self.revisar(self.mi_silo())
        self.assertEqual(problemas(rs), [])

    def test_en_el_home(self):
        rs = self.revisar(self.mi_silo(), directorio=self.home)
        self.assertEqual(rs[0].fallo, "B2")
        self.assertIn("directorio personal", rs[0].texto)

    def test_en_el_home_sin_imagenesmv(self):
        # Visto con la cuenta de prueba en avantasia (6-nov): no hay ~/imagenesMV
        os.rmdir(self.silo)
        rs = self.revisar(directorio=self.home)
        self.assertIn("mkdir ~/imagenesMV", rs[0].arreglo)

    def test_fuera_de_un_silo(self):
        otro = os.path.join(self.home, "pruebas")
        os.mkdir(otro)
        rs = self.revisar(self.mi_silo(), directorio=otro)
        self.assertEqual((rs[0].estado, rs[0].fallo), (cd.ERROR, "B2"))
        self.assertIn("silo automático", rs[0].efecto)

    def test_silo_automatico(self):
        rs = self.revisar(fl.Silo("imagenesMV-2", self.silo))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "B2")])

    def test_parado_y_sin_autoarranque(self):
        rs = self.revisar(self.mi_silo(activo=False))
        self.assertTrue(any("parado" in r.texto for r in con_estado(rs, cd.ERROR)))
        rs = self.revisar(self.mi_silo(autoarranque=False))
        self.assertTrue(any("no arranca solo" in r.texto for r in con_estado(rs, cd.AVISO)))

    def test_silo_con_errata_en_el_trayecto(self):
        # B9: pcj4404, silo sobre imagenesMVl (con errata), que no existía
        rs = self.revisar(fl.Silo("%s-imagenesMV" % UVUS, self.silo + "l"),
                          fl.Silo("imagenesMV-2", self.silo))
        b9 = [r for r in rs if r.fallo == "B9"]
        self.assertEqual(len(b9), 1)
        self.assertIn("no existe", texto_de(b9))

    def test_directorio_de_otro(self):
        with mock.patch.object(cd.os, "getuid", return_value=os.getuid() + 1):
            rs = self.revisar(self.mi_silo())
        self.assertTrue(any(r.fallo == "B9" for r in con_estado(rs, cd.ERROR)))

    def test_silo_sobre_el_home_y_sobre_ssh(self):
        os.mkdir(os.path.join(self.home, ".ssh"))
        rs = self.revisar(self.mi_silo(), fl.Silo(UVUS, self.home),
                          fl.Silo(".ssh-1", os.path.join(self.home, ".ssh")))
        avisos = con_estado(rs, cd.AVISO)
        self.assertEqual(len(avisos), 2)
        self.assertIn("directorio personal", avisos[0].texto)
        self.assertIn(".ssh", avisos[1].texto)


class TestRed(unittest.TestCase):

    def revisar(self, *redes):
        return cd.comprobar_red(fl.Conexion(redes=redes), UVUS)

    def test_correcta(self):
        rs, red = self.revisar(fl.Red("%s-red" % UVUS))
        self.assertEqual(problemas(rs), [])
        self.assertEqual(str(red.red), "192.168.7.0/24")
        self.assertEqual(str(red.pasarela), "192.168.7.1")
        self.assertTrue(red.en_dhcp(ipaddress.ip_address("192.168.7.200")))

    def test_no_existe(self):
        rs, red = self.revisar(fl.Red("%s-red2" % UVUS), fl.Red("otra", base="192.168.9"))
        self.assertIsNone(red)
        self.assertIn("alu0000-red2", texto_de(rs))

    def test_parada_sin_autoarranque_aislada_e_ipv6(self):
        rs, _ = self.revisar(fl.Red("%s-red" % UVUS, activa=False, autoarranque=False,
                                    modo=None, ipv6=True))
        self.assertEqual(len(con_estado(rs, cd.ERROR)), 1)
        self.assertEqual(len(con_estado(rs, cd.AVISO)), 3)

    def test_dhcp_distinto(self):
        rs, _ = self.revisar(fl.Red("%s-red" % UVUS, dhcp=(2, 254)))
        self.assertIn("DHCP", con_estado(rs, cd.AVISO)[0].texto)

    def test_misma_subred_que_otra(self):
        # A2: con la otra activa y la suya parada, la suya no arranca
        rs, _ = self.revisar(fl.Red("%s-red" % UVUS, activa=False), fl.Red("ajena"))
        self.assertIn("A2", [r.fallo for r in con_estado(rs, cd.ERROR)])
        rs, _ = self.revisar(fl.Red("%s-red" % UVUS), fl.Red("ajena", activa=False))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "A2")])

    @necesita_yaml
    def test_la_red_sirve_para_network_config(self):
        _, red = self.revisar(fl.Red("%s-red" % UVUS, base="192.168.9"))
        from comun import NETWORK_CONFIG
        rs, _ = cd.comprobar_network_config(NETWORK_CONFIG, red)
        self.assertTrue(any("no es de su red" in r.texto for r in con_estado(rs, cd.ERROR)))


class TestImagenYDisco(ConHome):

    def base(self, formato="qcow2", tam="3758096384"):
        qemu_img("-f", formato, os.path.join(self.silo, cd.IMAGEN_BASE), tam)

    def disco(self, tam="40G", formato_respaldo="qcow2"):
        qemu_img(os.path.join(self.silo, "server1.qcow2"), "-f", "qcow2",
                 "-b", cd.IMAGEN_BASE, "-F", formato_respaldo, tam)

    def revisar(self):
        return cd.comprobar_imagen_y_disco(self.silo, "server1")

    def test_correctos(self):
        self.base()
        self.disco()
        os.chmod(os.path.join(self.silo, cd.IMAGEN_BASE), 0o644)
        os.chmod(os.path.join(self.silo, "server1.qcow2"), 0o644)
        self.assertEqual(problemas(self.revisar()), [])

    def test_sin_imagen_base(self):
        rs = self.revisar()
        self.assertEqual(rs[0].fallo, "B3")
        self.assertIn("qemu-img create server1.qcow2", texto_de(rs))

    def test_imagen_base_que_no_es_qcow2(self):
        self.base(formato="raw", tam="1M")
        self.assertIn("formato qcow2", con_estado(self.revisar(), cd.ERROR)[0].texto)

    def test_imagen_base_de_otro_tamano(self):
        self.base(tam="3G")
        self.assertIn("3.5 GiB", con_estado(self.revisar(), cd.AVISO)[0].texto)

    def test_disco_pequeno_y_respaldo_raw(self):
        self.base()
        self.disco(tam="20G", formato_respaldo="raw")
        mal = con_estado(self.revisar(), cd.ERROR)[0]
        self.assertEqual(len(mal.detalle), 2)
        self.assertIn("-F qcow2", texto_de([mal]))

    def test_imagen_base_movida(self):
        self.base()
        self.disco()
        os.rename(os.path.join(self.silo, cd.IMAGEN_BASE), os.path.join(self.silo, "otra.img"))
        textos = [r.texto for r in con_estado(self.revisar(), cd.ERROR)]
        self.assertIn("No está la imagen de la que depende server1.qcow2", textos)

    def test_imagen_escribible_por_el_grupo(self):
        self.base()
        os.chmod(os.path.join(self.silo, cd.IMAGEN_BASE), 0o664)
        avisos = con_estado(self.revisar(), cd.AVISO)
        self.assertIn("0664", avisos[0].texto)
        self.assertIn("cp %s copia" % cd.IMAGEN_BASE, avisos[0].arreglo)
        self.assertIn("kvm", avisos[0].efecto)

    def test_disco_escribible_por_cualquiera(self):
        # Visto en megadeth el 6-nov: discos de alumnos con 666 y 646
        self.base()
        self.disco()
        os.chmod(os.path.join(self.silo, "server1.qcow2"), 0o646)
        avisos = [r for r in con_estado(self.revisar(), cd.AVISO) if "server1" in r.texto]
        self.assertIn("cualquier usuario del servidor", avisos[0].efecto)

    def test_sin_maquina(self):
        self.base()
        rs = cd.comprobar_imagen_y_disco(self.silo, None)
        self.assertEqual(con_estado(rs, cd.OMITIDA)[0].texto.split(":")[0],
                         "Disco de la máquina")


class TestNombres(ConHome):

    def revisar(self, *dominios, ip=None, red=None):
        return cd.comprobar_nombres_libres(fl.Conexion(dominios=dominios), UVUS, self.home,
                                           self.silo, "server1", ip, red)

    def test_libre(self):
        rs, existe = self.revisar(fl.Dominio("otro-server1", ["/home/otro/server1.qcow2"]))
        self.assertEqual(problemas(rs), [])
        self.assertFalse(existe)

    def test_ya_existe(self):
        rs, existe = self.revisar(fl.Dominio("%s-server1" % UVUS))
        self.assertTrue(existe)
        self.assertEqual(rs[0].fallo, "C2")

    def test_disco_en_uso(self):
        disco = os.path.join(self.silo, "server1.qcow2")
        rs, _ = self.revisar(fl.Dominio("%s-server2" % UVUS, [disco]))
        self.assertTrue(any("ya lo usa la máquina" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_oautoconsole(self):
        # C1 visto en avantasia: -noautoconsole con un solo guion
        rs, _ = self.revisar(fl.Dominio("oautoconsole", [os.path.join(self.silo, "s.qcow2")]))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "C1")])

    def test_maquina_suya_sin_uvus(self):
        rs, _ = self.revisar(fl.Dominio("server1", [os.path.join(self.silo, "s.qcow2")]))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "A3")])

    def test_ip_ocupada(self):
        _, red = cd.comprobar_red(fl.Conexion(redes=[fl.Red("%s-red" % UVUS)]), UVUS)
        ip = ipaddress.ip_address("192.168.7.2")
        with mock.patch.object(cd, "responde_ping", return_value=True):
            rs, _ = self.revisar(ip=ip, red=red)
        self.assertIn("D5", [r.fallo for r in con_estado(rs, cd.ERROR)])
        with mock.patch.object(cd, "responde_ping", return_value=False):
            rs, _ = self.revisar(ip=ip, red=red)
        self.assertEqual(problemas(rs), [])


class TestPermisos(ConHome):

    def test_atravesar(self):
        cerrado = os.path.join(self.home, "cerrado")
        os.mkdir(cerrado, 0o700)
        os.chmod(self.silo, 0o751)
        otro = os.getuid() + 12345
        self.assertFalse(cd.puede_atravesar(cerrado, otro, set()))
        self.assertTrue(cd.puede_atravesar(self.silo, otro, set()))
        self.assertTrue(cd.puede_atravesar(cerrado, os.getuid(), set()))

    def test_home_cerrado(self):
        os.chmod(self.home, 0o700)
        qemu = mock.Mock(pw_uid=os.getuid() + 12345, pw_gid=os.getgid() + 12345)
        with mock.patch.object(cd.pwd, "getpwnam", return_value=qemu), \
                mock.patch.object(cd, "_cadena_hasta", return_value=[self.home, self.silo]):
            rs = cd.comprobar_permisos(self.silo)
        self.assertEqual((rs[0].estado, rs[0].fallo), (cd.ERROR, "B8"))
        self.assertIn("0700", rs[0].texto)
        self.assertIn("chmod o+x", rs[0].arreglo)

    def test_sin_usuario_de_qemu(self):
        with mock.patch.object(cd.pwd, "getpwnam", side_effect=KeyError):
            self.assertEqual(cd.comprobar_permisos(self.silo)[0].estado, cd.OMITIDA)


class TestConexion(unittest.TestCase):

    def test_solo_lectura(self):
        conn = fl.Conexion()
        with fl.instalado(conn):
            self.assertIs(cd.abrir_conexion(), conn)

    def test_sin_modulo(self):
        with mock.patch.dict("sys.modules", {"libvirt": None}):
            with self.assertRaises(cd.SinLibvirt):
                cd.abrir_conexion()


if __name__ == "__main__":
    unittest.main()
