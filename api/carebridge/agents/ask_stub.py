"""Rule-based answers to the outreach lead's questions, from a finished PlanResponse.

Stands in for the coordinator's Q&A until the ADK graph runs. It covers the
README's seven questions and the "questions that need more than we gave you",
and it refuses where the data cannot answer: respiratory trends are a
four-county figure, PM2.5 is a 12 km grid, distances are straight lines, and
nothing is ever said about individuals. Each answer names the grain it rests on.
"""
import re

from ..contracts.api_models import PlanResponse
from ..contracts.interaction_models import AskResponse
from .trace import tract_label

TRACT = "census_tract_11char"
GRID = "epa_12km_grid_on_tract_id"
FACILITY = "facility_lon_lat_point"
HSA = "multi_county_health_service_area"

SUGGESTIONS = [
    "Which neighborhoods need the van most?",
    "Why didn't we pick the tract with the highest need?",
    "Is respiratory illness rising in this neighborhood?",
    "Who does this plan reach?",
    "How far is each stop from a clinic that takes the uninsured?",
]

LOCAL = re.compile(r"neighbou?rhood|street|tract|block|here|this area|local", re.I)


def _has(pattern: str, q: str) -> bool:
    return re.search(pattern, q, re.I) is not None


def _mentioned_tract(q: str) -> str | None:
    m = re.search(r"tract\s*(\d{1,4})(?:\.(\d{2}))?", q, re.I)
    if not m:
        return None
    return f"13121{int(m.group(1)):04d}{m.group(2) or '00'}"


