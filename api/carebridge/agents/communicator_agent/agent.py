"""Community Communications Agent (plan 08): bilingual flyers from `final_plan`.

The LlmAgent writes only the prose. Ranks, dates, venues, tract ids and
distances are copied from `final_plan` into `OutreachMessages` here, so the
model cannot move a stop or invent a booking. Each notice is checked; any text
that is missing, claims a booking, or quotes a statistic is replaced by the
`draft_outreach` template for that item, so the result is always a valid
`OutreachMessages`.
"""
import json
import re
from datetime import date
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types
from pydantic import BaseModel, ValidationError

from ...config import Settings
from ...contracts.evidence_models import RegionalDiseaseSignal
from ...contracts.outreach_models import OutreachMessages
from ...contracts.plan_models import DraftPlan, ProposedClinicStop
from ...security.model_armor import default_vertex_safety_settings
from ...security.owasp_guardrails import UNVERIFIED_BOOKING_CLAIM_REGEX, before_model_guardrail_callback
from ...security.race_blind_guard import assert_race_blind_planner_input
from ..trace import tract_label
from .prompts import COMMUNICATOR_INSTRUCTION

STATE_COMMUNICATIONS_BRIEF = "temp:communications_brief"  # this run only; never persisted

PROVISIONAL_EN = "The exact place is not confirmed yet."
PROVISIONAL_ES = "El lugar exacto todavía no está confirmado."

SERVICES = {
    "en": ["free blood pressure checks", "free blood sugar checks", "routine check-ups",
           "no insurance needed", "no appointment needed"],
    "es": ["revisión gratis de la presión", "revisión gratis del azúcar en la sangre", "chequeos de rutina",
           "no necesita seguro", "no necesita cita"],
}

_MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
              "octubre", "noviembre", "diciembre"]

# Highest normalized need components → the words a resident would recognize.
_REASONS = {
    "uninsured_norm": "many people here have no health insurance",
    "safety_net_distance_norm": "the nearest free or low-cost clinic is far away",
    "no_vehicle_norm": "many homes here do not have a car",
    "chronic_respiratory_norm": "many people here live with long-term health problems",
    "checkup_preventive_gap_norm": "many people here have not had a check-up in a while",
}

_DEFERRAL = {
    "catchment_already_covered": "a nearby stop already reaches this area",
    "inter_stop_separation_constraint": "a stop is already very close by, and the four Saturdays are spread out "
                                        "to reach four different areas",
    "no_saturday_transit_or_venue": "we could not yet find a Saturday bus route and a place to park the van here",
    "lower_marginal_coverage": "there are only four Saturdays, and other stops could reach more people who live "
                               "far from a clinic",
}

_BOOKED = re.compile(r"\b(booked|reserved|reservad[oa]s?|guaranteed|garantizad[oa]s?)\b", re.I)
_STATISTIC = re.compile(r"%|\bpercent|\bpor ?ciento|\bper cent", re.I)


