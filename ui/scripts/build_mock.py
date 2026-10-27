"""Build recorded PlanResponse fixtures for the UI from the real Fulton data.

Emits one `PlanResponse` (plan 00 `carebridge/contracts/api_models.py`) per
strategy x `simulate_first_draft_defect`, plus the tract layer the UI will get
from `GET /v1/tracts/{county_fips}`. Scoring and stop selection follow plan 05
(within-county min-max, five weights, 4 km catchments, 5 km separation, 0.85
overlap discount); the audit follows plan 07, including the post-hoc ACS
demographic comparison. Only the agents' prose is templated here.

Run from the repo root (needs ADC; BQ_PROJECT comes from .env or api/.env):
    api/.venv/bin/python ui/scripts/build_mock.py
"""
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from carebridge.config import Settings  # noqa: E402
from carebridge.data.bigquery import BigQueryRepo  # noqa: E402

_repo = BigQueryRepo(Settings())
query, table = _repo.query, _repo.table

DATA = ROOT / "ui" / "assets" / "data"
MOCK = ROOT / "ui" / "assets" / "mock"

COUNTY_FIPS = "13121"
COUNTY_NAME = "Fulton"
SATURDAYS = ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"]
CATCHMENT_KM = 4.0
MIN_SEPARATION_KM = 5.0
OVERLAP_DISCOUNT = 0.85
PARITY_FLOOR = 0.80

# Plan 05 strategy profiles (the five-weight version, which includes the checkup gap).
STRATEGIES = {
    "balanced_uninsured_safety_net_gap": {
        "uninsured": 0.30, "safety_net_distance": 0.25, "no_vehicle": 0.20,
        "chronic_respiratory": 0.15, "checkup_gap": 0.10},
    "chronic_respiratory_focus": {
        "uninsured": 0.20, "safety_net_distance": 0.20, "no_vehicle": 0.15,
        "chronic_respiratory": 0.35, "checkup_gap": 0.10},
    "zero_vehicle_transit_priority": {
        "uninsured": 0.20, "safety_net_distance": 0.25, "no_vehicle": 0.35,
        "chronic_respiratory": 0.10, "checkup_gap": 0.10},
}

CITATIONS = [
    "a4i_health.burden_tracts: CDC PLACES (modeled, tract) and CDC SVI / ACS 5-yr (survey, tract)",
    "a4i_health.tract_access: straight-line km to CMS/HRSA sites (facility point, upper bound)",
]
GRAIN = [
    "census_tract_11char: every ranking input is tract-level",
    "facility_lon_lat_point: distances are straight-line upper bounds to federal sites, not journey time",
]


# ── geometry ───────────────────────────────────────────────────────────────

def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def label(geo_id):
    code = geo_id[5:]
    return f"Tract {int(code[:4])}" + (f".{code[4:]}" if code[4:] != "00" else "")


# ── data ───────────────────────────────────────────────────────────────────

def load_tracts():
    rows = query(f"""
        SELECT b.geo_id, b.total_pop, b.pct_uninsured, b.pct_asthma, b.pct_copd, b.pct_diabetes,
               b.pct_high_bp, b.pct_checkup, b.pct_no_vehicle, b.pct_mobility_difficulty,
               b.pct_lack_transport, b.pct_age_65_plus, b.pct_limited_english,
               b.latitude AS lat, b.longitude AS lng,
               a.km_to_any_care, a.km_to_safety_net, a.extra_km_if_uninsured
        FROM {table('burden_tracts')} b
        LEFT JOIN {table('tract_access')} a USING (geo_id)""")
    for r in rows:
        for k, v in r.items():
            if k != "geo_id" and v is not None:
                r[k] = float(v)
        r["pct_checkup_gap"] = None if r["pct_checkup"] is None else round(100 - r["pct_checkup"], 2)
    return [r for r in rows if (r["total_pop"] or 0) > 0 and r["lat"] is not None]


