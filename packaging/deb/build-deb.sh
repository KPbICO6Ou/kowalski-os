#!/bin/bash
# Build the Kowalski .deb family from ONE shared virtualenv.
#
# Kowalski's Python dependencies (ollama, pydantic-ai, pydantic-ai-toolbox, ...)
# are not in the Ubuntu archive, so instead of declaring them as deb deps we
# bundle a virtualenv at /opt/kowalski/venv. The venv is built at its FINAL
# install path so the script shebangs are valid after dpkg installs it.
#
# To avoid duplicating that ~hundreds-of-MB venv once per component, we build it
# ONCE with every component installed (they share ~all deps) and ship it in the
# heavy base package, kowalski-core. The thin component packages
# (kowalski-ui / kowalski-voice / kowalski-indexer) carry no Python payload: each
# is just a version-locked dependency on kowalski-core plus the component's
# /usr/bin launcher (a symlink into the shared venv) and any assets.
#
# Resulting packages:
#   kowalski-core     venv + /usr/bin/{kow,kow-setup} + systemd user unit
#   kowalski-ui       /usr/bin/kow-omni + XFCE theme/onboarding
#   kowalski-voice    /usr/bin/kow-voice
#   kowalski-indexer  /usr/bin/kow-index
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
MAINTAINER="wachawo"

echo "==> Copying sources out of the read-only mount"
# setuptools writes <pkg>.egg-info into the source tree, which fails on the
# read-only /repo bind mount — build from a writable copy instead.
SRC=/tmp/src
rm -rf "$SRC"
mkdir -p "$SRC"
for pkg in core indexer ui voice setup; do
    cp -a "$REPO/$pkg" "$SRC/$pkg"
done

echo "==> Building shared venv at $VENV (all components)"
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
# Non-editable installs copy the code into the venv (the /repo mount is gone
# after the build); pull the cross-package deps from PyPI. Installing every
# component here is what lets the thin packages ship only a symlink.
"$VENV/bin/pip" install -q \
    "$SRC/core[api,pydantic-ai]" \
    "$SRC/indexer" \
    "$SRC/ui" \
    "$SRC/voice" \
    "$SRC/setup"

# --- helpers -------------------------------------------------------------------

# stage_root <name> -> echoes the staging dir and creates DEBIAN/.
stage_root() {
    local name="$1"
    local dir="/tmp/stage/${name}"
    rm -rf "$dir"
    install -d "$dir/DEBIAN"
    printf '%s' "$dir"
}

# write_control <staging> <pkg> <depends> <recommends> <description...>
# Computes Installed-Size from the staged tree.
write_control() {
    local staging="$1" pkg="$2" depends="$3" recommends="$4" desc="$5"
    local kb
    kb="$(du -sk "$staging" | cut -f1)"
    {
        echo "Package: $pkg"
        echo "Version: $VERSION"
        echo "Section: utils"
        echo "Priority: optional"
        echo "Architecture: $ARCH"
        echo "Depends: $depends"
        [ -n "$recommends" ] && echo "Recommends: $recommends"
        echo "Installed-Size: $kb"
        echo "Maintainer: $MAINTAINER"
        printf '%s\n' "$desc"
    } > "$staging/DEBIAN/control"
}

# build_pkg <staging> <pkg>
build_pkg() {
    local staging="$1" pkg="$2"
    local out="$OUT/${pkg}_${VERSION}_${ARCH}.deb"
    dpkg-deb --root-owner-group --build "$staging" "$out"
    echo "==> Built $out"
    dpkg-deb --info "$out"
}

# =============================================================================
# kowalski-core — the heavy base: shared venv + base launchers + systemd unit.
# =============================================================================
echo "==> Staging kowalski-core"
CORE="$(stage_root kowalski-core)"
install -d "$CORE$PREFIX" "$CORE/usr/bin" "$CORE/usr/lib/systemd/user"
cp -a "$PREFIX/." "$CORE$PREFIX/"

# Base launchers: the headless agent (kow) and first-run setup (kow-setup).
for bin in kow kow-setup; do
    ln -sf "$VENV/bin/$bin" "$CORE/usr/bin/$bin"
done

cp "$REPO/packaging/systemd/kowalski-core.service" \
   "$CORE/usr/lib/systemd/user/kowalski-core.service"

