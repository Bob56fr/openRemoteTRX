#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Compile les deux décodeurs FreeDV RADE V1 utilisés par la station en réception (trxstation/freedv/) :
# freedv-ka9q (freedv-integrations : voix décodée et indicatif) et radae_rx (rade_c : synchro, SNR, décalage).
# Sources ÉPINGLÉES (commits complets vérifiés, archive d'Opus vérifiée par SHA-256 ; les modèles d'Opus et de
# RNNoise sont vérifiés par leurs propres scripts), correctifs de freedv-patches/ appliqués avant la compilation.
#
#   sudo bash compiler-freedv.sh               compile et installe dans /usr/local/lib/trx-freedv (liens dans
#                                               /usr/local/bin : la station les trouve sans rien régler)
#   sudo bash compiler-freedv.sh --force       recompile même si cette version est déjà installée
#   sudo bash compiler-freedv.sh --retirer     retire les décodeurs installés par ce script
#   bash compiler-freedv.sh --prefix DOSSIER   essai sans sudo : installe dans DOSSIER/lib/trx-freedv et DOSSIER/bin
#   bash compiler-freedv.sh --windows DOSSIER  compilation croisée pour le paquet Windows (MinGW, depuis Debian) :
#                                               exécutables, DLL, licences et SHA256SUMS dans DOSSIER
#
# Durée : ~5 minutes sur un PC récent, 30 à 60 minutes sur un Raspberry Pi 4 (non essayé).
set -Eeuo pipefail

# --- Versions épinglées (lot F0 du 2026-11-10/11, validées sous Debian et Windows) -----------------------------
RADE_C_REPO=https://github.com/freedv/rade_c.git
RADE_C_COMMIT=c8a3dc156045cae2cd251e1a4be0c304c9ddf2f9            # rade_c, 2026-11 (CI macOS)
INTEG_REPO=https://github.com/freedv/freedv-integrations.git
INTEG_COMMIT=ec6407754f024319eac9cea115c258f46bed1d98             # freedv-integrations v2.4.1
BACKEND_COMMIT=5dd2c52faac68273824cfd5d65cb905770cb5e0a           # sous-module src/backend (freedv-backend v1.0.1)
EBUR128_COMMIT=67b33abe1558160ed76ada1322329b0e9e058b02           # libebur128 v1.2.6 (étiquette remplacée par le commit)
OPUS_COMMIT=940d4e5af64351ca8ba8390df3f555484c567fbb
OPUS_URL=https://github.com/xiph/opus/archive/$OPUS_COMMIT.zip
OPUS_SHA256=20e37f9079ac2b80e3235cd8ce2547829e147bf44a2f5dd28a888fa3e9c24341
FREEDV_BUILD_ID="rade_c ${RADE_C_COMMIT:0:7} + freedv-integrations ${INTEG_COMMIT:0:7} (v2.4.1), correctifs trx-remote 1"

BUILD_PACKAGES=(build-essential cmake git autoconf automake libtool pkg-config curl wget ca-certificates unzip python3)
LINUX_PACKAGES=(patchelf)                                        # RUNPATH des exécutables installés
WIN_PACKAGES=(g++-mingw-w64-x86-64-posix gcc-mingw-w64-x86-64-posix binutils-mingw-w64-x86-64)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PATCHES=$HERE/freedv-patches

fail() { printf '  [ERREUR] %s\n' "$1"; exit 1; }
ok()   { printf '  [OK] %s\n' "$1"; }
usage() { sed -n '9,16p' "$0" | sed 's/^# \{0,1\}//'; }

