import 'models.dart';

/// What the Ask chat understood from a planning message, as a `PlanRequest`
/// ready for the outreach lead to confirm. Keyword matching only: the text
/// never reaches a model, and only the request's closed fields can change.
class PlanIntent {
  const PlanIntent({required this.request, required this.understood, required this.notes});

  final PlanRequest request;

  /// One line per setting the message changed, e.g. "Strategy: No car".
  final List<String> understood;

  /// What the message asked for that the planner can't do (another county, other dates).
  final List<String> notes;
}

const planSuggestions = [
  'Plan four stops for households without a car',
  'Plan for asthma, COPD and diabetes',
  'Balanced plan, and show the auditor catching an overlap',
  'Plan a clean run without the demo defect',
];

final _planVerb = RegExp(r'^\s*(please\s+)?(re-?plan|plan|generate|run|start|make|create|redo|pick|choose|schedule)\b',
    caseSensitive: false);

/// True when a message after a plan exists should start a new plan rather than
/// go to `POST /v1/ask` as a question.
bool looksLikePlanCommand(String text) => _planVerb.hasMatch(text);

bool _any(String text, List<String> patterns) => patterns.any((p) => RegExp(p, caseSensitive: false).hasMatch(text));

PlanIntent parsePlanIntent(String text, PlanRequest current) {
  var r = current;
  final understood = <String>[];
  final notes = <String>[];

  Strategy? strategy;
  if (_any(text, [r'\bno[- ]?car', r'without (a )?car', r'\bvehicle', r'\btransit\b', r'\bbus(es)?\b', r'\bmobility\b',
      r'\btransport'])) {
    strategy = Strategy.zeroVehicle;
  } else if (_any(text, [r'\bchronic', r'\brespirator', r'\basthma', r'\bcopd\b', r'\bdiabet', r'blood pressure',
      r'\bhypertension'])) {
    strategy = Strategy.chronic;
  } else if (_any(text, [r'\bbalanced\b', r'\buninsured', r'\binsurance', r'safety[- ]net'])) {
    strategy = Strategy.balanced;
  }
  if (strategy != null) {
    r = r.copyWith(strategy: strategy);
    understood.add('Strategy: ${strategy.label}');
  }

  if (_any(text, [r'\bclean\b', r'\bno (demo )?defect', r'without (the )?(demo )?defect', r'\bnormal run'])) {
    r = r.copyWith(simulateFirstDraftDefect: false);
    understood.add('Demo defect: off');
  } else if (_any(text, [r'\bdefect', r'\boverlap', r'auditor (catch|reject)'])) {
    r = r.copyWith(simulateFirstDraftDefect: true);
    understood.add('Demo defect: on (the auditor rejects draft 0)');
  }

  if (_any(text, [r'without (the )?optional', r'core (data|tables) only', r'no optional'])) {
    r = r.copyWith(includeOptionalDatasets: false);
    understood.add('Optional datasets: off');
  } else if (_any(text, [r'\bfood\b', r'\blibrar', r'\bvenue', r'with (the )?optional', r'\bmarta\b'])) {
    r = r.copyWith(includeOptionalDatasets: true);
    understood.add('Optional datasets: on');
  }

  final otherCounty = RegExp(r'\b(dekalb|cobb|clayton|gwinnett|cherokee|forsyth|henry)\b', caseSensitive: false)
      .firstMatch(text);
  final fips = RegExp(r'\b\d{5}\b').allMatches(text).map((m) => m.group(0)!).where((f) => f != current.countyFips);
  if (otherCounty != null || fips.isNotEmpty) {
    notes.add('Only ${current.countyName} County (${current.countyFips}) is loaded, so the plan is for '
        '${current.countyName}.');
  }
  if (_any(text, [r'\b(january|february|march|april|may|june|july|august|september|october|december)\b',
      r'\bsunday', r'\bweekday', r'\b(five|six|three|two) (stops|saturdays)'])) {
    notes.add('The planner always picks four stops on the four Saturdays shown in the form.');
  }

  return PlanIntent(request: r, understood: understood, notes: notes);
}
