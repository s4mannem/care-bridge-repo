import 'package:http/http.dart' as http;

/// iOS, Android, desktop: dart:io streams responses as they arrive.
http.Client createStreamingClient() => http.Client();
