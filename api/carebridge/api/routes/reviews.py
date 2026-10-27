"""`/v1/reviews/{plan_request_id}`: the human review a provisional plan needs.

A plan is provisional until someone approves it and confirms a host venue for
every stop they keep. The UI reads the state and posts one action at a time.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from ...contracts.interaction_models import ReviewAction, ReviewState
from ...data.reviews import ReviewStore
from ...security import ModelArmorScreener
from ..deps import get_review_store
from ..errors import GatewayError

router = APIRouter(tags=["reviews"])

PlanId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$", description="PlanResponse.request_id")]


@router.get("/reviews/{plan_request_id}", response_model=ReviewState)
def get_review(plan_request_id: PlanId, store: Annotated[ReviewStore, Depends(get_review_store)]) -> ReviewState:
    return store.get(plan_request_id)


@router.post("/reviews/{plan_request_id}/actions", response_model=ReviewState)
def post_review_action(plan_request_id: PlanId, action: ReviewAction,
                       store: Annotated[ReviewStore, Depends(get_review_store)]) -> ReviewState:
    for text in (action.note, action.venue_name):
        if text:
            ok, reason = ModelArmorScreener().screen_input(text)
            if not ok:
                raise GatewayError(400, "blocked_input", reason)
    return store.apply(plan_request_id, action)
