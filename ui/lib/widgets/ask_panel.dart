import 'package:flutter/material.dart';

import '../models.dart';
import '../plan_intent.dart';
import '../plan_source.dart';
import 'common.dart';

const suggestedQuestions = [
  'Which neighborhoods need the van most?',
  'Why didn\'t we pick the tract with the highest need?',
  'Is respiratory illness rising in this neighborhood?',
  'Who does this plan reach?',
  'How far is each stop from a clinic that takes the uninsured?',
];

sealed class _Turn {}

/// A question for `POST /v1/ask` and its answer or error.
class _Question extends _Turn {
  _Question(this.text);
  final String text;
  AskResponse? answer;
  String? error;
}

/// A planning message and the request it became, waiting for the lead to confirm.
class _Proposal extends _Turn {
  _Proposal(this.text, this.intent);
  final String text;
  final PlanIntent intent;
  bool started = false;
}

class _Note extends _Turn {
  _Note(this.text);
  final String text;
}

/// The chat beside the plan. Before a plan exists it plans: the lead describes
/// what they want, the panel shows the request it understood, and nothing runs
/// until they press Generate plan. Once a plan is on screen it answers
/// follow-up questions (`POST /v1/ask`); answers say which agent answered and
/// which grain they rest on, and refusals are marked. A message that starts
/// with "plan", "re-plan" and the like proposes a new plan instead.
class AskPanel extends StatefulWidget {
  const AskPanel({
    super.key,
    required this.source,
    required this.plan,
    required this.request,
    required this.formRequest,
    required this.planning,
    required this.onPlan,
  });
  final PlanSource source;
  final PlanResponse? plan;

  /// The request behind [plan], sent with each question.
  final PlanRequest request;

  /// The request form's current settings, the starting point for a proposal.
  final PlanRequest formRequest;
  final bool planning;
  final ValueChanged<PlanRequest> onPlan;

  @override
  State<AskPanel> createState() => _AskPanelState();
}

class _AskPanelState extends State<AskPanel> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _turns = <_Turn>[];
  bool _busy = false;

  @override
  void didUpdateWidget(AskPanel old) {
    super.didUpdateWidget(old);
    final plan = widget.plan;
    if (plan != null && old.plan?.requestId != plan.requestId && _turns.isNotEmpty) {
      final stops = plan.finalPlan?.stops.length ?? 0;
      final status = plan.needsHumanReview
          ? 'It needs your review in tab 1 before anything is announced.'
          : 'The auditor approved it; venues are still unconfirmed.';
      _turns.add(_Note('Plan ready: $stops stops. $status Ask about it, or say "re-plan for …" to change it.'));
      _scrollToEnd();
    }
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });

  void _send(String text) {
    text = text.trim();
    if (text.length < 2 || _busy || widget.planning) return;
    _input.clear();
    if (widget.plan == null || looksLikePlanCommand(text)) {
      setState(() => _turns.add(_Proposal(text, parsePlanIntent(text, widget.formRequest))));
      _scrollToEnd();
    } else {
      _ask(text);
    }
  }

  void _start(_Proposal p) {
    if (widget.planning) return;
    setState(() {
      p.started = true;
      _turns.add(_Note('Planning now. Follow the agents in the Run tab; the request form shows the same settings.'));
    });
    widget.onPlan(p.intent.request);
    _scrollToEnd();
  }

  Future<void> _ask(String q) async {
    final turn = _Question(q);
    setState(() {
      _busy = true;
      _turns.add(turn);
    });
    try {
      final a = await widget.source.ask(
          AskRequest(question: q, plan: widget.request, planRequestId: widget.plan!.requestId));
      setState(() => turn.answer = a);
    } on PlanSourceException catch (e) {
      setState(() => turn.error = e.message);
    } catch (e) {
      setState(() => turn.error = '$e');
    } finally {
      setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  @override
  Widget build(BuildContext context) {
    final planMode = widget.plan == null;
    final lastAnswer = _turns.whereType<_Question>().lastOrNull?.answer;
    final chips = planMode
        ? planSuggestions
        : (lastAnswer?.followUps.isNotEmpty == true ? lastAnswer!.followUps : suggestedQuestions);
    final locked = _busy || widget.planning;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: ListView(controller: _scroll, padding: const EdgeInsets.all(12), children: [
          if (_turns.isEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                  planMode
                      ? 'Tell me what to plan, for example "focus on households without a car". I\'ll fill in the '
                          'request and nothing runs until you press Generate plan.'
                      : 'Ask about this plan. Answers say which data they rest on, and the agents refuse claims '
                          'the data can\'t support. To change the plan, start with "re-plan".',
                  style: const TextStyle(fontSize: 12.5, color: Palette.muted, height: 1.4)),
            ),
          for (final t in _turns) ...switch (t) {
            _Question(:final text, :final answer, :final error) => [
                _Bubble(text),
                if (answer != null) _Answer(answer),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12, right: 40),
                    child: Text(error, style: const TextStyle(fontSize: 12.5, color: Palette.warn)),
                  ),
                if (answer == null && error == null) const _Spinner(),
              ],
            _Proposal() => [
                _Bubble(t.text),
                _ProposalCard(t, onStart: t.started || widget.planning ? null : () => _start(t)),
              ],
            _Note(:final text) => [
                Padding(
                  padding: const EdgeInsets.only(bottom: 12, right: 24),
                  child: Text(text, style: const TextStyle(fontSize: 12.5, color: Palette.muted, height: 1.4)),
                ),
              ],
          },
          if (widget.planning) const _Spinner(),
        ]),
      ),
      const Divider(height: 1),
      SizedBox(
        height: 44,
        child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
          for (final s in chips)
            Padding(
              padding: const EdgeInsets.only(right: 6, top: 6, bottom: 6),
              child: ActionChip(
                label: Text(s, style: const TextStyle(fontSize: 12)),
                visualDensity: VisualDensity.compact,
                onPressed: locked ? null : () => _send(s),
              ),
            ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 0, 8, 12),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _input,
              enabled: !locked,
              maxLength: 500,
              textInputAction: TextInputAction.send,
              onSubmitted: _send,
              decoration: InputDecoration(
                isDense: true,
                counterText: '',
                hintText: widget.planning
                    ? 'Planning…'
                    : planMode
                        ? 'Describe the plan you want…'
                        : widget.source.recorded
                            ? 'Suggested questions work offline'
                            : 'Ask about this plan…',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          IconButton(
            tooltip: planMode ? 'Send' : 'Ask',
            onPressed: locked ? null : () => _send(_input.text),
            icon: const Icon(Icons.send),
          ),
        ]),
      ),
    ]);
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 6, left: 40),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(color: const Color(0xFFE3F2FD), borderRadius: BorderRadius.circular(12)),
          child: Text(text, style: const TextStyle(fontSize: 13.5)),
        ),
      );
}

