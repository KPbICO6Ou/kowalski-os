# Autoinstall USB

Fully unattended Ubuntu 24.04 Server install for Kowalski OS.

## Building the media

1. Download the Ubuntu 24.04 Server ISO and write it to a USB stick
   (balenaEtcher / `dd`).
2. Create a second small FAT partition (or a second stick) labelled **CIDATA**;
   put these files on it:
   - `user-data` — a copy of `autoinstall.yaml`
   - `meta-data` — an empty file
   - `firstboot.sh` and `kowalski-firstboot.service` from `../files/`
3. Before writing:
   - generate your own password hash: `mkpasswd -m sha-512` → the
     `identity.password` field;
   - add your key to `ssh.authorized-keys`.
4. Boot from the media — the install runs with no questions asked.

## What happens on first boot

`kowalski-firstboot.service` (oneshot) runs `ansible-pull` from this repository
(`provision/local.yml`), which finishes the system: NVIDIA drivers, CUDA,
Docker, Ollama, XFCE + LightDM. On success the service disables itself
(stamp file `/var/lib/kowalski-firstboot.done`).
Log: `/var/log/kowalski-firstboot.log`.

Override the repository: set `KOWALSKI_REPO_URL` in the service environment.

## Alternative without a USB stick

On an already-installed Ubuntu 24.04:

```bash
sudo ansible-pull -U https://github.com/KPbICO6Ou/kowalski-os.git \
    -i provision/inventories/local/hosts.yml provision/local.yml
```
