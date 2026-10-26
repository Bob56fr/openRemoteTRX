#!/usr/bin/env bash
# Installation de TRX distant sur Debian 12 ou 13 (PC avec bureau). Relançable sans danger :
# une nouvelle exécution répare ou met à jour, sans jamais écraser la configuration.
#
#   sudo bash install.sh                  installe ou met à jour (la version d'avant est gardée)
#   sudo bash install.sh --importer F     reprend la station.toml F d'un autre PC (comptes, alertes, bandes)
#   sudo bash install.sh --desinstaller   désinstalle (la configuration est gardée si tu le demandes)
#   sudo bash /opt/trx-remote/previous/install.sh --reactiver   revient à la version précédente, sans réseau
#
# Une station.toml posée à côté de ce script est importée automatiquement à la première installation.
set -Eeuo pipefail

APP_DIR=/opt/trx-remote
CONF_DIR=/etc/trx-remote
CONF=$CONF_DIR/station.toml
IMPORT=$CONF_DIR/station.import.toml
STATE_DIR=/var/lib/trx-remote
LOG=/var/log/trx-remote-install.log
SERVICE_USER=trx
UNIT_DIR=/etc/systemd/system
UNITS=(rigctld.service trx-gateway.service trx-supervisor.service trx-update-check.timer trx-remote.target)
HELPER_UNITS=(trx-update-check.service)   # lancées par un timer : copiées, jamais activées
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

if [[ ! -f $HERE/releases.sh ]]; then
  printf 'Fichier manquant : releases.sh. Décompresse tout le zip et lance install.sh depuis son dossier.\n'
  exit 1
fi
# shellcheck source=releases.sh
. "$HERE/releases.sh"          # RELEASES, CURRENT_LINK, PREVIOUS_LINK, VENV, activate_release...

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

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

# ------------------------------------------------------------------ options

MODE=install
IMPORT_SOURCE=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --desinstaller|--uninstall) MODE=uninstall ;;
    --reactiver) MODE=reactivate ;;
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

config_loads() {   # config_loads [FICHIER] : vrai si la version active accepte cette configuration
  "$VENV/bin/python" -c 'import sys; from trxstation import config; config.load(sys.argv[1])' "${1:-$CONF}" 2>/dev/null
}

# ------------------------------------------------------------------ sortie en cours de route

WAS_RUNNING=0
BUILDING=0          # 1 : releases/$TRX_VERSION est neuve et pas encore active (à retirer si on s'arrête)
FINISHED=0
on_exit() {
  [[ $FINISHED -eq 1 || $MODE == uninstall ]] && return 0
  if [[ $BUILDING -eq 1 && $(release_of "$CURRENT_LINK") != "$TRX_VERSION" ]]; then
    rm -rf "${RELEASES:?}/$TRX_VERSION"
    printf '  Version %s incomplète retirée : la version active reste inchangée.\n' "$TRX_VERSION"
  fi
  if [[ $WAS_RUNNING -eq 1 && -x $VENV/bin/python ]] && config_loads; then
    systemctl start trx-remote.target && printf '  Station relancée sur la version active.\n' || true
  fi
}
trap on_exit EXIT

# ------------------------------------------------------------------ services et lanceur (installation et retour arrière)

install_services() {   # units de la version active (dossier systeme/ donné), activées au démarrage
  local src=$1 unit
  install -D -m 0644 "$src/trx-remote-tmpfiles.conf" "$TMPFILES"
  systemd-tmpfiles --create "$TMPFILES"
  for unit in "${UNITS[@]}" "${HELPER_UNITS[@]}"; do install -D -m 0644 "$src/$unit" "$UNIT_DIR/$unit"; done
  systemctl daemon-reload
  systemctl enable "${UNITS[@]}" >/dev/null 2>&1
  ok "services enregistrés, démarrage automatique avec le PC (recherche de mise à jour : au démarrage puis toutes les 24 h)"
}

start_if_configured() {
  if [[ -f $CONF ]] && config_loads; then
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
}

install_launcher() {
  local src=$1 cmd
  for cmd in "${COMMANDS[@]}"; do ln -sf "$VENV/bin/$cmd" "/usr/local/bin/$cmd"; done
  install -D -m 0644 "$src/trx-console.desktop" "$DESKTOP_FILE"
  install -D -m 0644 "$src/trx-console.svg" "$ICON_FILE"
  command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
}

