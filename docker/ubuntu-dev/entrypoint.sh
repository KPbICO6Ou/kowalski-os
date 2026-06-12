#!/bin/bash
# Run core tests (incl. dbus-marked ones) inside Ubuntu 24.04 with a session bus.
set -euo pipefail

eval "$(dbus-launch --sh-syntax)"
export DBUS_SESSION_BUS_ADDRESS

# --system-site-packages exposes the apt-installed PyGObject (python3-gi);
# pip only installs the pure-Python pieces. Copy the package out of the
# read-only-ish bind mount so pip never writes build artifacts into /repo.
python3.12 -m venv --system-site-packages /tmp/venv
cp -a /repo/core /tmp/core-build
/tmp/venv/bin/pip install -q /tmp/core-build dasbus pytest pytest-asyncio

cd /repo
exec /tmp/venv/bin/pytest core/tests -q "$@"
