#!/bin/sh
set -eu
umask 077

endpoint=${1:-}
if ! printf '%s\n' "$endpoint" | awk -F. '
    NR != 1 || NF != 4 { invalid = 1 }
    { for (i = 1; i <= NF; i++) if ($i !~ /^(0|[1-9][0-9]?[0-9]?)$/ || $i > 255) invalid = 1 }
    END { exit (NR != 1 || invalid) }
'; then
    echo 'Usage: docker compose run --rm init-profiles VPS_PUBLIC_IPV4' >&2
    exit 2
fi

lock=/state/.init.lock
if ! mkdir "$lock"; then
    echo 'Another initialization is running or the state directory is not writable.' >&2
    exit 1
fi
work=
trap 'if [ -n "$work" ]; then rm -f "$work/server/awg0.conf" "$work/client.conf"; rmdir "$work/server" 2>/dev/null || true; rmdir "$work"; fi; rmdir "$lock"' EXIT
trap 'exit 143' INT TERM
if [ -e /state/profiles ]; then
    echo 'Profiles already exist. Existing keys and configurations were preserved.' >&2
    exit 1
fi
work=$(mktemp -d /state/.profiles.XXXXXX)
mkdir "$work/server"
templates=/usr/local/share/amneziawg

server_private=$(awg genkey)
server_public=$(printf '%s\n' "$server_private" | awg pubkey)
client_private=$(awg genkey)
client_public=$(printf '%s\n' "$client_private" | awg pubkey)
header_key=$(awg genpsk)
peer_psk=$(awg genpsk)

render_profile() {
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            'PrivateKey = '*) printf 'PrivateKey = %s\n' "$2" ;;
            'PublicKey = '*) printf 'PublicKey = %s\n' "$3" ;;
            'HeaderProtectionKey = '*) printf 'HeaderProtectionKey = %s\n' "$header_key" ;;
            'PresharedKey = '*) printf 'PresharedKey = %s\n' "$peer_psk" ;;
            'Endpoint = '*) printf 'Endpoint = %s:1234\n' "$endpoint" ;;
            *) printf '%s\n' "$line" ;;
        esac
    done < "$1"
}

render_profile "$templates/awg0.conf.example" "$server_private" "$client_public" > "$work/server/awg0.conf"
render_profile "$templates/client.conf.example" "$client_private" "$server_public" > "$work/client.conf"

mv "$work" /state/profiles
work=
echo 'Created state/profiles/server/awg0.conf and state/profiles/client.conf.'
