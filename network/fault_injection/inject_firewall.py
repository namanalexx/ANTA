from common import sh, emit

DEVICE = "firewall"
RULE = "FORWARD -p tcp --dport 80 -j DROP"


def inject() -> None:
    sh(DEVICE, f"iptables -C {RULE} 2>/dev/null || iptables -I {RULE}")
    emit("firewall_block", "inject", DEVICE, port=80, protocol="tcp")


if __name__ == "__main__":
    inject()
