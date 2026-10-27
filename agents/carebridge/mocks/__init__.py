"""Deterministic Fulton County (`13121`) mock fixtures for offline unit and integration tests."""

from __future__ import annotations

from carebridge.mocks.fulton_fixtures import (
    DEMOGRAPHIC_AUDIT_FIXTURES,
    FULTON_CANDIDATE_VENUES,
    FULTON_CARE_SITES,
    FULTON_REGIONAL_DISEASE,
    FULTON_TRACT_HEALTH_RECORDS,
    FULTON_TRACT_MOBILITY_RECORDS,
    build_mock_audit_report,
    build_mock_draft_plan,
    build_mock_evidence_report,
    build_mock_health_evidence,
    build_mock_mobility_evidence,
    build_mock_outreach_messages,
    build_mock_plan_response,
)

__all__ = [
    "DEMOGRAPHIC_AUDIT_FIXTURES",
    "FULTON_CANDIDATE_VENUES",
    "FULTON_CARE_SITES",
    "FULTON_REGIONAL_DISEASE",
    "FULTON_TRACT_HEALTH_RECORDS",
    "FULTON_TRACT_MOBILITY_RECORDS",
    "build_mock_audit_report",
    "build_mock_draft_plan",
    "build_mock_evidence_report",
    "build_mock_health_evidence",
    "build_mock_mobility_evidence",
    "build_mock_outreach_messages",
    "build_mock_plan_response",
]
