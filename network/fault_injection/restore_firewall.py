from common import sh, emit

DEVICE = "firewall"
RULE = "FORWARD -p tcp --dport 80 -j DROP"


def restore() -> None:
    sh(DEVICE, f"while iptables -C {RULE} 2>/dev/null; do iptables -D {RULE}; done")
    emit("firewall_block", "restore", DEVICE, port=80, protocol="tcp")


if __name__ == "__main__":
    restore()
