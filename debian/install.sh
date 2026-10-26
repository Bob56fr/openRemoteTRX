#!/usr/bin/env bash
# Installation de TRX distant sur Debian 12 ou 13 (PC avec bureau). Relançable sans danger :
# une nouvelle exécution répare ou met à jour, sans jamais écraser la configuration.
#
#   sudo bash install.sh                  installe ou met à jour
#   sudo bash install.sh --importer F     reprend la station.toml F d'un autre PC (comptes, alertes, bandes)
#   sudo bash install.sh --desinstaller   désinstalle (la configuration est gardée si tu le demandes)
#
# Une station.toml posée à côté de ce script est importée automatiquement à la première installation.
set -Eeuo pipefail

APP_DIR=/opt/trx-remote
SRC_DIR=$APP_DIR/app
VENV=$APP_DIR/venv
CONF_DIR=/etc/trx-remote
CONF=$CONF_DIR/station.toml
IMPORT=$CONF_DIR/station.import.toml
STATE_DIR=/var/lib/trx-remote
LOG=/var/log/trx-remote-install.log
SERVICE_USER=trx
UNIT_DIR=/etc/systemd/system
UNITS=(rigctld.service trx-gateway.service trx-supervisor.service trx-remote.target)
TMPFILES=/etc/tmpfiles.d/trx-remote.conf
MM_RULE=/etc/udev/rules.d/99-trx-remote-modemmanager.rules
BRLTTY_OVERRIDE=/etc/udev/rules.d/85-brltty.rules
DESKTOP_FILE=/usr/share/applications/trx-console.desktop
ICON_FILE=/usr/share/icons/hicolor/scalable/apps/trx-console.svg
COMMANDS=(trx-console trx-setup trx-monitor trx-hwtest)
APT_PACKAGES=(python3 python3-venv python3-pip python3-dev build-essential pkg-config libffi-dev libssl-dev
              libhamlib-utils alsa-utils libportaudio2 ca-certificates)
MIN_FREE_MB=2000
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TARGET_USER=${SUDO_USER:-}
STEP="préparation"

# ------------------------------------------------------------------ affichage

if [[ -t 1 ]]; then
  GREEN=$'\e[32m'; ORANGE=$'\e[33m'; RED=$'\e[31m'; BOLD=$'\e[1m'; RESET=$'\e[0m'
else
  GREEN=""; ORANGE=""; RED=""; BOLD=""; RESET=""
fi
step()  { STEP=$1; printf '\n%s== %s ==%s\n' "$BOLD" "$1" "$RESET"; }
ok()    { printf '  %s[OK]%s %s\n' "$GREEN" "$RESET" "$1"; }
warn()  { printf '  %s[ATTENTION]%s %s\n' "$ORANGE" "$RESET" "$1"; }
fail()  { printf '  %s[ERREUR]%s %s\n' "$RED" "$RESET" "$1"; printf '\nInstallation arrêtée. Compte-rendu : %s\n' "$LOG"; exit 1; }
on_error() { printf '  %s[ERREUR]%s étape « %s » interrompue (ligne %s). Compte-rendu : %s\n' "$RED" "$RESET" "$STEP" "$1" "$LOG"; }
trap 'on_error $LINENO' ERR

ask_yes() {   # ask_yes "Question" défaut(o/n) : lit au clavier même si la sortie est enregistrée
  local answer="" default=$2
  printf '  %s (%s) : ' "$1" "$([[ $default == o ]] && echo O/n || echo o/N)"
  { read -r answer </dev/tty; } 2>/dev/null || true
  printf '%s\n' "${answer:-$default}"
  answer=${answer:-$default}
  [[ ${answer,,} == o || ${answer,,} == oui || ${answer,,} == y ]]
}

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; }

# ------------------------------------------------------------------ options

MODE=install
IMPORT_SOURCE=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --desinstaller|--uninstall) MODE=uninstall ;;
    --importer) IMPORT_SOURCE=${2:-}; shift ;;
    -h|--aide|--help) usage; exit 0 ;;
    *) printf 'Option inconnue : %s\n' "$1"; usage; exit 2 ;;
  esac
  shift
done

