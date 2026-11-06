# --- Cuando no puede entrar: estado, conectividad, SSH y orden de virt-install --
#
# D1, D3, D4, D6 y C1. Nunca arranca ni apaga la máquina: si hace falta que esté
# apagada (para leer el disco), se le pide al alumno.

ESTADO_ENCENDIDA = 1
ESTADO_PAUSADA = 3
ESTADO_APAGADA = 5
NOMBRES_ESTADO = {0: "sin estado", 1: "encendida", 2: "bloqueada", 3: "en pausa",
                  4: "apagándose", 5: "apagada", 6: "caída", 7: "suspendida"}
FUENTE_ARP = 2   # VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP


def buscar_dominio(conn, nombre):
    for d in conn.listAllDomains(0):
        if d.name() == nombre:
            return d
    return None


class Maquina:
    """Lo que hace falta saber de la máquina, leído de su definición."""

    def __init__(self, dominio):
        self.dominio = dominio
        self.nombre = dominio.name()
        estado = dominio.state()
        self.estado = estado[0] if isinstance(estado, (list, tuple)) else estado
        raiz = _xml(dominio)
        self.on_reboot = raiz.findtext("on_reboot")
        self.redes = [i.find("source").get("network")
                      for i in raiz.findall("devices/interface")
                      if i.get("type") == "network" and i.find("source") is not None]
        self.discos = discos_de(dominio)
        self.iso_cloud_init = any(
            "cloudinit" in (d.find("source").get("file") or "")
            for d in raiz.findall("devices/disk")
            if d.get("device") == "cdrom" and d.find("source") is not None)
        memoria = raiz.find("memory")
        self.memoria_mib = None
        if memoria is not None and (memoria.text or "").isdigit():
            factor = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(memoria.get("unit", "KiB"))
            if factor:
                self.memoria_mib = int(int(memoria.text) * factor)
        vcpu = raiz.findtext("vcpu")
        self.vcpus = int(vcpu) if vcpu and vcpu.strip().isdigit() else None

    @property
    def encendida(self):
        return self.estado == ESTADO_ENCENDIDA

    @property
    def apagada(self):
        return self.estado == ESTADO_APAGADA


def comprobar_maquina(maquina, uvus):
    """D3 y lo esperado por el manual (5.4.2)."""
    rs = []
    nombre_estado = NOMBRES_ESTADO.get(maquina.estado, str(maquina.estado))
    if maquina.encendida:
        rs.append(ok("La máquina %s está encendida" % maquina.nombre))
    elif maquina.apagada:
        rs.append(ok("La máquina %s está apagada" % maquina.nombre))
    else:
        rs.append(aviso("La máquina %s está %s" % (maquina.nombre, nombre_estado),
                        arreglo="apáguela (virsh shutdown %s) y vuelva a arrancarla "
                                "(virsh start %s)." % (maquina.nombre, maquina.nombre),
                        seccion="acceso"))
    red = "%s-red" % uvus
    if red not in maquina.redes:
        rs.append(error("La máquina no está conectada a su red %s" % red,
                        detalle=["Está en: %s." % ", ".join(maquina.redes)]
                        if maquina.redes else ["No tiene ninguna red."],
                        efecto="la IP de network-config no le sirve en esa red.",
                        arreglo="vuelva a crearla con --network network=%s." % red,
                        seccion="instanciar"))
    else:
        rs.append(ok("Está conectada a su red %s" % red))
    if maquina.encendida and maquina.on_reboot == "destroy":
        rs.append(aviso(
            "Todavía tiene la configuración del primer arranque", fallo="D3",
            efecto="si la reinicia desde dentro, se apagará en vez de reiniciarse.",
            arreglo="cuando haya entrado e instalado qemu-guest-agent, apáguela con "
                    "virsh shutdown %s y arránquela con virsh start %s."
                    % (maquina.nombre, maquina.nombre),
            seccion="acceso"))
    if maquina.memoria_mib is not None and maquina.memoria_mib != 2048:
        rs.append(aviso("La máquina tiene %d MiB de RAM; el manual pide 2048"
                        % maquina.memoria_mib, seccion="instanciar"))
    if maquina.vcpus is not None and maquina.vcpus != 2:
        rs.append(aviso("La máquina tiene %d vCPU; el manual pide 2" % maquina.vcpus,
                        seccion="instanciar"))
    return rs


