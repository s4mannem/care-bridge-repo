"""CareBridge AI Independent Equity & Rigor Auditor Agent package (`equity_rigor_auditor`)."""

from __future__ import annotations

from carebridge.agents.auditor_agent.agent import build_equity_rigor_auditor_agent, root_agent
from carebridge.agents.auditor_agent.prompts import AUDITOR_AGENT_INSTRUCTION
from carebridge.agents.auditor_agent.tools import (
    execute_independent_plan_audit,
    run_equity_and_rigor_audit,
)

__all__ = [
    "AUDITOR_AGENT_INSTRUCTION",
    "build_equity_rigor_auditor_agent",
    "execute_independent_plan_audit",
    "root_agent",
    "run_equity_and_rigor_audit",
]
