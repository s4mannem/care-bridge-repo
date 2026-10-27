"""`GET /v1/tracts/{county_fips}`: the tract layer (GeoJSON with need per strategy) for the map.

Served from the recorded Fulton layer for now. Computing it live means porting
the scoring in `ui/scripts/build_mock.py` to `carebridge/tools` and joining
TIGER tract shapes, which the planner tools will need anyway.
"""
from typing import Annotated, Any

from fastapi import APIRouter, Path

from ...mocks.recorded import RECORDED_COUNTY_FIPS, recorded_tract_layer
from ..errors import GatewayError

router = APIRouter(tags=["tracts"])

CountyFips = Annotated[str, Path(pattern=r"^\d{5}$", description="5-digit state+county FIPS, e.g. 13121")]


@router.get("/tracts/{county_fips}")
def get_tracts(county_fips: CountyFips) -> dict[str, Any]:
    layer = recorded_tract_layer(county_fips)
    if layer is None:
        raise GatewayError(404, "county_not_available", f"Only {RECORDED_COUNTY_FIPS} has a tract layer so far.")
    return layer