def ip_por_arp(dominio):
    """IPv4 que ve el servidor en sus tablas ARP para la máquina, o None."""
    try:
        datos = dominio.interfaceAddresses(FUENTE_ARP, 0)
    except Exception:
        return None
    for interfaz in (datos or {}).values():
        for direccion in interfaz.get("addrs") or []:
            if direccion.get("type") == 0:   # VIR_IP_ADDR_TYPE_IPV4
                try:
                    return ipaddress.ip_address(direccion.get("addr"))
                except ValueError:
                    continue
    return None


def probar_puerto(ip, puerto=22, espera=5):
    """'abierto', 'rechazado', 'sin ruta' o 'sin respuesta'."""
    try:
        s = socket.create_connection((str(ip), puerto), timeout=espera)
        s.close()
        return "abierto"
    except ConnectionRefusedError:
        return "rechazado"
    except socket.timeout:
        return "sin respuesta"
    except OSError as e:
        return "sin ruta" if e.errno in (113, 101) else "sin respuesta"   # EHOSTUNREACH, ENETUNREACH


def comprobar_conectividad(ip):
    """D1 y B6. Devuelve (resultados, el puerto 22 está abierto)."""
    rs = []
    if responde_ping(ip):
        rs.append(ok("La máquina responde en %s" % ip))
    else:
        rs.append(aviso("La máquina no responde al ping en %s" % ip,
                        efecto="o todavía está arrancando, o no tiene esa IP."))
    puerto = probar_puerto(ip)
    if puerto == "abierto":
        rs.append(ok("El puerto 22 (ssh) está abierto"))
        return rs, True
    espere = "Si acaba de crearla o de arrancarla, espere medio minuto y repita."
    if puerto == "rechazado":
        rs.append(error("La máquina rechaza la conexión al puerto 22", fallo="D1",
                        detalle=["ssh dice «Connection refused».",
                                 "Quien rechaza es la máquina virtual, no el servidor de la "
                                 "asignatura.", espere],
                        efecto="la máquina tiene la IP, pero ssh todavía no escucha "
                               "(o la máquina se ha quedado en modo de emergencia).",
                        seccion="acceso"))
    elif puerto == "sin ruta":
        rs.append(error("No hay ruta hasta %s" % ip, fallo="D1",
                        detalle=["ssh dice «No route to host».", espere],
                        efecto="nada responde en esa IP: la máquina aún arranca, o "
                               "network-config no le ha dado esa IP (B6).",
                        seccion="acceso"))
    else:
        rs.append(error("La máquina no contesta en el puerto 22 de %s" % ip, fallo="D1",
                        detalle=["ssh dice «Connection timed out» (o, si se espera más, "
                                 "«No route to host»).", espere],
                        efecto="nada responde en esa IP: la máquina aún arranca, o "
                               "network-config no le ha dado esa IP (B6).",
                        seccion="acceso"))
    return rs, False


def _ssh(ip, home, known_hosts, estricto):
    # Solo con clave, nunca con contraseña: un ssh que no puede preguntar acaba
    # enviando contraseñas vacías, y cada una cuenta como «Failed password»
    # (catálogo, A4 y E4)
    opciones = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                "-o", "ConnectionAttempts=1", "-o", "NumberOfPasswordPrompts=0",
                "-o", "PreferredAuthentications=publickey",
                "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
                "-o", "UpdateHostKeys=no", "-o", "IdentitiesOnly=yes",
                "-i", os.path.join(home, ".ssh", "id_rsa"),
                "-o", "UserKnownHostsFile=%s" % known_hosts,
                "-o", "StrictHostKeyChecking=%s" % ("yes" if estricto else "no")]
    if not estricto:
        opciones += ["-o", "GlobalKnownHostsFile=/dev/null"]
    return ejecutar(["ssh", "-n"] + opciones + ["%s@%s" % (USUARIO_VM, ip), "true"],
                    timeout=30)


