# --- Programa principal --------------------------------------------------------

USO = """\
Uso: ci-diagnosis [serverX] [--antes | --acceso] [--ip IP]

Revisa la construcción de una máquina virtual con cloud-init (manual,
sección 5.4) y dice qué falla. Ejecútelo desde su silo (~/imagenesMV).

  serverX     la máquina que quiere revisar: server1, 1 o <uvus>-server1.
              Si no la indica, se toma del local-hostname de meta-data.
  --antes     revisión antes de virt-install (silo, red, imagen, archivos,
              claves).
  --acceso    revisión de una máquina ya creada en la que no puede entrar.
  --ip IP     la IP de la máquina, si no es la de su network-config.
  --version   muestra la versión.
  --ayuda     muestra esta ayuda.

Solo lee: no cambia archivos, no arranca ni apaga máquinas y no muestra
nunca su clave privada. Código de salida: 0 sin errores, 1 si hay algún
ERROR, 2 si la herramienta no ha podido hacer la revisión.
"""


class ErrorDeUso(Exception):
    pass


def analizar_argumentos(argv):
    opciones = {"maquina": None, "modo": None, "ip": None,
                "ayuda": False, "version": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--ayuda", "-h", "--help"):
            opciones["ayuda"] = True
        elif a == "--version":
            opciones["version"] = True
        elif a in ("--antes", "--acceso"):
            if opciones["modo"] and opciones["modo"] != a[2:]:
                raise ErrorDeUso("--antes y --acceso no pueden ir juntas.")
            opciones["modo"] = a[2:]
        elif a == "--ip" or a.startswith("--ip="):
            if a == "--ip":
                i += 1
                if i == len(argv):
                    raise ErrorDeUso("falta la IP después de --ip.")
                valor = argv[i]
            else:
                valor = a[len("--ip="):]
            try:
                opciones["ip"] = ipaddress.ip_address(valor)
            except ValueError:
                raise ErrorDeUso("«%s» no es una dirección IP." % valor)
        elif a.startswith("-"):
            raise ErrorDeUso("opción desconocida: %s (las opciones empiezan por "
                             "dos guiones)." % a)
        elif opciones["maquina"] is None:
            opciones["maquina"] = a
        else:
            raise ErrorDeUso("sobra «%s»: indique una sola máquina." % a)
        i += 1
    return opciones


def normalizar_maquina(nombre, uvus):
    """server1, 1 o <uvus>-server1 → server1."""
    if nombre is None:
        return None
    if nombre.startswith(uvus + "-"):
        nombre = nombre[len(uvus) + 1:]
    if nombre.isdigit():
        nombre = "server" + nombre
    return nombre


def diagnosticar_antes(uvus, home, directorio, maquina, red=None):
    """Comprobaciones antes de virt-install. Devuelve (informe, máquina)."""
    informe = Informe()
    res_claves, clave = comprobar_claves(home)

    res = []
    for nombre, (r, datos) in comprobar_nombres(directorio).items():
        res += r
        if datos is None:
            continue
        r, texto = comprobar_texto(nombre, datos)
        res += r
        if texto is None:
            continue
        if nombre == "user-data":
            res += comprobar_user_data(texto, clave)
        elif nombre == "meta-data":
            r, meta = comprobar_meta_data(texto, uvus, maquina)
            res += r
            if maquina is None and isinstance(meta, dict) and meta.get("local-hostname"):
                maquina = str(meta["local-hostname"])
        else:
            res += comprobar_network_config(texto, red)[0]
    informe.bloque("Archivos de cloud-init", res)
    informe.bloque("Claves SSH", res_claves)
    return informe, maquina


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        opciones = analizar_argumentos(argv)
    except ErrorDeUso as e:
        print("ci-diagnosis: %s" % e, file=sys.stderr)
        print("Consulte la ayuda con: ci-diagnosis --ayuda", file=sys.stderr)
        return 2
    if opciones["ayuda"]:
        print(USO, end="")
        return 0
    if opciones["version"]:
        print("ci-diagnosis %s" % VERSION)
        return 0
    if opciones["modo"] == "acceso":
        print("ci-diagnosis: --acceso todavía no está disponible.", file=sys.stderr)
        return 2

    # El usuario de la cuenta, no el de las variables de entorno. Para las
    # pruebas locales se puede fijar con CI_DIAGNOSIS_USUARIO.
    uvus = (os.environ.get("CI_DIAGNOSIS_USUARIO")
            or pwd.getpwuid(os.getuid()).pw_name)
    home = os.path.expanduser("~")
    directorio = os.getcwd()
    maquina = normalizar_maquina(opciones["maquina"], uvus)
    informe, maquina = diagnosticar_antes(uvus, home, directorio, maquina)

    servidor = os.uname().nodename.split(".")[0]
    print("ci-diagnosis %s · %s · usuario: %s · máquina: %s" % (
        VERSION, servidor, uvus, "%s-%s" % (uvus, maquina) if maquina else "sin determinar"))
    print("Modo: antes de virt-install")
    print("(Versión en desarrollo: de momento solo revisa los archivos de "
          "cloud-init y las claves.)")
    print()
    for linea in formatear_informe(informe, usar_color(sys.stdout)):
        print(linea)
    return informe.codigo_salida()


if __name__ == "__main__":
    sys.exit(main())
