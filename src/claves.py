# --- Claves SSH (B5, B7, B10, D6) -------------------------------------------
#
# Nunca se muestra ni se guarda nada de la clave privada: de ella solo se lee la
# cabecera, que en el formato openssh-key-v1 dice, sin cifrar, si tiene
# contraseña y cuál es su clave pública.

class ClavePublica:
    def __init__(self, tipo, blob, comentario=""):
        self.tipo = tipo
        self.blob = blob
        self.comentario = comentario

    @property
    def huella(self):
        resumen = base64.b64encode(hashlib.sha256(self.blob).digest()).decode()
        return "SHA256:" + resumen.rstrip("=")

    def describir(self):
        if self.comentario:
            return "%s (%s)" % (self.huella, self.comentario)
        return self.huella


def _cadenas_ssh(blob):
    """Divide un blob SSH en sus cadenas (uint32 de longitud + datos), o None
    si no está completo: así se detecta una clave cortada."""
    cadenas, i = [], 0
    while i < len(blob):
        if i + 4 > len(blob):
            return None
        n = struct.unpack(">I", blob[i:i + 4])[0]
        if i + 4 + n > len(blob):
            return None
        cadenas.append(blob[i + 4:i + 4 + n])
        i += 4 + n
    return cadenas


# Número de cadenas del blob público de cada tipo
CAMPOS_POR_TIPO = {"ssh-rsa": 3, "ssh-ed25519": 2, "ssh-dss": 5,
                   "ecdsa-sha2-nistp256": 3, "ecdsa-sha2-nistp384": 3,
                   "ecdsa-sha2-nistp521": 3}


