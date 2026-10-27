import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';

import '../geo.dart';
import '../models.dart';
import '../replay.dart';
import '../src/google_maps.dart';
import 'common.dart';
import 'google_planner_map.dart';

/// Fulton County shaded by need under the requested strategy, with care sites
/// and the stops of whichever draft the run has reached. A rejected draft's
/// overlapping pair is linked in red; after revision the dropped stop stays as
/// a ghost with a dashed line to its replacement. Runner-up tracts the van
/// won't reach are ringed in orange.
///
/// On the web with a Maps key deployed it draws on Google Maps
/// ([GooglePlannerMap]), where tracts can be tapped; otherwise on
/// OpenStreetMap tiles.
class PlannerMap extends StatelessWidget {
  const PlannerMap({
    super.key,
    required this.tracts,
    required this.sites,
    required this.response,
    required this.strategy,
    required this.replay,
    required this.selectedStop,
    required this.onSelectStop,
  });

  final List<Tract> tracts;
  final List<CareSite> sites;
  final PlanResponse? response;
  final Strategy strategy;
  final ReplayController replay;
  final int? selectedStop;
  final ValueChanged<int> onSelectStop;

  @override
  Widget build(BuildContext context) {
    final quantile = _needQuantiles();
    final r = response;
    final idx = replay.draftIndex;
    final drafts = replay.drafts;
    final draft = replay.currentDraft;
    final stops = draft?.stops ?? const <ProposedClinicStop>[];
    final rejected = replay.rejectedOnScreen;
    final approved = replay.audited && idx == drafts.length - 1;
    final conflict = rejected ? replay.conflictRanks : const <int>[];

    final first = idx != null && idx > 0 ? drafts.first.stops : const <ProposedClinicStop>[];
    bool same(ProposedClinicStop a, ProposedClinicStop b) => a.tractGeoid == b.tractGeoid;
    final ghosts = first.where((o) => !stops.any((n) => same(o, n))).toList();
    final added = idx != null && idx > 0 ? stops.where((n) => !first.any((o) => same(o, n))).toList() : const [];

    final byId = {for (final t in tracts) t.geoId: t};
    final runnerUps = replay.finalWritten ? r?.finalPlan?.runnerUps ?? const <RunnerUpTract>[] : const [];

    final bounds = LatLngBounds.fromPoints(tracts.expand((t) => t.rings.expand((ring) => ring)).toList());
    Color tone(ProposedClinicStop s) => conflict.contains(s.rank)
        ? Palette.reject
        : approved
            ? Palette.accent
            : const Color(0xFF1565C0);

    final google = googleMapsLoaded;
    return Stack(children: [
      if (google)
        GooglePlannerMap(
          tracts: tracts,
          bounds: bounds,
          quantile: quantile,
          strategy: strategy,
          sites: sites,
          stops: stops,
          tone: tone,
          conflict: conflict,
          ghosts: ghosts,
          added: added.cast<ProposedClinicStop>(),
          runnerUps: runnerUps.cast<RunnerUpTract>(),
          approved: approved,
          rejected: rejected,
          selectedStop: selectedStop,
          onSelectStop: onSelectStop,
        )
      else
      FlutterMap(
        options: MapOptions(
          initialCameraFit: CameraFit.bounds(bounds: bounds, padding: const EdgeInsets.all(24)),
          interactionOptions: const InteractionOptions(flags: InteractiveFlag.all & ~InteractiveFlag.rotate),
        ),
        children: [
          // OSM tiles, greyed and faded so the need shading carries the color.
          // (CARTO now needs a key; Esri's tile server sends no CORS header.)
          Opacity(
            opacity: 0.55,
            child: ColorFiltered(
              colorFilter: const ColorFilter.matrix([
                0.2126, 0.7152, 0.0722, 0, 0, //
                0.2126, 0.7152, 0.0722, 0, 0,
                0.2126, 0.7152, 0.0722, 0, 0,
                0, 0, 0, 1, 0,
              ]),
              child: TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'org.carebridge.saturday_planner',
              ),
            ),
          ),
          PolygonLayer(polygons: [
            for (final t in tracts)
              for (final ring in t.rings)
                Polygon(
                  points: ring,
                  color: Palette.forNeed(quantile[t.geoId]).withValues(alpha: 0.72),
                  borderColor: Colors.white.withValues(alpha: 0.9),
                  borderStrokeWidth: 0.6,
                ),
            for (final u in runnerUps)
              if (byId[u.tractGeoid] case final t?)
                for (final ring in t.rings)
                  Polygon(points: ring, borderColor: Palette.warn, borderStrokeWidth: 2.5),
          ]),
          CircleLayer(circles: [
            for (final s in stops)
              CircleMarker(
                point: s.point,
                radius: s.catchmentKm * 1000,
                useRadiusInMeter: true,
                color: tone(s).withValues(alpha: 0.08),
                borderColor: tone(s).withValues(alpha: 0.6),
                borderStrokeWidth: 1.2,
              ),
            for (final site in sites)
              CircleMarker(
                point: site.point,
                // Opening hours as capacity: a 60-hour clinic is more supply than an 8-hour one.
                radius: site.safetyNet ? 3 + ((site.hours ?? 20) / 168 * 7) : 3.5,
                color: site.safetyNet ? const Color(0xFF1565C0) : const Color(0xFF90A4AE),
                borderColor: Colors.white,
                borderStrokeWidth: 1,
              ),
          ]),
          PolylineLayer(polylines: [
            if (conflict.length == 2)
              Polyline(
                points: [for (final n in conflict) stops.firstWhere((s) => s.rank == n).point],
                color: Palette.reject,
                strokeWidth: 3,
              ),
            for (var i = 0; i < ghosts.length && i < added.length; i++)
              Polyline(
                points: [ghosts[i].point, added[i].point],
                color: Palette.ink.withValues(alpha: 0.7),
                strokeWidth: 2,
                pattern: StrokePattern.dashed(segments: const [8, 6]),
              ),
          ]),
          MarkerLayer(markers: [
            for (final u in runnerUps)
              if (byId[u.tractGeoid] case final t?)
                Marker(
                  point: centroid(t.rings),
                  width: 34,
                  height: 20,
                  child: Tooltip(
                    message: '${t.label}: need rank #${u.needRank}, not reached (${u.reasonLabel})',
                    child: Container(
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                          color: Colors.white,
                          border: Border.all(color: Palette.warn),
                          borderRadius: BorderRadius.circular(10)),
                      child: Text('#${u.needRank}',
                          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: Palette.warn)),
                    ),
                  ),
                ),
            for (final g in ghosts)
              Marker(
                point: g.point,
                width: 30,
                height: 30,
                child: Tooltip(
                  message: '${tractLabel(g.tractGeoid)}: dropped after audit',
                  child: const _Pin(label: '×', color: Color(0xFF9E9E9E), ghost: true),
                ),
              ),
            for (final s in stops)
              Marker(
                point: s.point,
                width: 34,
                height: 34,
                child: GestureDetector(
                  onTap: () => onSelectStop(s.rank),
                  child: Tooltip(
                    message: '${saturdayLabel(s.saturday)} · ${tractLabel(s.tractGeoid)}',
                    child: _Pin(
                      label: '${s.rank}',
                      color: tone(s),
                      ghost: !approved && !rejected,
                      selected: s.rank == selectedStop,
                    ),
                  ),
                ),
              ),
          ]),
          const RichAttributionWidget(
            alignment: AttributionAlignment.bottomRight,
            attributions: [
              TextSourceAttribution('© OpenStreetMap contributors'),
              TextSourceAttribution('US Census TIGER (tracts)'),
            ],
          ),
        ],
      ),
      // Clear of Google's logo and terms along the bottom edge.
      Positioned(left: 12, bottom: google ? 30 : 12, child: _Legend(strategy: strategy)),
      if (draft != null)
        Positioned(
          top: 12,
          left: 12,
          child: _DraftTag(revision: draft.revision, rejected: rejected, approved: approved,
              status: r?.status ?? 'running'),
        ),
    ]);
  }

  /// Colors by rank within the county so the ramp stays readable per strategy.
  Map<String, double> _needQuantiles() {
    final scored = tracts.where((t) => t.need?[strategy.wire] != null).toList()
      ..sort((a, b) => a.need![strategy.wire]!.compareTo(b.need![strategy.wire]!));
    return {for (var i = 0; i < scored.length; i++) scored[i].geoId: i / (scored.length - 1)};
  }
}

