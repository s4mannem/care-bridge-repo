"""Greedy maximum-coverage 4-stop selector and runner-up deferral ledger for CareBridge AI."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import (
    ProposedClinicStop,
    RunnerUpTractExplanation,
    ScoreBreakdown,
)
from carebridge.tools.optimizer.scoring import haversine_km

DEFAULT_SATURDAYS: List[str] = ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"]


def _format_stop_rationale(
    tract: TractHealthRecord,
    score: ScoreBreakdown,
    venue_name: str,
    catchment_tracts: Sequence[str],
    catchment_pop: int,
) -> str:
    """Builds an analytical, source-cited, resolution-qualified rationale for the outreach lead."""
    unins = f"{tract.pct_uninsured_18_64:.1f}%" if tract.pct_uninsured_18_64 is not None else "N/A"
    ci_str = (
        f" (+/-{tract.pct_uninsured_18_64_ci_width:.1f}% 95% CI)"
        if tract.pct_uninsured_18_64_ci_width is not None
        else ""
    )
    chk_gap = (
        f"{tract.pct_checkup_gap:.1f}%"
        if tract.pct_checkup_gap is not None
        else (f"{100.0 - tract.pct_checkup:.1f}%" if tract.pct_checkup is not None else "N/A")
    )
    no_veh = f"{tract.pct_no_vehicle:.1f}%" if tract.pct_no_vehicle is not None else "N/A"
    km_safety = f"{tract.km_to_safety_net:.1f} km" if tract.km_to_safety_net is not None else "N/A"
    extra_km = (
        f"{tract.extra_km_if_uninsured:.1f} km"
        if tract.extra_km_if_uninsured is not None
        else "N/A"
    )
    return (
        f"Tract {tract.geo_id} ({venue_name}) has {unins} uninsured adults aged 18-64 "
        f"(CDC PLACES modeled estimate{ci_str}), a {chk_gap} routine checkup preventive gap "
        f"(100 - pct_checkup), {no_veh} zero-vehicle households (CDC SVI 5-year ACS), and "
        f"{km_safety} straight-line upper-bound distance to the nearest federal safety-net clinic "
        f"({extra_km} uninsured distance penalty vs any care). Serves {len(catchment_tracts)} tract(s) "
        f"({catchment_pop:,} residents) with composite need score {score.composite_need_score:.3f}. "
        f"Traveling 5+ km without a car requires multi-bus transfers and time off work."
    )


def select_four_distinct_stops(
    tracts: Sequence[TractHealthRecord],
    scores: Dict[str, ScoreBreakdown],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    saturdays: Optional[Sequence[str]] = None,
    catchment_radius_km: float = 4.0,
    min_separation_km: float = 5.0,
    overlap_discount: float = 0.85,
    excluded_tract_geoids: Optional[Sequence[str]] = None,
    simulate_first_draft_defect: bool = False,
    revision_number: int = 0,
) -> List[ProposedClinicStop]:
    """Selects 4 geographically distinct Saturday mobile clinic stops using greedy max-coverage.

    When `simulate_first_draft_defect=True` and `revision_number == 0`, Stop 2 deliberately relaxes
    `min_separation_km` so that Stops 1 and 2 sit within `< 5.0 km` (overlapping catchments),
    allowing the Independent Equity & Rigor Auditor to reject Draft 0 and trigger Revision 1.
    """
    excluded: Set[str] = set(excluded_tract_geoids or [])
    mob_lookup = mobility_map or {}
    assigned_dates = list(saturdays or DEFAULT_SATURDAYS)
    while len(assigned_dates) < 4:
        assigned_dates.append(DEFAULT_SATURDAYS[len(assigned_dates) % 4])

    valid_candidates: List[TractHealthRecord] = [
        t
        for t in tracts
        if t.geo_id in scores
        and t.geo_id not in excluded
        and t.total_pop > 0
        and t.latitude is not None
        and t.longitude is not None
    ]
    if len(valid_candidates) < 4:
        return []

    tract_by_id: Dict[str, TractHealthRecord] = {t.geo_id: t for t in valid_candidates}

    # Precompute catchment neighborhoods within catchment_radius_km
    catchments: Dict[str, List[TractHealthRecord]] = {}
    for cand in valid_candidates:
        c_lat = float(cand.latitude)
        c_lon = float(cand.longitude)
        neighbors: List[TractHealthRecord] = []
        for other in valid_candidates:
            dist = haversine_km(c_lat, c_lon, float(other.latitude), float(other.longitude))
            if dist <= catchment_radius_km:
                neighbors.append(other)
        if not neighbors:
            neighbors.append(cand)
        catchments[cand.geo_id] = neighbors

    selected_stops: List[ProposedClinicStop] = []
    selected_geoids: Set[str] = set()
    covered_geoids: Set[str] = set()

    for step_idx in range(4):
        stop_rank = step_idx + 1
        force_overlap_defect = (
            simulate_first_draft_defect and revision_number == 0 and stop_rank == 2 and len(selected_stops) == 1
        )

        best_candidate: Optional[TractHealthRecord] = None
        best_utility: float = -1.0

        if force_overlap_defect:
            # Pick the highest-need unselected tract within < min_separation_km of Stop 1
            stop1 = selected_stops[0]
            nearby_candidates: List[TractHealthRecord] = []
            for cand in valid_candidates:
                if cand.geo_id in selected_geoids:
                    continue
                d_km = haversine_km(
                    stop1.latitude,
                    stop1.longitude,
                    float(cand.latitude),
                    float(cand.longitude),
                )
                if d_km < min_separation_km:
                    nearby_candidates.append(cand)

            if nearby_candidates:
                nearby_candidates.sort(
                    key=lambda c: (
                        scores[c.geo_id].composite_need_score,
                        c.total_pop,
                        c.geo_id,
                    ),
                    reverse=True,
                )
                best_candidate = nearby_candidates[0]

        if best_candidate is None:
            # Standard greedy maximum-coverage selection enforcing min_separation_km
            eligible_candidates: List[TractHealthRecord] = []
            for cand in valid_candidates:
                if cand.geo_id in selected_geoids:
                    continue
                too_close = any(
                    haversine_km(
                        prev.latitude,
                        prev.longitude,
                        float(cand.latitude),
                        float(cand.longitude),
                    )
                    < min_separation_km
                    for prev in selected_stops
                )
                if not too_close:
                    eligible_candidates.append(cand)

            if not eligible_candidates:
                return []

            for cand in eligible_candidates:
                cand_score = scores[cand.geo_id]
                marginal_pop_weighted_need = 0.0
                for neighbor in catchments[cand.geo_id]:
                    n_score = scores[neighbor.geo_id].composite_need_score
                    discount_factor = (
                        (1.0 - overlap_discount)
                        if neighbor.geo_id in covered_geoids
                        else 1.0
                    )
                    marginal_pop_weighted_need += (
                        float(neighbor.total_pop) * n_score * discount_factor
                    )
                # Blend primary tract composite need score with catchment marginal utility
                utility = (
                    marginal_pop_weighted_need
                    * (0.50 + 0.50 * cand_score.composite_need_score)
                    * (1.0 + 0.05 * cand_score.saturday_transit_access_bonus)
                )
                if (
                    utility > best_utility
                    or (
                        abs(utility - best_utility) <= 1e-9
                        and best_candidate is not None
                        and cand.geo_id < best_candidate.geo_id
                    )
                ):
                    best_utility = utility
                    best_candidate = cand

        assert best_candidate is not None
        chosen_gid = best_candidate.geo_id
        chosen_catchment = catchments[chosen_gid]
        chosen_catchment_ids = [t.geo_id for t in chosen_catchment]

        total_catchment_pop = sum(t.total_pop for t in chosen_catchment)
        already_covered_pop = sum(
            t.total_pop for t in chosen_catchment if t.geo_id in covered_geoids
        )
        overlap_ratio = (
            round(already_covered_pop / float(total_catchment_pop), 4)
            if total_catchment_pop > 0
            else 0.0
        )

        base_score = scores[chosen_gid]
        adjusted_score = base_score.model_copy(
            update={
                "overlap_penalty": round(min(1.0, overlap_ratio * overlap_discount), 4),
                "composite_need_score": round(
                    max(
                        0.0,
                        base_score.composite_need_score
                        * (1.0 - 0.50 * overlap_ratio * overlap_discount),
                    ),
                    4,
                ),
            }
        )

        mob_rec = mob_lookup.get(chosen_gid)
        if mob_rec and mob_rec.candidate_venues:
            venue = mob_rec.candidate_venues[0]
            venue_name = venue.venue_name
            stop_lat = float(venue.latitude)
            stop_lon = float(venue.longitude)
        else:
            venue_name = (
                f"Provisional Tract Centroid Host ({chosen_gid}) — Venue Unassigned"
            )
            stop_lat = float(best_candidate.latitude)
            stop_lon = float(best_candidate.longitude)

        citations = [
            f"a4i_health.v_burden_tracts:geo_id={chosen_gid}",
            f"a4i_health.v_tract_access:geo_id={chosen_gid}",
        ]
        if mob_rec and mob_rec.saturday_active_stops_count > 0:
            citations.append(
                f"marta_gtfs.v_tract_saturday_transit_access:geo_id={chosen_gid}"
            )

        disclosures = [
            "Tract health prevalences (uninsured, asthma, COPD, diabetes, high BP, routine checkup) are CDC PLACES small-area modeled estimates (11-char tract grain) with 95% confidence intervals, not direct patient counts.",
            f"km_to_safety_net={best_candidate.km_to_safety_net or 0.0:.1f} km is a straight-line Euclidean upper-bound distance to federally recognized FQHCs/Health Centers, not bus transit journey time.",
            "Regional respiratory ED trends (COVID-19, influenza, RSV) are measured at the 4-county Atlanta Health Service Area (HSA) level, never at the individual census tract level.",
        ]

        stop_obj = ProposedClinicStop(
            stop_rank=stop_rank,
            assigned_saturday=assigned_dates[step_idx],
            primary_tract_geoid=chosen_gid,
            covered_tract_geoids=chosen_catchment_ids,
            candidate_venue_name=venue_name,
            latitude=stop_lat,
            longitude=stop_lon,
            catchment_radius_km=catchment_radius_km,
            estimated_population_in_catchment=total_catchment_pop,
            score_breakdown=adjusted_score,
            plain_language_rationale=_format_stop_rationale(
                tract=best_candidate,
                score=adjusted_score,
                venue_name=venue_name,
                catchment_tracts=chosen_catchment_ids,
                catchment_pop=total_catchment_pop,
            ),
            evidence_citations=citations,
            spatial_grain_disclosures=disclosures,
            host_verified=False,
        )
        selected_stops.append(stop_obj)
        selected_geoids.add(chosen_gid)
        for cid in chosen_catchment_ids:
            covered_geoids.add(cid)

    return selected_stops


def build_runner_up_explanations(
    tracts: Sequence[TractHealthRecord],
    scores: Dict[str, ScoreBreakdown],
    selected_stops: Sequence[ProposedClinicStop],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    catchment_radius_km: float = 4.0,
    min_separation_km: float = 5.0,
    max_runner_ups: int = 4,
) -> List[RunnerUpTractExplanation]:
    """Builds deterministic deferral explanations for high-need runner-up tracts (ranks #5-#8).

    Answers Question 7: 'How do I tell the neighborhood we didn't pick why we didn't pick them?'
    """
    if not selected_stops:
        return []

    mob_lookup = mobility_map or {}
    selected_primary_ids = {s.primary_tract_geoid for s in selected_stops}

    non_selected: List[TractHealthRecord] = [
        t
        for t in tracts
        if t.geo_id in scores
        and t.geo_id not in selected_primary_ids
        and t.total_pop > 0
        and t.latitude is not None
        and t.longitude is not None
    ]
    non_selected.sort(
        key=lambda t: (
            scores[t.geo_id].composite_need_score,
            t.total_pop,
            t.geo_id,
        ),
        reverse=True,
    )

    runner_ups: List[RunnerUpTractExplanation] = []
    for idx, tract in enumerate(non_selected[:max_runner_ups]):
        need_rank = 5 + idx
        t_lat = float(tract.latitude)
        t_lon = float(tract.longitude)
        t_score = scores[tract.geo_id].composite_need_score

        nearest_stop = min(
            selected_stops,
            key=lambda s: haversine_km(t_lat, t_lon, s.latitude, s.longitude),
        )
        nearest_dist_km = round(
            haversine_km(t_lat, t_lon, nearest_stop.latitude, nearest_stop.longitude), 2
        )

        mob_rec = mob_lookup.get(tract.geo_id)
        has_transit_or_venue = bool(
            mob_rec
            and (mob_rec.saturday_active_stops_count > 0 or len(mob_rec.candidate_venues) > 0)
        )

        if (
            tract.geo_id in nearest_stop.covered_tract_geoids
            or nearest_dist_km <= catchment_radius_km
        ):
            reason_code = "catchment_already_covered"
            covered_rank: Optional[int] = nearest_stop.stop_rank
            rationale = (
                f"Tract {tract.geo_id} ranks #{need_rank} in county need (score={t_score:.2f}) and is "
                f"already served within the {catchment_radius_km:.1f} km catchment of Stop #{nearest_stop.stop_rank} "
                f"({nearest_stop.candidate_venue_name}, {nearest_dist_km:.1f} km away on {nearest_stop.assigned_saturday})."
            )
        elif nearest_dist_km < min_separation_km:
            reason_code = "inter_stop_separation_constraint"
            covered_rank = nearest_stop.stop_rank
            rationale = (
                f"Tract {tract.geo_id} ranks #{need_rank} in county need (score={t_score:.2f}) and sits "
                f"{nearest_dist_km:.1f} km from Stop #{nearest_stop.stop_rank} ({nearest_stop.candidate_venue_name}), "
                f"inside the {min_separation_km:.1f} km minimum inter-stop separation buffer used to prevent "
                f"duplicate catchment clustering."
            )
        elif mobility_map is not None and not has_transit_or_venue:
            reason_code = "no_saturday_transit_or_venue"
            covered_rank = nearest_stop.stop_rank
            rationale = (
                f"Tract {tract.geo_id} ranks #{need_rank} in county need (score={t_score:.2f}), but lacks a "
                f"Saturday-served transit stop or candidate community host venue; nearest active mobile clinic "
                f"is Stop #{nearest_stop.stop_rank} ({nearest_dist_km:.1f} km away)."
            )
        else:
            reason_code = "lower_marginal_coverage"
            covered_rank = nearest_stop.stop_rank
            rationale = (
                f"Tract {tract.geo_id} ranks #{need_rank} in county need (score={t_score:.2f}), but had lower "
                f"marginal uncovered population in its {catchment_radius_km:.1f} km catchment than the top 4 "
                f"selected stops; residents can access Stop #{nearest_stop.stop_rank} ({nearest_dist_km:.1f} km away)."
            )

        runner_ups.append(
            RunnerUpTractExplanation(
                tract_geoid=tract.geo_id,
                need_rank=need_rank,
                composite_need_score=round(t_score, 4),
                deferral_reason_code=reason_code,
                covered_by_stop_rank=covered_rank,
                distance_to_nearest_selected_stop_km=nearest_dist_km,
                technical_deferral_rationale=rationale,
            )
        )

    return runner_ups
