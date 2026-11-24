#!/bin/bash
# Installation von Moonraker LCD Status auf dem Raspberry Pi.
#
#   ./install.sh                  normale Installation
#   ./install.sh --no-service     nur venv und Konfiguration, kein systemd
#   ./install.sh --instance NAME  weiteres Display mit eigener Konfiguration
#
set -eu

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Das Paket ist nicht ins venv installiert und wird nur im Projektordner gefunden.
cd "$SRC_DIR"
VENV_DIR="${VENV_DIR:-${HOME}/moonraker-lcd-env}"
NAME="moonraker-lcd"
WITH_SERVICE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --no-service) WITH_SERVICE=0 ;;
        --instance)
            case "${2:-}" in
                ""|*[!a-zA-Z0-9_-]*) echo "--instance braucht einen Namen (a-z, 0-9, - und _)" >&2; exit 2 ;;
            esac
            NAME="moonraker-lcd-$2"
            shift
            ;;
        -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ "$(id -u)" = "0" ]; then
    echo "Bitte nicht als root starten - das Skript ruft sudo selbst auf." >&2
    exit 1
fi
case "$SRC_DIR$VENV_DIR" in
    *" "*) echo "Der Projektordner darf auf dem Pi kein Leerzeichen enthalten: $SRC_DIR" >&2; exit 1 ;;
esac

info() { printf '\n== %s\n' "$1"; }

CONFIG_DIR=""
for candidate in "${HOME}/printer_data/config" "${HOME}/klipper_config"; do
    if [ -d "$candidate" ]; then CONFIG_DIR="$candidate"; break; fi
done
if [ -z "$CONFIG_DIR" ]; then
    CONFIG_DIR="${HOME}/printer_data/config"
    mkdir -p "$CONFIG_DIR"
fi
CONFIG_FILE="${CONFIG_DIR}/${NAME}.conf"

# ---------------------------------------------------------------- Pakete

info "Systempakete pruefen"
MISSING=""
for pkg in python3-venv python3-pip; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then MISSING="$MISSING $pkg"; fi
done
if [ -n "$MISSING" ]; then
    echo "installiere:$MISSING"
    sudo apt-get update
    # shellcheck disable=SC2086
    sudo apt-get install -y $MISSING
else
    echo "alles vorhanden"
fi

info "Virtuelle Umgebung: ${VENV_DIR}"
if [ ! -d "$VENV_DIR" ]; then python3 -m venv "$VENV_DIR"; fi
"${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
"${VENV_DIR}/bin/pip" install -r "${SRC_DIR}/requirements.txt"

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
    info "Benutzer ${USER} der Gruppe dialout hinzufuegen"
    sudo usermod -aG dialout "$USER"
    echo "Hinweis: fuer die eigene Shell erst nach dem naechsten Login wirksam."
fi

# ---------------------------------------------------------------- Konfiguration

# Der Port wird bewusst NICHT geraten. An einem Drucker haengen weitere
# serielle Geraete (Klipper-MCUs, andere Arduinos); CH340-Nachbauten lassen sich
# unter /dev/serial/by-id nicht einmal zaehlen, weil sich alle denselben Namen
# teilen.
info "Konfiguration: ${CONFIG_FILE}"
if [ -f "$CONFIG_FILE" ]; then
    echo "bleibt unveraendert (vorhanden)"
else
    cp "${SRC_DIR}/config/moonraker-lcd.conf" "$CONFIG_FILE"
    echo "angelegt"
fi

CONFIGURED_PORT="$(sed -n 's/^port[[:space:]]*=[[:space:]]*//p' "$CONFIG_FILE" | head -n 1 | sed 's/[[:space:]]*#.*$//')"
PORT_OK=0
if [ -n "$CONFIGURED_PORT" ] && [ -e "$CONFIGURED_PORT" ]; then PORT_OK=1; fi

"${VENV_DIR}/bin/python" -m moonraker_lcd --config "$CONFIG_FILE" config

if [ "$PORT_OK" = "0" ]; then
    info "Port des Display-Arduino"
    echo "[serial] port in ${CONFIG_FILE}"
    echo "zeigt auf kein vorhandenes Geraet (aktuell: '${CONFIGURED_PORT}')."
    echo "So findest du den richtigen Eintrag: Arduino abziehen, Befehl ausfuehren,"
    echo "Arduino anstecken, nochmals ausfuehren - der neue Eintrag ist es."
    echo
    "${VENV_DIR}/bin/python" -m moonraker_lcd --config "$CONFIG_FILE" ports || true
fi

# ---------------------------------------------------------------- systemd

if [ "$WITH_SERVICE" = "1" ]; then
    info "systemd-Dienst ${NAME}"
    TMP_UNIT="$(mktemp)"
    sed -e "s|__USER__|${USER}|g" -e "s|__DIR__|${SRC_DIR}|g" -e "s|__NAME__|${NAME}|g" \
        -e "s|__PYTHON__|${VENV_DIR}/bin/python|g" -e "s|__CONFIG__|${CONFIG_FILE}|g" \
        "${SRC_DIR}/scripts/moonraker-lcd.service" > "$TMP_UNIT"
    sudo install -m 644 "$TMP_UNIT" "/etc/systemd/system/${NAME}.service"
    rm -f "$TMP_UNIT"
    sudo systemctl daemon-reload
    sudo systemctl enable "${NAME}.service"
    if [ "$PORT_OK" = "1" ]; then
        sudo systemctl restart "${NAME}.service"
        sleep 3
        sudo systemctl --no-pager --lines=15 status "${NAME}.service" || true
    else
        echo "installiert, aber NICHT gestartet (Port fehlt)."
    fi
fi

# ---------------------------------------------------------------- Abschluss

ORIGIN_URL=""
if command -v git >/dev/null 2>&1; then
    ORIGIN_URL="$(git -C "$SRC_DIR" remote get-url origin 2>/dev/null || true)"
fi
ORIGIN_URL="${ORIGIN_URL:-<git-url-dieses-repos>}"

cat <<END

== Fertig

Konfiguration : ${CONFIG_FILE}
Logs          : journalctl -u ${NAME} -f

Port eintragen, pruefen und starten:
  nano ${CONFIG_FILE}
  cd ${SRC_DIR}
  sudo systemctl stop ${NAME}
  ${VENV_DIR}/bin/python -m moonraker_lcd --config ${CONFIG_FILE} identify
  sudo systemctl start ${NAME}

Fuer Updates ueber Mainsail/Fluidd in moonraker.conf ergaenzen:

  [update_manager moonraker-lcd]
  type: git_repo
  path: ${SRC_DIR}
  origin: ${ORIGIN_URL}
  primary_branch: main
  virtualenv: ${VENV_DIR}
  requirements: requirements.txt
  managed_services: ${NAME}

Den Dienst fuer Moonraker freigeben (einmalig) und Moonraker neu starten:
  echo ${NAME} >> $(dirname "$CONFIG_DIR")/moonraker.asvc
  sudo systemctl restart moonraker

Das Update betrifft nur die Software auf dem Pi. Meldet das Display
"Sketch veraltet", den Sketch aus arduino/ neu hochladen.
END
