import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models.dart';
import '../replay.dart';
import 'common.dart';

/// The four parts of the Clinic Plan (plan 11). Each tab unlocks when the run
/// reaches the agent that owns it.
class PlanTabs extends StatelessWidget {
  const PlanTabs({
    super.key,
    required this.response,
    required this.replay,
    required this.selectedStop,
    required this.onSelectStop,
  });

  final PlanResponse? response;
  final ReplayController replay;
  final int? selectedStop;
  final ValueChanged<int> onSelectStop;

  @override
  Widget build(BuildContext context) {
    final r = response;
    final idx = replay.draftIndex;
    return DefaultTabController(
      length: 4,
      child: Column(children: [
        const Material(
          color: Colors.white,
          child: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            labelColor: Palette.ink,
            unselectedLabelColor: Palette.muted,
            indicatorColor: Palette.accent,
            tabs: [
              Tab(text: '1 · Four Saturdays'),
              Tab(text: '2 · Why not here?'),
              Tab(text: '3 · Equity & rigor audit'),
              Tab(text: '4 · Flyers & data limits'),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: TabBarView(children: [
            r == null || idx == null
                ? const _Locked('The planner hasn\'t written a draft yet.')
                : _StopsTab(
                    response: r,
                    draft: r.revisionHistory[idx],
                    replay: replay,
                    selectedStop: selectedStop,
                    onSelectStop: onSelectStop),
            r?.finalPlan == null || !replay.finalWritten
                ? const _Locked('Runner-up tracts are listed once the final plan is chosen.')
                : _RunnerUpsTab(plan: r!.finalPlan!, outreach: r.outreach),
            r?.auditReport == null || !replay.audited
                ? const _Locked('The auditor publishes this after its final verdict.')
                : _AuditTab(response: r!),
            r?.outreach == null || !replay.outreachReady
                ? const _Locked('Communications writes this from final_plan only, after the audit.')
                : _FlyersTab(response: r!),
          ]),
        ),
      ]),
    );
  }
}

class _Locked extends StatelessWidget {
  const _Locked(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.lock_clock_outlined, color: Palette.muted, size: 18),
            const SizedBox(width: 8),
            Flexible(child: Text(text, style: const TextStyle(color: Palette.muted))),
          ]),
        ),
      );
}

class _Banner extends StatelessWidget {
  const _Banner({required this.icon, required this.color, required this.title, this.lines = const []});
  final IconData icon;
  final Color color;
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.07),
          border: Border.all(color: color.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: color)),
              for (final l in lines) Text(l, style: const TextStyle(fontSize: 13, height: 1.35)),
            ]),
          ),
        ]),
      );
}

// ── 1 · Four Saturdays ─────────────────────────────────────────────────────

class _StopsTab extends StatelessWidget {
  const _StopsTab({
    required this.response,
    required this.draft,
    required this.replay,
    required this.selectedStop,
    required this.onSelectStop,
  });

  final PlanResponse response;
  final DraftPlan draft;
  final ReplayController replay;
  final int? selectedStop;
  final ValueChanged<int> onSelectStop;

  @override
  Widget build(BuildContext context) {
    final rejected = replay.rejectedOnScreen;
    final pair = rejected ? overlapPair(draft) : null;
    final done = replay.finalWritten;
    final equity = response.auditReport?.demographicImpact.requiresHumanReview ?? false;
    return ListView(padding: const EdgeInsets.all(16), children: [
      if (pair != null)
        _Banner(
          icon: Icons.block,
          color: Palette.reject,
          title: 'Auditor rejected draft ${draft.revision}',
          lines: ['Stops ${pair.$1.rank} and ${pair.$2.rank} are ${pair.$3.toStringAsFixed(1)} km apart, so their '
              '${pair.$1.catchmentKm.round()} km catchments overlap and two Saturdays would serve the same people.'],
        ),
      if (done && response.needsHumanReview)
        _Banner(
          icon: Icons.how_to_reg_outlined,
          color: Palette.warn,
          title: response.status == 'needs_human_review'
              ? 'Needs human review before anything is announced'
              : 'Provisionally approved: confirm hosts before announcing',
          lines: [
            if (draft.stops.any((s) => !s.hostVerified)) '• No host venue is verified yet.',
            if (equity) '• The equity audit flagged groups below parity (see tab 3).',
          ],
        ),
      for (final n in draft.plannerNotes)
        _Banner(icon: Icons.edit_note, color: const Color(0xFF1565C0), title: 'Planner note', lines: [n]),
      Wrap(spacing: 12, runSpacing: 12, children: [
        for (final s in draft.stops)
          _StopCard(
            stop: s,
            selected: s.rank == selectedStop,
            flagged: pair != null && (s.rank == pair.$1.rank || s.rank == pair.$2.rank),
            onTap: () => onSelectStop(s.rank),
          ),
      ]),
    ]);
  }
}

