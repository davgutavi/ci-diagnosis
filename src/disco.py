# --- El disco de la máquina, con la máquina apagada (B4, B5, B6, D2) ------------
#
# Se lee con una sola sesión de guestfish en solo lectura (--ro): cada arranque
# de libguestfs tarda de 8 a 15 s en los servidores. guestfish trabaja sobre una
# copia temporal: el disco no se modifica.

ARCHIVOS_DISCO = (
    "/var/lib/cloud/data/result.json",
    "/var/lib/cloud/data/status.json",
    "/var/lib/cloud/instance/user-data.txt",
    "/home/administrador/.ssh/authorized_keys",
    "/etc/netplan/50-cloud-init.yaml",
    "/var/log/cloud-init.log",
)
DIR_INSTANCIAS = "/var/lib/cloud/instances"
MARCA = "==CI-DIAGNOSIS=="


def comprobar_libguestfs():
    """Lo que necesita libguestfs para funcionar con una cuenta normal."""
    nucleo = "/boot/vmlinuz-%s" % os.uname().release
    if os.path.exists(nucleo) and not os.access(nucleo, os.R_OK):
        return error("No se puede leer el núcleo del servidor (%s)" % nucleo,
                     efecto="no se puede revisar el disco de la máquina.",
                     arreglo="avise al profesor: es un ajuste del servidor.",
                     seccion="faq-guestfs")
    if os.path.exists("/dev/kvm") and not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return aviso("No tiene acceso a /dev/kvm: revisar el disco será muy lento",
                     arreglo="avise al profesor.")
    return None


def leer_disco(disco):
    """Lee los archivos de ARCHIVOS_DISCO y la lista de instancias de cloud-init.

    Devuelve (archivos, instancias, problema): archivos, {ruta: texto o None si no
    existe}; instancias, lista de nombres o None; problema, un Resultado si no se
    ha podido leer el disco.
    """
    ordenes = []
    for ruta in ARCHIVOS_DISCO:
        ordenes += ["echo %s %s" % (MARCA, ruta), "-is-file %s" % ruta, "-cat %s" % ruta]
    ordenes += ["echo %s %s" % (MARCA, DIR_INSTANCIAS), "-is-dir %s" % DIR_INSTANCIAS,
                "-ls %s" % DIR_INSTANCIAS]
    codigo, salida, err = ejecutar(
        ["guestfish", "--ro", "--format=qcow2", "-a", disco, "-i"],
        timeout=300, entrada="\n".join(ordenes) + "\n")
    if codigo is None:
        return {}, None, error("guestfish no ha terminado a tiempo (o no está instalado)",
                               arreglo="avise al profesor.", seccion="faq-guestfs")
    if MARCA not in salida:
        ultima = [l for l in err.strip().splitlines() if l.strip()][-1:] or ["(sin mensaje)"]
        if "supermin" in err:
            return {}, None, error("libguestfs no funciona en el servidor",
                                   detalle=["guestfish dice: %s" % ultima[0]],
                                   arreglo="avise al profesor.", seccion="faq-guestfs")
        if "lock" in err:
            return {}, None, error("El disco está en uso (¿la máquina sigue encendida?)",
                                   detalle=["guestfish dice: %s" % ultima[0]],
                                   seccion="acceso")
        return {}, None, error("No se ha podido leer el disco",
                               detalle=["guestfish dice: %s" % ultima[0]],
                               arreglo="avise al profesor.", seccion="faq-guestfs")
    archivos, instancias = {}, None
    for trozo in salida.split(MARCA + " ")[1:]:
        cabecera, _, resto = trozo.partition("\n")
        ruta = cabecera.strip()
        existe, _, contenido = resto.partition("\n")
        if ruta == DIR_INSTANCIAS:
            instancias = ([l for l in contenido.splitlines() if l.strip()]
                          if existe.strip() == "true" else None)
        else:
            archivos[ruta] = contenido if existe.strip() == "true" else None
    return archivos, instancias, None


