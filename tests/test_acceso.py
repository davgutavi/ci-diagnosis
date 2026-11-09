"""Cuando no puede entrar: C1, D1, D2, D3, D4, D6 y el disco (B4, B5, B6)."""

import ipaddress
import json
import os
import tempfile
import unittest
from unittest import mock

import falso_libvirt as fl
from comun import (NETWORK_CONFIG, UVUS, USER_DATA, Claves, cd, con_estado, escribir,
                   necesita_yaml, problemas, red_de_prueba, texto_de)

IP = ipaddress.ip_address("192.168.7.2")


def maquina(**kw):
    kw.setdefault("red", "%s-red" % UVUS)
    return cd.Maquina(fl.Dominio("%s-server1" % UVUS, **kw))


class TestMaquina(unittest.TestCase):

    def test_apagada_y_bien(self):
        self.assertEqual(problemas(cd.comprobar_maquina(maquina(), UVUS)), [])

    def test_primer_arranque(self):
        # D3: virt-install arranca la máquina con on_reboot=destroy (cap5-27.txt)
        rs = cd.comprobar_maquina(maquina(activo=True, on_reboot="destroy", iso=True), UVUS)
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "D3")])

    def test_apagada_no_avisa_del_primer_arranque(self):
        rs = cd.comprobar_maquina(maquina(on_reboot="destroy"), UVUS)
        self.assertEqual(problemas(rs), [])

    def test_otra_red(self):
        rs = cd.comprobar_maquina(maquina(red="default"), UVUS)
        self.assertIn("Está en: default", texto_de(con_estado(rs, cd.ERROR)))

    def test_memoria_y_cpus(self):
        rs = cd.comprobar_maquina(maquina(memoria_kib=1048576, vcpus=1), UVUS)
        self.assertEqual(len(con_estado(rs, cd.AVISO)), 2)
        self.assertIn("1024 MiB", texto_de(rs))

    def test_ip_por_arp(self):
        self.assertEqual(cd.ip_por_arp(fl.Dominio("x", arp="192.168.7.9")),
                         ipaddress.ip_address("192.168.7.9"))
        self.assertIsNone(cd.ip_por_arp(fl.Dominio("x")))


class TestConectividad(unittest.TestCase):

    def revisar(self, ping, puerto):
        with mock.patch.object(cd, "responde_ping", return_value=ping), \
                mock.patch.object(cd, "probar_puerto", return_value=puerto):
            return cd.comprobar_conectividad(IP)

    def test_abierto(self):
        rs, abierto = self.revisar(True, "abierto")
        self.assertTrue(abierto)
        self.assertEqual(problemas(rs), [])

    def test_rechazada(self):
        # Mensaje grabado en avantasia: ssh: connect to host ... port 22: Connection refused
        rs, abierto = self.revisar(True, "rechazado")
        self.assertFalse(abierto)
        self.assertIn("Connection refused", texto_de(rs))
        self.assertEqual(con_estado(rs, cd.ERROR)[0].fallo, "D1")

    def test_sin_ruta(self):
        rs, _ = self.revisar(False, "sin ruta")
        self.assertIn("No route to host", texto_de(rs))
        self.assertIn("B6", texto_de(rs))


class Ssh:
    """Simula ssh-keygen -F y ssh, y guarda cada orden."""

    def __init__(self, conocida, respuestas):
        self.conocida, self.respuestas, self.ordenes = conocida, list(respuestas), []

    def __call__(self, argv, timeout=30, entrada=None):
        self.ordenes.append(argv)
        if argv[0] == "ssh-keygen":
            return (0 if self.conocida else 1), "", ""
        return self.respuestas.pop(0)


