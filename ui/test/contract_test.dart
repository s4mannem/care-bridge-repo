import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:saturday_planner/models.dart';
import 'package:saturday_planner/replay.dart';

PlanResponse _fixture(Strategy s, bool defect) => PlanResponse.fromJson(jsonDecode(
    File('assets/mock/plan_${s.wire}_${defect ? 'defect' : 'standard'}.json').readAsStringSync()));

void main() {
  test('PlanRequest serializes with plan 00 field names', () {
    final j = const PlanRequest(strategy: Strategy.chronic, simulateFirstDraftDefect: true).toJson();
    expect(j.keys, containsAll(['county_fips', 'county_name', 'state_abbr', 'saturdays', 'strategy',
        'include_optional_datasets', 'simulate_first_draft_defect']));
    expect(j['strategy'], 'chronic_respiratory_focus');
    expect(j['saturdays'], hasLength(4));
  });

  for (final s in Strategy.values) {
    for (final defect in [false, true]) {
      test('fixture ${s.wire} defect=$defect parses and replays', () {
        final r = _fixture(s, defect);
        final plan = r.finalPlan!;
        expect(plan.stops, hasLength(4));
        expect(plan.stops.every((x) => x.catchmentKm == 4.0 && !x.hostVerified), isTrue);
        expect(overlapPair(plan), isNull, reason: 'final plan keeps stops 5 km apart');
        expect(r.revisionHistory, hasLength(defect ? 2 : 1));
        expect(r.needsHumanReview, isTrue, reason: 'no host is verified');

        final trace = buildTrace(r, PlanRequest(strategy: s, simulateFirstDraftDefect: defect));
        expect(trace.any((e) => e.verdict == 'reject'), defect);
        if (defect) expect(overlapPair(r.revisionHistory.first), isNotNull);
        expect(trace.last.kind, 'done');
      });
    }
  }

  test('replay shows the rejected draft until the revision is written', () async {
    final r = _fixture(Strategy.balanced, true);
    final replay = ReplayController()..load(buildTrace(r, const PlanRequest(simulateFirstDraftDefect: true)));
    final rejectAt = replay.events.indexWhere((e) => e.verdict == 'reject');
    replay.shown.addAll(replay.events.take(rejectAt + 1));
    expect(replay.draftIndex, 0);
    expect(replay.rejectedOnScreen, isTrue);
    expect(replay.conflictRanks, hasLength(2));
    replay.skipToEnd();
    expect(replay.draftIndex, 1);
    expect(replay.rejectedOnScreen, isFalse);
    expect(replay.outreachReady, isTrue);
  });

  test('UI never imports backend libraries', () {
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      final src = f.readAsStringSync();
      expect(src.contains('bigquery') && src.contains('import'), isFalse, reason: f.path);
      expect(src.contains('google_adk') || src.contains('google.adk'), isFalse, reason: f.path);
    }
  });
}
