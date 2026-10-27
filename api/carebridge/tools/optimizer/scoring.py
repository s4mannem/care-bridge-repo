"""Within-county race-blind min-max need scoring for the Four-Stop Coverage Optimizer."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import ScoreBreakdown
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)

STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "balanced_uninsured_safety_net_gap": {
        "uninsured": 0.30,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.20,
        "chronic_respiratory": 0.15,
        "checkup_preventive_gap": 0.10,
    },
    "chronic_respiratory_focus": {
        "uninsured": 0.20,
        "safety_net_distance": 0.20,
        "no_vehicle": 0.15,
        "chronic_respiratory": 0.35,
        "checkup_preventive_gap": 0.10,
    },
    "zero_vehicle_transit_priority": {
        "uninsured": 0.20,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.35,
        "chronic_respiratory": 0.10,
        "checkup_preventive_gap": 0.10,
    },
}

_STRATEGY_ALIASES: Dict[str, str] = {
    "balanced": "balanced_uninsured_safety_net_gap",
    "respiratory": "chronic_respiratory_focus",
    "transit": "zero_vehicle_transit_priority",
}


def resolve_strategy_weights(
    strategy: str = "balanced_uninsured_safety_net_gap",
    custom_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Resolves and normalizes a strategy weight dictionary so weights sum to 1.0."""
    if custom_weights:
        base = dict(custom_weights)
    else:
        canonical = _STRATEGY_ALIASES.get(strategy, strategy)
        base = dict(
            STRATEGY_WEIGHTS.get(
                canonical, STRATEGY_WEIGHTS["balanced_uninsured_safety_net_gap"]
            )
        )
    if "checkup_preventive_gap" not in base:
        base["checkup_preventive_gap"] = 0.10
    total = sum(max(0.0, float(v)) for v in base.values())
    if total <= 0.0:
        return dict(STRATEGY_WEIGHTS["balanced_uninsured_safety_net_gap"])
    return {k: float(max(0.0, v)) / total for k, v in base.items()}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle Haversine distance in kilometers between two (lat, lon) coordinates."""
    earth_radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return earth_radius_km * c


def _min_max_normalize(values: Dict[str, float]) -> Dict[str, float]:
    """Normalizes a mapping `{geo_id: value}` into `[0.0, 1.0]` within the county."""
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    span = hi - lo
    if span <= 1e-9:
        return {k: 0.5 for k in values}
    return {k: max(0.0, min(1.0, (v - lo) / span)) for k, v in values.items()}


def _inverted_checkup_gap(tract: TractHealthRecord) -> float:
    """Returns `100.0 - pct_checkup` (low routine checkup rate = high preventive care gap)."""
    if tract.pct_checkup_gap is not None:
        return float(tract.pct_checkup_gap)
    if tract.pct_checkup is not None:
        return max(0.0, min(100.0, 100.0 - float(tract.pct_checkup)))
    return 0.0


def compute_tract_scores(
    tracts: Sequence[TractHealthRecord],
    mobility_map: Optional[Dict[str, TractMobilityRecord]] = None,
    strategy: str = "balanced_uninsured_safety_net_gap",
    custom_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, ScoreBreakdown]:
    """Computes deterministic, race-blind within-county normalized need scores for all valid tracts.

    Enforces `assert_race_blind_planner_input` and `assert_no_pii_in_payload` at entry.
    Ignores zero-population tracts (`total_pop <= 0`) or tracts missing coordinates.
    """
    tracts_payload = [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in tracts]
    assert_race_blind_planner_input(tracts_payload)
    assert_no_pii_in_payload(tracts_payload)

    if mobility_map:
        mob_payload = {
            k: (v.model_dump() if hasattr(v, "model_dump") else dict(v))
            for k, v in mobility_map.items()
        }
        assert_race_blind_planner_input(mob_payload)
        assert_no_pii_in_payload(mob_payload)

    valid_tracts: List[TractHealthRecord] = [
        t
        for t in tracts
        if t.total_pop > 0 and t.latitude is not None and t.longitude is not None
    ]
    if not valid_tracts:
        return {}

    weights = resolve_strategy_weights(strategy=strategy, custom_weights=custom_weights)
    mob_lookup = mobility_map or {}

    raw_uninsured: Dict[str, float] = {}
    raw_safety_net_dist: Dict[str, float] = {}
    raw_no_vehicle: Dict[str, float] = {}
    raw_asthma: Dict[str, float] = {}
    raw_copd: Dict[str, float] = {}
    raw_diabetes: Dict[str, float] = {}
    raw_bphigh: Dict[str, float] = {}
    raw_checkup_gap: Dict[str, float] = {}
    raw_saturday_stops: Dict[str, float] = {}

    for t in valid_tracts:
        gid = t.geo_id
        raw_uninsured[gid] = float(t.pct_uninsured_18_64 or 0.0)

        km_safety = float(t.km_to_safety_net or 0.0)
        extra_km = (
            float(t.extra_km_if_uninsured)
            if t.extra_km_if_uninsured is not None
            else max(0.0, km_safety - float(t.km_to_any_care or 0.0))
        )
        raw_safety_net_dist[gid] = 0.70 * km_safety + 0.30 * max(0.0, extra_km)

        no_veh = float(t.pct_no_vehicle or 0.0)
        mob_diff = float(t.pct_mobility_difficulty or 0.0)
        lack_trans = float(t.pct_lack_transport or 0.0)
        raw_no_vehicle[gid] = 0.70 * no_veh + 0.15 * mob_diff + 0.15 * lack_trans

        raw_asthma[gid] = float(t.pct_asthma or 0.0)
        raw_copd[gid] = float(t.pct_copd or 0.0)
        raw_diabetes[gid] = float(t.pct_diabetes or 0.0)
        raw_bphigh[gid] = float(t.pct_bphigh or 0.0)
        raw_checkup_gap[gid] = _inverted_checkup_gap(t)

        mob_rec = mob_lookup.get(gid)
        raw_saturday_stops[gid] = (
            float(mob_rec.saturday_active_stops_count) if mob_rec is not None else 0.0
        )

    norm_uninsured = _min_max_normalize(raw_uninsured)
    norm_safety_dist = _min_max_normalize(raw_safety_net_dist)
    norm_no_vehicle = _min_max_normalize(raw_no_vehicle)
    norm_asthma = _min_max_normalize(raw_asthma)
    norm_copd = _min_max_normalize(raw_copd)
    norm_diabetes = _min_max_normalize(raw_diabetes)
    norm_bphigh = _min_max_normalize(raw_bphigh)
    norm_checkup_gap = _min_max_normalize(raw_checkup_gap)

    has_any_transit = any(v > 0.0 for v in raw_saturday_stops.values())
    norm_transit = (
        _min_max_normalize(raw_saturday_stops)
        if has_any_transit
        else {t.geo_id: 0.0 for t in valid_tracts}
    )

    scores: Dict[str, ScoreBreakdown] = {}
    for t in valid_tracts:
        gid = t.geo_id
        u_n = round(norm_uninsured[gid], 4)
        s_n = round(norm_safety_dist[gid], 4)
        v_n = round(norm_no_vehicle[gid], 4)
        c_raw = (
            norm_asthma[gid] + norm_copd[gid] + norm_diabetes[gid] + norm_bphigh[gid]
        ) / 4.0
        c_n = round(max(0.0, min(1.0, c_raw)), 4)
        chk_n = round(norm_checkup_gap[gid], 4)
        tr_bonus = round(norm_transit[gid], 4)

        weighted_core = (
            weights.get("uninsured", 0.30) * u_n
            + weights.get("safety_net_distance", 0.25) * s_n
            + weights.get("no_vehicle", 0.20) * v_n
            + weights.get("chronic_respiratory", 0.15) * c_n
            + weights.get("checkup_preventive_gap", 0.10) * chk_n
        )
        # Small Saturday transit tie-breaker bonus (up to +0.04, scaled inside [0.0, 1.0])
        composite = round(max(0.0, min(1.0, 0.96 * weighted_core + 0.04 * tr_bonus)), 4)

        scores[gid] = ScoreBreakdown(
            uninsured_norm=u_n,
            safety_net_distance_norm=s_n,
            no_vehicle_norm=v_n,
            chronic_respiratory_norm=c_n,
            checkup_preventive_gap_norm=chk_n,
            saturday_transit_access_bonus=tr_bonus,
            overlap_penalty=0.0,
            composite_need_score=composite,
        )

    return scores
