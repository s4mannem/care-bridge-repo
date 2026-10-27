"""Enforces the non-negotiable race-blind Planner boundary and global PII exclusion rules."""

from __future__ import annotations

import re
from typing import Any
from carebridge._compat import BaseModel

PROHIBITED_PII_COLUMNS: frozenset[str] = frozenset({
    "fqhc_admin_contact_nm",
    "fqhc_admin_contact_email",
    "fqhc_admin_contact_phone_num",
    "npi_practitioner_name",
    "practitioner_name",
    "provider_first_name",
    "provider_last_name",
})

PROHIBITED_PLANNER_DEMOGRAPHIC_KEYS: frozenset[str] = frozenset({
    "rpl_theme3",
    "rpl_themes",
    "spl_theme3",
    "ep_minrty",
    "epl_minrty",
    "pct_minority",
    "pct_black",
    "pct_african_american",
    "pct_hispanic",
    "pct_latino",
    "pct_white",
    "pct_asian",
    "external_demographic_audit",
    "demographic_impact",
})

EMAIL_PHONE_REGEX = re.compile(
    r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\b\d{3}[-.)\s]*\d{3}[-.\s]*\d{4}\b)"
)


class PolicyViolationError(RuntimeError):
    """Raised when PII or prohibited demographic features cross an access boundary."""


def assert_no_pii_in_payload(payload: Any) -> None:
    """Recursively checks dicts/lists/models/strings for prohibited PII columns or email/phone patterns."""
    if isinstance(payload, BaseModel):
        assert_no_pii_in_payload(payload.model_dump())
    elif isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in PROHIBITED_PII_COLUMNS:
                raise PolicyViolationError(f"Prohibited PII column detected: {k}")
            assert_no_pii_in_payload(v)
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            assert_no_pii_in_payload(item)
    elif isinstance(payload, str):
        if EMAIL_PHONE_REGEX.search(payload):
            raise PolicyViolationError("Potential individual PII (email/phone) detected in payload.")


def assert_race_blind_planner_input(payload: Any) -> None:
    """Ensures no race/ethnicity or SVI Theme 3 keys or tokens enter the Planner or Optimizer."""
    assert_no_pii_in_payload(payload)
    if isinstance(payload, BaseModel):
        assert_race_blind_planner_input(payload.model_dump())
    elif isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in PROHIBITED_PLANNER_DEMOGRAPHIC_KEYS:
                raise PolicyViolationError(
                    f"Race-blind boundary violation: key '{k}' is forbidden in Planner/Optimizer."
                )
            assert_race_blind_planner_input(v)
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            assert_race_blind_planner_input(item)
    elif isinstance(payload, str):
        lowered = payload.lower()
        for forbidden_token in PROHIBITED_PLANNER_DEMOGRAPHIC_KEYS:
            if re.search(rf"\b{re.escape(forbidden_token)}\b", lowered):
                raise PolicyViolationError(
                    f"Race-blind boundary violation: token '{forbidden_token}' found in Planner input."
                )
