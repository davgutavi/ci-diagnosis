# --- Archivos de cloud-init (B1, B4, B5, B6) ----------------------------------
#
# Criterio de gravedad: ERROR cuando el efecto se conoce (YAML inválido, sin
# #cloud-config, sin el usuario, clave que no es la del servidor...); AVISO
# cuando solo se aparta del manual y el efecto no está comprobado.

FALLO_DE = {"user-data": "B4", "meta-data": None, "network-config": "B6"}
SECCION_DE = {"user-data": "preliminar", "meta-data": "instanciar",
              "network-config": "instanciar"}


class Red:
    """Lo que hace falta saber de la red del alumno para revisar su IP."""

    def __init__(self, nombre, red, pasarela, dhcp=()):
        self.nombre = nombre
        self.red = ipaddress.ip_network(red)
        self.pasarela = ipaddress.ip_address(pasarela)
        self.dhcp = [(ipaddress.ip_address(a), ipaddress.ip_address(b)) for a, b in dhcp]

    def en_dhcp(self, ip):
        return any(a <= ip <= b for a, b in self.dhcp)


def escapar_nombre(nombre):
    """Nombre de archivo (bytes) como lo muestra «ls -b»."""
    trozos = []
    for b in nombre:
        c = chr(b)
        if c == " ":
            trozos.append("\\ ")
        elif c == "\\":
            trozos.append("\\\\")
        elif 0x21 <= b <= 0x7e:
            trozos.append(c)
        else:
            trozos.append("\\%03o" % b)
    return "".join(trozos)


def _invisible(c):
    cat = unicodedata.category(c)
    return cat == "Cf" or (cat == "Zs" and c != " ") or c in "  "


def _base_de_nombre(nombre):
    """Nombre reducido para reconocer variantes: sin invisibles, en minúsculas,
    sin extensiones ni marcas de copias de editores."""
    n = "".join(c for c in nombre.decode("utf-8", "replace") if not _invisible(c))
    n = n.strip().lower()
    n = re.sub(r"\.sw[a-p]$", "", n)
    n = re.sub(r"^\.", "", n)
    n = re.sub(r"(~|\.(ya?ml|txt|bak|orig|save|old))+$", "", n)
    return n.replace("_", "-")


def comprobar_nombres(directorio):
    """Que existan user-data, meta-data y network-config con esos nombres exactos.

    Devuelve {nombre: (resultados, bytes o None)}.
    """
    salida = {}
    try:
        entradas = os.listdir(os.fsencode(directorio))
    except OSError:
        entradas = []
    for nombre in ARCHIVOS_CI:
        rs = []
        salida[nombre] = (rs, None)
        exacto = nombre.encode()
        variantes = sorted(e for e in entradas
                           if e != exacto and _base_de_nombre(e) == nombre)
        ruta = os.path.join(directorio, nombre)
        detalle = ["Hay un archivo parecido: %s" % escapar_nombre(v) for v in variantes]
        if exacto not in entradas:
            arreglo = "créelo con ese nombre exacto."
            if len(variantes) == 1:
                arreglo = "renómbrelo: mv %s %s" % (escapar_nombre(variantes[0]), nombre)
            rs.append(error("No existe el archivo %s" % nombre, fallo=FALLO_DE[nombre],
                            detalle=detalle,
                            efecto="virt-install no podrá usarlo.",
                            arreglo=arreglo, seccion=SECCION_DE[nombre]))
            continue
        if not os.path.isfile(ruta):
            rs.append(error("%s no es un archivo normal" % nombre, fallo=FALLO_DE[nombre],
                            seccion=SECCION_DE[nombre]))
            continue
        datos = leer_bytes(ruta)
        if datos is None:
            rs.append(error("No se puede leer %s" % nombre, fallo=FALLO_DE[nombre],
                            arreglo="chmod 644 %s" % nombre, seccion=SECCION_DE[nombre]))
        elif variantes:
            rs.append(aviso(
                "Además de %s hay otros archivos con un nombre parecido" % nombre,
                detalle=detalle,
                efecto="virt-install solo usa %s." % nombre,
                arreglo="compruebe que el que editó es %s." % nombre,
                seccion=SECCION_DE[nombre]))
        else:
            rs.append(ok("Existe %s" % nombre))
        salida[nombre] = (rs, datos)
    return salida


