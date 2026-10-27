/// Dart mirror of the plan 00 API contract (`carebridge/contracts/*_models.py`).
///
/// Field names follow the JSON exactly. Only `PlanRequest` is serialized; the
/// rest is parsed from `POST /v1/plan`. Parsing is tolerant of missing optional
/// fields so a partial or `error` response still renders.
library;

import 'package:latlong2/latlong.dart';

double _d(Object? v) => (v as num?)?.toDouble() ?? 0;
List<T> _list<T>(Object? v, T Function(Map<String, dynamic>) f) =>
    [for (final e in (v as List?) ?? const []) f(e as Map<String, dynamic>)];

// ── api_models ─────────────────────────────────────────────────────────────

enum Strategy {
  balanced('balanced_uninsured_safety_net_gap', 'Balanced',
      'Uninsured share and distance to a safety-net clinic lead'),
  chronic('chronic_respiratory_focus', 'Chronic & respiratory',
      'Asthma, COPD, diabetes and high blood pressure lead'),
  zeroVehicle('zero_vehicle_transit_priority', 'No car',
      'Households without a car or with mobility limits lead');

  const Strategy(this.wire, this.label, this.description);
  final String wire;
  final String label;
  final String description;

  static Strategy parse(String s) => values.firstWhere((v) => v.wire == s, orElse: () => balanced);
}

class PlanRequest {
  const PlanRequest({
    this.countyFips = '13121',
    this.countyName = 'Fulton',
    this.stateAbbr = 'GA',
    this.saturdays = const ['2026-11-07', '2026-11-14', '2026-11-21', '2026-11-28'],
    this.strategy = Strategy.balanced,
    this.includeOptionalDatasets = true,
    this.simulateFirstDraftDefect = false,
  });

  final String countyFips;
  final String countyName;
  final String stateAbbr;
  final List<String> saturdays;
  final Strategy strategy;
  final bool includeOptionalDatasets;
  final bool simulateFirstDraftDefect;

  PlanRequest copyWith({Strategy? strategy, bool? includeOptionalDatasets, bool? simulateFirstDraftDefect}) =>
      PlanRequest(
        countyFips: countyFips,
        countyName: countyName,
        stateAbbr: stateAbbr,
        saturdays: saturdays,
        strategy: strategy ?? this.strategy,
        includeOptionalDatasets: includeOptionalDatasets ?? this.includeOptionalDatasets,
        simulateFirstDraftDefect: simulateFirstDraftDefect ?? this.simulateFirstDraftDefect,
      );

  Map<String, dynamic> toJson() => {
        'county_fips': countyFips,
        'county_name': countyName,
        'state_abbr': stateAbbr,
        'saturdays': saturdays,
        'strategy': strategy.wire,
        'include_optional_datasets': includeOptionalDatasets,
        'simulate_first_draft_defect': simulateFirstDraftDefect,
      };
}

class PlanResponse {
  PlanResponse.fromJson(Map<String, dynamic> j)
      : requestId = j['request_id'],
        status = j['status'],
        needsHumanReview = j['needs_human_review'] ?? true,
        countyFips = j['county_fips'],
        countyName = j['county_name'],
        finalPlan = j['final_plan'] == null ? null : DraftPlan.fromJson(j['final_plan']),
        auditReport = j['audit_report'] == null ? null : AuditReport.fromJson(j['audit_report']),
        revisionHistory = _list(j['revision_history'], DraftPlan.fromJson),
        evidenceReport = j['evidence_report'] == null ? null : EvidenceReport.fromJson(j['evidence_report']),
        outreach = j['outreach'] == null ? null : OutreachMessages.fromJson(j['outreach']),
        provenance = List<String>.from(j['provenance'] ?? const []),
        limitations = List<String>.from(j['limitations'] ?? const []),
        dataAvailability = Map<String, bool>.from(j['data_availability'] ?? const {}),
        telemetrySummary = Map<String, dynamic>.from(j['telemetry_summary'] ?? const {});

  final String requestId;