class _StopCard extends StatelessWidget {
  const _StopCard({required this.stop, required this.selected, required this.flagged, required this.onTap});
  final ProposedClinicStop stop;
  final bool selected;
  final bool flagged;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final border = flagged ? Palette.reject : selected ? Palette.ink : Palette.line;
    return SizedBox(
      width: 340,
      child: Card(
        elevation: selected ? 3 : 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(color: border, width: selected || flagged ? 2 : 1),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                CircleAvatar(
                  radius: 13,
                  backgroundColor: flagged ? Palette.reject : Palette.accent,
                  child: Text('${stop.rank}',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(saturdayLabel(stop.saturday), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                    Text(tractLabel(stop.tractGeoid), style: const TextStyle(fontSize: 12, color: Palette.muted)),
                  ]),
                ),
                Tooltip(
                  message: 'composite_need_score',
                  child: Text(stop.score.composite.toStringAsFixed(2),
                      style: const TextStyle(fontWeight: FontWeight.w700, color: Palette.accent, fontSize: 16)),
                ),
              ]),
              if (!stop.hostVerified) ...[
                const SizedBox(height: 8),
                Tooltip(
                  message: stop.provisionalWarning,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                    decoration: BoxDecoration(
                      color: Palette.warn.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: const Text('PROVISIONAL · host unconfirmed',
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Palette.warn)),
                  ),
                ),
              ],
              const SizedBox(height: 10),
              for (final (label, v, measured) in stop.score.components) _ScoreBar(label, v, measured),
              const SizedBox(height: 8),
              Text(stop.rationale, style: const TextStyle(fontSize: 12.5, height: 1.4)),
              const SizedBox(height: 4),
              Text('~${fmtInt(stop.catchmentPop)} residents within ${stop.catchmentKm.round()} km · '
                  '${stop.coveredTractGeoids.length} tracts',
                  style: const TextStyle(fontSize: 12, color: Palette.muted)),
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(bottom: 4),
                  dense: true,
                  title: const Text('Sources and grain', style: TextStyle(fontSize: 12)),
                  children: [
                    for (final g in stop.grainDisclosures)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          ScaleBadge(g),
                          const SizedBox(width: 6),
                          Expanded(
                              child: Text(g.split(':').skip(1).join(':').trim(), style: const TextStyle(fontSize: 11.5))),
                        ]),
                      ),
                    for (final c in stop.citations)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text('• $c', style: const TextStyle(fontSize: 11.5, color: Palette.muted)),
                      ),
                  ],
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _ScoreBar extends StatelessWidget {
  const _ScoreBar(this.label, this.value, this.measured);
  final String label;
  final double value;
  final bool measured;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          SizedBox(width: 128, child: Text(label, style: const TextStyle(fontSize: 11.5))),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: LinearProgressIndicator(
                value: value,
                minHeight: 8,
                backgroundColor: Palette.surface,
                color: Palette.accent.withValues(alpha: 0.75),
              ),
            ),
          ),
          const SizedBox(width: 6),
          SizedBox(
              width: 30,
              child: Text(value.toStringAsFixed(2), textAlign: TextAlign.right, style: const TextStyle(fontSize: 11))),
          const SizedBox(width: 4),
          SourceBadge(measured: measured),
        ]),
      );
}

// ── 2 · Why not here? (Question 7) ─────────────────────────────────────────

class _RunnerUpsTab extends StatefulWidget {
  const _RunnerUpsTab({required this.plan, required this.outreach});
  final DraftPlan plan;
  final OutreachMessages? outreach;

  @override
  State<_RunnerUpsTab> createState() => _RunnerUpsTabState();
}

class _RunnerUpsTabState extends State<_RunnerUpsTab> {
  bool _spanish = false;

