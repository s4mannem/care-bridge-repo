import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:saturday_planner/widgets/help_page.dart';

void main() {
  for (final width in [390.0, 1280.0]) {
    testWidgets('help page lays out at ${width.round()} px', (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const MaterialApp(home: HelpPage()));

      final list = find.byType(Scrollable).first;
      for (final title in [
        'What CareBridge is for',
        'Reading the map',
        'The Agents panel',
        'Ask',
        'CANNOT SAY',
        'Scale and source badges',
        'What the data can\'t tell you',
      ]) {
        await tester.scrollUntilVisible(find.text(title), 300, scrollable: list);
      }
      expect(tester.takeException(), isNull);
    });
  }
}