class TestSsh(unittest.TestCase):

    def revisar(self, conocida, respuestas, cifrada=False, en_agente=False):
        falso = Ssh(conocida, respuestas)
        with mock.patch.object(cd, "ejecutar", falso):
            rs, entra = cd.comprobar_ssh(IP, "/home/alu0000", cifrada, en_agente)
        return rs, entra, [o for o in falso.ordenes if o[0] == "ssh"]

    def test_entra_sin_tocar_known_hosts(self):
        rs, entra, ordenes = self.revisar(False, [(0, "", "")])
        self.assertTrue(entra)
        orden = " ".join(ordenes[0])
        self.assertIn("UserKnownHostsFile=/dev/null", orden)
        self.assertIn("UpdateHostKeys=no", orden)
        self.assertIn("BatchMode=yes", orden)
        self.assertIn("administrador@192.168.7.2 hostname", orden)
        # Nunca contraseñas: no deja «Failed password» en ninguna parte (A4, E4)
        for opcion in ("NumberOfPasswordPrompts=0", "PasswordAuthentication=no",
                       "KbdInteractiveAuthentication=no",
                       "PreferredAuthentications=publickey"):
            self.assertIn(opcion, orden)

    def test_con_known_hosts_es_estricto(self):
        _, _, ordenes = self.revisar(True, [(0, "", "")])
        orden = " ".join(ordenes[0])
        self.assertIn("StrictHostKeyChecking=yes", orden)
        self.assertIn("UserKnownHostsFile=/home/alu0000/.ssh/known_hosts", orden)

    def test_contesta_otra_maquina(self):
        # D5 visto en avantasia (6-nov): con dos máquinas en la misma IP, ssh entra
        # unas veces en una y otras en la otra
        falso = Ssh(False, [(0, "server1\n", "")])
        with mock.patch.object(cd, "ejecutar", falso):
            rs, entra = cd.comprobar_ssh(IP, "/home/alu0000", False, False, "server2")
        self.assertFalse(entra)
        self.assertEqual([(r.estado, r.fallo) for r in rs], [(cd.AVISO, "D5")])
        self.assertIn("se llama server1, no server2", rs[0].texto)

    def test_contesta_la_suya(self):
        falso = Ssh(False, [(0, "server2\n", "")])
        with mock.patch.object(cd, "ejecutar", falso):
            _, entra = cd.comprobar_ssh(IP, "/home/alu0000", False, False, "server2")
        self.assertTrue(entra)

    def test_clave_del_host_cambiada(self):
        # D4: el mensaje de la FAQ B.2 (grabado en b2-21.txt)
        aviso = ("@@@\n@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
                 "Host key verification failed.\n")
        rs, entra, ordenes = self.revisar(True, [(255, "", aviso), (0, "", "")])
        self.assertFalse(entra)
        d4 = con_estado(rs, cd.ERROR)[0]
        self.assertEqual(d4.fallo, "D4")
        self.assertIn('ssh-keygen -f "/home/alu0000/.ssh/known_hosts" -R "192.168.7.2"',
                      d4.arreglo)
        self.assertIn("podrá entrar", texto_de(rs))
        self.assertEqual(len(ordenes), 2)

    def test_rechaza_la_clave(self):
        rs, _, _ = self.revisar(False, [(255, "", "administrador@192.168.7.2: "
                                                 "Permission denied (publickey).\n")])
        self.assertEqual(con_estado(rs, cd.ERROR)[0].fallo, "B5")
        self.assertIn("virsh shutdown", texto_de(rs))

    def test_frase_de_paso_sin_agente_no_concluye(self):
        rs, _, _ = self.revisar(False, [(255, "", "Permission denied (publickey).\n")],
                                cifrada=True, en_agente=False)
        self.assertEqual(con_estado(rs, cd.ERROR), [])
        self.assertIn("no concluyente", con_estado(rs, cd.OMITIDA)[0].texto)

    def test_clave_con_permisos_abiertos(self):
        rs, _, _ = self.revisar(False, [(255, "", "WARNING: UNPROTECTED PRIVATE KEY FILE!\n"
                                                 "Permission denied (publickey).\n")])
        self.assertEqual(con_estado(rs, cd.ERROR)[0].fallo, "B10")


LINEA = ("[Thu, 05 Nov 2026 10:00:00 virt-install 1234] DEBUG (cli:204) Launched with "
         "command line: /usr/bin/virt-install %s\n")