  /// provisional_approved | needs_human_review | error
  final String status;
  final bool needsHumanReview;
  final String countyFips;
  final String countyName;
  final DraftPlan? finalPlan;
  final AuditReport? auditReport;
  final List<DraftPlan> revisionHistory;
  final EvidenceReport? evidenceReport;
  final OutreachMessages? outreach;
  final List<String> provenance;
  final List<String> limitations;
  final Map<String, bool> dataAvailability;
  final Map<String, dynamic> telemetrySummary;

  bool get isRecorded => telemetrySummary['source'] == 'recorded_fixture';

  /// The auditor rejected the first draft when the planner had to revise.
  bool get hadRevision => revisionHistory.length > 1;
}

// ── plan_models ────────────────────────────────────────────────────────────

class ScoreBreakdown {
  ScoreBreakdown.fromJson(Map<String, dynamic> j)
      : uninsured = _d(j['uninsured_norm']),
        safetyNetDistance = _d(j['safety_net_distance_norm']),
        noVehicle = _d(j['no_vehicle_norm']),
        chronicRespiratory = _d(j['chronic_respiratory_norm']),
        checkupGap = _d(j['checkup_preventive_gap_norm']),
        transitBonus = _d(j['saturday_transit_access_bonus']),
        overlapPenalty = _d(j['overlap_penalty']),
        composite = _d(j['composite_need_score']);

  final double uninsured;
  final double safetyNetDistance;
  final double noVehicle;
  final double chronicRespiratory;
  final double checkupGap;
  final double transitBonus;
  final double overlapPenalty;
  final double composite;

  /// Components shown as bars, with whether the input is measured (true) or
  /// includes CDC PLACES model estimates (false). No-vehicle mixes ACS with
  /// PLACES mobility and transport, so it counts as modeled.
  List<(String, double, bool)> get components => [
        ('Uninsured 18–64', uninsured, false),
        ('Safety-net distance', safetyNetDistance, true),
        ('No vehicle / mobility', noVehicle, false),
        ('Chronic & respiratory', chronicRespiratory, false),
        ('No routine checkup', checkupGap, false),
      ];
}

class ProposedClinicStop {
  ProposedClinicStop.fromJson(Map<String, dynamic> j)
      : rank = j['stop_rank'],
        saturday = DateTime.parse(j['assigned_saturday']),
        tractGeoid = j['primary_tract_geoid'],
        coveredTractGeoids = List<String>.from(j['covered_tract_geoids'] ?? const []),
        venueName = j['candidate_venue_name'],
        point = LatLng(_d(j['latitude']), _d(j['longitude'])),
        catchmentKm = _d(j['catchment_radius_km']),
        catchmentPop = j['estimated_population_in_catchment'] ?? 0,
        score = ScoreBreakdown.fromJson(j['score_breakdown']),
        rationale = j['plain_language_rationale'],
        citations = List<String>.from(j['evidence_citations'] ?? const []),
        grainDisclosures = List<String>.from(j['spatial_grain_disclosures'] ?? const []),
        hostVerified = j['host_verified'] ?? false,
        provisionalWarning = j['provisional_warning'] ?? '';

  final int rank;
  final DateTime saturday;
  final String tractGeoid;
  final List<String> coveredTractGeoids;
  final String venueName;
  final LatLng point;
  final double catchmentKm;
  final int catchmentPop;
  final ScoreBreakdown score;
  final String rationale;
  final List<String> citations;
  final List<String> grainDisclosures;
  final bool hostVerified;
  final String provisionalWarning;
}

class RunnerUpTract {
  RunnerUpTract.fromJson(Map<String, dynamic> j)
      : tractGeoid = j['tract_geoid'],
        needRank = j['need_rank'],
        compositeNeedScore = _d(j['composite_need_score']),
        reasonCode = j['deferral_reason_code'],
        coveredByStopRank = j['covered_by_stop_rank'],
        distanceKm = _d(j['distance_to_nearest_selected_stop_km']),
        rationale = j['technical_deferral_rationale'];

  final String tractGeoid;
  final int needRank;
  final double compositeNeedScore;
  final String reasonCode;
  final int? coveredByStopRank;
  final double distanceKm;
  final String rationale;

