# --- El servidor: libvirt, silos, red, imagen, disco, nombres y permisos -------
#
# La conexión es de solo lectura (openReadOnly): libvirt rechaza cualquier
# cambio, aunque el código lo intentara. Todo se decide por los trayectos, nunca
# por los nombres de los silos, que no identifican al dueño (catálogo, sección 0).

URI = "qemu:///system"
IMAGEN_BASE = "noble-server-cloudimg-amd64.img"
TAM_IMAGEN_BASE = 3758096384          # 3.5 GiB (manual, 5.4.1)
TAM_DISCO = 40 * 1024 ** 3            # 40 GiB (manual, 5.4.2)
USUARIO_QEMU = "libvirt-qemu"


class SinLibvirt(Exception):
    pass


def abrir_conexion():
    try:
        import libvirt
    except ImportError:
        raise SinLibvirt("falta el módulo libvirt de Python (python3-libvirt)")
    # Sin esto, libvirt escribe sus errores por su cuenta en la salida de errores
    libvirt.registerErrorHandler(lambda contexto, error: None, None)
    try:
        return libvirt.openReadOnly(URI)
    except libvirt.libvirtError as e:
        raise SinLibvirt("no se puede conectar con %s: %s" % (URI, e))


def _xml(objeto, flags=0):
    return ET.fromstring(objeto.XMLDesc(flags))


def _real(ruta):
    return os.path.realpath(ruta)


class Silo:
    def __init__(self, pool):
        self.nombre = pool.name()
        raiz = _xml(pool)
        self.ruta = raiz.findtext("target/path")
        self.activo = bool(pool.isActive())
        try:
            self.autoarranque = bool(pool.autostart())
        except Exception:
            self.autoarranque = None
        self.pool = pool

    @property
    def real(self):
        return _real(self.ruta) if self.ruta else None


def leer_silos(conn):
    silos = []
    for p in conn.listAllStoragePools(0):
        try:
            silos.append(Silo(p))
        except Exception:
            continue
    return silos


def _nombres_no_utf8(ruta):
    try:
        nombres = os.listdir(os.fsencode(ruta))
    except OSError:
        return None
    malos = []
    for n in nombres:
        try:
            n.decode("utf-8")
        except UnicodeDecodeError:
            malos.append(n)
    return malos


def comprobar_entorno_compartido(silos, home):
    """A1: virt-install recorre los volúmenes de todos los silos activos (con
    XMLDesc de cada volumen) y falla para todos si alguno no se puede leer."""
    fallan = []
    for s in silos:
        if not s.activo:
            continue
        try:
            for v in s.pool.listAllVolumes(0):
                v.name()
                v.XMLDesc(0)
        except Exception:
            fallan.append(s)
    revisados = sum(1 for s in silos if s.activo)
    if not fallan:
        return [ok("Ningún silo del servidor impide usar virt-install "
                   "(%d silos activos revisados)" % revisados)]
    rs = []
    mensaje = "«'utf-8' codec can't decode ...» al procesar --disk"
    for s in fallan:
        propio = s.real and (s.real == _real(home) or s.real.startswith(_real(home) + os.sep))
        if propio:
            malos = _nombres_no_utf8(s.ruta) or []
            rs.append(error(
                "Su silo %s hace fallar a virt-install para todos" % s.nombre, fallo="A1",
                detalle=["Trayecto: %s" % s.ruta]
                + ["Nombre que no es UTF-8: %s" % escapar_nombre(m) for m in malos],
                efecto="virt-install falla a todos los usuarios del servidor con "
                       + mensaje + ".",
                arreglo="cambie el nombre de ese archivo (con mv y comillas) o "
                        "bórrelo, y avise al profesor.",
                seccion="silo"))
        else:
            rs.append(error(
                "El silo %s de otro usuario hace fallar a virt-install" % s.nombre,
                fallo="A1",
                detalle=["Trayecto: %s" % s.ruta],
                efecto="virt-install fallará con " + mensaje + ". No es culpa suya.",
                arreglo="avise al profesor y dígale el nombre del silo.",
                seccion="silo"))
    return rs


