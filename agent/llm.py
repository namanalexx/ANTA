"""Minimal Ollama client (stdlib only). Returns parsed JSON dicts; raises LLMError on failure."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("ANTA_MODEL", "qwen2.5:7b")


class LLMError(Exception):
    pass


def chat_json(system: str, user: str, max_tokens: int = 300, retries: int = 1) -> dict:
    payload = {
        "model": os.environ.get("ANTA_MODEL", MODEL),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": max_tokens},
    }
    last = LLMError("no attempt made")
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read())
            data = json.loads(body["message"]["content"])
            if isinstance(data, dict):
                return data
            last = LLMError("LLM returned non-object JSON")
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            last = LLMError(f"{type(e).__name__}: {e}")
    raise last


if __name__ == "__main__":
    t = time.time()
    print(chat_json("Reply with JSON only.", 'Return {"ok": true, "note": "one short sentence"}'))
    print(f"model={MODEL} latency={time.time() - t:.1f}s")