if [[ $EUID -ne 0 ]]; then
  printf 'Cette installation a besoin des droits administrateur. Tape :\n\n    sudo bash install.sh\n\n'
  exit 1
fi
touch "$LOG" && chmod 0644 "$LOG"
exec > >(tee -a "$LOG") 2>&1
printf '\n===== %s : %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$MODE"

TRX_VERSION=$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$HERE/app/pyproject.toml" 2>/dev/null | head -n1)
TRX_VERSION=${TRX_VERSION:-inconnue}

stop_station() {
  if systemctl list-unit-files trx-remote.target >/dev/null 2>&1 && systemctl is-active --quiet trx-remote.target; then
    systemctl stop trx-remote.target && ok "station arrêtée"
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------ désinstallation

uninstall() {
  step "Désinstallation de TRX distant"
  stop_station || true
  for unit in "${UNITS[@]}"; do
    systemctl disable "$unit" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$unit"
  done
  systemctl daemon-reload
  ok "services supprimés"
  for cmd in "${COMMANDS[@]}"; do rm -f "/usr/local/bin/$cmd"; done
  rm -f "$DESKTOP_FILE" "$ICON_FILE" "$TMPFILES" "$MM_RULE"
  if [[ -f $BRLTTY_OVERRIDE ]] && grep -q 'trx-remote' "$BRLTTY_OVERRIDE"; then rm -f "$BRLTTY_OVERRIDE"; fi
  command -v udevadm >/dev/null && udevadm control --reload || true
  command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
  rm -rf "$APP_DIR"
  ok "logiciel, icône et règles USB supprimés"
  if ask_yes "Effacer aussi la configuration (comptes, réglages du poste) et l'état de la station" n; then
    rm -rf "$CONF_DIR" "$STATE_DIR" /run/trx-remote
    userdel "$SERVICE_USER" >/dev/null 2>&1 || true
    groupdel "$SERVICE_USER" >/dev/null 2>&1 || true
    ok "configuration et compte $SERVICE_USER effacés"
  else
    ok "configuration gardée dans $CONF_DIR (réutilisée par une prochaine installation)"
  fi
  printf '\nLes composants Debian (Hamlib, outils audio, Python) sont laissés en place.\n%sDésinstallation terminée.%s\n' "$BOLD" "$RESET"
}

if [[ $MODE == uninstall ]]; then uninstall; exit 0; fi

# ------------------------------------------------------------------ 1. vérifications

step "1/8 Vérifications"
for f in app/pyproject.toml app/trxstation/__init__.py systeme/trx-remote.target; do
  [[ -f $HERE/$f ]] || fail "fichier manquant : $f. Décompresse tout le zip et lance install.sh depuis son dossier."
done
ok "TRX distant version $TRX_VERSION"
# shellcheck disable=SC1091
. /etc/os-release
if [[ " ${ID:-} ${ID_LIKE:-} " != *" debian "* ]]; then
  fail "système non pris en charge : ${PRETTY_NAME:-inconnu}. Debian 12 ou 13 est nécessaire."
fi
if [[ -n ${VERSION_ID:-} && ${VERSION_ID%%.*} =~ ^[0-9]+$ && ${VERSION_ID%%.*} -lt 12 && $ID == debian ]]; then
  fail "${PRETTY_NAME} est trop ancien : Debian 12 ou plus récent est nécessaire."
fi
ok "${PRETTY_NAME:-Debian}"
ARCH=$(dpkg --print-architecture)
case $ARCH in
  amd64|arm64) ok "architecture $ARCH" ;;
  *) warn "architecture $ARCH : certains modules seront compilés, l'installation sera beaucoup plus longue" ;;
esac
FREE_MB=$(df --output=avail -BM / | tail -n1 | tr -dc '0-9')
[[ ${FREE_MB:-0} -ge $MIN_FREE_MB ]] || fail "espace disque insuffisant : ${FREE_MB:-0} Mo libres, $MIN_FREE_MB Mo nécessaires."
ok "espace disque : ${FREE_MB} Mo libres"
for host in deb.debian.org pypi.org files.pythonhosted.org; do
  getent hosts "$host" >/dev/null || fail "pas d'accès à $host : vérifie la connexion Internet."