class _Pin extends StatelessWidget {
  const _Pin({required this.label, required this.color, this.ghost = false, this.selected = false});
  final String label;
  final Color color;
  final bool ghost;
  final bool selected;

  @override
  Widget build(BuildContext context) => AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        decoration: BoxDecoration(
          color: ghost ? Colors.white : color,
          shape: BoxShape.circle,
          border: Border.all(color: selected ? Palette.ink : color, width: selected ? 3 : 2),
          boxShadow: const [BoxShadow(blurRadius: 4, color: Colors.black26)],
        ),
        alignment: Alignment.center,
        child: Text(label,
            style: TextStyle(color: ghost ? color : Colors.white, fontWeight: FontWeight.w800, fontSize: 14)),
      );
}

class _DraftTag extends StatelessWidget {
  const _DraftTag({required this.revision, required this.rejected, required this.approved, required this.status});
  final int revision;
  final bool rejected;
  final bool approved;

  /// PlanResponse.status, which also folds in the equity review.
  final String status;

  @override
  Widget build(BuildContext context) {
    final (text, color, icon) = rejected
        ? ('Draft $revision · REJECTED by auditor', Palette.reject, Icons.block)
        : approved && status == 'running'
            ? ('Draft $revision · audited', Palette.pass, Icons.verified_outlined)
            : approved
            ? status == 'provisional_approved'
                ? ('Draft $revision · approved, provisional', Palette.pass, Icons.verified_outlined)
                : ('Draft $revision · needs human review', Palette.warn, Icons.how_to_reg_outlined)
            : ('Draft $revision · awaiting audit', const Color(0xFF1565C0), Icons.hourglass_top);
    return Material(
      elevation: 2,
      borderRadius: BorderRadius.circular(6),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(text, style: TextStyle(fontWeight: FontWeight.w600, color: color, fontSize: 12)),
        ]),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.strategy});
  final Strategy strategy;

  @override
  Widget build(BuildContext context) => Material(
        elevation: 1,
        borderRadius: BorderRadius.circular(6),
        color: Colors.white.withValues(alpha: 0.95),
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text('Need rank · ${strategy.label}', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Row(mainAxisSize: MainAxisSize.min, children: [
              const Text('low ', style: TextStyle(fontSize: 10)),
              for (final c in Palette.need) Container(width: 16, height: 10, color: c),
              const Text(' high', style: TextStyle(fontSize: 10)),
            ]),
            const SizedBox(height: 6),
            _row(const Color(0xFF1565C0), 'Safety-net site (size = hours/week)'),
            _row(const Color(0xFF90A4AE), 'Hospital (not safety-net)'),
            _row(Palette.warn, 'High-need tract the van won\'t reach'),
          ]),
        ),
      );

  Widget _row(Color c, String t) => Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 10, height: 10, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(t, style: const TextStyle(fontSize: 10)),
        ]),
      );
}
