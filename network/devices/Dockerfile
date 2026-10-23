FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 iputils-ping traceroute dnsutils dnsmasq iptables \
    tcpdump curl nginx procps ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY dns/dnsmasq.conf /etc/dnsmasq.conf
COPY web/nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