def comprobar_ssh(ip, home, cifrada, en_agente):
    """D4 y D6: primero known_hosts, después el acceso. No escribe en known_hosts.

    Devuelve (resultados, ha podido entrar).
    """
    rs = []
    known_hosts = os.path.join(home, ".ssh", "known_hosts")
    codigo, _, _ = ejecutar(["ssh-keygen", "-F", str(ip), "-f", known_hosts])
    conocida = codigo == 0
    codigo, _, err = _ssh(ip, home, known_hosts if conocida else "/dev/null", conocida)
    if codigo == 0:
        rs.append(ok("Puede entrar: ssh %s@%s funciona" % (USUARIO_VM, ip)))
        return rs, True
    if codigo is None:
        rs.append(aviso("ssh no ha terminado a tiempo", seccion="acceso"))
        return rs, False
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in err:
        rs.append(error(
            "known_hosts tiene otra clave para %s" % ip, fallo="D4",
            efecto="ssh se niega a conectar («REMOTE HOST IDENTIFICATION HAS CHANGED»). "
                   "Pasa al volver a crear una máquina con la misma IP.",
            arreglo='ssh-keygen -f "%s" -R "%s"' % (known_hosts, ip),
            seccion="faq-warning"))
        # Con la clave del host aparte, se mira si además entraría
        codigo, _, err = _ssh(ip, home, "/dev/null", False)
        if codigo == 0:
            rs.append(ok("Quitando esa línea de known_hosts, podrá entrar"))
            return rs, False
    if "UNPROTECTED PRIVATE KEY FILE" in err:
        rs.append(error("ssh ignora ~/.ssh/id_rsa por sus permisos", fallo="B10",
                        arreglo="chmod 600 ~/.ssh/id_rsa", seccion="preliminar"))
    elif "Permission denied" in err:
        if cifrada and not en_agente:
            rs.append(omitida(
                "Acceso por ssh: no concluyente. Su clave tiene frase de paso y no está "
                "en el agente, así que esta prueba no puede usarla (D6). Cárguela con "
                "ssh-add y repita, o pruebe ssh %s@%s a mano" % (USUARIO_VM, ip)))
        else:
            rs.append(error(
                "La máquina rechaza su clave: «Permission denied (publickey)»", fallo="B5",
                efecto="lo que falla está en lo que cloud-init instaló en la máquina "
                       "(usuario o clave).",
                arreglo="apague la máquina (virsh shutdown) y vuelva a ejecutar "
                        "ci-diagnosis: con la máquina apagada se revisa su disco.",
                seccion="faq-publickey"))
    else:
        ultima = [l for l in err.strip().splitlines() if l.strip()][-1:] or ["(sin mensaje)"]
        rs.append(error("ssh no ha podido entrar", detalle=["ssh dice: %s" % ultima[0]],
                        seccion="acceso"))
    return rs, False


# --- C1: la orden de virt-install, en su registro --------------------------------

REGISTRO_VIRT_INSTALL = os.path.join(".cache", "virt-manager", "virt-install.log")
LANZADA_RE = re.compile(r"^\[([^\]]*?) virt-install \d+\].*Launched with command line: (.*)$")
# Mismo formato que la línea de la orden (grabada): «[fecha virt-install PID] NIVEL (módulo:línea) mensaje»
ERROR_RE = re.compile(r"^\[[^\]]*\] ERROR \([^)]*\) (.*)$")


class Intento:
    """Una ejecución de virt-install en su registro."""

    def __init__(self, fecha, palabras):
        self.fecha, self.palabras = fecha, palabras
        self.errores, self.completado = [], False


def ultimo_intento(home, nombre):
    """La última ejecución de virt-install para esa máquina, o None."""
    base = os.path.join(home, REGISTRO_VIRT_INSTALL)
    for ruta in [base] + ["%s.%d" % (base, i) for i in range(1, 6)]:
        datos = leer_bytes(ruta)
        if datos is None:
            continue
        encontrado, actual = None, None
        for linea in datos.decode("utf-8", "replace").splitlines():
            m = LANZADA_RE.search(linea)
            if m:
                palabras = m.group(2).split()
                actual = Intento(m.group(1), palabras) if nombre in _nombre_en(palabras) else None
                if actual is not None:
                    encontrado = actual
                continue
            if actual is None:
                continue
            e = ERROR_RE.search(linea)
            if e:
                actual.errores.append(e.group(1).strip())
            elif "Domain creation completed" in linea:
                actual.completado = True
        if encontrado:
            return encontrado
    return None


