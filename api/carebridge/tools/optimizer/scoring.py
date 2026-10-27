"""Within-county race-blind min-max and quantile need scoring for census tracts."""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import ScoreBreakdown
from carebridge.security.race_blind_guard import assert_race_blind_planner_input

STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "balanced_uninsured_safety_net_gap": {
        "uninsured": 0.30,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.20,
        "chronic_respiratory": 0.15,
        "checkup_gap": 0.10,
    },
    "chronic_respiratory_focus": {
        "uninsured": 0.20,
        "safety_net_distance": 0.20,
        "no_vehicle": 0.15,
        "chronic_respiratory": 0.35,
        "checkup_gap": 0.10,
    },
    "zero_vehicle_transit_priority": {
        "uninsured": 0.20,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.35,
        "chronic_respiratory": 0.10,
        "checkup_gap": 0.10,
    },
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two points in kilometers."""
    radius = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius * c


def _normalize(val: Optional[float], min_val: float, max_val: float) -> float:
    if val is None:
        return 0.0
    if max_val <= min_val:
        return 0.5
    norm = (val - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, float(norm)))


def compute_tract_scores(
    tracts: List[TractHealthRecord],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    strategy: str = "balanced_uninsured_safety_net_gap",
    custom_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, ScoreBreakdown]:
    """Computes normalized [0.0, 1.0] component scores and composite need score.

    Enforces strict race-blindness before scoring.
    """
    assert_race_blind_planner_input([t.model_dump() for t in tracts])
    if custom_weights:
        assert_race_blind_planner_input(custom_weights)
    mobility_map = mobility_map or {}

    valid_tracts = [
        t for t in tracts
        if t.total_pop > 0 and t.latitude is not None and t.longitude is not None
    ]
    if not valid_tracts:
        return {}

    weights = custom_weights or STRATEGY_WEIGHTS.get(
        strategy, STRATEGY_WEIGHTS["balanced_uninsured_safety_net_gap"]
    )

    uninsured_vals = [t.pct_uninsured_18_64 for t in valid_tracts if t.pct_uninsured_18_64 is not None]
    safety_net_vals = [t.km_to_safety_net for t in valid_tracts if t.km_to_safety_net is not None]
    no_vehicle_vals = [t.pct_no_vehicle for t in valid_tracts if t.pct_no_vehicle is not None]

    chronic_means: Dict[str, float] = {}
    for t in valid_tracts:
        components = [v for v in (t.pct_asthma, t.pct_copd, t.pct_diabetes, t.pct_bphigh) if v is not None]
        chronic_means[t.geo_id] = sum(components) / len(components) if components else 0.0

    chronic_vals = list(chronic_means.values())
    checkup_gap_vals = [
        t.pct_checkup_gap if t.pct_checkup_gap is not None
        else (100.0 - t.pct_checkup if t.pct_checkup is not None else None)
        for t in valid_tracts
    ]
    checkup_gap_vals_clean = [v for v in checkup_gap_vals if v is not None]

    min_uninsured = min(uninsured_vals) if uninsured_vals else 0.0
    max_uninsured = max(uninsured_vals) if uninsured_vals else 1.0

    min_safety_net = min(safety_net_vals) if safety_net_vals else 0.0
    max_safety_net = max(safety_net_vals) if safety_net_vals else 1.0

    min_no_vehicle = min(no_vehicle_vals) if no_vehicle_vals else 0.0
    max_no_vehicle = max(no_vehicle_vals) if no_vehicle_vals else 1.0

    min_chronic = min(chronic_vals) if chronic_vals else 0.0
    max_chronic = max(chronic_vals) if chronic_vals else 1.0

    min_checkup_gap = min(checkup_gap_vals_clean) if checkup_gap_vals_clean else 0.0
    max_checkup_gap = max(checkup_gap_vals_clean) if checkup_gap_vals_clean else 1.0

    scores: Dict[str, ScoreBreakdown] = {}
    w_uninsured = weights.get("uninsured", 0.30)
    w_safety_net = weights.get("safety_net_distance", 0.25)
    w_no_vehicle = weights.get("no_vehicle", 0.20)
    w_chronic = weights.get("chronic_respiratory", 0.15)
    w_checkup = weights.get("checkup_gap", 0.10)
    total_w = w_uninsured + w_safety_net + w_no_vehicle + w_chronic + w_checkup or 1.0

    for t in valid_tracts:
        u_norm = _normalize(t.pct_uninsured_18_64, min_uninsured, max_uninsured)
        s_norm = _normalize(t.km_to_safety_net, min_safety_net, max_safety_net)
        v_norm = _normalize(t.pct_no_vehicle, min_no_vehicle, max_no_vehicle)
        c_norm = _normalize(chronic_means.get(t.geo_id, 0.0), min_chronic, max_chronic)

        gap_val = t.pct_checkup_gap
        if gap_val is None and t.pct_checkup is not None:
            gap_val = 100.0 - t.pct_checkup
        g_norm = _normalize(gap_val, min_checkup_gap, max_checkup_gap)

        m_rec = mobility_map.get(t.geo_id)
        transit_bonus = 0.0
        if m_rec and m_rec.saturday_active_stops_count > 0:
            transit_bonus = min(1.0, m_rec.saturday_active_stops_count / 10.0)

        composite = (
            (w_uninsured * u_norm)
            + (w_safety_net * s_norm)
            + (w_no_vehicle * v_norm)
            + (w_chronic * c_norm)
            + (w_checkup * g_norm)
        ) / total_w

        composite = max(0.0, min(1.0, composite))

        scores[t.geo_id] = ScoreBreakdown(
            uninsured_norm=round(u_norm, 4),
            safety_net_distance_norm=round(s_norm, 4),
            no_vehicle_norm=round(v_norm, 4),
            chronic_respiratory_norm=round(c_norm, 4),
            checkup_preventive_gap_norm=round(g_norm, 4),
            saturday_transit_access_bonus=round(transit_bonus, 4),
            overlap_penalty=0.0,
            composite_need_score=round(composite, 4),
        )

    return scores