done
ok "connexion Internet"
if [[ -z $TARGET_USER || $TARGET_USER == root ]]; then
  warn "lancé sans sudo depuis un compte utilisateur : aucun compte n'aura accès aux ports série pour les tests"
  TARGET_USER=""
else
  ok "compte utilisateur : $TARGET_USER"
fi
WAS_RUNNING=0
stop_station && WAS_RUNNING=1 || true

# ------------------------------------------------------------------ 2. paquets Debian

step "2/8 Composants Debian (Hamlib, audio, Python)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q || fail "mise à jour de la liste des paquets impossible (apt-get update)."
apt-get install -y -q --no-install-recommends "${APT_PACKAGES[@]}" || fail "installation des paquets Debian impossible."
ok "paquets installés"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11 ou plus récent est nécessaire (Debian 12 et plus)."
ok "$(python3 --version) ; $(rigctld --version 2>/dev/null | head -n1 || echo 'rigctld présent')"

# ------------------------------------------------------------------ 3. comptes

step "3/8 Comptes et droits"
if ! getent passwd "$SERVICE_USER" >/dev/null; then
  useradd --system --user-group --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin \
          --comment "Station TRX distant" "$SERVICE_USER"
  ok "compte système $SERVICE_USER créé"
else
  ok "compte système $SERVICE_USER déjà présent"
fi
usermod -aG dialout,audio "$SERVICE_USER"
ok "$SERVICE_USER : accès aux ports série et au son"
if [[ -n $TARGET_USER ]]; then
  groups_to_add=dialout,audio,$SERVICE_USER
  getent group systemd-journal >/dev/null && groups_to_add+=,systemd-journal
  usermod -aG "$groups_to_add" "$TARGET_USER"
  ok "$TARGET_USER : ports série, son, configuration et journaux (actif après déconnexion et reconnexion)"
fi

# ------------------------------------------------------------------ 4. logiciel

step "4/8 Logiciel TRX distant (environnement Python isolé)"
install -d -m 0755 "$APP_DIR"
rm -rf "$SRC_DIR"
cp -r "$HERE/app" "$SRC_DIR"
find "$SRC_DIR" -name '__pycache__' -prune -exec rm -rf {} +
SYS_PY=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
VENV_PY=$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
if [[ $VENV_PY != "$SYS_PY" ]]; then
  python3 -m venv --clear "$VENV"
  ok "environnement Python $SYS_PY créé dans $VENV"
else
  ok "environnement Python $SYS_PY réutilisé"
fi
printf '  Téléchargement et installation des modules Python (de 2 à 10 minutes)...\n'
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip setuptools wheel \
  || fail "mise à jour de pip impossible."
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check "$SRC_DIR[station]" \
  || fail "installation des modules Python impossible (détails dans $LOG)."
"$VENV/bin/python" -c 'import trxstation, aiohttp, aiortc, sounddevice, cryptography' \
  || fail "modules Python incomplets après installation."
ok "modules Python installés (aiortc, aiohttp, sounddevice, textual, cryptography)"
for cmd in "${COMMANDS[@]}"; do ln -sf "$VENV/bin/$cmd" "/usr/local/bin/$cmd"; done
ok "commandes disponibles : ${COMMANDS[*]}"

# ------------------------------------------------------------------ 5. configuration

step "5/8 Configuration"
install -d -m 0755 -o root -g "$SERVICE_USER" "$CONF_DIR"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONF_DIR/tls"
for f in "$CONF" "$CONF.bak" "$IMPORT"; do
  [[ -f $f ]] && chown root:"$SERVICE_USER" "$f" && chmod 0640 "$f"
done
find "$CONF_DIR/tls" -type f -exec chown root:"$SERVICE_USER" {} + -exec chmod 0640 {} +
if [[ -z $IMPORT_SOURCE && -f $HERE/station.toml ]]; then IMPORT_SOURCE=$HERE/station.toml; fi
if [[ -f $CONF ]]; then
  ok "configuration existante conservée : $CONF"
  [[ -n $IMPORT_SOURCE ]] && warn "import de $IMPORT_SOURCE ignoré : une configuration existe déjà"
