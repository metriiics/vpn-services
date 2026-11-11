import base64
import binascii
import fcntl
import hmac
import ipaddress
import os
import re
import secrets
import subprocess
import tempfile
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


CONFIG = Path("/etc/amneziawg/awg0.conf")
CLIENT_TEMPLATE = Path("/usr/local/share/amneziawg/client.conf.example")
TUNNEL = ipaddress.IPv4Network("10.77.38.0/24")
SERVER_ADDRESS = TUNNEL.network_address + 1
PEER_SECTION = re.compile(r"(?mi)(?=^[ \t]*\[Peer\][ \t]*(?:#.*)?$)")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
AWG_OPTIONS = (
    "HeaderProtectionKey", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4",
    "Jc", "Jmin", "Jmax", "I1", "I2", "I3", "I4", "I5", "RandomTrailers",
    "ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout", "RejectAfterTime",
    "KeepaliveTimeout", "MaxHandshakeAttempts", "DisableCookies",
)


def awg(*args, data=None):
    return subprocess.run(
        ["awg", *args], input=data, capture_output=True, text=True, check=True, timeout=8
    ).stdout.strip()


def fields(section):
    options = {}
    for line in section.splitlines():
        key, separator, value = line.split("#", 1)[0].partition("=")
        if separator:
            options[key.strip().lower()] = value.strip()
    return options


def peer_name(section):
    match = re.search(r"(?m)^# PanelName = (.+)$", section)
    return match.group(1) if match else "Без имени"


def allocate_address(peers):
    occupied = [
        ipaddress.ip_network(entry.strip(), strict=False)
        for peer in peers
        for entry in fields(peer).get("allowedips", "").split(",")
        if entry.strip()
    ]
    for address in TUNNEL.hosts():
        if address != SERVER_ADDRESS and all(address not in network for network in occupied):
            return address
    raise ValueError("В подсети VPN закончились свободные адреса.")


def replace_config(content):
    pending = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG.parent, delete=False)
    path = Path(pending.name)
    try:
        with pending:
            pending.write(content)
            pending.flush()
            os.fsync(pending.fileno())
        os.replace(path, CONFIG)
    finally:
        path.unlink(missing_ok=True)


def apply_config(previous, updated):
    replace_config(updated)
    try:
        awg("syncconf", "awg0", str(CONFIG))
    except (OSError, subprocess.SubprocessError):
        replace_config(previous)
        awg("syncconf", "awg0", str(CONFIG))
        raise


def create_peer(previous, name, endpoint):
    if not NAME.fullmatch(name):
        raise ValueError("Имя должно содержать от 1 до 32 латинских букв, цифр, дефисов или подчёркиваний.")
    interface, *peers = PEER_SECTION.split(previous)
    if any(peer_name(peer).lower() == name.lower() for peer in peers):
        raise ValueError("Профиль с таким именем уже есть.")
    address = allocate_address(peers)
    server_options = fields(interface)
    template_options = fields(CLIENT_TEMPLATE.read_text(encoding="utf-8"))
    server_public = awg("pubkey", data=server_options["privatekey"] + "\n")
    private = awg("genkey")
    public = awg("pubkey", data=private + "\n")
    psk = awg("genpsk")
    options = [f"{key} = {server_options[key.lower()]}" for key in AWG_OPTIONS if key.lower() in server_options]
    client = "\n".join([
        "[Interface]", f"PrivateKey = {private}", f"Address = {address}/32",
        f"DNS = {template_options['dns']}", f"MTU = {template_options['mtu']}",
        *options, "", "[Peer]", f"PublicKey = {server_public}", f"PresharedKey = {psk}",
        f"AllowedIPs = {template_options['allowedips']}", f"Endpoint = {endpoint}", "",
    ])
    updated = previous.rstrip() + (
        f"\n\n[Peer]\n# PanelName = {name}\nPublicKey = {public}\n"
        f"PresharedKey = {psk}\nAllowedIPs = {address}/32\n"
    )
    apply_config(previous, updated)
    return client


def revoke_peer(previous, public_key):
    try:
        valid = len(public_key) == 44 and len(base64.b64decode(public_key, validate=True)) == 32
    except binascii.Error:
        valid = False
    if not valid:
        raise ValueError("Некорректный публичный ключ.")
    interface, *peers = PEER_SECTION.split(previous)
    remaining = [peer for peer in peers if fields(peer).get("publickey") != public_key]
    if len(remaining) == len(peers):
        raise ValueError("Профиль не найден.")
    apply_config(previous, interface + "".join(remaining))


