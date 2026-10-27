import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart' show LatLngBounds;
import 'package:google_maps_flutter/google_maps_flutter.dart' as gm;
import 'package:latlong2/latlong.dart';

import '../geo.dart';
import '../models.dart';
import 'common.dart';

/// [PlannerMap]'s layers on a live Google map: Fulton tracts as a need heat
/// map you can tap, care sites, the current draft's stops with their 4 km
/// catchments, the auditor's conflict line, dropped stops and runner-up tracts.
/// [PlannerMap] works out what to draw; this only draws it.
class GooglePlannerMap extends StatefulWidget {
  const GooglePlannerMap({
    super.key,
    required this.tracts,
    required this.bounds,
    required this.quantile,
    required this.strategy,
    required this.sites,
    required this.stops,
    required this.tone,
    required this.conflict,
    required this.ghosts,
    required this.added,
    required this.runnerUps,
    required this.approved,
    required this.rejected,
    required this.selectedStop,
    required this.onSelectStop,
  });

  final List<Tract> tracts;
  final LatLngBounds bounds;
  final Map<String, double> quantile;
  final Strategy strategy;
  final List<CareSite> sites;
  final List<ProposedClinicStop> stops;
  final Color Function(ProposedClinicStop) tone;
  final List<int> conflict;
  final List<ProposedClinicStop> ghosts;
  final List<ProposedClinicStop> added;
  final List<RunnerUpTract> runnerUps;
  final bool approved;
  final bool rejected;
  final int? selectedStop;
  final ValueChanged<int> onSelectStop;

  @override
  State<GooglePlannerMap> createState() => _GooglePlannerMapState();
}

class _GooglePlannerMapState extends State<GooglePlannerMap> {
  gm.GoogleMapController? _controller;
  gm.MapType _type = gm.MapType.normal;
  bool _shading = true;
  String? _tapped;

  /// Pin and dot images, drawn once per look and reused.
  static final _icons = <String, gm.BitmapDescriptor>{};
  final _pending = <String>{};

  gm.LatLng _g(LatLng p) => gm.LatLng(p.latitude, p.longitude);

  gm.LatLngBounds get _bounds => gm.LatLngBounds(southwest: _g(widget.bounds.southWest), northeast: _g(widget.bounds.northEast));

  void _fit() => _controller?.moveCamera(gm.CameraUpdate.newLatLngBounds(_bounds, 24));

  /// The icon for [key], or Google's default marker until it has been drawn.
  gm.BitmapDescriptor _icon(String key, Future<gm.BitmapDescriptor> Function() draw) {
    final hit = _icons[key];
    if (hit != null) return hit;
    if (_pending.add(key)) {
      draw().then((d) {
        _icons[key] = d;
        if (mounted) setState(() {});
      });
    }
    return gm.BitmapDescriptor.defaultMarker;
  }

  /// Need rank of each scored tract under the current strategy, 1 = highest.
  Map<String, int> _ranks() {
    final ids = widget.quantile.keys.toList()..sort((a, b) => widget.quantile[b]!.compareTo(widget.quantile[a]!));
    return {for (var i = 0; i < ids.length; i++) ids[i]: i + 1};
  }

