# Packaging

## .deb (kowalski)

Kowalski's Python dependencies (`ollama`, `pydantic-ai`, `pydantic-ai-toolbox`,
…) are not in the Ubuntu archive, so the `.deb` does not declare them as deb
dependencies. Instead it bundles a self-contained virtualenv at
`/opt/kowalski/venv` (built at its final install path so the script shebangs are
valid post-install) and exposes the console entry points as `/usr/bin` symlinks:
`kow`, `kow-omni`, `kow-voice`, `kow-index`, `kow-setup`. The systemd **user**
unit lands at `/usr/lib/systemd/user/kowalski-core.service`.

```bash
make deb        # build dist/kowalski_<version>_<arch>.deb in Docker (ubuntu:24.04)
make test-deb   # build, then install into a clean container and smoke-test every CLI
```

The build is architecture-specific (the venv contains compiled wheels), so build
on the target arch — `make deb` on Apple Silicon yields an `arm64` package, the
CI job on `ubuntu-latest` yields `amd64`.

Install and enable per user:

```bash
sudo apt install ./kowalski_<version>_<arch>.deb
systemctl --user enable --now kowalski-core
```

One bundled package is shipped rather than separate `kowalski-core/ui/voice`
debs: a shared venv avoids duplicating ~hundreds of MB of compiled deps four
times. Splitting later (a base `kowalski` package + thin metapackages) is a
refinement, not a blocker.

## XFCE theme + onboarding

`packaging/theme/` holds the first-login experience (installed by the ISO build,
or droppable into `/etc/xdg/autostart` + `/usr/share/kowalski/`):

- `apply-theme.sh` — idempotent xfconf tweaks (dark Adwaita, minimal panel).
- `kowalski-onboarding` — first-login script (stamp-guarded): apply theme → run
  `kow-setup` once → enable the `kowalski-core` user service.
- `kowalski-onboarding.desktop` — the XFCE autostart entry that runs it.

## ISO (needs hardware / a VM to verify)

The bootable `kowalski-os-<ver>-<arch>.iso` is produced from the Ubuntu 24.04
Server ISO via the autoinstall flow already in `provision/` (see
[provisioning.md](provisioning.md)) — `cloud-init` does an unattended install and
the first-boot `ansible-pull` provisions drivers/CUDA/Docker/Ollama/XFCE and
installs the kowalski `.deb`. Two build paths:

1. **Cubic** (GUI): remaster the Server ISO, preseed `autoinstall.yaml`, drop the
   `.deb` and `provision/` into the squashfs.
2. **autoinstall image**: ship `autoinstall.yaml` on a `CIDATA` volume next to the
   stock ISO (no remaster) — the lowest-maintenance option, documented in
   `provision/autoinstall/README.md`.

ISO assembly and boot are verified on real hardware or a VM, not in CI.
