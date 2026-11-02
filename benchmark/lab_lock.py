"""Only one process may drive the lab at a time: overlapping runs inject and reset each other's faults."""
import fcntl

_HANDLE = None  # kept open for the life of the process; the kernel releases the lock when it exits


def acquire(what: str) -> None:
    global _HANDLE
    _HANDLE = open("/tmp/anta_lab.lock", "w")
    try:
        fcntl.flock(_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f"Another run is already using the lab; {what} refuses to start. "
                         "Check with: pgrep -af 'benchmark.runner|run_eval|run_gate_eval'")
