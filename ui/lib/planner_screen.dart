import 'dart:async';

import 'package:flutter/material.dart';

import 'models.dart';
import 'plan_source.dart';
import 'replay.dart';
import 'widgets/agent_graph.dart';
import 'widgets/ask_panel.dart';
import 'widgets/common.dart';
import 'widgets/plan_tabs.dart';
import 'widgets/planner_map.dart';
import 'widgets/side_panels.dart';
import 'widgets/timeline.dart';

class PlannerScreen extends StatefulWidget {
  const PlannerScreen({super.key, required this.source});
  final PlanSource source;

  @override
  State<PlannerScreen> createState() => _PlannerScreenState();
}

class _PlannerScreenState extends State<PlannerScreen> {
  final _replay = ReplayController();
  late final Future<(List<Tract>, List<CareSite>)> _layers = _loadLayers();
  PlanRequest _request = const PlanRequest(simulateFirstDraftDefect: true);
  PlanRequest? _planned; // the request behind _response, for Ask
  PlanResponse? _response;
  Object? _error;
  bool _loading = false;
  int? _selectedStop;
  int _mobileTab = 0;
  StreamSubscription<RunUpdate>? _run;

  Future<(List<Tract>, List<CareSite>)> _loadLayers() async =>
      (await widget.source.tracts(_request.countyFips), await loadSites());

  void _submit() {
    _run?.cancel();
    final request = _request;
    _replay.startLive();
    setState(() {
      _loading = true;
      _error = null;
      _response = null;
      _selectedStop = null;
    });
    _run = widget.source.run(request).listen(
      (u) => switch (u) {
        RunEvent(:final event) => _replay.add(event),
        RunDone(:final plan) => setState(() {
            _response = plan;
            _planned = request;
          }),
      },
      onError: (Object e) => setState(() {
        _error = e;
        _loading = false;
        _replay.finish();
      }),
      onDone: () => setState(() {
        _loading = false;
        _replay.finish();
      }),
    );
  }

