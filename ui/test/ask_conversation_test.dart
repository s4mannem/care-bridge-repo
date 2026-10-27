import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:saturday_planner/models.dart';
import 'package:saturday_planner/plan_source.dart';
import 'package:saturday_planner/widgets/ask_panel.dart';

/// A live API stand-in: records each AskRequest and answers with the next reply.
class FakeApi implements PlanSource {
  FakeApi(this.replies);
  final List<Map<String, dynamic>> replies;
  final asked = <AskRequest>[];

  @override
  bool get recorded => false;

  @override
  Future<AskResponse> ask(AskRequest request) async {
    asked.add(request);
    if (replies.isEmpty) throw PlanSourceException(503, 'unavailable', 'API down');
    return AskResponse.fromJson({'request_id': 'r${asked.length}', ...replies.removeAt(0)});
  }

  @override
  Stream<RunUpdate> run(PlanRequest request) => const Stream.empty();
  @override
  Future<ReviewState> review(String id) => throw UnimplementedError();
  @override
  Future<ReviewState> act(String id, ReviewAction a) => throw UnimplementedError();
  @override
  Future<List<Tract>> tracts(String fips) async => [];
}

PlanResponse _plan() => PlanResponse.fromJson(
    jsonDecode(File('assets/mock/plan_balanced_uninsured_safety_net_gap_defect.json').readAsStringSync()));

Widget _panel(PlanSource source, {PlanResponse? plan, ValueChanged<PlanRequest>? onPlan}) => MaterialApp(
      home: Scaffold(
        body: AskPanel(
          source: source,
          plan: plan,
          request: const PlanRequest(),
          formRequest: const PlanRequest(simulateFirstDraftDefect: true),
          planning: false,
          onPlan: onPlan ?? (_) {},
        ),
      ),
    );

Future<void> _say(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.testTextInput.receiveAction(TextInputAction.send);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('live: a proposal from the conversation becomes a card that runs on confirm', (tester) async {
    final api = FakeApi([
      {
        'answer': 'Let\'s focus on households without a car. Press Generate plan when you\'re ready.',
        'answered_by': 'coordinator',
        'intent': 'propose_plan',
        'proposed_plan': const PlanRequest(strategy: Strategy.zeroVehicle).toJson(),
      },
    ]);
    PlanRequest? started;
    await tester.pumpWidget(_panel(api, onPlan: (r) => started = r));
    await _say(tester, 'help people with no car get seen');

    expect(api.asked.single.planRequestId, isNull);
    expect(api.asked.single.plan.simulateFirstDraftDefect, isTrue, reason: 'proposals start from the form');
    expect(find.textContaining('Let\'s focus on households without a car'), findsOneWidget);
    expect(find.textContaining('No car: Households without a car'), findsOneWidget, reason: 'the card shows the request');
    await tester.tap(find.text('Generate plan'));
    await tester.pump();
    expect(started?.strategy, Strategy.zeroVehicle);
  });

  testWidgets('live: follow-ups carry the conversation so far', (tester) async {
    final api = FakeApi([
      {'answer': 'Stop 1 has the highest need.', 'answered_by': 'siting_planner'},
      {'answer': 'Stop 2 is 1.6 km from a safety-net clinic.', 'answered_by': 'health_access'},
    ]);
    final plan = _plan();
    await tester.pumpWidget(_panel(api, plan: plan));
    await _say(tester, 'Which stop needs it most?');
    await _say(tester, 'and the second one?');

    final second = api.asked.last;
    expect(second.planRequestId, plan.requestId);
    expect([for (final t in second.history) '${t.role}: ${t.text}'],
        ['user: Which stop needs it most?', 'assistant: Stop 1 has the highest need.']);
  });

  testWidgets('live: a question before any plan is asked again once the plan is ready', (tester) async {
    final api = FakeApi([
      {
        'answer': 'I need a plan on screen to answer that.',
        'answered_by': 'coordinator',
        'intent': 'propose_plan',
        'proposed_plan': const PlanRequest().toJson(),
      },
      {'answer': 'Tract 116.34 has the biggest checkup gap.', 'answered_by': 'health_access'},
    ]);
    await tester.pumpWidget(_panel(api));
    await _say(tester, 'Which neighborhoods have the most people who are sick and not being seen?');
    await tester.tap(find.text('Generate plan'));
    await tester.pump();

    final plan = _plan();
    await tester.pumpWidget(_panel(api, plan: plan));
    await tester.pumpAndSettle();
    expect(api.asked, hasLength(2));
    expect(api.asked.last.planRequestId, plan.requestId);
    expect(api.asked.last.question, startsWith('The plan is ready now.'));
    expect(find.textContaining('biggest checkup gap'), findsOneWidget);
  });

  testWidgets('live: API down before a plan falls back to planning on the device', (tester) async {
    await tester.pumpWidget(_panel(FakeApi([])));
    await _say(tester, 'Plan for asthma and diabetes');
    expect(find.textContaining('Chronic & respiratory'), findsWidgets);
    expect(find.text('Generate plan'), findsOneWidget);
  });
}