  @override
  Widget build(BuildContext context) {
    final notes = {for (final u in widget.outreach?.unpicked ?? const <UnpickedExplanation>[]) u.tractGeoid: u};
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        const Text(
          'The highest-need tracts that no stop\'s catchment reaches. For each: the planner\'s technical '
          'reason, and what to tell people who live there.',
          style: TextStyle(color: Palette.muted),
        ),
        _LangToggle(spanish: _spanish, onChanged: (v) => setState(() => _spanish = v)),
      ]),
      const SizedBox(height: 12),
      if (widget.plan.runnerUps.isEmpty) const Text('Every high-need tract falls inside a selected catchment.'),
      for (final u in widget.plan.runnerUps)
        Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(border: Border.all(color: Palette.line), borderRadius: BorderRadius.circular(6)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: Palette.warn, borderRadius: BorderRadius.circular(10)),
                child: Text('#${u.needRank}',
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 12)),
              ),
              Text(tractLabel(u.tractGeoid), style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(u.reasonLabel, style: const TextStyle(fontSize: 12, color: Palette.warn)),
              Text('${u.distanceKm.toStringAsFixed(1)} km to nearest stop',
                  style: const TextStyle(fontSize: 12, color: Palette.muted)),
              const ScaleBadge('census_tract_11char'),
            ]),
            const SizedBox(height: 6),
            Text(u.rationale, style: const TextStyle(fontSize: 13, height: 1.35)),
            if (notes[u.tractGeoid] case final n?) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: const Color(0xFFFFFBF2), borderRadius: BorderRadius.circular(6)),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.record_voice_over_outlined, size: 16, color: Palette.muted),
                  const SizedBox(width: 8),
                  Expanded(
                      child: Text(_spanish ? n.spanish : n.english, style: const TextStyle(fontSize: 14, height: 1.4))),
                  _CopyButton(text: _spanish ? n.spanish : n.english),
                ]),
              ),
            ],
          ]),
        ),
    ]);
  }
}

// ── 3 · Equity & rigor audit ───────────────────────────────────────────────

class _AuditTab extends StatelessWidget {
  const _AuditTab({required this.response});
  final PlanResponse response;

  @override
  Widget build(BuildContext context) {
    final a = response.auditReport!;
    final impact = a.demographicImpact;
    final sens = response.finalPlan?.sensitivity;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Row(children: [
        const Text('Verdict ', style: TextStyle(fontWeight: FontWeight.w700)),
        VerdictChip(a.verdict),
        const SizedBox(width: 8),
        Text('on draft ${a.revisionAudited}', style: const TextStyle(color: Palette.muted)),
      ]),
      const SizedBox(height: 6),
      Text(a.summary, style: const TextStyle(fontSize: 13.5, height: 1.4)),
      if (response.hadRevision) ...[
        const SizedBox(height: 16),
        const SectionTitle('The disagreement: draft 0 vs final'),
        _RevisionDiff(history: response.revisionHistory),
      ],
      if (a.defects.isNotEmpty) ...[
        const SizedBox(height: 16),
        const SectionTitle('Open non-demographic defects'),
        for (final d in a.defects)
          _Banner(
              icon: Icons.report_outlined,
              color: Palette.reject,
              title: '${d.category} · stops ${d.affectedStopRanks.join(', ')}',
              lines: [d.description, 'Fix: ${d.remediation}']),
      ],
      if (sens != null) ...[
        const SizedBox(height: 16),
        const SectionTitle('Sensitivity'),
        Row(children: [
          Text('Jaccard ${sens.jaccard.toStringAsFixed(2)}',
              style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 16,
                  color: sens.jaccard >= 0.8 ? Palette.pass : Palette.warn)),
          const SizedBox(width: 8),
          Expanded(child: Text(sens.notes, style: const TextStyle(fontSize: 12.5))),
        ]),
        if (sens.borderlineTracts.isNotEmpty)
          Text('Borderline: ${sens.borderlineTracts.map(tractLabel).join(', ')}',
              style: const TextStyle(fontSize: 12, color: Palette.muted)),
      ],
      const SizedBox(height: 20),
      const _Banner(
        icon: Icons.shield_outlined,
        color: Color(0xFFAD1457),
        title: 'Auditor-only: post-hoc demographic comparison',
        lines: [
          'Computed after the plan is drafted, from ACS tract data the planner never receives. Findings go to '
              'human review; only non-demographic defects are ever sent back to the planner.',
        ],
      ),
      Text(
          'Catchments reach ~${fmtInt(impact.catchmentPop)} of ${fmtInt(impact.countyPop)} residents '
          '(${(impact.catchmentPop / impact.countyPop * 100).toStringAsFixed(0)}%). '
          'SVI theme 3 proxy: ${impact.catchmentTheme3.toStringAsFixed(2)} in catchments vs '
          '${impact.countyTheme3.toStringAsFixed(2)} county-wide.',
          style: const TextStyle(fontSize: 13.5)),
      const SizedBox(height: 12),
      // Highlight what the auditor flagged rather than re-deciding the rule here.
      for (final g in impact.groups) _ParityRow(g, flagged: impact.findings.any((f) => f.startsWith('${g.group}:'))),
      if (impact.findings.isNotEmpty)
        _Banner(
            icon: Icons.flag_outlined,
            color: Palette.warn,
            title: 'Below parity 0.80, referred to human review',
            lines: impact.findings),
      for (final l in a.limitations)
        Text('• $l', style: const TextStyle(fontSize: 12, color: Palette.muted)),
    ]);
  }
}

