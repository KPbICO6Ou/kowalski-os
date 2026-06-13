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

echo "Kowalski OS theme applied."
