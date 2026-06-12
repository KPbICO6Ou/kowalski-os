#!/bin/bash
# Kowalski OS first boot: pull the repo and run the provisioning playbook,
# then disable ourselves. Network is available here (unlike inside curtin).
set -uo pipefail

STAMP=/var/lib/kowalski-firstboot.done
REPO_URL="${KOWALSKI_REPO_URL:-https://github.com/KPbICO6Ou/kowalski-os.git}"

if [ -f "$STAMP" ]; then
    exit 0
fi

LOG=/var/log/kowalski-firstboot.log
{
    echo "=== kowalski firstboot $(date -Is) ==="
    ansible-pull -U "$REPO_URL" \
        -i provision/inventories/local/hosts.yml \
        provision/local.yml
    STATUS=$?
    echo "=== ansible-pull exited with $STATUS ==="
    if [ "$STATUS" -eq 0 ]; then
        touch "$STAMP"
        systemctl disable kowalski-firstboot.service
    fi
} >>"$LOG" 2>&1
