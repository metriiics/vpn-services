# AmneziaWG 3.1 на VPS

## 1. Подготовьте VPS

На Ubuntu 24.04 с публичным IPv4 откройте в firewall хостинга входящие `1234/UDP`, `80/TCP` и `443/TCP`. Подключитесь по SSH и выполняйте команды под `root`.

```sh
apt update
apt install -y git nano docker.io docker-compose-v2 docker-buildx
systemctl enable --now docker
docker compose version
test -c /dev/net/tun && echo 'TUN OK'
```

Продолжайте после вывода версии Compose и `TUN OK`.

## 2. Скачайте проект

```sh
cd /home
git clone https://github.com/metriiics/vpn-services.git
cd vpn-services
install -d -o root -g root -m 0700 state
```

## 3. Настройте панель

Введите пароль панели дважды по приглашению `caddy hash-password`. Скопируйте последнюю строку вывода целиком.

```sh
docker run --rm -it caddy:2.11.9-alpine caddy hash-password
cp .env.panel.example .env
chmod 600 .env
nano .env
```

Замените `203.0.113.10` публичным IPv4 VPS, а `198.51.100.25` — публичным IPv4 сети, из которой будете открывать панель. Сохраните `/32`. Вставьте полный хэш со всеми знаками `$` между одинарными кавычками. Для входа по IP оставьте `AWG_PANEL_DOMAIN` пустым.

```dotenv
AWG_VPN_PUBLIC_IPV4=203.0.113.10
AWG_PANEL_DOMAIN=
AWG_PANEL_ADMIN_IP=198.51.100.25/32
AWG_PANEL_PASSWORD_HASH='ВСТАВЬТЕ_ПОЛНЫЙ_ХЭШ'
```

## 4. Запустите VPN и панель

В `init-profiles` подставьте тот же IPv4 VPS, который указали в `.env`.

```sh
docker compose -f compose.yaml -f compose.panel.yaml run --rm --no-deps panel-https \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile &&
docker compose -f compose.yaml -f compose.panel.yaml build --pull awg panel &&
docker compose run --rm --no-deps init-profiles 203.0.113.10 &&
docker compose -f compose.yaml -f compose.panel.yaml up -d --no-build --wait
```

## 5. Создайте клиентский профиль

Откройте `https://ПУБЛИЧНЫЙ_IP_VPS` из разрешённой сети. Войдите как `admin` с паролем из шага 3, создайте профиль устройства, скачайте `.conf` и импортируйте его в клиент AmneziaWG 3.1.