def clave_desde_blob(blob, comentario=""):
    cadenas = _cadenas_ssh(blob)
    if not cadenas:
        return None
    try:
        tipo = cadenas[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    if tipo in CAMPOS_POR_TIPO and len(cadenas) != CAMPOS_POR_TIPO[tipo]:
        return None
    return ClavePublica(tipo, blob, comentario)


def analizar_clave_publica(texto):
    """'ssh-rsa AAAA... comentario' → ClavePublica, o None si no es válida."""
    partes = texto.strip().split(None, 2)
    if len(partes) < 2:
        return None
    try:
        blob = base64.b64decode(partes[1], validate=True)
    except (ValueError, TypeError):
        return None
    clave = clave_desde_blob(blob, partes[2] if len(partes) > 2 else "")
    if clave is None or clave.tipo != partes[0]:
        return None
    return clave


PRIVADA_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def analizar_privada(datos):
    """Cabecera de una clave privada.

    Devuelve (formato, cifrada, publica): formato 'openssh', 'pem' o None (no
    se reconoce); cifrada True/False/None (no se sabe); publica, la ClavePublica
    que contiene (solo en el formato openssh).
    """
    texto = datos.decode("ascii", "replace")
    if "-----BEGIN OPENSSH PRIVATE KEY-----" in texto:
        cuerpo = texto.split("-----BEGIN OPENSSH PRIVATE KEY-----", 1)[1]
        cuerpo = cuerpo.split("-----END OPENSSH PRIVATE KEY-----", 1)[0]
        try:
            blob = base64.b64decode("".join(cuerpo.split()))
        except (ValueError, TypeError):
            return "openssh", None, None
        magia = b"openssh-key-v1\0"
        if not blob.startswith(magia):
            return "openssh", None, None
        resto = blob[len(magia):]
        # cifrado, kdf, opciones del kdf, número de claves y la primera pública
        campos, i = [], 0
        try:
            for _ in range(3):
                n = struct.unpack(">I", resto[i:i + 4])[0]
                campos.append(resto[i + 4:i + 4 + n])
                i += 4 + n
            i += 4
            n = struct.unpack(">I", resto[i:i + 4])[0]
            publica = clave_desde_blob(resto[i + 4:i + 4 + n])
        except struct.error:
            return "openssh", None, None
        return "openssh", campos[0] != b"none", publica
    if PRIVADA_RE.search(texto):
        cifrada = ("Proc-Type: 4,ENCRYPTED" in texto
                   or "BEGIN ENCRYPTED PRIVATE KEY" in texto)
        return "pem", cifrada, None
    return None, None, None


def _modo(st):
    return "%04o" % stat.S_IMODE(st.st_mode)


def comprobar_claves(home):
    """Comprobaciones de ~/.ssh/id_rsa y ~/.ssh/id_rsa.pub.

    Devuelve (resultados, clave pública del servidor o None).
    """
    rs = []
    dir_ssh = os.path.join(home, ".ssh")
    ruta_pub = os.path.join(dir_ssh, "id_rsa.pub")
    ruta_priv = os.path.join(dir_ssh, "id_rsa")

    datos_pub = leer_bytes(ruta_pub)
    publica = None
    if datos_pub is None:
        otras = sorted(n for n in _listar(dir_ssh)
                       if n.startswith("id_") and n.endswith(".pub"))
        rs.append(error(
            "No existe ~/.ssh/id_rsa.pub (o no se puede leer)", fallo="B7",
            detalle=["En ~/.ssh hay: %s." % ", ".join(otras)] if otras else [],
            efecto="no hay clave pública que poner en user-data.",
            arreglo="genere la pareja de claves RSA con «ssh-keygen -t rsa» y "
                    "acepte el nombre que propone.",
            seccion="preliminar"))
    else:
        publica = analizar_clave_publica(datos_pub.decode("utf-8", "replace"))
        if publica is None:
            rs.append(error(
                "~/.ssh/id_rsa.pub no contiene una clave pública válida", fallo="B7",
                arreglo="si conserva ~/.ssh/id_rsa, puede volver a obtener la "
                        "pública con «ssh-keygen -y -f ~/.ssh/id_rsa».",
                seccion="preliminar"))
        elif publica.tipo != "ssh-rsa":
            rs.append(aviso(
                "~/.ssh/id_rsa.pub es de tipo %s, no RSA" % publica.tipo,
                arreglo="el manual usa claves RSA («ssh-keygen -t rsa»).",
                seccion="preliminar"))
        else:
            rs.append(ok("~/.ssh/id_rsa.pub: clave RSA %s" % publica.huella))

    try:
        st = os.stat(ruta_priv)
    except OSError:
        rs.append(error(
            "No existe ~/.ssh/id_rsa", fallo="B7",
            efecto="ssh no tiene con qué entrar en las máquinas: "
                   "«Permission denied (publickey)».",
            arreglo=["Si la borró, aparte la pública que queda y genere una pareja "
                     "nueva (acepte el nombre que propone):",
                     "$ mv ~/.ssh/id_rsa.pub ~/.ssh/id_rsa.pub.vieja",
                     "$ ssh-keygen -t rsa",
                     "Después ponga la nueva ~/.ssh/id_rsa.pub en user-data y vuelva a "
                     "crear las máquinas que ya tenga: las anteriores solo aceptan la "
                     "clave que se perdió."],
            seccion="faq-publickey"))
        return rs, publica

    if st.st_mode & 0o077:
        rs.append(error(
            "~/.ssh/id_rsa tiene permisos %s: puede leerla alguien más" % _modo(st),
            fallo="B10",
            efecto="ssh y ssh-add la ignoran («WARNING: UNPROTECTED PRIVATE KEY "
                   "FILE!» … «This private key will be ignored.»), y la máquina "
                   "responderá «Permission denied (publickey)».",
            arreglo="chmod 600 ~/.ssh/id_rsa", seccion="preliminar"))
    else:
        rs.append(ok("~/.ssh/id_rsa: solo la puede leer usted (%s)" % _modo(st)))

    datos_priv = leer_bytes(ruta_priv)
    if datos_priv is None:
        rs.append(error("No se puede leer ~/.ssh/id_rsa", fallo="B10",
                        arreglo="chmod 600 ~/.ssh/id_rsa", seccion="preliminar"))
        return rs, publica
    formato, cifrada, pub_de_priv = analizar_privada(datos_priv)
    del datos_priv

    if formato is None:
        rs.append(error("~/.ssh/id_rsa no parece una clave privada", fallo="B7",
                        efecto="ssh no tiene con qué entrar en las máquinas: "
                               "«Permission denied (publickey)».",
                        arreglo=["Apártela y genere una pareja nueva (acepte el nombre "
                                 "que propone):",
                                 "$ mv ~/.ssh/id_rsa ~/.ssh/id_rsa.mala",
                                 "$ mv ~/.ssh/id_rsa.pub ~/.ssh/id_rsa.pub.mala",
                                 "$ ssh-keygen -t rsa",
                                 "Después ponga la nueva ~/.ssh/id_rsa.pub en user-data y "
                                 "vuelva a crear las máquinas que ya tenga."],
                        seccion="preliminar"))
        return rs, publica
    if formato == "pem" and cifrada is False:
        # Formato antiguo sin contraseña: ssh-keygen calcula la pública
        codigo, salida, _ = ejecutar(["ssh-keygen", "-y", "-P", "", "-f", ruta_priv])
        if codigo == 0:
            pub_de_priv = analizar_clave_publica(salida)

    if publica is not None:
        if pub_de_priv is None:
            rs.append(omitida("Correspondencia entre id_rsa e id_rsa.pub: no se "
                              "puede comprobar sin la contraseña de la clave"))
        elif pub_de_priv.blob == publica.blob:
            rs.append(ok("~/.ssh/id_rsa e id_rsa.pub son pareja"))
        else:
            rs.append(error(
                "~/.ssh/id_rsa e id_rsa.pub no son pareja", fallo="B7",
                detalle=["id_rsa.pub:           %s" % publica.huella,
                         "pública de id_rsa:    %s" % pub_de_priv.huella],
                efecto="las máquinas creadas con esta id_rsa.pub no aceptarán su "
                       "clave privada: «Permission denied (publickey)».",
                arreglo="si id_rsa es la buena, vuelva a obtener la pública con "
                        "«ssh-keygen -y -f ~/.ssh/id_rsa > ~/.ssh/id_rsa.pub» y "
                        "póngala en user-data.",
                seccion="faq-publickey"))

    if cifrada is False:
        rs.append(ok("La clave privada no tiene contraseña: no necesita el agente"))
    elif cifrada:
        rs.append(comprobar_agente(pub_de_priv or publica))
    # Sin id_rsa.pub, la clave con la que entra ssh es la de id_rsa
    return rs, publica or pub_de_priv


def _listar(directorio):
    try:
        return os.listdir(directorio)
    except OSError:
        return []


def estado_de_la_clave(home):
    """(cifrada, en el agente) de ~/.ssh/id_rsa, para interpretar ssh (D6)."""
    datos = leer_bytes(os.path.join(home, ".ssh", "id_rsa"))
    if datos is None:
        return None, False
    _, cifrada, publica = analizar_privada(datos)
    del datos
    if publica is None:
        pub = leer_bytes(os.path.join(home, ".ssh", "id_rsa.pub"))
        publica = analizar_clave_publica(pub.decode("utf-8", "replace")) if pub else None
    if not os.environ.get("SSH_AUTH_SOCK") or publica is None:
        return cifrada, False
    codigo, salida, _ = ejecutar(["ssh-add", "-L"], timeout=10)
    if codigo != 0:
        return cifrada, False
    cargadas = [analizar_clave_publica(l) for l in salida.splitlines()]
    return cifrada, any(c and c.blob == publica.blob for c in cargadas)


def comprobar_agente(clave):
    """D6: con contraseña, la clave debería estar cargada en el agente."""
    arreglo_agente = ("cárguela con «ssh-add» (si no funciona, antes "
                      "«eval \"$(ssh-agent -s)\"»). Hay que hacerlo en cada sesión.")
    efecto = ("ssh le pedirá la contraseña de la clave cada vez. Si la teclea mal, "
              "acabará en «Permission denied (publickey)» aunque todo esté bien.")
    if not os.environ.get("SSH_AUTH_SOCK"):
        return aviso("Su clave tiene contraseña y no hay agente en esta sesión",
                     fallo="D6", efecto=efecto, arreglo=arreglo_agente,
                     seccion="preliminar")
    codigo, salida, _ = ejecutar(["ssh-add", "-L"], timeout=10)
    if codigo == 0:
        cargadas = [analizar_clave_publica(l) for l in salida.splitlines()]
        if clave is not None and any(c and c.blob == clave.blob for c in cargadas):
            return ok("Su clave está cargada en el agente")
        return aviso(
            "El agente no tiene su clave ~/.ssh/id_rsa", fallo="D6",
            detalle=["El agente tiene %d clave(s) de otro origen (si entró al "
                     "servidor con «ssh -A», son las de su ordenador)." % len(cargadas)],
            efecto=efecto, arreglo=arreglo_agente, seccion="preliminar")
    if codigo == 1:
        return aviso("El agente no tiene ninguna clave cargada", fallo="D6",
                     efecto=efecto, arreglo=arreglo_agente, seccion="preliminar")
    return aviso("No se puede consultar el agente de claves", fallo="D6",
                 efecto=efecto, arreglo="«eval \"$(ssh-agent -s)\"» y después «ssh-add».",
                 seccion="preliminar")
