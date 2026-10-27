"""CareBridge AI Evidence Validator Agent package (Plan 04)."""

from __future__ import annotations

from carebridge.agents.validator_agent.agent import build_evidence_validator_agent
from carebridge.agents.validator_agent.prompts import VALIDATOR_AGENT_INSTRUCTION
from carebridge.agents.validator_agent.rules import (
    DEFAULT_PROHIBITED_CLAIMS_BLOCKED,
    MANDATORY_EVIDENCE_CAVEATS,
    check,
    evaluate_evidence_quality,
    note,
    validate_collected_evidence,
    validate_collected_evidence_tool,
)

__all__ = [
    "DEFAULT_PROHIBITED_CLAIMS_BLOCKED",
    "MANDATORY_EVIDENCE_CAVEATS",
    "VALIDATOR_AGENT_INSTRUCTION",
    "build_evidence_validator_agent",
    "check",
    "evaluate_evidence_quality",
    "note",
    "validate_collected_evidence",
    "validate_collected_evidence_tool",
]
