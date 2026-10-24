"""Baseline 1: LLM-only. No tools: the model sees the network description and the symptom, and must guess."""
from __future__ import annotations

import time

from agent import llm

from .common import ANSWER_HELP, NETWORK_DESCRIPTION, chat, norm_cause, norm_device, shape

SYSTEM = (
    "You are a network engineer diagnosing a problem in a small lab network. You cannot run any commands; "
    "use only the description and the symptom. "
    'Reply with JSON only: {"cause": "<one cause>", "device": "<one device>", "reason": "<one sentence>"}.'
)


def run_llm_only(symptom: str) -> dict:
    t0 = time.time()
    messages = [
        {"role": "system", "content": f"{SYSTEM}\n\n{NETWORK_DESCRIPTION}\n\n{ANSWER_HELP}"},
        {"role": "user", "content": f"Symptom: {symptom}\nGive your diagnosis."},
    ]
    try:
        out = chat(messages, max_tokens=300)
    except llm.LLMError:
        out = {}
    return shape(symptom, norm_cause(out.get("cause")), norm_device(out.get("device")), [], [],
                 str(out.get("reason", ""))[:400],
                 {"llm_calls": 1, "seconds": round(time.time() - t0, 1)})