def _dentro_de(ruta, base):
    return ruta == base or ruta.startswith(base + os.sep)


def comprobar_silo(silos, uvus, home, directorio):
    """B2, B9 y sección 0: el directorio actual tiene que ser su silo."""
    rs = []
    home_r = _real(home)
    dir_r = _real(directorio)
    esperado = os.path.join(home_r, "imagenesMV")
    nombre_esperado = "%s-imagenesMV" % uvus
    del_dir = [s for s in silos if s.real == dir_r]

    if dir_r == home_r:
        rs.append(error("Está en su directorio personal, no en su silo", fallo="B2",
                        efecto="el disco y los archivos quedarían fuera del silo.",
                        arreglo="cd ~/imagenesMV", seccion="silo"))
    elif not del_dir:
        rs.append(error("El directorio actual (%s) no es un silo" % directorio, fallo="B2",
                        efecto="virt-install creará un silo automático sobre él.",
                        arreglo="cd ~/imagenesMV" if dir_r != esperado
                        else "defina el silo %s sobre este directorio." % nombre_esperado,
                        seccion="silo"))
    else:
        for s in del_dir:
            if re.match(r"^imagenesMV-\d+$", s.nombre) and dir_r == esperado:
                rs.append(aviso(
                    "El silo de %s es %s, un silo automático de virt-install" % (
                        directorio, s.nombre), fallo="B2",
                    efecto="no lo definió usted: no se llama %s." % nombre_esperado,
                    arreglo="no es grave: puede seguir usándolo.", seccion="silo"))
            elif s.nombre == nombre_esperado:
                rs.append(ok("%s es su silo %s" % (directorio, s.nombre)))
            else:
                rs.append(aviso("El silo de %s se llama %s, no %s" % (
                    directorio, s.nombre, nombre_esperado), seccion="silo"))
            if not s.activo:
                rs.append(error("El silo %s está parado" % s.nombre, fallo="B2",
                                efecto="virt-install no lo reconocerá como silo.",
                                arreglo="virsh pool-start %s" % s.nombre, seccion="silo"))
            elif s.autoarranque is False:
                rs.append(aviso("El silo %s no arranca solo" % s.nombre,
                                efecto="tras un reinicio del servidor estará parado.",
                                arreglo="virsh pool-autostart %s" % s.nombre,
                                seccion="silo"))
        if dir_r != esperado:
            rs.append(aviso("Según el manual, su silo es ~/imagenesMV", seccion="silo"))

    # Dueño y escritura del directorio actual (B9: si lo creó libvirt, es de root)
    try:
        st = os.stat(dir_r)
        if st.st_uid != os.getuid():
            try:
                dueno = pwd.getpwuid(st.st_uid).pw_name
            except KeyError:
                dueno = str(st.st_uid)
            rs.append(error("El directorio %s es de %s, no suyo" % (directorio, dueno),
                            fallo="B9",
                            efecto="no podrá crear en él el disco ni los archivos."
                            if not os.access(dir_r, os.W_OK) else None,
                            arreglo="si es de root, lo creó libvirt al definir el silo "
                                    "sobre un directorio que no existía: avise al profesor.",
                            seccion="silo"))
        elif not os.access(dir_r, os.W_OK):
            rs.append(error("No puede escribir en %s" % directorio, fallo="B9",
                            arreglo="chmod u+w %s" % directorio, seccion="silo"))
    except OSError:
        pass

    # Su silo con el nombre del manual, pero en otro sitio (B9)
    for s in silos:
        if s.nombre == nombre_esperado and s.real != dir_r:
            detalle = ["Trayecto: %s" % s.ruta]
            if not os.path.isdir(s.ruta or ""):
                detalle.append("Ese directorio no existe.")
            rs.append(aviso("Su silo %s no apunta a %s" % (s.nombre, directorio),
                            fallo="B9", detalle=detalle,
                            efecto="los archivos de este directorio no están en él.",
                            seccion="silo"))

    # Silos sobre su home entero o sobre su .ssh (sección 0)
    for s in silos:
        if s.real == home_r:
            rs.append(aviso(
                "Tiene un silo sobre su directorio personal: %s" % s.nombre,
                efecto="no hace falta, y cualquier archivo raro de su home puede "
                       "hacer fallar a virt-install para todos (A1).",
                arreglo="deténgalo y elimínelo desde virt-manager; no borra sus "
                        "archivos.", seccion="silo"))
        elif s.real and _dentro_de(s.real, home_r) and os.path.basename(s.real) == ".ssh":
            rs.append(aviso("Tiene un silo sobre %s: %s" % (s.ruta, s.nombre),
                            efecto="cualquier usuario del servidor puede manejar a "
                                   "través de libvirt los archivos de ese directorio.",
                            arreglo="deténgalo y elimínelo desde virt-manager; no borra "
                                    "sus archivos.", seccion="silo"))
    return rs


