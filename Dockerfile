FROM golang:1.26 AS awg
RUN git clone --depth 1 --branch v3.1.20260828 https://github.com/amnezia-vpn/amneziawg-go.git /src/awg
WORKDIR /src/awg
RUN go mod download && go mod verify && CGO_ENABLED=0 go build -trimpath -o /out/amneziawg-go .

FROM alpine:3.24 AS tools
RUN apk add --no-cache build-base git linux-headers && \
    git clone --depth 1 --branch v3.1.20260812 https://github.com/amnezia-vpn/amneziawg-tools.git /src/tools && \
    make -C /src/tools/src

FROM alpine:3.24 AS base
COPY --from=tools /src/tools/src/wg /usr/local/bin/awg
RUN awg --version
COPY awg0.conf.example client.conf.example /usr/local/share/amneziawg/

FROM base AS panel
RUN apk add --no-cache python3
COPY docker/panel.py /usr/local/bin/panel.py
ENTRYPOINT ["python3", "-B", "/usr/local/bin/panel.py"]

FROM base AS server
RUN apk add --no-cache iproute2 nftables
COPY --from=awg /out/amneziawg-go /usr/local/bin/
COPY docker/start-server.sh docker/init-profiles.sh /usr/local/bin/
ENTRYPOINT ["/bin/sh", "/usr/local/bin/start-server.sh"]
