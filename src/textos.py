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