class RedLibvirt(Red):
    def __init__(self, net):
        raiz = _xml(net)
        self.nombre_libvirt = net.name()
        self.activa = bool(net.isActive())
        try:
            self.autoarranque = bool(net.autostart())
        except Exception:
            self.autoarranque = None
        forward = raiz.find("forward")
        self.modo = forward.get("mode") if forward is not None else None
        self.ipv6 = False
        ipv4 = None
        for ip in raiz.findall("ip"):
            if ip.get("family") == "ipv6" or ":" in (ip.get("address") or ""):
                self.ipv6 = True
            elif ipv4 is None:
                ipv4 = ip
        if ipv4 is None:
            raise ValueError("sin IPv4")
        prefijo = ipv4.get("prefix") or ipv4.get("netmask")
        interfaz = ipaddress.ip_interface("%s/%s" % (ipv4.get("address"), prefijo))
        rangos = [(r.get("start"), r.get("end")) for r in ipv4.findall("dhcp/range")]
        Red.__init__(self, net.name(), str(interfaz.network), str(interfaz.ip), rangos)


def comprobar_red(conn, uvus):
    """A2 y sección 5.3. Devuelve (resultados, RedLibvirt o None)."""
    rs = []
    nombre = "%s-red" % uvus
    redes, todas = {}, []
    for net in conn.listAllNetworks(0):
        try:
            r = RedLibvirt(net)
        except Exception:
            continue
        todas.append(r)
        redes[r.nombre] = r
    red = redes.get(nombre)
    if red is None:
        parecidas = sorted(n for n in redes if n.lower().startswith(uvus.lower()))
        rs.append(error("No existe la red %s" % nombre,
                        detalle=["Redes con su usuario: %s." % ", ".join(parecidas)]
                        if parecidas else [],
                        efecto="la máquina no tendrá red; la IP de network-config no "
                               "se puede comprobar.",
                        arreglo="créela como dice el manual, con ese nombre.",
                        seccion="red"))
        return rs, None

    if red.activa:
        rs.append(ok("La red %s existe y está activa (%s)" % (nombre, red.red)))
    else:
        rs.append(error("La red %s está parada" % nombre,
                        efecto="virt-install no podrá conectar la máquina.",
                        arreglo="virsh net-start %s" % nombre, seccion="red"))
    if red.autoarranque is False:
        rs.append(aviso("La red %s no arranca sola" % nombre,
                        efecto="tras un reinicio del servidor estará parada.",
                        arreglo="virsh net-autostart %s" % nombre, seccion="red"))
    if red.modo != "nat":
        rs.append(aviso("La red %s no es de tipo NAT" % nombre,
                        detalle=["Modo: %s" % (red.modo or "aislada")], seccion="red"))
    if red.red.prefixlen != 24 or red.pasarela != red.red.network_address + 1:
        rs.append(aviso("La red %s no es como la del manual" % nombre,
                        detalle=["Tiene %s con pasarela %s; el manual usa "
                                 "192.168.XXX.0/24 con pasarela .1." % (red.red, red.pasarela)],
                        seccion="red"))
    esperado = [(red.red.network_address + 128, red.red.network_address + 254)]
    if red.red.prefixlen == 24 and red.dhcp != esperado:
        rs.append(aviso("El DHCP de la red %s no es el del manual (de .128 a .254)" % nombre,
                        detalle=["Tiene: %s." % ", ".join("%s-%s" % r for r in red.dhcp)
                                 if red.dhcp else "Sin DHCP."],
                        seccion="red"))
    if red.ipv6:
        rs.append(aviso("La red %s tiene IPv6; el manual no lo activa" % nombre,
                        seccion="red"))

    # A2: otra red del servidor con la misma subred
    for otra in todas:
        if otra is red or not otra.red.overlaps(red.red):
            continue
        if otra.activa and not red.activa:
            rs.append(error("La red %s usa la misma subred que la suya" % otra.nombre,
                            fallo="A2", detalle=["Subred: %s" % otra.red],
                            efecto="mientras esa esté activa, la suya no podrá arrancar.",
                            arreglo="vuelva a crear su red con otro XXX (súmele 1).",
                            seccion="red"))
        else:
            rs.append(aviso("La red %s usa la misma subred que la suya" % otra.nombre,
                            fallo="A2", detalle=["Subred: %s" % otra.red],
                            efecto="si la otra se arranca antes que la suya (por ejemplo, "
                                   "tras un reinicio del servidor), la suya podría no arrancar.",
                            arreglo="vuelva a crear su red con otro XXX (súmele 1).",
                            seccion="red"))
    return rs, red


