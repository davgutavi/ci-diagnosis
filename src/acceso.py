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
                        efecto="la IP de network-config no le sirve en esa red: no podrá "
                               "llegar a la máquina.",
                        arreglo=pasos_rehacer(),
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
                        % maquina.memoria_mib,
                        efecto="con menos memoria puede ir lenta o no arrancar bien.",
                        arreglo=["No hace falta volver a crearla. Con la máquina apagada:",
                                 "$ virsh setmaxmem %s 2048M --config" % maquina.nombre,
                                 "$ virsh setmem %s 2048M --config" % maquina.nombre,
                                 "y arránquela: virsh start %s" % maquina.nombre],
                        seccion="instanciar"))
    if maquina.vcpus is not None and maquina.vcpus != 2:
        rs.append(aviso("La máquina tiene %d vCPU; el manual pide 2" % maquina.vcpus,
                        efecto="ninguno grave: solo se aparta del manual.",
                        arreglo=["No hace falta volver a crearla. Con la máquina apagada:",
                                 "$ virsh setvcpus %s 2 --config --maximum" % maquina.nombre,
                                 "$ virsh setvcpus %s 2 --config" % maquina.nombre,
                                 "y arránquela: virsh start %s" % maquina.nombre],
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
                        efecto="o todavía está arrancando, o no tiene esa IP.",
                        arreglo="si acaba de crearla o de arrancarla, espere un minuto y "
                                "repita. Si sigue igual, mire abajo el puerto 22 y el "
                                "bloque 5 (network-config)."))
    puerto = probar_puerto(ip)
    if puerto == "abierto":
        rs.append(ok("El puerto 22 (ssh) está abierto"))
        return rs, True
    espere = "Si acaba de crearla o de arrancarla, espere medio minuto y repita."
    if puerto == "rechazado":
        causa = "si cloud-init falló al arrancar."
        rs.append(error("La máquina rechaza la conexión al puerto 22", fallo="D1",
                        detalle=["ssh dice «Connection refused».",
                                 "Quien rechaza es la máquina virtual, no el servidor de la "
                                 "asignatura.", espere],
                        efecto="la máquina tiene la IP, pero ssh todavía no escucha "
                               "(o la máquina se ha quedado en modo de emergencia).",
                        arreglo=["Si acaba de crearla o de arrancarla, espere un minuto y repita.",
                                 "Si sigue igual, apáguela y vuelva a ejecutar "
                                 "./ci-diagnosis: con la máquina apagada se revisa su "
                                 "disco, y se ve %s" % causa,
                                 "$ virsh shutdown %s" % nombre_de_maquina()],
                        seccion="acceso"))
    elif puerto == "sin ruta":
        causa = "qué red le configuró cloud-init (B6)."
        rs.append(error("No hay ruta hasta %s" % ip, fallo="D1",
                        detalle=["ssh dice «No route to host».", espere],
                        efecto="nada responde en esa IP: la máquina aún arranca, o "
                               "network-config no le ha dado esa IP (B6).",
                        arreglo=["Si acaba de crearla o de arrancarla, espere un minuto y repita.",
                                 "Si sigue igual, apáguela y vuelva a ejecutar "
                                 "./ci-diagnosis: con la máquina apagada se revisa su "
                                 "disco, y se ve %s" % causa,
                                 "$ virsh shutdown %s" % nombre_de_maquina()],
                        seccion="acceso"))
    else:
        causa = "qué red le configuró cloud-init (B6)."
        rs.append(error("La máquina no contesta en el puerto 22 de %s" % ip, fallo="D1",
                        detalle=["ssh dice «Connection timed out» (o, si se espera más, "
                                 "«No route to host»).", espere],
                        efecto="nada responde en esa IP: la máquina aún arranca, o "
                               "network-config no le ha dado esa IP (B6).",
                        arreglo=["Si acaba de crearla o de arrancarla, espere un minuto y repita.",
                                 "Si sigue igual, apáguela y vuelva a ejecutar "
                                 "./ci-diagnosis: con la máquina apagada se revisa su "
                                 "disco, y se ve %s" % causa,
                                 "$ virsh shutdown %s" % nombre_de_maquina()],
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
    # hostname: para saber en qué máquina ha entrado (D5); solo lee
    return ejecutar(["ssh", "-n"] + opciones + ["%s@%s" % (USUARIO_VM, ip), "hostname"],
                    timeout=30)


def _otra_maquina(salida, esperado):
    """El hostname de la máquina en la que ha entrado ssh, si no es la esperada."""
    nombre = (salida or "").strip().splitlines()[-1:] or [""]
    nombre = nombre[0].strip()
    if esperado and nombre and nombre != esperado:
        return nombre
    return None


def _aviso_d5(ip, otra, esperado):
    return aviso("En %s ha contestado una máquina que se llama %s, no %s" % (ip, otra, esperado),
                 fallo="D5",
                 efecto="probablemente otra máquina suya tiene la misma IP; con las dos "
                        "encendidas, ssh entra unas veces en una y otras en la otra.",
                 arreglo=["Dos máquinas no pueden tener la misma IP. Lo más rápido: "
                          "apague la otra (virsh shutdown NOMBRE; virsh list --all le dice "
                          "cuáles tiene). Para usar las dos a la vez, una de ellas necesita "
                          "otra IP:"] + pasos_rehacer(
                              "Ponga en su network-config una IP que no use ninguna otra "
                              "máquina suya (YYY entre 2 y 127)."),
                 seccion="instanciar")


def comprobar_ssh(ip, home, cifrada, en_agente, esperado=None):
    """D4, D5 y D6: primero known_hosts, después el acceso. No escribe en known_hosts.

    esperado: el hostname de la máquina (serverX); si contesta otra, es D5.
    Devuelve (resultados, ha podido entrar).
    """
    rs = []
    known_hosts = os.path.join(home, ".ssh", "known_hosts")
    codigo, _, _ = ejecutar(["ssh-keygen", "-F", str(ip), "-f", known_hosts])
    conocida = codigo == 0
    codigo, salida, err = _ssh(ip, home, known_hosts if conocida else "/dev/null", conocida)
    if codigo == 0:
        otra = _otra_maquina(salida, esperado)
        if otra:
            rs.append(_aviso_d5(ip, otra, esperado))
            return rs, False
        rs.append(ok("Puede entrar: ssh %s@%s funciona" % (USUARIO_VM, ip),
                     detalle=["Si a usted no le deja, compruebe que lo ejecuta en el "
                              "servidor (no en su ordenador) y que escribe exactamente "
                              "ssh %s@%s: ni ubuntu ni su UVUS." % (USUARIO_VM, ip)]))
        return rs, True
    if codigo is None:
        rs.append(aviso("ssh no ha terminado a tiempo",
                        efecto="no se sabe si puede entrar.",
                        arreglo="repita dentro de un minuto, o pruébelo a mano: ssh %s@%s"
                                % (USUARIO_VM, ip), seccion="acceso"))
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
                "Acceso por ssh: no concluyente. Su clave tiene contraseña y no está "
                "en el agente, así que esta prueba no puede usarla (D6). Cárguela con "
                "ssh-add y repita, o pruebe ssh %s@%s a mano" % (USUARIO_VM, ip)))
        else:
            rs.append(error(
                "La máquina rechaza su clave: «Permission denied (publickey)»", fallo="B5",
                efecto="lo que falla está en lo que cloud-init instaló en la máquina "
                       "(usuario o clave).",
                arreglo=["Apague la máquina y, cuando esté apagada, vuelva a ejecutar "
                         "./ci-diagnosis: con la máquina apagada se revisa su disco y se ve "
                         "qué usuario y qué clave le instaló cloud-init.",
                         "$ virsh shutdown %s" % nombre_de_maquina(),
                         "$ virsh domstate %s" % nombre_de_maquina(),
                         "(tiene que decir «shut off»)"],
                seccion="faq-publickey"))
    else:
        ultima = [l for l in err.strip().splitlines() if l.strip()][-1:] or ["(sin mensaje)"]
        rs.append(error("ssh no ha podido entrar", detalle=["ssh dice: %s" % ultima[0]],
                        arreglo=["Pruébelo a mano con más detalle y fíjese en las "
                                 "últimas líneas:",
                                 "$ ssh -v %s@%s" % (USUARIO_VM, ip),
                                 "Si no lo entiende, pregunte en el chat de dudas con esas "
                                 "líneas y esta salida."],
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


# Errores de virt-install que se conocen (grabados en los servidores), con su arreglo
ERRORES_VIRT_INSTALL = (
    ("is already in use", "C2", "la máquina (o el disco) ya existe. Si quiere volver a "
     "crearla, elimine antes la que hay; si lo que pasa es que no puede entrar, use "
     "./ci-diagnosis --acceso."),
    ("Size must be specified for non existent volume", "B3",
     "no existe el disco de --disk path=: créelo antes con qemu-img create, desde "
     "~/imagenesMV (./ci-diagnosis --antes le da la orden)."),
    ("Permission denied", "B8", "QEMU no puede llegar al disco: ./ci-diagnosis --antes "
     "le dice qué directorio tiene que abrir (chmod o+x)."),
    ("codec can't decode", "A1", "un silo del servidor tiene un archivo con un nombre "
     "que no es UTF-8: ./ci-diagnosis --antes le dice cuál; si no es suyo, avise al "
     "profesor."),
    ("Cannot access backing file", "B3", "la imagen base no está donde estaba al crear "
     "el disco: devuélvala a su sitio, con su nombre."),
)


def _arreglo_de_error(mensaje):
    for patron, fallo, arreglo in ERRORES_VIRT_INSTALL:
        if patron in mensaje:
            return fallo, arreglo
    return None, ("lea el mensaje: dice qué opción o qué archivo falla. Corríjalo y "
                  "vuelva a ejecutar la orden del manual: " + orden_virt_install())


def _ruta_de_disk(valor):
    """path=serverX.qcow2,... → serverX.qcow2"""
    for parte in (valor or "").split(","):
        if parte.startswith("path="):
            return parte[len("path="):]
    primera = (valor or "").split(",")[0]
    return primera if "=" not in primera else None


def comprobar_orden(home, uvus, nombre, intento=None, existe=True):
    """C1: la última orden de virt-install para esa máquina, frente a la del manual.

    existe: si la máquina está creada (entonces corregir la orden es volver a
    crearla) o no (basta con ejecutar la orden buena)."""
    intento = intento or ultimo_intento(home, nombre)
    if intento is None:
        return [omitida("Orden de virt-install: no está en su registro "
                        "(~/.cache/virt-manager/virt-install.log): no la creó con "
                        "virt-install en esta cuenta, o el registro ya no la guarda")]
    palabras = intento.palabras
    maquina = nombre.split("-", 1)[1] if "-" in nombre else nombre
    manual = orden_virt_install(uvus, maquina)
    sec = "instanciar"
    rs = [ok("La orden que ejecutó (%s):" % intento.fecha,
             detalle=["virt-install " + " ".join(palabras[1:])])]
    graves = []      # los que obligan a repetir la orden (o a rehacer la máquina)
    menores = []     # los que solo se apartan del manual

    for e in intento.errores[:3]:
        fallo, arreglo = _arreglo_de_error(e)
        rs.append(error("virt-install terminó con un error", fallo=fallo,
                        detalle=["virt-install dijo: %s" % e[:300]],
                        efecto="no creó la máquina.", arreglo=arreglo, seccion=sec))

    un_guion = [p for p in palabras[1:] if re.match(r"^-[a-z]{2,}", p)]
    if un_guion:
        graves.append(error(
            "La orden tiene opciones con un solo guion: %s" % " ".join(un_guion),
            fallo="C1", efecto="virt-install las entiende como otra cosa "
            "(-noautoconsole es --name oautoconsole).",
            arreglo="todas las opciones empiezan por dos guiones: %s."
                    % ", ".join("-" + p for p in un_guion), seccion=sec))

    ci = _valor(palabras, "--cloud-init")
    sueltas = [p for p in palabras if re.match(r"^(user-data|meta-data|network-config)=", p)
               and p != ci]
    if ci is None:
        graves.append(error(
            "La orden no lleva --cloud-init", fallo="C1",
            efecto="cloud-init no recibió ninguno de los tres archivos: la máquina no "
                   "tiene el usuario administrador ni su IP.",
            arreglo="--cloud-init user-data=user-data,meta-data=meta-data,"
                    "network-config=network-config", seccion=sec))
    else:
        faltan = [a for a in ARCHIVOS_CI if a + "=" not in ci]
        if sueltas:
            graves.append(error(
                "Hay un espacio tras una coma en --cloud-init", fallo="C1",
                detalle=["Sueltos: %s" % " ".join(sueltas)],
                efecto="virt-install no los toma como parte de --cloud-init.",
                arreglo="los tres, separados por comas y sin espacios: --cloud-init "
                        "user-data=user-data,meta-data=meta-data,"
                        "network-config=network-config", seccion=sec))
        elif faltan:
            graves.append(error(
                "--cloud-init no lleva %s" % ", ".join(faltan), fallo="C1",
                efecto="cloud-init no recibió ese archivo%s." % (
                    ": la máquina no tiene su IP fija" if "network-config" in faltan
                    else ": la máquina no tiene el usuario administrador"
                    if "user-data" in faltan else ""),
                arreglo="--cloud-init user-data=user-data,meta-data=meta-data,"
                        "network-config=network-config", seccion=sec))
        else:
            # Los del silo: con ese nombre, sin directorio o con el del silo
            # (visto en avantasia, 9-nov: --cloud-init user-data=/tmp/.../user-data)
            silo = CONTEXTO.get("directorio")
            otros = []
            for parte in ci.split(","):
                clave, _, valor = parte.partition("=")
                if clave not in ARCHIVOS_CI:
                    continue
                directorio = os.path.dirname(valor)
                del_silo = os.path.basename(valor) == clave and (
                    directorio in ("", ".") or silo is None
                    or os.path.realpath(directorio) == os.path.realpath(silo))
                if not del_silo:
                    otros.append("%s=%s" % (clave, valor))
            if otros:
                menores.append(aviso(
                         "--cloud-init no usa los archivos %s del silo" % ", ".join(ARCHIVOS_CI),
                         detalle=["Usa: %s" % ", ".join(otros)],
                         efecto="la máquina se creó con esos archivos, y el bloque 5 revisa "
                                "los de nombre exacto: puede que no sean los mismos.",
                         arreglo="revise también esos archivos, o use los del manual.",
                         seccion=sec))

    if "--import" not in palabras:
        menores.append(aviso("La orden no lleva --import", fallo="C1",
                                  arreglo="añada --import: la máquina arranca del disco, que "
                                          "ya tiene Ubuntu.", seccion=sec))
    variante = _valor(palabras, "--os-variant") or _valor(palabras, "--osinfo")
    if variante is None:
        menores.append(aviso("La orden no lleva --os-variant", fallo="C1",
                                  arreglo="añada --os-variant=ubuntu24.04.", seccion=sec))
    elif variante != "ubuntu24.04":
        menores.append(aviso("La orden lleva --os-variant=%s; el manual, ubuntu24.04" % variante,
                             efecto="ninguno grave: libvirt ajusta el hardware virtual a ese "
                                    "sistema.", arreglo="--os-variant=ubuntu24.04", seccion=sec))
    red = _valor(palabras, "--network")
    if red is None:
        graves.append(aviso("La orden no lleva --network", fallo="C1",
                            efecto="la máquina queda en la red default, no en la suya: "
                                   "la IP de network-config no le sirve.",
                            arreglo="--network network=%s-red" % uvus, seccion=sec))
    elif "network=%s-red" % uvus not in red:
        graves.append(aviso("La orden conecta la máquina a otra red: %s" % red, fallo="C1",
                            efecto="la IP de network-config es de su red: en otra no "
                                   "podrá llegar a la máquina.",
                            arreglo="--network network=%s-red" % uvus, seccion=sec))
    disco = _ruta_de_disk(_valor(palabras, "--disk"))
    if disco is None:
        graves.append(error("La orden no lleva --disk path=...", fallo="C1",
                            efecto="la máquina no tiene el disco con Ubuntu.",
                            arreglo="--disk path=%s.qcow2" % maquina, seccion=sec))
    elif os.path.basename(disco) != "%s.qcow2" % maquina:
        menores.append(aviso("La orden usa el disco %s, no %s.qcow2" % (disco, maquina),
                             efecto="si ese disco ya lo usó otra máquina, cloud-init no se "
                                    "vuelve a aplicar (D2).",
                             arreglo="--disk path=%s.qcow2, un disco nuevo para cada máquina."
                                     % maquina, seccion=sec))
    ram = _valor(palabras, "--ram") or _valor(palabras, "--memory")
    if ram is not None and ram.replace("memory=", "") != "2048":
        menores.append(aviso("La orden pide %s MiB de RAM; el manual, 2048" % ram,
                             arreglo="--ram=2048.", seccion=sec))
    vcpus = _valor(palabras, "--vcpus")
    if vcpus is not None and vcpus != "2":
        menores.append(aviso("La orden pide %s vCPU; el manual, 2" % vcpus,
                             arreglo="--vcpus=2", seccion=sec))
    if "--noautoconsole" not in palabras and "-noautoconsole" not in palabras:
        menores.append(aviso("La orden no lleva --noautoconsole",
                             arreglo="añada --noautoconsole (con dos guiones).", seccion=sec))

    if graves:
        # El primero lleva los pasos completos; los demás, solo su corrección
        primero = graves[0]
        corregir = "Corrija la orden: %s" % "; ".join(
            texto_del_arreglo(g.arreglo).rstrip(".") for g in graves) + "."
        if existe:
            primero.arreglo = pasos_rehacer(corregir, uvus, maquina)
        else:
            primero.arreglo = [corregir, "La orden del manual, con sus nombres (desde "
                               "~/imagenesMV, en una sola línea):", "$ " + manual]
        for g in graves[1:]:
            g.arreglo = "%s (los pasos completos, arriba)." % texto_del_arreglo(
                g.arreglo).rstrip(".")
    rs += graves + menores
    if len(rs) == 1:
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
    rs = comprobar_orden(home, uvus, nombre, intento, existe=False)
    if not intento.errores and not [r for r in rs if r.estado in (ERROR, AVISO)]:
        rs.append(aviso("El último virt-install de %s (%s) no llegó a crear la máquina"
                        % (nombre, intento.fecha),
                        efecto="su registro no dice por qué; revise lo que mostró en "
                               "pantalla.",
                        arreglo=["Corrija lo que señale esta revisión y vuelva a ejecutar "
                                 "la orden del manual (desde ~/imagenesMV, en una sola "
                                 "línea):", "$ " + orden_virt_install()],
                        seccion="instanciar"))
    return rs
