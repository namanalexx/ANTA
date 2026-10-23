"""Shared plumbing for ANTA tools: docker exec runner, error type, JSON helpers, tool registry."""
from __future__ import annotations

import dataclasses
import functools
import json
import re
import subprocess
from typing import Any

NODES = ["client", "router", "firewall", "dns-server", "web-server"]
_TARGET_RE = re.compile(r"[A-Za-z0-9._-]+")


class ToolError(Exception):
    """A tool could not gather facts (bad argument, container down, ...)."""


def check_node(node: str) -> str:
    if node not in NODES:
        raise ToolError(f"unknown node '{node}' (valid: {', '.join(NODES)})")
    return node


def check_target(value: str, what: str = "target") -> str:
    if not isinstance(value, str) or not _TARGET_RE.fullmatch(value):
        raise ToolError(f"invalid {what} '{value}'")
    return value


def run(node: str, cmd: str, timeout: int = 20) -> tuple[int, str, str]:
    """Run a shell command inside a container. Returns (returncode, stdout, stderr)."""
    check_node(node)
    try:
        res = subprocess.run(
            ["docker", "exec", node, "sh", "-c", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"command timed out on {node}")
    except FileNotFoundError:
        raise ToolError("docker CLI not found")
    if "Error response from daemon" in res.stderr or "No such container" in res.stderr:
        raise ToolError(f"container '{node}' unavailable")
    return res.returncode, res.stdout, res.stderr


def docker(*args: str, timeout: int = 20, merge_stderr: bool = False) -> str:
    """Run a docker CLI command on the host side (inspect, logs, ...)."""
    try:
        res = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        raise ToolError(f"docker {args[0]} unavailable")
    if res.returncode != 0:
        raise ToolError(f"docker {args[0]} failed")
    return res.stdout + (res.stderr if merge_stderr else "")


def to_dict(result: Any) -> dict:
    return dataclasses.asdict(result)


def to_json(result: Any, indent: int | None = 2) -> str:
    return json.dumps(dataclasses.asdict(result), indent=indent)


# name -> {"fn": callable, "description": str, "result": dataclass type}
TOOLS: dict[str, dict[str, Any]] = {}


def tool(result_cls: type, description: str):
    """Register a diagnostic tool. A ToolError becomes a valid result with tool_error set."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ToolError as e:
                return result_cls(tool_error=str(e))
        TOOLS[fn.__name__] = {"fn": wrapper, "description": description, "result": result_cls}
        return wrapper
    return deco
