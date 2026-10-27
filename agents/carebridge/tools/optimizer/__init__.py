"""CareBridge AI Four-Stop Coverage Optimizer (Deterministic Python Tool)."""

from carebridge.tools.optimizer.coverage import (
    build_runner_up_explanations,
    select_four_distinct_stops,
)
from carebridge.tools.optimizer.scoring import (
    STRATEGY_WEIGHTS,
    compute_tract_scores,
    haversine_km,
    resolve_strategy_weights,
)
from carebridge.tools.optimizer.sensitivity import run_weight_sensitivity
from carebridge.tools.optimizer.tool import optimize_four_clinic_stops

__all__ = [
    "STRATEGY_WEIGHTS",
    "build_runner_up_explanations",
    "compute_tract_scores",
    "haversine_km",
    "optimize_four_clinic_stops",
    "resolve_strategy_weights",
    "run_weight_sensitivity",
    "select_four_distinct_stops",
]