def answer(question: str, r: PlanResponse, request_id: str) -> AskResponse:
    q = question.strip()
    plan = r.final_plan
    stops = plan.stops if plan else []
    citations = list(r.provenance[:2])

    def reply(text: str, agent: str, grain: str | None, refused: bool = False, cites: list[str] | None = None):
        return AskResponse(request_id=request_id, answer=text, answered_by=agent, grain=grain, refused=refused,
                           citations=citations if cites is None else cites,
                           follow_ups=[s for s in SUGGESTIONS if s.lower() != q.lower()][:3])

    if _has(r"\b(which|what) (people|patients|residents|person)\b|\bnames?\b|\bindividual|\bpatients?\b|"
            r"\bwho (exactly|specifically)\b", q):
        return reply("I can't answer that, and nothing in this system can. Individual-level health data is "
                     "prohibited here. I can tell you about places (census tracts of about 4,000 people), "
                     "never about specific people.", "coordinator", None, refused=True, cites=[])

    if _has(r"covid|flu|influenza|\brsv\b|respiratory|rising|surge|outbreak", q):
        note = r.outreach.regional_surveillance_note_en if r.outreach else ""
        local = LOCAL.search(q) is not None
        lead = ("I can't tell you that about a neighborhood, and neither can any public dataset we have. "
                if local else "")
        return reply(f"{lead}Respiratory emergency-visit data covers the whole four-county Health Service Area "
                     f"(Fulton, DeKalb, Clayton and Gwinnett), not a tract. {note} The plan gives it no weight.",
                     "evidence_validator", HSA, refused=local, cites=["a4i_health.disease_weekly"])

    if _has(r"\bair\b|pm ?2\.?5|pollution|smog|particulate", q):
        return reply("Air quality comes from a 12 km modeling grid wearing tract IDs, so neighboring tracts get "
                     "nearly the same value. It can't tell neighborhoods apart, so it has zero weight in the "
                     "ranking and I won't rank places on it.", "evidence_validator", GRID,
                     refused=LOCAL.search(q) is not None, cites=["a4i_health.exposure_tracts"])

    if _has(r"\bbus\b|transit|travel time|how long|marta|journey", q):
        return reply("I don't have travel times. No license-clean federal dataset of travel time to care exists, "
                     "and MARTA's Saturday schedule isn't loaded yet. Every distance here is a straight line to a "
                     "federal clinic, so it's an upper bound on distance, not a journey time.",
                     "evidence_validator", FACILITY, refused=True)

    if _has(r"why (not|didn.?t)|not (picked|chosen)|left out|skip|didn.?t (we )?(pick|choose)", q) or \
            (_mentioned_tract(q) and not _has(r"\bwhy (here|this)\b", q)):
        gid = _mentioned_tract(q)
        chosen = next((s for s in stops if s.primary_tract_geoid == gid), None) if gid else None
        if chosen:
            return reply(f"{tract_label(gid)} is stop {chosen.stop_rank} ({chosen.assigned_saturday}). "
                         f"{chosen.plain_language_rationale}", "siting_planner", TRACT,
                         cites=chosen.evidence_citations)
        covered = next((s for s in stops if gid in s.covered_tract_geoids), None) if gid else None
        if covered:
            return reply(f"{tract_label(gid)} wasn't picked as a stop, but it's inside stop {covered.stop_rank}'s "
                         f"{covered.catchment_radius_km:.0f} km catchment, so the van comes within reach on "
                         f"{covered.assigned_saturday}.", "siting_planner", TRACT)
        runners = plan.runner_up_tracts if plan else []
        picked = [u for u in runners if u.tract_geoid == gid] if gid else runners[:3]
        if not picked:
            return reply(f"{tract_label(gid)} isn't among the highest-need tracts left unreached under this "
                         "strategy." if gid else "Every high-need tract is inside a selected catchment.",
                         "siting_planner", TRACT)
        lines = [u.technical_deferral_rationale for u in picked]
        if r.outreach:
            notes = {n.tract_geoid: n.english_explanation for n in r.outreach.unpicked_neighborhood_explanations}
            lines += [f"What to tell people there: {notes[u.tract_geoid]}" for u in picked[:1] if u.tract_geoid in notes]
        return reply(" ".join(lines), "siting_planner", TRACT)

    if _has(r"\brace\b|black|hispanic|latin|asian|white|equity|fair|parity|who (does|will) (this|the plan) "
            r"(reach|serve)|who.*reach", q):
        a = r.audit_report
        if a is None:
            return reply("The equity audit hasn't run for this plan.", "equity_auditor", None, refused=True)
        di = a.demographic_impact
        groups = "; ".join(f"{g} {v['catchment_pct']:.1f}% vs {v['county_pct']:.1f}% county-wide"
                           for g, v in list(di.group_comparisons.items())[:4])
        findings = (" Flagged for human review: " + " ".join(di.disparity_findings)) if di.disparity_findings \
            else " No group falls below the 0.80 parity floor."
        return reply(f"The four catchments reach about {di.catchment_total_pop:,} of {di.county_total_pop:,} "
                     f"residents. {groups}.{findings} This comparison is auditor-only: the planner never saw "
                     "race or ethnicity.", "equity_auditor", TRACT,
                     cites=["bigquery-public-data.census_bureau_acs.censustract_2020_5yr (auditor only)"])

    if _has(r"not (being )?(seen|treated|getting care)|unseen|untreated|unmet|go(ing|es)? without|"
            r"without (a )?(doctor|care|checkups?)|no (doctor|regular care|checkups?)|miss(ing|ed)? (care|checkups?)|"
            r"can.?t (get|see) (care|a doctor|seen)|checkups?|preventive", q):
        parts = [f"{tract_label(s.primary_tract_geoid)} (stop {s.stop_rank}): chronic illness "
                 f"{s.score_breakdown.chronic_respiratory_norm:.2f}, checkup gap "
                 f"{s.score_breakdown.checkup_preventive_gap_norm:.2f}, distance to a safety-net clinic "
                 f"{s.score_breakdown.safety_net_distance_norm:.2f}" for s in stops]
        runners = plan.runner_up_tracts[:3] if plan else []
        missed = [f"{tract_label(u.tract_geoid)} (need rank {u.need_rank}, "
                  f"{u.distance_to_nearest_selected_stop_km:.1f} km from stop {u.covered_by_stop_rank or 1})"
                  for u in runners]
        tail = (" High-need areas no stop reaches yet: " + "; ".join(missed) + ".") if missed else ""
        return reply("Nothing here counts sick people or who sees a doctor, so I can't name people or count "
                     "missed visits. The closest tract-level signal combines modeled chronic illness (CDC PLACES), "
                     "a low routine-checkup rate and distance to a safety-net clinic, each 0–1 within the county "
                     "(1 = worst). The plan's stops: " + "; ".join(parts) + "." + tail
                     + " These are model estimates, not counts.", "health_access", TRACT,
                     cites=["a4i_health.burden_tracts", "a4i_health.tract_access"])

    if _has(r"shortage|hpsa|underserved|federal(ly)? (designat|said)", q):
        check = next((c for c in (r.evidence_report.checks if r.evidence_report else [])
                      if c.check_name == "shortage_areas_present"), None)
        return reply("No, not in Fulton right now. " + (check.detail if check else "")
                     + " No signal isn't the same as no shortage, so the plan relies on uninsured share and "
                     "distance instead.", "evidence_validator", "hrsa_mixed_grain_component",
                     cites=["a4i_health.shortage_areas"])

    if _has(r"how far|distance|\bkm\b|clinic|safety.?net", q):
        parts = [f"Stop {s.stop_rank} ({tract_label(s.primary_tract_geoid)}): safety-net distance score "
                 f"{s.score_breakdown.safety_net_distance_norm:.2f}" for s in stops]
        return reply("; ".join(parts) + ". Scores are 0–1 within the county (1 = furthest). Distances are "
                     "straight lines to federal sites only, so they're upper bounds.", "health_access", FACILITY,
                     cites=["a4i_health.tract_access"])

    if _has(r"\bcar\b|vehicle|transport|get to|mobility", q):
        parts = [f"stop {s.stop_rank} ({tract_label(s.primary_tract_geoid)}) {s.score_breakdown.no_vehicle_norm:.2f}"
                 for s in stops]
        return reply("No-car and mobility scores (0–1 within the county): " + "; ".join(parts) + ". This mixes "
                     "ACS vehicle ownership with modeled PLACES mobility and transport measures.",
                     "health_access", TRACT)

    if _has(r"need|sick|uninsured|most|where|which|why (here|these)|plan|stop|saturday", q):
        parts = [f"{s.assigned_saturday}: {tract_label(s.primary_tract_geoid)}, need "
                 f"{s.score_breakdown.composite_need_score:.2f}, ~{s.estimated_population_in_catchment:,} residents "
                 "within reach" for s in stops]
        return reply("The four stops: " + "; ".join(parts) + ". Each is placed so its 4 km catchment covers as "
                     "many high-need residents as possible. Prevalence figures are CDC PLACES model estimates, "
                     "not counts.", "siting_planner", TRACT, cites=stops[0].evidence_citations if stops else None)

    return reply("I can answer questions about where the van goes and why, who the plan reaches, what the "
                 "data can't tell us, and why a neighborhood wasn't picked. Try one of the suggestions.",
                 "coordinator", None, cites=[])