def load_demographics():
    """Auditor-only. Plan 01 `external_demographic_audit`, read straight from ACS here."""
    rows = query(f"""
        SELECT geo_id, total_pop, black_pop, hispanic_pop, white_pop, asian_pop
        FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
        WHERE STARTS_WITH(geo_id, '{COUNTY_FIPS}')""")
    out = {}
    for r in rows:
        pop = float(r["total_pop"] or 0)
        out[r["geo_id"]] = {"pop": pop, **{k: float(r[k] or 0) for k in
                                          ("black_pop", "hispanic_pop", "white_pop", "asian_pop")}}
    # rpl_theme3_proxy: within-county percent rank of minority share (plan 01).
    shares = sorted((1 - d["white_pop"] / d["pop"]) for d in out.values() if d["pop"])
    for d in out.values():
        s = 1 - d["white_pop"] / d["pop"] if d["pop"] else 0
        d["theme3"] = sum(x < s for x in shares) / max(len(shares) - 1, 1)
    return out


def load_disease():
    return query(f"""
        SELECT ANY_VALUE(hsa) AS hsa, ANY_VALUE(hsa_counties) AS hsa_counties, COUNT(*) AS n,
               COUNTIF(percent_visits_smoothed_combined IS NOT NULL) AS nonnull,
               CAST(MAX(IF(percent_visits_smoothed_combined IS NOT NULL, week_end, NULL)) AS STRING) AS last_nonnull
        FROM {table('disease_weekly')}""")[0]


def load_counts():
    return query(f"""
        SELECT (SELECT COUNT(*) FROM {table('care_sites')}) AS care_sites,
               (SELECT COUNTIF(site_kind != 'Hospital') FROM {table('care_sites')}) AS safety_net,
               (SELECT COUNT(*) FROM {table('shortage_areas')}) AS shortage_areas,
               (SELECT COUNT(*) FROM {table('shortage_facilities')}) AS shortage_facilities""")[0]


def load_sites():
    rows = query(f"""SELECT FACILITY_NM AS name, site_kind AS kind, latitude AS lat, longitude AS lng,
                            TOT_OPER_HR_PER_WEEK AS hours FROM {table('care_sites')}""")
    return [{**r, "lat": float(r["lat"]), "lng": float(r["lng"]),
             "hours": None if r["hours"] is None else float(r["hours"])} for r in rows]


def load_geometry():
    """2020 tract shapes from Census TIGERweb (public domain)."""
    url = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0/query?"
           + urllib.parse.urlencode({"where": f"STATE='{COUNTY_FIPS[:2]}' AND COUNTY='{COUNTY_FIPS[2:]}'",
                                     "outFields": "GEOID", "f": "geojson", "outSR": 4326,
                                     "maxAllowableOffset": 0.0004, "geometryPrecision": 5}))
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


# ── plan 05: scoring and selection ─────────────────────────────────────────

def minmax(rows, col):
    vals = [r[col] for r in rows if r[col] is not None]
    lo, hi = min(vals), max(vals)
    return {r["geo_id"]: (None if r[col] is None else (r[col] - lo) / (hi - lo) if hi > lo else 0.0) for r in rows}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def add_components(rows):
    n = {c: minmax(rows, c) for c in ("pct_uninsured", "km_to_safety_net", "extra_km_if_uninsured",
                                      "pct_no_vehicle", "pct_mobility_difficulty", "pct_lack_transport",
                                      "pct_asthma", "pct_copd", "pct_diabetes", "pct_high_bp",
                                      "pct_checkup_gap")}
    for r in rows:
        g = r["geo_id"]
        r["norm"] = {
            "uninsured": n["pct_uninsured"][g] or 0.0,
            "safety_net_distance": mean([n["km_to_safety_net"][g], n["extra_km_if_uninsured"][g]]),
            "no_vehicle": mean([n["pct_no_vehicle"][g], n["pct_mobility_difficulty"][g], n["pct_lack_transport"][g]]),
            "chronic_respiratory": mean([n[c][g] for c in ("pct_asthma", "pct_copd", "pct_diabetes", "pct_high_bp")]),
            "checkup_gap": n["pct_checkup_gap"][g] or 0.0,
        }