  @override
  Widget build(BuildContext context) {
    final w = widget;
    final byId = {for (final t in w.tracts) t.geoId: t};
    final reached = {for (final s in w.stops) s.tractGeoid};

    final polygons = <gm.Polygon>{
      if (_shading)
        for (final t in w.tracts)
          for (final (i, ring) in t.rings.indexed)
            gm.Polygon(
              polygonId: gm.PolygonId('${t.geoId}/$i'),
              points: [for (final p in ring) _g(p)],
              fillColor: Palette.forNeed(w.quantile[t.geoId]).withValues(alpha: 0.6),
              strokeColor: t.geoId == _tapped ? Palette.ink : Colors.white,
              strokeWidth: t.geoId == _tapped ? 3 : 1,
              zIndex: t.geoId == _tapped ? 2 : 0,
              consumeTapEvents: true,
              onTap: () => setState(() => _tapped = t.geoId),
            ),
      for (final u in w.runnerUps)
        if (byId[u.tractGeoid] case final t?)
          for (final (i, ring) in t.rings.indexed)
            gm.Polygon(
              polygonId: gm.PolygonId('runner-up/${t.geoId}/$i'),
              points: [for (final p in ring) _g(p)],
              fillColor: Colors.transparent,
              strokeColor: Palette.warn,
              strokeWidth: 3,
              zIndex: 1,
            ),
    };

    final circles = <gm.Circle>{
      for (final s in w.stops)
        gm.Circle(
          circleId: gm.CircleId('catchment/${s.rank}'),
          center: _g(s.point),
          radius: s.catchmentKm * 1000,
          fillColor: w.tone(s).withValues(alpha: 0.08),
          strokeColor: w.tone(s).withValues(alpha: 0.7),
          strokeWidth: 2,
          zIndex: 3,
        ),
    };

    final polylines = <gm.Polyline>{
      if (w.conflict.length == 2)
        gm.Polyline(
          polylineId: const gm.PolylineId('conflict'),
          points: [for (final n in w.conflict) _g(w.stops.firstWhere((s) => s.rank == n).point)],
          color: Palette.reject,
          width: 4,
          zIndex: 4,
        ),
      for (var i = 0; i < w.ghosts.length && i < w.added.length; i++)
        gm.Polyline(
          polylineId: gm.PolylineId('moved/$i'),
          points: [_g(w.ghosts[i].point), _g(w.added[i].point)],
          color: Palette.ink.withValues(alpha: 0.7),
          width: 2,
          patterns: [gm.PatternItem.dash(12), gm.PatternItem.gap(8)],
          zIndex: 4,
        ),
    };

    final markers = <gm.Marker>{
      for (final (i, site) in w.sites.indexed)
        () {
          // Opening hours as capacity, as on the OSM map: a 60-hour clinic is more supply than an 8-hour one.
          final d = site.safetyNet ? (2 * (3 + (site.hours ?? 20) / 168 * 7)).round() : 7;
          final color = site.safetyNet ? const Color(0xFF1565C0) : const Color(0xFF90A4AE);
          return gm.Marker(
            markerId: gm.MarkerId('site/$i'),
            position: _g(site.point),
            icon: _icon('dot/${color.toARGB32()}/$d', () => _dot(color, d)),
            anchor: const Offset(0.5, 0.5),
            zIndexInt: 1,
            infoWindow: gm.InfoWindow(title: site.name, snippet: site.kind),
          );
        }(),
      for (final u in w.runnerUps)
        if (byId[u.tractGeoid] case final t?)
          gm.Marker(
            markerId: gm.MarkerId('runner-up/${u.tractGeoid}'),
            position: _g(centroid(t.rings)),
            icon: _icon('runner-up/${u.needRank}', () => _pill('#${u.needRank}')),
            anchor: const Offset(0.5, 0.5),
            zIndexInt: 2,
            infoWindow: gm.InfoWindow(title: t.label, snippet: 'Need rank #${u.needRank}, not reached (${u.reasonLabel})'),
          ),
      for (final g in w.ghosts)
        gm.Marker(
          markerId: gm.MarkerId('dropped/${g.tractGeoid}'),
          position: _g(g.point),
          icon: _icon('dropped', () => _pin('×', const Color(0xFF9E9E9E), ghost: true)),
          anchor: const Offset(0.5, 0.5),
          zIndexInt: 3,
          infoWindow: gm.InfoWindow(title: tractLabel(g.tractGeoid), snippet: 'Dropped after audit'),
        ),
      for (final s in w.stops)
        () {
          final ghost = !w.approved && !w.rejected;
          final selected = s.rank == w.selectedStop;
          final color = w.tone(s);
          return gm.Marker(
            markerId: gm.MarkerId('stop/${s.rank}'),
            position: _g(s.point),
            icon: _icon('stop/${s.rank}/${color.toARGB32()}/$ghost/$selected',
                () => _pin('${s.rank}', color, ghost: ghost, selected: selected)),
            anchor: const Offset(0.5, 0.5),
            zIndexInt: 4,
            infoWindow: gm.InfoWindow(title: 'Stop ${s.rank} · ${saturdayLabel(s.saturday)}', snippet: tractLabel(s.tractGeoid)),
            onTap: () => w.onSelectStop(s.rank),
          );
        }(),
    };

    final tapped = _tapped == null ? null : byId[_tapped];
    return Stack(children: [
      gm.GoogleMap(
        initialCameraPosition: gm.CameraPosition(target: _g(widget.bounds.center), zoom: 9.5),
        mapType: _type,
        polygons: polygons,
        circles: circles,
        polylines: polylines,
        markers: markers,
        zoomControlsEnabled: true,
        mapToolbarEnabled: false,
        rotateGesturesEnabled: false,
        tiltGesturesEnabled: false,
        webGestureHandling: gm.WebGestureHandling.greedy,
        onTap: (_) => setState(() => _tapped = null),
        onMapCreated: (c) {
          _controller = c;
          // The map needs its size before it can fit bounds.
          Future<void>.delayed(const Duration(milliseconds: 200), _fit);
        },
      ),
      Positioned(
        top: 12,
        right: 12,
        child: _Controls(
          type: _type,
          shading: _shading,
          onType: (t) => setState(() => _type = t),
          onShading: (v) => setState(() {
            _shading = v;
            if (!v) _tapped = null;
          }),
          onFit: _fit,
        ),
      ),
      if (tapped != null)
        Positioned(
          top: 60,
          right: 12,
          child: _TractCard(
            tract: tapped,
            strategy: w.strategy,
            rank: _ranks()[tapped.geoId],
            of: w.quantile.length,
            hasStop: reached.contains(tapped.geoId),
            runnerUp: w.runnerUps.where((u) => u.tractGeoid == tapped.geoId).firstOrNull,
            onClose: () => setState(() => _tapped = null),
          ),
        ),
    ]);
  }
}

