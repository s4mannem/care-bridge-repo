import 'dart:async';

import 'package:flutter/foundation.dart';

import 'geo.dart';
import 'models.dart';

/// One step of the agent run, reconstructed from a [PlanResponse].
///
/// `POST /v1/plan` returns a single JSON document, not a stream, so the UI
/// derives the run from what the response records: `revision_history`,
/// `evidence_report`, the final `audit_report` and `outreach`.
class AgentEvent {
  const AgentEvent({
    required this.tMs,
    required this.agent,
    required this.kind,
    required this.message,
    this.parallel = false,
    this.stateKey,
    this.draftIndex,
    this.verdict,
    this.conflictRanks,
  });

  final int tMs;
  final String agent;

  /// start | skip | tool | finding | state_write | verdict | done
  final String kind;
  final String message;
  final bool parallel;
  final String? stateKey;

  /// Index into `revision_history` once that draft has been written.
  final int? draftIndex;

  /// reject | approved | needs_human_review
  final String? verdict;
  final List<int>? conflictRanks;
}

/// Closest pair of stops in a draft that breaks the minimum separation.
(ProposedClinicStop, ProposedClinicStop, double)? overlapPair(DraftPlan d, {double minKm = 5}) {
  (ProposedClinicStop, ProposedClinicStop, double)? best;
  for (var i = 0; i < d.stops.length; i++) {
    for (var j = i + 1; j < d.stops.length; j++) {
      final dist = km(d.stops[i].point, d.stops[j].point);
      if (dist < minKm && (best == null || dist < best.$3)) best = (d.stops[i], d.stops[j], dist);
    }
  }
  return best;
}

List<AgentEvent> buildTrace(PlanResponse r, PlanRequest req) {
  final out = <AgentEvent>[];
  var t = 0;
  void add(int gap, String agent, String kind, String message,
      {bool parallel = false, String? stateKey, int? draftIndex, String? verdict, List<int>? conflictRanks}) {
    t += gap;
    out.add(AgentEvent(
        tMs: t,
        agent: agent,
        kind: kind,
        message: message,
        parallel: parallel,
        stateKey: stateKey,
        draftIndex: draftIndex,
        verdict: verdict,
        conflictRanks: conflictRanks));
  }

  final ev = r.evidenceReport;
  String names(DraftPlan d) => d.stops.map((s) => tractLabel(s.tractGeoid)).join(', ');

  add(0, 'coordinator', 'start',
      'POST /v1/plan · ${r.countyName} · ${req.strategy.label}'
      '${req.simulateFirstDraftDefect ? ' · simulate draft-0 defect' : ''}',
      stateKey: 'plan_request');
  add(400, 'health_access', 'start', 'Querying burden_tracts + tract_access via BigQuery MCP', parallel: true);
  final marta = r.dataAvailability['marta_gtfs_saturday'] ?? false;
  add(0, 'transit_community', marta ? 'start' : 'skip',
      marta ? 'Querying MARTA Saturday service' : 'MARTA GTFS ${ev?.optionalDatasetsStatus['marta_gtfs'] ?? 'unavailable'}',
      parallel: true, stateKey: marta ? null : 'mobility_evidence');
  add(1200, 'health_access', 'state_write', '${ev?.validatedTractCount ?? 0} tracts with burden and two distances',
      parallel: true, stateKey: 'health_evidence');

  add(500, 'evidence_validator', 'start', 'Checking grain, inversion and leakage on every input');
  for (final c in ev?.checks.where((c) => c.verdict != 'PASS') ?? const <ValidationCheck>[]) {
    add(500, 'evidence_validator', 'finding', '${c.verdict} ${c.name}: ${c.detail}');
  }
  final passes = ev?.checks.where((c) => c.verdict == 'PASS').length ?? 0;
  add(400, 'evidence_validator', 'state_write',
      '$passes checks passed · core tables ${ev?.coreTablesReady == true ? 'ready' : 'NOT ready'}',
      stateKey: 'evidence_report');

  for (var i = 0; i < r.revisionHistory.length; i++) {
    final d = r.revisionHistory[i];
    final last = i == r.revisionHistory.length - 1;
    add(600, 'siting_planner', 'start',
        i == 0 ? 'Race-blind planning · ${d.strategy.label} weights' : 'Revising with non_demographic_feedback only');
    add(800, 'optimizer', 'tool', 'optimize_four_clinic_stops(revision=${d.revision})');
    add(500, 'siting_planner', 'state_write', 'Draft ${d.revision}: ${names(d)}',
        stateKey: 'draft_plan', draftIndex: i);
    if (!last) {
      add(700, 'equity_auditor', 'start', 'Auditing draft ${d.revision} (no access to planner reasoning)');
      final pair = overlapPair(d);
      add(1200, 'equity_auditor', 'verdict',
          pair == null
              ? 'REJECT: defects found in draft ${d.revision}'
              : 'REJECT: stops ${pair.$1.rank} and ${pair.$2.rank} are ${pair.$3.toStringAsFixed(1)} km apart, '
                  'so their ${pair.$1.catchmentKm.round()} km catchments overlap.',
          verdict: 'reject',
          draftIndex: i,
          conflictRanks: pair == null ? null : [pair.$1.rank, pair.$2.rank],
          stateKey: 'revision_required');
      add(200, 'equity_auditor', 'state_write', 'CATCHMENT_OVERLAP sent back; no demographic fields',
          stateKey: 'non_demographic_feedback');
    }
  }

  final audit = r.auditReport;
  if (audit != null) {
    add(700, 'equity_auditor', 'start',
        'Auditing draft ${audit.revisionAudited} + post-hoc ACS comparison (auditor only)');
    for (final f in audit.demographicImpact.findings) {
      add(600, 'equity_auditor', 'finding', 'PARITY $f');
    }
    add(600, 'equity_auditor', 'verdict',
        '${audit.verdict == 'approved' ? 'APPROVED' : audit.verdict.toUpperCase().replaceAll('_', ' ')}: '
        '${audit.summary.split('. ').first}.',
        verdict: audit.verdict,
        stateKey: 'audit_report');
  }
  add(200, 'coordinator', 'state_write',
      'final_plan · status=${r.status} · needs_human_review=${r.needsHumanReview}',
      stateKey: 'final_plan');
  if (r.outreach != null) {
    add(600, 'communications', 'start', 'Drafting EN/ES notices from final_plan only');
    add(1400, 'communications', 'state_write',
        '${r.outreach!.stopNotices.length} stop notices · ${r.outreach!.unpicked.length} "why not here" notes',
        stateKey: 'outreach_messages');
  }
  add(300, 'coordinator', 'done', r.needsHumanReview ? 'Plan ready, pending human review' : 'Plan ready');
  return out;
}

