# Plan 08 — Community Communications Agent (Grounded Bilingual Explanation Agent)

> **Component Role**: Implements the **Community Communications Agent** (`data-node="communicator"`) in Lane 02 (Output Stage) of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` consuming `session.state["final_plan"]` and `session.state["audit_report"]` (limitations/status), writing `session.state["outreach_messages"]`.

---

## 1. Executive Summary & Architectural Purpose

As noted in `c5_01_load_explore.ipynb` Section 13:
> *"1. Two of your jobs need contradictory instructions. A clinical-safety reviewer whose whole prompt is hedge, cite, refuse if unsure cannot share a system prompt with an outreach writer whose prompt is warm, plain language, sixth-grade reading level, Spanish and English. Put both in one agent and you get hedged flyers and chatty triage notes."*

And from the CareBridge AI architecture diagram:
- **Responsibility**: *"Drafts plain-language English / Spanish outreach notices and explains why locations were chosen. Mini tag: `No invented bookings`. Writes `outreach_messages`. It must not announce unconfirmed parking locations, dates or availability as booked."*
- **State Contract**:
  - **Reads**: `session.state["final_plan"]` and `session.state["audit_report"]` (for limitations and provisional status).
  - **Writes**: `output_key="outreach_messages"` (`OutreachMessages` JSON / Pydantic model).
- **Non-Negotiable Grounding & Anti-Hallucination Rules**:
  1. **No Invented Bookings**: Must explicitly mark every English and Spanish outreach draft as a **PROVISIONAL DRAFT PENDING SITE CONFIRMATION** (`"Proposed site — pending host permit & Saturday schedule confirmation"` / `"Sitio propuesto — pendiente de confirmación del lugar y horario del sábado"`).
  2. **No Medical Triage or Clinical Advice**: Explains *where* the mobile health van is proposed to visit and *why* the neighborhood was prioritized (distance to sliding-scale care, households without cars, routine checkup and chronic screening need), without giving medical advice.
  3. **Accurate Regional Surveillance Context**: Includes `regional_surveillance_note_en` and `regional_surveillance_note_es` explaining that weekly respiratory virus updates (COVID-19, flu, RSV) reflect the broader multi-county Atlanta Health Service Area, not a single neighborhood.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── communicator_agent/
│           ├── __init__.py
│           ├── prompts.py
│           └── agent.py
└── tests/
    └── test_08_communicator_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: System Prompt (`carebridge/agents/communicator_agent/prompts.py`)

```python
COMMUNICATOR_AGENT_INSTRUCTION = """You are the CareBridge AI Community Communications Agent (Explanation Agent).
Your tone is WARM, WELCOMING, ACTION-ORIENTED, and ACCESSIBLE (6th-grade reading level, zero epidemiological jargon,
readable by a resident standing at a bus stop) in both English and Spanish.
Notice how your instructions intentionally contradict the Siting Planner and Auditor: they hedge, cite confidence
intervals, and qualify spatial resolutions for clinical/technical reviewers; you translate the approved plan into clear,
human-centered community flyers without statistical hedging or invented bookings.

Inputs from session.state:
- final_plan: {final_plan?}
- audit_report: {audit_report?}

STRICT GROUNDING RULES (NO HALLUCINATIONS OR INVENTED BOOKINGS):
1. You may ONLY reference the 4 stops, candidate venue names, Saturday dates, runner-up tracts, and evidence present
   in `final_plan`.
2. NEVER announce any location, parking lot, date, or appointment slot as confirmed or booked. Every English
   notice MUST include a clear provisional notice ("PROPOSED LOCATION — Pending host site confirmation before
   public release") and every Spanish notice MUST include ("UBICACIÓN PROPUESTA — Pendiente de confirmación del
   sitio antes del anuncio público").
3. For each of the 4 selected stops, write:
   - `english_notice`: Warm, plain-language community bus-stop flyer draft (6th-grade reading level) explaining proposed
     preventive screenings (blood pressure, diabetes, routine checkups, respiratory support) and Saturday bus access.
   - `spanish_notice`: Culturally natural, accurate Spanish translation at the same 6th-grade reading level.
   - `why_chosen_explanation`: Clear explanation for residents and community partners explaining why this neighborhood
     was prioritized (distance to sliding-scale care, households without cars, uninsured and routine checkup need).
4. Answer Question 7 ("How do I tell the neighborhood we didn't pick why we didn't pick them?"):
   For each entry in `final_plan.runner_up_tracts`, populate `unpicked_neighborhood_explanations` with an empathetic,
   honest `english_explanation` and `spanish_explanation` explaining why the van could not stop directly in their
   tract this month (e.g., only 4 Saturdays available and a nearby Saturday stop at `nearest_selected_stop_rank`
   is within `distance_to_selected_stop_km` km to avoid overlapping two vans in the same area) and inviting them to
   that nearest stop.
5. Populate `regional_surveillance_note_en` and `regional_surveillance_note_es` stating clearly in plain language that
   weekly respiratory virus updates (COVID-19, flu, RSV) are tracked across the 4-county Atlanta area, not by
   individual street or neighborhood.
"""
```

---

### Step 3.2: Grounded Post-Model Verification & Agent Definition (`carebridge/agents/communicator_agent/agent.py`)

Implement `communicator_after_model_guardrail`:
- Scans the generated `OutreachMessages` output for forbidden booking phrases (`"officially booked"`, `"confirmed parking"`, `"guaranteed appointments"`, `"reservado oficialmente"`) without a provisional qualifier.
- Verifies that `provisional_disclaimer_included` is `True` on all 4 `StopOutreachDraft` items and that both `english_notice` and `spanish_notice` are non-empty.

```python
from google.adk.agents import LlmAgent
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_OUTREACH_MESSAGES
from carebridge.contracts.outreach_models import OutreachMessages
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.agents.communicator_agent.prompts import COMMUNICATOR_AGENT_INSTRUCTION


