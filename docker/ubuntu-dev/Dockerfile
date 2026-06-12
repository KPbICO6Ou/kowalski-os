FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# python3-gi provides PyGObject for the system python3.12; the test venv is
# created with --system-site-packages so it is reused (no pip build of
# PyGObject needed). dbus-x11 ships dbus-launch for the session bus.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        dbus dbus-x11 gir1.2-glib-2.0 python3-gi \
        fd-find ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