write_control "$CORE" kowalski-core \
    "python3 (>= 3.12)" \
    "fd-find, ripgrep, plocate, bubblewrap" \
    "Description: Kowalski OS agent core (headless)
 The base of the Kowalski OS AI-native desktop: the kow-core agent daemon plus
 the kow and kow-setup commands, bundled with their Python runtime in a
 self-contained virtualenv under /opt/kowalski/venv. This venv is built with
 every Kowalski component installed, so the thin kowalski-ui / kowalski-voice /
 kowalski-indexer packages reuse it instead of duplicating ~hundreds of MB of
 compiled dependencies. Installed alone this is a fully functional headless
 agent. Enable the daemon per user with:
 systemctl --user enable --now kowalski-core"

cat > "$CORE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
# The bundled venv records its build path; nothing to relocate (it is built at
# the final /opt/kowalski/venv). Refresh systemd's user unit cache if running.
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$CORE/DEBIAN/postinst"

build_pkg "$CORE" kowalski-core

# =============================================================================
# kowalski-ui — thin: kow-omni launcher + XFCE theme/onboarding.
# =============================================================================
echo "==> Staging kowalski-ui"
UI="$(stage_root kowalski-ui)"
install -d "$UI/usr/bin" "$UI/usr/share/kowalski" "$UI/etc/xdg/autostart"
ln -sf "$VENV/bin/kow-omni" "$UI/usr/bin/kow-omni"

install -m 0755 "$REPO/packaging/theme/apply-theme.sh" \
   "$UI/usr/share/kowalski/apply-theme.sh"
install -m 0755 "$REPO/packaging/theme/kowalski-onboarding" \
   "$UI/usr/bin/kowalski-onboarding"
install -m 0644 "$REPO/packaging/theme/kowalski-onboarding.desktop" \
   "$UI/etc/xdg/autostart/kowalski-onboarding.desktop"

write_control "$UI" kowalski-ui \
    "kowalski-core (= $VERSION)" \
    "xdotool, wmctrl, maim" \
    "Description: Kowalski OS omnibox UI and XFCE onboarding
 The Kowalski OS desktop overlay: the kow-omni omnibox plus the XFCE theme and
 first-login onboarding. This is a thin package — it reuses the shared venv from
 kowalski-core (its kow-omni launcher is a symlink into /opt/kowalski/venv) and
 ships no Python payload of its own."

build_pkg "$UI" kowalski-ui

# =============================================================================
# kowalski-voice — thin: kow-voice launcher.
# =============================================================================
echo "==> Staging kowalski-voice"
VOICE="$(stage_root kowalski-voice)"
install -d "$VOICE/usr/bin"
ln -sf "$VENV/bin/kow-voice" "$VOICE/usr/bin/kow-voice"

write_control "$VOICE" kowalski-voice \
    "kowalski-core (= $VERSION)" \
    "" \
    "Description: Kowalski OS voice front-end
 The kow-voice command for Kowalski OS. This is a thin package — it reuses the
 shared venv from kowalski-core (its kow-voice launcher is a symlink into
 /opt/kowalski/venv) and ships no Python payload of its own. Microphone capture
 and wake-word extras are pip-only and not pulled in by this package."

build_pkg "$VOICE" kowalski-voice

# =============================================================================
# kowalski-indexer — thin: kow-index launcher.
# =============================================================================
echo "==> Staging kowalski-indexer"
INDEXER="$(stage_root kowalski-indexer)"
install -d "$INDEXER/usr/bin"
ln -sf "$VENV/bin/kow-index" "$INDEXER/usr/bin/kow-index"

write_control "$INDEXER" kowalski-indexer \
    "kowalski-core (= $VERSION)" \
    "ripgrep, fd-find" \
    "Description: Kowalski OS semantic indexer
 The kow-index command for Kowalski OS. This is a thin package — it reuses the
 shared venv from kowalski-core (its kow-index launcher is a symlink into
 /opt/kowalski/venv) and ships no Python payload of its own."

build_pkg "$INDEXER" kowalski-indexer

echo "==> Built all four packages into $OUT:"
ls -1 "$OUT"/kowalski-*_"${VERSION}"_"${ARCH}".deb