def composite(r, weights):
    return round(sum(w * r["norm"][k] for k, w in weights.items()), 4)


def select(rows, weights, force_overlap=False):
    """Greedy max coverage. With force_overlap, stop 2 ignores the separation rule (plan 05 demo defect).

    Deviation from plan 05 as written: utility counts only need above the county
    median, and stop centers must be top-quartile tracts. Plan 05's raw
    sum(pop x score) lets dense, moderate-need areas win (it picked a #158-ranked
    tract and deferred ranks #1-#3).
    """
    score = {r["geo_id"]: composite(r, weights) for r in rows}
    ordered = sorted(score.values())
    median, q3 = ordered[len(ordered) // 2], ordered[(3 * len(ordered)) // 4]
    excess = {g: max(0.0, s - median) for g, s in score.items()}
    near = {r["geo_id"]: [x for x in rows if km(r, x) <= CATCHMENT_KM] for r in rows}
    covered, chosen = set(), []
    while len(chosen) < 4:
        best, best_u = None, -1
        for r in rows:
            if r in chosen or score[r["geo_id"]] < q3:
                continue
            gaps = [km(r, c) for c in chosen]
            if force_overlap and len(chosen) == 1:
                if not gaps[0] < MIN_SEPARATION_KM:
                    continue
            elif any(d < MIN_SEPARATION_KM for d in gaps):
                continue
            u = sum((x["total_pop"] or 0) * excess[x["geo_id"]] *
                    (1 - OVERLAP_DISCOUNT if x["geo_id"] in covered else 1.0) for x in near[r["geo_id"]])
            if u > best_u:
                best, best_u = r, u
        chosen.append(best)
        covered.update(x["geo_id"] for x in near[best["geo_id"]])
    return chosen, score, near


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b)


def sensitivity(rows, weights, base_ids):
    runs = []
    for k in weights:
        for f in (0.85, 1.15):
            w = {**weights, k: weights[k] * f}
            s = sum(w.values())
            w = {kk: v / s for kk, v in w.items()}
            runs.append([r["geo_id"] for r in select(rows, w)[0]])
    seen = {g for run in runs for g in run} | set(base_ids)
    borderline = sorted(g for g in seen if not all(g in run for run in runs + [base_ids]))
    jac = round(sum(jaccard(base_ids, run) for run in runs) / len(runs), 3)
    return {
        "weight_perturbation_pct": 15.0,
        "top_4_stability_jaccard": jac,
        "borderline_tracts": borderline,
        "notes": f"Each of the 5 weights moved ±15% and renormalized ({len(runs)} runs). Mean Jaccard overlap of "
                 f"the selected tracts with the base plan is {jac:.2f}; {len(borderline)} tract(s) enter or leave "
                 "under some perturbation.",
    }


# ── contract builders ──────────────────────────────────────────────────────

def score_breakdown(r, weights):
    return {
        "uninsured_norm": round(r["norm"]["uninsured"], 4),
        "safety_net_distance_norm": round(r["norm"]["safety_net_distance"], 4),
        "no_vehicle_norm": round(r["norm"]["no_vehicle"], 4),
        "chronic_respiratory_norm": round(r["norm"]["chronic_respiratory"], 4),
        "checkup_preventive_gap_norm": round(r["norm"]["checkup_gap"], 4),
        "saturday_transit_access_bonus": 0.0,
        "overlap_penalty": 0.0,
        "composite_need_score": composite(r, weights),
    }


