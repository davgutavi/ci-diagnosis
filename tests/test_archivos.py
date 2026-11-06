"""Archivos de cloud-init: B1, B4, B5 y B6 del catálogo."""

import os
import tempfile
import unittest
from unittest import mock

from comun import (META_DATA, NETWORK_CONFIG, USER_DATA, Claves, cd, con_estado,
                   escribir, leer, necesita_yaml, problemas, red_de_prueba, texto_de)


def clave_servidor():
    return cd.analizar_clave_publica(Claves.publica("sin_frase"))


def user_data(clave=None, **cambios):
    texto = USER_DATA.format(clave=clave or Claves.publica("sin_frase"))
    for viejo, nuevo in cambios.items():
        texto = texto.replace(viejo.replace("_", " "), nuevo)
    return texto


def revisar_user_data(texto, clave=None):
    rs, limpio = cd.comprobar_texto("user-data", texto.encode("utf-8"))
    if limpio is not None:
        rs += cd.comprobar_user_data(limpio, clave or clave_servidor())
    return rs


def fallos(rs, estado=None):
    return {r.fallo for r in rs if (estado is None and r.estado in (cd.ERROR, cd.AVISO))
            or r.estado == estado}


class TestNombres(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def crear(self, *nombres):
        for n in nombres:
            ruta = os.path.join(os.fsencode(self.dir), n if isinstance(n, bytes) else n.encode())
            escribir(ruta, "x\n")

    def test_los_tres_existen(self):
        self.crear("user-data", "meta-data", "network-config")
        salida = cd.comprobar_nombres(self.dir)
        for nombre in cd.ARCHIVOS_CI:
            rs, datos = salida[nombre]
            self.assertEqual(problemas(rs), [])
            self.assertEqual(datos, b"x\n")

    def test_con_extension_yaml(self):
        # nlw2095 (catálogo, B2): archivos .yaml
        self.crear("user-data.yaml", "meta-data", "network-config")
        rs, datos = cd.comprobar_nombres(self.dir)["user-data"]
        self.assertIsNone(datos)
        self.assertEqual(rs[0].estado, cd.ERROR)
        self.assertIn("user-data.yaml", texto_de(rs))
        self.assertIn("mv user-data.yaml user-data", rs[0].arreglo)

    def test_espacio_invisible_en_el_nombre(self):
        # B1 visto: ls -b muestra 'so-ejemplos'$'\342\200\213'
        self.crear("user-data​".encode("utf-8"))
        rs, _ = cd.comprobar_nombres(self.dir)["user-data"]
        self.assertEqual(rs[0].estado, cd.ERROR)
        self.assertIn("user-data\\342\\200\\213", texto_de(rs))

    def test_nombre_que_no_es_utf8(self):
        # macOS no deja crear este nombre (Linux sí): se prueba sin el disco
        self.assertEqual(cd._base_de_nombre(b"meta-data\xc3"), "meta-data�")
        self.assertEqual(cd.escapar_nombre(b"meta-data\xc3"), "meta-data\\303")
        self.assertEqual(cd.escapar_nombre(b"user data"), "user\\ data")

    def test_copias_de_editores_junto_al_bueno(self):
        self.crear("network-config", "network-config~", ".network-config.swp")
        rs, datos = cd.comprobar_nombres(self.dir)["network-config"]
        self.assertEqual(datos, b"x\n")
        self.assertEqual(rs[0].estado, cd.AVISO)
        self.assertIn("network-config~", texto_de(rs))

    def test_mayusculas(self):
        self.crear("User-Data")
        rs, _ = cd.comprobar_nombres(self.dir)["user-data"]
        self.assertEqual(rs[0].estado, cd.ERROR)
        self.assertIn("User-Data", texto_de(rs))

    def test_directorio_con_ese_nombre(self):
        os.mkdir(os.path.join(self.dir, "meta-data"))
        rs, datos = cd.comprobar_nombres(self.dir)["meta-data"]
        self.assertIsNone(datos)
        self.assertEqual(rs[0].estado, cd.ERROR)


@necesita_yaml
class TestTexto(unittest.TestCase):

    def test_correcto(self):
        rs = revisar_user_data(user_data())
        self.assertEqual(problemas(rs), [])

    def test_espacio_invisible(self):
        rs = revisar_user_data(user_data(administrador="administrador​"))
        self.assertIn("B1", fallos(rs, cd.ERROR))
        self.assertIn("U+200B", texto_de(rs))
        self.assertIn("línea 3", texto_de(rs))

    def test_espacio_de_no_separacion(self):
        rs, _ = cd.comprobar_texto("meta-data", "instance-id: alu0000-server1\n".encode())
        self.assertIn("U+00A0", texto_de(rs))

    def test_raya_en_lugar_de_guion(self):
        rs = revisar_user_data(user_data(**{"-_name": "– name"}))
        self.assertIn("B1", fallos(rs, cd.ERROR))
        self.assertIn("U+2013", texto_de(rs))

    def test_comillas_curvas_del_pdf(self):
        texto = user_data().replace("['ALL=(ALL) NOPASSWD:ALL']",
                                    "[‘ALL=(ALL) NOPASSWD:ALL’]")
        rs = revisar_user_data(texto)
        self.assertIn("B1", fallos(rs, cd.ERROR))
        self.assertTrue(any("sudo" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_tabuladores(self):
        texto = user_data().replace("    shell:", "\tshell:")
        rs = revisar_user_data(texto)
        errores = con_estado(rs, cd.ERROR)
        self.assertTrue(any("tabuladores (línea 6)" in r.texto for r in errores))
        self.assertTrue(any("no es YAML válido" in r.texto for r in errores))

    def test_crlf(self):
        rs = revisar_user_data(user_data().replace("\n", "\r\n"))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "B1")])

    def test_bom(self):
        rs = revisar_user_data("﻿" + user_data())
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.ERROR, "B1")])

    def test_no_es_utf8(self):
        rs, texto = cd.comprobar_texto("network-config", b"version: 2\nethernets: \xe1\n")
        self.assertIsNone(texto)
        self.assertIn("línea 2", rs[0].texto)