elif [[ -n $IMPORT_SOURCE ]]; then
  [[ -f $IMPORT_SOURCE ]] || fail "fichier à importer introuvable : $IMPORT_SOURCE"
  "$VENV/bin/python" -m trxstation.migrate "$IMPORT_SOURCE" "$IMPORT" \
    || fail "import de $IMPORT_SOURCE impossible."
  chown root:"$SERVICE_USER" "$IMPORT" && chmod 0640 "$IMPORT"
  ok "configuration de l'ancien PC prête à être complétée par l'assistant"
else
  ok "pas encore de configuration : l'assistant de TRX Console la créera"
fi

# ------------------------------------------------------------------ 6. ports USB

step "6/8 Ports USB du poste"
install -D -m 0644 "$HERE/systeme/99-trx-remote-modemmanager.rules" "$MM_RULE"
ok "ModemManager ignorera les ports série USB"
BRLTTY_RULE=""
for dir in /usr/lib/udev/rules.d /lib/udev/rules.d; do
  [[ -f $dir/85-brltty.rules ]] && BRLTTY_RULE=$dir/85-brltty.rules && break
done
if [[ -n $BRLTTY_RULE && ! -f $BRLTTY_OVERRIDE ]]; then
  if ask_yes "Utilises-tu un afficheur braille sur ce PC" n; then
    warn "brltty laissé actif : il peut s'approprier certains adaptateurs USB série (CP210x, CH340)"
  else
    install -d -m 0755 "$(dirname "$BRLTTY_OVERRIDE")"
    printf '# trx-remote : règles brltty désactivées (elles capturent les adaptateurs série USB des postes radio).\n' >"$BRLTTY_OVERRIDE"
    ok "brltty ne capturera plus les adaptateurs série USB"
  fi
elif [[ -f $BRLTTY_OVERRIDE ]]; then
  ok "brltty déjà neutralisé"
fi
udevadm control --reload && udevadm trigger --subsystem-match=tty || warn "rechargement des règles USB impossible : redémarre le PC"

# ------------------------------------------------------------------ 7. services

step "7/8 Services de la station"
install -D -m 0644 "$HERE/systeme/trx-remote-tmpfiles.conf" "$TMPFILES"
systemd-tmpfiles --create "$TMPFILES"
for unit in "${UNITS[@]}"; do install -D -m 0644 "$HERE/systeme/$unit" "$UNIT_DIR/$unit"; done
systemctl daemon-reload
systemctl enable "${UNITS[@]}" >/dev/null 2>&1
ok "services enregistrés, démarrage automatique avec le PC"
if [[ -f $CONF ]] && "$VENV/bin/python" -c "from trxstation import config; config.load('$CONF')" 2>/dev/null; then
  if systemctl restart trx-remote.target; then
    ok "station démarrée"
  else
    warn "la station n'a pas démarré : TRX Console, menus « Diagnostic » et « Journal »"
  fi
elif [[ -f $CONF ]]; then
  warn "configuration incomplète : la station démarrera après l'assistant de TRX Console"
else
  ok "la station démarrera après l'assistant de TRX Console"
fi
[[ $WAS_RUNNING -eq 1 && ! -f $CONF ]] && warn "la station tournait avant la mise à jour mais n'a plus de configuration"

# ------------------------------------------------------------------ 8. lanceur

step "8/8 Lanceur TRX Console"
install -D -m 0644 "$HERE/systeme/trx-console.desktop" "$DESKTOP_FILE"
install -D -m 0644 "$HERE/systeme/trx-console.svg" "$ICON_FILE"
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
ok "icône « TRX Console » ajoutée au menu des applications"

printf '\n%s%sInstallation terminée%s (TRX distant %s).\n' "$GREEN" "$BOLD" "$RESET" "$TRX_VERSION"
if [[ -n $TARGET_USER ]]; then
  printf '\nÀ faire maintenant :\n  1. Déconnecte-toi puis reconnecte-toi (les nouveaux droits ne valent qu'\''après).\n'
  printf '  2. Ouvre « TRX Console » depuis le menu des applications.\n'
else
  printf '\nOuvre « TRX Console » depuis le menu des applications.\n'
fi
printf '\nCompte-rendu complet : %s\n' "$LOG"
