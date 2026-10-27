import 'package:flutter/material.dart';

import '../models.dart';
import '../replay.dart';
import 'common.dart';

/// The PlanRequest form: strategy, optional datasets and the demo toggle
/// that forces a draft-0 defect so the auditor's rejection is on screen.
class RequestPanel extends StatelessWidget {
  const RequestPanel({
    super.key,
    required this.request,
    required this.onChanged,
    required this.onSubmit,
    required this.loading,
    required this.response,
  });

  final PlanRequest request;
  final ValueChanged<PlanRequest> onChanged;
  final VoidCallback onSubmit;
  final bool loading;
  final PlanResponse? response;

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.all(16), children: [
        Text('${request.countyName} County, ${request.stateAbbr}',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
        Text('FIPS ${request.countyFips} · one van · four Saturdays', style: const TextStyle(color: Palette.muted)),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final s in request.saturdays)
            Chip(
              label: Text(saturdayLabel(DateTime.parse(s)), style: const TextStyle(fontSize: 12)),
              visualDensity: VisualDensity.compact,
            ),
        ]),
        const SizedBox(height: 20),
        const SectionTitle('What "needs the van" means'),
        for (final s in Strategy.values)
          RadioListTile<Strategy>(
            value: s,
            groupValue: request.strategy,
            onChanged: loading ? null : (v) => onChanged(request.copyWith(strategy: v)),
            contentPadding: EdgeInsets.zero,
            dense: true,
            title: Text(s.label, style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(s.description, style: const TextStyle(fontSize: 12)),
          ),
        const SizedBox(height: 8),
        const SectionTitle('Options'),
        SwitchListTile(
          value: request.simulateFirstDraftDefect,
          onChanged: loading ? null : (v) => onChanged(request.copyWith(simulateFirstDraftDefect: v)),
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: const Text('Simulate draft-0 defect', style: TextStyle(fontWeight: FontWeight.w600)),
          subtitle: const Text('Forces overlapping stops in the first draft to show the auditor rejecting it',
              style: TextStyle(fontSize: 12)),
        ),
        SwitchListTile(
          value: request.includeOptionalDatasets,
          onChanged: loading ? null : (v) => onChanged(request.copyWith(includeOptionalDatasets: v)),
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: const Text('Include optional datasets', style: TextStyle(fontWeight: FontWeight.w600)),
          subtitle: const Text('MARTA Saturday service, USDA food access, IMLS venues when available',
              style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: loading ? null : onSubmit,
          icon: loading
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.send),
          label: const Text('Generate plan'),
        ),
        if (response != null) ...[
          const SizedBox(height: 16),
          Row(children: [
            const Text('Last response ', style: TextStyle(fontSize: 12, color: Palette.muted)),
            VerdictChip(response!.status),
          ]),
          const SizedBox(height: 4),
          Text(response!.requestId, style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Palette.muted)),
          if (response!.finalPlan?.sensitivity case final s?) ...[
            const SizedBox(height: 8),
            Text('Stability under ±${s.perturbationPct.round()}% weights: Jaccard ${s.jaccard.toStringAsFixed(2)}',
                style: const TextStyle(fontSize: 12)),
          ],
        ],
      ]);
}

/// Who writes and reads each session.state key (plans 06–09). Lights up as
/// the run writes them, which answers "show me a key written by one agent and
/// read by another."
class StateInspector extends StatelessWidget {
  const StateInspector({super.key, required this.replay});
  final ReplayController replay;

  static const keys = <(String, String, List<String>)>[
    ('plan_request', 'coordinator', ['siting_planner', 'optimizer']),
    ('health_evidence', 'health_access', ['evidence_validator', 'optimizer']),
    ('mobility_evidence', 'transit_community', ['evidence_validator', 'optimizer']),
    ('evidence_report', 'evidence_validator', ['siting_planner', 'equity_auditor']),
    ('draft_plan', 'siting_planner', ['equity_auditor']),
    ('revision_required', 'equity_auditor', ['coordinator']),
    ('non_demographic_feedback', 'equity_auditor', ['siting_planner']),
    ('audit_report', 'equity_auditor', ['coordinator']),
    ('final_plan', 'coordinator', ['communications']),
    ('outreach_messages', 'communications', ['coordinator']),
  ];

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: replay,
        builder: (context, _) => ListView(padding: const EdgeInsets.all(16), children: [
          const Text('session.state',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, fontFamily: 'monospace')),
          const SizedBox(height: 4),
          const Text(
              'Every handoff between agents goes through one of these keys, and each has one writer. '
              'audit_report is never read by the planner: only non_demographic_feedback goes back.',
              style: TextStyle(color: Palette.muted, fontSize: 13)),
          const SizedBox(height: 16),
          for (final k in keys) _KeyRow(k: k, written: replay.writtenKeys.contains(k.$1)),
        ]),
      );
}

class _KeyRow extends StatelessWidget {
  const _KeyRow({required this.k, required this.written});
  final (String, String, List<String>) k;
  final bool written;

  @override
  Widget build(BuildContext context) {
    final w = agentInfo(k.$2);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: written ? Palette.accent.withValues(alpha: 0.06) : Colors.white,
        border: Border.all(color: written ? Palette.accent.withValues(alpha: 0.5) : Palette.line),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(k.$1, style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w700)),
          const Spacer(),
          Text(written ? 'written' : 'empty',
              style: TextStyle(fontSize: 11, color: written ? Palette.accent : Palette.muted)),
        ]),
        const SizedBox(height: 4),
        Text.rich(TextSpan(style: const TextStyle(fontSize: 12), children: [
          TextSpan(text: w.name, style: TextStyle(color: w.color, fontWeight: FontWeight.w600)),
          const TextSpan(text: '  →  ', style: TextStyle(color: Palette.muted)),
          TextSpan(text: k.$3.map((r) => agentInfo(r).name).join(', ')),
        ])),
      ]),
    );
  }
}