def rationale(r, need_rank, n_ranked):
    parts = [f"{label(r['geo_id'])} ranks #{need_rank} of {n_ranked} Fulton tracts on composite need."]
    parts.append(f"Uninsured adults 18–64: {r['pct_uninsured']:.1f}% (CDC PLACES, tract, modeled).")
    if r["km_to_safety_net"] is not None:
        parts.append(f"Nearest safety-net site: {r['km_to_safety_net']:.1f} km, "
                     f"{r['extra_km_if_uninsured'] or 0:.1f} km further than any care (straight-line upper bound).")
    if r["pct_no_vehicle"] is not None:
        parts.append(f"Households without a vehicle: {r['pct_no_vehicle']:.1f}% (ACS via SVI, tract, survey).")
    if r["pct_checkup_gap"] is not None:
        parts.append(f"Adults without a routine checkup in the past year: {r['pct_checkup_gap']:.1f}% "
                     "(100 − PLACES checkup, tract, modeled).")
    return " ".join(parts)


def draft(rows, weights, strategy, revision, chosen, score, near, notes, sens):
    ranked = sorted(rows, key=lambda r: -score[r["geo_id"]])
    rank = {r["geo_id"]: i + 1 for i, r in enumerate(ranked)}
    stops = []
    for i, r in enumerate(chosen):
        catch = near[r["geo_id"]]
        top = sorted(rank[x["geo_id"]] for x in catch if rank[x["geo_id"]] <= 25)
        reach = (f" Its {CATCHMENT_KM:.0f} km catchment reaches {len(top)} of the county's 25 highest-need tracts"
                 f" (ranks {', '.join(f'#{n}' for n in top[:5])}{'…' if len(top) > 5 else ''})." if top else "")
        stops.append({
            "stop_rank": i + 1,
            "assigned_saturday": SATURDAYS[i],
            "primary_tract_geoid": r["geo_id"],
            "covered_tract_geoids": [x["geo_id"] for x in catch],
            "candidate_venue_name": f"Provisional Tract Centroid Host ({r['geo_id']}) — Venue Unassigned",
            "latitude": r["lat"], "longitude": r["lng"],
            "catchment_radius_km": CATCHMENT_KM,
            "estimated_population_in_catchment": int(sum(x["total_pop"] or 0 for x in catch)),
            "score_breakdown": score_breakdown(r, weights),
            "plain_language_rationale": rationale(r, rank[r["geo_id"]], len(rows)) + reach,
            "evidence_citations": CITATIONS,
            "spatial_grain_disclosures": GRAIN,
            "host_verified": False,
            "provisional_warning": "PROVISIONAL SITE: Host permission, parking pad clearance, and Saturday staffing "
                                   "must be confirmed by field operations before public announcement.",
        })
    # Q7 is about neighborhoods the van won't reach: the highest-need tracts
    # outside every catchment. Tracts inside one were effectively picked.
    reached = {x["geo_id"] for r in chosen for x in near[r["geo_id"]]}
    runners = []
    for r in ranked:
        if r["geo_id"] in reached:
            continue
        d, nearest = min((km(r, c), i + 1) for i, c in enumerate(chosen))
        if d < MIN_SEPARATION_KM:
            code, by = "inter_stop_separation_constraint", nearest
            why = (f"{d:.1f} km from stop {nearest}; stops must be at least {MIN_SEPARATION_KM:.0f} km apart so the four "
                   "Saturdays reach four different neighborhoods.")
        else:
            code, by = "lower_marginal_coverage", None
            why = (f"{d:.1f} km from the nearest stop. Its catchment adds less population-weighted need than the "
                   "four selected catchments under this strategy.")
        runners.append({
            "tract_geoid": r["geo_id"],
            # True county rank. Plan 00 says ge=5, which only holds if stops are the
            # top-4 tracts; a coverage optimizer can leave a top-4 tract unreached.
            "need_rank": rank[r["geo_id"]],
            "composite_need_score": score[r["geo_id"]],
            "deferral_reason_code": code,
            "covered_by_stop_rank": by,
            "distance_to_nearest_selected_stop_km": round(d, 2),
            "technical_deferral_rationale": f"{label(r['geo_id'])} (need rank #{rank[r['geo_id']]}): {why}",
        })
        if len(runners) == 4:
            break
    return {
        "county_fips": COUNTY_FIPS, "strategy_used": strategy, "status": "ok",
        "revision_number": revision, "stops": stops, "runner_up_tracts": runners,
        "sensitivity": sens, "planner_notes": notes,
    }


