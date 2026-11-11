#!/bin/sh
set -eu

nft -f - <<'NFT'
add table inet amneziawg
delete table inet amneziawg
table inet amneziawg {
    set restricted_ipv4 {
        type ipv4_addr; flags interval;
        elements = {
            0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16,
            172.16.0.0/12, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/3
        }
    }

    chain input {
        type filter hook input priority filter; policy drop;
        iifname "lo" accept
        iifname "eth0" ct state { established, related } accept
        iifname "eth0" meta nfproto ipv4 udp dport 1234 accept
    }

    chain forward {
        type filter hook forward priority filter; policy drop;
        iifname "awg0" ip daddr @restricted_ipv4 counter drop
        iifname "awg0" oifname "eth0" ip saddr 10.77.38.0/24 accept
        iifname "eth0" oifname "awg0" ip daddr 10.77.38.0/24 ct state { established, related } accept
    }

    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;
        oifname "eth0" ip saddr 10.77.38.0/24 masquerade
    }
}
NFT

amneziawg-go -f awg0 &
daemon=$!
trap 'kill "$daemon" 2>/dev/null || true; wait "$daemon" 2>/dev/null || true' EXIT
trap 'exit 143' INT TERM

attempt=0
until awg show awg0 listen-port >/dev/null 2>&1; do
    if ! kill -0 "$daemon" 2>/dev/null || [ "$attempt" -ge 10 ]; then
        echo 'AmneziaWG did not create a usable interface.' >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 1
done

if ! awg setconf awg0 /etc/amneziawg/awg0.conf 2>/dev/null; then
    echo 'AmneziaWG rejected awg0.conf. Check the server profile locally.' >&2
    exit 1
fi
ip address add 10.77.38.1/24 dev awg0
ip link set dev awg0 mtu 1280 up
wait "$daemon"
