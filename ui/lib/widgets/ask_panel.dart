import 'package:flutter/material.dart';

import '../models.dart';
import '../plan_source.dart';
import 'common.dart';

const suggestedQuestions = [
  'Which neighborhoods need the van most?',
  'Why didn\'t we pick the tract with the highest need?',
  'Is respiratory illness rising in this neighborhood?',
  'Who does this plan reach?',
  'How far is each stop from a clinic that takes the uninsured?',
];

/// Follow-up questions about the plan on screen (`POST /v1/ask`). Answers say
/// which agent answered and which grain they rest on, and refusals are marked:
/// "I can tell you about the region; I cannot tell you about this street."
class AskPanel extends StatefulWidget {
  const AskPanel({super.key, required this.source, required this.plan, required this.request});
  final PlanSource source;
  final PlanResponse? plan;
  final PlanRequest request;

  @override
  State<AskPanel> createState() => _AskPanelState();
}

class _AskPanelState extends State<AskPanel> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _turns = <(String, AskResponse?, String?)>[]; // question, answer, error
  bool _busy = false;

  @override
  void didUpdateWidget(AskPanel old) {
    super.didUpdateWidget(old);
    // A new plan means a new conversation.
    if (old.plan?.requestId != widget.plan?.requestId) _turns.clear();
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _ask(String q) async {
    q = q.trim();
    if (q.length < 2 || _busy || widget.plan == null) return;
    setState(() {
      _busy = true;
      _turns.add((q, null, null));
      _input.clear();
    });
    final i = _turns.length - 1;
    try {
      final a = await widget.source.ask(
          AskRequest(question: q, plan: widget.request, planRequestId: widget.plan!.requestId));
      setState(() => _turns[i] = (q, a, null));
    } on PlanSourceException catch (e) {
      setState(() => _turns[i] = (q, null, e.message));
    } catch (e) {
      setState(() => _turns[i] = (q, null, '$e'));
    } finally {
      setState(() => _busy = false);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.plan == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Generate a plan, then ask about it here.',
              textAlign: TextAlign.center, style: TextStyle(color: Palette.muted)),
        ),
      );
    }
    final last = _turns.isEmpty ? null : _turns.last.$2;
    final chips = last?.followUps.isNotEmpty == true ? last!.followUps : suggestedQuestions;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: ListView(controller: _scroll, padding: const EdgeInsets.all(12), children: [
          if (_turns.isEmpty)
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text('Ask about this plan. Answers say which data they rest on, and the agents refuse claims '
                  'the data can\'t support.', style: TextStyle(fontSize: 12.5, color: Palette.muted, height: 1.4)),
            ),
          for (final (q, a, err) in _turns) ...[
            Align(
              alignment: Alignment.centerRight,
              child: Container(
                margin: const EdgeInsets.only(bottom: 6, left: 40),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(color: const Color(0xFFE3F2FD), borderRadius: BorderRadius.circular(12)),
                child: Text(q, style: const TextStyle(fontSize: 13.5)),
              ),
            ),
            if (a != null) _Answer(a),
            if (err != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12, right: 40),
                child: Text(err, style: const TextStyle(fontSize: 12.5, color: Palette.warn)),
              ),
            if (a == null && err == null)
              const Padding(
                padding: EdgeInsets.only(bottom: 12),
                child: SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2)),
              ),
          ],
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
                onPressed: _busy ? null : () => _ask(s),
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
              enabled: !_busy,
              maxLength: 500,
              textInputAction: TextInputAction.send,
              onSubmitted: _ask,
              decoration: InputDecoration(
                isDense: true,
                counterText: '',
                hintText: widget.source.recorded ? 'Suggested questions work offline' : 'Ask about this plan…',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Ask',
            onPressed: _busy ? null : () => _ask(_input.text),
            icon: const Icon(Icons.send),
          ),
        ]),
      ),
    ]);
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