def claves_de_user_data(texto):
    """Las claves de administrador en un user-data (vacío si no se puede leer)."""
    if yaml is None:
        return []
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError:
        return []
    claves = []
    for u in (datos or {}).get("users") or [] if isinstance(datos, dict) else []:
        if isinstance(u, dict) and u.get("name") == USUARIO_VM:
            for k in _como_lista(u.get("ssh_authorized_keys") or u.get("ssh-authorized-keys")):
                c = analizar_clave_publica(str(k))
                if c is not None:
                    claves.append(c)
    return claves


def _con_prefijo(resultados, prefijo):
    """Los resultados de una comprobación, referidos a lo que hay en la máquina."""
    for r in resultados:
        texto = r.texto
        if len(texto) > 1 and texto[0].isupper() and texto[1].islower():
            texto = texto[0].lower() + texto[1:]
        r.texto = prefijo + texto
    return resultados


def _json(texto):
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return None


def comprobar_disco(archivos, instancias, clave, user_data_actual, iid_actual, red):
    """Lo que dejó cloud-init en la máquina."""
    rs = []
    sec = "acceso"

    # ¿Se ejecutó cloud-init, y con qué?
    if not instancias:
        rs.append(error("cloud-init no llegó a configurar la máquina", fallo="C1",
                        detalle=["No hay ninguna instancia en %s." % DIR_INSTANCIAS],
                        efecto="la máquina no tiene ni el usuario ni la IP del manual.",
                        arreglo="compruebe que pasó los tres archivos a virt-install.",
                        seccion=sec))
    elif len(instancias) > 1:
        rs.append(aviso("El disco se ha configurado con %d instance-id distintos" % len(instancias),
                        fallo="D2", detalle=["Instancias: %s." % ", ".join(instancias)],
                        efecto="el disco se reutilizó con otro meta-data.",
                        arreglo="para una máquina nueva, use siempre un disco nuevo.",
                        seccion=sec))
    else:
        rs.append(ok("cloud-init configuró la máquina con el instance-id %s" % instancias[0]))

    estado = _json(archivos.get("/var/lib/cloud/data/status.json"))
    v1 = (estado or {}).get("v1") or {}
    fuente = v1.get("datasource")
    if estado is not None and not fuente:
        rs.append(error("cloud-init no encontró los archivos de configuración", fallo="C1",
                        efecto="la máquina arrancó sin user-data, meta-data ni network-config.",
                        arreglo="compruebe la opción --cloud-init de virt-install.",
                        seccion=sec))

    resultado = _json(archivos.get("/var/lib/cloud/data/result.json"))
    if resultado is not None:
        errores = (resultado.get("v1") or {}).get("errors") or []
        recuperables = (resultado.get("v1") or {}).get("recoverable_errors") or {}
        if errores:
            rs.append(error("cloud-init terminó con errores", fallo="B4",
                            detalle=["cloud-init: %s" % str(e)[:200] for e in errores[:4]],
                            seccion=sec))
        avisos = [(nivel, m) for nivel, ms in recuperables.items() for m in ms]
        if avisos:
            rs.append(aviso("cloud-init dejó avisos", fallo="B4",
                            detalle=["%s: %s" % (n, str(m)[:200]) for n, m in avisos[:4]],
                            seccion=sec))
        if not errores and not avisos:
            rs.append(ok("cloud-init terminó sin errores ni avisos"))

    # El user-data que se aplicó, frente al de ahora
    aplicado = archivos.get("/var/lib/cloud/instance/user-data.txt")
    if aplicado is not None:
        if user_data_actual is not None and aplicado.strip() != user_data_actual.strip():
            mismo_iid = instancias and iid_actual and iid_actual in instancias
            rs.append(aviso(
                "El user-data que se aplicó a la máquina no es el que tiene ahora en el silo",
                fallo="D2" if mismo_iid else None,
                efecto="cloud-init solo se aplica en el primer arranque: corregir "
                       "user-data después no cambia la máquina." if mismo_iid else None,
                arreglo="elimine la máquina y su disco, y créela de nuevo desde el "
                        "primer paso de la 5.4.2." if mismo_iid else None,
                seccion=sec))
        problemas_ud = [r for r in comprobar_user_data(aplicado, clave)
                        if r.estado in (ERROR, AVISO)]
        rs += _con_prefijo(problemas_ud, "En el user-data que se aplicó, ")

    # La clave que quedó en la máquina
    claves_ruta = "/home/administrador/.ssh/authorized_keys"
    if claves_ruta in archivos:
        texto = archivos[claves_ruta]
        if texto is None:
            rs.append(error("En la máquina, administrador no tiene authorized_keys",
                            fallo="B5", efecto="«Permission denied (publickey)».",
                            arreglo="revise ssh_authorized_keys en user-data (o si se creó "
                                    "el usuario administrador).", seccion=sec))
        else:
            instaladas = [c for c in (analizar_clave_publica(l) for l in texto.splitlines()
                                      if l.strip() and not l.startswith("#")) if c]
            en_aplicado = clave is not None and aplicado is not None and any(
                c.blob == clave.blob for c in claves_de_user_data(aplicado))
            if clave is None:
                rs.append(omitida("Clave de la máquina: no hay ~/.ssh/id_rsa.pub con la que "
                                  "compararla"))
            elif any(c.blob == clave.blob for c in instaladas):
                rs.append(ok("La máquina tiene su clave de ~/.ssh/id_rsa.pub"))
            elif en_aplicado:
                # Visto en avantasia (6-nov): con el mismo instance-id, cloud-init
                # guarda el user-data nuevo pero no vuelve a instalar las claves
                rs.append(error(
                    "cloud-init no ha vuelto a aplicar user-data a este disco", fallo="D2",
                    detalle=["El user-data que tiene la máquina ya lleva su clave, pero "
                             "la que está instalada es otra:"]
                    + ["En la máquina: %s" % c.describir() for c in instaladas],
                    efecto="el disco ya se configuró una vez con este instance-id: corregir "
                           "user-data y crear la máquina con el mismo disco no cambia nada. "
                           "ssh seguirá respondiendo «Permission denied (publickey)».",
                    arreglo="elimine la máquina y su disco, y créela de nuevo desde el "
                            "primer paso de la 5.4.2, con un disco nuevo.",
                    seccion=sec))
            else:
                rs.append(error(
                    "La clave que tiene la máquina no es la de ~/.ssh/id_rsa.pub", fallo="B5",
                    detalle=["En la máquina: %s" % c.describir() for c in instaladas]
                    + ["id_rsa.pub:    %s" % clave.describir()],
                    efecto="«Permission denied (publickey)».",
                    arreglo="si regeneró la clave después de crear la máquina, vea la "
                            "FAQ B.3; si no, corrija user-data y cree la máquina de nuevo.",
                    seccion="faq-publickey"))

    # La red que quedó en la máquina
    netplan = archivos.get("/etc/netplan/50-cloud-init.yaml")
    if netplan is not None and yaml is not None:
        try:
            datos = yaml.safe_load(netplan) or {}
        except yaml.YAMLError:
            datos = {}
        red_maquina = datos.get("network") if isinstance(datos, dict) else None
        if isinstance(red_maquina, dict):
            r, _ = comprobar_network_config(yaml.safe_dump(red_maquina), red)
            rs += _con_prefijo([x for x in r if x.estado in (ERROR, AVISO)],
                               "En la red de la máquina, ")
            if not any(x.estado in (ERROR, AVISO) for x in r):
                rs.append(ok("La red de la máquina es la de network-config"))
    elif "/etc/netplan/50-cloud-init.yaml" in archivos and netplan is None:
        rs.append(error("La máquina no tiene la configuración de red de cloud-init",
                        fallo="B6", efecto="no tiene la IP fija de network-config.",
                        seccion=sec))
    return rs
