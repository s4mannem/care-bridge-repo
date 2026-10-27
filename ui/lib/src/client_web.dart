import 'package:fetch_client/fetch_client.dart';
import 'package:http/http.dart' as http;

/// Web: the default browser client buffers whole responses, which would hold
/// back server-sent events until the run ended. Fetch streams them.
http.Client createStreamingClient() => FetchClient(mode: RequestMode.cors);