class _Spinner extends StatelessWidget {
  const _Spinner();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.only(bottom: 12),
        child: Align(
          alignment: Alignment.centerLeft,
          child: SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      );
}

/// The request a planning message became, with a button that runs it.
class _ProposalCard extends StatelessWidget {
  const _ProposalCard(this.p, {required this.onStart});
  final _Proposal p;
  final VoidCallback? onStart;

  @override
  Widget build(BuildContext context) {
    final r = p.intent.request;
    final info = agentInfo('coordinator');
    Widget row(String k, String v) => Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '$k  ', style: const TextStyle(color: Palette.muted)),
            TextSpan(text: v),
          ]), style: const TextStyle(fontSize: 12.5)),
        );
    return Container(
      margin: const EdgeInsets.only(bottom: 12, right: 24),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Palette.surface,
        border: Border.all(color: Palette.line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(info.icon, size: 14, color: info.color),
          const SizedBox(width: 6),
          Text(info.name, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: info.color)),
        ]),
        const SizedBox(height: 6),
        Text(
            p.intent.understood.isEmpty
                ? 'I didn\'t catch a change, so this uses the form\'s settings:'
                : 'I picked up ${p.intent.understood.join('; ')}. The request:',
            style: const TextStyle(fontSize: 13.5, height: 1.45)),
        const SizedBox(height: 6),
        row('County', '${r.countyName}, ${r.stateAbbr} (${r.countyFips})'),
        row('Saturdays', r.saturdays.map((s) => saturdayLabel(DateTime.parse(s))).join(', ')),
        row('Strategy', '${r.strategy.label}: ${r.strategy.description}'),
        row('Demo defect', r.simulateFirstDraftDefect ? 'on, so the auditor rejects draft 0' : 'off'),
        row('Optional datasets', r.includeOptionalDatasets ? 'on' : 'off'),
        for (final n in p.intent.notes)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(n, style: const TextStyle(fontSize: 12.5, color: Palette.warn)),
          ),
        const SizedBox(height: 8),
        FilledButton.icon(
          onPressed: onStart,
          icon: const Icon(Icons.play_arrow, size: 18),
          label: Text(p.started ? 'Plan started' : 'Generate plan'),
        ),
      ]),
    );
  }
}

class _Answer extends StatelessWidget {
  const _Answer(this.a);
  final AskResponse a;

  @override
  Widget build(BuildContext context) {
    final info = agentInfo(a.answeredBy);
    return Container(
      margin: const EdgeInsets.only(bottom: 12, right: 24),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: a.refused ? Palette.warn.withValues(alpha: 0.06) : Palette.surface,
        border: Border.all(color: a.refused ? Palette.warn.withValues(alpha: 0.5) : Palette.line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Icon(info.icon, size: 14, color: info.color),
          Text(info.name, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: info.color)),
          if (a.grain != null) ScaleBadge(a.grain!),
          if (a.refused) const VerdictChip('CANNOT SAY'),
        ]),
        const SizedBox(height: 6),
        Text(a.answer, style: const TextStyle(fontSize: 13.5, height: 1.45)),
        if (a.citations.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(a.citations.join(' · '), style: const TextStyle(fontSize: 11, color: Palette.muted)),
        ],
      ]),
    );
  }
}