MANUAL = ("--name=alu0000-server1 --cloud-init user-data=user-data,meta-data=meta-data,"
          "network-config=network-config --ram=2048 --vcpus=2 --import --disk "
          "path=server1.qcow2 --os-variant=ubuntu24.04 --network network=alu0000-red "
          "--noautoconsole")


class TestOrden(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(os.path.join(self.home, ".cache", "virt-manager"))

    def tearDown(self):
        self.tmp.cleanup()

    def revisar(self, *ordenes, archivo="virt-install.log"):
        escribir(os.path.join(self.home, ".cache", "virt-manager", archivo),
                 "".join(LINEA % o for o in ordenes))
        return cd.comprobar_orden(self.home, UVUS, "alu0000-server1")

    def test_como_la_del_manual(self):
        rs = self.revisar("--name=otra " + MANUAL.replace("--name=alu0000-server1 ", ""),
                          MANUAL)
        self.assertEqual(problemas(rs), [])

    def test_vale_la_ultima(self):
        rs = self.revisar(MANUAL.replace("--import ", ""), MANUAL)
        self.assertEqual(problemas(rs), [])

    def test_un_solo_guion(self):
        rs = self.revisar(MANUAL.replace("--noautoconsole", "-noautoconsole"))
        self.assertIn("-noautoconsole", con_estado(rs, cd.ERROR)[0].texto)

    def test_espacio_tras_la_coma(self):
        rs = self.revisar(MANUAL.replace("user-data,meta-data", "user-data, meta-data"))
        self.assertIn("espacio tras una coma", con_estado(rs, cd.ERROR)[0].texto)

    def test_sin_network_config(self):
        rs = self.revisar(MANUAL.replace(",network-config=network-config", ""))
        self.assertIn("no lleva network-config", con_estado(rs, cd.ERROR)[0].texto)

    def test_sin_cloud_init_ni_import_ni_os_variant(self):
        orden = ("--name=alu0000-server1 --ram=2048 --disk path=server1.qcow2 "
                 "--network network=default")
        rs = self.revisar(orden)
        self.assertEqual(len(con_estado(rs, cd.ERROR)), 1)
        # --import, --os-variant, la red y --noautoconsole
        self.assertEqual(len(con_estado(rs, cd.AVISO)), 4)

    def test_en_un_registro_rotado(self):
        rs = self.revisar(MANUAL.replace("--import ", ""), archivo="virt-install.log.2")
        self.assertIn("--import", texto_de(rs))

    def test_con_error_en_el_registro(self):
        escribir(os.path.join(self.home, ".cache", "virt-manager", "virt-install.log"),
                 LINEA % MANUAL + "[Thu, 05 Nov 2026 10:00:01 virt-install 1234] DEBUG "
                 "(x:1) algo\n[Thu, 05 Nov 2026 10:00:02 virt-install 1234] ERROR "
                 "(cli:255) Guest name 'alu0000-server1' is already in use.\n")
        rs = cd.comprobar_orden(self.home, UVUS, "alu0000-server1")
        self.assertIn("is already in use", texto_de(con_estado(rs, cd.ERROR)))
        self.assertIn("Thu, 05 Nov 2026 10:00:00", rs[0].texto)

    def test_intento_anterior_en_antes(self):
        # --antes: espacio tras la coma (visto en avantasia: virt-install no la crea)
        self.revisar(MANUAL.replace("user-data,meta-data", "user-data, meta-data"))
        rs = cd.comprobar_intento_anterior(self.home, UVUS, "alu0000-server1")
        self.assertIn("espacio tras una coma", texto_de(rs))

    def test_intento_anterior_completado(self):
        escribir(os.path.join(self.home, ".cache", "virt-manager", "virt-install.log"),
                 LINEA % MANUAL + "[Thu, 05 Nov 2026 10:00:09 virt-install 1234] DEBUG "
                 "(x:1) Domain creation completed.\n")
        rs = cd.comprobar_intento_anterior(self.home, UVUS, "alu0000-server1")
        self.assertEqual([r.estado for r in rs], [cd.OK])

    def test_sin_intento_anterior(self):
        self.assertEqual(cd.comprobar_intento_anterior(self.home, UVUS, "alu0000-server1"), [])

    def test_muestra_la_orden(self):
        rs = self.revisar(MANUAL)
        self.assertEqual(rs[0].estado, cd.OK)
        self.assertEqual(rs[0].detalle, ["virt-install " + MANUAL])
        self.assertIn("como la del manual", rs[-1].texto)

    def test_la_orden_del_manual_es_la_buena(self):
        # La orden que se da en las soluciones no tiene ningún problema
        rs = self.revisar(cd.orden_virt_install(UVUS, "server1")[len("virt-install "):])
        self.assertEqual(problemas(rs), [])

    def test_maquina_creada_con_orden_mala_lleva_los_pasos(self):
        rs = self.revisar(MANUAL.replace(",network-config=network-config", "")
                          .replace("network=alu0000-red", "network=default"))
        graves = problemas(rs)
        self.assertEqual(len(graves), 2)
        pasos = graves[0].arreglo
        self.assertIsInstance(pasos, cd.PasosRehacer)
        self.assertIn("$ virsh undefine alu0000-server1 --remove-all-storage", pasos)
        self.assertIn("$ " + cd.orden_virt_install(UVUS, "server1"), pasos)
        self.assertIn("network=alu0000-red", pasos.corregir)
        self.assertIn("arriba", graves[1].arreglo)

    def test_antes_basta_con_la_orden_del_manual(self):
        self.revisar(MANUAL.replace("--cloud-init user-data=user-data,meta-data=meta-data,"
                                    "network-config=network-config ", ""))
        rs = cd.comprobar_intento_anterior(self.home, UVUS, "alu0000-server1")
        pasos = con_estado(rs, cd.ERROR)[0].arreglo
        self.assertNotIsInstance(pasos, cd.PasosRehacer)
        self.assertIn("$ " + cd.orden_virt_install(UVUS, "server1"), pasos)

    def test_otros_archivos_ram_y_disco(self):
        rs = self.revisar(MANUAL.replace("user-data=user-data", "user-data=user-data.yaml")
                          .replace("--ram=2048", "--ram=1024")
                          .replace("path=server1.qcow2", "path=server2.qcow2"))
        textos = texto_de(con_estado(rs, cd.AVISO))
        self.assertIn("user-data=user-data.yaml", textos)
        self.assertIn("1024 MiB", textos)
        self.assertIn("server2.qcow2", textos)
        self.assertEqual(con_estado(rs, cd.ERROR), [])

    def test_error_conocido_de_virt_install(self):
        escribir(os.path.join(self.home, ".cache", "virt-manager", "virt-install.log"),
                 LINEA % MANUAL + "[Thu, 05 Nov 2026 10:00:02 virt-install 1234] ERROR "
                 "(cli:255) Size must be specified for non existent volume "
                 "'server1.qcow2'\n")
        rs = cd.comprobar_orden(self.home, UVUS, "alu0000-server1", existe=False)
        mal = con_estado(rs, cd.ERROR)[0]
        self.assertEqual(mal.fallo, "B3")
        self.assertIn("qemu-img create", mal.arreglo)

    def test_sin_registro(self):
        rs = cd.comprobar_orden(self.home, UVUS, "alu0000-server1")
        self.assertEqual(rs[0].estado, cd.OMITIDA)


def salida_guestfish(archivos, instancias):
    """Lo que escribe guestfish con las órdenes de leer_disco."""
    trozos = []
    for ruta in cd.ARCHIVOS_DISCO:
        contenido = archivos.get(ruta)
        trozos.append("%s %s\n%s\n%s" % (cd.MARCA, ruta, "false" if contenido is None
                                         else "true", contenido or ""))
    trozos.append("%s %s\n%s\n%s" % (cd.MARCA, cd.DIR_INSTANCIAS,
                                     "false" if instancias is None else "true",
                                     "".join(i + "\n" for i in instancias or [])))
    return "".join(trozos)


def resultado(errores=(), recuperables=None):
    return json.dumps({"v1": {"datasource": "DataSourceNoCloud [seed=/dev/sr0]",
                              "errors": list(errores),
                              "recoverable_errors": recuperables or {}}})


ESTADO = json.dumps({"v1": {"datasource": "DataSourceNoCloud [seed=/dev/sr0]"}})
NETPLAN = "network:\n" + "".join("  " + l + "\n" for l in NETWORK_CONFIG.splitlines())


def disco_bueno(**cambios):
    archivos = {
        "/var/lib/cloud/data/result.json": resultado(),
        "/var/lib/cloud/data/status.json": ESTADO,
        "/var/lib/cloud/instance/user-data.txt": USER_DATA.format(
            clave=Claves.publica("sin_frase")),
        "/home/administrador/.ssh/authorized_keys": Claves.publica("sin_frase") + "\n",
        "/etc/netplan/50-cloud-init.yaml": NETPLAN,
        "/var/log/cloud-init.log": "...\n",
    }
    archivos.update(cambios)
    return archivos


class TestLeerDisco(unittest.TestCase):

    def leer(self, codigo, salida, err=""):
        llamadas = []

        def falso(argv, timeout=30, entrada=None):
            llamadas.append((argv, entrada))
            return codigo, salida, err
        with mock.patch.object(cd, "ejecutar", falso):
            return cd.leer_disco("/home/alu0000/imagenesMV/server1.qcow2"), llamadas

    def test_lee_en_una_sola_sesion_de_solo_lectura(self):
        (archivos, instancias, problema), llamadas = self.leer(
            0, salida_guestfish(disco_bueno(), ["alu0000-server1"]))
        self.assertIsNone(problema)
        self.assertEqual(instancias, ["alu0000-server1"])
        self.assertIn("ssh-rsa", archivos["/home/administrador/.ssh/authorized_keys"])
        self.assertEqual(len(llamadas), 1)
        argv, entrada = llamadas[0]
        self.assertEqual(argv[:2], ["guestfish", "--ro"])
        for ruta in cd.ARCHIVOS_DISCO:
            self.assertIn("-cat %s" % ruta, entrada)

    def test_archivo_que_no_existe(self):
        (archivos, _, _), _ = self.leer(0, salida_guestfish(
            disco_bueno(**{"/home/administrador/.ssh/authorized_keys": None}), ["x"]))
        self.assertIsNone(archivos["/home/administrador/.ssh/authorized_keys"])

    def test_libguestfs_roto(self):
        # Mensaje grabado en avantasia el 3-nov (c1b1-v1.txt)
        (_, _, problema), _ = self.leer(
            1, "", "libguestfs: error: /usr/bin/supermin exited with error status 1.\n")
        self.assertEqual(problema.seccion, "faq-guestfs")
        self.assertIn("avise al profesor", problema.arreglo)

    def test_elige_la_linea_del_error(self):
        err = ("libguestfs: error: could not create appliance\n"
               "into a bug report or message to the libguestfs\nmailing list.\n")
        (_, _, problema), _ = self.leer(1, "", err)
        self.assertIn("could not create appliance", problema.detalle[0])

    def test_disco_bloqueado(self):
        (_, _, problema), _ = self.leer(1, "", 'qemu-img: Failed to get shared "write" lock\n')
        self.assertIn("encendida", problema.texto)


@necesita_yaml
class TestComprobarDisco(unittest.TestCase):

    def revisar(self, archivos, instancias=("alu0000-server1",), actual=None, iid=None):
        clave = cd.analizar_clave_publica(Claves.publica("sin_frase"))
        return cd.comprobar_disco(archivos, list(instancias) if instancias is not None
                                  else None, clave, actual, iid, red_de_prueba())

    def test_bueno(self):
        rs = self.revisar(disco_bueno())
        self.assertEqual(problemas(rs), [])
        self.assertIn("La máquina tiene su clave", texto_de(rs))

    def test_sin_instancias(self):
        rs = self.revisar(disco_bueno(), instancias=None)
        self.assertIn("no llegó a configurar", con_estado(rs, cd.ERROR)[0].texto)

    def test_dos_instancias(self):
        rs = self.revisar(disco_bueno(), instancias=("alu0000-server1", "alu0000-server2"))
        self.assertEqual([(r.estado, r.fallo) for r in problemas(rs)], [(cd.AVISO, "D2")])

    def test_sin_fuente_de_datos(self):
        rs = self.revisar(disco_bueno(**{"/var/lib/cloud/data/status.json":
                                         json.dumps({"v1": {"datasource": None}})}))
        self.assertIn("no encontró los archivos", con_estado(rs, cd.ERROR)[0].texto)

    def test_errores_de_cloud_init(self):
        rs = self.revisar(disco_bueno(**{"/var/lib/cloud/data/result.json": resultado(
            ["('users_groups', ValueError('x'))"], {"DEPRECATED": ["Key 'y' is deprecated"]})}))
        self.assertIn("users_groups", texto_de(con_estado(rs, cd.ERROR)))
        self.assertIn("DEPRECATED", texto_de(con_estado(rs, cd.AVISO)))

    def test_user_data_corregido_despues(self):
        # D2: el disco se configuró con el user-data anterior
        rs = self.revisar(disco_bueno(), actual="#cloud-config\n# otro\n",
                          iid="alu0000-server1")
        d2 = [r for r in rs if r.fallo == "D2"]
        self.assertEqual(len(d2), 1)
        self.assertIn("primer arranque", d2[0].efecto)

    def test_mismo_disco_con_user_data_corregido(self):
        # D2 visto en avantasia (6-nov): cloud-init guarda el user-data nuevo,
        # pero la clave instalada sigue siendo la del primer arranque
        rs = self.revisar(disco_bueno(**{"/home/administrador/.ssh/authorized_keys":
                                         Claves.publica("portatil") + "\n"}),
                          actual=USER_DATA.format(clave=Claves.publica("sin_frase")),
                          iid="alu0000-server1")
        errores = con_estado(rs, cd.ERROR)
        self.assertEqual([r.fallo for r in errores], ["D2"])
        self.assertIn("alu0000@portatil", texto_de(errores))

    def test_user_data_aplicado_con_fallos(self):
        aplicado = USER_DATA.format(clave=Claves.publica("portatil")).replace(
            "#cloud-config\n", "")
        rs = self.revisar(disco_bueno(**{"/var/lib/cloud/instance/user-data.txt": aplicado}))
        textos = [r.texto for r in con_estado(rs, cd.ERROR)]
        self.assertIn("En el user-data que se aplicó, la primera línea de user-data no es "
                      "#cloud-config", textos)

    def test_sin_authorized_keys(self):
        rs = self.revisar(disco_bueno(**{"/home/administrador/.ssh/authorized_keys": None}))
        self.assertIn("no tiene authorized_keys", con_estado(rs, cd.ERROR)[0].texto)

    def test_otra_clave_en_la_maquina(self):
        # B5: el user-data ya llevaba la clave del portátil
        portatil = Claves.publica("portatil")
        rs = self.revisar(disco_bueno(**{
            "/home/administrador/.ssh/authorized_keys": portatil + "\n",
            "/var/lib/cloud/instance/user-data.txt": USER_DATA.format(clave=portatil)}))
        mal = con_estado(rs, cd.ERROR)[0]
        self.assertEqual(mal.fallo, "B5")
        self.assertIn("alu0000@portatil", texto_de([mal]))

    def test_red_de_la_maquina(self):
        rs = self.revisar(disco_bueno(**{"/etc/netplan/50-cloud-init.yaml":
                                         NETPLAN.replace("enp1s0", "eth0")}))
        self.assertTrue(any(r.texto.startswith("En la red de la máquina, ")
                            for r in con_estado(rs, cd.ERROR)))

    def test_sin_netplan(self):
        rs = self.revisar(disco_bueno(**{"/etc/netplan/50-cloud-init.yaml": None}))
        self.assertEqual(con_estado(rs, cd.ERROR)[0].fallo, "B6")


if __name__ == "__main__":
    unittest.main()
