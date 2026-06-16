#!/usr/bin/env bash
# Deploy Kowalski OS onto a machine with the Ansible playbook.
#
# Usage:
#   ./deploy.sh <username> [addr] [options] [extra ansible-playbook args...]
#
#   <username>        account to deploy under (and the SSH user for a remote addr)
#   [addr]            target host; optional, default 127.0.0.1 (local connection)
#   --pass PW         SSH login password for <username> on a remote host
#                     (needs `sshpass`; ignored for a local connection)
#   --sudo-pass PW    sudo/become password; defaults to --pass when omitted
#   extra args        forwarded to ansible-playbook (e.g. -e kow_ollama_model=qwen3:8b)
#
# Passwords are passed to Ansible through a temporary 0600 vars file (removed on
# exit), never on the command line, so they don't leak via `ps` or the log.
#
# Examples:
#   ./deploy.sh alice                              # deploy locally as alice
#   ./deploy.sh alice 10.0.0.5                     # remote over SSH (key auth)
#   ./deploy.sh alice 10.0.0.5 --pass 's3cret'     # remote with a login password
#                                                  # (sudo password defaults to it)
#   ./deploy.sh alice 10.0.0.5 --sudo-pass 's3cret'  # key login, sudo needs a password
#   ./deploy.sh alice 10.0.0.5 --pass login --sudo-pass other \
#       -e kow_ollama_model=qwen3:8b               # different login vs sudo passwords
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

USERNAME="${1:-}"
if [ -z "$USERNAME" ]; then
  echo "usage: $0 <username> [addr] [--pass PW] [--sudo-pass PW] [extra args...]" >&2
  exit 2
fi
shift

ADDR="127.0.0.1"
# Treat the next token as addr only if it is not an option flag.
if [ "${1:-}" ] && [ "${1#-}" = "${1:-}" ]; then
  ADDR="$1"
  shift
fi

# Pull --pass / --sudo-pass out of the args; forward everything else to ansible.
PASS=""
SUDO_PASS=""
PASSTHRU=()
while [ $# -gt 0 ]; do
  case "$1" in
    --pass)
      [ $# -ge 2 ] || { echo "--pass requires a value" >&2; exit 2; }
      PASS="$2"; shift 2 ;;
    --pass=*)
      PASS="${1#--pass=}"; shift ;;
    --sudo-pass)
      [ $# -ge 2 ] || { echo "--sudo-pass requires a value" >&2; exit 2; }
      SUDO_PASS="$2"; shift 2 ;;
    --sudo-pass=*)
      SUDO_PASS="${1#--sudo-pass=}"; shift ;;
    *)
      PASSTHRU+=("$1"); shift ;;
  esac
done
# No explicit sudo password -> reuse the login password.
SUDO_PASS="${SUDO_PASS:-$PASS}"

# Prefer the repo's venv ansible if present, else the one on PATH.
AP="$HERE/../.venv/bin/ansible-playbook"
[ -x "$AP" ] || AP="ansible-playbook"
if ! command -v "$AP" >/dev/null 2>&1 && [ ! -x "$AP" ]; then
  echo "ansible-playbook not found. Install it (e.g. 'make venv' at the repo root)." >&2
  exit 1
fi

LOCAL=0
CONN=()
case "$ADDR" in
  127.0.0.1 | localhost | ::1)
    LOCAL=1
    echo ">> Deploying Kowalski OS locally as '$USERNAME'"
    CONN=(-i "localhost," -c local) ;;
  *)
    echo ">> Deploying Kowalski OS to '$USERNAME@$ADDR' over SSH"
    CONN=(-i "$ADDR," -u "$USERNAME") ;;
esac

# Write any passwords to a temporary 0600 vars file (removed on exit).
yaml_quote() {                       # YAML single-quoted scalar: '' escapes a quote
  local q=\'
  printf "'%s'" "${1//$q/$q$q}"
}
SECRETS_FILE=""
want_ssh_pass=0
[ -n "$PASS" ] && [ "$LOCAL" = 0 ] && want_ssh_pass=1
if [ "$want_ssh_pass" = 1 ] || [ -n "$SUDO_PASS" ]; then
  SECRETS_FILE="$(mktemp)"
  trap 'rm -f "$SECRETS_FILE"' EXIT
  chmod 600 "$SECRETS_FILE"
  {
    echo "---"
    [ "$want_ssh_pass" = 1 ] && echo "ansible_password: $(yaml_quote "$PASS")"
    [ -n "$SUDO_PASS" ] && echo "ansible_become_password: $(yaml_quote "$SUDO_PASS")"
  } >"$SECRETS_FILE"
fi

if [ "$want_ssh_pass" = 1 ] && ! command -v sshpass >/dev/null 2>&1; then
  echo "remote password auth needs 'sshpass' on this machine" >&2
  echo "  macOS: brew install hudochenkov/sshpass/sshpass   Debian/Ubuntu: apt install sshpass" >&2
  exit 1
fi
# A password login to a not-yet-known host would block on the host-key prompt.
[ "$want_ssh_pass" = 1 ] && export ANSIBLE_HOST_KEY_CHECKING=False

CMD=("$AP" "$HERE/deploy.yml")
CMD+=("${CONN[@]}")
CMD+=(-e "kow_user=$USERNAME")
[ -n "$SECRETS_FILE" ] && CMD+=(-e "@$SECRETS_FILE")
if [ "${#PASSTHRU[@]}" -gt 0 ]; then
  CMD+=("${PASSTHRU[@]}")
fi

echo ">> ${CMD[*]}"   # passwords live in the vars file, not here
"${CMD[@]}"
