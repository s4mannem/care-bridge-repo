"""Weight sensitivity analysis perturbing strategy weights by +/- 15%."""

from __future__ import annotations

from typing import Dict, List, Optional, Set
from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import SensitivitySummary
from carebridge.tools.optimizer.coverage import select_four_distinct_stops
from carebridge.tools.optimizer.scoring import STRATEGY_WEIGHTS, compute_tract_scores


def run_weight_sensitivity(
    tracts: List[TractHealthRecord],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    strategy: str = "balanced_uninsured_safety_net_gap",
    saturdays: Optional[List[str]] = None,
    perturbation_pct: float = 15.0,
) -> SensitivitySummary:
    """Perturbs weights across dimensions and computes Jaccard similarity of selected top-4."""
    base_weights = dict(
        STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["balanced_uninsured_safety_net_gap"])
    )

    base_stops, _ = select_four_distinct_stops(
        tracts=tracts,
        mobility_map=mobility_map,
        strategy=strategy,
        saturdays=saturdays,
    )
    base_geoids: Set[str] = {s.primary_tract_geoid for s in base_stops}

    if not base_geoids:
        return SensitivitySummary(
            weight_perturbation_pct=perturbation_pct,
            top_4_stability_jaccard=1.0,
            borderline_tracts=[],
            notes="Insufficient candidates to evaluate perturbation sensitivity.",
        )

    all_perturbed_geoids: Set[str] = set()
    jaccards: List[float] = []
    ratio = perturbation_pct / 100.0

    for key in base_weights:
        for delta in (-ratio, ratio):
            perturbed = dict(base_weights)
            perturbed[key] = max(0.01, perturbed[key] * (1.0 + delta))

            p_scores = compute_tract_scores(
                tracts=tracts,
                mobility_map=mobility_map,
                custom_weights=perturbed,
            )
            p_stops, _ = select_four_distinct_stops(
                tracts=tracts,
                mobility_map=mobility_map,
                saturdays=saturdays,
                custom_scores=p_scores,
            )
            p_geoids = {s.primary_tract_geoid for s in p_stops}
            all_perturbed_geoids.update(p_geoids)

            intersection = len(base_geoids & p_geoids)
            union = len(base_geoids | p_geoids)
            j_score = intersection / union if union > 0 else 1.0
            jaccards.append(j_score)

    avg_jaccard = round(sum(jaccards) / len(jaccards), 3) if jaccards else 1.0
    borderline = sorted(list(all_perturbed_geoids - base_geoids))

    return SensitivitySummary(
        weight_perturbation_pct=perturbation_pct,
        top_4_stability_jaccard=avg_jaccard,
        borderline_tracts=borderline,
        notes=(
            f"Mean Jaccard stability under +/-{perturbation_pct:.0f}% weight shifts: {avg_jaccard:.2f}. "
            f"{len(borderline)} alternative borderline tract(s) entered the top 4 under perturbed weights."
        ),
    )
