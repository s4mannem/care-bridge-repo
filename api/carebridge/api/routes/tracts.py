"""`GET /v1/tracts/{county_fips}`: the tract layer (GeoJSON with need per strategy) for the map."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from ...data.bigquery import BigQueryRepo
from ..deps import get_repo
from ..errors import GatewayError

router = APIRouter(tags=["tracts"])

CountyFips = Annotated[str, Path(pattern=r"^\d{5}$", description="5-digit state+county FIPS, e.g. 13121")]


@router.get("/tracts/{county_fips}")
def get_tracts(county_fips: CountyFips, repo: Annotated[BigQueryRepo, Depends(get_repo)]) -> dict[str, Any]:
    # Scoring lives in carebridge/tools once the planner tools are ported from
    # ui/scripts/build_mock.py; until then this route is wired but empty.
    raise GatewayError(501, "not_implemented", f"Tract layer for {county_fips} is not built yet.")
