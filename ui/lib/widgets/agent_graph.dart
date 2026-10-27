import 'package:flutter/material.dart';

import '../replay.dart';
import 'common.dart';

/// What each agent is for and where its boundaries are (plans 02–09). Shown
/// when a node is tapped; the boundaries are the architecture argument.
class AgentProfile {
  const AgentProfile({
    required this.role,
    required this.posture,
    required this.sees,
    required this.neverSees,
    required this.reads,
    required this.writes,
  });
  final String role;
  final String posture;
  final List<String> sees;
  final List<String> neverSees;
  final List<String> reads;
  final List<String> writes;
}

const profiles = <String, AgentProfile>{
  'coordinator': AgentProfile(
    role: 'Runs the graph: evidence in parallel, the validator gate, the plan-audit loop, then outreach.',
    posture: 'Routes and enforces limits; never edits a plan, a finding or an audit result.',
    sees: ['plan_request', 'final verdicts'],
    neverSees: ['demographic audit data'],
    reads: ['plan_request', 'audit_report', 'revision_required'],
    writes: ['final_plan'],
  ),
  'health_access': AgentProfile(
    role: 'Gathers tract burden, insurance and the two distances to care through the BigQuery MCP server.',
    posture: 'Reports each number with its grain: tract, facility point, 12 km grid or 4-county region.',
    sees: ['burden_tracts', 'tract_access', 'care_sites', 'shortage designations'],
    neverSees: ['race or ethnicity', 'personal data'],
    reads: ['plan_request'],
    writes: ['health_evidence'],
  ),
  'transit_community': AgentProfile(
    role: 'Adds Saturday MARTA service and candidate host venues when those datasets are available.',
    posture: 'Degrades gracefully: missing optional data is recorded, never invented.',
    sees: ['MARTA GTFS', 'USDA food access', 'IMLS venues (optional)'],
    neverSees: ['race or ethnicity', 'personal data'],
    reads: ['plan_request'],
    writes: ['mobility_evidence'],
  ),
  'evidence_validator': AgentProfile(
    role: 'Independent data-quality gate between evidence and planning.',
    posture: 'Blocks unsupported claims: a tract is not an HSA, distance is not journey time.',
    sees: ['health_evidence', 'mobility_evidence'],
    neverSees: ['race or ethnicity'],
    reads: ['health_evidence', 'mobility_evidence'],
    writes: ['evidence_report'],
  ),
  'siting_planner': AgentProfile(
    role: 'Picks four Saturday stops and explains each with cited, grain-qualified reasons.',
    posture: 'Analytical and hedged; race-blind by construction.',
    sees: ['evidence_report', 'non_demographic_feedback on revision'],
    neverSees: ['race or ethnicity', 'audit_report', 'the auditor\'s reasoning'],
    reads: ['plan_request', 'evidence_report', 'non_demographic_feedback'],
    writes: ['draft_plan', 'revision_history'],
  ),
  'optimizer': AgentProfile(
    role: 'Deterministic Python tool: scores tracts and selects four distinct 4 km catchments.',
    posture: 'Fixed rules, testable, no model calls. Reports sensitivity to ±15% weight changes.',
    sees: ['evidence the planner passes in'],
    neverSees: ['race or ethnicity'],
    reads: ['health_evidence', 'mobility_evidence', 'non_demographic_feedback'],
    writes: ['(returns a DraftPlan to the planner)'],
  ),
  'equity_auditor': AgentProfile(
    role: 'Challenges the draft: overlap, unsupported grain, sensitivity, and who the plan lands on.',
    posture: 'Skeptical and adversarial; cannot rewrite the plan. Only non-demographic defects go back.',
    sees: ['draft_plan', 'evidence_report', 'ACS race and ethnicity (auditor only)'],
    neverSees: ['the planner\'s prompt or reasoning'],
    reads: ['draft_plan', 'evidence_report'],
    writes: ['audit_report', 'revision_required', 'non_demographic_feedback'],
  ),
  'communications': AgentProfile(
    role: 'Writes EN/ES bus-stop flyers and "why not here" notes for neighborhoods not picked.',
    posture: 'Warm, plain, sixth-grade reading level. No statistics, no invented bookings.',
    sees: ['final_plan only'],
    neverSees: ['audit details', 'race or ethnicity'],
    reads: ['final_plan'],
    writes: ['outreach_messages'],
  ),
};

enum NodeState { idle, active, done, skipped, rejected, flagged }

NodeState nodeState(ReplayController r, String agent) {
  final latest = r.latestByAgent[agent];
  if (latest == null) return NodeState.idle;
  if (r.activeAgent == agent) return NodeState.active;
  if (latest.kind == 'skip') return NodeState.skipped;
  if (agent == 'equity_auditor' && r.rejectedOnScreen) return NodeState.rejected;
  if (latest.verdict == 'needs_human_review') return NodeState.flagged;
  return NodeState.done;
}

class AgentGraph extends StatelessWidget {
  const AgentGraph({super.key, required this.replay});
  final ReplayController replay;