/// Plays a trace step by step and exposes what the screen should show now.
class ReplayController extends ChangeNotifier {
  List<AgentEvent> events = const [];
  final List<AgentEvent> shown = [];
  double speed = 1;
  Timer? _timer;

  bool get idle => shown.isEmpty && _timer == null;
  bool get running => _timer != null;
  bool get done => events.isNotEmpty && shown.length == events.length;

  int get _lastDraftAt => shown.lastIndexWhere((e) => e.kind == 'state_write' && e.draftIndex != null);

  /// Index into revision_history of the draft on screen, or null before any.
  int? get draftIndex => _lastDraftAt < 0 ? null : shown[_lastDraftAt].draftIndex;

  /// The draft on screen has been rejected and no revision has replaced it yet.
  bool get rejectedOnScreen => shown.lastIndexWhere((e) => e.verdict == 'reject') > _lastDraftAt;

  List<int> get conflictRanks {
    final i = shown.lastIndexWhere((e) => e.conflictRanks != null);
    return i < 0 ? const [] : shown[i].conflictRanks!;
  }

  bool get rejected => shown.any((e) => e.verdict == 'reject');
  bool get audited => shown.any((e) => e.verdict != null && e.verdict != 'reject');
  bool get finalWritten => shown.any((e) => e.stateKey == 'final_plan');
  bool get outreachReady => shown.any((e) => e.stateKey == 'outreach_messages');
  Set<String> get writtenKeys => {for (final e in shown) if (e.stateKey != null) e.stateKey!};

  void load(List<AgentEvent> trace) {
    stop();
    events = trace;
    shown.clear();
    notifyListeners();
  }

  void setSpeed(double v) {
    speed = v;
    notifyListeners();
  }

  void play() {
    stop();
    shown.clear();
    notifyListeners();
    _next(0);
  }

  void skipToEnd() {
    stop();
    shown
      ..clear()
      ..addAll(events);
    notifyListeners();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  void _next(int i) {
    if (i >= events.length) {
      _timer = null;
      notifyListeners();
      return;
    }
    final gap = i == 0 ? 0 : events[i].tMs - events[i - 1].tMs;
    _timer = Timer(Duration(milliseconds: (gap / speed).round()), () {
      shown.add(events[i]);
      notifyListeners();
      _next(i + 1);
    });
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
