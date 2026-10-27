import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import 'models.dart';
import 'src/streaming_client.dart';

/// What a run produces: agent events as they happen, then the finished plan.
sealed class RunUpdate {}

class RunEvent extends RunUpdate {
  RunEvent(this.event);
  final AgentEvent event;
}

class RunDone extends RunUpdate {
  RunDone(this.plan);
  final PlanResponse plan;
}

/// Where plans come from. The UI talks only to the gateway contract
/// (plan 10): it never queries BigQuery or calls agent tools itself.
abstract class PlanSource {
  /// True when answers come from recorded files, not the API.
  bool get recorded;

  Stream<RunUpdate> run(PlanRequest request);
  Future<AskResponse> ask(AskRequest request);
  Future<ReviewState> review(String planRequestId);
  Future<ReviewState> act(String planRequestId, ReviewAction action);
  Future<List<Tract>> tracts(String countyFips);
}

class PlanSourceException implements Exception {
  PlanSourceException(this.statusCode, this.code, this.message, [this.requestId]);
  final int statusCode;
  final String code;
  final String message;
  final String? requestId;

  factory PlanSourceException.fromResponse(int status, String body, String? rid) {
    try {
      final e = (jsonDecode(body) as Map<String, dynamic>)['error'] as Map<String, dynamic>;
      return PlanSourceException(status, e['code'] ?? 'http_$status', e['message'] ?? body, e['request_id'] ?? rid);
    } catch (_) {
      return PlanSourceException(status, 'http_$status', body.isEmpty ? 'Gateway returned $status' : body, rid);
    }
  }

  @override
  String toString() => message;
}

/// Recorded runs generated from the real data by scripts/build_mock.py: the
/// plan, the events the API would stream, and answers to the suggested
/// questions. Review state is kept in memory.
class RecordedPlanSource implements PlanSource {
  final _reviews = <String, Map<String, dynamic>>{};

  @override
  bool get recorded => true;

  String _stem(PlanRequest r) => '${r.strategy.wire}_${r.simulateFirstDraftDefect ? 'defect' : 'standard'}';

  Future<Map<String, dynamic>> _run(PlanRequest r) async =>
      jsonDecode(await rootBundle.loadString('assets/mock/run_${_stem(r)}.json'));

  @override
  Stream<RunUpdate> run(PlanRequest request) async* {
    final plan = PlanResponse.fromJson(jsonDecode(await rootBundle.loadString('assets/mock/plan_${_stem(request)}.json')));
    var last = 0;
    for (final e in (await _run(request))['events'] as List) {
      final event = AgentEvent.fromJson(e);
      await Future<void>.delayed(Duration(milliseconds: event.tMs - last));
      last = event.tMs;
      yield RunEvent(event);
    }
    yield RunDone(plan);
  }

  @override
  Future<AskResponse> ask(AskRequest request) async {
    final asks = (await _run(request.plan))['asks'] as Map<String, dynamic>;
    final hit = asks[request.question.trim()];
    if (hit == null) {
      throw PlanSourceException(0, 'needs_api',
          'This recorded build can only answer the suggested questions. Free-text questions need the live API.');
    }
    return AskResponse.fromJson(hit);
  }

  Map<String, dynamic> _state(String id) => _reviews[id] ??= {
        'plan_request_id': id,
        'status': 'pending',
        'stops': [for (var n = 1; n <= 4; n++) {'stop_rank': n, 'venue_confirmed': false, 'rejected': false}],
        'log': <Map<String, dynamic>>[],
        'ready_to_announce': false,
      };

  @override
  Future<ReviewState> review(String planRequestId) async => ReviewState.fromJson(_state(planRequestId));

