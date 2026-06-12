FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        dbus dbus-x11 libgirepository1.0-dev gir1.2-glib-2.0 python3-gi \
        fd-find ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
