# --- Secciones del manual ----------------------------------------------------
#
# Todas las referencias al manual están aquí: si el manual cambia la numeración,
# se cambia solo esta tabla. Numeración del manual v4.2.0.

SECCIONES = {
    "silo": "sección 5.2 (Silo)",
    "red": "sección 5.3 (Red virtual)",
    "preliminar": "sección 5.4.1 (Pasos preliminares)",
    "instanciar": "sección 5.4.2 (Instanciar la máquina virtual)",
    "acceso": "sección 5.4.3 (Primer acceso)",
    "faq-warning": "FAQ B.2 (remote host identification has changed)",
    "faq-publickey": "FAQ B.3 (Permission denied (publickey))",
    "faq-guestfs": "FAQ B.5 (libguestfs error)",
}

# Lo que espera el manual
USUARIO_VM = "administrador"
SUDO_ESPERADO = "ALL=(ALL) NOPASSWD:ALL"
INTERFAZ = "enp1s0"
DNS_ESPERADOS = ("150.214.186.69", "150.214.130.15")
ARCHIVOS_CI = ("user-data", "meta-data", "network-config")
IMAGEN_BASE = "noble-server-cloudimg-amd64.img"

# Lo que se sabe del alumno y de su máquina en esta revisión, para que las
# soluciones lleven sus nombres reales (lo rellena main; si falta algo, se usa
# el marcador del manual)
CONTEXTO = {}


def _ctx(clave, defecto):
    valor = CONTEXTO.get(clave)
    return str(valor) if valor else defecto


def nombre_de_maquina():
    return "%s-%s" % (_ctx("uvus", "<uvus>"), _ctx("maquina", "serverX"))


def orden_crear_disco(maquina=None):
    return ("qemu-img create %s.qcow2 -f qcow2 -b %s -F qcow2 40G"
            % (maquina or _ctx("maquina", "serverX"), IMAGEN_BASE))


def orden_virt_install(uvus=None, maquina=None):
    """La orden del manual (5.4.2), con los nombres del alumno."""
    uvus = uvus or _ctx("uvus", "<uvus>")
    maquina = maquina or _ctx("maquina", "serverX")
    return ("virt-install --name=%s-%s --cloud-init user-data=user-data,"
            "meta-data=meta-data,network-config=network-config --ram=2048 --vcpus=2 "
            "--import --disk path=%s.qcow2 --os-variant=ubuntu24.04 --network "
            "network=%s-red --noautoconsole" % (uvus, maquina, maquina, uvus))


class PasosRehacer(list):
    """Los pasos para volver a crear la máquina (una lista de pasos), con lo que
    hay que corregir antes. En un informe solo se muestran enteros una vez."""
    corregir = None


def pasos_rehacer(corregir=None, uvus=None, maquina=None):
    """Los pasos para volver a crear la máquina con un disco nuevo.

    corregir: lo que hay que corregir antes (un texto), si hay algo. uvus y
    maquina: si no se indican, los de CONTEXTO."""
    uvus = uvus or _ctx("uvus", "<uvus>")
    maquina = maquina or _ctx("maquina", "serverX")
    nombre = "%s-%s" % (uvus, maquina)
    ip = _ctx("ip", "192.168.XXX.YYY")
    pasos = ["Vuelva a crear la máquina con un disco nuevo, desde ~/imagenesMV "
             "(cd ~/imagenesMV):"]
    n = 1
    if corregir:
        pasos.append("%d. %s" % (n, corregir))
        n += 1
    pasos += ["%d. Elimine la máquina y su disco (la imagen base no se borra). Si "
              "está apagada, la primera orden dice que no está activa: no importa." % n,
              "$ virsh destroy %s" % nombre,
              "$ virsh undefine %s --remove-all-storage" % nombre,
              "%d. Cree un disco nuevo:" % (n + 1),
              "$ " + orden_crear_disco(maquina),
              "%d. Cree la máquina (es una sola línea):" % (n + 2),
              "$ " + orden_virt_install(uvus, maquina),
              "%d. Olvide la huella de la máquina anterior y, pasado un minuto, entre:"
              % (n + 3),
              "$ ssh-keygen -R %s" % ip,
              "$ ssh %s@%s" % (USUARIO_VM, ip)]
    resultado = PasosRehacer(pasos)
    resultado.corregir = corregir
    return resultado


def compactar_rehacer(resultados):
    """Los pasos para volver a crear la máquina, enteros solo la primera vez."""
    primero = None
    for r in resultados:
        if not isinstance(r.arreglo, PasosRehacer):
            continue
        if primero is None:
            primero = r
            continue
        corto = "vuelva a crear la máquina con un disco nuevo: los pasos están más " \
                "arriba, en «%s»." % primero.texto
        r.arreglo = ("%s Después, %s" % (r.arreglo.corregir, corto)
                     if r.arreglo.corregir else corto[0].upper() + corto[1:])
