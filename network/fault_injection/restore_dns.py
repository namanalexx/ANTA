from common import sh, emit

DEVICE = "dns-server"


def restore() -> None:
    sh(DEVICE, "pgrep -x dnsmasq >/dev/null || dnsmasq -C /etc/dnsmasq.conf")
    emit("dns_failure", "restore", DEVICE, service="dnsmasq")


if __name__ == "__main__":
    restore()
