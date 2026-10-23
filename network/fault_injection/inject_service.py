from common import sh, emit

DEVICE = "web-server"


def inject() -> None:
    sh(DEVICE, "pkill -x nginx; for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -x nginx >/dev/null || break; sleep 0.2; done; ! pgrep -x nginx >/dev/null")
    emit("service_failure", "inject", DEVICE, service="nginx")


if __name__ == "__main__":
    inject()
