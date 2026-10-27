import 'package:latlong2/latlong.dart';

// Haversine, matching the optimizer, so UI and planner notes agree to 0.1 km.
const _distance = Distance(calculator: Haversine());

/// Great-circle distance in km, as the optimizer's haversine computes it.
double km(LatLng a, LatLng b) => _distance.as(LengthUnit.Meter, a, b) / 1000;

LatLng centroid(List<List<LatLng>> rings) {
  final pts = rings.expand((r) => r).toList();
  return LatLng(
    pts.map((p) => p.latitude).reduce((a, b) => a + b) / pts.length,
    pts.map((p) => p.longitude).reduce((a, b) => a + b) / pts.length,
  );
}
