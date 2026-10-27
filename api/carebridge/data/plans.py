"""Finished plans, kept so Ask can answer about them without running the agents again.

`CAREBRIDGE_PLAN_STORE` picks the store: `memory` (tests, local runs; lost on
restart and not shared between Cloud Run instances) or `firestore` (deployed).
A PlanResponse has passed the gateway's PII check before it is stored.
"""
import threading
from collections import OrderedDict
from typing import Protocol

from ..config import Settings
from ..contracts.api_models import PlanResponse

COLLECTION = "plan_responses"


class PlanStore(Protocol):
    name: str

    def get(self, plan_request_id: str) -> PlanResponse | None: ...

    def put(self, plan: PlanResponse) -> None: ...


class MemoryPlanStore:
    name = "memory"

    def __init__(self, capacity: int = 50) -> None:
        self._plans: OrderedDict[str, PlanResponse] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def get(self, plan_request_id: str) -> PlanResponse | None:
        with self._lock:
            return self._plans.get(plan_request_id)

    def put(self, plan: PlanResponse) -> None:
        with self._lock:
            self._plans[plan.request_id] = plan
            self._plans.move_to_end(plan.request_id)
            while len(self._plans) > self._capacity:
                self._plans.popitem(last=False)


class FirestorePlanStore:
    name = "firestore"

    def __init__(self, settings: Settings):
        from google.cloud import firestore  # import here: optional locally and in tests

        self._db = firestore.Client(project=settings.gcp_project or settings.bq_project,
                                    database=settings.firestore_database)

    def get(self, plan_request_id: str) -> PlanResponse | None:
        snap = self._db.collection(COLLECTION).document(plan_request_id).get()
        return PlanResponse.model_validate(snap.to_dict()) if snap.exists else None

    def put(self, plan: PlanResponse) -> None:
        self._db.collection(COLLECTION).document(plan.request_id).set(plan.model_dump(mode="json"))


def build_plan_store(settings: Settings) -> PlanStore:
    if settings.plan_store == "firestore":
        return FirestorePlanStore(settings)
    return MemoryPlanStore()
