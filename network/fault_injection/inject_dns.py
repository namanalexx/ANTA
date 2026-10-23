from common import sh, emit

DEVICE = "dns-server"


def inject() -> None:
    sh(DEVICE, "pkill -x dnsmasq; for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -x dnsmasq >/dev/null || break; sleep 0.2; done; ! pgrep -x dnsmasq >/dev/null")
    emit("dns_failure", "inject", DEVICE, service="dnsmasq")


if __name__ == "__main__":
    inject()
