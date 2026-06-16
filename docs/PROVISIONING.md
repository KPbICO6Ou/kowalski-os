# Provisioning

Phase-0 goal: "plug in a USB stick → a ready system with a login screen in
20 minutes".

## Flow

1. **Autoinstall USB** — Ubuntu 24.04 Server ISO + `provision/autoinstall/`
   (cloud-init user-data). Fully unattended: user, ssh, base packages.
2. **First boot** — `kowalski-firstboot.service` runs
   `ansible-pull -U <repo> provision/local.yml` and disables itself.
3. **Ansible** finishes the system: sysctl/limits → NVIDIA+CUDA →
   Docker(+toolkit) → Ollama (+models) → XFCE+LightDM → kowalski scaffolding.

Alternative: a remote run over ssh —
`ansible-playbook provision/site.yml -i provision/inventories/remote/hosts.yml`.

## Tags

| Tag | Roles | When to skip |
|---|---|---|
| `base` | sysctl, limits, governor | — |
| `nvidia`, `gpu` | driver, cuda-keyring, toolkit | no NVIDIA / container |
| `docker` | docker-ce, compose, nvidia-container-toolkit (under `gpu`) | — |
| `ollama` | binary, unit, models | model pulls happen on real hardware only |
| `desktop` | xfce4, lightdm, slick-greeter, xorg | fast test iterations |
| `kowalski` | directories, user unit (inert) | — |

Container mode: `-e kowalski_in_container=true` disables systemd/sysctl tasks.

## Architectures

Both **amd64** and **arm64** are supported — the architecture is detected
automatically (`kowalski_deb_arch` / `cuda_repo_arch` in `group_vars/all.yml`):

| Component | amd64 | arm64 |
|---|---|---|
| Docker repo | `arch=amd64` | `arch=arm64` |
| Ollama | `ollama-linux-amd64.tgz` | `ollama-linux-arm64.tgz` |
| CUDA repo | `ubuntu2404/x86_64` | `ubuntu2404/sbsa` (Server Base System Arch) |
| nvidia-container-toolkit | `deb/amd64` | `deb/arm64` |
| Driver | `nvidia-driver-*-server` | `nvidia-driver-*-server` (SBSA) |

⚠ **Jetson (Orin/Xavier) is not covered by this path**: there the driver ships
with L4T/JetPack firmware and CUDA comes from the JetPack repos. On Jetson,
skip the `nvidia` role (`--skip-tags nvidia`) and install the JetPack stack
manually; the docker/ollama/desktop roles work as-is. The Docker smoke test on
Apple Silicon runs in an arm64 container, so the arm64 role branches are
exercised locally on every run.

## Deploy the app onto an existing machine

`provision/deploy.yml` (run via `provision/deploy.sh`) installs just the Kowalski
agent onto a host that already has a desktop — it clones the repo into
`/opt/KowalskiOS`, builds a venv, installs the packages, writes the config,
links the `kow*` launchers into `/usr/local/bin`, enables the `kowalski-core`
systemd **user** service, and installs the XFCE theme + onboarding. The LLM
(Ollama) is *configured*, not installed.

```bash
./provision/deploy.sh <username> [addr]      # addr optional, default 127.0.0.1
```

```bash
./provision/deploy.sh alice                  # deploy locally as alice
./provision/deploy.sh alice 10.0.0.5         # deploy to a remote host over SSH
# point at a remote Ollama and pick models (extra args pass through to ansible):
./provision/deploy.sh alice 10.0.0.5 \
    -e kow_ollama_host=http://10.0.0.6:11434 -e kow_ollama_model=qwen3:8b \
    -e kow_embed_model=bge-m3 -e kow_vision=0
```

It is idempotent (re-running converges to `changed=0`, aside from the optional
pre-deploy profile backup). Useful overrides: `kow_manage_conf=false` (leave a
hand-tuned `kowalski.conf` alone), `kow_theme=false`, `kow_service=false`,
`kow_backup=false`, `kow_prefix=/opt/...`, `kow_version=<branch/tag>`. The
pre-deploy backup lands in `~/kowalski-backups/` for rollback.

## Smoke testing without hardware

```bash
make test-provision        # full: cloud-init schema + 2× playbook (changed=0)
make test-provision-fast   # without desktop packages (order of magnitude faster)
```

## Deferred until hardware is available

- a real run of the `nvidia` role and Ollama model warm-pull;
- boot into LightDM/XFCE verification;
- the local-install branch in `kow-setup` (docker compose for STT/TTS);
- wtftools (`wtf ai`) integration as the diagnostics layer.
