"""Equity & rigor audit (plan 07) and outreach drafting (plan 08), deterministic core.

The graph's auditor and communications stand-ins call these until the LLM
agents exist. The demographic query is auditor-only: its output goes into
`audit_report.demographic_impact` and never back to the planner.
"""
from datetime import date

from ..agents.trace import overlap_pair, tract_label
from ..contracts.audit_models import (
    AuditReport,
    AuditVerdict,
    DefectCategory,
    DemographicImpactComparison,
    NonDemographicAuditDefect,
)
from ..contracts.evidence_models import HealthEvidence
from ..contracts.outreach_models import OutreachMessages, StopOutreachDraft, UnpickedNeighborhoodExplanation
from ..contracts.plan_models import DraftPlan
from ..data.bigquery import BigQueryRepo

PARITY_FLOOR = 0.80


def demographic_impact(repo: BigQueryRepo, draft: DraftPlan, health: HealthEvidence) -> DemographicImpactComparison:
    fips = draft.county_fips
    acs = {r["geo_id"]: r for r in repo.query("""
        SELECT geo_id, total_pop, black_pop, hispanic_pop, white_pop, asian_pop
        FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
        WHERE STARTS_WITH(geo_id, @fips)""", {"fips": fips})}
    reached = {g for s in draft.stops for g in s.covered_tract_geoids}

    def pct(ids, col):
        rows = [acs[g] for g in ids if g in acs and acs[g]["total_pop"]]
        pop = sum(float(r["total_pop"]) for r in rows)
        return 100 * sum(float(r[col] or 0) for r in rows) / pop if pop else 0.0

    def theme3(ids):
        rows = [acs[g] for g in ids if g in acs and acs[g]["total_pop"]]
        pop = sum(float(r["total_pop"]) for r in rows)
        return sum(float(r["total_pop"]) - float(r["white_pop"] or 0) for r in rows) / pop if pop else 0.0

    tracts = {t.geo_id: t for t in health.tracts}

    def pw(ids, attr):
        rows = [tracts[g] for g in ids if g in tracts and getattr(tracts[g], attr) is not None and tracts[g].total_pop]
        pop = sum(t.total_pop for t in rows)
        return sum(getattr(t, attr) * t.total_pop for t in rows) / pop if pop else 0.0

    county = set(acs)
    groups = {}
    for name, col in (("Black", "black_pop"), ("Hispanic or Latino", "hispanic_pop"),
                      ("Asian", "asian_pop"), ("White", "white_pop")):
        c, p = pct(county, col), pct(reached, col)
        groups[name] = {"county_pct": round(c, 1), "catchment_pct": round(p, 1),
                        "parity_ratio": round(p / c, 2) if c else 0.0}
    for name, attr in (("Uninsured 18–64", "pct_uninsured_18_64"), ("No vehicle", "pct_no_vehicle"),
                       ("Age 65+", "pct_age_65_plus")):
        c, p = pw(list(tracts), attr), pw(reached, attr)
        groups[name] = {"county_pct": round(c, 1), "catchment_pct": round(p, 1),
                        "parity_ratio": round(p / c, 2) if c else 0.0}
    findings = [f"{g}: catchments reach {v['catchment_pct']}% vs {v['county_pct']}% county-wide "
                f"(parity {v['parity_ratio']:.2f} < {PARITY_FLOOR:.2f})."
                for g, v in groups.items() if g != "White" and v["parity_ratio"] < PARITY_FLOOR]
    return DemographicImpactComparison(
        county_total_pop=int(sum(float(r["total_pop"] or 0) for r in acs.values())),
        catchment_total_pop=int(sum(float(acs[g]["total_pop"] or 0) for g in reached if g in acs)),
        county_svi_theme3_mean=round(min(1.0, theme3(county)), 3),
        catchment_svi_theme3_mean=round(min(1.0, theme3(reached)), 3),
        group_comparisons=groups, disparity_findings=findings,
        requires_human_equity_review=bool(findings),
    )