def _lineas_de(apariciones, maximo=6):
    lineas = sorted(set(n for n, _ in apariciones))
    texto = ", ".join(str(n) for n in lineas[:maximo])
    if len(lineas) > maximo:
        texto += " y %d más" % (len(lineas) - maximo)
    return ("línea " if len(lineas) == 1 else "líneas ") + texto


def _codigos(apariciones):
    return ", ".join(sorted(set("U+%04X" % ord(c) for _, c in apariciones)))


RAYAS = "‐‑‒–—―−"
COMILLAS = "‘’‚‛“”„"


def comprobar_texto(nombre, datos):
    """Caracteres que no deberían estar: invisibles, rayas, comillas curvas,
    tabuladores, BOM, CRLF. Nunca se muestra el contenido de las líneas.

    Devuelve (resultados, texto o None si no es UTF-8).
    """
    rs = []
    fallo, seccion = FALLO_DE[nombre], SECCION_DE[nombre]
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError as e:
        linea = datos[:e.start].count(b"\n") + 1
        rs.append(error("%s no es texto UTF-8 (línea %d)" % (nombre, linea), fallo="B1",
                        arreglo="vuelva a escribir esa línea a mano con nano.",
                        seccion=seccion))
        return rs, None

    if texto.startswith("﻿"):
        r = error if nombre == "user-data" else aviso
        rs.append(r("%s empieza por un carácter invisible (BOM)" % nombre, fallo="B1",
                    efecto="la primera línea ya no es exactamente la que espera cloud-init."
                    if nombre == "user-data" else None,
                    arreglo="vuelva a escribir la primera línea a mano con nano.",
                    seccion=seccion))
        texto = texto[1:]

    invisibles, rayas, comillas, tabs = [], [], [], []
    for n, linea in enumerate(texto.split("\n"), 1):
        for c in linea:
            if c == "\t":
                tabs.append((n, c))
            elif c in RAYAS:
                rayas.append((n, c))
            elif c in COMILLAS:
                comillas.append((n, c))
            elif _invisible(c):
                invisibles.append((n, c))

    copiar = ("suele pasar al copiar del PDF o de la web. Escriba esa parte a mano "
              "con nano.")
    if invisibles:
        rs.append(error("%s tiene caracteres invisibles (%s)" % (nombre, _lineas_de(invisibles)),
                        fallo="B1",
                        detalle=["Caracteres: %s." % _codigos(invisibles)],
                        arreglo=copiar, seccion=seccion))
    if rayas:
        rs.append(error("%s tiene rayas en lugar de guiones (%s)" % (nombre, _lineas_de(rayas)),
                        fallo="B1",
                        detalle=["Caracteres: %s; el guion es «-»." % _codigos(rayas)],
                        arreglo=copiar, seccion=seccion))
    if comillas:
        rs.append(error("%s tiene comillas curvas (%s)" % (nombre, _lineas_de(comillas)),
                        fallo="B1",
                        detalle=["Caracteres: %s; la comilla es «'»." % _codigos(comillas)],
                        arreglo=copiar, seccion=seccion))
    if tabs:
        rs.append(error("%s tiene tabuladores (%s)" % (nombre, _lineas_de(tabs)), fallo=fallo,
                        efecto="YAML no admite tabuladores para indentar.",
                        arreglo="sustitúyalos por espacios, respetando la indentación del manual.",
                        seccion=seccion))
    if "\r" in texto:
        rs.append(aviso("%s tiene finales de línea de Windows (CRLF)" % nombre, fallo="B1",
                        arreglo="escríbalo con nano en el servidor, o conviértalo: "
                                "sed -i 's/\\r$//' %s" % nombre,
                        seccion=seccion))
    if not rs:
        rs.append(ok("%s: sin caracteres extraños ni tabuladores" % nombre))
    return rs, texto.replace("\r\n", "\n")


def cargar_yaml(nombre, texto, mostrar_problema=True):
    """(datos, None) si el YAML es válido; (None, Resultado) si no."""
    if yaml is None:
        return None, aviso("No se ha podido comprobar la sintaxis de %s: falta "
                           "PyYAML en el servidor" % nombre,
                           arreglo="avise al profesor.")
    try:
        return yaml.safe_load(texto), None
    except yaml.YAMLError as e:
        # Nunca str(e): incluye el texto de la línea, que podría ser una clave
        detalle = []
        marca = getattr(e, "problem_mark", None)
        if marca is not None:
            detalle.append("Línea %d, columna %d." % (marca.line + 1, marca.column + 1))
        problema = getattr(e, "problem", None)
        if problema and mostrar_problema:
            detalle.append("PyYAML dice: %s" % problema)
        return None, error("%s no es YAML válido" % nombre, fallo=FALLO_DE[nombre],
                           detalle=detalle,
                           efecto="cloud-init no podrá usarlo.",
                           arreglo="revise la indentación (solo espacios) y los "
                                   "dos puntos alrededor de esa línea, comparándolo "
                                   "con el manual.",
                           seccion=SECCION_DE[nombre])


