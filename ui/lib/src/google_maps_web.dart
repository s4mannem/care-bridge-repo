import 'dart:js_interop';
import 'dart:js_interop_unsafe';

/// True once /gmaps.js has loaded the Maps JavaScript API (nginx serves it only
/// when the deployment has a GOOGLE_MAPS_KEY).
bool get googleMapsLoaded => globalContext.has('google') && (globalContext['google'] as JSObject).has('maps');