def info_imagen(ruta):
    """qemu-img info en JSON (con -U, por si la usa una máquina encendida)."""
    codigo, salida, err = ejecutar(["qemu-img", "info", "-U", "--output=json", ruta])
    if codigo is None:
        return None, "no se ha podido ejecutar qemu-img"
    if codigo != 0:
        return None, err.strip().splitlines()[-1] if err.strip() else "qemu-img falló"
    try:
        return json.loads(salida), None
    except ValueError:
        return None, "qemu-img devolvió algo que no es JSON"


def _escribible_por_otros(ruta):
    try:
        return stat.S_IMODE(os.stat(ruta).st_mode) & 0o022
    except OSError:
        return 0


def _aviso_escribible(ruta, nombre):
    modo = stat.S_IMODE(os.stat(ruta).st_mode)
    if modo & 0o002:
        efecto = "cualquier usuario del servidor podría estropearlo."
    else:
        efecto = ("cualquiera de su grupo podría estropearlo; con la máquina "
                  "encendida el grupo pasa a ser kvm, en el que están todos los alumnos.")
    return aviso(
        "%s lo pueden modificar otros usuarios (permisos %04o)" % (nombre, modo),
        efecto=efecto,
        arreglo="con las máquinas que lo usan apagadas: cp %s copia && chmod 644 copia && "
                "mv copia %s" % (nombre, nombre))