def _como_lista(valor):
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    return [valor]


def comprobar_user_data(texto, clave_servidor):
    """Estructura de user-data y su clave (B4, B5)."""
    rs = []
    sec = "preliminar"
    privada = bool(PRIVADA_RE.search(texto))
    if privada:
        rs.append(error(
            "user-data contiene una clave privada", fallo="B5",
            efecto="la clave privada no sirve para entrar y queda copiada en la máquina.",
            arreglo="quítela y ponga en su lugar el contenido de ~/.ssh/id_rsa.pub "
                    "(la pública, que empieza por ssh-rsa).",
            seccion=sec))

    lineas = texto.split("\n")
    if lineas[0].rstrip() == "#cloud-config":
        rs.append(ok("La primera línea de user-data es #cloud-config"))
    else:
        detalle = []
        for n, l in enumerate(lineas[1:], 2):
            if l.strip() == "#cloud-config":
                detalle.append("Está en la línea %d: tiene que ser la primera." % n)
                break
        if not detalle and re.match(r"\s*#\s*cloud-config\s*$", lineas[0], re.I):
            detalle.append("Se escribe exactamente así: #cloud-config, sin espacios "
                           "y en minúsculas.")
        rs.append(error("La primera línea de user-data no es #cloud-config", fallo="B4",
                        detalle=detalle,
                        efecto="cloud-init ignora el archivo: la máquina se crea sin "
                               "el usuario administrador.",
                        arreglo="escriba #cloud-config en la primera línea.",
                        seccion=sec))

    datos, problema = cargar_yaml("user-data", texto, mostrar_problema=not privada)
    if problema:
        rs.append(problema)
        return rs
    if not isinstance(datos, dict):
        rs.append(error("user-data no tiene la estructura esperada", fallo="B4",
                        arreglo="compárelo línea a línea con el del manual.",
                        seccion=sec))
        return rs

    for clave in ("ssh_authorized_keys", "ssh-authorized-keys"):
        if clave in datos:
            rs.append(error(
                "%s está fuera del usuario administrador" % clave, fallo="B4",
                efecto="esa clave no se instala en administrador: "
                       "«Permission denied (publickey)».",
                arreglo="indéntelo dentro del usuario, al nivel de «shell:», como "
                        "en el manual.",
                seccion=sec))

    usuarios = datos.get("users")
    if usuarios is None:
        detalle = []
        parecidas = [k for k in datos if str(k).lower() in ("user", "usuarios", "usuario")]
        if parecidas:
            detalle.append("Hay «%s:»; tiene que ser «users:»." % parecidas[0])
        rs.append(error("user-data no tiene la lista users", fallo="B4", detalle=detalle,
                        efecto="no se crea el usuario administrador.",
                        seccion=sec))
        return rs
    if not isinstance(usuarios, list):
        rs.append(error("users no es una lista", fallo="B4",
                        detalle=["Falta el guion antes de «name: administrador»."]
                        if isinstance(usuarios, dict) else [],
                        efecto="no se crea el usuario administrador.",
                        arreglo="escriba «  - name: administrador», con el guion.",
                        seccion=sec))
        return rs

    nombres = [u.get("name") for u in usuarios if isinstance(u, dict)]
    admin = None
    for u in usuarios:
        if isinstance(u, dict) and u.get("name") == USUARIO_VM:
            admin = u
    if admin is None:
        rs.append(error("user-data no crea el usuario administrador", fallo="B4",
                        detalle=["Usuarios que crea: %s." % ", ".join(
                            str(n) for n in nombres if n is not None)]
                        if any(n is not None for n in nombres) else [],
                        efecto="ssh administrador@... no podrá entrar.",
                        arreglo="«- name: administrador», en minúsculas.",
                        seccion=sec))
        return rs
    rs.append(ok("user-data crea el usuario administrador"))

    sudo = [str(s) for s in _como_lista(admin.get("sudo"))]
    if SUDO_ESPERADO in sudo:
        rs.append(ok("administrador tiene sudo sin contraseña"))
    elif not sudo:
        rs.append(error("administrador no tiene la línea sudo", fallo="B4",
                        efecto="no podrá usar sudo dentro de la máquina (por ejemplo, "
                               "para instalar qemu-guest-agent).",
                        arreglo="añada «    sudo: ['%s']»." % SUDO_ESPERADO,
                        seccion=sec))
    else:
        rs.append(error("La regla de sudo no es la del manual", fallo="B4",
                        detalle=["Tiene: %s" % "; ".join(sudo),
                                 "Tiene que ser: %s" % SUDO_ESPERADO],
                        efecto="sudo no funcionará como espera el manual.",
                        seccion=sec))

    grupos = admin.get("groups")
    lista_grupos = (re.split(r"[,\s]+", grupos.strip()) if isinstance(grupos, str)
                    else [str(g) for g in _como_lista(grupos)])
    if "sudo" not in lista_grupos:
        rs.append(aviso("administrador no está en el grupo sudo",
                        arreglo="añada «    groups: sudo».", seccion=sec))
    if admin.get("shell") != "/bin/bash":
        rs.append(aviso("El intérprete de administrador no es /bin/bash",
                        detalle=["Tiene: %s" % admin.get("shell")] if admin.get("shell")
                        else [],
                        arreglo="añada «    shell: /bin/bash».", seccion=sec))

    rs += comprobar_claves_user_data(admin, clave_servidor)
    return rs


