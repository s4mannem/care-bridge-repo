"""Weight sensitivity analysis (+/- 15% perturbation Jaccard stability) for the 4-Stop Coverage Optimizer."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import ProposedClinicStop, SensitivitySummary
from carebridge.tools.optimizer.coverage import select_four_distinct_stops
from carebridge.tools.optimizer.scoring import compute_tract_scores, resolve_strategy_weights

_PERTURBATION_DIRECTIONS = [
    ("uninsured", 1.15),
    ("uninsured", 0.85),
    ("safety_net_distance", 1.15),
    ("safety_net_distance", 0.85),
    ("no_vehicle", 1.15),
    ("no_vehicle", 0.85),
    ("chronic_respiratory", 1.15),
    ("checkup_preventive_gap", 1.15),
]


def run_weight_sensitivity(
    tracts: Sequence[TractHealthRecord],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    strategy: str = "balanced_uninsured_safety_net_gap",
    baseline_stops: Optional[Sequence[ProposedClinicStop]] = None,
    perturbation_pct: float = 15.0,
    excluded_tract_geoids: Optional[Sequence[str]] = None,
    catchment_radius_km: float = 4.0,
    min_separation_km: float = 5.0,
) -> SensitivitySummary:
    """Runs +/- 15% weight perturbations across 8 deterministic directions and computes Jaccard stability."""
    base_weights = resolve_strategy_weights(strategy=strategy)
    if baseline_stops is None:
        base_scores = compute_tract_scores(
            tracts=tracts, mobility_map=mobility_map, strategy=strategy
        )
        baseline_stops = select_four_distinct_stops(
            tracts=tracts,
            scores=base_scores,
            mobility_map=mobility_map,
            catchment_radius_km=catchment_radius_km,
            min_separation_km=min_separation_km,
            excluded_tract_geoids=excluded_tract_geoids,
        )

    baseline_set: Set[str] = {s.primary_tract_geoid for s in baseline_stops}
    if not baseline_set:
        return SensitivitySummary(
            weight_perturbation_pct=perturbation_pct,
            top_4_stability_jaccard=0.0,
            borderline_tracts=[],
            notes="Insufficient candidate tracts to evaluate weight sensitivity.",
        )

    scale_hi = 1.0 + (perturbation_pct / 100.0)
    scale_lo = max(0.05, 1.0 - (perturbation_pct / 100.0))

    jaccard_scores: List[float] = []
    borderline_set: Set[str] = set()

    for idx, (dim_name, _) in enumerate(_PERTURBATION_DIRECTIONS):
        factor = scale_hi if idx % 2 == 0 else scale_lo
        perturbed_weights = dict(base_weights)
        perturbed_weights[dim_name] = perturbed_weights.get(dim_name, 0.15) * factor

        p_scores = compute_tract_scores(
            tracts=tracts,
            mobility_map=mobility_map,
            strategy=strategy,
            custom_weights=perturbed_weights,
        )
        p_stops = select_four_distinct_stops(
            tracts=tracts,
            scores=p_scores,
            mobility_map=mobility_map,
            catchment_radius_km=catchment_radius_km,
            min_separation_km=min_separation_km,
            excluded_tract_geoids=excluded_tract_geoids,
        )
        p_set = {s.primary_tract_geoid for s in p_stops}
        union_set = baseline_set | p_set
        inter_set = baseline_set & p_set
        jacc = (len(inter_set) / float(len(union_set))) if union_set else 1.0
        jaccard_scores.append(jacc)

        diff = p_set ^ baseline_set
        for gid in diff:
            borderline_set.add(gid)

    mean_jaccard = round(
        max(0.0, min(1.0, sum(jaccard_scores) / float(len(jaccard_scores)))), 4
    )

    if not borderline_set:
        # Identify the next two highest-scoring non-selected tracts as borderline runner-ups
        base_scores = compute_tract_scores(
            tracts=tracts, mobility_map=mobility_map, strategy=strategy
        )
        ranked_others = sorted(
            (gid for gid in base_scores if gid not in baseline_set),
            key=lambda g: base_scores[g].composite_need_score,
            reverse=True,
        )
        borderline_list = ranked_others[:2]
    else:
        borderline_list = sorted(borderline_set)

    return SensitivitySummary(
        weight_perturbation_pct=perturbation_pct,
        top_4_stability_jaccard=mean_jaccard,
        borderline_tracts=borderline_list,
        notes=(
            f"Evaluated 8 deterministic +/-{perturbation_pct:.0f}% weight perturbations around "
            f"strategy '{strategy}'; mean top-4 Jaccard stability={mean_jaccard:.2f}."
        ),
    )
