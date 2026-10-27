"""Community Communications Agent package (plan 08)."""

from carebridge.agents.communicator_agent.agent import (
    PROVISIONAL_EN,
    PROVISIONAL_ES,
    STATE_COMMUNICATIONS_BRIEF,
    CommunicationsDraft,
    build_brief,
    build_communicator_agent,
    merge_outreach,
)
from carebridge.agents.communicator_agent.prompts import COMMUNICATOR_INSTRUCTION

__all__ = [
    "COMMUNICATOR_INSTRUCTION",
    "PROVISIONAL_EN",
    "PROVISIONAL_ES",
    "STATE_COMMUNICATIONS_BRIEF",
    "CommunicationsDraft",
    "build_brief",
    "build_communicator_agent",
    "merge_outreach",
]
