# --- Programa principal --------------------------------------------------------

USO = """\
Uso: ./ci-diagnosis [serverX] [--antes | --acceso] [--ip IP]

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
        if maquina and not existe:
            anterior = comprobar_intento_anterior(home, uvus, "%s-%s" % (uvus, maquina))
            if anterior:
                informe.bloque("Último virt-install", anterior)
        informe.bloque("Permisos", comprobar_permisos(directorio))
    return informe, maquina, existe


def _meta_del_silo(directorio):
    """(local-hostname, instance-id) de meta-data, o (None, None)."""
    datos = leer_bytes(os.path.join(directorio, "meta-data"))
    if datos is None or yaml is None:
        return None, None
    try:
        meta = yaml.safe_load(datos.decode("utf-8", "replace").lstrip("\ufeff"))
    except yaml.YAMLError:
        return None, None
    if not isinstance(meta, dict):
        return None, None
    host, iid = meta.get("local-hostname"), meta.get("instance-id")
    return (str(host) if host else None), (str(iid) if iid else None)


def _ip_de_network_config(directorio):
    """La IP fija de network-config: la de enp1s0 o, si no la tiene, la de la
    primera interfaz (con eth0 la máquina no la tendrá, pero es la que se espera)."""
    datos = leer_bytes(os.path.join(directorio, "network-config"))
    if datos is None or yaml is None:
        return None
    try:
        ethernets = yaml.safe_load(datos.decode("utf-8", "replace"))["ethernets"]
        nombres = [INTERFAZ] + [n for n in ethernets if n != INTERFAZ]
        for nombre in nombres:
            if isinstance(ethernets.get(nombre), dict):
                for direccion in _como_lista(ethernets[nombre].get("addresses")):
                    try:
                        return ipaddress.ip_interface(str(direccion)).ip
                    except ValueError:
                        continue
    except Exception:
        pass
    return None


def diagnosticar_acceso(uvus, home, directorio, maquina, conn, ip_forzada=None):
    """Revisión de una máquina ya creada en la que no se puede entrar."""
    informe = Informe()
    nombre = "%s-%s" % (uvus, maquina)
    dominio = buscar_dominio(conn, nombre)
    if dominio is None:
        informe.bloque("Máquina", [error(
            "No existe la máquina %s" % nombre,
            arreglo="si todavía no la ha creado, revise antes su trabajo con "
                    "./ci-diagnosis --antes.", seccion="instanciar")])
        return informe
    m = Maquina(dominio)
    informe.bloque("Máquina", comprobar_maquina(m, uvus))
    res_claves, clave = comprobar_claves(home)
    res_red, red = comprobar_red(conn, uvus)
    problemas_red = [r for r in res_red if r.estado in (ERROR, AVISO)]
    if problemas_red:
        informe.bloque("Red", problemas_red)

    # La IP: la indicada, la de network-config si es de esta máquina, o la de ARP
    _, iid = _meta_del_silo(directorio)
    ip, origen = ip_forzada, "--ip"
    if ip is None and iid == nombre:
        ip, origen = _ip_de_network_config(directorio), "network-config"
    if ip is None and m.encendida:
        ip, origen = ip_por_arp(dominio), "las tablas ARP del servidor"

    entra = False
    if m.encendida:
        if ip is None:
            if iid == nombre:
                motivo = "network-config no tiene una dirección IP válida"
            elif iid:
                motivo = "el meta-data del silo es de otra máquina (%s)" % iid
            else:
                motivo = "no hay meta-data en este directorio"
            informe.bloque("Conectividad", [omitida(
                "No se sabe la IP de la máquina: %s. Indíquela con --ip" % motivo)])
        else:
            res_con, abierto = comprobar_conectividad(ip)
            informe.bloque("Conectividad", [ok("IP %s (de %s)" % (ip, origen))] + res_con)
            if abierto:
                cifrada, en_agente = estado_de_la_clave(home)
                res_ssh, entra = comprobar_ssh(ip, home, cifrada, en_agente, maquina)
                informe.bloque("Acceso por SSH", res_ssh)
        if not entra:
            informe.bloque("Disco de la máquina", [omitida(
                "Para revisar su disco, apáguela (virsh shutdown %s), espere a que "
                "virsh domstate %s diga «shut off» y vuelva a ejecutar ./ci-diagnosis"
                % (nombre, nombre))])
    elif m.apagada:
        informe.bloque("Conectividad", [omitida("Conectividad y SSH: la máquina está apagada")])
        informe.bloque("Disco de la máquina", revisar_disco(conn, m, clave, directorio,
                                                            iid, red))
    if not entra:
        informe.bloque("Orden de virt-install", comprobar_orden(home, uvus, nombre))
        res_archivos, _, _ = diagnosticar_archivos(uvus, directorio, maquina, clave, red)
        informe.bloque("Archivos de cloud-init (en el silo)", res_archivos)
    informe.bloque("Claves SSH", res_claves)
    return informe


def revisar_disco(conn, maquina, clave, directorio, iid, red):
    if not maquina.discos:
        return [error("La máquina no tiene ningún disco", seccion="instanciar")]
    disco = maquina.discos[0]
    for d in conn.listAllDomains(0):
        if d.name() != maquina.nombre and d.isActive() and disco in discos_de(d):
            return [error("El disco lo está usando la máquina encendida %s" % d.name(),
                          fallo="C2", seccion="instanciar")]
    info, _ = info_imagen(disco)
    respaldo = (info or {}).get("backing-filename")
    if respaldo:
        completo = info.get("full-backing-filename") or os.path.join(
            os.path.dirname(disco), respaldo)
        if not os.path.exists(completo):
            # Visto en avantasia (6-nov): virsh start dice «Cannot access backing
            # file ... No such file or directory», y guestfish no puede leer el disco
            return [error("No está la imagen de la que depende el disco de la máquina",
                          fallo="B3", detalle=["Disco: %s" % disco, "Respaldo: %s" % completo],
                          efecto="la máquina no puede arrancar («Cannot access backing file "
                                 "... No such file or directory») y su disco no se puede leer.",
                          arreglo="devuelva la imagen base a ese sitio, con ese nombre: la "
                                  "imagen base no se puede mover ni renombrar.",
                          seccion="instanciar")]
    previo = comprobar_libguestfs()
    if previo is not None and previo.estado == ERROR:
        return [previo]
    archivos, instancias, problema = leer_disco(disco)
    if problema is not None:
        return [problema]
    actual = leer_bytes(os.path.join(directorio, "user-data"))
    actual = actual.decode("utf-8", "replace") if actual is not None else None
    rs = [ok("Disco leído: %s" % disco)] + ([previo] if previo else [])
    return rs + comprobar_disco(archivos, instancias, clave, actual, iid, red)


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
        print("Consulte la ayuda con: ./ci-diagnosis --ayuda", file=sys.stderr)
        return 2
    if opciones["ayuda"]:
        print(USO, end="")
        return 0
    if opciones["version"]:
        print("ci-diagnosis %s" % VERSION)
        return 0
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
        if maquina is None:
            maquina = normalizar_maquina(_meta_del_silo(directorio)[0], uvus)
        modo = opciones["modo"]
        if modo is None:
            existe = maquina is not None and buscar_dominio(
                conn, "%s-%s" % (uvus, maquina)) is not None
            modo = "acceso" if existe else "antes"
        if modo == "acceso":
            if maquina is None:
                print("ci-diagnosis: indique qué máquina quiere revisar "
                      "(por ejemplo: ./ci-diagnosis server1 --acceso).", file=sys.stderr)
                return 2
            informe = diagnosticar_acceso(uvus, home, directorio, maquina, conn,
                                          opciones["ip"])
        else:
            informe, maquina, _ = diagnosticar_antes(uvus, home, directorio, maquina, conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    servidor = os.uname().nodename.split(".")[0]
    print("ci-diagnosis %s · %s · usuario: %s · máquina: %s" % (
        VERSION, servidor, uvus, "%s-%s" % (uvus, maquina) if maquina else "sin determinar"))
    if modo == "acceso":
        print("Modo: no puede entrar en la máquina (--acceso)")
        if opciones["modo"] is None:
            print("(La máquina ya existe. Para revisarla como antes de crearla: --antes)")
    else:
        print("Modo: antes de virt-install (--antes)")
    if "dev" in VERSION:
        print("(Versión en desarrollo.)")
    print()
    for linea in formatear_informe(informe, usar_color(sys.stdout)):
        print(linea)
    return informe.codigo_salida()


if __name__ == "__main__":
    sys.exit(main())