def comprobar_imagen_y_disco(directorio, maquina):
    """B3: la imagen base y el disco COW, con qemu-img info."""
    rs = []
    base = os.path.join(directorio, IMAGEN_BASE)
    if not os.path.exists(base):
        rs.append(error("No está la imagen base %s en el silo" % IMAGEN_BASE, fallo="B3",
                        efecto="no se puede crear el disco de la máquina.",
                        arreglo="descárguela en el silo sin cambiarle el nombre.",
                        seccion="preliminar"))
    else:
        info, problema = info_imagen(base)
        if info is None:
            rs.append(aviso("No se ha podido leer la imagen base: %s" % problema))
        elif info.get("format") != "qcow2":
            rs.append(error("La imagen base no está en formato qcow2", fallo="B3",
                            detalle=["Formato: %s" % info.get("format")],
                            efecto="la descarga no es la imagen cloud correcta.",
                            arreglo="bórrela y descárguela de nuevo.", seccion="preliminar"))
        elif info.get("virtual-size") != TAM_IMAGEN_BASE:
            rs.append(aviso("La imagen base no mide 3.5 GiB", fallo="B3",
                            detalle=["Tamaño virtual: %s bytes" % info.get("virtual-size")],
                            efecto="si Canonical ha cambiado la imagen, puede ser normal.",
                            seccion="preliminar"))
        else:
            rs.append(ok("Imagen base: qcow2 de 3.5 GiB"))
        if _escribible_por_otros(base):
            rs.append(_aviso_escribible(base, IMAGEN_BASE))

    if not maquina:
        rs.append(omitida("Disco de la máquina: no se sabe qué máquina es"))
        return rs
    nombre = "%s.qcow2" % maquina
    disco = os.path.join(directorio, nombre)
    crear = ("qemu-img create %s -f qcow2 -b %s -F qcow2 40G" % (nombre, IMAGEN_BASE))
    if not os.path.exists(disco):
        rs.append(error("No existe el disco %s" % nombre, fallo="B3",
                        arreglo=crear, seccion="instanciar"))
        return rs
    info, problema = info_imagen(disco)
    if info is None:
        rs.append(aviso("No se ha podido leer %s: %s" % (nombre, problema)))
        return rs
    malos = []
    if info.get("format") != "qcow2":
        malos.append("formato %s, no qcow2" % info.get("format"))
    if info.get("virtual-size") != TAM_DISCO:
        malos.append("tamaño virtual de %s bytes, no 40 GiB" % info.get("virtual-size"))
    respaldo = info.get("backing-filename")
    if respaldo is None:
        malos.append("no hace copia COW de ninguna imagen")
    elif os.path.basename(respaldo) != IMAGEN_BASE:
        malos.append("su respaldo es %s, no %s" % (respaldo, IMAGEN_BASE))
    if respaldo is not None and info.get("backing-filename-format") != "qcow2":
        malos.append("el formato del respaldo no es qcow2 (falta -F qcow2)")
    if malos:
        rs.append(error("El disco %s no es como el del manual" % nombre, fallo="B3",
                        detalle=[m[0].upper() + m[1:] + "." for m in malos],
                        arreglo="bórrelo y vuelva a crearlo: %s" % crear,
                        seccion="instanciar"))
    else:
        rs.append(ok("%s: qcow2 de 40 GiB, copia COW de %s" % (nombre, IMAGEN_BASE)))
    if respaldo is not None:
        completo = info.get("full-backing-filename") or os.path.join(directorio, respaldo)
        if not os.path.exists(completo):
            rs.append(error("No está la imagen de la que depende %s" % nombre, fallo="B3",
                            detalle=["Respaldo: %s" % completo],
                            efecto="la máquina no podrá arrancar.",
                            arreglo="la imagen base no se puede mover ni renombrar.",
                            seccion="instanciar"))
    if _escribible_por_otros(disco):
        rs.append(_aviso_escribible(disco, nombre))
    return rs


def discos_de(dominio):
    """Trayectos (reales) de los discos de una máquina."""
    try:
        raiz = _xml(dominio)
    except Exception:
        return []
    rutas = []
    for d in raiz.findall("devices/disk"):
        if d.get("device") != "disk":
            continue
        fuente = d.find("source")
        if fuente is not None and fuente.get("file"):
            rutas.append(_real(fuente.get("file")))
    return rutas


def responde_ping(ip):
    codigo, _, _ = ejecutar(["ping", "-c", "1", "-W", "1", str(ip)], timeout=5)
    return codigo == 0