  String get reasonLabel => switch (reasonCode) {
        'catchment_already_covered' => 'Already inside a stop\'s catchment',
        'inter_stop_separation_constraint' => 'Too close to another stop',
        'no_saturday_transit_or_venue' => 'No Saturday transit or venue',
        _ => 'Less need reached than the chosen stops',
      };
}

class SensitivitySummary {
  SensitivitySummary.fromJson(Map<String, dynamic> j)
      : perturbationPct = _d(j['weight_perturbation_pct']),
        jaccard = _d(j['top_4_stability_jaccard']),
        borderlineTracts = List<String>.from(j['borderline_tracts'] ?? const []),
        notes = j['notes'] ?? '';

  final double perturbationPct;
  final double jaccard;
  final List<String> borderlineTracts;
  final String notes;
}

class DraftPlan {
  DraftPlan.fromJson(Map<String, dynamic> j)
      : countyFips = j['county_fips'],
        strategy = Strategy.parse(j['strategy_used']),
        status = j['status'],
        revision = j['revision_number'] ?? 0,
        stops = _list(j['stops'], ProposedClinicStop.fromJson),
        runnerUps = _list(j['runner_up_tracts'], RunnerUpTract.fromJson),
        sensitivity = j['sensitivity'] == null ? null : SensitivitySummary.fromJson(j['sensitivity']),
        plannerNotes = List<String>.from(j['planner_notes'] ?? const []);

  final String countyFips;
  final Strategy strategy;
  final String status;
  final int revision;
  final List<ProposedClinicStop> stops;
  final List<RunnerUpTract> runnerUps;
  final SensitivitySummary? sensitivity;
  final List<String> plannerNotes;
}

// ── audit_models ───────────────────────────────────────────────────────────

class NonDemographicDefect {
  NonDemographicDefect.fromJson(Map<String, dynamic> j)
      : id = j['defect_id'],
        category = j['category'],
        affectedStopRanks = List<int>.from(j['affected_stop_ranks'] ?? const []),
        description = j['description'],
        remediation = j['remediation_instruction'];

  final String id;
  final String category;
  final List<int> affectedStopRanks;
  final String description;
  final String remediation;
}

class GroupComparison {
  GroupComparison(this.group, Map<String, dynamic> j)
      : countyPct = _d(j['county_pct']),
        catchmentPct = _d(j['catchment_pct']),
        parityRatio = _d(j['parity_ratio']);

  final String group;
  final double countyPct;
  final double catchmentPct;
  final double parityRatio;
}

class DemographicImpact {
  DemographicImpact.fromJson(Map<String, dynamic> j)
      : countyPop = j['county_total_pop'] ?? 0,
        catchmentPop = j['catchment_total_pop'] ?? 0,
        countyTheme3 = _d(j['county_svi_theme3_mean']),
        catchmentTheme3 = _d(j['catchment_svi_theme3_mean']),
        groups = [
          for (final e in ((j['group_comparisons'] as Map?) ?? const {}).entries)
            GroupComparison(e.key as String, e.value as Map<String, dynamic>)
        ],
        findings = List<String>.from(j['disparity_findings'] ?? const []),
        requiresHumanReview = j['requires_human_equity_review'] ?? false;

  final int countyPop;
  final int catchmentPop;
  final double countyTheme3;
  final double catchmentTheme3;
  final List<GroupComparison> groups;
  final List<String> findings;
  final bool requiresHumanReview;
}

class AuditReport {
  AuditReport.fromJson(Map<String, dynamic> j)
      : revisionAudited = j['revision_audited'] ?? 0,
        verdict = j['verdict'],
        defects = _list(j['non_demographic_defects'], NonDemographicDefect.fromJson),
        demographicImpact = DemographicImpact.fromJson(j['demographic_impact']),
        summary = j['auditor_summary'] ?? '',
        limitations = List<String>.from(j['limitations_attached'] ?? const []);

  final int revisionAudited;

  /// approved | rejected_revision_required | needs_human_review
  final String verdict;
  final List<NonDemographicDefect> defects;
  final DemographicImpact demographicImpact;
  final String summary;
  final List<String> limitations;
}

// ── evidence_models ────────────────────────────────────────────────────────

