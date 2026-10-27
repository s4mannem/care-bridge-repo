"""Greedy maximum-coverage 4-stop selector, runner-up deferral ledger, and overlap discount."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from carebridge.contracts.evidence_models import (
    CandidateHostVenue,
    TractHealthRecord,
    TractMobilityRecord,
)
from carebridge.contracts.plan_models import (
    ProposedClinicStop,
    RunnerUpTractExplanation,
    ScoreBreakdown,
)
from carebridge.tools.optimizer.scoring import compute_tract_scores, haversine_km


def _find_best_venue_for_tract(
    geo_id: str,
    tract_lat: float,
    tract_lon: float,
    mobility_map: Dict[str, TractMobilityRecord],
) -> Tuple[str, float, float]:
    m_rec = mobility_map.get(geo_id)
    if m_rec and m_rec.candidate_venues:
        best_venue = max(
            m_rec.candidate_venues,
            key=lambda v: (v.saturday_transit_stops_within_400m, v.venue_name),
        )
        return (best_venue.venue_name, best_venue.latitude, best_venue.longitude)

    return (
        f"Provisional Tract Centroid Host ({geo_id}) — Venue Unassigned",
        tract_lat,
        tract_lon,
    )


def select_four_distinct_stops(
    tracts: List[TractHealthRecord],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    saturdays: Optional[List[str]] = None,
    strategy: str = "balanced_uninsured_safety_net_gap",
    catchment_radius_km: float = 4.0,
    min_separation_km: float = 5.0,
    overlap_discount: float = 0.85,
    excluded_tract_geoids: Optional[Set[str]] = None,
    simulate_first_draft_defect: bool = False,
    custom_scores: Optional[Dict[str, ScoreBreakdown]] = None,
) -> Tuple[List[ProposedClinicStop], List[RunnerUpTractExplanation]]:
    """Selects 4 distinct clinic stops using greedy population-weighted marginal coverage.

    Answers Question 7 by generating RunnerUpTractExplanation entries for top non-selected tracts.
    """
    mobility_map = mobility_map or {}
    saturdays = saturdays or [
        "2026-11-07",
        "2026-11-14",
        "2026-11-21",
        "2026-11-28",
    ]
    excluded_tract_geoids = set(excluded_tract_geoids or set())

    valid_tracts = [
        t for t in tracts
        if t.total_pop > 0 and t.latitude is not None and t.longitude is not None
    ]
    tract_by_id = {t.geo_id: t for t in valid_tracts}

    scores = custom_scores or compute_tract_scores(
        tracts=valid_tracts,
        mobility_map=mobility_map,
        strategy=strategy,
    )

    if len(valid_tracts) < 4:
        return [], []

    # Precompute catchments for all candidates
    catchments: Dict[str, List[str]] = {}
    for c_id, c_t in tract_by_id.items():
        covered = []
        for other_id, o_t in tract_by_id.items():
            dist = haversine_km(c_t.latitude, c_t.longitude, o_t.latitude, o_t.longitude)
            if dist <= catchment_radius_km:
                covered.append(other_id)
        catchments[c_id] = covered

    selected_stops: List[ProposedClinicStop] = []
    selected_tract_ids: List[str] = []
    covered_tract_ids: Set[str] = set()

    for k in range(min(4, len(saturdays))):
        best_candidate: Optional[str] = None
        best_utility = -1.0

        # If simulating first draft defect on step 1 (2nd stop), pick the highest need neighbor within 4 km of Stop 1
        if simulate_first_draft_defect and k == 1 and selected_tract_ids:
            first_tract = tract_by_id[selected_tract_ids[0]]
            nearby_candidates = [
                cand_id for cand_id, cand_t in tract_by_id.items()
                if cand_id not in selected_tract_ids
                and cand_id not in excluded_tract_geoids
                and haversine_km(cand_t.latitude, cand_t.longitude, first_tract.latitude, first_tract.longitude) < 5.0
            ]
            if nearby_candidates:
                best_candidate = max(
                    nearby_candidates,
                    key=lambda cid: scores[cid].composite_need_score if cid in scores else 0.0,
                )

        if best_candidate is None:
            for cand_id, cand_t in tract_by_id.items():
                if cand_id in selected_tract_ids or cand_id in excluded_tract_geoids:
                    continue

                separation_ok = True
                for sel_id in selected_tract_ids:
                    sel_t = tract_by_id[sel_id]
                    dist = haversine_km(cand_t.latitude, cand_t.longitude, sel_t.latitude, sel_t.longitude)
                    if dist < min_separation_km:
                        separation_ok = False
                        break

                if not separation_ok:
                    continue

                # Marginal utility calculation
                utility = 0.0
                for t_id in catchments[cand_id]:
                    t_obj = tract_by_id[t_id]
                    t_score = scores.get(t_id)
                    score_val = t_score.composite_need_score if t_score else 0.5
                    weight = (1.0 - overlap_discount) if t_id in covered_tract_ids else 1.0
                    utility += t_obj.total_pop * score_val * weight

                if utility > best_utility:
                    best_utility = utility
                    best_candidate = cand_id

        if best_candidate is None:
            break

        cand_tract = tract_by_id[best_candidate]
        cand_catchment = catchments[best_candidate]
        covered_tract_ids.update(cand_catchment)
        selected_tract_ids.append(best_candidate)

        venue_name, v_lat, v_lon = _find_best_venue_for_tract(
            best_candidate, cand_tract.latitude, cand_tract.longitude, mobility_map
        )
        total_catchment_pop = sum(tract_by_id[t_id].total_pop for t_id in cand_catchment)

        assigned_sat = saturdays[k]
        cand_score = scores.get(best_candidate)

        citations = [
            f"CDC PLACES 2024 (uninsured 18-64: {cand_tract.pct_uninsured_18_64 or 0.0:.1f}%)",
            f"CDC SVI 2022 (zero-vehicle: {cand_tract.pct_no_vehicle or 0.0:.1f}%)",
            f"HRSA FQHC Distance (km to nearest safety-net: {cand_tract.km_to_safety_net or 0.0:.1f} km)",
        ]

        spatial_disclosures = [
            f"Primary Tract {best_candidate} (11-character census tract small-area estimate)",
            f"Catchment radius {catchment_radius_km:.1f} km covering {len(cand_catchment)} tracts",
            "Regional syndromic disease signals reflect multi-county HSA, not tract-level rates",
        ]

        unins = cand_tract.pct_uninsured_18_64 or 0.0
        km_sn = cand_tract.km_to_safety_net or 0.0
        no_veh = cand_tract.pct_no_vehicle or 0.0
        chk_gap = cand_tract.pct_checkup_gap or (100.0 - (cand_tract.pct_checkup or 0.0))

        rationale = (
            f"Selected Stop #{k + 1} at {venue_name} serves census tract {best_candidate}. "
            f"This tract demonstrates high structural need with {unins:.1f}% adult uninsured rate "
            f"(CDC PLACES estimate), a preventive checkup gap of {chk_gap:.1f}%, and {no_veh:.1f}% "
            f"zero-vehicle households facing a {km_sn:.1f} km straight-line transit barrier to the "
            f"nearest safety-net clinic. 5+ km travel without personal vehicle represents a significant "
            f"full-day obstacle requiring multiple transfers. Catchment serves an estimated {total_catchment_pop} residents."
        )

        stop = ProposedClinicStop(
            stop_rank=k + 1,
            assigned_saturday=assigned_sat,
            primary_tract_geoid=best_candidate,
            covered_tract_geoids=cand_catchment,
            candidate_venue_name=venue_name,
            latitude=v_lat,
            longitude=v_lon,
            catchment_radius_km=catchment_radius_km,
            estimated_population_in_catchment=total_catchment_pop,
            score_breakdown=cand_score or ScoreBreakdown(
                uninsured_norm=0.5,
                safety_net_distance_norm=0.5,
                no_vehicle_norm=0.5,
                chronic_respiratory_norm=0.5,
                composite_need_score=0.5,
            ),
            plain_language_rationale=rationale,
            evidence_citations=citations,
            spatial_grain_disclosures=spatial_disclosures,
            host_verified=False,
        )
        selected_stops.append(stop)

    # Question 7: Explain runner-up high-need tracts (#5-#8)
    sorted_all_tracts = sorted(
        valid_tracts,
        key=lambda t: (scores.get(t.geo_id).composite_need_score if scores.get(t.geo_id) else 0.0),
        reverse=True,
    )

    runner_up_explanations: List[RunnerUpTractExplanation] = []
    rank_counter = 1

    for t in sorted_all_tracts:
        t_id = t.geo_id
        is_selected = t_id in selected_tract_ids
        current_rank = rank_counter
        rank_counter += 1

        if is_selected or current_rank < 5 or current_rank > 8:
            continue

        t_score = scores.get(t_id)
        composite = t_score.composite_need_score if t_score else 0.5

        # Determine nearest selected stop
        nearest_stop_rank: Optional[int] = None
        min_dist_to_stop = float("inf")

        for stop in selected_stops:
            s_lat = stop.latitude
            s_lon = stop.longitude
            dist = haversine_km(t.latitude, t.longitude, s_lat, s_lon)
            if dist < min_dist_to_stop:
                min_dist_to_stop = dist
                nearest_stop_rank = stop.stop_rank

        # Determine deferral reason
        if min_dist_to_stop <= catchment_radius_km:
            reason_code = "catchment_already_covered"
            rationale_text = (
                f"Tract {t_id} (composite need score {composite:.3f}) was not selected for a dedicated "
                f"Saturday stop because it is already encompassed within the {catchment_radius_km:.1f} km "
                f"service catchment of Stop #{nearest_stop_rank} ({min_dist_to_stop:.1f} km away)."
            )
        elif min_dist_to_stop < min_separation_km:
            reason_code = "inter_stop_separation_constraint"
            rationale_text = (
                f"Tract {t_id} (need rank #{current_rank}, composite score {composite:.3f}) sits {min_dist_to_stop:.1f} km "
                f"from Stop #{nearest_stop_rank}, within the {min_separation_km:.1f} km inter-stop separation buffer. "
                f"Placing a separate stop here would duplicate geographic catchment coverage rather than expanding reach."
            )
        else:
            reason_code = "lower_marginal_coverage"
            rationale_text = (
                f"Tract {t_id} (need rank #{current_rank}) exhibited high individual need (score {composite:.3f}), "
                f"but prioritizing tracts with greater marginal unserved population in their 4 km radius "
                f"achieved higher total countywide coverage."
            )

        runner_up_explanations.append(
            RunnerUpTractExplanation(
                tract_geoid=t_id,
                need_rank=current_rank,
                composite_need_score=round(composite, 4),
                deferral_reason_code=reason_code,
                covered_by_stop_rank=nearest_stop_rank,
                distance_to_nearest_selected_stop_km=round(min_dist_to_stop, 2),
                technical_deferral_rationale=rationale_text,
            )
        )

    return selected_stops, runner_up_explanations