def comprobar_nombres_libres(conn, uvus, home, directorio, maquina, ip=None, red=None):
    """A3, C1, C2 y D5. Devuelve (resultados, existe la máquina)."""
    rs = []
    dominios = list(conn.listAllDomains(0))
    nombres = {d.name(): d for d in dominios}
    home_r = _real(home)
    existe = False

    if maquina:
        nombre = "%s-%s" % (uvus, maquina)
        if nombre in nombres:
            existe = True
            rs.append(error("Ya existe la máquina %s" % nombre, fallo="C2",
                            efecto="virt-install dirá que el nombre está en uso.",
                            arreglo="si quiere volver a crearla, apáguela y elimínela "
                                    "con su disco (virsh destroy y virsh undefine "
                                    "--remove-all-storage). Si lo que pasa es que no puede "
                                    "entrar en ella, use ci-diagnosis --acceso.",
                            seccion="acceso"))
        else:
            rs.append(ok("El nombre %s está libre" % nombre))
        disco = _real(os.path.join(directorio, "%s.qcow2" % maquina))
        for d in dominios:
            if d.name() != nombre and disco in discos_de(d):
                rs.append(error("El disco %s.qcow2 ya lo usa la máquina %s" % (maquina, d.name()),
                                fallo="C2",
                                efecto="dos máquinas no pueden usar el mismo disco.",
                                arreglo="cree un disco nuevo para esta máquina.",
                                seccion="instanciar"))

    # Máquinas suyas (por los discos) sin el UVUS en el nombre
    for d in dominios:
        if d.name().startswith(uvus + "-"):
            continue
        if any(_dentro_de(r, home_r) for r in discos_de(d)):
            if d.name() == "oautoconsole":
                rs.append(aviso("Tiene una máquina llamada oautoconsole", fallo="C1",
                                efecto="la creó un virt-install con «-noautoconsole» (un "
                                       "solo guion): virt-install lo entiende como "
                                       "«--name oautoconsole».",
                                arreglo="elimínela; las opciones llevan dos guiones.",
                                seccion="instanciar"))
            else:
                rs.append(aviso("La máquina %s usa un disco suyo y no lleva su UVUS" % d.name(),
                                fallo="A3",
                                efecto="todos comparten la conexión: un nombre sin UVUS "
                                       "puede chocar con el de otro.",
                                seccion="instanciar"))

    # D5: algo responde ya en la IP de network-config
    if ip is not None and red is not None and red.activa and ip in red.red:
        if responde_ping(ip):
            if existe:
                rs.append(omitida("IP %s: responde (puede ser la propia máquina)" % ip))
            else:
                rs.append(error("Algo responde ya en la IP %s" % ip, fallo="D5",
                                efecto="otra máquina tiene esa IP: las dos funcionarían mal.",
                                arreglo="use otra IP entre la .2 y la .127.",
                                seccion="instanciar"))
        else:
            rs.append(ok("No responde nada en la IP %s (solo se ven las máquinas "
                         "encendidas)" % ip))
    return rs, existe


def _cadena_hasta(ruta):
    """Directorios desde / hasta ruta, incluida."""
    partes, actual = [], _real(ruta)
    while True:
        partes.append(actual)
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    return list(reversed(partes))


def _acl_permite(ruta, uid):
    """True/False si una ACL decide para ese usuario; None si no hay ACL."""
    try:
        datos = os.getxattr(ruta, "system.posix_acl_access")
    except (OSError, AttributeError):
        return None
    entradas = [struct.unpack("<HHI", datos[i:i + 8]) for i in range(4, len(datos) - 7, 8)]
    mascara = next((p for t, p, _ in entradas if t == 0x10), 7)
    for tag, perm, ident in entradas:
        if tag == 0x02 and ident == uid:
            return bool(perm & mascara & 1)
    return None


def puede_atravesar(ruta, uid, gids):
    st = os.stat(ruta)
    acl = _acl_permite(ruta, uid)
    if acl is not None:
        return acl
    if st.st_uid == uid:
        return bool(st.st_mode & stat.S_IXUSR)
    if st.st_gid in gids:
        return bool(st.st_mode & stat.S_IXGRP)
    return bool(st.st_mode & stat.S_IXOTH)


def comprobar_permisos(directorio):
    """B8: QEMU (libvirt-qemu) tiene que poder llegar hasta el silo."""
    try:
        usuario = pwd.getpwnam(USUARIO_QEMU)
    except KeyError:
        return [omitida("Permisos: no existe el usuario %s en este sistema" % USUARIO_QEMU)]
    gids = {usuario.pw_gid} | {g.gr_gid for g in grp.getgrall()
                                if USUARIO_QEMU in g.gr_mem}
    for d in _cadena_hasta(directorio):
        try:
            permite = puede_atravesar(d, usuario.pw_uid, gids)
        except OSError:
            continue
        if not permite:
            modo = stat.S_IMODE(os.stat(d).st_mode)
            return [error("%s no puede atravesar %s (permisos %04o)" % (USUARIO_QEMU, d, modo),
                          fallo="B8",
                          efecto="es probable que la máquina no pueda abrir su disco.",
                          arreglo="chmod o+x %s" % d, seccion="silo")]
    return [ok("%s puede llegar hasta %s" % (USUARIO_QEMU, directorio))]
