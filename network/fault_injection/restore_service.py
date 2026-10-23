from common import sh, emit

DEVICE = "web-server"


def restore() -> None:
    sh(DEVICE, "pgrep -x nginx >/dev/null || nginx -c /etc/nginx/nginx.conf")
    emit("service_failure", "restore", DEVICE, service="nginx")


if __name__ == "__main__":
    restore()
