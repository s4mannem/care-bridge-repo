"""Outreach models for the Community Communications Agent (Explanation Agent)."""

from __future__ import annotations

from typing import List, Optional
from carebridge._compat import BaseModel, Field


class StopOutreachDraft(BaseModel):
    stop_rank: int
    assigned_saturday: str
    candidate_venue_name: str
    english_notice: str = Field(
        ...,
        description="Plain-language 6th-grade reading level English bus-stop flyer draft",
    )
    spanish_notice: str = Field(
        ...,
        description="Plain-language 6th-grade reading level Spanish bus-stop flyer draft",
    )
    why_chosen_explanation: str
    provisional_disclaimer_included: bool = True


class UnpickedNeighborhoodExplanation(BaseModel):
    """Respectful 6th-grade EN/ES explanation for runner-up neighborhoods not selected in the 4-stop rotation."""

    tract_geoid: str
    need_rank: int
    nearest_selected_stop_rank: Optional[int] = None
    distance_to_selected_stop_km: float
    english_explanation: str = Field(
        ...,
        description="Empathetic, honest plain-language explanation of why this neighborhood was not picked and which nearby Saturday stop serves it.",
    )
    spanish_explanation: str = Field(
        ...,
        description="Empathetic, honest Spanish explanation of why this neighborhood was not picked and which nearby Saturday stop serves it.",
    )


class OutreachMessages(BaseModel):
    county_name: str
    provisional_banner: str = (
        "DRAFT FOR INTERNAL REVIEW ONLY — DO NOT PUBLISH UNTIL VENUE PERMITS ARE CONFIRMED."
    )
    stop_notices: List[StopOutreachDraft]
    unpicked_neighborhood_explanations: List[UnpickedNeighborhoodExplanation] = Field(
        default_factory=list,
        description="Answers Question 7: How to tell runner-up neighborhoods why they were not picked.",
    )
    regional_surveillance_note_en: str
    regional_surveillance_note_es: str
