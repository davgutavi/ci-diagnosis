"""ci-diagnosis: diagnóstico de máquinas virtuales construidas con cloud-init.

Asignatura Sistemas Operativos, Universidad de Sevilla.
https://github.com/davgutavi/ci-diagnosis

Este archivo se genera con tools/build.py a partir de src/: no lo edite a mano.

La herramienta solo lee: no cambia archivos, no arranca ni apaga máquinas, no
toca silos ni redes y no muestra nunca la clave privada.
"""

import base64
import grp
import hashlib
import ipaddress
import json
import os
import pwd
import re
import socket
import stat
import struct
import subprocess
import sys
import textwrap
import unicodedata
import xml.etree.ElementTree as ET

try:
    import yaml
except ImportError:  # sin PyYAML se omiten las comprobaciones de estructura
    yaml = None

VERSION = "1.0.1"

# Si José Antonio decide que la herramienta solo señale los fallos, basta con
# poner esto a False: «Cómo arreglarlo» desaparece de toda la salida.
MOSTRAR_ARREGLO = True

OK = "OK"
AVISO = "AVISO"
ERROR = "ERROR"
OMITIDA = "--"


class Resultado:
    """El resultado de una comprobación.

    estado   OK, AVISO, ERROR u OMITIDA (no comprobada: falla algo de lo que depende)
    texto    una línea con lo comprobado o lo que falla
    fallo    código del catálogo (B5, D6...), si lo hay
    detalle  líneas con datos concretos (números de línea, huellas...)
    efecto   qué pasará si no se arregla
    arreglo  cómo arreglarlo
    seccion  clave de SECCIONES (textos.py)
    """

    def __init__(self, estado, texto, fallo=None, detalle=(), efecto=None,
                 arreglo=None, seccion=None):
        self.estado = estado
        self.texto = texto
        self.fallo = fallo
        self.detalle = list(detalle)
        self.efecto = efecto
        self.arreglo = arreglo
        self.seccion = seccion

    def __repr__(self):
        return "Resultado(%s, %r, %s)" % (self.estado, self.texto, self.fallo)


def ok(texto, **kw):
    return Resultado(OK, texto, **kw)


def aviso(texto, **kw):
    return Resultado(AVISO, texto, **kw)


def error(texto, **kw):
    return Resultado(ERROR, texto, **kw)


def omitida(texto, **kw):
    return Resultado(OMITIDA, texto, **kw)


class Informe:
    """Resultados agrupados por bloques, en el orden en que se comprueban."""

    def __init__(self):
        self.bloques = []

    def bloque(self, titulo, resultados):
        self.bloques.append((titulo, list(resultados)))

    def todos(self):
        return [r for _, rs in self.bloques for r in rs]

    def cuenta(self, estado):
        return sum(1 for r in self.todos() if r.estado == estado)

    def codigo_salida(self):
        return 1 if self.cuenta(ERROR) else 0


# --- Salida ---------------------------------------------------------------

ANCHO = 78
SANGRIA = " " * 9
COLORES = {OK: "\033[32m", AVISO: "\033[33m", ERROR: "\033[31m", OMITIDA: "\033[2m"}
FIN_COLOR = "\033[0m"


def _envolver(texto, primera, resto):
    return textwrap.wrap(texto, ANCHO, initial_indent=primera,
                         subsequent_indent=resto, break_on_hyphens=False,
                         break_long_words=False) or [primera.rstrip()]


def formatear_resultado(r, color=False):
    etiqueta = r.estado.ljust(7)
    if color:
        etiqueta = COLORES[r.estado] + r.estado + FIN_COLOR + " " * (7 - len(r.estado))
    texto = r.texto + (" [%s]" % r.fallo if r.fallo else "")
    lineas = _envolver(texto, "  " + "X" * 7, SANGRIA)
    lineas[0] = "  " + etiqueta + lineas[0][9:]
    if r.estado in (OK, OMITIDA):
        return lineas
    for d in r.detalle:
        lineas += _envolver(d, SANGRIA, SANGRIA + "  ")
    if r.efecto:
        lineas += _envolver("Efecto: " + r.efecto, SANGRIA, SANGRIA)
    if r.arreglo and MOSTRAR_ARREGLO:
        lineas += _envolver("Cómo arreglarlo: " + r.arreglo, SANGRIA, SANGRIA)
    if r.seccion:
        lineas += _envolver("Manual: " + SECCIONES[r.seccion], SANGRIA, SANGRIA)
    return lineas


def formatear_informe(informe, color=False):
    lineas = []
    for titulo, resultados in informe.bloques:
        lineas.append(titulo.upper())
        for r in resultados:
            lineas += formatear_resultado(r, color)
        lineas.append("")
    errores, avisos = informe.cuenta(ERROR), informe.cuenta(AVISO)
    if errores:
        lineas.append("Resultado: %d ERROR, %d AVISO. Empiece por el primer ERROR: "
                      "los demás pueden ser consecuencia suya." % (errores, avisos))
    elif avisos:
        lineas.append("Resultado: ningún ERROR y %d AVISO. Revise los avisos." % avisos)
    else:
        lineas.append("Resultado: todo correcto.")
    return lineas


def usar_color(flujo):
    return flujo.isatty() and "NO_COLOR" not in os.environ


# --- Órdenes externas -------------------------------------------------------

# Solo estas, y todas solo para leer. Cualquier otra es un error de programación.
ORDENES_PERMITIDAS = ("qemu-img", "ssh-keygen", "ssh", "ssh-add", "ping",
                      "guestfish", "virt-cat", "virt-ls")


def ejecutar(argv, timeout=30, entrada=None):
    """Ejecuta una orden de la lista blanca, sin teclado y con LC_ALL=C.

    entrada: texto que recibe por la entrada estándar (lo usa guestfish para
    leer sus órdenes); sin ella, la entrada es /dev/null.

    Devuelve (código, salida, errores). El código es None si la orden no existe
    o no termina a tiempo.
    """
    if argv[0] not in ORDENES_PERMITIDAS:
        raise ValueError("orden no permitida: %s" % argv[0])
    entorno = dict(os.environ, LC_ALL="C", LANG="C")
    extra = ({"input": entrada.encode("utf-8")} if entrada is not None
             else {"stdin": subprocess.DEVNULL})
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=entorno, timeout=timeout, **extra)
    except (OSError, subprocess.TimeoutExpired):
        return None, "", ""
    return (p.returncode, p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def leer_bytes(ruta):
    """Contenido de un archivo, o None si no existe o no se puede leer."""
    try:
        with open(ruta, "rb") as f:
            return f.read()
    except OSError:
        return None