def _clave_partida(texto):
    """Si la clave se pegó partida en varias líneas, YAML la une con espacios:
    se prueba a quitarlos dentro de la parte en base64."""
    partes = texto.split()
    if len(partes) < 3:
        return None
    for fin in range(len(partes), 2, -1):
        if all(re.match(r"^[A-Za-z0-9+/=]+$", p) for p in partes[1:fin]):
            candidata = analizar_clave_publica(
                partes[0] + " " + "".join(partes[1:fin]) + " " + " ".join(partes[fin:]))
            if candidata is not None:
                return candidata
    return None


def comprobar_claves_user_data(admin, clave_servidor):
    rs = []
    sec = "preliminar"
    if "ssh_authorized_keys" in admin:
        valor = admin["ssh_authorized_keys"]
    elif "ssh-authorized-keys" in admin:
        valor = admin["ssh-authorized-keys"]
        rs.append(aviso("user-data usa ssh-authorized-keys (con guiones)", fallo="B4",
                        efecto="es la forma antigua: cloud-init de Ubuntu 24.04 la "
                               "trata como obsoleta.",
                        arreglo="escríbalo con guiones bajos: ssh_authorized_keys.",
                        seccion=sec))
    else:
        rs.append(error("administrador no tiene ssh_authorized_keys", fallo="B5",
                        efecto="no podrá entrar: «Permission denied (publickey)».",
                        seccion=sec))
        return rs
    if isinstance(valor, str):
        rs.append(aviso("ssh_authorized_keys no es una lista",
                        arreglo="ponga la clave en la línea siguiente, tras «- ».",
                        seccion=sec))
    claves = []
    for i, texto in enumerate(_como_lista(valor), 1):
        texto = str(texto)
        if "CLAVE" in texto.upper() and "SSH-" not in texto.upper():
            rs.append(error("En user-data sigue el texto de ejemplo, no su clave",
                            fallo="B5",
                            arreglo="sustitúyalo por el contenido de ~/.ssh/id_rsa.pub.",
                            seccion=sec))
            continue
        clave = analizar_clave_publica(texto)
        if clave is None:
            partida = _clave_partida(texto)
            if partida is not None:
                rs.append(error("La clave de user-data está partida en varias líneas",
                                fallo="B5",
                                efecto="cloud-init instala una clave que no sirve: "
                                       "«Permission denied (publickey)».",
                                arreglo="póngala entera en una sola línea, tras «- ».",
                                seccion=sec))
                claves.append(partida)
            else:
                rs.append(error("La clave %d de user-data no es una clave pública válida" % i,
                                fallo="B5",
                                detalle=["Puede estar incompleta o partida al pegarla."],
                                arreglo="copie de nuevo el contenido de ~/.ssh/id_rsa.pub, "
                                        "en una sola línea.",
                                seccion=sec))
            continue
        claves.append(clave)
    if not claves:
        return rs
    if clave_servidor is None:
        rs.append(omitida("Clave de user-data: no se puede comparar con ~/.ssh/id_rsa.pub"))
    elif any(c.blob == clave_servidor.blob for c in claves):
        rs.append(ok("La clave de user-data es la de ~/.ssh/id_rsa.pub"))
    else:
        rs.append(error(
            "La clave de user-data no es la de ~/.ssh/id_rsa.pub", fallo="B5",
            detalle=["user-data:  %s" % c.describir() for c in claves]
            + ["id_rsa.pub: %s" % clave_servidor.describir()],
            efecto="ssh responderá «Permission denied (publickey)».",
            arreglo="copie en user-data el contenido de ~/.ssh/id_rsa.pub, la del "
                    "servidor (no la de su ordenador).",
            seccion=sec))
    return rs


