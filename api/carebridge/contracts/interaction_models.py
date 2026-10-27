"""Contracts for how the UI interacts with the agents beyond one plan request.

- `AgentEvent`: one step of a run, streamed by `POST /v1/plan/stream` as
  server-sent events, so the UI timeline and agent graph show the run live.
- `AskRequest` / `AskResponse`: the outreach lead's follow-up questions about a
  plan, answered at the grain the data supports or refused (`POST /v1/ask`).
- `ReviewAction` / `ReviewState`: the human review a provisional plan needs
  before anything is announced (`/v1/reviews/{request_id}`).

`ui/lib/models.dart` mirrors these field for field.
"""

from __future__ import annotations

from typing import Literal, Optional

from carebridge._compat import BaseModel, Field
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.plan_models import DraftPlan

AgentName = Literal[
    "coordinator", "health_access", "transit_community", "evidence_validator",
    "siting_planner", "optimizer", "equity_auditor", "communications",
]


class AgentEvent(BaseModel):
    t_ms: int = Field(..., ge=0, description="Milliseconds since the run started")
    agent: AgentName
    kind: Literal["start", "skip", "tool", "finding", "state_write", "verdict", "done"]
    message: str
    parallel: bool = False
    state_key: Optional[str] = None
    draft_index: Optional[int] = Field(None, ge=0, description="Index into revision_history once written")
    verdict: Optional[Literal["reject", "approved", "needs_human_review"]] = None
    conflict_ranks: Optional[list[int]] = None
    # On the planner's draft_plan writes: the draft itself, so the map can show it
    # before the run finishes.
    draft: Optional[DraftPlan] = None


class ChatTurn(BaseModel):
    """One earlier message in the Ask conversation, oldest first."""

    role: Literal["user", "assistant"]
    text: str = Field(..., min_length=1, max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    # The request form's settings (or the plan's, once one exists): the
    # starting point for any plan the conversation proposes.
    plan: PlanRequest = Field(default_factory=PlanRequest)
    # The finished plan the conversation is about; None before the first plan.
    plan_request_id: Optional[str] = Field(None, max_length=64)
    # Earlier turns, so follow-ups ("and the second stop?") make sense.
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class AskResponse(BaseModel):
    request_id: str
    answer: str
    answered_by: AgentName
    # The SpatialGrain the answer rests on; None when nothing was claimed.
    grain: Optional[str] = None
    refused: bool = False
    citations: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    # "propose_plan" carries `proposed_plan` for the lead to confirm; nothing
    # runs until they press Generate plan. "clarify" asks them a question back.
    intent: Literal["answer", "propose_plan", "clarify"] = "answer"
    proposed_plan: Optional[PlanRequest] = None


ReviewActionKind = Literal["approve_plan", "request_changes", "confirm_venue", "reject_stop", "reopen"]


class ReviewAction(BaseModel):
    action: ReviewActionKind
    stop_rank: Optional[int] = Field(None, ge=1, le=4)
    venue_name: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=500)
    # A role, never a person's name: the review log must stay free of personal data.
    reviewer_role: str = Field("outreach_lead", pattern=r"^[a-z_]{3,40}$")


class StopReview(BaseModel):
    stop_rank: int = Field(..., ge=1, le=4)
    venue_confirmed: bool = False
    venue_name: Optional[str] = None
    rejected: bool = False


class ReviewLogEntry(BaseModel):
    at: str = Field(..., description="ISO 8601 UTC timestamp")
    action: ReviewAction


class ReviewState(BaseModel):
    plan_request_id: str
    status: Literal["pending", "approved", "changes_requested"] = "pending"
    stops: list[StopReview] = Field(default_factory=lambda: [StopReview(stop_rank=n) for n in range(1, 5)])
    log: list[ReviewLogEntry] = Field(default_factory=list)
    # Set by the review service: approved, and every kept stop has a confirmed venue.
    ready_to_announce: bool = False
