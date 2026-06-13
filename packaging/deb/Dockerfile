FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip dpkg-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY build-deb.sh /usr/local/bin/build-deb.sh
RUN chmod +x /usr/local/bin/build-deb.sh

ENTRYPOINT ["/usr/local/bin/build-deb.sh"]
