"""Human review of a provisional plan: the rules, and where review state is kept.

`CAREBRIDGE_REVIEW_STORE` picks the store: `memory` (tests, local runs; lost on
restart and not shared between Cloud Run instances) or `firestore` (deployed).
Documents hold roles and venue names only, never people's names.
"""
import threading
from datetime import UTC, datetime
from typing import Protocol

from ..api.errors import GatewayError
from ..config import Settings
from ..contracts.interaction_models import ReviewAction, ReviewLogEntry, ReviewState

COLLECTION = "plan_reviews"


def apply_action(state: ReviewState, action: ReviewAction) -> ReviewState:
    """Return the state after `action`. Raises GatewayError(422) for an action that doesn't fit."""
    s = state.model_copy(deep=True)
    if action.action in ("confirm_venue", "reject_stop"):
        if action.stop_rank is None:
            raise GatewayError(422, "invalid_review_action", f"{action.action} needs stop_rank.")
        stop = next(x for x in s.stops if x.stop_rank == action.stop_rank)
        if action.action == "confirm_venue":
            if not (action.venue_name or "").strip():
                raise GatewayError(422, "invalid_review_action", "confirm_venue needs venue_name.")
            stop.venue_confirmed, stop.venue_name, stop.rejected = True, action.venue_name.strip(), False
        else:
            stop.rejected, stop.venue_confirmed = True, False
        if s.status == "approved":
            s.status = "pending"  # a changed stop needs approving again
    elif action.action == "approve_plan":
        if all(x.rejected for x in s.stops):
            raise GatewayError(422, "invalid_review_action", "Every stop is rejected; nothing to approve.")
        s.status = "approved"
    elif action.action == "request_changes":
        s.status = "changes_requested"
    elif action.action == "reopen":
        s.status = "pending"
    s.log.append(ReviewLogEntry(at=datetime.now(UTC).isoformat(timespec="seconds"), action=action))
    kept = [x for x in s.stops if not x.rejected]
    s.ready_to_announce = s.status == "approved" and bool(kept) and all(x.venue_confirmed for x in kept)
    return s


class ReviewStore(Protocol):
    name: str

    def get(self, plan_request_id: str) -> ReviewState: ...

    def apply(self, plan_request_id: str, action: ReviewAction) -> ReviewState: ...


class MemoryReviewStore:
    name = "memory"

    def __init__(self) -> None:
        self._states: dict[str, ReviewState] = {}
        self._lock = threading.Lock()

    def get(self, plan_request_id: str) -> ReviewState:
        return self._states.get(plan_request_id) or ReviewState(plan_request_id=plan_request_id)

    def apply(self, plan_request_id: str, action: ReviewAction) -> ReviewState:
        with self._lock:
            new = apply_action(self.get(plan_request_id), action)
            self._states[plan_request_id] = new
            return new


class FirestoreReviewStore:
    name = "firestore"

    def __init__(self, settings: Settings):
        from google.cloud import firestore  # import here: optional locally and in tests

        self._fs = firestore
        self._db = firestore.Client(project=settings.gcp_project or settings.bq_project,
                                    database=settings.firestore_database)

    def _doc(self, plan_request_id: str):
        return self._db.collection(COLLECTION).document(plan_request_id)

    def get(self, plan_request_id: str) -> ReviewState:
        snap = self._doc(plan_request_id).get()
        return ReviewState.model_validate(snap.to_dict()) if snap.exists \
            else ReviewState(plan_request_id=plan_request_id)

    def apply(self, plan_request_id: str, action: ReviewAction) -> ReviewState:
        ref = self._doc(plan_request_id)

        @self._fs.transactional
        def run(tx) -> ReviewState:
            snap = ref.get(transaction=tx)
            current = ReviewState.model_validate(snap.to_dict()) if snap.exists \
                else ReviewState(plan_request_id=plan_request_id)
            new = apply_action(current, action)
            tx.set(ref, new.model_dump(mode="json"))
            return new

        return run(self._db.transaction())


def build_review_store(settings: Settings) -> ReviewStore:
    if settings.review_store == "firestore":
        return FirestoreReviewStore(settings)
    return MemoryReviewStore()