class _RevisionDiff extends StatelessWidget {
  const _RevisionDiff({required this.history});
  final List<DraftPlan> history;

  @override
  Widget build(BuildContext context) {
    final d0 = history.first, d1 = history.last;
    final pair = overlapPair(d0);
    Widget col(DraftPlan d, Set<String> other, Color changed) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Draft ${d.revision}', style: const TextStyle(fontWeight: FontWeight.w700)),
            for (final s in d.stops)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('${s.rank}. ${tractLabel(s.tractGeoid)}',
                    style: TextStyle(
                        fontSize: 13,
                        color: other.contains(s.tractGeoid) ? Palette.ink : changed,
                        fontWeight: other.contains(s.tractGeoid) ? FontWeight.normal : FontWeight.w700)),
              ),
          ]),
        );
    final ids0 = d0.stops.map((s) => s.tractGeoid).toSet();
    final ids1 = d1.stops.map((s) => s.tractGeoid).toSet();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(border: Border.all(color: Palette.line), borderRadius: BorderRadius.circular(6)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          col(d0, ids1, Palette.reject),
          const Padding(padding: EdgeInsets.symmetric(horizontal: 8, vertical: 20), child: Icon(Icons.arrow_forward)),
          col(d1, ids0, Palette.pass),
        ]),
        if (pair != null) ...[
          const SizedBox(height: 8),
          Text('Rejected because stops ${pair.$1.rank} and ${pair.$2.rank} were ${pair.$3.toStringAsFixed(1)} km apart.',
              style: const TextStyle(fontSize: 12.5, color: Palette.reject)),
        ],
        for (final n in d1.plannerNotes) Text(n, style: const TextStyle(fontSize: 12.5, color: Palette.muted)),
      ]),
    );
  }
}

class _ParityRow extends StatelessWidget {
  const _ParityRow(this.g, {required this.flagged});
  final GroupComparison g;
  final bool flagged;

  @override
  Widget build(BuildContext context) {
    final max = [g.catchmentPct, g.countyPct].reduce((a, b) => a > b ? a : b) * 1.15;
    final low = flagged;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(g.group, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13))),
          Text('parity ${g.parityRatio.toStringAsFixed(2)}',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: low ? Palette.warn : Palette.muted)),
        ]),
        _bar('Plan', g.catchmentPct, max, low ? Palette.warn : Palette.accent),
        _bar('County', g.countyPct, max, const Color(0xFFB0BEC5)),
      ]),
    );
  }

  Widget _bar(String label, double v, double max, Color c) => Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Row(children: [
          SizedBox(width: 52, child: Text(label, style: const TextStyle(fontSize: 11, color: Palette.muted))),
          Expanded(
            child: LayoutBuilder(
              builder: (_, box) => Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  height: 10,
                  width: max == 0 ? 0 : box.maxWidth * v / max,
                  decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(2)),
                ),
              ),
            ),
          ),
          SizedBox(
              width: 48,
              child: Text('${v.toStringAsFixed(1)}%',
                  textAlign: TextAlign.right, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
        ]),
      );
}

// ── 4 · Flyers & data limits ───────────────────────────────────────────────

class _FlyersTab extends StatefulWidget {
  const _FlyersTab({required this.response});
  final PlanResponse response;

  @override
  State<_FlyersTab> createState() => _FlyersTabState();
}

class _FlyersTabState extends State<_FlyersTab> {
  bool _spanish = false;