  @override
  void dispose() {
    _run?.cancel();
    _replay.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder(
        future: _layers,
        builder: (context, snap) {
          if (snap.hasError) {
            return Scaffold(body: Center(child: Text('Could not load the tract layer: ${snap.error}')));
          }
          if (!snap.hasData) return const Scaffold(body: Center(child: CircularProgressIndicator()));
          final (tracts, sites) = snap.data!;
          return ListenableBuilder(
            listenable: _replay,
            builder: (context, _) => _scaffold(context, tracts, sites),
          );
        },
      );

  Widget _scaffold(BuildContext context, List<Tract> tracts, List<CareSite> sites) {
    void select(int rank) => setState(() => _selectedStop = rank);
    final map = PlannerMap(
      tracts: tracts,
      sites: sites,
      response: _response,
      strategy: _replay.currentDraft?.strategy ?? _request.strategy,
      replay: _replay,
      selectedStop: _selectedStop,
      onSelectStop: select,
    );
    final tabs = Column(children: [
      if (_error != null)
        MaterialBanner(
          content: Text('Plan request failed: $_error'),
          backgroundColor: Palette.reject.withValues(alpha: 0.08),
          actions: [TextButton(onPressed: _submit, child: const Text('Retry'))],
        ),
      if (_response?.status == 'error')
        const MaterialBanner(
          content: Text('The gateway returned status "error": core evidence was not ready, so no plan was made.'),
          actions: [SizedBox.shrink()],
        ),
      Expanded(
        child: PlanTabs(
            source: widget.source,
            response: _response,
            replay: _replay,
            selectedStop: _selectedStop,
            onSelectStop: select),
      ),
    ]);
    final agents = DefaultTabController(
      length: 3,
      child: Column(children: [
        Material(
          color: Colors.white,
          child: TabBar(
            labelColor: Palette.ink,
            unselectedLabelColor: Palette.muted,
            indicatorColor: Palette.accent,
            tabs: [
              const Tab(icon: Icon(Icons.account_tree_outlined, size: 18), text: 'Agents'),
              Tab(
                icon: Badge(
                  isLabelVisible: _replay.rejectedOnScreen,
                  backgroundColor: Palette.reject,
                  child: const Icon(Icons.timeline, size: 18),
                ),
                text: 'Run',
              ),
              const Tab(icon: Icon(Icons.forum_outlined, size: 18), text: 'Ask'),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: TabBarView(children: [
            AgentGraph(replay: _replay),
            AgentTimeline(replay: _replay),
            AskPanel(source: widget.source, plan: _response, request: _planned ?? _request),
          ]),
        ),
      ]),
    );
    final form = RequestPanel(
      request: _request,
      onChanged: (r) => setState(() => _request = r),
      onSubmit: () {
        _submit();
        setState(() => _mobileTab = 0);
      },
      loading: _loading,
      response: _response,
    );

    return LayoutBuilder(builder: (context, box) {
      final wide = box.maxWidth >= 1100;
      return Scaffold(
        backgroundColor: Colors.white,
        appBar: AppBar(
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.white,
          titleSpacing: 16,
          title: Row(children: [
            const Icon(Icons.airport_shuttle_outlined, color: Palette.accent),
            const SizedBox(width: 8),
            const Text('CareBridge', style: TextStyle(fontWeight: FontWeight.w800)),
            if (wide) const Text('  ·  Saturday Planner', style: TextStyle(color: Palette.muted)),
            if (_response?.isRecorded ?? widget.source.recorded) ...[
              const SizedBox(width: 12),
              Tooltip(
                message: 'Plans recorded from the real a4i_health tables by scripts/build_mock.py, in the '
                    'plan 00 PlanResponse shape. Agent wording is templated until the ADK agents run.',
                child: box.maxWidth >= 600
                    ? const _Tag('RECORDED')
                    : const Icon(Icons.fiber_manual_record, size: 12, color: Palette.warn),
              ),
            ],
          ]),
          actions: [
            Builder(
              builder: (context) => TextButton.icon(
                onPressed: () => Scaffold.of(context).openEndDrawer(),
                icon: const Icon(Icons.data_object),
                label: Text(wide ? 'session.state' : 'State'),
              ),
            ),
            const SizedBox(width: 8),
          ],
          bottom: const PreferredSize(preferredSize: Size.fromHeight(1), child: Divider(height: 1)),
        ),
        endDrawer: Drawer(width: 380, child: StateInspector(replay: _replay)),
        body: wide
            ? Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SizedBox(width: 300, child: form),
                const VerticalDivider(width: 1),
                Expanded(
                  child: Column(children: [
                    Expanded(flex: 10, child: map),
                    const Divider(height: 1),
                    Expanded(flex: 11, child: tabs),
                  ]),
                ),
                const VerticalDivider(width: 1),
                SizedBox(width: 400, child: agents),
              ])
            : IndexedStack(index: _mobileTab, children: [
                Column(children: [
                  SizedBox(height: box.maxHeight * 0.4, child: map),
                  ReplayBar(replay: _replay),
                  const Divider(height: 1),
                  Expanded(child: tabs),
                ]),
                agents,
                form,
              ]),
        bottomNavigationBar: wide
            ? null
            : NavigationBar(
                selectedIndex: _mobileTab,
                onDestinationSelected: (i) => setState(() => _mobileTab = i),
                destinations: [
                  const NavigationDestination(icon: Icon(Icons.map_outlined), label: 'Plan'),
                  NavigationDestination(
                    icon: Badge(
                      isLabelVisible: _replay.rejectedOnScreen,
                      backgroundColor: Palette.reject,
                      child: const Icon(Icons.account_tree_outlined),
                    ),
                    label: 'Agents',
                  ),
                  const NavigationDestination(icon: Icon(Icons.tune), label: 'Request'),
                ],
              ),
      );
    });
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: Palette.warn.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(4)),
        child: Text(text, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Palette.warn)),
      );
}