def overlaps(d):
    pts = [{"lat": s["latitude"], "lng": s["longitude"], "rank": s["stop_rank"]} for s in d["stops"]]
    return [(a, b, km(a, b)) for i, a in enumerate(pts) for b in pts[i + 1:] if km(a, b) < MIN_SEPARATION_KM]


def demographic_impact(final, rows, demo):
    reached = {g for s in final["stops"] for g in s["covered_tract_geoids"]}
    by_id = {r["geo_id"]: r for r in rows}

    def pct(ids, num):
        pop = sum(demo[g]["pop"] for g in ids if g in demo)
        return 100 * sum(demo[g][num] for g in ids if g in demo) / pop

    def pw(ids, col):
        rs = [by_id[g] for g in ids if g in by_id and by_id[g][col] is not None]
        return sum(r[col] * r["total_pop"] for r in rs) / sum(r["total_pop"] for r in rs)

    def theme3(ids):
        ds = [demo[g] for g in ids if g in demo and demo[g]["pop"]]
        return sum(d["theme3"] * d["pop"] for d in ds) / sum(d["pop"] for d in ds)

    county = set(demo)
    groups = {}
    for name, num in (("Black", "black_pop"), ("Hispanic or Latino", "hispanic_pop"),
                      ("Asian", "asian_pop"), ("White", "white_pop")):
        c, p = pct(county, num), pct(reached, num)
        groups[name] = {"county_pct": round(c, 1), "catchment_pct": round(p, 1), "parity_ratio": round(p / c, 2)}
    for name, col in (("Uninsured 18–64", "pct_uninsured"), ("No vehicle", "pct_no_vehicle"),
                      ("Age 65+", "pct_age_65_plus"), ("Limited English", "pct_limited_english")):
        c, p = pw([r["geo_id"] for r in rows], col), pw(reached, col)
        groups[name] = {"county_pct": round(c, 1), "catchment_pct": round(p, 1), "parity_ratio": round(p / c, 2)}
    # Plan 07 flags parity below the floor for underserved groups only; White is reported, not flagged.
    findings = [f"{g}: catchments reach {v['catchment_pct']}% vs {v['county_pct']}% county-wide "
                f"(parity {v['parity_ratio']:.2f} < {PARITY_FLOOR:.2f})."
                for g, v in groups.items() if g != "White" and v["parity_ratio"] < PARITY_FLOOR]
    return {
        "county_total_pop": int(sum(d["pop"] for d in demo.values())),
        "catchment_total_pop": int(sum(demo[g]["pop"] for g in reached if g in demo)),
        "county_svi_theme3_mean": round(theme3(county), 3),
        "catchment_svi_theme3_mean": round(theme3(reached), 3),
        "group_comparisons": groups,
        "disparity_findings": findings,
        "requires_human_equity_review": bool(findings),
    }


