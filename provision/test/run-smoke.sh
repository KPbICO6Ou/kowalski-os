#!/bin/bash
# Smoke test for the provisioning layer, run inside ubuntu:24.04.
# The repo is bind-mounted read-only at /repo.
#
# 1. cloud-init schema validation of the autoinstall config (if present)
# 2. ansible-playbook run with container guards (must exit 0)
# 3. second identical run (must report changed=0 — idempotency)
set -euo pipefail

REPO=/repo
SKIP_TAGS="${SKIP_TAGS:-gpu}"
EXTRA=(-e kowalski_in_container=true --skip-tags "$SKIP_TAGS")
PLAYBOOK="$REPO/provision/site.yml"
INVENTORY="$REPO/provision/inventories/local/hosts.yml"

cd "$REPO/provision"
export ANSIBLE_CONFIG="$REPO/provision/ansible.cfg"
export ANSIBLE_ROLES_PATH="$REPO/provision/roles"

if [ -f "$REPO/provision/autoinstall/autoinstall.yaml" ]; then
    echo "==> cloud-init schema check"
    cloud-init schema --config-file "$REPO/provision/autoinstall/autoinstall.yaml"
fi

echo "==> playbook run 1 (apply)"
ansible-playbook "$PLAYBOOK" -i "$INVENTORY" "${EXTRA[@]}"

echo "==> playbook run 2 (idempotency)"
LOG=$(mktemp)
ansible-playbook "$PLAYBOOK" -i "$INVENTORY" "${EXTRA[@]}" | tee "$LOG"

if grep -E 'changed=[1-9]' "$LOG"; then
    echo "FAIL: second run is not idempotent (changed != 0)"
    exit 1
fi
echo "OK: idempotent"
