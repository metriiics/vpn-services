# AmneziaWG 3.1 на VPS

Нужен Ubuntu 24.04 VPS с публичным IPv4, SSH-доступом, устройством `/dev/net/tun` и установленными Git, Docker Engine и Docker Compose. В панели хостинга разрешите входящий `1234/UDP`. [Установка Docker на Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

## 1. Запустите VPN

После публикации репозитория подключитесь к новому VPS по SSH и выполните команды. Замените `203.0.113.10` на публичный IPv4 VPS.

```sh
git clone https://github.com/metriiics/vpn-services.git
cd vpn-services
sudo install -d -o root -g root -m 0700 state
sudo docker compose build --pull awg
sudo docker compose run --rm --no-deps init-profiles 203.0.113.10
sudo docker compose up -d --no-build --wait awg
sudo docker compose ps
```

Скопируйте `state/profiles/client.conf` на своё устройство по SSH и импортируйте в клиент с поддержкой AmneziaWG 3.1. Файл содержит приватный ключ. Храните каталог `state/` вне Git. [Импорт профиля](https://docs.amnezia.org/documentation/instructions/connect-via-config/)

## 2. Запустите веб-панель

Панель можно открыть по `https://ПУБЛИЧНЫЙ_IP_VPS`. Caddy получает и продлевает сертификат Let's Encrypt для публичного IP. Разрешите входящий `80/TCP` для проверки адреса и `443/TCP` для HTTPS. [Сертификаты Let's Encrypt для IP](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)

```sh
cp .env.panel.example .env
chmod 600 .env
sudo docker run --rm -it caddy:2.11.9-alpine caddy hash-password
```

Заполните `.env` перед запуском.

| Переменная | Пример в шаблоне | Что указать |
| --- | --- | --- |
| `AWG_VPN_PUBLIC_IPV4` | `203.0.113.10` | Публичный IPv4 VPS, тот же, что в команде `init-profiles`. Панель записывает его в `Endpoint` новых профилей. |
| `AWG_PANEL_DOMAIN` | `panel.example.com` | Необязательно. Без этой переменной панель использует `AWG_VPN_PUBLIC_IPV4`. При использовании домена укажите его без `https://` и направьте DNS-запись `A` на VPS. |
| `AWG_PANEL_ADMIN_IP` | `198.51.100.25/32` | Ваш публичный IPv4, с которого будете открывать панель, с маской `/32`. |
| `AWG_PANEL_PASSWORD_HASH` | `'PASTE_CADDY_BCRYPT_HASH'` | Хэш, который выдала команда `caddy hash-password`. Сохраните одинарные кавычки. |

**Доступ к панели определяется `AWG_PANEL_ADMIN_IP` в `.env`.** Сейчас `198.51.100.25/32` указан только как пример в `.env.panel.example`. Рабочий IP администратора нужно задать при развёртывании. Запросы с других IP получат `403`.

```sh
sudo docker compose -f compose.yaml -f compose.panel.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.panel.yaml up -d --build --wait
```

Откройте `https://` с публичным IP VPS или настроенным доменом и войдите как `admin` с паролем, который вводили при создании хэша. Если сертификат ещё выпускается, проверьте `sudo docker compose -f compose.yaml -f compose.panel.yaml logs panel-https`. [Подробная настройка панели](AMNEZIAWG.md#веб-панель) · [Анализ DPI](DPI.md)
