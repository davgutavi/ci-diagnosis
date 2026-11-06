#!/bin/bash
# Batería de pruebas de ci-diagnosis en un servidor de la asignatura.
#
# Se ejecuta CON UNA CUENTA DE ALUMNO DE PRUEBA (sin sudo), preparada antes con
# tools/preparar-cuenta-prueba.sh: silo <usuario>-imagenesMV, red <usuario>-red
# e imagen base. Desde la cuenta de un profesor, por ejemplo:
#
#   sudo -iu CUENTA bash /ruta/pruebas-servidor.sh a
#
#   a   Revisión --antes: provoca cada fallo en el silo de la cuenta de prueba
#       (archivos, claves, disco, permisos) y comprueba que ci-diagnosis lo
#       detecta. No crea máquinas, silos ni redes.
#
# Variables:
#   CI_DIAGNOSIS=RUTA   el programa que se prueba (por defecto, ci-diagnosis en
#                       el mismo directorio que este script)
#
# Al terminar deja el silo como estaba (solo con la imagen base), aunque falle
# algo. El registro completo, con la salida de cada ejecución, queda en /tmp.
#
# NUNCA se crea aquí un archivo cuyo nombre no sea UTF-8: el silo está activo
# y eso haría fallar virt-install a todos los usuarios del servidor (A1). Ese
# caso solo se prueba en los tests locales.

set -uo pipefail
export LC_ALL=C
# Los alumnos no tienen grupo propio y crean sus archivos con 644; la cuenta de
# prueba sí lo tiene (su máscara sería 002), así que se fija la de los alumnos
umask 022
URI="qemu:///system"
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CI="${CI_DIAGNOSIS:-$AQUI/ci-diagnosis}"
PY=/usr/bin/python3
FASE="${1:-a}"
USUARIO="$(id -un)"
SILO="$HOME/imagenesMV"
BASE="noble-server-cloudimg-amd64.img"
LOG="/tmp/pruebas-ci-diagnosis-$USUARIO-$(date +%Y%m%d-%H%M%S).log"
OK=0
KO=0

