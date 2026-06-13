#!/bin/bash
# Build a single self-contained kowalski .deb.
#
# Kowalski's Python dependencies (ollama, pydantic-ai, pydantic-ai-toolbox, ...)
# are not in the Ubuntu archive, so instead of declaring them as deb deps we
# bundle a virtualenv at /opt/kowalski/venv. The venv is built at its FINAL
# install path so the script shebangs are valid after dpkg installs it.
#
# Run inside ubuntu:24.04 with the repo bind-mounted read-only at /repo and an
# output dir at /out (see Dockerfile / `make deb`).
set -euo pipefail

REPO=/repo
OUT=/out
PREFIX=/opt/kowalski
VENV="$PREFIX/venv"
VERSION="$(grep -m1 '^version' "$REPO/core/pyproject.toml" | cut -d'"' -f2)"
ARCH="$(dpkg --print-architecture)"
PKG="kowalski_${VERSION}_${ARCH}"
STAGING="/tmp/$PKG"

echo "==> Copying sources out of the read-only mount"
# setuptools writes <pkg>.egg-info into the source tree, which fails on the
# read-only /repo bind mount — build from a writable copy instead.
SRC=/tmp/src
rm -rf "$SRC"
mkdir -p "$SRC"
for pkg in core indexer ui voice setup; do
    cp -a "$REPO/$pkg" "$SRC/$pkg"
done

echo "==> Building venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
# Non-editable installs copy the code into the venv (the /repo mount is gone
# after the build); pull the cross-package deps from PyPI.
"$VENV/bin/pip" install -q \
    "$SRC/core[api,pydantic-ai]" \
    "$SRC/indexer" \
    "$SRC/ui" \
    "$SRC/voice" \
    "$SRC/setup"

echo "==> Staging package tree"
rm -rf "$STAGING"
install -d "$STAGING$PREFIX" "$STAGING/usr/bin" "$STAGING/usr/lib/systemd/user" "$STAGING/DEBIAN"
cp -a "$PREFIX/." "$STAGING$PREFIX/"

# Console-script launchers -> stable /usr/bin entries.
for bin in kow kow-omni kow-voice kow-index kow-setup; do
    if [ -x "$VENV/bin/$bin" ]; then
        ln -sf "$VENV/bin/$bin" "$STAGING/usr/bin/$bin"
    fi
done

cp "$REPO/packaging/systemd/kowalski-core.service" \
   "$STAGING/usr/lib/systemd/user/kowalski-core.service"

# Theme + first-login onboarding.
install -d "$STAGING/usr/share/kowalski" "$STAGING/etc/xdg/autostart"
install -m 0755 "$REPO/packaging/theme/apply-theme.sh" \
   "$STAGING/usr/share/kowalski/apply-theme.sh"
install -m 0755 "$REPO/packaging/theme/kowalski-onboarding" \
   "$STAGING/usr/bin/kowalski-onboarding"
install -m 0644 "$REPO/packaging/theme/kowalski-onboarding.desktop" \
   "$STAGING/etc/xdg/autostart/kowalski-onboarding.desktop"

INSTALLED_KB="$(du -sk "$STAGING$PREFIX" | cut -f1)"

cat > "$STAGING/DEBIAN/control" <<EOF
Package: kowalski
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.12)
Recommends: fd-find, ripgrep, plocate, maim, xdotool, wmctrl, bubblewrap
Installed-Size: $INSTALLED_KB
Maintainer: wachawo
Description: Kowalski OS agent core, omnibox, voice, and semantic indexer
 An AI-native desktop layer: the kow-core agent daemon plus the kow / kow-omni /
 kow-voice / kow-index / kow-setup commands, bundled with their Python runtime
 in a self-contained virtualenv under /opt/kowalski. Enable the daemon per user
 with: systemctl --user enable --now kowalski-core
EOF

cat > "$STAGING/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
# The bundled venv records its build path; nothing to relocate (it is built at
# the final /opt/kowalski/venv). Refresh systemd's user unit cache if running.
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$STAGING/DEBIAN/postinst"

echo "==> dpkg-deb --build"
dpkg-deb --root-owner-group --build "$STAGING" "$OUT/$PKG.deb"
echo "==> Built $OUT/$PKG.deb"
dpkg-deb --info "$OUT/$PKG.deb"
