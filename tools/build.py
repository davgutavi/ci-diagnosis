#!/usr/bin/env python3
"""Genera el archivo distribuible ci-diagnosis a partir de los fuentes de src/.

    python3 tools/build.py            escribe ./ci-diagnosis
    python3 tools/build.py SALIDA     escribe en otra ruta (lo usan los tests)

Los fuentes son fragmentos de un único programa: se concatenan en este orden y
comparten el espacio de nombres. Las importaciones van todas en base.py.
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDEN = ["base", "textos", "claves", "archivos", "main"]
CABECERA = "#!/usr/bin/python3\n"


def construir():
    trozos = []
    for nombre in ORDEN:
        with open(os.path.join(RAIZ, "src", nombre + ".py"), encoding="utf-8") as f:
            trozos.append(f.read().rstrip("\n") + "\n")
    return CABECERA + "\n\n".join(trozos)


def main():
    salida = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "ci-diagnosis")
    codigo = construir()
    compile(codigo, salida, "exec")
    with open(salida, "w", encoding="utf-8") as f:
        f.write(codigo)
    os.chmod(salida, 0o755)
    print("Generado: %s" % salida)


if __name__ == "__main__":
    main()