class Panel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, content_type, content, filename=None):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def page(self, status=200, message=""):
        token = f'<input type="hidden" name="csrf" value="{self.server.csrf}">'
        rows = []
        for peer in PEER_SECTION.split(CONFIG.read_text(encoding="utf-8"))[1:]:
            options = fields(peer)
            public_key = escape(options.get("publickey", ""))
            address = escape(options.get("allowedips", ""))
            rows.append(f'''<li><span><strong>{escape(peer_name(peer))}</strong><small>{address}</small></span>
                <form method="post" action="/revoke">{token}
                <input type="hidden" name="public_key" value="{public_key}">
                <button class="revoke">Отозвать</button></form></li>''')
        notice = f'<p role="status">{escape(message)}</p>' if message else ""
        html = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1"><title>AmneziaWG · Клиенты</title>
        <style>
          body {{font: 16px/1.5 system-ui,sans-serif; background:#f3f5f9; color:#152033; margin:0}}
          main {{max-width:42rem; margin:3rem auto; padding:0 1rem}}
          section {{background:#fff; border:1px solid #dce2ec; border-radius:12px; padding:1.3rem; margin:1rem 0}}
          h1,h2,p {{margin:0 0 .8rem}} h2 {{font-size:1.2rem}}
          input,button {{font:inherit; padding:.5rem .7rem; border-radius:7px; border:1px solid #8d99ab}}
          button {{cursor:pointer; background:#234bba; border-color:#234bba; color:#fff}}
          .revoke {{background:#fff; border-color:#c48b8b; color:#8a2929}}
          ul {{padding:0; margin:0; list-style:none}} li {{display:flex; align-items:center; justify-content:space-between;
              gap:1rem; padding:.7rem 0; border-bottom:1px solid #dce2ec}} li:last-child {{border-bottom:0}}
          small {{display:block; color:#4e5b70}} a {{color:#234bba}} label {{display:block; margin-bottom:.35rem}}
        </style><main><h1>AmneziaWG · Клиенты</h1>{notice}
        <section><h2>Новый профиль</h2><p>Сохраните файл при выдаче. Приватный ключ нового клиента доступен только в скачанном файле.</p>
        <form method="post" action="/create">{token}<label for="name">Имя устройства</label>
        <input id="name" name="name" required maxlength="32" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]{{0,31}}" placeholder="laptop">
        <button>Скачать .conf</button></form></section>
        <section><h2>Выданные профили</h2><a href="/">Обновить список</a>
        {('<ul>' + ''.join(rows) + '</ul>') if rows else '<p>Профилей пока нет.</p>'}</section></main></html>'''
        self.reply(status, "text/html; charset=utf-8", html)

    def do_GET(self):
        if self.path == "/":
            self.page()
        else:
            self.reply(404, "text/plain; charset=utf-8", "Страница не найдена.")

    def do_POST(self):
        if self.path not in {"/create", "/revoke"}:
            self.reply(404, "text/plain; charset=utf-8", "Страница не найдена.")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError
            form = parse_qs(self.rfile.read(size).decode("utf-8"), max_num_fields=4)
        except (ValueError, UnicodeError):
            self.reply(400, "text/plain; charset=utf-8", "Некорректный запрос.")
            return
        token = form.get("csrf", [""])[0].encode("utf-8")
        if not hmac.compare_digest(token, self.server.csrf.encode("ascii")):
            self.reply(403, "text/plain; charset=utf-8", "Обновите страницу и повторите действие.")
            return
        try:
            with CONFIG.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                previous = CONFIG.read_text(encoding="utf-8")
                if self.path == "/create":
                    name = form.get("name", [""])[0]
                    profile = create_peer(previous, name, self.server.endpoint)
                else:
                    revoke_peer(previous, form.get("public_key", [""])[0])
        except ValueError as error:
            self.page(400, str(error))
            return
        except (KeyError, OSError, subprocess.SubprocessError):
            self.reply(503, "text/plain; charset=utf-8", "Не удалось применить изменения. Проверьте контейнер AmneziaWG по SSH.")
            return
        if self.path == "/create":
            self.reply(200, "application/octet-stream", profile, f"{name}.conf")
        else:
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()


def main():
    os.umask(0o077)
    address = ipaddress.IPv4Address(os.environ["AWG_VPN_PUBLIC_IPV4"])
    with ThreadingHTTPServer(("0.0.0.0", 8080), Panel) as server:
        server.endpoint = f"{address}:1234"
        server.csrf = secrets.token_urlsafe(32)
        server.serve_forever()


if __name__ == "__main__":
    main()
