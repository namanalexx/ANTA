"""ANTA agent package. Makes network/ (tools) and network/fault_injection importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "network", ROOT / "network" / "fault_injection"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