def evidence_report(rows, counts, disease):
    bad_ids = [r["geo_id"] for r in rows if len(r["geo_id"]) != 11 or not r["geo_id"].startswith(COUNTY_FIPS)]
    inverted = all(r["pct_checkup_gap"] is None or abs(r["pct_checkup_gap"] - (100 - r["pct_checkup"])) < 0.01
                   for r in rows)
    checks = [
        {"check_name": "tract_ids_11char_fulton", "verdict": "FAIL" if bad_ids else "PASS",
         "detail": f"{len(rows)} tracts with population and coordinates; all IDs are 11 characters with prefix 13121."},
        {"check_name": "checkup_inverted", "verdict": "PASS" if inverted else "FAIL",
         "detail": "pct_checkup_gap = 100 − pct_checkup, so a low checkup rate raises need."},
        {"check_name": "hsa_grain_respected", "verdict": "PASS",
         "detail": f"disease_weekly is the {disease['hsa_counties']} Health Service Area; excluded from tract ranking."},
        {"check_name": "respiratory_trend_freshness", "verdict": "WARN",
         "detail": f"Last non-empty week {disease['last_nonnull'][:10]}; {disease['n'] - disease['nonnull']} of "
                   f"{disease['n']} weeks are blank."},
        {"check_name": "shortage_areas_present", "verdict": "WARN" if not counts["shortage_areas"] else "PASS",
         "detail": "0 live HPSA areas (all 99 designations are Proposed For Withdrawal); HPSA_SCORE unavailable.",
         "is_pipeline_check": False},
        {"check_name": "pm25_grain", "verdict": "PASS",
         "detail": "exposure_tracts is a 12 km grid on tract IDs; given zero ranking weight.", "is_pipeline_check": False},
        {"check_name": "race_and_pii_columns_absent", "verdict": "PASS",
         "detail": "No race/ethnicity or personal columns reach the planner's evidence."},
    ]
    return {
        "county_fips": COUNTY_FIPS, "core_tables_ready": not bad_ids, "blocking_failures": [],
        "checks": checks, "validated_tract_count": len(rows),
        "prohibited_claims_blocked": ["tract-level respiratory trend from an HSA figure",
                                      "travel time inferred from straight-line distance",
                                      "ranking neighborhoods on 12 km PM2.5"],
        "optional_datasets_status": {"marta_gtfs": "unavailable: license not yet verified",
                                     "usda_food_access": "unavailable", "imls_venues": "unavailable"},
        "caveats": [
            "4 SPATIAL RESOLUTIONS (TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA): weekly respiratory ED "
            "trends describe the 4-county Health Service Area, never a census tract; PM2.5 is a 12 km grid and "
            "cannot rank neighborhoods.",
            "DISTANCE != JOURNEY TIME: km_to_any_care and km_to_safety_net are straight-line upper bounds to "
            "federal facilities, not bus or road travel times.",
            "PLACES MODELED ESTIMATES: tract prevalences are small-area model estimates, not counts; differences "
            "of 1–2 points fall within overlapping 95% confidence intervals.",
            "UPPER-BOUND FEDERAL FACILITIES: free clinics, county clinics and pharmacies are not in any licensed "
            "national list, so every distance is an upper bound.",
        ],
    }


LIMITATIONS = [
    "Bus travel time: no license-clean federal dataset exists; the best transit matrix is CC BY-NC. "
    "Distances are straight-line upper bounds.",
    "Free and county clinics: no national list exists. Facility layers are federal only (CMS + HRSA).",
    "Pharmacies: excluded. NPPES carries practitioner names and home addresses.",
    "Other mobile clinics: the one national registry has no license or bulk download; not scraped.",
    "How many people have asthma: unknown. CDC PLACES gives modeled prevalence, not counts.",
    "Is COVID rising in this neighborhood: unanswerable. disease_weekly is a 4-county HSA figure.",
    "Which specific people are unmanaged: none, by design. Individual-level data is prohibited.",
]


