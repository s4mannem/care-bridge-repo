import 'package:flutter/material.dart';

/// Palette shared by the map and the panels.
abstract final class Palette {
  static const ink = Color(0xFF1B2430);
  static const muted = Color(0xFF5B6675);
  static const line = Color(0xFFDDE2E8);
  static const surface = Color(0xFFF6F7F9);
  static const reject = Color(0xFFC62828);
  static const warn = Color(0xFFB26A00);
  static const pass = Color(0xFF2E7D32);
  static const accent = Color(0xFF00695C);

  /// Sequential need ramp, low → high.
  static const need = [
    Color(0xFFF1F7F6),
    Color(0xFFC9E4DF),
    Color(0xFF8CC7BC),
    Color(0xFF3F9E8F),
    Color(0xFF0F6B5F),
  ];

  static Color forNeed(double? score) {
    if (score == null) return const Color(0xFFE6E8EB);
    final i = (score * need.length).floor().clamp(0, need.length - 1);
    return need[i];
  }
}

class AgentInfo {
  const AgentInfo(this.name, this.icon, this.color);
  final String name;
  final IconData icon;
  final Color color;
}

const agents = <String, AgentInfo>{
  'coordinator': AgentInfo('Coordinator', Icons.hub_outlined, Color(0xFF455A64)),
  'health_access': AgentInfo('Health & Access', Icons.local_hospital_outlined, Color(0xFF00796B)),
  'transit_community': AgentInfo('Transit & Community', Icons.directions_bus_outlined, Color(0xFF6D4C41)),
  'evidence_validator': AgentInfo('Evidence Validator', Icons.fact_check_outlined, Color(0xFF5E35B1)),
  'siting_planner': AgentInfo('Siting Planner', Icons.place_outlined, Color(0xFF1565C0)),
  'optimizer': AgentInfo('Four-Stop Optimizer (tool)', Icons.functions, Color(0xFF0277BD)),
  'equity_auditor': AgentInfo('Equity & Rigor Auditor', Icons.gavel_outlined, Color(0xFFAD1457)),
  'communications': AgentInfo('Communications', Icons.campaign_outlined, Color(0xFFEF6C00)),
};

AgentInfo agentInfo(String id) =>
    agents[id] ?? AgentInfo(id, Icons.smart_toy_outlined, Palette.muted);

/// Plan 00 `SpatialGrain` values → badge label, meaning, color.
const _grains = <String, (String, String, Color)>{
  'census_tract_11char': ('TRACT', 'Census tract (~4,000 people)', Color(0xFF00695C)),
  'epa_12km_grid_on_tract_id': ('12 KM GRID', '12 km modeling grid wearing a tract ID', Color(0xFF8D6E63)),
  'facility_lon_lat_point': ('FACILITY', 'A single facility point; distances are upper bounds', Color(0xFF1565C0)),
  'hrsa_mixed_grain_component': ('SHORTAGE AREA', 'HRSA designation of mixed grain', Color(0xFF6A1B9A)),
  'multi_county_health_service_area': ('HSA REGION', 'Multi-county Health Service Area on a county key', Color(0xFFC62828)),
};

/// Says which grain a claim came from. Accepts a bare `SpatialGrain` value or
/// a `spatial_grain_disclosures` entry ("census_tract_11char: …").
class ScaleBadge extends StatelessWidget {
  const ScaleBadge(this.grain, {super.key});
  final String grain;

  static bool knows(String text) => _grains.containsKey(text.split(':').first.trim());

  @override
  Widget build(BuildContext context) {
    final g = _grains[grain.split(':').first.trim()] ?? ('OTHER', grain, Palette.muted);
    return Tooltip(message: g.$2, child: _Chip(text: g.$1, color: g.$3));
  }
}

class VerdictChip extends StatelessWidget {
  const VerdictChip(this.verdict, {super.key});
  final String verdict;

  @override
  Widget build(BuildContext context) {
    final c = switch (verdict) {
      'PASS' || 'approved' || 'provisional_approved' => Palette.pass,
      'WARN' || 'needs_human_review' => Palette.warn,
      _ => Palette.reject,
    };
    return _Chip(text: verdict.toUpperCase().replaceAll('_', ' '), color: c);
  }
}

/// Measured (survey/computed) vs modeled (a prediction for people like these).
class SourceBadge extends StatelessWidget {
  const SourceBadge({super.key, required this.measured, this.source});
  final bool measured;
  final String? source;

  @override
  Widget build(BuildContext context) => Tooltip(
        message: source ?? (measured ? 'Measured or computed' : 'Modeled estimate'),
        child: _Chip(
          text: measured ? 'MEASURED' : 'MODELED',
          color: measured ? const Color(0xFF37474F) : const Color(0xFF7B1FA2),
          outlined: !measured,
        ),
      );
}

class _Chip extends StatelessWidget {
  const _Chip({required this.text, required this.color, this.outlined = false});
  final String text;
  final Color color;
  final bool outlined;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: outlined ? Colors.transparent : color.withValues(alpha: 0.1),
          border: Border.all(color: color.withValues(alpha: outlined ? 0.8 : 0.35)),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.4, color: color)),
      );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(children: [
          Expanded(
            child: Text(text.toUpperCase(),
                style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.8,
                    color: Palette.muted)),
          ),
          if (trailing != null) trailing!,
        ]),
      );
}

String saturdayLabel(DateTime d) {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return 'Sat ${months[d.month - 1]} ${d.day}';
}

String fmtInt(int n) => n.toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
