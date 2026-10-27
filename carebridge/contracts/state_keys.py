"""ADK session.state keys and scoped visibility boundaries."""

from __future__ import annotations

from typing import Final

# Input request context injected into session.state by FastAPI Gateway / Coordinator
STATE_PLAN_REQUEST: Final[str] = "plan_request"
STATE_REQUEST_ID: Final[str] = "request_id"

# 01 — Parallel Evidence Collection output_keys (MUST be distinct across ParallelAgent branches!)
STATE_HEALTH_EVIDENCE: Final[str] = "health_evidence"
STATE_MOBILITY_EVIDENCE: Final[str] = "mobility_evidence"

# Sequential Data-Quality & 4-Resolution Gate output_key
STATE_EVIDENCE_REPORT: Final[str] = "evidence_report"

# 02 — Decide, Optimize, Challenge output_keys
STATE_DRAFT_PLAN: Final[str] = "draft_plan"
STATE_AUDIT_REPORT: Final[str] = "audit_report"
STATE_REVISION_REQUIRED: Final[str] = "revision_required"
STATE_NON_DEMOGRAPHIC_FEEDBACK: Final[str] = "non_demographic_feedback"
STATE_REVISION_HISTORY: Final[str] = "revision_history"
STATE_ITERATION_COUNT: Final[str] = "iteration_count"

# Final approved/provisional plan & outreach output_keys
STATE_FINAL_PLAN: Final[str] = "final_plan"
STATE_OUTREACH_MESSAGES: Final[str] = "outreach_messages"

# Scoped visibility boundaries matching the CareBridge AI Architecture Diagram
PLANNER_VISIBLE_STATE_KEYS: Final[tuple[str, ...]] = (
    STATE_PLAN_REQUEST,
    STATE_REQUEST_ID,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_EVIDENCE_REPORT,
    STATE_DRAFT_PLAN,
)

SANITIZED_LOOPBACK_STATE_KEYS: Final[tuple[str, ...]] = (
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_REQUIRED,
    STATE_ITERATION_COUNT,
)

AUDITOR_AND_POST_PLANNER_STATE_KEYS: Final[tuple[str, ...]] = (
    STATE_AUDIT_REPORT,
    STATE_FINAL_PLAN,
    STATE_OUTREACH_MESSAGES,
    STATE_REVISION_HISTORY,
)

ALL_STATE_KEYS: Final[tuple[str, ...]] = (
    STATE_PLAN_REQUEST,
    STATE_REQUEST_ID,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_EVIDENCE_REPORT,
    STATE_DRAFT_PLAN,
    STATE_AUDIT_REPORT,
    STATE_REVISION_REQUIRED,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_HISTORY,
    STATE_ITERATION_COUNT,
    STATE_FINAL_PLAN,
    STATE_OUTREACH_MESSAGES,
)
