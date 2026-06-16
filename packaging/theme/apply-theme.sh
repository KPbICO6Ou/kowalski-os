#!/bin/bash
# Apply the Kowalski OS XFCE look on first login (idempotent). Intended to run
# from the onboarding autostart entry; safe to re-run. Uses xfconf-query, so it
# only does anything inside a running XFCE session.
set -euo pipefail

if ! command -v xfconf-query >/dev/null 2>&1; then
    echo "xfconf-query not found (not an XFCE session?) — skipping theme" >&2
    exit 0
fi

set_prop() {  # channel property value [type]
    xfconf-query -c "$1" -p "$2" -n -t "${4:-string}" -s "$3" 2>/dev/null \
        || xfconf-query -c "$1" -p "$2" -s "$3" 2>/dev/null || true
}

# Dark, minimal desktop tuned for the AI layer.
set_prop xsettings /Net/ThemeName "Adwaita-dark"
set_prop xsettings /Net/IconThemeName "elementary-xfce-dark"
set_prop xfwm4 /general/theme "Default-xhdpi"
set_prop xfce4-panel /panels/dark-mode true bool

to_xfce_accel() {  # "super+space" -> "<Super>space"; pass through "<...>" as-is
    local combo="$1" out="" tok n i=0
    case "$combo" in *"<"*) printf '%s' "$combo"; return ;; esac
    local parts=()
    IFS='+' read -ra parts <<< "$combo" || true
    n=${#parts[@]}
    for tok in "${parts[@]}"; do
        i=$((i + 1))
        if [ "$i" -lt "$n" ]; then
            case "$(printf '%s' "$tok" | tr 'A-Z' 'a-z')" in
                ctrl | control | primary) out="$out<Primary>" ;;
                alt)                       out="$out<Alt>" ;;
                shift)                     out="$out<Shift>" ;;
                super | win | meta | cmd)  out="$out<Super>" ;;
                *)                         out="$out<$tok>" ;;
            esac
        else
            out="$out$tok"   # the key itself
        fi
    done
    printf '%s' "$out"
}

# Bind the push-to-talk hotkey (KOW_VOICE_HOTKEY) to a one-shot voice turn.
KOW_CONF="$HOME/.config/kowalski/kowalski.conf"
HOTKEY="$(sed -n 's/^KOW_VOICE_HOTKEY=//p' "$KOW_CONF" 2>/dev/null | tail -1 | tr -d "\"'")"
if [ -n "${HOTKEY:-}" ]; then
    ACCEL="$(to_xfce_accel "$HOTKEY")"
    set_prop xfce4-keyboard-shortcuts "/commands/custom/$ACCEL" "kow-voice once"
    echo "Push-to-talk: $ACCEL -> kow-voice once"
fi

echo "Kowalski OS theme applied."
