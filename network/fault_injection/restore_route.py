from common import sh, emit

DEVICE = "router"
DEST = "10.10.3.0/24"
GATEWAY = "10.10.2.3"


def restore() -> None:
    sh(DEVICE, f"ip route replace {DEST} via {GATEWAY}")
    emit("broken_route", "restore", DEVICE, dest=DEST, via=GATEWAY)


if __name__ == "__main__":
    restore()
