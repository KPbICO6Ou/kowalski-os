#!/usr/bin/env bash
# Pull-based auto-update for a Kowalski OS install (beta convenience).
#
# Polls origin/<branch>; when it has advanced, hard-resets the checkout to it,
# reinstalls ONLY when a pyproject/requirements changed (editable installs pick
# up code changes with no reinstall), and restarts the kowalski-core user
# service. Runs as the install user from a systemd user timer — no sudo.
#
# Scope: code + Python deps. Full infra changes (apt packages, systemd unit
# edits, the XFCE theme) still need a real `deploy.sh` run.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

PREFIX="${KOW_PREFIX:-/opt/KowalskiOS}"
BRANCH="${KOW_BRANCH:-main}"
EXTRAS="${KOW_EXTRAS:-[api,pydantic-ai]}"
VENV="$PREFIX/.venv"

cd "$PREFIX" || exit 0
git fetch --quiet origin "$BRANCH" || exit 0
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse "origin/$BRANCH")"
[ "$local_rev" = "$remote_rev" ] && exit 0

echo "kow-autoupdate: $local_rev -> $remote_rev"
deps_changed="$(git diff --name-only "$local_rev" "$remote_rev" \
  | grep -E 'pyproject\.toml|requirements.*\.txt' || true)"
git reset --hard "origin/$BRANCH"

if [ -n "$deps_changed" ] || [ ! -x "$VENV/bin/kow" ]; then
  echo "kow-autoupdate: dependencies changed — reinstalling packages"
  "$VENV/bin/pip" install --quiet --upgrade \
    -e "$PREFIX/core$EXTRAS" -e "$PREFIX/indexer" -e "$PREFIX/ui" \
    -e "$PREFIX/voice" -e "$PREFIX/setup"
fi

systemctl --user restart kowalski-core 2>/dev/null || true
echo "kow-autoupdate: now at $remote_rev"
