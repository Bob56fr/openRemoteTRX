#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Compile et installe une version récente de Hamlib dans /usr/local, quand celle de Debian ou de Raspberry Pi OS
# ne connaît pas le poste (ex. IC-7300MK2, modèle 3094, absent avant Hamlib 4.7). Sur Debian 13 (trixie),
# install.sh prend d'abord Hamlib 4.7 dans les backports officiels : ce script ne sert alors que pour une version
# plus récente que celle des backports, ou sur Debian 12. La station prend le rigctld
# trouvé en premier dans le PATH : /usr/local/bin passe avant /usr/bin, le paquet Debian reste en place.
#
#   sudo bash compiler-hamlib.sh            compile la version prévue (de 10 à 30 minutes sur un Raspberry Pi 4)
#   sudo bash compiler-hamlib.sh --force    recompile même si cette version est déjà installée
#
# L'archive téléchargée est vérifiée par son empreinte SHA-256 (publiée par Hamlib) avant toute compilation.
set -Eeuo pipefail

HAMLIB_VERSION=4.7.2
HAMLIB_SHA256=ae1fcf2dbc80ea0786ea8f047b09399c3f7737d1930442f61a031708ed33e88f
HAMLIB_URL=https://github.com/Hamlib/Hamlib/releases/download/$HAMLIB_VERSION/hamlib-$HAMLIB_VERSION.tar.gz
PREFIX=/usr/local
BUILD_PACKAGES=(build-essential pkg-config curl ca-certificates libusb-1.0-0-dev)

fail() { printf '  [ERREUR] %s\n' "$1"; exit 1; }
ok()   { printf '  [OK] %s\n' "$1"; }

FORCE=0
case ${1:-} in
  --force) FORCE=1 ;;
  "") ;;
  *) printf 'Option inconnue : %s\n' "$1"; sed -n '10,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
[[ $EUID -eq 0 ]] || { printf 'Droits administrateur nécessaires. Tape :\n\n    sudo bash compiler-hamlib.sh\n\n'; exit 1; }

current=$("$PREFIX/bin/rigctld" --version 2>/dev/null | head -n1 || true)
if [[ $FORCE -eq 0 && $current == *" $HAMLIB_VERSION"* ]]; then
  ok "Hamlib $HAMLIB_VERSION déjà installé dans $PREFIX ($current)"
  exit 0
fi

printf '== Composants de compilation ==\n'
apt-get update -q || fail "mise à jour de la liste des paquets impossible"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${BUILD_PACKAGES[@]}" \
  || fail "installation des composants de compilation impossible"

WORK=$(mktemp -d /tmp/hamlib-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
printf '== Téléchargement de Hamlib %s ==\n' "$HAMLIB_VERSION"
curl -fsSL -o hamlib.tar.gz "$HAMLIB_URL" || fail "téléchargement impossible : $HAMLIB_URL"
echo "$HAMLIB_SHA256  hamlib.tar.gz" | sha256sum -c --quiet - \
  || fail "empreinte SHA-256 incorrecte : archive refusée, rien n'est installé"
ok "archive vérifiée (SHA-256)"
tar xzf hamlib.tar.gz
cd "hamlib-$HAMLIB_VERSION"

printf '== Compilation (de 10 à 30 minutes sur un Raspberry Pi 4) ==\n'
# RUNPATH vers $PREFIX/lib : sans lui, le rigctld neuf chargeait la libhamlib.so.4 du paquet Debian (même nom,
# version 4.6.2 relevée sur Raspberry Pi OS, étape 93) et répondait « Hamlib 4.6.2 ».
./configure --prefix="$PREFIX" --disable-static --without-cxx-binding \
            LDFLAGS="-Wl,-rpath,$PREFIX/lib -Wl,--enable-new-dtags" >configure.log 2>&1 \
  || { tail -n 30 configure.log; fail "configure a échoué"; }
make -j"$(nproc)" >make.log 2>&1 || { tail -n 30 make.log; fail "la compilation a échoué"; }
make install >install.log 2>&1 || { tail -n 30 install.log; fail "l'installation a échoué"; }
ldconfig
hash -r

installed=$("$PREFIX/bin/rigctld" --version 2>/dev/null | head -n1 || true)
[[ $installed == *" $HAMLIB_VERSION"* ]] || fail "rigctld de $PREFIX ne répond pas comme prévu : « $installed »"
ok "$installed installé dans $PREFIX/bin"
found=$(command -v rigctld)
[[ $found == "$PREFIX/bin/rigctld" ]] || printf '  [ATTENTION] le PATH trouve d'\''abord %s\n' "$found"

if systemctl is-active --quiet trx-remote.target 2>/dev/null; then
  systemctl restart rigctld.service && ok "rigctld de la station relancé avec Hamlib $HAMLIB_VERSION"
fi
printf '\nVérifie ton poste dans la liste : rigctl -l | grep -i <nom du poste>\n'