class ValidationCheck {
  ValidationCheck.fromJson(Map<String, dynamic> j)
      : name = j['check_name'],
        verdict = j['verdict'],
        detail = j['detail'],
        isPipelineCheck = j['is_pipeline_check'] ?? true;

  final String name;

  /// PASS | WARN | FAIL
  final String verdict;
  final String detail;
  final bool isPipelineCheck;
}

class EvidenceReport {
  EvidenceReport.fromJson(Map<String, dynamic> j)
      : coreTablesReady = j['core_tables_ready'] ?? false,
        blockingFailures = List<String>.from(j['blocking_failures'] ?? const []),
        checks = _list(j['checks'], ValidationCheck.fromJson),
        validatedTractCount = j['validated_tract_count'] ?? 0,
        prohibitedClaimsBlocked = List<String>.from(j['prohibited_claims_blocked'] ?? const []),
        optionalDatasetsStatus = Map<String, String>.from(j['optional_datasets_status'] ?? const {}),
        caveats = List<String>.from(j['caveats'] ?? const []);

  final bool coreTablesReady;
  final List<String> blockingFailures;
  final List<ValidationCheck> checks;
  final int validatedTractCount;
  final List<String> prohibitedClaimsBlocked;
  final Map<String, String> optionalDatasetsStatus;
  final List<String> caveats;
}

// ── outreach_models ────────────────────────────────────────────────────────

class StopNotice {
  StopNotice.fromJson(Map<String, dynamic> j)
      : stopRank = j['stop_rank'],
        saturday = DateTime.parse(j['assigned_saturday']),
        english = j['english_notice'],
        spanish = j['spanish_notice'],
        whyChosen = j['why_chosen_explanation'] ?? '';

  final int stopRank;
  final DateTime saturday;
  final String english;
  final String spanish;
  final String whyChosen;
}

class UnpickedExplanation {
  UnpickedExplanation.fromJson(Map<String, dynamic> j)
      : tractGeoid = j['tract_geoid'],
        needRank = j['need_rank'],
        nearestStopRank = j['nearest_selected_stop_rank'],
        distanceKm = _d(j['distance_to_selected_stop_km']),
        english = j['english_explanation'],
        spanish = j['spanish_explanation'];

  final String tractGeoid;
  final int needRank;
  final int? nearestStopRank;
  final double distanceKm;
  final String english;
  final String spanish;
}

class OutreachMessages {
  OutreachMessages.fromJson(Map<String, dynamic> j)
      : banner = j['provisional_banner'] ?? '',
        stopNotices = _list(j['stop_notices'], StopNotice.fromJson),
        unpicked = _list(j['unpicked_neighborhood_explanations'], UnpickedExplanation.fromJson),
        surveillanceNoteEn = j['regional_surveillance_note_en'] ?? '',
        surveillanceNoteEs = j['regional_surveillance_note_es'] ?? '';

  final String banner;
  final List<StopNotice> stopNotices;
  final List<UnpickedExplanation> unpicked;
  final String surveillanceNoteEn;
  final String surveillanceNoteEs;
}

// ── tract layer (GET /v1/tracts/{county_fips}) and care sites ──────────────

class Tract {
  Tract({required this.geoId, required this.label, required this.rings, required this.need});

  final String geoId;
  final String label;
  final List<List<LatLng>> rings;

  /// Composite need per strategy wire name; null for unpopulated tracts.
  final Map<String, double>? need;
}

class CareSite {
  CareSite.fromJson(Map<String, dynamic> j)
      : name = j['name'],
        kind = j['kind'],
        point = LatLng(_d(j['lat']), _d(j['lng'])),
        hours = (j['hours'] as num?)?.toDouble();

  final String name;

  /// FQHC | Health Center site | Hospital
  final String kind;
  final LatLng point;
  final double? hours;

  bool get safetyNet => kind != 'Hospital';
}

/// "13121011634" → "Tract 116.34"
String tractLabel(String geoId) {
  final code = geoId.substring(5);
  final whole = int.parse(code.substring(0, 4));
  final suffix = code.substring(4);
  return suffix == '00' ? 'Tract $whole' : 'Tract $whole.$suffix';
}

// ── interaction_models: run events, Ask, human review ──────────────────────

