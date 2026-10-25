#!/bin/sh
set -e

# Remove any default route Docker added (keeps the lab isolated from host/internet)
while ip route del default 2>/dev/null; do :; done

# Apply static routes from $ROUTES (semicolon-separated)
if [ -n "${ROUTES:-}" ]; then
  echo "$ROUTES" | tr ';' '\n' | while read -r route; do
    if [ -n "$route" ]; then ip route replace $route; fi
  done
fi

# Optional: render the lab IP plan (the shadow stack sets IP_PREFIX=10.20)
if [ -n "${IP_PREFIX:-}" ]; then
  sed -i "s/10\.10\./${IP_PREFIX}./g" /etc/dnsmasq.conf
fi

# Start the role's service (they daemonize), then keep the container alive
case "${ROLE:-}" in
  dns) dnsmasq -C /etc/dnsmasq.conf ;;
  web) nginx -c /etc/nginx/nginx.conf ;;
esac

echo "[anta] $(hostname) up, role=${ROLE:-none}"
exec sleep infinity
