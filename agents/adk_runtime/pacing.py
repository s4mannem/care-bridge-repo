"""Spaces out Gemini calls across every agent in the process.

The lab project's per-minute token quota is tight, and the parallel evidence
agents plus the plan/audit loop fire calls back to back. This gate runs as each
agent's first `before_model_callback` and holds a call until
`GEMINI_MIN_GAP_S` (default 3 s, 0 = off) has passed since the previous one started. Calls queue in
arrival order; nothing is dropped.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

_lock: asyncio.Lock | None = None
_last_start = 0.0


async def pace_model_call(callback_context: Any, llm_request: Any) -> None:
    global _lock, _last_start
    gap = float(os.environ.get("GEMINI_MIN_GAP_S", "3"))
    if gap <= 0:
        return None
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        wait = _last_start + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_start = time.monotonic()
    return None
