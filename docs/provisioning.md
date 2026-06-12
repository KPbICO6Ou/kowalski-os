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

## Отложено до появления железа

- реальный прогон роли `nvidia` и warm-pull моделей Ollama;
- проверка загрузки в LightDM/XFCE;
- ветка локальной установки в `kow-setup` (docker compose для STT/TTS);
- интеграция wtftools (`wtf ai`) как диагностического слоя.