def saturday_en(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"Saturday, {d.strftime('%B')} {d.day}"


def saturday_es(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"sábado {d.day} de {_MONTHS_ES[d.month - 1]}"


def _area(geoid: str) -> dict:
    label = tract_label(geoid)
    return {"en": f"Census {label}", "es": f"el sector censal {label.split(' ', 1)[1]}"}


def _reasons(stop: ProposedClinicStop) -> list[str]:
    b = stop.score_breakdown.model_dump()
    top = sorted(_REASONS, key=lambda k: b.get(k, 0.0), reverse=True)[:2]
    return [_REASONS[k] for k in top if b.get(k, 0.0) > 0]


def build_brief(final: DraftPlan, regional: RegionalDiseaseSignal, county_name: str) -> dict:
    """Everything the model may say, from `final_plan` and the regional disease note only."""
    by_rank = {s.stop_rank: s for s in final.stops}
    return {
        "county_name": county_name,
        "services": SERVICES,
        "stops": [{
            "stop_rank": s.stop_rank, "date_en": saturday_en(s.assigned_saturday),
            "date_es": saturday_es(s.assigned_saturday), "area": _area(s.primary_tract_geoid),
            "reasons": _reasons(s),
        } for s in final.stops],
        "unpicked": [{
            "tract_geoid": r.tract_geoid, "area": _area(r.tract_geoid),
            "reason": _DEFERRAL.get(r.deferral_reason_code, _DEFERRAL["lower_marginal_coverage"]),
            "nearby_stop": None if (s := by_rank.get(r.covered_by_stop_rank)) is None else {
                "date_en": saturday_en(s.assigned_saturday), "date_es": saturday_es(s.assigned_saturday),
                "area": _area(s.primary_tract_geoid),
                "about_miles": max(1, round(r.distance_to_nearest_selected_stop_km / 1.609)),
            },
        } for r in final.runner_up_tracts],
        "regional": {"area": regional.hsa_counties, "latest_week": regional.latest_week_end,
                     "data_unavailable": regional.data_unavailable},
    }


class _StopText(BaseModel):
    stop_rank: int
    english_notice: str
    spanish_notice: str
    why_chosen_explanation: str


class _UnpickedText(BaseModel):
    tract_geoid: str
    english_explanation: str
    spanish_explanation: str


class CommunicationsDraft(BaseModel):
    """What the model writes: prose only, keyed to the plan's ranks and tracts."""
    stops: list[_StopText]
    unpicked: list[_UnpickedText]
    regional_note_en: str
    regional_note_es: str


def _instruction(ctx: ReadonlyContext) -> str:
    brief = ctx.state[STATE_COMMUNICATIONS_BRIEF]
    return COMMUNICATOR_INSTRUCTION.format(
        county_name=brief["county_name"], hsa_counties=brief["regional"]["area"],
        provisional_en=PROVISIONAL_EN, provisional_es=PROVISIONAL_ES,
        brief=json.dumps({k: v for k, v in brief.items() if k != "county_name"}, ensure_ascii=False, indent=1))


def _before_model(callback_context: Any, llm_request: Any) -> None:
    before_model_guardrail_callback(callback_context, llm_request)
    assert_race_blind_planner_input(str(llm_request.config.system_instruction) + str(llm_request.contents))


def build_communicator_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="community_communications_writer",
        model=settings.gemini_model_fast,
        description="Writes warm, plain EN/ES flyers and 'why not here' notes from final_plan. No bookings.",
        instruction=_instruction,
        output_schema=CommunicationsDraft,
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, safety_settings=default_vertex_safety_settings()),
        before_model_callback=_before_model,
    )


def _ok(text: str | None) -> bool:
    return bool(text and text.strip()) and not (
        UNVERIFIED_BOOKING_CLAIM_REGEX.search(text) or _BOOKED.search(text) or _STATISTIC.search(text))


def _with_provisional(text: str, sentence: str) -> str:
    text = text.strip()
    return text if sentence.lower() in text.lower() else f"{text}\n\n{sentence}"


def merge_outreach(raw: str | None, template: OutreachMessages) -> tuple[OutreachMessages, list[str]]:
    """Lay the model's prose over the template; returns the result and what fell back."""
    try:
        draft = CommunicationsDraft.model_validate_json(raw or "")
    except ValidationError as exc:
        return template, [f"model output invalid ({exc.error_count()} error(s)); used the template"]
    fallbacks: list[str] = []
    stops = {s.stop_rank: s for s in draft.stops}
    notices = []
    for t in template.stop_notices:
        m = stops.get(t.stop_rank)
        if m and _ok(m.english_notice) and _ok(m.spanish_notice) and _ok(m.why_chosen_explanation):
            t = t.model_copy(update={
                "english_notice": _with_provisional(m.english_notice, PROVISIONAL_EN),
                "spanish_notice": _with_provisional(m.spanish_notice, PROVISIONAL_ES),
                "why_chosen_explanation": m.why_chosen_explanation.strip()})
        else:
            fallbacks.append(f"stop {t.stop_rank}")
        notices.append(t)
    unpicked_by_tract = {u.tract_geoid: u for u in draft.unpicked}
    unpicked = []
    for t in template.unpicked_neighborhood_explanations:
        m = unpicked_by_tract.get(t.tract_geoid)
        if m and _ok(m.english_explanation) and _ok(m.spanish_explanation):
            t = t.model_copy(update={"english_explanation": m.english_explanation.strip(),
                                     "spanish_explanation": m.spanish_explanation.strip()})
        else:
            fallbacks.append(f"why-not-here {tract_label(t.tract_geoid)}")
        unpicked.append(t)
    regional = {}
    if _ok(draft.regional_note_en) and _ok(draft.regional_note_es):
        regional = {"regional_surveillance_note_en": draft.regional_note_en.strip(),
                    "regional_surveillance_note_es": draft.regional_note_es.strip()}
    else:
        fallbacks.append("regional note")
    out = template.model_copy(update={"stop_notices": notices, "unpicked_neighborhood_explanations": unpicked,
                                      **regional})
    return OutreachMessages.model_validate(out.model_dump()), fallbacks
