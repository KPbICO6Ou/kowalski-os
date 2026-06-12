# Autoinstall USB

Полностью unattended-установка Ubuntu 24.04 Server для Kowalski OS.

## Сборка носителя

1. Скачай Ubuntu 24.04 Server ISO и запиши на флешку (balenaEtcher / `dd`).
2. Создай второй небольшой FAT-раздел (или вторую флешку) с меткой **CIDATA**;
   положи туда:
   - `user-data` — копия `autoinstall.yaml`
   - `meta-data` — пустой файл
   - `firstboot.sh` и `kowalski-firstboot.service` из `../files/`
3. Перед записью:
   - сгенерируй свой пароль: `mkpasswd -m sha-512` → поле `identity.password`;
   - добавь свой ключ в `ssh.authorized-keys`.
4. Загрузись с носителя — установка пройдёт без вопросов.

## Что происходит на первом буте

`kowalski-firstboot.service` (oneshot) запускает `ansible-pull` из этого
репозитория (`provision/local.yml`), который доводит систему: драйверы NVIDIA,
CUDA, Docker, Ollama, XFCE + LightDM. По успеху сервис отключает сам себя
(стамп `/var/lib/kowalski-firstboot.done`). Лог: `/var/log/kowalski-firstboot.log`.

Переопределить репозиторий: `KOWALSKI_REPO_URL` в окружении сервиса.

## Альтернатива без USB

На уже установленной Ubuntu 24.04:

```bash
sudo ansible-pull -U https://github.com/KPbICO6Ou/kowalski-os.git \
    -i provision/inventories/local/hosts.yml provision/local.yml
```
