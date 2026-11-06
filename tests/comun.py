"""Preparación común de los tests locales.

Los tests cargan el archivo distribuible (ci-diagnosis), que es lo que usa el
alumnado, no los fuentes de src/. Ningún test usa claves, cuentas ni UVUS
reales: el alumno de prueba es «alu0000» y las claves se generan al vuelo.
"""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RAIZ, "ci-diagnosis")
UVUS = "alu0000"


def cargar():
    if "ci_diagnosis" not in sys.modules:
        cargador = importlib.machinery.SourceFileLoader("ci_diagnosis", SCRIPT)
        spec = importlib.util.spec_from_loader("ci_diagnosis", cargador)
        modulo = importlib.util.module_from_spec(spec)
        cargador.exec_module(modulo)
        sys.modules["ci_diagnosis"] = modulo
    return sys.modules["ci_diagnosis"]


cd = cargar()

# Lo que comprueba la estructura de los archivos necesita PyYAML
necesita_yaml = __import__("unittest").skipIf(cd.yaml is None, "sin PyYAML")


def generar_clave(directorio, nombre, frase="", comentario="alu0000@avantasia",
                  formato=None):
    """Pareja de claves RSA desechable. Devuelve la ruta de la privada."""
    ruta = os.path.join(directorio, nombre)
    orden = ["ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", frase,
             "-C", comentario, "-f", ruta]
    if formato:
        orden += ["-m", formato]
    subprocess.run(orden, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL)
    return ruta


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def escribir(ruta, contenido, modo=None):
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    with open(ruta, "wb") as f:
        f.write(datos)
    if modo is not None:
        os.chmod(ruta, modo)


class Claves:
    """Tres parejas de claves para todos los tests: la del servidor sin frase,
    la del servidor con frase y la «del portátil»."""

    _dir = None

    @classmethod
    def preparar(cls):
        if cls._dir is None:
            cls._tmp = tempfile.TemporaryDirectory()
            cls._dir = cls._tmp.name
            cls.sin_frase = generar_clave(cls._dir, "sin_frase")
            cls.con_frase = generar_clave(cls._dir, "con_frase", frase="frase de prueba")
            cls.portatil = generar_clave(cls._dir, "portatil", comentario="alu0000@portatil")
            cls.pem = generar_clave(cls._dir, "pem", formato="PEM")
            cls.pem_frase = generar_clave(cls._dir, "pem_frase", frase="otra frase",
                                          formato="PEM")
        return cls

    @classmethod
    def publica(cls, nombre):
        return leer(getattr(cls.preparar(), nombre) + ".pub").strip()


USER_DATA = """#cloud-config
users:
  - name: administrador
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    groups: sudo
    shell: /bin/bash
    ssh_authorized_keys:
      - {clave}
"""

META_DATA = """instance-id: alu0000-server1
local-hostname: server1
"""

NETWORK_CONFIG = """version: 2
ethernets:
  enp1s0:
    addresses:
      - 192.168.7.2/24
    routes:
      - to: default
        via: 192.168.7.1
    nameservers:
      addresses:
        - 150.214.186.69
        - 150.214.130.15
"""


def red_de_prueba():
    return cd.Red("alu0000-red", "192.168.7.0/24", "192.168.7.1",
                  [("192.168.7.128", "192.168.7.254")])


def estados(resultados):
    """[(estado, fallo)] para comparar de un vistazo."""
    return [(r.estado, r.fallo) for r in resultados]


def con_estado(resultados, estado):
    return [r for r in resultados if r.estado == estado]


def problemas(resultados):
    return [r for r in resultados if r.estado in (cd.ERROR, cd.AVISO)]


def texto_de(resultados):
    """La salida tal y como la vería el alumno."""
    lineas = []
    for r in resultados:
        lineas += cd.formatear_resultado(r)
    return "\n".join(lineas)
