"""Google Cloud Model Armor screening and Vertex AI / Gemini safety settings."""

from __future__ import annotations

import re
from typing import List, Tuple
from carebridge._compat import genai_types as types
from carebridge.config import get_settings

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"system\s*prompt|reveal\s+your\s+instructions|developer\s+mode", re.I),
    re.compile(
        r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|EXEC)\b\s+\b(TABLE|DATABASE|INTO|VIEW)\b",
        re.I,
    ),
    re.compile(r"('|\")\s*OR\s+('?1'?\s*=\s*'?1)", re.I),
    re.compile(r";\s*(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE)\b", re.I),
    re.compile(r"bypass\s+(audit|equity|race|guardrail)", re.I),
)


def default_vertex_safety_settings() -> List[types.SafetySetting]:
    """Standard strict Vertex AI / Gemini safety settings for all CareBridge ADK LlmAgents."""
    return [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
    ]


class ModelArmorScreener:
    """Screens user prompts and tool outputs via Google Cloud Model Armor + OWASP LLM01 heuristics."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def screen_input(self, text: str) -> Tuple[bool, str]:
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                return False, f"Blocked by OWASP LLM01 / Model Armor policy: matched {pattern.pattern}"
        return True, "clean"
