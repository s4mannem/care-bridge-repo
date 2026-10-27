import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:saturday_planner/models.dart';
import 'package:saturday_planner/plan_intent.dart';
import 'package:saturday_planner/plan_source.dart';
import 'package:saturday_planner/widgets/ask_panel.dart';

void main() {
  const form = PlanRequest(simulateFirstDraftDefect: true);

  group('parsePlanIntent', () {
    test('no-car wording picks the No car strategy', () {
      final i = parsePlanIntent('Plan four stops for households without a car', form);
      expect(i.request.strategy, Strategy.zeroVehicle);
      expect(i.understood, contains('Strategy: No car'));
    });

    test('conditions pick Chronic & respiratory', () {
      expect(parsePlanIntent('Plan for asthma, COPD and diabetes', form).request.strategy, Strategy.chronic);
    });

    test('clean run turns the demo defect off; overlap turns it on', () {
      expect(parsePlanIntent('Plan a clean run without the demo defect', form).request.simulateFirstDraftDefect,
          isFalse);
      const off = PlanRequest();
      expect(parsePlanIntent('Balanced plan, and show the auditor catching an overlap', off)
          .request.simulateFirstDraftDefect, isTrue);
    });

    test('unrecognised text keeps the form settings', () {
      final i = parsePlanIntent('Let us get going', form);
      expect(i.understood, isEmpty);
      expect(i.request.strategy, form.strategy);
      expect(i.request.simulateFirstDraftDefect, form.simulateFirstDraftDefect);
    });

    test('another county is noted, never changed', () {
      final i = parsePlanIntent('Plan for DeKalb County', form);
      expect(i.request.countyFips, '13121');
      expect(i.notes.single, contains('Only Fulton'));
    });

    test('plan commands are told apart from questions', () {
      expect(looksLikePlanCommand('Re-plan for households without a car'), isTrue);
      expect(looksLikePlanCommand('plan for asthma'), isTrue);
      expect(looksLikePlanCommand('Who does this plan reach?'), isFalse);
      expect(looksLikePlanCommand('Why didn\'t we pick the highest-need tract?'), isFalse);
    });
  });

  group('free-text questions', () {
    const recorded = [
      'Which neighborhoods need the van most?',
      'Why didn\'t we pick the tract with the highest need?',
      'Is respiratory illness rising in this neighborhood?',
      'Who does this plan reach?',
      'How far is each stop from a clinic that takes the uninsured?',
    ];

    test('route to the closest recorded question by topic', () {
      expect(closestRecordedQuestion('Which neighborhoods have the most people who are sick and not being seen?',
          recorded), recorded[0]);
      expect(closestRecordedQuestion('is the flu going up?', recorded), recorded[2]);
      expect(closestRecordedQuestion('why was tract 120 left out', recorded), recorded[1]);
      expect(closestRecordedQuestion('is this plan fair to Black residents?', recorded), recorded[3]);
      expect(closestRecordedQuestion('how far is the nearest safety-net clinic', recorded), recorded[4]);
      expect(closestRecordedQuestion('tell me a joke', recorded), isNull);
    });

    test('questions are told apart from plan requests', () {
      expect(looksLikeQuestion('Which neighborhoods have the most people who are sick and not being seen?'), isTrue);
      expect(looksLikeQuestion('Plan for asthma'), isFalse);
      expect(looksLikeQuestion('focus on households without a car'), isFalse);
    });

    testWidgets('recorded source answers free text with the closest recorded answer', (tester) async {
      final a = await tester.runAsync(() => RecordedPlanSource().ask(const AskRequest(
          question: 'Which neighborhoods have the most people who are sick and not being seen?', plan: form)));
      expect(a!.answer, startsWith('Closest question I can answer offline: "Which neighborhoods need the van most?"'));
      final refused = await tester.runAsync(
          () => RecordedPlanSource().ask(const AskRequest(question: 'Which patients have diabetes?', plan: form)));
      expect(refused!.refused, isTrue);
    });
  });

  testWidgets('a question before any plan offers the plan first', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AskPanel(
            source: RecordedPlanSource(),
            plan: null,
            request: form,
            formRequest: form,
            planning: false,
            onPlan: (_) {}),
      ),
    ));
    await tester.enterText(find.byType(TextField), 'Which neighborhoods have the most people who are sick?');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();
    expect(find.textContaining('I need a plan to answer that'), findsOneWidget);
    expect(find.text('Generate plan'), findsOneWidget);
  });

  testWidgets('before a plan, a chat message becomes a request the lead confirms', (tester) async {
    PlanRequest? started;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AskPanel(
          source: RecordedPlanSource(),
          plan: null,
          request: form,
          formRequest: form,
          planning: false,
          onPlan: (r) => started = r,
        ),
      ),
    ));

    await tester.enterText(find.byType(TextField), 'Plan for households without a car');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();

    expect(find.textContaining('No car'), findsWidgets);
    expect(started, isNull, reason: 'nothing runs before Generate plan');

    await tester.tap(find.text('Generate plan'));
    await tester.pump();
    expect(started?.strategy, Strategy.zeroVehicle);
    expect(find.text('Plan started'), findsOneWidget);
  });
}
