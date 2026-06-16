#!/bin/bash
# Targeted pre-deploy backup of the user profile that the Kowalski deploy
# touches (packages, XFCE/xfconf, user systemd units, autostart, kowalski
# config/state). Small + restorable — not a full home dump. Writes a
# timestamped tarball under ~/kowalski-backups/. Run as the deploy user.
set -uo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
ROOT="$HOME/kowalski-backups"
BK="$ROOT/profile-$TS"
mkdir -p "$BK/xfconf"

dpkg --get-selections > "$BK/dpkg-selections.txt" 2>/dev/null || true
(dpkg -l 2>/dev/null | grep -i kowalski || echo "(no kowalski packages)") > "$BK/kowalski-packages.txt"
systemctl --user list-unit-files --state=enabled > "$BK/user-units-enabled.txt" 2>/dev/null || true
(crontab -l 2>/dev/null || echo "(no crontab)") > "$BK/crontab.txt"
{ id; hostname; uname -a; } > "$BK/system-info.txt" 2>&1 || true
{ for p in "$HOME/.config/kowalski" "$HOME/.config/ttsgen.conf" "$HOME/.local/share/kowalski"; do
    [ -e "$p" ] && echo "PRESENT $p" || echo "ABSENT  $p"; done; } > "$BK/pre-deploy-state.txt"

if command -v xfconf-query >/dev/null 2>&1; then
  xfconf-query -l 2>/dev/null | tail -n +2 | while read -r ch; do
    ch="$(echo "$ch" | xargs)"; [ -z "$ch" ] && continue
    xfconf-query -c "$ch" -lv > "$BK/xfconf/${ch//\//_}.txt" 2>/dev/null || true
  done
fi

PATHS=()
for p in .config/xfce4 .config/autostart .config/systemd/user .config/ttsgen.conf \
         .config/kowalski .local/share/kowalski; do
  [ -e "$HOME/$p" ] && PATHS+=("$p")
done
TAR="$ROOT/profile-$TS.tar.gz"
tar czf "$TAR" -C "$HOME" --ignore-failed-read \
  "kowalski-backups/profile-$TS" ${PATHS[@]+"${PATHS[@]}"}
( cd "$ROOT" && sha256sum "profile-$TS.tar.gz" > "profile-$TS.tar.gz.sha256" )
echo "BACKUP_TAR=$TAR"
