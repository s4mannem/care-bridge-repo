import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import 'models.dart';

/// Where plans come from. The UI talks only to the gateway contract
/// (plan 10): it never queries BigQuery or calls agent tools itself.
abstract class PlanSource {
  Future<PlanResponse> plan(PlanRequest request);
  Future<List<Tract>> tracts(String countyFips);
}

/// Recorded responses generated from the real data by scripts/build_mock.py,
/// one per strategy and defect toggle.
class RecordedPlanSource implements PlanSource {
  @override
  Future<PlanResponse> plan(PlanRequest request) async {
    final mode = request.simulateFirstDraftDefect ? 'defect' : 'standard';
    final raw = await rootBundle.loadString('assets/mock/plan_${request.strategy.wire}_$mode.json');
    return PlanResponse.fromJson(jsonDecode(raw));
  }

  @override
  Future<List<Tract>> tracts(String countyFips) async =>
      parseTracts(jsonDecode(await rootBundle.loadString('assets/data/fulton_tracts.geojson')));
}

/// The live gateway. Build with `--dart-define=CAREBRIDGE_API=https://…`.
///
/// No API key is sent: a key compiled into a Flutter bundle is public. The
/// gateway must authorize the UI another way (Cloud Run IAM / IAP in front of
/// a backend-for-frontend route). See plans/11.
class HttpPlanSource implements PlanSource {
  HttpPlanSource(this.baseUrl, {http.Client? client}) : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  @override
  Future<PlanResponse> plan(PlanRequest request) async {
    final res = await _client
        .post(Uri.parse('$baseUrl/v1/plan'),
            headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: jsonEncode(request.toJson()))
        .timeout(const Duration(seconds: 130));
    if (res.statusCode != 200) {
      throw PlanSourceException(res.statusCode, res.body, res.headers['x-request-id']);
    }
    return PlanResponse.fromJson(jsonDecode(res.body));
  }

  @override
  Future<List<Tract>> tracts(String countyFips) async {
    final res = await _client.get(Uri.parse('$baseUrl/v1/tracts/$countyFips'));
    if (res.statusCode != 200) throw PlanSourceException(res.statusCode, res.body, res.headers['x-request-id']);
    return parseTracts(jsonDecode(res.body));
  }
}

class PlanSourceException implements Exception {
  PlanSourceException(this.statusCode, this.body, this.requestId);
  final int statusCode;
  final String body;
  final String? requestId;

  @override
  String toString() => 'Gateway returned $statusCode${requestId == null ? '' : ' (request $requestId)'}';
}

List<Tract> parseTracts(Map<String, dynamic> geo) => [
      for (final f in geo['features'] as List)
        Tract(
          geoId: f['properties']['geo_id'],
          label: f['properties']['label'],
          // Outer rings only; Fulton tracts have no holes worth drawing at this zoom.
          rings: [
            for (final poly in f['geometry']['type'] == 'Polygon'
                ? [f['geometry']['coordinates']]
                : f['geometry']['coordinates'] as List)
              [for (final c in poly[0]) LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())]
          ],
          need: f['properties']['need'] == null
              ? null
              : {
                  for (final e in (f['properties']['need'] as Map).entries)
                    e.key as String: (e.value as num).toDouble()
                },
        ),
    ];

Future<List<CareSite>> loadSites() async {
  final list = jsonDecode(await rootBundle.loadString('assets/data/care_sites.json')) as List;
  return [for (final s in list) CareSite.fromJson(s)];
}
