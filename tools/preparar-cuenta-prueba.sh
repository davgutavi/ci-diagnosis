#!/bin/bash
# Prepara una cuenta de alumno de prueba como la dejaría el manual (5.2 y 5.3):
# ~/imagenesMV, el silo <usuario>-imagenesMV y la red <usuario>-red, con un XXX
# libre. Se ejecuta CON LA CUENTA DE PRUEBA, no con la de un profesor:
#
#   bash preparar-cuenta-prueba.sh [--imagen RUTA]   prepara (no repite lo que ya hay)
#   bash preparar-cuenta-prueba.sh --quitar          quita el silo y la red
#
# --imagen RUTA   copia la imagen base desde RUTA en lugar de descargarla.
#
# Solo crea o quita objetos con el nombre del usuario que lo ejecuta. --quitar
# no borra ningún archivo (ni ~/imagenesMV ni lo que contenga).

set -euo pipefail
export LC_ALL=C
URI="qemu:///system"
USUARIO="$(id -un)"
SILO_DIR="$HOME/imagenesMV"
SILO="${USUARIO}-imagenesMV"
RED="${USUARIO}-red"
IMAGEN_BASE="noble-server-cloudimg-amd64.img"
URL="https://cloud-images.ubuntu.com/noble/current/$IMAGEN_BASE"

v() { virsh -q -c "$URI" "$@"; }
existe_silo() { v pool-info "$SILO" >/dev/null 2>&1; }
existe_red()  { v net-info "$RED" >/dev/null 2>&1; }
activo()      { v "$1" "$2" 2>/dev/null | grep -qE '^(Active|State): *(yes|running)'; }

quitar() {
    if existe_red; then
        activo net-info "$RED" && v net-destroy "$RED"
        v net-undefine "$RED"
        echo "Red $RED quitada."
    else
        echo "No hay red $RED."
    fi
    if existe_silo; then
        activo pool-info "$SILO" && v pool-destroy "$SILO"
        v pool-undefine "$SILO"
        echo "Silo $SILO quitado (el directorio $SILO_DIR sigue ahí)."
    else
        echo "No hay silo $SILO."
    fi
}

# Primer XXX (de 200 a 254) que no usa ninguna red de libvirt, ni una dirección
# ni una ruta del servidor
xxx_libre() {
    local usadas n x
    usadas="$( {
        for n in $(v net-list --all --name); do
            v net-dumpxml "$n" 2>/dev/null || true
        done | grep -oE "address='192\.168\.[0-9]+\." || true
        ip -4 addr | grep -oE 'inet 192\.168\.[0-9]+\.' || true
        ip -4 route | grep -oE '(^| )192\.168\.[0-9]+\.' || true
    } | grep -oE '192\.168\.[0-9]+' | sort -u )"
    for x in $(seq 200 254); do
        if ! grep -qx "192\.168\.$x" <<< "$usadas"; then
            echo "$x"
            return 0
        fi
    done
    return 1
}

preparar() {
    local imagen="${1:-}"
    echo "Usuario: $USUARIO"
    mkdir -p "$SILO_DIR"

    if existe_silo; then
        echo "El silo $SILO ya existe."
    else
        v pool-define-as "$SILO" dir --target "$SILO_DIR" >/dev/null
        v pool-autostart "$SILO" >/dev/null
        echo "Silo $SILO creado sobre $SILO_DIR."
    fi
    activo pool-info "$SILO" || v pool-start "$SILO" >/dev/null

    if existe_red; then
        echo "La red $RED ya existe."
    else
        local x
        x="$(xxx_libre)" || { echo "No hay ningún XXX libre entre 200 y 254." >&2; exit 1; }
        XML="$(mktemp)"
        trap 'rm -f "$XML"' EXIT
        cat > "$XML" <<FIN
<network>
  <name>$RED</name>
  <forward mode='nat'/>
  <ip address='192.168.$x.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.$x.128' end='192.168.$x.254'/>
    </dhcp>
  </ip>
</network>
FIN
        v net-define "$XML" >/dev/null
        v net-autostart "$RED" >/dev/null
        echo "Red $RED creada: 192.168.$x.0/24."
    fi
    activo net-info "$RED" || v net-start "$RED" >/dev/null

    if [[ -f "$SILO_DIR/$IMAGEN_BASE" ]]; then
        echo "La imagen base ya está en el silo."
    elif [[ -n "$imagen" ]]; then
        cp "$imagen" "$SILO_DIR/$IMAGEN_BASE"
        chmod 644 "$SILO_DIR/$IMAGEN_BASE"
        echo "Imagen base copiada de $imagen."
    else
        wget -q -O "$SILO_DIR/$IMAGEN_BASE" "$URL"
        echo "Imagen base descargada."
    fi

    echo
    v pool-info "$SILO"
    v net-info "$RED"
    v net-dumpxml "$RED" | grep -E '<ip |<range '
    ls -l "$SILO_DIR"
}

case "${1:-}" in
    --quitar) quitar ;;
    --imagen) preparar "${2:?falta la ruta de la imagen}" ;;
    "")       preparar ;;
    *)        echo "Uso: $0 [--imagen RUTA | --quitar]" >&2; exit 2 ;;
esac