  @override
  Widget build(BuildContext context) {
    final o = widget.response.outreach!;
    final ev = widget.response.evidenceReport;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        _LangToggle(spanish: _spanish, onChanged: (v) => setState(() => _spanish = v)),
        Text(o.banner, style: const TextStyle(fontSize: 12, color: Palette.warn, fontWeight: FontWeight.w700)),
      ]),
      const SizedBox(height: 16),
      Wrap(spacing: 16, runSpacing: 16, children: [
        for (final n in o.stopNotices) _Flyer(text: _spanish ? n.spanish : n.english, why: n.whyChosen),
      ]),
      const SizedBox(height: 16),
      Row(children: [
        const ScaleBadge('multi_county_health_service_area'),
        const SizedBox(width: 8),
        Expanded(
            child: Text(_spanish ? o.surveillanceNoteEs : o.surveillanceNoteEn,
                style: const TextStyle(fontSize: 13))),
      ]),
      const SizedBox(height: 24),
      const SectionTitle('What this plan cannot tell you'),
      for (final l in widget.response.limitations)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.visibility_off_outlined, size: 16, color: Palette.muted),
            const SizedBox(width: 8),
            Expanded(child: Text(l, style: const TextStyle(fontSize: 13, height: 1.35))),
          ]),
        ),
      if (ev != null) ...[
        const SizedBox(height: 16),
        const SectionTitle('Evidence validator'),
        for (final c in ev.checks)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 52, child: VerdictChip(c.verdict)),
              const SizedBox(width: 8),
              Expanded(
                child: Text.rich(TextSpan(style: const TextStyle(fontSize: 12.5), children: [
                  TextSpan(text: '${c.name}  ', style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w600)),
                  TextSpan(text: c.detail),
                  if (!c.isPipelineCheck) const TextSpan(text: '  (note)', style: TextStyle(color: Palette.muted)),
                ])),
              ),
            ]),
          ),
        const SizedBox(height: 8),
        for (final c in ev.caveats)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(c, style: const TextStyle(fontSize: 12, color: Palette.muted, height: 1.35)),
          ),
      ],
      const SizedBox(height: 16),
      const SectionTitle('Data availability'),
      Wrap(spacing: 6, runSpacing: 6, children: [
        for (final e in widget.response.dataAvailability.entries)
          Chip(
            avatar: Icon(e.value ? Icons.check_circle : Icons.cancel_outlined,
                size: 16, color: e.value ? Palette.pass : Palette.muted),
            label: Text(e.key, style: const TextStyle(fontSize: 12, fontFamily: 'monospace')),
            visualDensity: VisualDensity.compact,
          ),
      ]),
      const SizedBox(height: 8),
      Text('Provenance: ${widget.response.provenance.join(' · ')}',
          style: const TextStyle(fontSize: 11, color: Palette.muted)),
    ]);
  }
}

class _Flyer extends StatelessWidget {
  const _Flyer({required this.text, required this.why});
  final String text;
  final String why;

  @override
  Widget build(BuildContext context) {
    final lines = text.split('\n');
    return Container(
      width: 340,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFBF2),
        border: Border.all(color: const Color(0xFFE8D9B5)),
        borderRadius: BorderRadius.circular(4),
        boxShadow: const [BoxShadow(blurRadius: 6, color: Colors.black12, offset: Offset(0, 2))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
              child: Text(lines.first, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800, height: 1.2))),
          _CopyButton(text: text),
        ]),
        const SizedBox(height: 8),
        Text(lines.skip(1).join('\n').trim(), style: const TextStyle(fontSize: 14.5, height: 1.45)),
        const Divider(height: 20),
        Text('Why here: $why', style: const TextStyle(fontSize: 12, color: Palette.muted)),
      ]),
    );
  }
}

class _LangToggle extends StatelessWidget {
  const _LangToggle({required this.spanish, required this.onChanged});
  final bool spanish;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => SegmentedButton<bool>(
        segments: const [
          ButtonSegment(value: false, label: Text('English')),
          ButtonSegment(value: true, label: Text('Español')),
        ],
        selected: {spanish},
        showSelectedIcon: false,
        onSelectionChanged: (s) => onChanged(s.first),
      );
}

class _CopyButton extends StatelessWidget {
  const _CopyButton({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: 'Copy',
        icon: const Icon(Icons.copy, size: 18),
        onPressed: () {
          Clipboard.setData(ClipboardData(text: text));
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied')));
        },
      );
}
