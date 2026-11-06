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


def diagnosticar_archivos(uvus, directorio, maquina, clave, red):
    """Los tres archivos de cloud-init. Devuelve (resultados, máquina, IP)."""
    res, ip = [], None
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
            r, ip = comprobar_network_config(texto, red)
            res += r
    return res, maquina, ip


def diagnosticar_antes(uvus, home, directorio, maquina, conn=None):
    """Comprobaciones antes de virt-install.

    Sin conexión (conn=None) solo se revisan los archivos y las claves: lo usan
    los tests de esas partes. Devuelve (informe, máquina, existe la máquina).
    """
    informe = Informe()
    res_claves, clave = comprobar_claves(home)
    red, existe = None, False
    if conn is not None:
        silos = leer_silos(conn)
        informe.bloque("Entorno compartido", comprobar_entorno_compartido(silos, home))
        informe.bloque("Directorio y silo", comprobar_silo(silos, uvus, home, directorio))
        res_red, red = comprobar_red(conn, uvus)
        informe.bloque("Red", res_red)
    res_archivos, maquina, ip = diagnosticar_archivos(uvus, directorio, maquina, clave, red)
    if conn is not None:
        informe.bloque("Imagen y disco", comprobar_imagen_y_disco(directorio, maquina))
    informe.bloque("Archivos de cloud-init", res_archivos)
    informe.bloque("Claves SSH", res_claves)
    if conn is not None:
        res_nombres, existe = comprobar_nombres_libres(conn, uvus, home, directorio,
                                                       maquina, ip, red)
        informe.bloque("Nombres libres", res_nombres)
        informe.bloque("Permisos", comprobar_permisos(directorio))
    return informe, maquina, existe


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
    try:
        conn = abrir_conexion()
    except SinLibvirt as e:
        print("ci-diagnosis: %s." % e, file=sys.stderr)
        print("Sin libvirt no se puede hacer la revisión: avise al profesor.",
              file=sys.stderr)
        return 2
    try:
        informe, maquina, existe = diagnosticar_antes(uvus, home, directorio, maquina, conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    servidor = os.uname().nodename.split(".")[0]
    print("ci-diagnosis %s · %s · usuario: %s · máquina: %s" % (
        VERSION, servidor, uvus, "%s-%s" % (uvus, maquina) if maquina else "sin determinar"))
    print("Modo: antes de virt-install")
    if existe and opciones["modo"] is None:
        print("(La máquina ya existe. La revisión --acceso, para cuando no puede "
              "entrar en ella, todavía no está disponible.)")
    print("(Versión en desarrollo.)")
    print()
    for linea in formatear_informe(informe, usar_color(sys.stdout)):
        print(linea)
    return informe.codigo_salida()


if __name__ == "__main__":
    sys.exit(main())
