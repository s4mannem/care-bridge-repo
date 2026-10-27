"""Recorded Fulton plans and tract layer, served by the stub runner and `/v1/tracts`.

Generated from the real `a4i_health` tables (and ACS 2020 5-year, auditor-only)
by `ui/scripts/build_mock.py`, which writes the same files to `ui/assets/` for
the offline UI build. One PlanResponse per strategy and draft-0 defect toggle.
"""
import json
from functools import cache
from importlib import resources
from typing import Any

from ..contracts.api_models import PlanRequest, PlanResponse

RECORDED_COUNTY_FIPS = "13121"


def _read(name: str) -> Any:
    return json.loads(resources.files(__package__).joinpath("recorded", name).read_text())


@cache
def _plan(strategy: str, defect: bool) -> PlanResponse:
    return PlanResponse.model_validate(_read(f"plan_{strategy}_{'defect' if defect else 'standard'}.json"))


def recorded_plan(request: PlanRequest) -> PlanResponse | None:
    """The recorded response for this request, or None for a county we have no recording of."""
    if request.county_fips != RECORDED_COUNTY_FIPS:
        return None
    return _plan(request.strategy, request.simulate_first_draft_defect)


@cache
def recorded_tract_layer(county_fips: str) -> dict[str, Any] | None:
    """GeoJSON FeatureCollection with `geo_id`, `label`, `total_pop` and `need` per strategy."""
    if county_fips != RECORDED_COUNTY_FIPS:
        return None
    return _read("fulton_tracts.geojson")