if [[ -t 1 ]]; then V=$'\033[32m'; R=$'\033[31m'; N=$'\033[0m'; else V=""; R=""; N=""; fi
titulo() { echo; echo "═══ $* ═══"; printf '\n═══ %s ═══\n' "$*" >> "$LOG"; }
ok()     { OK=$(( OK + 1 )); printf '  %s✔%s %s\n' "$V" "$N" "$*"; }
ko()     { KO=$(( KO + 1 )); printf '  %s✘%s %s\n' "$R" "$N" "$*"; }
info()   { printf '  · %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Comprobaciones previas
# ---------------------------------------------------------------------------
if id -nG | tr ' ' '\n' | grep -qx sudo; then
    echo "Esta cuenta está en el grupo sudo: lánzalo con la cuenta de alumno de prueba." >&2
    exit 1
fi
[[ -f "$CI" ]] || { echo "No encuentro ci-diagnosis en $CI" >&2; exit 1; }
virsh -q -c "$URI" pool-info "$USUARIO-imagenesMV" >/dev/null 2>&1 \
    || { echo "Falta el silo $USUARIO-imagenesMV: lanza antes preparar-cuenta-prueba.sh" >&2; exit 1; }
XXX="$(virsh -q -c "$URI" net-dumpxml "$USUARIO-red" 2>/dev/null \
       | sed -n "s/.*<ip address='192\.168\.\([0-9]*\)\.1'.*/\1/p" | head -1)"
[[ -n "$XXX" ]] || { echo "Falta la red $USUARIO-red: lanza antes preparar-cuenta-prueba.sh" >&2; exit 1; }
[[ -f "$SILO/$BASE" ]] || { echo "Falta $SILO/$BASE" >&2; exit 1; }

T="$(mktemp -d)"
MODO_HOME="$(stat -c %a "$HOME")"
AGENTE_PID=""

limpiar() {
    chmod "$MODO_HOME" "$HOME"
    [[ -f "$T/$BASE" && ! -f "$SILO/$BASE" ]] && mv "$T/$BASE" "$SILO/$BASE"
    [[ -n "$AGENTE_PID" ]] && kill "$AGENTE_PID" 2>/dev/null
    (cd "$SILO" && rm -f -- user-data meta-data network-config ./*.yaml ./*~ \
        "user-data"$'\342\200\213' server1.qcow2 server1.qcow2.* )
    rm -rf "$HOME/pruebas-b2" "$T"
}
trap limpiar EXIT

: > "$LOG"
chmod 644 "$LOG"
{
    echo "# Pruebas de ci-diagnosis, fase $FASE, $(date '+%Y-%m-%d %H:%M:%S')"
    echo "# $(hostname) · $USUARIO · red 192.168.$XXX.0/24 · $("$PY" "$CI" --version)"
    "$PY" --version
    "$PY" -c 'import yaml; print("PyYAML", yaml.__version__)'
    qemu-img --version | head -1
    ssh -V
} >> "$LOG" 2>&1

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
# Claves de usar y tirar, sin frase de paso salvo que se indique
clave() {   # RUTA COMENTARIO [FRASE]
    ssh-keygen -q -t rsa -b 2048 -N "${3:-}" -C "$2" -f "$1" <<< y >/dev/null 2>&1
}

# La cuenta de prueba necesita su pareja de claves (como la del manual, 5.4.1)
if [[ ! -f "$HOME/.ssh/id_rsa" ]]; then
    mkdir -p -m 700 "$HOME/.ssh"
    clave "$HOME/.ssh/id_rsa" "$USUARIO@$(hostname -s)"
fi
PUB="$(cat "$HOME/.ssh/id_rsa.pub")"
clave "$T/portatil" "$USUARIO@portatil"

user_data() {   # [CLAVE]
    cat <<FIN
#cloud-config
users:
  - name: administrador
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    groups: sudo
    shell: /bin/bash
    ssh_authorized_keys:
      - ${1:-$PUB}
FIN
}

meta_data() {
    printf 'instance-id: %s-server1\nlocal-hostname: server1\n' "$USUARIO"
}

network_config() {   # [IP/PREFIJO] [PASARELA] [INTERFAZ]
    cat <<FIN
version: 2
ethernets:
  ${3:-enp1s0}:
    addresses:
      - ${1:-192.168.$XXX.2/24}
    routes:
      - to: default
        via: ${2:-192.168.$XXX.1}
    nameservers:
      addresses:
        - 150.214.186.69
        - 150.214.130.15
FIN
}

# Deja el silo como lo dejaría el manual: los tres archivos y el disco
preparar_bien() {
    (cd "$SILO" && rm -f -- user-data meta-data network-config ./*.yaml \
        "user-data"$'\342\200\213' server1.qcow2)
    user_data > "$SILO/user-data"
    meta_data > "$SILO/meta-data"
    network_config > "$SILO/network-config"
    (cd "$SILO" && qemu-img create -q server1.qcow2 -f qcow2 -b "$BASE" -F qcow2 40G)
}

# ejecuta DIRECTORIO [ARGS...]: lanza ci-diagnosis y deja la salida en SALIDA y RC
ejecuta() {
    local dir="$1"; shift
    SALIDA="$(cd "$dir" && "$PY" "$CI" "$@" 2>&1)"; RC=$?
    printf '\n$ (%s) ci-diagnosis %s   → código %s\n%s\n' "$dir" "$*" "$RC" "$SALIDA" >> "$LOG"
}

# espera DESCRIPCION PATRON: la última salida tiene que contener PATRON (ERE)
espera() {
    if grep -qE -- "$2" <<< "$SALIDA"; then
        ok "$1"
    else
        ko "$1 → no aparece: $2"
        grep -E '^  (ERROR|AVISO)' <<< "$SALIDA" | head -4 | sed 's/^/       | /'
    fi
}

# no_aparece DESCRIPCION TEXTO: la última salida NO tiene que contener TEXTO (literal)
no_aparece() {
    if grep -qF -- "$2" <<< "$SALIDA"; then ko "$1"; else ok "$1"; fi
}

# caso DESCRIPCION PATRON: prepara el silo bien, aplica el cambio que se pase
# por la entrada estándar (una orden de bash) y comprueba
caso() {
    local desc="$1" patron="$2" cambio
    cambio="$(cat)"
    preparar_bien
    (cd "$SILO" && eval "$cambio")
    ejecuta "$SILO" server1
    espera "$desc" "$patron"
}

# ---------------------------------------------------------------------------
# Fase A: revisión --antes
# ---------------------------------------------------------------------------
fase_a() {
    titulo "A.0 Todo como dice el manual"
    preparar_bien
    ejecuta "$SILO" server1
    espera "sale «todo correcto»" '^Resultado: todo correcto\.$'
    [[ "$RC" == 0 ]] && ok "código de salida 0" || ko "código de salida $RC, esperaba 0"
    ejecuta "$SILO"
    espera "sin argumentos, deduce la máquina de meta-data" "máquina: $USUARIO-server1"

    titulo "A.1 Caracteres copiados del PDF o de la web (B1)"
    caso "espacio invisible U+200B" 'caracteres invisibles .*\[B1\]' <<'FIN'
sed -i 's/name: administrador/name: administrador\xe2\x80\x8b/' user-data
FIN
    caso "espacio de no separación U+00A0" 'U\+00A0' <<'FIN'
sed -i 's/instance-id: /instance-id:\xc2\xa0/' meta-data
FIN
    caso "raya en lugar de guion" 'rayas en lugar de guiones' <<'FIN'
sed -i 's/  - name:/  \xe2\x80\x93 name:/' user-data
FIN
    caso "comillas curvas en sudo" 'comillas curvas' <<'FIN'
sed -i "s/\['ALL=(ALL) NOPASSWD:ALL'\]/[\xe2\x80\x98ALL=(ALL) NOPASSWD:ALL\xe2\x80\x99]/" user-data
FIN
    caso "finales de línea CRLF" 'CRLF' <<'FIN'
sed -i 's/$/\r/' network-config
FIN
    caso "BOM al principio de user-data" 'BOM' <<'FIN'
printf '\xef\xbb\xbf' | cat - user-data > u && mv u user-data
FIN
    caso "espacio invisible en el nombre del archivo" 'user-data\\342\\200\\213' <<'FIN'
mv user-data "user-data"$'\342\200\213'
FIN

    titulo "A.2 user-data (B4, B5)"
    caso "sin #cloud-config" 'primera línea de user-data no es #cloud-config' <<'FIN'
sed -i '1d' user-data
FIN
    caso "# cloud-config con espacio" 'sin espacios' <<'FIN'
sed -i '1s/.*/# cloud-config/' user-data
FIN
    caso "tabuladores" 'tabuladores \(línea 6\)' <<'FIN'
sed -i 's/^    shell:/\tshell:/' user-data
FIN
    caso "mal indentado: YAML inválido, con la línea" 'no es YAML válido' <<'FIN'
sed -i 's/^    groups:/  groups:/' user-data
FIN
    info "mensaje de PyYAML: $(grep -m1 'PyYAML dice' <<< "$SALIDA" | sed 's/^ *//')"
    caso "ssh_authorized_keys fuera del usuario" 'fuera del usuario administrador' <<'FIN'
sed -i 's/^    ssh_authorized_keys:/ssh_authorized_keys:/' user-data
FIN
    caso "users sin guion" 'Falta el guion' <<'FIN'
sed -i 's/^  - name:/    name:/' user-data
FIN
    caso "archivos con .yaml" 'mv user-data\.yaml user-data' <<'FIN'
mv user-data user-data.yaml
FIN
    caso "clave del portátil" 'no es la de ~/\.ssh/id_rsa\.pub \[B5\]' <<FIN
user_data "\$(cat "$T/portatil.pub")" > user-data
FIN
    espera "  ...y dice el comentario de la clave" "$USUARIO@portatil"
    caso "clave partida en dos líneas" 'partida en varias líneas' <<'FIN'
python3 - <<'PY'
t = open("user-data").read().split("\n")
i = next(n for n, l in enumerate(t) if "ssh-rsa" in l)
tipo, cuerpo, comentario = t[i].split("- ", 1)[1].split()
m = len(cuerpo) // 2
t[i:i + 1] = ["      - %s %s" % (tipo, cuerpo[:m]), "        %s %s" % (cuerpo[m:], comentario)]
open("user-data", "w").write("\n".join(t))
PY
FIN
    caso "clave privada pegada" 'contiene una clave privada' <<FIN
{ head -7 user-data; echo '      - |'; sed 's/^/        /' "$T/portatil"; } > u && mv u user-data
FIN
    no_aparece "  ...y no muestra nada de la clave privada" "$(sed -n 2p "$T/portatil" | cut -c1-30)"
    caso "texto de ejemplo del manual" 'texto de ejemplo' <<'FIN'
sed -i 's/      - ssh-rsa .*/      - SU CLAVE PÚBLICA/' user-data
FIN

    titulo "A.3 meta-data y network-config (B6)"
    caso "meta-data de otra máquina" "instance-id de meta-data no es $USUARIO-server1" <<'FIN'
sed -i 's/server1/server2/' meta-data
FIN
    caso "otra interfaz (eth0)" 'no configura la interfaz enp1s0' <<FIN
network_config "" "" eth0 > network-config
FIN
    caso "sin /24" 'no lleva /24' <<FIN
network_config "192.168.$XXX.2" > network-config
FIN
    caso "IP de otra red" 'no es de su red' <<FIN
network_config "10.0.$XXX.2/24" > network-config
FIN
    caso "IP dentro del DHCP" 'rango del DHCP' <<FIN
network_config "192.168.$XXX.200/24" > network-config
FIN
    caso "IP de la pasarela" 'reservada' <<FIN
network_config "192.168.$XXX.1/24" > network-config
FIN
    caso "pasarela equivocada" "La pasarela 192\.168\.$XXX\.254 no es la de su red" <<FIN
network_config "" "192.168.$XXX.254" > network-config
FIN

    titulo "A.4 Disco (B3)"
    info "qemu-img create sin -F (mensaje real):"
    (cd "$SILO" && rm -f server1.qcow2 \
        && qemu-img create server1.qcow2 -f qcow2 -b "$BASE" 40G 2>&1) | tee -a "$LOG" | sed 's/^/       | /'
    caso "disco de 20G" 'no 40 GiB' <<'FIN'
rm -f server1.qcow2 && qemu-img create -q server1.qcow2 -f qcow2 -b noble-server-cloudimg-amd64.img -F qcow2 20G
FIN
    caso "respaldo en formato raw (-F raw)" 'falta -F qcow2' <<'FIN'
rm -f server1.qcow2 && qemu-img create -q server1.qcow2 -f qcow2 -b noble-server-cloudimg-amd64.img -F raw 40G
FIN
    caso "disco sin crear" 'No existe el disco server1\.qcow2' <<'FIN'
rm -f server1.qcow2
FIN
    caso "disco que puede modificar cualquiera (666)" 'cualquier usuario del servidor' <<'FIN'
chmod 666 server1.qcow2
FIN
    preparar_bien
    mv "$SILO/$BASE" "$T/$BASE"
    ejecuta "$SILO" server1
    espera "imagen base movida" 'No está la imagen de la que depende server1\.qcow2'
    mv "$T/$BASE" "$SILO/$BASE"

    titulo "A.5 Directorio y permisos (B2, B8)"
    preparar_bien
    ejecuta "$HOME" server1
    espera "trabajando en el home" 'Está en su directorio personal, no en su silo'
    mkdir -p "$HOME/pruebas-b2"
    ejecuta "$HOME/pruebas-b2" server1
    espera "trabajando en un directorio que no es silo" 'no es un silo'
    chmod 700 "$HOME"
    ejecuta "$SILO" server1
    espera "home cerrado (700): libvirt-qemu no llega" 'libvirt-qemu no puede atravesar .*\[B8\]'
    chmod "$MODO_HOME" "$HOME"

    titulo "A.6 Claves (B7, B10, D6), con un HOME aparte"
    local h="$T/home"
    mkdir -p -m 700 "$h/.ssh"
    preparar_bien
    clave "$h/.ssh/id_rsa" "$USUARIO@servidor"
    cp "$T/portatil.pub" "$h/.ssh/id_rsa.pub"
    SALIDA="$(cd "$SILO" && HOME="$h" "$PY" "$CI" server1 2>&1)"
    printf '\n$ HOME=%s ci-diagnosis (pareja cambiada)\n%s\n' "$h" "$SALIDA" >> "$LOG"
    espera "id_rsa e id_rsa.pub no son pareja" 'no son pareja \[B7\]'
    clave "$h/.ssh/id_rsa" "$USUARIO@servidor"
    chmod 644 "$h/.ssh/id_rsa"
    SALIDA="$(cd "$SILO" && HOME="$h" "$PY" "$CI" server1 2>&1)"
    printf '\n$ HOME=%s ci-diagnosis (id_rsa 644)\n%s\n' "$h" "$SALIDA" >> "$LOG"
    espera "id_rsa con permisos 644" 'permisos 0644.*\[B10\]'
    clave "$h/.ssh/id_rsa" "$USUARIO@servidor" "frase de prueba"
    SALIDA="$(cd "$SILO" && HOME="$h" SSH_AUTH_SOCK= "$PY" "$CI" server1 2>&1)"
    printf '\n$ HOME=%s ci-diagnosis (con frase, sin agente)\n%s\n' "$h" "$SALIDA" >> "$LOG"
    espera "frase de paso sin agente" 'no hay agente en esta sesión \[D6\]'
    # Un agente propio, con la clave cargada sin teclado (SSH_ASKPASS)
    printf '#!/bin/sh\necho "frase de prueba"\n' > "$T/askpass"
    chmod 700 "$T/askpass"
    eval "$(ssh-agent -s)" >/dev/null
    AGENTE_PID="$SSH_AGENT_PID"
    SSH_ASKPASS="$T/askpass" SSH_ASKPASS_REQUIRE=force DISPLAY=x \
        ssh-add "$h/.ssh/id_rsa" </dev/null >>"$LOG" 2>&1
    SALIDA="$(cd "$SILO" && HOME="$h" "$PY" "$CI" server1 2>&1)"
    printf '\n$ HOME=%s ci-diagnosis (con frase, en el agente)\n%s\n' "$h" "$SALIDA" >> "$LOG"
    espera "frase de paso con la clave en el agente" 'Su clave está cargada en el agente'
    kill "$AGENTE_PID" 2>/dev/null; AGENTE_PID=""

    titulo "A.7 cloud-init schema en el servidor (información para B4)"
    preparar_bien
    if command -v cloud-init >/dev/null; then
        info "con el user-data bueno:"
        cloud-init schema --config-file "$SILO/user-data" 2>&1 | tee -a "$LOG" | sed 's/^/       | /'
        sed -i 's/^    groups:/  groups:/' "$SILO/user-data"
        info "con el user-data mal indentado:"
        cloud-init schema --config-file "$SILO/user-data" 2>&1 | tee -a "$LOG" | sed 's/^/       | /'
    else
        info "cloud-init no está instalado en el servidor"
    fi
}

case "$FASE" in
    a) fase_a ;;
    *) echo "Fase desconocida: $FASE (de momento, solo a)" >&2; exit 2 ;;
esac

echo
echo "Resultado: $OK bien, $KO mal. Registro completo: $LOG"
[[ "$KO" == 0 ]]
