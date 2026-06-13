# Packaging

## .deb (kowalski-core + thin component packages)

Kowalski ships as **four** `.deb` packages: a heavy base, `kowalski-core`, plus
three thin component packages that depend on it.

### Why a shared venv + thin packages

Kowalski's Python dependencies (`ollama`, `pydantic-ai`, `pydantic-ai-toolbox`,
…) are not in the Ubuntu archive, so the packages do not declare them as deb
dependencies. Instead a self-contained virtualenv is bundled at
`/opt/kowalski/venv` (built at its final install path so the script shebangs are
valid post-install).

The components share ~all of those dependencies, so duplicating the venv per
component would waste ~hundreds of MB four times over. Instead the venv is built
**once** with *every* component installed and shipped only in `kowalski-core`.
The thin packages carry no Python payload at all — each contributes only a
`/usr/bin` launcher that is a **symlink into the shared venv** (the executable
already exists there because the base venv installed every component), plus any
component assets. They are version-locked to the exact base they were built
against via `Depends: kowalski-core (= <version>)`.

### The four packages

| Package | Ships | Depends | Recommends |
| --- | --- | --- | --- |
| `kowalski-core` | the venv at `/opt/kowalski/venv`, `/usr/bin/kow` + `/usr/bin/kow-setup`, the systemd **user** unit `/usr/lib/systemd/user/kowalski-core.service` | `python3 (>= 3.12)` | `fd-find, ripgrep, plocate, bubblewrap` |
| `kowalski-ui` | `/usr/bin/kow-omni` (symlink), XFCE theme + onboarding (`apply-theme.sh` → `/usr/share/kowalski/`, `kowalski-onboarding` → `/usr/bin/`, autostart `.desktop` → `/etc/xdg/autostart/`) | `kowalski-core (= <version>)` | `xdotool, wmctrl, maim` |
| `kowalski-voice` | `/usr/bin/kow-voice` (symlink); mic/wake extras are pip-only | `kowalski-core (= <version>)` | — |
| `kowalski-indexer` | `/usr/bin/kow-index` (symlink) | `kowalski-core (= <version>)` | `ripgrep, fd-find` |

Dependency graph:

```
kowalski-ui ─┐
kowalski-voice ─┼─→ kowalski-core (= version) ─→ python3 (>= 3.12)
kowalski-indexer ─┘
```

`kowalski-core` installed alone is a fully functional **headless agent** (it has
`kow` and `kow-setup`); it does *not* provide `/usr/bin/kow-omni` — that comes
only with `kowalski-ui`.

### Build and verify

```bash
make deb        # build all four into dist/ in Docker (ubuntu:24.04)
make test-deb   # build, then install into a clean container and smoke-test every CLI
```

Output filenames: `kowalski-core_<version>_<arch>.deb`,
`kowalski-ui_<version>_<arch>.deb`, `kowalski-voice_<version>_<arch>.deb`,
`kowalski-indexer_<version>_<arch>.deb`.

The build is architecture-specific (the venv contains compiled wheels), so build
on the target arch — `make deb` on Apple Silicon yields `arm64` packages, the CI
job on `ubuntu-latest` yields `amd64`.

### Install

Headless agent only:

```bash
sudo apt install ./kowalski-core_<version>_<arch>.deb
systemctl --user enable --now kowalski-core
```

Add the omnibox (and/or voice, indexer) — install the thin package(s) together
with the matching `kowalski-core` so the `= version` dependency resolves:

```bash
sudo apt install ./kowalski-core_<version>_<arch>.deb \
                 ./kowalski-ui_<version>_<arch>.deb
# full desktop: add ./kowalski-voice_*.deb ./kowalski-indexer_*.deb too
```

Because the thin packages are version-locked, upgrade `kowalski-core` and the
component packages in the same `apt` transaction.

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
