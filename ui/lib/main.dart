import 'package:flutter/material.dart';

import 'plan_source.dart';
import 'planner_screen.dart';
import 'widgets/common.dart';

void main() => runApp(const CareBridgeApp());

class CareBridgeApp extends StatelessWidget {
  const CareBridgeApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'CareBridge · Saturday Planner',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Palette.accent),
          scaffoldBackgroundColor: Colors.white,
          useMaterial3: true,
        ),
        home: PlannerScreen(source: _source()),
      );
}

/// Recorded fixtures unless built with `--dart-define=CAREBRIDGE_API=<gateway url>`.
/// `same-origin` calls the host serving the app, which proxies /v1/ (see nginx/).
PlanSource _source() {
  const api = String.fromEnvironment('CAREBRIDGE_API');
  if (api.isEmpty) return RecordedPlanSource();
  return HttpPlanSource(api == 'same-origin' ? Uri.base.origin : api);
}
