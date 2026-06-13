#!/bin/bash
# Install the freshly built .deb into a clean ubuntu:24.04 and smoke-test every
# console entry point. Run with the output dir bind-mounted at /out.
set -euo pipefail

DEB="$(ls -1 /out/kowalski_*.deb | head -n1)"
echo "==> Installing $DEB"
apt-get update -qq
apt-get install -y -qq "$DEB"

echo "==> dpkg contents (head)"
dpkg-deb --contents "$DEB" | grep -E '/usr/bin/|kowalski-core.service' || true

echo "==> Smoke-testing entry points"
for cmd in "kow --version" "kow tools list" "kow-omni --version" \
           "kow-voice --version" "kow-index --version" "kow-setup --version"; do
    echo "--- $cmd"
    KOW_DB_PATH=/tmp/verify.db $cmd
done
echo "==> OK: kowalski .deb installs and all entry points run"