backup_config_for() {  # copie de station.toml prise avant de passer à la version $1 (retour arrière)
  [[ -f $CONF ]] || return 0
  cp -p "$CONF" "$CONF_DIR/station.toml.avant-$1"
  chown root:"$SERVICE_USER" "$CONF_DIR/station.toml.avant-$1" && chmod 0640 "$CONF_DIR/station.toml.avant-$1"
  local f keep_cur keep_prev
  keep_cur=$(release_of "$CURRENT_LINK"); keep_prev=$(release_of "$PREVIOUS_LINK")
  for f in "$CONF_DIR"/station.toml.avant-*; do
    [[ -f $f ]] || continue
    case ${f##*.avant-} in "$1"|"$keep_cur"|"$keep_prev") ;; *) rm -f "$f" ;; esac
  done
}

# ------------------------------------------------------------------ désinstallation

uninstall() {
  step "Désinstallation de TRX distant"
  stop_station || true
  for unit in "${UNITS[@]}"; do
    systemctl disable "$unit" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$unit"
  done
  for unit in "${HELPER_UNITS[@]}"; do rm -f "$UNIT_DIR/$unit"; done
  systemctl daemon-reload
  ok "services supprimés"
  for cmd in "${COMMANDS[@]}"; do rm -f "/usr/local/bin/$cmd"; done
  rm -f "$DESKTOP_FILE" "$ICON_FILE" "$TMPFILES" "$MM_RULE"
  if [[ -f $BRLTTY_OVERRIDE ]] && grep -q 'trx-remote' "$BRLTTY_OVERRIDE"; then rm -f "$BRLTTY_OVERRIDE"; fi
  command -v udevadm >/dev/null && udevadm control --reload || true
  command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
  rm -rf "$APP_DIR"
  ok "logiciel (toutes les versions), icône et règles USB supprimés"
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

# ------------------------------------------------------------------ retour à une version déjà installée (sans réseau)

reactivate() {
  step "Retour à la version $TRX_VERSION"
  valid_version "$TRX_VERSION" || fail "version illisible dans $HERE/app/pyproject.toml"
  [[ $HERE == "$RELEASES/$TRX_VERSION" ]] \
    || fail "--reactiver se lance depuis $RELEASES/<version>/install.sh (version déjà installée)"
  local left
  left=$(release_of "$CURRENT_LINK")
  [[ $left != "$TRX_VERSION" ]] || fail "la version $TRX_VERSION est déjà la version active"
  "$HERE/venv/bin/python" -c 'import trxstation, aiohttp, aiortc, sounddevice, cryptography' 2>/dev/null \
    || fail "environnement Python de la version $TRX_VERSION abîmé : réinstalle-la depuis son zip"
  stop_station && WAS_RUNNING=1 || true
  activate_release "$TRX_VERSION" || fail "activation de la version $TRX_VERSION impossible"
  ok "version $TRX_VERSION active (version $left gardée comme précédente)"
  if [[ -f $CONF ]] && ! config_loads; then
    local backup=$CONF_DIR/station.toml.avant-$left
    if [[ -f $backup ]] && config_loads "$backup"; then
      cp -p "$CONF" "$CONF_DIR/station.toml.version-$left"
      cp -p "$backup" "$CONF"
      chown root:"$SERVICE_USER" "$CONF" "$CONF_DIR/station.toml.version-$left"
      chmod 0640 "$CONF" "$CONF_DIR/station.toml.version-$left"
      warn "configuration refusée par la version $TRX_VERSION : celle d'avant la mise à jour est remise (l'autre est gardée dans station.toml.version-$left)"
    else
      warn "configuration refusée par la version $TRX_VERSION : TRX Console, menu « Assistant de configuration »"
    fi
  fi
  install_services "$HERE/systeme"
  install_launcher "$HERE/systeme"
  FINISHED=1
  start_if_configured
  printf '\n%s%sRetour terminé%s (TRX distant %s).\n' "$GREEN" "$BOLD" "$RESET" "$TRX_VERSION"
}

if [[ $MODE == reactivate ]]; then reactivate; exit 0; fi

# ------------------------------------------------------------------ 1. vérifications

step "1/8 Vérifications"
for f in app/pyproject.toml app/trxstation/__init__.py systeme/trx-remote.target; do
  [[ -f $HERE/$f ]] || fail "fichier manquant : $f. Décompresse tout le zip et lance install.sh depuis son dossier."
done
valid_version "$TRX_VERSION" || fail "version illisible dans app/pyproject.toml : $TRX_VERSION"
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
CURRENT_VERSION=$(release_of "$CURRENT_LINK")
if [[ -n $CURRENT_VERSION && $CURRENT_VERSION != "$TRX_VERSION" ]]; then
  ok "mise à jour : $CURRENT_VERSION -> $TRX_VERSION (la version $CURRENT_VERSION est gardée pour un retour arrière)"
elif legacy_layout; then
  ok "mise à jour d'une installation d'avant la 0.23.0 (pas de retour arrière possible vers elle)"
fi
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
RELEASE=$RELEASES/$TRX_VERSION
install -d -m 0755 "$APP_DIR" "$RELEASES"
if [[ $HERE != "$RELEASE" ]]; then
  [[ $(release_of "$PREVIOUS_LINK") == "$TRX_VERSION" ]] && rm -f "$PREVIOUS_LINK"
  if [[ $TRX_VERSION != "$CURRENT_VERSION" ]]; then
    rm -rf "$RELEASE"
    BUILDING=1
  fi
  install -d -m 0755 "$RELEASE"
  rm -rf "$RELEASE/app" "$RELEASE/systeme"
  cp -r "$HERE/app" "$HERE/systeme" "$RELEASE/"
  install -m 0755 "$HERE/install.sh" "$RELEASE/install.sh"
  install -m 0644 "$HERE/releases.sh" "$RELEASE/releases.sh"
  install -m 0644 "$HERE/LISEZMOI.txt" "$RELEASE/LISEZMOI.txt"
fi
find "$RELEASE" -name '__pycache__' -prune -exec rm -rf {} +
REL_VENV=$RELEASE/venv
SYS_PY=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
VENV_PY=$("$REL_VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
if [[ $VENV_PY != "$SYS_PY" ]]; then
  python3 -m venv --clear "$REL_VENV"
  ok "environnement Python $SYS_PY créé dans $REL_VENV"
else
  ok "environnement Python $SYS_PY réutilisé"
fi
printf '  Téléchargement et installation des modules Python (de 2 à 10 minutes)...\n'
"$REL_VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip setuptools wheel \
  || fail "mise à jour de pip impossible."
"$REL_VENV/bin/python" -m pip install --quiet --disable-pip-version-check "$RELEASE/app[station]" \
  || fail "installation des modules Python impossible (détails dans $LOG)."
"$REL_VENV/bin/python" -c 'import trxstation, aiohttp, aiortc, sounddevice, cryptography' \
  || fail "modules Python incomplets après installation."
ok "modules Python installés (aiortc, aiohttp, sounddevice, textual, cryptography)"
if [[ -n $CURRENT_VERSION && $CURRENT_VERSION != "$TRX_VERSION" ]]; then backup_config_for "$TRX_VERSION"; fi
activate_release "$TRX_VERSION" || fail "activation de la version $TRX_VERSION impossible."
BUILDING=0
PREVIOUS_VERSION=$(release_of "$PREVIOUS_LINK")
ok "version $TRX_VERSION active${PREVIOUS_VERSION:+ (version précédente gardée : $PREVIOUS_VERSION)}"
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
install_services "$HERE/systeme"
FINISHED=1
start_if_configured
[[ $WAS_RUNNING -eq 1 && ! -f $CONF ]] && warn "la station tournait avant la mise à jour mais n'a plus de configuration"

# ------------------------------------------------------------------ 8. lanceur

step "8/8 Lanceur TRX Console"
install_launcher "$HERE/systeme"
ok "icône « TRX Console » ajoutée au menu des applications"

printf '\n%s%sInstallation terminée%s (TRX distant %s).\n' "$GREEN" "$BOLD" "$RESET" "$TRX_VERSION"
if [[ -n $TARGET_USER ]]; then
  printf '\nÀ faire maintenant :\n  1. Déconnecte-toi puis reconnecte-toi (les nouveaux droits ne valent qu'\''après).\n'
  printf '  2. Ouvre « TRX Console » depuis le menu des applications.\n'
else
  printf '\nOuvre « TRX Console » depuis le menu des applications.\n'
fi
printf '\nCompte-rendu complet : %s\n' "$LOG"