def comprobar_meta_data(texto, uvus, maquina):
    """meta-data: instance-id y local-hostname. Devuelve (resultados, datos)."""
    rs = []
    sec = "instanciar"
    datos, problema = cargar_yaml("meta-data", texto)
    if problema:
        return [problema], None
    if not isinstance(datos, dict):
        return [error("meta-data no tiene la estructura esperada",
                      arreglo="dos líneas: instance-id: ... y local-hostname: ...",
                      seccion=sec)], None
    iid = datos.get("instance-id")
    host = datos.get("local-hostname")
    if maquina is None and host:
        maquina = str(host)
    esperado = "%s-%s" % (uvus, maquina) if maquina else None
    if iid is None:
        rs.append(aviso("meta-data no tiene instance-id",
                        arreglo="instance-id: %s" % (esperado or "<uvus>-serverX"),
                        seccion=sec))
    elif "su_usuario" in str(iid):
        rs.append(aviso("El instance-id de meta-data es el texto de ejemplo del manual",
                        detalle=["Tiene: %s" % iid],
                        arreglo="instance-id: %s" % (esperado or "<uvus>-serverX"),
                        seccion=sec))
    elif esperado and str(iid) != esperado:
        rs.append(aviso("El instance-id de meta-data no es %s" % esperado,
                        detalle=["Tiene: %s" % iid],
                        efecto="si es el de otra máquina suya, puede estar "
                               "diagnosticando los archivos de esa otra máquina.",
                        seccion=sec))
    elif esperado:
        rs.append(ok("meta-data: instance-id %s" % iid))
    if host is None:
        rs.append(aviso("meta-data no tiene local-hostname",
                        arreglo="local-hostname: %s" % (maquina or "serverX"), seccion=sec))
    elif maquina and str(host) != maquina:
        rs.append(aviso("El local-hostname de meta-data no es %s" % maquina,
                        detalle=["Tiene: %s" % host], seccion=sec))
    elif maquina:
        rs.append(ok("meta-data: local-hostname %s" % host))
    return rs, datos


