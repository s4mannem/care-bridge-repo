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

/// A message for `POST /v1/ask` and its reply or error. A reply can carry a
/// proposed plan; the card under it runs that plan when the lead confirms.
class _Question extends _Turn {
  _Question(this.text);
  final String text;
  AskResponse? answer;
  String? error;
  bool started = false;

  /// Asked before any plan existed: asked again once the plan it proposed is ready.
  bool answerWhenReady = false;
}

/// A planning message parsed on the device (recorded mode, or the API out of
/// reach) and the request it became, waiting for the lead to confirm.
class _Proposal extends _Turn {
  _Proposal(this.text, this.intent, {this.question});
  final String text;
  final PlanIntent intent;

  /// A question asked before any plan existed, answered once this plan is ready.
  final String? question;
  bool started = false;
}

class _Note extends _Turn {
  _Note(this.text);
  final String text;
}

/// The conversation beside the plan. Against the live API every message goes
/// to `POST /v1/ask` with the recent turns, so follow-ups work, and a reply can
/// propose a plan: the card shows the request and nothing runs until the lead
/// presses Generate plan. Answers say which agent answered and which grain they
/// rest on, and refusals are marked. Offline (recorded) the panel parses
/// planning messages itself (`plan_intent.dart`) and answers from recordings.
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
      final asked = _turns.whereType<_Question>().where((t) => t.started && t.answerWhenReady).lastOrNull;
      final waiting = _turns.whereType<_Proposal>().where((p) => p.started && p.question != null).lastOrNull;
      if (asked != null) {
        asked.answerWhenReady = false;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _ask(asked.text, sendAs: 'The plan is ready now. ${asked.text}');
        });
      } else if (waiting != null) {
        final q = waiting.question!;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted && _turns.whereType<_Question>().every((t) => t.text != q)) _ask(q);
        });
      }
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
    if (!widget.source.recorded) {
      _ask(text);
    } else if (widget.plan == null || looksLikePlanCommand(text)) {
      _propose(text);
    } else {
      _ask(text);
    }
  }

  void _propose(String text) {
    final question = widget.plan == null && looksLikeQuestion(text) ? text : null;
    setState(() => _turns.add(_Proposal(text, parsePlanIntent(text, widget.formRequest), question: question)));
    _scrollToEnd();
  }

  void _start(PlanRequest request, void Function() markStarted) {
    if (widget.planning) return;
    setState(() {
      markStarted();
      _turns.add(_Note('Planning now. Follow the agents in the Run tab; the request form shows the same settings.'));
    });
    widget.onPlan(request);
    _scrollToEnd();
  }

  /// The conversation so far, oldest first, for the API (it keeps the last 12).
  List<ChatTurn> _history() {
    final out = <ChatTurn>[];
    String clip(String t) => t.length <= 2000 ? t : t.substring(0, 2000);
    for (final t in _turns) {
      switch (t) {
        case _Question(:final text, :final answer):
          out.add(ChatTurn('user', clip(text)));
          if (answer != null) out.add(ChatTurn('assistant', clip(answer.answer)));
        case _Proposal(:final text, :final intent):
          out.add(ChatTurn('user', clip(text)));
          out.add(ChatTurn('assistant', 'Proposed a plan: ${intent.request.strategy.label} strategy.'));
        case _Note():
          break;
      }
    }
    return out.length <= 12 ? out : out.sublist(out.length - 12);
  }

  /// Sends [q] (or [sendAs], when the model needs more context than the lead typed).
  Future<void> _ask(String q, {String? sendAs}) async {
    final history = _history();
    final turn = _Question(q);
    setState(() {
      _busy = true;
      _turns.add(turn);
    });
    try {
      final plan = widget.plan;
      final a = await widget.source.ask(AskRequest(
          question: sendAs ?? q,
          plan: plan == null ? widget.formRequest : widget.request,
          planRequestId: plan?.requestId,
          history: history));
      setState(() {
        turn.answer = a;
        turn.answerWhenReady = plan == null && a.proposedPlan != null && looksLikeQuestion(q);
      });
    } on PlanSourceException catch (e) {
      _fallback(turn, e.message);
    } catch (e) {
      _fallback(turn, '$e');
    } finally {
      setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  /// The API couldn't answer: plan on the device if that's what was asked, else show the error.
  void _fallback(_Question turn, String message) {
    if (widget.plan == null || looksLikePlanCommand(turn.text)) {
      setState(() => _turns.remove(turn));
      _propose(turn.text);
    } else {
      setState(() => turn.error = message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final planMode = widget.plan == null;
    final live = !widget.source.recorded;
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
                      ? 'Tell me what you want to plan, for example "focus on households without a car", or ask '
                          'anything. I\'ll set up the request, and nothing runs until you press Generate plan.'
                      : live
                          ? 'Ask about this plan in your own words, follow up, or ask me to change it. Answers say '
                              'which data they rest on, and the agents refuse claims the data can\'t support.'
                          : 'Ask about this plan. Answers say which data they rest on, and the agents refuse claims '
                              'the data can\'t support. To change the plan, start with "re-plan".',
                  style: const TextStyle(fontSize: 12.5, color: Palette.muted, height: 1.4)),
            ),
          for (final t in _turns) ...switch (t) {
            _Question(:final text, :final answer, :final error) => [
                _Bubble(text),
                if (answer != null) _Answer(answer),
                if (answer?.proposedPlan case final proposed?)
                  _ProposalCard(
                    request: proposed,
                    started: t.started,
                    onStart: t.started || widget.planning ? null : () => _start(proposed, () => t.started = true),
                  ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12, right: 40),
                    child: Text(error, style: const TextStyle(fontSize: 12.5, color: Palette.warn)),
                  ),
                if (answer == null && error == null) const _Spinner(),
              ],
            _Proposal() => [
                _Bubble(t.text),
                _ProposalCard(
                  request: t.intent.request,
                  intro: t.question != null
                      ? 'I need a plan to answer that. I\'ll answer as soon as this plan is ready:'
                      : t.intent.understood.isEmpty
                          ? 'I didn\'t catch a change, so this uses the form\'s settings:'
                          : 'I picked up ${t.intent.understood.join('; ')}. The request:',
                  notes: t.intent.notes,
                  started: t.started,
                  onStart: t.started || widget.planning ? null : () => _start(t.intent.request, () => t.started = true),
                ),
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
                        ? (live ? 'Ask anything, or describe the plan you want…' : 'Describe the plan you want…')
                        : live
                            ? 'Ask about this plan, or ask me to change it…'
                            : 'Suggested questions work offline',
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

/// A proposed plan request, with a button that runs it.
class _ProposalCard extends StatelessWidget {
  const _ProposalCard(
      {required this.request, this.intro, this.notes = const [], required this.started, required this.onStart});
  final PlanRequest request;

  /// The line above the settings; the conversation's own reply stands in for it when null.
  final String? intro;
  final List<String> notes;
  final bool started;
  final VoidCallback? onStart;

  @override
  Widget build(BuildContext context) {
    final r = request;
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
        if (intro case final text?) ...[
          const SizedBox(height: 6),
          Text(text, style: const TextStyle(fontSize: 13.5, height: 1.45)),
        ],
        const SizedBox(height: 6),
        row('County', '${r.countyName}, ${r.stateAbbr} (${r.countyFips})'),
        row('Saturdays', r.saturdays.map((s) => saturdayLabel(DateTime.parse(s))).join(', ')),
        row('Strategy', '${r.strategy.label}: ${r.strategy.description}'),
        row('Overlap demo', r.simulateFirstDraftDefect ? 'on, so the auditor rejects draft 0' : 'off'),
        row('Optional datasets', r.includeOptionalDatasets ? 'on' : 'off'),
        for (final n in notes)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(n, style: const TextStyle(fontSize: 12.5, color: Palette.warn)),
          ),
        const SizedBox(height: 8),
        FilledButton.icon(
          onPressed: onStart,
          icon: const Icon(Icons.play_arrow, size: 18),
          label: Text(started ? 'Plan started' : 'Generate plan'),
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
