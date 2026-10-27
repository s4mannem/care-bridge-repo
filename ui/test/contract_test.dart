import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:saturday_planner/models.dart';
import 'package:saturday_planner/plan_source.dart';
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

  List<AgentEvent> runEvents(Strategy s, bool defect) => [
        for (final e in (jsonDecode(File('assets/mock/run_${s.wire}_${defect ? 'defect' : 'standard'}.json')
                .readAsStringSync())['events'] as List))
          AgentEvent.fromJson(e)
      ];

  for (final s in Strategy.values) {
    for (final defect in [false, true]) {
      test('fixture ${s.wire} defect=$defect parses and its run matches', () {
        final r = _fixture(s, defect);
        final plan = r.finalPlan!;
        expect(plan.stops, hasLength(4));
        expect(plan.stops.every((x) => x.catchmentKm == 4.0 && !x.hostVerified), isTrue);
        expect(overlapPair(plan), isNull, reason: 'final plan keeps stops 5 km apart');
        expect(r.revisionHistory, hasLength(defect ? 2 : 1));
        expect(r.needsHumanReview, isTrue, reason: 'no host is verified');

        final events = runEvents(s, defect);
        expect(events.any((e) => e.verdict == 'reject'), defect);
        final drafts = [for (final e in events) if (e.draft != null) e.draft!];
        expect(drafts.map((d) => d.stops.map((x) => x.tractGeoid).join()),
            r.revisionHistory.map((d) => d.stops.map((x) => x.tractGeoid).join()));
        if (defect) expect(overlapPair(drafts.first), isNotNull);
        expect(events.last.kind, 'done');
      });
    }
  }

  test('live events show the rejected draft until the revision is written', () {
    final events = runEvents(Strategy.balanced, true);
    final replay = ReplayController()..startLive();
    final rejectAt = events.indexWhere((e) => e.verdict == 'reject');
    events.take(rejectAt + 1).forEach(replay.add);
    expect(replay.draftIndex, 0);
    expect(replay.rejectedOnScreen, isTrue);
    expect(replay.conflictRanks, hasLength(2));
    expect(replay.currentDraft, isNotNull);
    events.skip(rejectAt + 1).forEach(replay.add);
    replay.finish();
    expect(replay.draftIndex, 1);
    expect(replay.drafts, hasLength(2));
    expect(replay.rejectedOnScreen, isFalse);
    expect(replay.outreachReady, isTrue);
    expect(replay.done, isTrue);
  });

  test('recorded review follows the API rules', () async {
    final src = RecordedPlanSource();
    await src.act('p', const ReviewAction('reject_stop', stopRank: 4));
    for (final n in [1, 2, 3]) {
      await src.act('p', ReviewAction('confirm_venue', stopRank: n, venueName: 'Library $n'));
    }
    var s = await src.act('p', const ReviewAction('approve_plan'));
    expect(s.status, 'approved');
    expect(s.readyToAnnounce, isTrue);
    s = await src.act('p', const ReviewAction('reject_stop', stopRank: 1));
    expect(s.status, 'pending');
    expect(s.readyToAnnounce, isFalse);
    expect(() => src.act('p', const ReviewAction('confirm_venue', stopRank: 2)), throwsA(isA<PlanSourceException>()));
  });

  test('AskRequest and ReviewAction serialize with API field names', () {
    final ask = AskRequest(question: 'Who does this plan reach?', plan: const PlanRequest(), planRequestId: 'r1').toJson();
    expect(ask.keys, containsAll(['question', 'plan', 'plan_request_id']));
    final act = const ReviewAction('confirm_venue', stopRank: 2, venueName: 'Library').toJson();
    expect(act, {'action': 'confirm_venue', 'stop_rank': 2, 'venue_name': 'Library', 'reviewer_role': 'outreach_lead'});
  });

  test('UI never imports backend libraries', () {
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      final src = f.readAsStringSync();
      expect(src.contains('bigquery') && src.contains('import'), isFalse, reason: f.path);
      expect(src.contains('google_adk') || src.contains('google.adk'), isFalse, reason: f.path);
    }
  });
}