// ── Marker images ─────────────────────────────────────────────────────────────
// Google markers are images, so the OSM map's numbered pins are drawn here.

const _scale = 2.0; // device pixels per logical pixel, for sharp markers

Future<gm.BitmapDescriptor> _draw(Size size, void Function(Canvas c) paint) async {
  final rec = ui.PictureRecorder();
  final canvas = Canvas(rec)..scale(_scale);
  paint(canvas);
  final img = await rec.endRecording().toImage((size.width * _scale).ceil(), (size.height * _scale).ceil());
  final png = await img.toByteData(format: ui.ImageByteFormat.png);
  return gm.BitmapDescriptor.bytes(png!.buffer.asUint8List(), width: size.width, height: size.height);
}

void _text(Canvas c, String s, Offset center, Color color, double size) {
  final tp = TextPainter(
    text: TextSpan(text: s, style: TextStyle(color: color, fontSize: size, fontWeight: FontWeight.w800)),
    textDirection: TextDirection.ltr,
  )..layout();
  tp.paint(c, center - Offset(tp.width / 2, tp.height / 2));
}

/// Same look as the OSM map's `_Pin`.
Future<gm.BitmapDescriptor> _pin(String label, Color color, {bool ghost = false, bool selected = false}) {
  const size = Size(38, 38);
  return _draw(size, (c) {
    final center = size.center(Offset.zero);
    c.drawCircle(center + const Offset(0, 1.5), 16, Paint()..color = Colors.black26..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2));
    c.drawCircle(center, 15, Paint()..color = ghost ? Colors.white : color);
    c.drawCircle(
        center,
        15,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = selected ? 3 : 2
          ..color = selected ? Palette.ink : color);
    _text(c, label, center, ghost ? color : Colors.white, 14);
  });
}