def comprobar_network_config(texto, red=None):
    """network-config (B6). Devuelve (resultados, IP o None)."""
    rs = []
    sec = "instanciar"
    datos, problema = cargar_yaml("network-config", texto)
    if problema:
        return [problema], None
    if not isinstance(datos, dict):
        return [error("network-config no tiene la estructura esperada", fallo="B6",
                      arreglo="compárelo línea a línea con el del manual.",
                      seccion=sec)], None
    if datos.get("version") != 2:
        rs.append(error("network-config no tiene «version: 2»", fallo="B6",
                        detalle=["Tiene: version: %s" % datos.get("version")]
                        if "version" in datos else [],
                        efecto="cloud-init lo interpreta con otro formato.",
                        seccion=sec))
    ethernets = datos.get("ethernets")
    if not isinstance(ethernets, dict):
        rs.append(error("network-config no tiene el bloque ethernets", fallo="B6",
                        efecto="la máquina no tendrá su IP fija.", seccion=sec))
        return rs, None
    if INTERFAZ not in ethernets:
        rs.append(error("network-config no configura la interfaz %s" % INTERFAZ, fallo="B6",
                        detalle=["Configura: %s." % ", ".join(str(k) for k in ethernets)],
                        efecto="la máquina no tendrá su IP fija.",
                        arreglo="la interfaz de las máquinas del manual se llama %s." % INTERFAZ,
                        seccion=sec))
        return rs, None
    iface = ethernets[INTERFAZ]
    if not isinstance(iface, dict):
        rs.append(error("El bloque de %s está vacío o mal indentado" % INTERFAZ, fallo="B6",
                        seccion=sec))
        return rs, None

    direcciones = [str(d) for d in _como_lista(iface.get("addresses"))]
    if not direcciones:
        rs.append(error("network-config no tiene addresses", fallo="B6",
                        efecto="la máquina no tendrá su IP fija.", seccion=sec))
        return rs, None
    if len(direcciones) > 1:
        rs.append(aviso("network-config tiene varias direcciones; el manual usa una",
                        seccion=sec))
    if "/" not in direcciones[0]:
        rs.append(error("La dirección %s no lleva /24" % direcciones[0], fallo="B6",
                        efecto="la máquina no tendrá su IP fija.",
                        arreglo="escríbala así: %s/24" % direcciones[0], seccion=sec))
        return rs, None
    try:
        interfaz = ipaddress.ip_interface(direcciones[0])
    except ValueError:
        rs.append(error("%s no es una dirección IP válida" % direcciones[0], fallo="B6",
                        seccion=sec))
        return rs, None
    ip = interfaz.ip
    if interfaz.network.prefixlen != 24:
        rs.append(aviso("La dirección %s no es /24" % direcciones[0], seccion=sec))
    if iface.get("dhcp4") in (True, "true", "yes"):
        rs.append(aviso("network-config activa dhcp4 además de la IP fija", seccion=sec))

    via = None
    for ruta in _como_lista(iface.get("routes")):
        if isinstance(ruta, dict) and str(ruta.get("to")) in ("default", "0.0.0.0/0"):
            via = ruta.get("via")
    if via is None and iface.get("gateway4"):
        via = iface.get("gateway4")
        rs.append(aviso("network-config usa gateway4, que está obsoleto",
                        arreglo="use routes: - to: default / via: ..., como el manual.",
                        seccion=sec))
    pasarela = None
    if via is None:
        rs.append(error("network-config no tiene la ruta por defecto", fallo="B6",
                        efecto="la máquina no saldrá de su red (apt update fallará).",
                        seccion=sec))
    else:
        try:
            pasarela = ipaddress.ip_address(str(via))
        except ValueError:
            rs.append(error("La pasarela %s no es una dirección IP" % via, fallo="B6",
                            seccion=sec))

    dns = [str(d) for d in _como_lista((iface.get("nameservers") or {}).get("addresses"))
           ] if isinstance(iface.get("nameservers"), dict) else []
    if not dns:
        rs.append(aviso("network-config no tiene servidores DNS",
                        efecto="la máquina no podrá resolver nombres (apt update fallará).",
                        arreglo="añada el bloque nameservers del manual.", seccion=sec))
    elif set(dns) != set(DNS_ESPERADOS):
        rs.append(aviso("Los DNS de network-config no son los del manual",
                        detalle=["Tiene: %s" % ", ".join(dns),
                                 "El manual: %s" % ", ".join(DNS_ESPERADOS)],
                        seccion=sec))

    if red is None:
        rs.append(omitida("IP %s y pasarela: sin comprobar contra su red" % ip))
        return rs, ip
    rango = "de %s a %s" % (red.dhcp[0][0], red.dhcp[0][1]) if red.dhcp else ""
    if ip not in red.red:
        rs.append(error("La IP %s no es de su red %s (%s)" % (ip, red.nombre, red.red),
                        fallo="B6", efecto="no podrá llegar a la máquina.",
                        arreglo="use una IP de %s, entre la .2 y la .127." % red.red,
                        seccion=sec))
    elif ip in (red.red.network_address, red.red.broadcast_address, red.pasarela):
        rs.append(error("La IP %s está reservada en su red" % ip, fallo="B6",
                        arreglo="use una entre la .2 y la .127.", seccion=sec))
    elif red.en_dhcp(ip):
        rs.append(aviso("La IP %s está dentro del rango del DHCP (%s)" % (ip, rango),
                        fallo="B6",
                        efecto="el DHCP puede dársela también a otra máquina.",
                        arreglo="use una entre la .2 y la .127.", seccion="red"))
    else:
        rs.append(ok("IP %s: de su red y fuera del DHCP" % ip))
    if pasarela is not None:
        if pasarela == red.pasarela:
            rs.append(ok("Pasarela %s: la de su red" % pasarela))
        else:
            rs.append(error("La pasarela %s no es la de su red (%s)" % (pasarela, red.pasarela),
                            fallo="B6",
                            efecto="la máquina no saldrá de su red.",
                            arreglo="via: %s" % red.pasarela, seccion=sec))
    return rs, ip
