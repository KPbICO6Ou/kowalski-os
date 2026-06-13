#!/bin/bash
# Install the freshly built Kowalski .deb family into a clean ubuntu:24.04 and
# smoke-test every console entry point. Run with the output dir bind-mounted at
# /out.
#
# Checks:
#   1. Modularity: installing ONLY kowalski-core gives /usr/bin/kow but NOT
#      /usr/bin/kow-omni (the omnibox lives in the thin kowalski-ui package).
#   2. Full install: kowalski-core + the three thin packages together (apt
#      resolves the local versioned `= <version>` deps), then every CLI runs.
set -euo pipefail

cd /out

CORE_DEB="$(ls -1 ./kowalski-core_*.deb | head -n1)"
UI_DEB="$(ls -1 ./kowalski-ui_*.deb | head -n1)"
VOICE_DEB="$(ls -1 ./kowalski-voice_*.deb | head -n1)"
INDEXER_DEB="$(ls -1 ./kowalski-indexer_*.deb | head -n1)"

for d in "$CORE_DEB" "$UI_DEB" "$VOICE_DEB" "$INDEXER_DEB"; do
    [ -f "$d" ] || { echo "MISSING: $d" >&2; exit 1; }
done

apt-get update -qq

echo "==> [1/3] Modularity check: install ONLY kowalski-core"
apt-get install -y -qq "$CORE_DEB"

if [ ! -e /usr/bin/kow ]; then
    echo "FAIL: kowalski-core did not install /usr/bin/kow" >&2
    exit 1
fi
if [ -e /usr/bin/kow-omni ]; then
    echo "FAIL: /usr/bin/kow-omni present with core alone (should be in kowalski-ui)" >&2
    exit 1
fi
echo "OK: core provides /usr/bin/kow; /usr/bin/kow-omni absent (modular)"

echo "==> [2/3] Install the three thin packages (versioned deps resolved locally)"
# Install all three together so the `= <version>` dependency on the already
# installed kowalski-core is satisfied from the same apt transaction.
apt-get install -y -qq "$UI_DEB" "$VOICE_DEB" "$INDEXER_DEB"

echo "==> dpkg-deb contents (entry points + unit)"
for d in "$CORE_DEB" "$UI_DEB" "$VOICE_DEB" "$INDEXER_DEB"; do
    echo "--- $d"
    dpkg-deb --contents "$d" | grep -E '/usr/bin/|kowalski-core.service|autostart/' || true
done

echo "==> [3/3] Smoke-testing every entry point"
for cmd in "kow --version" "kow tools list" "kow-setup --version" \
           "kow-omni --version" "kow-voice --version" "kow-index --version"; do
    echo "--- $cmd"
    KOW_DB_PATH=/tmp/verify.db $cmd
done

echo "==> OK: all four Kowalski packages install and every entry point runs"
