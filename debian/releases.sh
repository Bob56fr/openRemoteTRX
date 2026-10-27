# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Versions installées de TRX distant. Sourcé par install.sh (APP_DIR défini avant) ; testé seul par
# tests/test_update_releases.py.
#
#   /opt/trx-remote/releases/<version>/   paquet de cette version (install.sh, systeme/, app/) et son venv/
#   /opt/trx-remote/current  -> releases/<version active>
#   /opt/trx-remote/previous -> releases/<version précédente>  (une seule : retour en arrière sans réseau)
#   /opt/trx-remote/venv     -> current/venv                    (chemin des units systemd et des commandes)
#
# Chaque lien est remplacé par un renommage (atomique) : une coupure ne laisse jamais de lien à moitié écrit.

RELEASES=$APP_DIR/releases
CURRENT_LINK=$APP_DIR/current
PREVIOUS_LINK=$APP_DIR/previous
VENV=$APP_DIR/venv

valid_version() { [[ $1 =~ ^[0-9][0-9A-Za-z.+-]{0,39}$ && $1 != *..* ]]; }

release_of() {   # release_of LIEN : version visée par le lien (rien si le lien manque ou vise un dossier absent)
  local target
  target=$(readlink "$1" 2>/dev/null) || return 0
  [[ -d $APP_DIR/$target ]] || return 0
  printf '%s\n' "${target##*/}"
}

set_link() {     # set_link LIEN CIBLE_RELATIVE
  rm -rf "$1.new"
  ln -s "$2" "$1.new"
  mv -T "$1.new" "$1"
}

legacy_layout() { [[ -d $VENV && ! -L $VENV ]]; }   # installation d'avant la 0.23.0 : app/ et venv/ en dossiers

activate_release() {   # activate_release VERSION : la rend active ; l'ancienne active devient la précédente
  local new=$1 old
  valid_version "$new" && [[ -x $RELEASES/$new/venv/bin/python ]] || return 1
  old=$(release_of "$CURRENT_LINK")
  if legacy_layout; then rm -rf "$VENV" "$APP_DIR/app"; fi
  set_link "$CURRENT_LINK" "releases/$new"
  set_link "$VENV" "current/venv"
  if [[ -n $old && $old != "$new" ]]; then set_link "$PREVIOUS_LINK" "releases/$old"; fi
  prune_releases
}

prune_releases() {     # garde la version active et la précédente, rien d'autre
  local current previous dir name
  current=$(release_of "$CURRENT_LINK")
  [[ -n $current ]] || return 0                    # aucune version active : on ne supprime rien
  previous=$(release_of "$PREVIOUS_LINK")
  [[ $previous == "$current" ]] && previous=""
  [[ -n $previous ]] || rm -f "$PREVIOUS_LINK"
  for dir in "$RELEASES"/*; do
    [[ -d $dir && ! -L $dir ]] || continue
    name=${dir##*/}
    [[ $name == "$current" || $name == "$previous" ]] || rm -rf "$dir"
  done
}
