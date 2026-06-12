#!/bin/bash
# Run core tests (incl. dbus-marked ones) inside Ubuntu 24.04 with a session bus.
set -euo pipefail

eval "$(dbus-launch --sh-syntax)"
export DBUS_SESSION_BUS_ADDRESS

python3.12 -m venv /tmp/venv
/tmp/venv/bin/pip install -q -e /repo/core dasbus PyGObject pytest pytest-asyncio

cd /repo
exec /tmp/venv/bin/pytest core/tests -q "$@"
