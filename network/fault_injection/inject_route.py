from common import sh, emit

DEVICE = "router"
DEST = "10.10.3.0/24"


def inject() -> None:
    sh(DEVICE, f"ip route del {DEST} 2>/dev/null || true")
    emit("broken_route", "inject", DEVICE, dest=DEST)


if __name__ == "__main__":
    inject()
