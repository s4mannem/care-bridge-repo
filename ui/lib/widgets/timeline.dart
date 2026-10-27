import 'package:flutter/material.dart';

import '../models.dart';
import '../replay.dart';
import 'common.dart';

/// Live view of the agent run. The point of it is the rejection: the auditor
/// row turns red and the planner's revision follows underneath it.
class AgentTimeline extends StatefulWidget {
  const AgentTimeline({super.key, required this.replay});
  final ReplayController replay;

  @override
  State<AgentTimeline> createState() => _AgentTimelineState();
}

class _AgentTimelineState extends State<AgentTimeline> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    widget.replay.addListener(_follow);
  }

  @override
  void dispose() {
    widget.replay.removeListener(_follow);
    _scroll.dispose();
    super.dispose();
  }

  void _follow() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients && widget.replay.running) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
        }
      });

  @override
  Widget build(BuildContext context) {
    final r = widget.replay;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      ReplayBar(replay: r),
      const Divider(height: 1),
      Expanded(
        child: r.idle
            ? const _Empty()
            : ListView.builder(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
                itemCount: r.shown.length,
                itemBuilder: (_, i) => _EventRow(
                  event: r.shown[i],
                  isLatest: i == r.shown.length - 1 && r.running,
                  revisionStart: r.shown[i].agent == 'siting_planner' &&
                      r.shown[i].kind == 'start' &&
                      r.shown.take(i).any((e) => e.verdict == 'reject'),
                ),
              ),
      ),
    ]);
  }
}

class ReplayBar extends StatelessWidget {
  const ReplayBar({super.key, required this.replay});
  final ReplayController replay;

  @override
  Widget build(BuildContext context) {
    final r = replay;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      child: Row(children: [
        const Expanded(
          child: Text('Agent run',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14, color: Palette.ink)),
        ),
        if (r.running)
          const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 4),
        PopupMenuButton<double>(
          tooltip: 'Replay speed',
          initialValue: r.speed,
          onSelected: r.setSpeed,
          itemBuilder: (_) => [
            for (final s in [0.5, 1.0, 2.0, 4.0]) PopupMenuItem(value: s, child: Text('${s}x')),
          ],
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Text('${r.speed}x', style: const TextStyle(fontSize: 12, color: Palette.muted)),
          ),
        ),
        IconButton(
          tooltip: 'Replay from start',
          onPressed: r.events.isEmpty || r.live ? null : r.play,
          icon: const Icon(Icons.replay),
        ),
        IconButton(
          tooltip: 'Skip to result',
          onPressed: r.events.isEmpty || r.live || r.shown.length == r.events.length ? null : r.skipToEnd,
          icon: const Icon(Icons.skip_next),
        ),
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) => const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Choose a strategy and press Generate plan.\n\nYou\'ll see evidence gathered in parallel, the '
            'planner\'s draft, the auditor\'s verdict on it and, with the defect toggle on, the revision.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Palette.muted, height: 1.4),
          ),
        ),
      );
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event, required this.isLatest, required this.revisionStart});
  final AgentEvent event;
  final bool isLatest;
  final bool revisionStart;

  @override
  Widget build(BuildContext context) {
    final a = agentInfo(event.agent);
    final reject = event.verdict == 'reject';
    final pass = event.verdict == 'approved';
    final warn = event.verdict == 'needs_human_review' ||
        event.message.startsWith('WARN') ||
        event.message.startsWith('PARITY');
    final skip = event.kind == 'skip';
    final tone = reject
        ? Palette.reject
        : pass
            ? Palette.pass
            : warn
                ? Palette.warn
                : null;

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (revisionStart)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 6),
          child: Row(children: [
            Expanded(child: Divider()),
            Padding(
              padding: EdgeInsets.symmetric(horizontal: 8),
              child: Text('REVISION 1 OF MAX 1',
                  style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Palette.reject)),
            ),
            Expanded(child: Divider()),
          ]),
        ),
      AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        margin: EdgeInsets.only(bottom: 6, left: event.parallel ? 14 : 0),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: tone?.withValues(alpha: 0.08) ?? (isLatest ? Palette.surface : Colors.white),
          border: Border.all(color: tone?.withValues(alpha: 0.5) ?? Palette.line),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(a.icon, size: 18, color: skip ? Palette.muted : a.color),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(
                  child: Text(a.name,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 11, fontWeight: FontWeight.w700, color: skip ? Palette.muted : a.color)),
                ),
                if (event.parallel) ...[
                  const SizedBox(width: 6),
                  const Text('parallel', style: TextStyle(fontSize: 10, color: Palette.muted)),
                ],
                const Spacer(),
                Text('${(event.tMs / 1000).toStringAsFixed(1)}s',
                    style: const TextStyle(fontSize: 10, color: Palette.muted)),
              ]),
              const SizedBox(height: 2),
              Text(event.message,
                  style: TextStyle(
                      fontSize: 12.5,
                      height: 1.3,
                      color: skip ? Palette.muted : Palette.ink,
                      fontWeight: reject || pass ? FontWeight.w600 : FontWeight.normal,
                      fontStyle: skip ? FontStyle.italic : FontStyle.normal)),
              if (event.stateKey != null && event.kind != 'verdict') ...[
                const SizedBox(height: 4),
                Text('→ session.state["${event.stateKey}"]',
                    style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Palette.muted)),
              ],
            ]),
          ),
        ]),
      ),
    ]);
  }
}