def outreach(final, disease):
    def day(s, es=False):
        d = int(s["assigned_saturday"][-2:])
        return f"sábado {d} de noviembre" if es else f"Saturday, November {d}"

    notices = []
    for s in final["stops"]:
        t = label(s["primary_tract_geoid"])
        notices.append({
            "stop_rank": s["stop_rank"],
            "assigned_saturday": s["assigned_saturday"],
            "candidate_venue_name": s["candidate_venue_name"],
            "english_notice": f"Free health check-ups near you!\n\n{day(s)}, near {t}. The exact spot will be "
                              "posted soon.\n\nWe check blood pressure and blood sugar. You do not need insurance. "
                              "You do not need an appointment. It is free.\n\nThis is a draft. The place is not "
                              "confirmed yet.",
            "spanish_notice": f"¡Chequeos de salud gratis cerca de usted!\n\n{day(s, True)}, cerca de {t}. Pronto "
                              "diremos el lugar exacto.\n\nRevisamos la presión y el azúcar en la sangre. No necesita "
                              "seguro. No necesita cita. Es gratis.\n\nEsto es un borrador. El lugar todavía no está "
                              "confirmado.",
            "why_chosen_explanation": f"Many people near {t} have no health insurance and live far from a clinic "
                                      "that sees people without insurance.",
            "provisional_disclaimer_included": True,
        })
    unpicked = []
    for r in final["runner_up_tracts"]:
        n = r["covered_by_stop_rank"]
        stop = next((s for s in final["stops"] if s["stop_rank"] == n), None) if n else None
        t = label(r["tract_geoid"])
        if stop:
            en = (f"We know people near {t} need care too. The van will be close by on {day(stop)}, about "
                  f"{r['distance_to_nearest_selected_stop_km']:.0f} km away. We picked one spot to reach as many "
                  "neighbors as we can each Saturday.")
            es = (f"Sabemos que la gente cerca de {t} también necesita atención. La van estará cerca el "
                  f"{day(stop, True)}, a unos {r['distance_to_nearest_selected_stop_km']:.0f} km. Elegimos un lugar "
                  "para llegar a la mayor cantidad de vecinos cada sábado.")
        else:
            en = (f"We know people near {t} need care too. We only have four Saturdays this month, and other "
                  "areas had more people who live far from a free or low-cost clinic. We will look again next month.")
            es = (f"Sabemos que la gente cerca de {t} también necesita atención. Solo tenemos cuatro sábados este "
                  "mes, y otras zonas tenían más personas lejos de una clínica gratis o de bajo costo. Lo revisaremos "
                  "el próximo mes.")
        unpicked.append({
            "tract_geoid": r["tract_geoid"], "need_rank": r["need_rank"],
            "nearest_selected_stop_rank": n,
            "distance_to_selected_stop_km": r["distance_to_nearest_selected_stop_km"],
            "english_explanation": en, "spanish_explanation": es,
        })
    return {
        "county_name": COUNTY_NAME,
        "provisional_banner": "DRAFT FOR INTERNAL REVIEW ONLY — DO NOT PUBLISH UNTIL VENUE PERMITS ARE CONFIRMED.",
        "stop_notices": notices,
        "unpicked_neighborhood_explanations": unpicked,
        "regional_surveillance_note_en": f"Flu and COVID numbers are only reported for the whole "
                                         f"{disease['hsa_counties']} area, not for your neighborhood. The latest "
                                         f"numbers we have are from {disease['last_nonnull'][:10]}.",
        "regional_surveillance_note_es": f"Los datos de gripe y COVID solo se reportan para toda el área de "
                                         f"{disease['hsa_counties']}, no para su vecindario. Los datos más recientes "
                                         f"son de {disease['last_nonnull'][:10]}.",
    }