Future<gm.BitmapDescriptor> _dot(Color color, int d) {
  final size = Size(d + 2.0, d + 2.0);
  return _draw(size, (c) {
    final center = size.center(Offset.zero);
    c.drawCircle(center, d / 2, Paint()..color = color);
    c.drawCircle(center, d / 2, Paint()..style = PaintingStyle.stroke..strokeWidth = 1..color = Colors.white);
  });
}

Future<gm.BitmapDescriptor> _pill(String label) {
  const size = Size(34, 20);
  return _draw(size, (c) {
    final r = RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(10)).deflate(0.5);
    c.drawRRect(r, Paint()..color = Colors.white);
    c.drawRRect(r, Paint()..style = PaintingStyle.stroke..color = Palette.warn);
    _text(c, label, size.center(Offset.zero), Palette.warn, 10);
  });
}

// ── Overlays ──────────────────────────────────────────────────────────────────

class _Controls extends StatelessWidget {
  const _Controls({
    required this.type,
    required this.shading,
    required this.onType,
    required this.onShading,
    required this.onFit,
  });
  final gm.MapType type;
  final bool shading;
  final ValueChanged<gm.MapType> onType;
  final ValueChanged<bool> onShading;
  final VoidCallback onFit;

  @override
  Widget build(BuildContext context) => Material(
        elevation: 2,
        borderRadius: BorderRadius.circular(6),
        color: Colors.white,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            SegmentedButton<gm.MapType>(
              style: const ButtonStyle(visualDensity: VisualDensity.compact),
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: gm.MapType.normal, label: Text('Map', style: TextStyle(fontSize: 12))),
                ButtonSegment(value: gm.MapType.hybrid, label: Text('Satellite', style: TextStyle(fontSize: 12))),
              ],
              selected: {type},
              onSelectionChanged: (s) => onType(s.first),
            ),
            const SizedBox(width: 8),
            const Text('Need shading', style: TextStyle(fontSize: 12)),
            Switch(value: shading, onChanged: onShading),
            IconButton(
              tooltip: 'Back to all of Fulton',
              icon: const Icon(Icons.fit_screen_outlined, size: 20),
              onPressed: onFit,
            ),
          ]),
        ),
      );
}

/// What a tapped tract scores under the current strategy, and whether the plan reaches it.
class _TractCard extends StatelessWidget {
  const _TractCard({
    required this.tract,
    required this.strategy,
    required this.rank,
    required this.of,
    required this.hasStop,
    required this.runnerUp,
    required this.onClose,
  });
  final Tract tract;
  final Strategy strategy;
  final int? rank;
  final int of;
  final bool hasStop;
  final RunnerUpTract? runnerUp;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final score = tract.need?[strategy.wire];
    final status = hasStop
        ? ('A stop is planned here', Palette.pass)
        : runnerUp != null
            ? ('Runner-up: not reached (${runnerUp!.reasonLabel})', Palette.warn)
            : null;
    return Material(
      elevation: 2,
      borderRadius: BorderRadius.circular(6),
      color: Colors.white,
      child: Container(
        width: 250,
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Expanded(child: Text(tract.label, style: const TextStyle(fontWeight: FontWeight.w700))),
            IconButton(
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.close, size: 18),
              onPressed: onClose,
            ),
          ]),
          if (score == null)
            const Text('No population: not scored.', style: TextStyle(fontSize: 12, color: Palette.muted))
          else ...[
            Text('Need rank #$rank of $of · ${strategy.label}', style: const TextStyle(fontSize: 12)),
            const SizedBox(height: 2),
            Text('Composite need score ${score.toStringAsFixed(2)} (top ${(100 * rank! / of).ceil()}%)',
                style: const TextStyle(fontSize: 12, color: Palette.muted)),
          ],
          if (status != null) ...[
            const SizedBox(height: 6),
            Text(status.$1, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: status.$2)),
          ],
        ]),
      ),
    );
  }
}
