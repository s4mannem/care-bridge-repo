# `carebridge.tools` — Deterministic ADK Tools Package

The [`carebridge/tools/`](file:///Users/dvt112/Downloads/A4I/carebridge/tools/__init__.py) package houses deterministic mathematical and spatial tools invoked by CareBridge Fulton's ADK agents. In accordance with CareBridge's engineering principles, **LLMs never perform mental arithmetic, Haversine distance geometry, or combinatorial set-cover optimization**—all quantitative calculations are executed inside deterministic Python tools and validated against Pydantic contracts.

---

## Subpackages

| Subpackage | Primary ADK Tool | Used By | Documentation |
| :--- | :--- | :--- | :--- |
| **[`carebridge/tools/optimizer/`](file:///Users/dvt112/Downloads/A4I/carebridge/tools/optimizer/README.md)** | [`optimize_four_clinic_stops()`](file:///Users/dvt112/Downloads/A4I/carebridge/tools/optimizer/tool.py#L41-L162) | [`siting_planner_agent`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/planner_agent/README.md) (Track 1) | [`optimizer/README.md`](file:///Users/dvt112/Downloads/A4I/carebridge/tools/optimizer/README.md) |

---

## Design Invariants

1. **Byte-Identical Determinism**: Given the same `HealthEvidence`, `MobilityEvidence`, `strategy`, and `revision_number`, tools in `carebridge.tools` produce byte-identical JSON outputs across runs (tie-broken lexicographically by 11-character `geo_id`).
2. **Race-Blind Input & Output**: Every tool in `carebridge.tools` runs [`assert_race_blind_planner_input()`](file:///Users/dvt112/Downloads/A4I/carebridge/security/race_blind_guard.py#L111-L143) and [`assert_no_pii_in_payload()`](file:///Users/dvt112/Downloads/A4I/carebridge/security/race_blind_guard.py#L79-L108) on both its inputs and its outputs.
3. **OpenTelemetry Instrumentation**: Every tool execution emits a dedicated span (`tool.<subpackage>.<tool_name>`) via [`trace_span()`](file:///Users/dvt112/Downloads/A4I/carebridge/telemetry/otel.py#L79-L103).