  /// Same rules as the API's data/reviews.py apply_action.
  @override
  Future<ReviewState> act(String planRequestId, ReviewAction a) async {
    final s = jsonDecode(jsonEncode(_state(planRequestId))) as Map<String, dynamic>;
    final stops = (s['stops'] as List).cast<Map<String, dynamic>>();
    switch (a.action) {
      case 'confirm_venue' || 'reject_stop':
        final stop = stops.firstWhere((x) => x['stop_rank'] == a.stopRank);
        if (a.action == 'confirm_venue') {
          if ((a.venueName ?? '').trim().isEmpty) {
            throw PlanSourceException(422, 'invalid_review_action', 'confirm_venue needs venue_name.');
          }
          stop..['venue_confirmed'] = true..['venue_name'] = a.venueName!.trim()..['rejected'] = false;
        } else {
          stop..['rejected'] = true..['venue_confirmed'] = false;
        }
        if (s['status'] == 'approved') s['status'] = 'pending';
      case 'approve_plan':
        if (stops.every((x) => x['rejected'] == true)) {
          throw PlanSourceException(422, 'invalid_review_action', 'Every stop is rejected; nothing to approve.');
        }
        s['status'] = 'approved';
      case 'request_changes':
        s['status'] = 'changes_requested';
      case 'reopen':
        s['status'] = 'pending';
    }
    (s['log'] as List).add({'at': DateTime.now().toUtc().toIso8601String(), 'action': a.toJson()});
    final kept = stops.where((x) => x['rejected'] != true);
    s['ready_to_announce'] =
        s['status'] == 'approved' && kept.isNotEmpty && kept.every((x) => x['venue_confirmed'] == true);
    _reviews[planRequestId] = s;
    return ReviewState.fromJson(s);
  }

  @override
  Future<List<Tract>> tracts(String countyFips) async =>
      parseTracts(jsonDecode(await rootBundle.loadString('assets/data/fulton_tracts.geojson')));
}

/// The live gateway. Build with `--dart-define=CAREBRIDGE_API=https://…`, or
/// `same-origin` behind the UI's nginx proxy.
///
/// No API key is sent: a key compiled into a Flutter bundle is public.
class HttpPlanSource implements PlanSource {
  HttpPlanSource(this.baseUrl, {http.Client? client}) : _client = client ?? createStreamingClient();

  final String baseUrl;
  final http.Client _client;

  @override
  bool get recorded => false;

  static const _json = {'Content-Type': 'application/json', 'Accept': 'application/json'};

  Future<Map<String, dynamic>> _send(String method, String path, [Object? body]) async {
    final req = http.Request(method, Uri.parse('$baseUrl$path'))..headers.addAll(_json);
    if (body != null) req.body = jsonEncode(body);
    final res = await http.Response.fromStream(await _client.send(req)).timeout(const Duration(seconds: 30));
    if (res.statusCode != 200) {
      throw PlanSourceException.fromResponse(res.statusCode, res.body, res.headers['x-request-id']);
    }
    return jsonDecode(utf8.decode(res.bodyBytes));
  }

  @override
  Stream<RunUpdate> run(PlanRequest request) async* {
    final req = http.Request('POST', Uri.parse('$baseUrl/v1/plan/stream'))
      ..headers.addAll({'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
      ..body = jsonEncode(request.toJson());
    final res = await _client.send(req).timeout(const Duration(seconds: 30));
    if (res.statusCode != 200) {
      final body = await res.stream.bytesToString();
      throw PlanSourceException.fromResponse(res.statusCode, body, res.headers['x-request-id']);
    }
    String? event;
    final data = StringBuffer();
    final lines = res.stream.transform(utf8.decoder).transform(const LineSplitter())
        // The gateway gives up at 120 s; allow for the proxy hop.
        .timeout(const Duration(seconds: 130));
    await for (final line in lines) {
      if (line.startsWith('event: ')) {
        event = line.substring(7);
      } else if (line.startsWith('data: ')) {
        data.write(line.substring(6));
      } else if (line.isEmpty && event != null) {
        final payload = jsonDecode(data.toString()) as Map<String, dynamic>;
        switch (event) {
          case 'agent':
            yield RunEvent(AgentEvent.fromJson(payload));
          case 'plan':
            yield RunDone(PlanResponse.fromJson(payload));
            return;
          case 'error':
            throw PlanSourceException(500, payload['code'] ?? 'run_failed', payload['message'] ?? 'Run failed',
                payload['request_id']);
        }
        event = null;
        data.clear();
      }
    }
    throw PlanSourceException(502, 'stream_ended', 'The run stream ended before the plan arrived.');
  }

  @override
  Future<AskResponse> ask(AskRequest request) async =>
      AskResponse.fromJson(await _send('POST', '/v1/ask', request.toJson()));

  @override
  Future<ReviewState> review(String planRequestId) async =>
      ReviewState.fromJson(await _send('GET', '/v1/reviews/$planRequestId'));

  @override
  Future<ReviewState> act(String planRequestId, ReviewAction action) async =>
      ReviewState.fromJson(await _send('POST', '/v1/reviews/$planRequestId/actions', action.toJson()));

  @override
  Future<List<Tract>> tracts(String countyFips) async =>
      parseTracts(await _send('GET', '/v1/tracts/$countyFips'));
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