/// One step of an agent run. Streamed live by `POST /v1/plan/stream`; draft
/// writes carry the draft so the map can show it before the run finishes.
class AgentEvent {
  AgentEvent.fromJson(Map<String, dynamic> j)
      : tMs = j['t_ms'],
        agent = j['agent'],
        kind = j['kind'],
        message = j['message'],
        parallel = j['parallel'] ?? false,
        stateKey = j['state_key'],
        draftIndex = j['draft_index'],
        verdict = j['verdict'],
        conflictRanks = j['conflict_ranks'] == null ? null : List<int>.from(j['conflict_ranks']),
        draft = j['draft'] == null ? null : DraftPlan.fromJson(j['draft']);

  final int tMs;
  final String agent;

  /// start | skip | tool | finding | state_write | verdict | done
  final String kind;
  final String message;
  final bool parallel;
  final String? stateKey;
  final int? draftIndex;

  /// reject | approved | needs_human_review
  final String? verdict;
  final List<int>? conflictRanks;
  final DraftPlan? draft;
}

class AskRequest {
  const AskRequest({required this.question, required this.plan, this.planRequestId});
  final String question;
  final PlanRequest plan;
  final String? planRequestId;

  Map<String, dynamic> toJson() => {
        'question': question,
        'plan': plan.toJson(),
        if (planRequestId != null) 'plan_request_id': planRequestId,
      };
}

class AskResponse {
  AskResponse.fromJson(Map<String, dynamic> j)
      : requestId = j['request_id'],
        answer = j['answer'],
        answeredBy = j['answered_by'],
        grain = j['grain'],
        refused = j['refused'] ?? false,
        citations = List<String>.from(j['citations'] ?? const []),
        followUps = List<String>.from(j['follow_ups'] ?? const []);

  final String requestId;
  final String answer;
  final String answeredBy;

  /// The SpatialGrain the answer rests on; null when nothing was claimed.
  final String? grain;
  final bool refused;
  final List<String> citations;
  final List<String> followUps;
}

/// approve_plan | request_changes | confirm_venue | reject_stop | reopen
class ReviewAction {
  const ReviewAction(this.action, {this.stopRank, this.venueName, this.note, this.reviewerRole = 'outreach_lead'});

  ReviewAction.fromJson(Map<String, dynamic> j)
      : action = j['action'],
        stopRank = j['stop_rank'],
        venueName = j['venue_name'],
        note = j['note'],
        reviewerRole = j['reviewer_role'] ?? 'outreach_lead';

  final String action;
  final int? stopRank;
  final String? venueName;
  final String? note;

  /// A role, never a person's name.
  final String reviewerRole;

  Map<String, dynamic> toJson() => {
        'action': action,
        if (stopRank != null) 'stop_rank': stopRank,
        if (venueName != null) 'venue_name': venueName,
        if (note != null) 'note': note,
        'reviewer_role': reviewerRole,
      };
}

class StopReview {
  StopReview({required this.stopRank, this.venueConfirmed = false, this.venueName, this.rejected = false});

  StopReview.fromJson(Map<String, dynamic> j)
      : stopRank = j['stop_rank'],
        venueConfirmed = j['venue_confirmed'] ?? false,
        venueName = j['venue_name'],
        rejected = j['rejected'] ?? false;

  final int stopRank;
  final bool venueConfirmed;
  final String? venueName;
  final bool rejected;
}

class ReviewState {
  ReviewState.fromJson(Map<String, dynamic> j)
      : planRequestId = j['plan_request_id'],
        status = j['status'],
        stops = _list(j['stops'], StopReview.fromJson),
        log = [
          for (final e in (j['log'] as List?) ?? const [])
            (DateTime.parse(e['at']), ReviewAction.fromJson(e['action']))
        ],
        readyToAnnounce = j['ready_to_announce'] ?? false;

  final String planRequestId;

  /// pending | approved | changes_requested
  final String status;
  final List<StopReview> stops;
  final List<(DateTime, ReviewAction)> log;
  final bool readyToAnnounce;

  StopReview stop(int rank) => stops.firstWhere((s) => s.stopRank == rank);
}
