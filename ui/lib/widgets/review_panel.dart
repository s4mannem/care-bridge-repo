import 'package:flutter/material.dart';

import '../models.dart';
import '../plan_source.dart';
import 'common.dart';

/// Human review of a provisional plan (`/v1/reviews/{request_id}`): confirm a
/// host venue per stop, reject a stop, then approve or ask for changes. The
/// plan is ready to announce only when approved with every kept stop's venue
/// confirmed; the API enforces the same rule.
class ReviewPanel extends StatefulWidget {
  const ReviewPanel({super.key, required this.source, required this.plan});
  final PlanSource source;
  final PlanResponse plan;

  @override
  State<ReviewPanel> createState() => _ReviewPanelState();
}

class _ReviewPanelState extends State<ReviewPanel> {
  ReviewState? _state;
  String? _error;
  bool _busy = false;

  String get _id => widget.plan.requestId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(ReviewPanel old) {
    super.didUpdateWidget(old);
    if (old.plan.requestId != _id) _load();
  }

  Future<void> _load() async {
    setState(() {
      _state = null;
      _error = null;
    });
    try {
      final s = await widget.source.review(_id);
      if (mounted) setState(() => _state = s);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _act(ReviewAction a) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final s = await widget.source.act(_id, a);
      if (mounted) setState(() => _state = s);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmVenue(int rank) async {
    final ctrl = TextEditingController(text: _state?.stop(rank).venueName ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Confirm a host venue for stop $rank'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          maxLength: 120,
          decoration: const InputDecoration(
              labelText: 'Venue', hintText: 'e.g. a library, church or community center lot'),
          onSubmitted: (v) => Navigator.pop(context, v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, ctrl.text), child: const Text('Confirm')),
        ],
      ),
    );
    if (name != null && name.trim().isNotEmpty) {
      await _act(ReviewAction('confirm_venue', stopRank: rank, venueName: name.trim()));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _state;
    final stops = widget.plan.finalPlan?.stops ?? const <ProposedClinicStop>[];
    final (Color color, String title) = switch (s?.status) {
      _ when s?.readyToAnnounce == true => (Palette.pass, 'Approved: ready to announce'),
      'approved' => (Palette.warn, 'Approved, but some venues are still unconfirmed'),
      'changes_requested' => (Palette.reject, 'Changes requested'),
      _ => (Palette.warn, 'Awaiting human review'),
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
        color: color.withValues(alpha: 0.04),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(s?.readyToAnnounce == true ? Icons.campaign : Icons.how_to_reg_outlined, color: color),
          const SizedBox(width: 8),
          Expanded(child: Text(title, style: TextStyle(fontWeight: FontWeight.w800, color: color))),
          if (_busy) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
        ]),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(_error!, style: const TextStyle(color: Palette.reject, fontSize: 12.5)),
          ),
        if (s == null && _error == null)
          const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator()),
        if (s != null) ...[
          const SizedBox(height: 8),
          for (final stop in stops) _stopRow(stop, s.stop(stop.rank)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.icon(
              onPressed: _busy || s.status == 'approved' ? null : () => _act(const ReviewAction('approve_plan')),
              icon: const Icon(Icons.check),
              label: const Text('Approve plan'),
            ),
            OutlinedButton.icon(
              onPressed: _busy || s.status == 'changes_requested'
                  ? null
                  : () => _act(const ReviewAction('request_changes')),
              icon: const Icon(Icons.undo),
              label: const Text('Request changes'),
            ),
            if (s.status != 'pending')
              TextButton(onPressed: _busy ? null : () => _act(const ReviewAction('reopen')), child: const Text('Reopen')),
          ]),
          if (s.log.isNotEmpty)
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                dense: true,
                title: Text('Review log (${s.log.length})', style: const TextStyle(fontSize: 12)),
                children: [
                  for (final (at, a) in s.log.reversed)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '${at.toLocal().toString().substring(0, 16)}  ${a.reviewerRole}: ${a.action.replaceAll('_', ' ')}'
                        '${a.stopRank != null ? ' · stop ${a.stopRank}' : ''}'
                        '${a.venueName != null ? ' · ${a.venueName}' : ''}',
                        style: const TextStyle(fontSize: 11.5, color: Palette.muted),
                      ),
                    ),
                ],
              ),
            ),
        ],
      ]),
    );
  }

  Widget _stopRow(ProposedClinicStop stop, StopReview r) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(children: [
          CircleAvatar(
            radius: 10,
            backgroundColor: r.rejected ? Palette.muted : Palette.accent,
            child: Text('${stop.rank}', style: const TextStyle(fontSize: 11, color: Colors.white)),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${saturdayLabel(stop.saturday)} · ${tractLabel(stop.tractGeoid)} · '
              '${r.rejected ? 'rejected' : r.venueConfirmed ? r.venueName : 'venue unconfirmed'}',
              style: TextStyle(
                fontSize: 12.5,
                decoration: r.rejected ? TextDecoration.lineThrough : null,
                color: r.venueConfirmed ? Palette.pass : r.rejected ? Palette.muted : Palette.ink,
                fontWeight: r.venueConfirmed ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ),
          TextButton(
            onPressed: _busy ? null : () => _confirmVenue(stop.rank),
            child: Text(r.venueConfirmed ? 'Change venue' : 'Confirm venue', style: const TextStyle(fontSize: 12)),
          ),
          IconButton(
            tooltip: r.rejected ? 'Already rejected' : 'Reject this stop',
            onPressed: _busy || r.rejected
                ? null
                : () => _act(ReviewAction('reject_stop', stopRank: stop.rank)),
            icon: const Icon(Icons.close, size: 18),
          ),
        ]),
      );
}