def build_community_communications_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="community_communications_agent",
        model=settings.gemini_model_fast,
        description=(
            "Community Communications Agent: Drafts grounded, 6th-grade reading level English and Spanish "
            "provisional outreach notices and plain-language siting explanations without inventing bookings."
        ),
        instruction=COMMUNICATOR_AGENT_INSTRUCTION,
        output_key=STATE_OUTREACH_MESSAGES,
        output_schema=OutreachMessages,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            safety_settings=default_vertex_safety_settings(),
        ),
        after_model_callback=communicator_after_model_guardrail,
    )
```

---

## 4. Security, Guardrails & Telemetry

- **Anti-Misinformation Guardrail (OWASP LLM09)**: `communicator_after_model_guardrail` deterministically checks that every stop notice contains a provisional/unconfirmed disclaimer in both English and Spanish and that only tract IDs / venue names present in `final_plan` appear in the text.
- **No PII or Clinical Advice**: Verified by `assert_no_pii_in_payload`.
- **Telemetry**: Emits OpenTelemetry span `agent.communicator.draft_outreach` with `stops_drafted_count`, `languages=["en", "es"]`, and token usage.

---

## 5. Verification & Unit Tests (`tests/test_08_communicator_agent.py`)

Run standalone:
```bash
pytest tests/test_08_communicator_agent.py -v
```
Tests must verify:
1. Given a valid `final_plan` and `audit_report` in `session.state`, `communicator_agent` (or its deterministic formatter helper) produces an `OutreachMessages` object with 4 bilingual stop drafts.
2. `communicator_after_model_guardrail` rejects any notice that claims a venue is `"confirmed and booked"` without a provisional disclaimer.
3. Both English and Spanish regional surveillance notes explicitly mention the multi-county Health Service Area (HSA).

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 08:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/08_community_communications_agent.md`. Create `carebridge/agents/communicator_agent/` (`__init__.py`, `prompts.py`, `agent.py`) and `tests/test_08_communicator_agent.py`. Run `pytest tests/test_08_communicator_agent.py -v` and confirm all tests pass."
