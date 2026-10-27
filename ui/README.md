# Mobile Care Planner (Flutter)

The CareBridge operations UI for the **Siting** track: an outreach lead plans four Saturday mobile-clinic
stops in Fulton County and watches the planner and auditor disagree before a plan is approved.
One codebase for web, iOS and Android. Spec: `plans/11_operations_ui_flutter.md`.

## Run it

```bash
cd ui
flutter pub get
flutter test
flutter run -d chrome                                                    # recorded responses
flutter run -d chrome --dart-define=CAREBRIDGE_API=http://127.0.0.1:8080 # live gateway (plan 10)
```

Wide screens (≥ 1100 px) show three columns: request form, map with Clinic Plan tabs, and the agent run.
Phones get a bottom bar with Plan, Agents and Request.

## How it fits the system

- **Contract:** `lib/models.dart` mirrors plan 00's `PlanRequest` / `PlanResponse` field for field.
- **Source:** `lib/plan_source.dart`. `RecordedPlanSource` (default) loads
  `assets/mock/plan_<strategy>_<standard|defect>.json`; `HttpPlanSource` calls `POST /v1/plan` and
  `GET /v1/tracts/{county_fips}`. It sends no API key, because a key in a Flutter bundle is public
  (see plan 11 §4).
- **Replay:** `/v1/plan` returns one JSON response, so `lib/replay.dart` rebuilds the agent run from
  `revision_history`, `evidence_report`, `audit_report` and `outreach`.

## Recorded responses

`scripts/build_mock.py` computes all six responses (three strategies, defect toggle on or off) from the real
`a4i_health` tables and ACS 2020 5-year data, following plans 05 and 07. Only the agents' wording is
templated. To regenerate, run from the repo root:

```bash
api/.venv/bin/python ui/scripts/build_mock.py   # BQ_PROJECT from .env or api/.env
```

The fixtures diverge from plan 00 and plan 05 in three places, all listed in plan 11 §5:
- They carry true `need_rank` values below 5.
- Selection counts only need above the county median.
- Runner-ups are the high-need tracts outside every catchment.

## Known gaps

- Draft 0's audit isn't in the contract; the rejection is reconstructed from `revision_history`.
- No host venues are loaded, so stops sit on tract centroids and every stop is provisional.
- The map legend covers part of the map on small phones.
- Basemap tiles come from OpenStreetMap. That's fine for a demo, but production traffic needs a tile provider.
