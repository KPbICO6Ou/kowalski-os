FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv sudo cloud-init ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/ansible && /opt/ansible/bin/pip install --no-cache-dir "ansible-core>=2.16,<2.18"
ENV PATH="/opt/ansible/bin:${PATH}"

COPY run-smoke.sh /usr/local/bin/run-smoke.sh
RUN chmod +x /usr/local/bin/run-smoke.sh

ENTRYPOINT ["/usr/local/bin/run-smoke.sh"]