def audit_draft(draft: DraftPlan, impact: DemographicImpactComparison,
                max_revisions: int = 1) -> tuple[AuditReport, list[dict]]:
    """Returns the report and the sanitized feedback for the planner (non-demographic defects only)."""
    defects = []
    pair = overlap_pair(draft)
    if pair:
        a, b, dist = pair
        defects.append(NonDemographicAuditDefect(
            defect_id=f"D{draft.revision_number}-CATCHMENT_OVERLAP",
            category=DefectCategory.CATCHMENT_OVERLAP,
            affected_stop_ranks=[a.stop_rank, b.stop_rank],
            description=f"Stops {a.stop_rank} and {b.stop_rank} are {dist:.1f} km apart; their "
                        f"{a.catchment_radius_km:.0f} km catchments overlap.",
            remediation_instruction="Re-run the optimizer with the minimum separation enforced.",
        ))
    if draft.status != "ok" or len(draft.stops) < 4:
        defects.append(NonDemographicAuditDefect(
            defect_id=f"D{draft.revision_number}-MISSING_CORE_EVIDENCE",
            category=DefectCategory.MISSING_CORE_EVIDENCE, affected_stop_ranks=[],
            description=f"Draft status {draft.status} with {len(draft.stops)} stops.",
            remediation_instruction="Check evidence_report.blocking_failures.",
        ))
    if not defects:
        verdict = AuditVerdict.APPROVED
    elif draft.revision_number < max_revisions:
        verdict = AuditVerdict.REJECTED_REVISION_REQUIRED
    else:
        verdict = AuditVerdict.NEEDS_HUMAN_REVIEW
    summary = (
        (f"Draft {draft.revision_number} resolves the earlier defects. " if draft.revision_number and not defects else "")
        + ("All four stops are at least 5 km apart and every claim is tract-level or labeled as an upper bound. "
           if not defects else " ".join(d.description for d in defects) + " ")
        + (f"Post-hoc equity check flags {len(impact.disparity_findings)} group(s) below parity {PARITY_FLOOR:.2f}; "
           "referred to human review, not fed back to the planner." if impact.disparity_findings
           else "No group falls below the parity floor.")
    )
    report = AuditReport(
        revision_audited=draft.revision_number, verdict=verdict,
        non_demographic_defects=defects, demographic_impact=impact, auditor_summary=summary,
        limitations_attached=["Demographics are ACS 2020 5-year tract aggregates, used only after planning.",
                              "No host venue is confirmed; stops sit on tract centroids or candidate venues."],
    )
    feedback = [d.model_dump(mode="json") for d in defects] if verdict == AuditVerdict.REJECTED_REVISION_REQUIRED else []
    return report, feedback


def draft_outreach(plan: DraftPlan, health: HealthEvidence, county_name: str) -> OutreachMessages:
    def day(iso: str, es: bool = False) -> str:
        d = date.fromisoformat(iso)
        return f"sábado {d.day} de noviembre" if es else f"Saturday, {d.strftime('%B')} {d.day}"

    notices = [StopOutreachDraft(
        stop_rank=s.stop_rank, assigned_saturday=s.assigned_saturday, candidate_venue_name=s.candidate_venue_name,
        english_notice=f"Free health check-ups near you!\n\n{day(s.assigned_saturday)}, near "
                       f"{tract_label(s.primary_tract_geoid)}. The exact spot will be posted soon.\n\nWe check blood "
                       "pressure and blood sugar. You do not need insurance. You do not need an appointment. It is "
                       "free.\n\nThis is a draft. The place is not confirmed yet.",
        spanish_notice=f"¡Chequeos de salud gratis cerca de usted!\n\n{day(s.assigned_saturday, True)}, cerca de "
                       f"{tract_label(s.primary_tract_geoid)}. Pronto diremos el lugar exacto.\n\nRevisamos la presión "
                       "y el azúcar en la sangre. No necesita seguro. No necesita cita. Es gratis.\n\nEsto es un "
                       "borrador. El lugar todavía no está confirmado.",
        why_chosen_explanation=f"Many people near {tract_label(s.primary_tract_geoid)} have no health insurance and "
                               "live far from a clinic that sees people without insurance.",
    ) for s in plan.stops]
    unpicked = []
    for r in plan.runner_up_tracts:
        stop = next((s for s in plan.stops if s.stop_rank == r.covered_by_stop_rank), None)
        t = tract_label(r.tract_geoid)
        if stop:
            en = (f"We know people near {t} need care too. The van will be close by on {day(stop.assigned_saturday)}, "
                  f"about {r.distance_to_nearest_selected_stop_km:.0f} km away.")
            es = (f"Sabemos que la gente cerca de {t} también necesita atención. La van estará cerca el "
                  f"{day(stop.assigned_saturday, True)}, a unos {r.distance_to_nearest_selected_stop_km:.0f} km.")
        else:
            en = (f"We know people near {t} need care too. We only have four Saturdays this month, and other areas had "
                  "more people far from a free or low-cost clinic. We will look again next month.")
            es = (f"Sabemos que la gente cerca de {t} también necesita atención. Solo tenemos cuatro sábados este mes. "
                  "Lo revisaremos el próximo mes.")
        unpicked.append(UnpickedNeighborhoodExplanation(
            tract_geoid=r.tract_geoid, need_rank=r.need_rank, nearest_selected_stop_rank=r.covered_by_stop_rank,
            distance_to_selected_stop_km=r.distance_to_nearest_selected_stop_km,
            english_explanation=en, spanish_explanation=es))
    rd = health.regional_disease
    return OutreachMessages(
        county_name=county_name, stop_notices=notices, unpicked_neighborhood_explanations=unpicked,
        regional_surveillance_note_en=f"Flu and COVID numbers are only reported for the whole {rd.hsa_counties} area, "
                                      f"not for your neighborhood. The latest numbers are from {rd.latest_week_end}.",
        regional_surveillance_note_es=f"Los datos de gripe y COVID solo se reportan para toda el área de "
                                      f"{rd.hsa_counties}, no para su vecindario. Los más recientes son de "
                                      f"{rd.latest_week_end}.",
    )
