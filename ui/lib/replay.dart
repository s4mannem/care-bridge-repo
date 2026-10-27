import 'dart:async';

import 'package:flutter/foundation.dart';

import 'geo.dart';
import 'models.dart';

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

/// The agent run on screen: events arrive live from the source, and the same
/// events can be replayed at their recorded pace afterwards. Everything the
/// map, tabs, graph and state drawer show is read from here.
class ReplayController extends ChangeNotifier {
  final List<AgentEvent> events = [];
  final List<AgentEvent> shown = [];
  double speed = 1;
  bool _live = false;
  Timer? _timer;

  /// Events are still arriving from the source (replay and skip wait for the end).
  bool get live => _live;
  bool get idle => shown.isEmpty && !running;
  bool get running => _live || _timer != null;
  bool get done => !running && events.isNotEmpty && shown.length == events.length;

  /// Start a new live run; call [add] per event and [finish] at the end.
  void startLive() {
    _stopTimer();
    events.clear();
    shown.clear();
    _live = true;
    notifyListeners();
  }

  void add(AgentEvent e) {
    events.add(e);
    shown.add(e);
    notifyListeners();
  }

  void finish() {
    _live = false;
    notifyListeners();
  }

  int get _lastDraftAt => shown.lastIndexWhere((e) => e.kind == 'state_write' && e.draftIndex != null);

  /// Drafts written so far, in order (index = revision_history index).
  List<DraftPlan> get drafts => [for (final e in shown) if (e.draft != null) e.draft!];

  /// Index into revision_history of the draft on screen, or null before any.
  int? get draftIndex => _lastDraftAt < 0 ? null : shown[_lastDraftAt].draftIndex;
  DraftPlan? get currentDraft {
    final i = draftIndex;
    final d = drafts;
    return i == null || i >= d.length ? null : d[i];
  }

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

  /// Latest event per agent, for the graph's node states.
  Map<String, AgentEvent> get latestByAgent => {for (final e in shown) e.agent: e};
  String? get activeAgent => running && shown.isNotEmpty ? shown.last.agent : null;

  void setSpeed(double v) {
    speed = v;
    notifyListeners();
  }

  /// Replay the finished run from the start at its recorded pace.
  void play() {
    if (_live || events.isEmpty) return;
    _stopTimer();
    shown.clear();
    notifyListeners();
    _next(0);
  }

  void skipToEnd() {
    if (_live) return;
    _stopTimer();
    shown
      ..clear()
      ..addAll(events);
    notifyListeners();
  }

  void _stopTimer() {
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
    _stopTimer();
    super.dispose();
  }
}