def ultima_orden(home, nombre):
    """La última orden de virt-install para esa máquina (lista de palabras)."""
    intento = ultimo_intento(home, nombre)
    return intento.palabras if intento else None


def _nombre_en(palabras):
    nombres = []
    for i, p in enumerate(palabras):
        if p.startswith("--name="):
            nombres.append(p.split("=", 1)[1])
        elif p in ("--name", "-n") and i + 1 < len(palabras):
            nombres.append(palabras[i + 1])
    return nombres


def _valor(palabras, opcion):
    for i, p in enumerate(palabras):
        if p.startswith(opcion + "="):
            return p.split("=", 1)[1]
        if p == opcion and i + 1 < len(palabras):
            return palabras[i + 1]
    return None


def comprobar_orden(home, uvus, nombre, intento=None):
    intento = intento or ultimo_intento(home, nombre)
    if intento is None:
        return [omitida("Orden de virt-install: no está en su registro "
                        "(~/.cache/virt-manager/virt-install.log)")]
    palabras = intento.palabras
    rs = []
    sec = "instanciar"
    if intento.errores:
        rs.append(error("virt-install terminó con un error (%s)" % intento.fecha,
                        detalle=["virt-install: %s" % e[:300] for e in intento.errores[:3]],
                        seccion=sec))
    un_guion = [p for p in palabras[1:] if re.match(r"^-[a-z]{2,}", p)]
    if un_guion:
        rs.append(error("La orden tiene opciones con un solo guion: %s" % " ".join(un_guion),
                        fallo="C1", efecto="virt-install las entiende como otra cosa "
                        "(-noautoconsole es --name oautoconsole).",
                        arreglo="todas las opciones empiezan por dos guiones.", seccion=sec))
    ci = _valor(palabras, "--cloud-init")
    sueltas = [p for p in palabras if re.match(r"^(user-data|meta-data|network-config)=", p)
               and p != ci]
    if ci is None:
        rs.append(error("La orden no lleva --cloud-init", fallo="C1",
                        efecto="cloud-init no recibió ninguno de los tres archivos.",
                        seccion=sec))
    else:
        faltan = [a for a in ARCHIVOS_CI if a + "=" not in ci]
        if sueltas:
            rs.append(error("Hay un espacio tras una coma en --cloud-init", fallo="C1",
                            detalle=["Sueltos: %s" % " ".join(sueltas)],
                            efecto="virt-install no los toma como parte de --cloud-init.",
                            arreglo="los tres, separados por comas y sin espacios.",
                            seccion=sec))
        elif faltan:
            rs.append(error("--cloud-init no lleva %s" % ", ".join(faltan), fallo="C1",
                            efecto="cloud-init no recibió ese archivo.", seccion=sec))
    if "--import" not in palabras:
        rs.append(aviso("La orden no lleva --import", fallo="C1", seccion=sec))
    if _valor(palabras, "--os-variant") is None and _valor(palabras, "--osinfo") is None:
        rs.append(aviso("La orden no lleva --os-variant", fallo="C1", seccion=sec))
    red = _valor(palabras, "--network")
    if red is not None and "network=%s-red" % uvus not in red:
        rs.append(aviso("La orden conecta la máquina a otra red: %s" % red, fallo="C1",
                        seccion=sec))
    if not rs:
        rs.append(ok("La orden de virt-install es como la del manual"))
    return rs


def comprobar_intento_anterior(home, uvus, nombre):
    """--antes: si ya hubo un virt-install para esta máquina (que no existe), qué
    pasó. Lista vacía si no lo hubo."""
    intento = ultimo_intento(home, nombre)
    if intento is None:
        return []
    if intento.completado and not intento.errores:
        return [ok("Ya la creó el %s y después la eliminó" % intento.fecha)]
    rs = comprobar_orden(home, uvus, nombre, intento)
    if not intento.errores and not [r for r in rs if r.estado in (ERROR, AVISO)]:
        rs.append(aviso("El último virt-install de %s (%s) no llegó a crear la máquina"
                        % (nombre, intento.fecha),
                        efecto="su registro no dice por qué; revise lo que mostró en "
                               "pantalla.", seccion="instanciar"))
    return rs
