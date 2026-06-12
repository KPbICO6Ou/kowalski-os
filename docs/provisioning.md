# Provisioning

Цель фазы 0: «вставил флешку → через 20 минут готовая система с логин-экраном».

## Поток

1. **USB c autoinstall** — Ubuntu 24.04 Server ISO + `provision/autoinstall/`
   (cloud-init user-data). Полностью unattended: пользователь, ssh, базовые пакеты.
2. **Первый бут** — `kowalski-firstboot.service` запускает
   `ansible-pull -U <repo> provision/local.yml` и отключает сам себя.
3. **Ansible** доводит систему: sysctl/limits → NVIDIA+CUDA → Docker(+toolkit) →
   Ollama (+модели) → XFCE+LightDM → каркас kowalski.

Альтернатива: удалённый прогон по ssh —
`ansible-playbook provision/site.yml -i provision/inventories/remote/hosts.yml`.

## Теги

| Тег | Роли | Когда пропускать |
|---|---|---|
| `base` | sysctl, limits, governor | — |
| `nvidia`, `gpu` | драйвер, cuda-keyring, toolkit | нет NVIDIA / контейнер |
| `docker` | docker-ce, compose, nvidia-container-toolkit (под `gpu`) | — |
| `ollama` | бинарник, unit, модели | модели — только на железе |
| `desktop` | xfce4, lightdm, slick-greeter, xorg | быстрые итерации теста |
| `kowalski` | каталоги, user unit (инертный) | — |

Контейнерный режим: `-e kowalski_in_container=true` отключает systemd/sysctl-задачи.

## Smoke-тест без железа

```bash
make test-provision        # полный: cloud-init schema + 2×playbook (changed=0)
make test-provision-fast   # без desktop-пакетов (~быстрее на порядок)
```

## Архитектуры

Поддерживаются **amd64** и **arm64** — архитектура определяется автоматически
(`kowalski_deb_arch` / `cuda_repo_arch` в `group_vars/all.yml`):

| Компонент | amd64 | arm64 |
|---|---|---|
| Docker repo | `arch=amd64` | `arch=arm64` |
| Ollama | `ollama-linux-amd64.tgz` | `ollama-linux-arm64.tgz` |
| CUDA repo | `ubuntu2404/x86_64` | `ubuntu2404/sbsa` (Server Base System Arch) |
| nvidia-container-toolkit | `deb/amd64` | `deb/arm64` |
| Драйвер | `nvidia-driver-*-server` | `nvidia-driver-*-server` (SBSA) |

⚠ **Jetson (Orin/Xavier) не покрывается этим путём**: там драйвер входит в L4T/JetPack
и ставится прошивкой, CUDA — из JetPack-репо. Для Jetson пропускайте роль
`nvidia` (`--skip-tags nvidia`) и ставьте JetPack-стек вручную; роли docker/ollama/desktop
работают как есть. Smoke-тест в Docker на Apple Silicon выполняется в arm64-контейнере,
то есть arm64-ветки ролей проверяются локально каждым прогоном.

## Отложено до появления железа

- реальный прогон роли `nvidia` и warm-pull моделей Ollama;
- проверка загрузки в LightDM/XFCE;
- ветка локальной установки в `kow-setup` (docker compose для STT/TTS);
- интеграция wtftools (`wtf ai`) как диагностического слоя.
