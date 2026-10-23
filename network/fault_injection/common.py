"""Shared helpers for ANTA fault injection scripts."""
import json
import subprocess


def sh(container: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command inside a container via docker exec."""
    res = subprocess.run(
        ["docker", "exec", container, "sh", "-c", cmd],
        capture_output=True, text=True,
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"[{container}] `{cmd}` failed: {(res.stderr or res.stdout).strip()}")
    return res


def emit(fault: str, action: str, device: str, **details) -> None:
    print(json.dumps({"fault": fault, "action": action, "device": device, **details}))