  @override
  Widget build(BuildContext context) {
    Widget node(String id, {bool compact = false}) =>
        _Node(id: id, state: nodeState(replay, id), compact: compact, onTap: () => _details(context, id));
    final revisions = replay.drafts.length;

    return ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 24), children: [
      const Text('Tap an agent to see what it may and may never see.',
          style: TextStyle(fontSize: 12, color: Palette.muted)),
      const SizedBox(height: 12),
      node('coordinator'),
      const _Arrow(),
      _Group(label: 'parallel evidence', children: [
        Expanded(child: node('health_access', compact: true)),
        const SizedBox(width: 8),
        Expanded(child: node('transit_community', compact: true)),
      ]),
      const _Arrow(),
      node('evidence_validator'),
      const _Arrow(),
      Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: replay.rejected ? Palette.reject : Palette.line, width: replay.rejected ? 1.5 : 1),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const Icon(Icons.loop, size: 14, color: Palette.muted),
            const SizedBox(width: 4),
            const Expanded(
              child: Text('plan ⇄ audit loop · max 1 revision',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Palette.muted)),
            ),
            if (revisions > 0)
              Text('draft ${revisions - 1}${revisions > 1 ? ' (revised)' : ''}',
                  style: TextStyle(
                      fontSize: 11, fontWeight: FontWeight.w700, color: revisions > 1 ? Palette.reject : Palette.muted)),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(flex: 3, child: node('siting_planner', compact: true)),
            const Padding(padding: EdgeInsets.symmetric(horizontal: 4), child: Icon(Icons.functions, size: 14)),
            Expanded(flex: 2, child: node('optimizer', compact: true)),
          ]),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              const Icon(Icons.arrow_downward, size: 16, color: Palette.muted),
              const SizedBox(width: 24),
              Icon(Icons.arrow_upward, size: 16, color: replay.rejected ? Palette.reject : Palette.line),
              const SizedBox(width: 4),
              Text('non-demographic feedback only',
                  style: TextStyle(fontSize: 10, color: replay.rejected ? Palette.reject : Palette.muted)),
            ]),
          ),
          node('equity_auditor'),
        ]),
      ),
      const _Arrow(),
      node('communications'),
    ]);
  }

  void _details(BuildContext context, String id) {
    final a = agentInfo(id);
    final p = profiles[id]!;
    final steps = [for (final e in replay.shown) if (e.agent == id) e];
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        builder: (context, scroll) => ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(20, 0, 20, 24), children: [
          Row(children: [
            Icon(a.icon, color: a.color),
            const SizedBox(width: 8),
            Expanded(child: Text(a.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800))),
          ]),
          const SizedBox(height: 8),
          Text(p.role, style: const TextStyle(fontSize: 14, height: 1.4)),
          const SizedBox(height: 4),
          Text(p.posture, style: const TextStyle(fontSize: 13, color: Palette.muted, height: 1.4)),
          const SizedBox(height: 16),
          _Facts('May see', p.sees, Palette.pass, Icons.visibility_outlined),
          _Facts('Never sees', p.neverSees, Palette.reject, Icons.visibility_off_outlined),
          _Facts('Reads from session.state', p.reads, Palette.muted, Icons.input),
          _Facts('Writes to session.state', p.writes, Palette.accent, Icons.output),
          const SizedBox(height: 8),
          SectionTitle('In this run (${steps.length})'),
          if (steps.isEmpty) const Text('Not reached yet.', style: TextStyle(color: Palette.muted)),
          for (final e in steps)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text('${(e.tMs / 1000).toStringAsFixed(1)}s  ${e.message}',
                  style: TextStyle(
                      fontSize: 12.5,
                      color: e.verdict == 'reject' ? Palette.reject : Palette.ink,
                      fontWeight: e.verdict != null ? FontWeight.w700 : FontWeight.normal)),
            ),
        ]),
      ),
    );
  }
}

class _Facts extends StatelessWidget {
  const _Facts(this.title, this.items, this.color, this.icon);
  final String title;
  final List<String> items;
  final Color color;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color)),
              Wrap(spacing: 6, runSpacing: 4, children: [
                for (final i in items)
                  Text(i, style: const TextStyle(fontSize: 12.5, fontFamily: 'monospace')),
              ]),
            ]),
          ),
        ]),
      );
}

class _Node extends StatelessWidget {
  const _Node({required this.id, required this.state, required this.onTap, this.compact = false});
  final String id;
  final NodeState state;
  final VoidCallback onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final a = agentInfo(id);
    final (Color border, Color fill, String label) = switch (state) {
      NodeState.idle => (Palette.line, Colors.white, 'waiting'),
      NodeState.active => (a.color, a.color.withValues(alpha: 0.1), 'working'),
      NodeState.done => (Palette.pass.withValues(alpha: 0.6), Palette.pass.withValues(alpha: 0.05), 'done'),
      NodeState.skipped => (Palette.line, Palette.surface, 'skipped'),
      NodeState.rejected => (Palette.reject, Palette.reject.withValues(alpha: 0.08), 'rejected draft'),
      NodeState.flagged => (Palette.warn, Palette.warn.withValues(alpha: 0.08), 'needs review'),
    };
    return Material(
      color: fill,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: border, width: state == NodeState.active ? 2 : 1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 10, vertical: compact ? 8 : 10),
          child: Row(children: [
            Icon(a.icon, size: 18, color: state == NodeState.idle ? Palette.muted : a.color),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(a.name.replaceAll(' (tool)', ''),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                Text(label, style: TextStyle(fontSize: 10.5, color: state == NodeState.idle ? Palette.muted : border)),
              ]),
            ),
            if (state == NodeState.active)
              const SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2)),
          ]),
        ),
      ),
    );
  }
}

class _Group extends StatelessWidget {
  const _Group({required this.label, required this.children});
  final String label;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(border: Border.all(color: Palette.line), borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Palette.muted)),
          const SizedBox(height: 6),
          Row(children: children),
        ]),
      );
}

class _Arrow extends StatelessWidget {
  const _Arrow();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(vertical: 2),
        child: Icon(Icons.arrow_downward, size: 16, color: Palette.muted),
      );
}
