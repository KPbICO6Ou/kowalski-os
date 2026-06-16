#!/usr/bin/env bash
# Deploy Kowalski OS onto a machine with the Ansible playbook.
#
# Usage:
#   ./deploy.sh <username> [addr] [extra ansible-playbook args...]
#
#   <username>  account to deploy under (and the SSH user for a remote addr)
#   [addr]      target host; optional, default 127.0.0.1 (local connection)
#   extra args  forwarded to ansible-playbook (e.g. -e kow_ollama_model=qwen3:8b)
#
# Examples:
#   ./deploy.sh alice                         # deploy locally as alice
#   ./deploy.sh alice 10.0.0.5                # deploy to a remote host over SSH
#   ./deploy.sh alice 10.0.0.5 \
#       -e kow_ollama_host=http://10.0.0.6:11434 -e kow_ollama_model=qwen3:8b \
#       -e kow_embed_model=bge-m3 -e kow_vision=0      # point at a remote Ollama
#   ./deploy.sh alice 10.0.0.5 --ask-become-pass      # if sudo needs a password
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

USERNAME="${1:-}"
if [ -z "$USERNAME" ]; then
  echo "usage: $0 <username> [addr] [extra ansible-playbook args...]" >&2
  exit 2
fi
shift

ADDR="127.0.0.1"
# Treat the next token as addr only if it is not an option flag.
if [ "${1:-}" ] && [ "${1#-}" = "${1:-}" ]; then
  ADDR="$1"
  shift
fi

# Prefer the repo's venv ansible if present, else the one on PATH.
AP="$HERE/../.venv/bin/ansible-playbook"
[ -x "$AP" ] || AP="ansible-playbook"
if ! command -v "$AP" >/dev/null 2>&1 && [ ! -x "$AP" ]; then
  echo "ansible-playbook not found. Install it (e.g. 'make venv' at the repo root)." >&2
  exit 1
fi

COMMON=(-e "kow_user=$USERNAME")
case "$ADDR" in
  127.0.0.1 | localhost | ::1)
    echo ">> Deploying Kowalski OS locally as '$USERNAME'"
    set -- "$AP" "$HERE/deploy.yml" -i "localhost," -c local "${COMMON[@]}" "$@"
    ;;
  *)
    echo ">> Deploying Kowalski OS to '$USERNAME@$ADDR' over SSH"
    set -- "$AP" "$HERE/deploy.yml" -i "$ADDR," -u "$USERNAME" "${COMMON[@]}" "$@"
    ;;
esac

echo ">> ${*}"
exec "$@"