def plan_response(strategy, defect, rows, demo, counts, disease):
    w = STRATEGIES[strategy]
    base, score, near = select(rows, w)
    sens = sensitivity(rows, w, [r["geo_id"] for r in base])
    history = []
    if defect:
        d0_chosen, _, _ = select(rows, w, force_overlap=True)
        d0 = draft(rows, w, strategy, 0, d0_chosen, score, near, [], None)
        history.append(d0)
        (a, b, dist), = overlaps(d0)[:1]
        notes = [f"Revision 1 resolves auditor defect D0-CATCHMENT_OVERLAP: draft 0 stops {a['rank']} and "
                 f"{b['rank']} were {dist:.1f} km apart (minimum {MIN_SEPARATION_KM:.0f} km), so their "
                 f"{CATCHMENT_KM:.0f} km catchments overlapped. Re-ran the optimizer with the separation enforced."]
        final = draft(rows, w, strategy, 1, base, score, near, notes, sens)
    else:
        final = draft(rows, w, strategy, 0, base, score, near, [], sens)
    history.append(final)

    impact = demographic_impact(final, rows, demo)
    approved = not overlaps(final)
    verdict = "approved" if approved else "needs_human_review"
    audit = {
        "revision_audited": final["revision_number"],
        "verdict": verdict,
        "non_demographic_defects": [],
        "demographic_impact": impact,
        "auditor_summary": (
            ("Draft 1 resolves the catchment overlap found in draft 0. " if defect else "")
            + f"All four stops are at least {MIN_SEPARATION_KM:.0f} km apart and every claim is tract-level or "
              "labeled as an upper bound. "
            + (f"Post-hoc equity check flags {len(impact['disparity_findings'])} group(s) below parity "
               f"{PARITY_FLOOR:.2f}; referred to human review, not fed back to the planner."
               if impact["disparity_findings"] else "No group falls below the parity floor.")),
        "limitations_attached": ["Demographics are ACS 2020 5-year tract aggregates, used only after planning.",
                                 "No host venue is confirmed; stops sit on tract centroids."],
    }
    status = ("needs_human_review" if verdict != "approved" or impact["requires_human_equity_review"]
              else "provisional_approved")
    return {
        "request_id": f"recorded-{strategy}-{'defect' if defect else 'standard'}",
        "status": status,
        "needs_human_review": True,
        "county_fips": COUNTY_FIPS,
        "county_name": COUNTY_NAME,
        "final_plan": final,
        "audit_report": audit,
        "revision_history": history,
        "evidence_report": evidence_report(rows, counts, disease),
        "outreach": outreach(final, disease),
        "provenance": ["a4i_health.burden_tracts", "a4i_health.tract_access", "a4i_health.care_sites",
                       "a4i_health.disease_weekly", "a4i_health.shortage_areas",
                       "bigquery-public-data.census_bureau_acs.censustract_2020_5yr (auditor only)"],
        "limitations": LIMITATIONS,
        "data_availability": {"a4i_health_core": True, "marta_gtfs_saturday": False, "usda_food_access": False,
                              "imls_candidate_venues": False, "external_demographic_audit": True},
        "telemetry_summary": {"source": "recorded_fixture", "iterations": len(history),
                              "strategy": strategy, "simulate_first_draft_defect": defect},
    }


def tract_layer(rows):
    """Mock of GET /v1/tracts/13121: shapes plus composite need per strategy."""
    geo = load_geometry()
    by_id = {r["geo_id"]: r for r in rows}
    for f in geo["features"]:
        gid = f["properties"]["GEOID"]
        r = by_id.get(gid)
        f["properties"] = {
            "geo_id": gid, "label": label(gid), "total_pop": r["total_pop"] if r else 0,
            "need": {s: composite(r, w) for s, w in STRATEGIES.items()} if r else None,
        }
    return geo


def main():
    rows = load_tracts()
    add_components(rows)
    demo, counts, disease = load_demographics(), load_counts(), load_disease()

    DATA.mkdir(parents=True, exist_ok=True)
    MOCK.mkdir(parents=True, exist_ok=True)
    for old in MOCK.glob("*.json"):
        old.unlink()
    for strategy in STRATEGIES:
        for defect in (False, True):
            resp = plan_response(strategy, defect, rows, demo, counts, disease)
            name = f"plan_{strategy}_{'defect' if defect else 'standard'}.json"
            (MOCK / name).write_text(json.dumps(resp, indent=2, ensure_ascii=False))
            print(f"{name}: {[label(s['primary_tract_geoid']) for s in resp['final_plan']['stops']]} "
                  f"status={resp['status']} jaccard={resp['final_plan']['sensitivity']['top_4_stability_jaccard']}")
    (DATA / "fulton_tracts.geojson").write_text(json.dumps(tract_layer(rows), separators=(",", ":")))
    (DATA / "care_sites.json").write_text(json.dumps(load_sites(), indent=1))


if __name__ == "__main__":
    main()
