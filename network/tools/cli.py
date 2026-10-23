"""CLI: python3 -m tools <tool> [args...] [--option value]"""
from __future__ import annotations

import sys

from .base import TOOLS, to_json
from . import diagnostics  # noqa: F401  (registers the tools)


def _coerce(name: str, value: str):
    if name in ("duration_s", "limit"):
        return int(value)
    if name == "probe":  # kind:src:dst, e.g. http:client:10.10.3.20
        kind, src, dst = value.split(":")
        return {"kind": kind, "src": src, "dst": dst}
    return value


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "list"):
        print("Usage: python3 -m tools <tool> [args...] [--option value]\n\nTools:")
        for name, meta in TOOLS.items():
            print(f"  {name:22s} {meta['description']}")
        return 0
    name, rest = argv[0], argv[1:]
    if name not in TOOLS:
        print(f"unknown tool '{name}'. Run: python3 -m tools list", file=sys.stderr)
        return 2
    args, kwargs, i = [], {}, 0
    while i < len(rest):
        if rest[i].startswith("--") and i + 1 < len(rest):
            key = rest[i][2:].replace("-", "_")
            kwargs[key] = _coerce(key, rest[i + 1])
            i += 2
        else:
            args.append(rest[i])
            i += 1
    try:
        result = TOOLS[name]["fn"](*args, **kwargs)
    except TypeError as e:
        print(f"bad arguments for {name}: {e}", file=sys.stderr)
        return 2
    print(to_json(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