@necesita_yaml
class TestUserData(unittest.TestCase):

    def test_sin_cloud_config(self):
        rs = revisar_user_data(user_data().replace("#cloud-config\n", ""))
        self.assertIn("B4", fallos(rs, cd.ERROR))

    def test_cloud_config_con_espacio(self):
        rs = revisar_user_data(user_data().replace("#cloud-config", "# cloud-config"))
        self.assertIn("sin espacios", texto_de(rs))

    def test_cloud_config_en_la_segunda_linea(self):
        rs = revisar_user_data("\n" + user_data())
        self.assertIn("Está en la línea 2", texto_de(rs))

    def test_ssh_authorized_keys_fuera_del_usuario(self):
        clave = Claves.publica("sin_frase")
        texto = ("#cloud-config\nusers:\n  - name: administrador\n"
                 "    sudo: ['ALL=(ALL) NOPASSWD:ALL']\n    groups: sudo\n"
                 "    shell: /bin/bash\nssh_authorized_keys:\n  - %s\n" % clave)
        rs = revisar_user_data(texto)
        self.assertTrue(any("fuera del usuario" in r.texto for r in con_estado(rs, cd.ERROR)))
        self.assertTrue(any("no tiene ssh_authorized_keys" in r.texto for r in rs))

    def test_users_sin_guion(self):
        texto = user_data().replace("  - name:", "    name:")
        rs = revisar_user_data(texto)
        self.assertIn("Falta el guion", texto_de(rs))

    def test_user_en_singular(self):
        rs = revisar_user_data(user_data().replace("users:", "user:"))
        self.assertIn("«user:»", texto_de(rs))

    def test_otro_nombre_de_usuario(self):
        rs = revisar_user_data(user_data().replace("name: administrador",
                                                   "name: Administrador"))
        self.assertIn("Usuarios que crea: Administrador", texto_de(rs))

    def test_sin_sudo(self):
        texto = user_data().replace("    sudo: ['ALL=(ALL) NOPASSWD:ALL']\n", "")
        rs = revisar_user_data(texto)
        self.assertTrue(any("no tiene la línea sudo" in r.texto
                            for r in con_estado(rs, cd.ERROR)))

    def test_grupo_y_shell_distintos(self):
        texto = user_data().replace("groups: sudo", "groups: adm").replace(
            "/bin/bash", "/bin/sh")
        self.assertEqual(len(con_estado(revisar_user_data(texto), cd.AVISO)), 2)

    def test_clave_de_otro_ordenador(self):
        rs = revisar_user_data(user_data(clave=Claves.publica("portatil")))
        errores = con_estado(rs, cd.ERROR)
        self.assertEqual([r.fallo for r in errores], ["B5"])
        self.assertIn("alu0000@portatil", texto_de(errores))

    def test_clave_partida_en_dos_lineas(self):
        tipo, cuerpo, comentario = Claves.publica("sin_frase").split()
        mitad = len(cuerpo) // 2
        texto = user_data(clave="%s %s\n        %s %s" % (tipo, cuerpo[:mitad],
                                                          cuerpo[mitad:], comentario))
        rs = revisar_user_data(texto)
        self.assertTrue(any("partida" in r.texto for r in con_estado(rs, cd.ERROR)))
        # Y se reconoce que es la buena: no hay un segundo error de clave distinta
        self.assertFalse(any("no es la de" in r.texto for r in rs))

    def test_clave_cortada(self):
        tipo, cuerpo, comentario = Claves.publica("sin_frase").split()
        rs = revisar_user_data(user_data(clave="%s %s %s" % (tipo, cuerpo[:200], comentario)))
        self.assertTrue(any("no es una clave pública válida" in r.texto for r in rs))

    def test_texto_de_ejemplo(self):
        rs = revisar_user_data(user_data(clave="SU CLAVE PÚBLICA"))
        self.assertTrue(any("texto de ejemplo" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_clave_privada_pegada_no_se_muestra(self):
        privada = leer(Claves.preparar().sin_frase)
        sangrada = "\n".join("        " + l for l in privada.strip().split("\n"))
        rs = revisar_user_data(user_data(clave="|\n" + sangrada))
        rs += revisar_user_data(user_data(clave=privada))   # sin sangrar: YAML inválido
        salida = texto_de(rs)
        self.assertIn("contiene una clave privada", salida)
        for linea in privada.split("\n")[1:-2]:
            self.assertNotIn(linea[:20], salida)

    def test_yaml_invalido_dice_la_linea(self):
        texto = user_data().replace("    groups: sudo", "  groups: sudo")
        rs = revisar_user_data(texto)
        mal = [r for r in rs if "no es YAML válido" in r.texto][0]
        self.assertTrue(mal.detalle[0].startswith("Línea "))

    def test_sin_clave_del_servidor(self):
        rs = cd.comprobar_user_data(user_data(), None)
        self.assertEqual(con_estado(rs, cd.OMITIDA)[0].texto.split(":")[0],
                         "Clave de user-data")


class TestSinPyYAML(unittest.TestCase):

    def test_sin_pyyaml(self):
        with mock.patch.object(cd, "yaml", None):
            rs = revisar_user_data(user_data())
        self.assertTrue(any("falta PyYAML" in r.texto for r in con_estado(rs, cd.AVISO)))
        self.assertEqual(con_estado(rs, cd.ERROR), [])


@necesita_yaml
class TestMetaData(unittest.TestCase):

    def test_correcto(self):
        rs, datos = cd.comprobar_meta_data(META_DATA, "alu0000", "server1")
        self.assertEqual(problemas(rs), [])
        self.assertEqual(datos["local-hostname"], "server1")

    def test_maquina_deducida(self):
        rs, _ = cd.comprobar_meta_data(META_DATA, "alu0000", None)
        self.assertEqual(problemas(rs), [])

    def test_de_otra_maquina(self):
        rs, _ = cd.comprobar_meta_data(META_DATA, "alu0000", "server2")
        self.assertEqual(len(con_estado(rs, cd.AVISO)), 2)

    def test_texto_de_ejemplo(self):
        texto = META_DATA.replace("alu0000-server1", "su_usuario_en_el_servidor-server1")
        rs, _ = cd.comprobar_meta_data(texto, "alu0000", "server1")
        self.assertIn("texto de ejemplo", con_estado(rs, cd.AVISO)[0].texto)


@necesita_yaml
class TestNetworkConfig(unittest.TestCase):

    def revisar(self, texto, red=True):
        return cd.comprobar_network_config(texto, red_de_prueba() if red else None)

    def test_correcto(self):
        rs, ip = self.revisar(NETWORK_CONFIG)
        self.assertEqual(problemas(rs), [])
        self.assertEqual(str(ip), "192.168.7.2")

    def test_sin_red_se_omite(self):
        rs, _ = self.revisar(NETWORK_CONFIG, red=False)
        self.assertEqual(problemas(rs), [])
        self.assertEqual(len(con_estado(rs, cd.OMITIDA)), 1)

    def test_otra_interfaz(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("enp1s0", "eth0"))
        self.assertIn("B6", fallos(rs, cd.ERROR))
        self.assertIn("Configura: eth0", texto_de(rs))

    def test_sin_prefijo(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("192.168.7.2/24", "192.168.7.2"))
        self.assertIn("no lleva /24", con_estado(rs, cd.ERROR)[0].texto)

    def test_ip_de_otra_red(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("192.168.7.2/24", "192.168.8.2/24"))
        self.assertTrue(any("no es de su red" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_ip_de_la_pasarela(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("192.168.7.2/24", "192.168.7.1/24"))
        self.assertTrue(any("reservada" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_ip_en_el_dhcp(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("192.168.7.2/24", "192.168.7.200/24"))
        self.assertTrue(any("rango del DHCP" in r.texto for r in con_estado(rs, cd.AVISO)))

    def test_pasarela_equivocada(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("via: 192.168.7.1", "via: 192.168.7.254"))
        self.assertTrue(any("pasarela" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_sin_ruta(self):
        texto = NETWORK_CONFIG.replace("    routes:\n      - to: default\n"
                                       "        via: 192.168.7.1\n", "")
        rs, _ = self.revisar(texto)
        self.assertTrue(any("ruta por defecto" in r.texto for r in con_estado(rs, cd.ERROR)))

    def test_gateway4(self):
        texto = NETWORK_CONFIG.replace("    routes:\n      - to: default\n"
                                       "        via: 192.168.7.1\n",
                                       "    gateway4: 192.168.7.1\n")
        rs, _ = self.revisar(texto)
        self.assertEqual([r.estado for r in problemas(rs)], [cd.AVISO])

    def test_dns_distintos(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("150.214.130.15", "8.8.8.8"))
        self.assertEqual([r.estado for r in problemas(rs)], [cd.AVISO])

    def test_version_1(self):
        rs, _ = self.revisar(NETWORK_CONFIG.replace("version: 2", "version: 1"))
        self.assertIn("version: 2", con_estado(rs, cd.ERROR)[0].texto)


if __name__ == "__main__":
    unittest.main()