MODE=system FORCE=0 PREFIX=/usr/local OUT=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --force) FORCE=1 ;;
    --retirer) MODE=remove ;;
    --prefix) [[ $# -ge 2 ]] || { usage; exit 2; }; MODE=prefix PREFIX=$(realpath -m "$2"); shift ;;
    --windows) [[ $# -ge 2 ]] || { usage; exit 2; }; MODE=windows OUT=$(realpath -m "$2"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Option inconnue : %s\n' "$1"; usage; exit 2 ;;
  esac
  shift
done
DEST=$PREFIX/lib/trx-freedv
BIN=$PREFIX/bin

if [[ $MODE == system || $MODE == remove ]]; then
  [[ $EUID -eq 0 ]] || { printf 'Droits administrateur nécessaires. Tape :\n\n    sudo bash compiler-freedv.sh\n\n'; exit 1; }
fi

remove_installed() {
  for name in freedv-ka9q radae_rx; do
    if [[ -L $BIN/$name && $(readlink "$BIN/$name") == "$DEST/$name" ]]; then rm -f "$BIN/$name"; fi
  done
  rm -rf "$DEST" "$DEST.new" "$DEST.old"
}

if [[ $MODE == remove ]]; then
  remove_installed
  ok "décodeurs FreeDV retirés de $DEST"
  exit 0
fi

if [[ $MODE != windows && $FORCE -eq 0 && -f $DEST/VERSION && $(head -n1 "$DEST/VERSION") == "$FREEDV_BUILD_ID" ]]; then
  ok "décodeurs FreeDV déjà installés dans $DEST ($FREEDV_BUILD_ID)"
  exit 0
fi

for p in radae_rx-windows-binary-stdin.patch freedv-ka9q-windows-stdin.patch; do
  [[ -f $PATCHES/$p ]] || fail "correctif absent : $PATCHES/$p (le dossier freedv-patches doit être à côté du script)"
done

# --- Outils de compilation --------------------------------------------------------------------------------------
need=("${BUILD_PACKAGES[@]}")
if [[ $MODE == windows ]]; then need+=("${WIN_PACKAGES[@]}"); else need+=("${LINUX_PACKAGES[@]}"); fi
if [[ $MODE == system ]]; then
  printf '== Composants de compilation ==\n'
  apt-get update -q || fail "mise à jour de la liste des paquets impossible"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "${need[@]}" \
    || fail "installation des composants de compilation impossible"
else
  missing=()
  for pkg in "${need[@]}"; do
    [[ $pkg == patchelf ]] && command -v patchelf >/dev/null && continue   # essai sans sudo : patchelf venu d'ailleurs (pip)
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
  done
  [[ ${#missing[@]} -eq 0 ]] || fail "paquets manquants : sudo apt-get install ${missing[*]}"
fi

WORK=$(mktemp -d /tmp/trx-freedv-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

checkout() {  # dépôt, commit, dossier : clone puis vérifie le commit COMPLET
  git clone -q "$1" "$3" || fail "téléchargement impossible : $1"
  git -C "$3" -c advice.detachedHead=false checkout -q "$2" || fail "commit $2 introuvable dans $1"
  [[ $(git -C "$3" rev-parse HEAD) == "$2" ]] || fail "$3 : commit inattendu, rien n'est compilé"
}

edit() {  # fichier, ancien texte, nouveau texte : remplacement exact, une seule occurrence exigée
  python3 - "$@" <<'PY' || fail "sources inattendues ($1) : rien n'est compilé"
import sys
path, old, new = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(1)
open(path, "w", encoding="utf-8").write(text.replace(old, new))
PY
}

printf '== Sources (commits épinglés) ==\n'
checkout "$RADE_C_REPO" "$RADE_C_COMMIT" rade_c
checkout "$INTEG_REPO" "$INTEG_COMMIT" integ
git -C integ submodule -q update --init src/backend || fail "sous-module freedv-backend introuvable"
[[ $(git -C integ/src/backend rev-parse HEAD) == "$BACKEND_COMMIT" ]] || fail "freedv-backend : commit inattendu"
curl -fsSL -o opus.zip "$OPUS_URL" || fail "téléchargement impossible : $OPUS_URL"
echo "$OPUS_SHA256  opus.zip" | sha256sum -c --quiet - || fail "empreinte SHA-256 d'Opus incorrecte : archive refusée"
ok "sources vérifiées (rade_c ${RADE_C_COMMIT:0:7}, freedv-integrations ${INTEG_COMMIT:0:7}, Opus SHA-256)"

git -C rade_c apply "$PATCHES/radae_rx-windows-binary-stdin.patch" || fail "correctif de radae_rx non applicable"
git -C integ apply "$PATCHES/freedv-ka9q-windows-stdin.patch" || fail "correctif de freedv-ka9q non applicable"
# freedv-integrations prend rade_c sur la branche « main » (mouvante) et Opus sans empreinte : on lui donne NOS
# sources vérifiées (le même rade_c corrigé sert à librade, freedv-ka9q et radae_rx).
RADE_CMAKE=integ/src/backend/cmake/BuildRADE.cmake
edit "$RADE_CMAKE" "-DOPUS_URL=$OPUS_URL)" "-DOPUS_URL=file://$WORK/opus.zip)"
edit "$RADE_CMAKE" "   SOURCE_DIR rade_src
   BINARY_DIR rade_build
   GIT_REPOSITORY https://github.com/freedv/rade_c
   GIT_TAG main
   GIT_SUBMODULES \"\"
   GIT_SUBMODULES_RECURSE NO
" "   SOURCE_DIR $WORK/rade_c
   BINARY_DIR rade_build
"
edit integ/src/backend/cmake/BuildEbur128.cmake 'GIT_TAG "v${EBUR128_VERSION}"' "GIT_TAG $EBUR128_COMMIT"
ok "correctifs appliqués"

mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
jobs=$(( mem_kb / 1500000 )); (( jobs < 1 )) && jobs=1; (( jobs > $(nproc) )) && jobs=$(nproc)   # ~1,5 Go par tâche

cmake_args=(-DCMAKE_BUILD_TYPE=Release -DDISABLE_TLS_SUPPORT=ON -DUSE_STATIC_EBUR128=ON -DUSE_STATIC_SAMPLERATE=ON)
if [[ $MODE == windows ]]; then
  cat >toolchain-mingw64.cmake <<'EOF'
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc-posix)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++-posix)
set(CMAKE_RC_COMPILER x86_64-w64-mingw32-windres)
set(CMAKE_FIND_ROOT_PATH /usr/x86_64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_C_COMPILER_TARGET x86_64-w64-mingw32)
EOF
  cmake_args+=(-DCMAKE_TOOLCHAIN_FILE="$WORK/toolchain-mingw64.cmake" -DCMAKE_C_FLAGS=-DWIN32
               "-DCMAKE_CXX_FLAGS=-DWIN32 -include winsock2.h -include ws2tcpip.h"
               "-DCMAKE_CXX_STANDARD_LIBRARIES=-lws2_32 -liphlpapi"
               "-DCMAKE_EXE_LINKER_FLAGS=-static-libgcc -static-libstdc++")
fi

printf '== Compilation (%s tâche(s) ; ~5 minutes sur un PC, 30 à 60 minutes sur un Raspberry Pi 4) ==\n' "$jobs"
cmake -S integ -B build "${cmake_args[@]}" >configure.log 2>&1 || { tail -n 30 configure.log; fail "cmake a échoué"; }
cmake --build build --target freedv-ka9q -j "$jobs" >make.log 2>&1 || { tail -n 40 make.log; fail "la compilation a échoué"; }

RADE_OUT=build/src/backend/rade_build/src
STAGE=$WORK/stage
mkdir -p "$STAGE/licences"
for lic in rade_c:rade_c/LICENSE freedv-integrations:integ/LICENSE freedv-backend:integ/src/backend/LICENSE; do
  cp "${lic#*:}" "$STAGE/licences/${lic%%:*}.txt"
done
for dep in opus:build/src/backend/rade_build/build_opus-prefix/src/build_opus/COPYING \
           rnnoise:"$(find build -path '*build_rnnoise/COPYING' | head -n1)" \
           libsamplerate:"$(find build -path '*samplerate-src/COPYING' | head -n1)" \
           libebur128:"$(find build -path '*ebur128_src/COPYING' | head -n1)"; do
  [[ -f ${dep#*:} ]] && cp "${dep#*:}" "$STAGE/licences/${dep%%:*}.txt"
done
cp "$PATCHES"/*.patch "$STAGE/licences/"
{
  printf '%s\n' "$FREEDV_BUILD_ID"
  printf 'Sources : %s @ %s ; %s @ %s (src/backend @ %s) ; Opus @ %s (SHA-256 %s) ; libebur128 @ %s\n' \
    "$RADE_C_REPO" "$RADE_C_COMMIT" "$INTEG_REPO" "$INTEG_COMMIT" "$BACKEND_COMMIT" "$OPUS_COMMIT" "$OPUS_SHA256" "$EBUR128_COMMIT"
  printf 'Correctifs : licences/*.patch (proposés à l équipe FreeDV). Compilé le %s.\n' "$(date -u +%Y-%m-%dT%H:%MZ)"
} >"$STAGE/VERSION"

if [[ $MODE == windows ]]; then
  cp build/src/ka9q/freedv-ka9q.exe "$RADE_OUT/radae_rx.exe" "$RADE_OUT/librade.dll" "$STAGE/"
  # DLL de MinGW demandées par les exécutables (les DLL de Windows restent celles du système)
  for _ in 1 2; do
    for f in "$STAGE"/*.exe "$STAGE"/*.dll; do
      for dll in $(x86_64-w64-mingw32-objdump -p "$f" | awk '/DLL Name:/ {print $3}'); do
        [[ -f $STAGE/$dll ]] && continue
        src=$(find /usr/lib/gcc/x86_64-w64-mingw32 /usr/x86_64-w64-mingw32/lib -name "$dll" 2>/dev/null | grep -v win32 | head -n1 || true)
        [[ -n $src ]] && cp "$src" "$STAGE/"
      done
    done
  done
  # Licences des DLL de MinGW livrées (winpthreads : MIT ; libssp : GCC avec exception d'exécution)
  for doc in mingw-w64-common gcc-mingw-w64-base; do
    [[ -f /usr/share/doc/$doc/copyright ]] && cp "/usr/share/doc/$doc/copyright" "$STAGE/licences/$doc.txt"
  done
  (cd "$STAGE" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | xargs sha256sum >SHA256SUMS)
  mkdir -p "$OUT"
  rm -rf "${OUT:?}"/*
  cp -r "$STAGE"/. "$OUT/"
  ok "décodeurs Windows dans $OUT : $(cd "$OUT" && ls ./*.exe ./*.dll | sed 's|^\./||' | tr '\n' ' ')"
  printf '\nPaquet Windows : python scripts/build_windows_zip.py --freedv %s\n' "$OUT"
  exit 0
fi

cp build/src/ka9q/freedv-ka9q "$RADE_OUT/radae_rx" "$STAGE/"
cp -P "$RADE_OUT"/librade.so* "$STAGE/"
# RUNPATH = dossier de l'exécutable : jamais le dossier de compilation (effacé, recréable par n'importe qui dans /tmp)
for exe in freedv-ka9q radae_rx; do patchelf --set-rpath '$ORIGIN' "$STAGE/$exe"; done
for so in "$STAGE"/librade.so*; do [[ -L $so ]] || patchelf --remove-rpath "$so"; done

printf '== Essai des décodeurs (1 s de silence) ==\n'
(cd "$WORK" && head -c 192000 /dev/zero | "$STAGE/freedv-ka9q" -i 48000 -o 48000 >/dev/null 2>ka9q.log) \
  || { tail -n 5 ka9q.log; fail "freedv-ka9q ne démarre pas"; }
(cd "$WORK" && head -c 64000 /dev/zero | "$STAGE/radae_rx" -v 1 >/dev/null 2>radae.log) \
  || { tail -n 5 radae.log; fail "radae_rx ne démarre pas"; }
ldd "$STAGE/radae_rx" | grep -q "librade.*$STAGE" || fail "radae_rx ne charge pas sa librade"
ok "les deux décodeurs démarrent"

mkdir -p "$PREFIX/lib" "$BIN"
rm -rf "$DEST.new" "$DEST.old"
cp -a "$STAGE" "$DEST.new"
(cd "$DEST.new" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | xargs sha256sum >SHA256SUMS)
[[ -e $DEST ]] && mv "$DEST" "$DEST.old"
mv "$DEST.new" "$DEST"
rm -rf "$DEST.old"
[[ $MODE == system ]] && chmod -R u=rwX,go=rX "$DEST"
for name in freedv-ka9q radae_rx; do
  if [[ -e $BIN/$name && ! -L $BIN/$name ]]; then
    printf '  [ATTENTION] %s existe déjà (pas un lien de ce script) : laissé en place ; [freedv] de station.toml\n' "$BIN/$name"
    printf '              peut désigner %s\n' "$DEST/$name"
  else
    ln -sfn "$DEST/$name" "$BIN/$name"
  fi
done
ok "décodeurs FreeDV installés dans $DEST ($FREEDV_BUILD_ID)"
if [[ $MODE == system ]]; then
  found=$(command -v freedv-ka9q || true)
  [[ $found == "$BIN/freedv-ka9q" ]] || printf '  [ATTENTION] le PATH trouve d'\''abord %s\n' "${found:-rien}"
  printf '\nPour s'\''en servir : [freedv] enabled = true dans station.toml (TRX Console, menu 3.2), puis le mode FreeDV\n'
  printf 'se choisit depuis la page (rubrique « FreeDV »).\n'
fi
