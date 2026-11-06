"""Un módulo libvirt de mentira para los tests locales.

Solo tiene los métodos de lectura que usa ci-diagnosis. Cualquier otro (refresh,
create, destroy, undefine...) hace fallar el test, y también cualquier intento
de abrir una conexión de escritura: así se comprueba que la herramienta solo lee.
"""

import sys
import types
from unittest import mock


class libvirtError(Exception):
    pass


class _Simulado:
    def __getattr__(self, nombre):
        raise AssertionError("ci-diagnosis ha llamado a %s.%s, que no es de solo lectura"
                             % (type(self).__name__, nombre))


class Volumen(_Simulado):
    def __init__(self, nombre, roto=False):
        self._nombre, self._roto = nombre, roto

    def _comprobar(self):
        if self._roto:   # Como el binding de Python con un nombre que no es UTF-8
            raise UnicodeDecodeError("utf-8", b"\xc3", 0, 1, "invalid continuation byte")

    def name(self):
        self._comprobar()
        return self._nombre

    def XMLDesc(self, flags=0):
        self._comprobar()
        return "<volume><name>%s</name></volume>" % self._nombre


class Silo(_Simulado):
    def __init__(self, nombre, ruta, activo=True, autoarranque=True, volumenes=()):
        self._nombre, self._ruta = nombre, ruta
        self._activo, self._auto = activo, autoarranque
        self._vols = list(volumenes)

    def name(self):
        return self._nombre

    def XMLDesc(self, flags=0):
        return ("<pool type='dir'><name>%s</name><target><path>%s</path></target></pool>"
                % (self._nombre, self._ruta))

    def isActive(self):
        return int(self._activo)

    def autostart(self):
        return int(self._auto)

    def listAllVolumes(self, flags=0):
        return list(self._vols)


class Red(_Simulado):
    def __init__(self, nombre, base="192.168.7", activa=True, autoarranque=True,
                 modo="nat", dhcp=(128, 254), ipv6=False):
        self._nombre, self._base = nombre, base
        self._activa, self._auto, self._modo = activa, autoarranque, modo
        self._dhcp, self._ipv6 = dhcp, ipv6

    def name(self):
        return self._nombre

    def XMLDesc(self, flags=0):
        forward = "<forward mode='%s'/>" % self._modo if self._modo else ""
        dhcp = ("<dhcp><range start='%s.%d' end='%s.%d'/></dhcp>"
                % (self._base, self._dhcp[0], self._base, self._dhcp[1])) if self._dhcp else ""
        ipv6 = "<ip family='ipv6' address='fd00::1' prefix='64'/>" if self._ipv6 else ""
        return ("<network><name>%s</name>%s<ip address='%s.1' netmask='255.255.255.0'>%s"
                "</ip>%s</network>" % (self._nombre, forward, self._base, dhcp, ipv6))

    def isActive(self):
        return int(self._activa)

    def autostart(self):
        return int(self._auto)


class Dominio(_Simulado):
    def __init__(self, nombre, discos=(), activo=False):
        self._nombre, self._discos, self._activo = nombre, list(discos), activo

    def name(self):
        return self._nombre

    def XMLDesc(self, flags=0):
        discos = "".join("<disk type='file' device='disk'><source file='%s'/></disk>" % d
                         for d in self._discos)
        return "<domain><name>%s</name><devices>%s</devices></domain>" % (self._nombre, discos)

    def isActive(self):
        return int(self._activo)


class Conexion(_Simulado):
    def __init__(self, silos=(), redes=(), dominios=()):
        self.silos, self.redes, self.dominios = list(silos), list(redes), list(dominios)
        self.cerrada = False

    def listAllStoragePools(self, flags=0):
        return list(self.silos)

    def listAllNetworks(self, flags=0):
        return list(self.redes)

    def listAllDomains(self, flags=0):
        return list(self.dominios)

    def close(self):
        self.cerrada = True
        return 0


def modulo(conexion):
    m = types.ModuleType("libvirt")
    m.libvirtError = libvirtError

    def solo_lectura(uri):
        assert uri == "qemu:///system", uri
        return conexion

    def escritura(*args, **kwargs):
        raise AssertionError("ci-diagnosis ha abierto una conexión de escritura")

    m.openReadOnly = solo_lectura
    m.open = m.openAuth = escritura
    m.registerErrorHandler = lambda funcion, contexto: None
    return m


def instalado(conexion):
    """Con «with instalado(conn):», import libvirt da el módulo simulado."""
    return mock.patch.dict(sys.modules, {"libvirt": modulo(conexion)})
