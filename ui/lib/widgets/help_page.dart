import 'package:flutter/material.dart';

import '../models.dart';
import 'common.dart';

/// How to use the Mobile Care Planner, written for a county outreach lead rather
/// than a developer. Badges, agent icons and map marks reuse the real widgets
/// and colors so they look the same here as in the app.
class HelpPage extends StatelessWidget {
  const HelpPage({super.key});

  static Future<void> open(BuildContext context) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const HelpPage()));

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.white,
        appBar: AppBar(
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.white,
          title: const Text('How to use CareBridge', style: TextStyle(fontWeight: FontWeight.w800)),
          bottom: const PreferredSize(preferredSize: Size.fromHeight(1), child: Divider(height: 1)),
        ),
        body: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 48), children: const [
              _Purpose(),
              _RequestForm(),
              _ReadingTheMap(),
              _PlanTabsHelp(),
              _AgentsHelp(),
              _RunHelp(),
              _AskHelp(),
              _ReviewHelp(),
              _BadgesHelp(),
              _LimitsHelp(),
            ]),
          ),
        ),
      );
}

// ── Sections ────────────────────────────────────────────────────────────────

class _Purpose extends StatelessWidget {
  const _Purpose();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.airport_shuttle_outlined,
        title: 'What CareBridge is for',
        children: [
          _P('CareBridge helps you choose where one mobile-clinic van should park on four Saturdays. '
              'It looks for neighborhoods (census tracts) with high need and poor access to care, picks four '
              'stops that don\'t overlap, and explains each choice in plain terms.'),
          _P('A team of AI agents does the work: some gather evidence, one plans, one audits the plan, and one '
              'writes flyers. You stay in charge. Nothing is ready to announce until a person reviews it.'),
          _Bullets([
            'Wide screen: request form on the left, map and plan in the middle, agents on the right.',
            'Phone: use the bottom bar to switch between Plan, Agents and Request.',
          ]),
        ],
      );
}

class _RequestForm extends StatelessWidget {
  const _RequestForm();

  @override
  Widget build(BuildContext context) => _Section(
        icon: Icons.tune,
        title: 'Making a request',
        children: [
          const _P('The form is set to Fulton County, one van, four Saturdays. Choose what "needs the van" '
              'means, then press Generate plan.'),
          for (final s in Strategy.values) _Term(s.label, s.description),
          const SizedBox(height: 8),
          const _Term('Simulate draft-0 defect',
              'A demo switch. It makes the planner\'s first draft put two stops too close together, so you can '
              'watch the auditor reject it and the planner fix it. Turn it off to see a normal run.'),
          const _Term('Include optional datasets',
              'Adds Saturday MARTA service, USDA food access and library venues when they are available. '
              'If one is missing, the plan says so instead of guessing.'),
        ],
      );
}

class _ReadingTheMap extends StatelessWidget {
  const _ReadingTheMap();

  @override
  Widget build(BuildContext context) => _Section(
        icon: Icons.map_outlined,
        title: 'Reading the map',
        children: [
          _Legend(
            swatch: Row(mainAxisSize: MainAxisSize.min, children: [
              for (final c in Palette.need) Container(width: 9, height: 14, color: c),
            ]),
            text: 'Green shading is need under the strategy you picked. Darker means higher need compared with '
                'the rest of the county.',
          ),
          const _Legend(
            swatch: Row(mainAxisSize: MainAxisSize.min, children: [
              _Dot(6, Color(0xFF1565C0)),
              SizedBox(width: 3),
              _Dot(12, Color(0xFF1565C0)),
              SizedBox(width: 3),
              _Dot(7, Color(0xFF90A4AE)),
            ]),
            text: 'Blue dots are safety-net clinics that see uninsured patients. Bigger dot = more open hours per '
                'week. Grey dots are hospitals that aren\'t safety-net sites.',
          ),
          const _Legend(
            swatch: _Ring(),
            text: 'Numbered pins are the four stops. The faint circle around each is its catchment: the area '
                'the stop is meant to serve. Hollow pins are still waiting for the auditor; filled teal pins '
                'have passed. Tap a pin to highlight its card.',
          ),
          const _Legend(
            swatch: _RejectedPair(),
            text: 'A red line joins two stops after the auditor rejects a draft: they are so close that their '
                'catchments overlap and two Saturdays would serve the same people.',
          ),
          const _Legend(
            swatch: _GhostPin(),
            text: 'After the revision, the dropped stop stays as a grey × with a dashed line to the stop that '
                'replaced it, so you can see what changed.',
          ),
          const _Legend(
            swatch: _UnreachedTag(),
            text: 'Orange outlines are high-need tracts the van won\'t reach with these four stops. The tag shows '
                'the tract\'s need rank. Tab 2 explains why each one was passed over.',
          ),
          const _P('The tag at the top left of the map says which draft you are looking at and what the auditor '
              'decided about it.'),
        ],
      );
}

class _PlanTabsHelp extends StatelessWidget {
  const _PlanTabsHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.view_agenda_outlined,
        title: 'The four plan tabs',
        children: [
          _Term('1 · Four Saturdays',
              'One card per stop: the date, the tract, its need score, the pieces of that score, a short reason '
              'and roughly how many residents live within reach. "PROVISIONAL · host unconfirmed" means no '
              'venue has been booked yet. Open "Sources and grain" to see where each number came from.'),
          _Term('2 · Why not here?',
              'The highest-need tracts that none of the four stops reach, with the reason and a ready-to-copy '
              'note (English or Spanish) for residents who ask why their neighborhood wasn\'t picked.'),
          _Term('3 · Equity & rigor audit',
              'The auditor\'s findings: first draft versus final, any open problems, how stable the choice is if '
              'the weights shift a little, and a check of who the plan reaches compared with the county.'),
          _Term('4 · Flyers & data limits',
              'Bus-stop flyers in English and Spanish, written from the final plan only, plus the plan\'s data '
              'limits, the validator\'s checks and which datasets were available.'),
        ],
      );
}

class _AgentsHelp extends StatelessWidget {
  const _AgentsHelp();

  static const _what = <String, String>{
    'coordinator': 'Runs the team in order and enforces the rules. Never edits a plan.',
    'health_access': 'Gathers need, insurance and distance-to-care figures for each tract.',
    'transit_community': 'Adds Saturday bus service and possible host venues when that data exists.',
    'evidence_validator': 'Checks the evidence before planning starts and blocks claims it can\'t support.',
    'siting_planner': 'Picks the four stops and writes the reasons. It never sees race or ethnicity.',
    'optimizer': 'A fixed calculator the planner uses to score tracts and keep stops from overlapping.',
    'equity_auditor': 'Challenges the draft and can reject it. Only it sees race and ethnicity data.',
    'communications': 'Writes the flyers and "why not here" notes from the final plan.',
  };

  @override
  Widget build(BuildContext context) => _Section(
        icon: Icons.account_tree_outlined,
        title: 'The Agents panel',
        children: [
          const _P('Each box is one agent. It lights up while it works and turns red if the auditor rejects a '
              'draft. Tap a box to see what that agent may and may never see.'),
          for (final e in _what.entries) _AgentRow(id: e.key, text: e.value),
          const SizedBox(height: 8),
          const _Term('The plan ⇄ audit loop',
              'The planner drafts, the auditor checks. If the auditor finds a fixable problem, such as two stops '
              'overlapping, it sends the planner a note and the planner revises once. The note never mentions '
              'race or ethnicity: the auditor uses that data only to flag who the plan reaches, for a person to '
              'review.'),
        ],
      );
}

class _RunHelp extends StatelessWidget {
  const _RunHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.timeline,
        title: 'The Run timeline and Replay',
        children: [
          _P('The Run tab lists each step as it happens, with the agent, the time and what it did. A rejection '
              'shows as a red row, followed by "REVISION 1 OF MAX 1" and the planner\'s new draft.'),
          _Bullets([
            'Replay (↻) plays a finished run again at its recorded pace, and the map and tabs follow along.',
            'Skip (⏭) jumps straight to the result.',
            'The 1x menu changes the replay speed.',
            'On a phone, these controls sit just under the map.',
          ]),
        ],
      );
}

class _AskHelp extends StatelessWidget {
  const _AskHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.forum_outlined,
        title: 'Ask',
        children: [
          _P('After a plan is made, ask questions about it in the Ask tab. Tap a suggested question to start, '
              'such as "Who does this plan reach?" or "Why didn\'t we pick the tract with the highest need?", or '
              'type your own. Each answer names the agent that answered and the scale of the data behind it.'),
          _Row(badge: VerdictChip('CANNOT SAY'), text: 'The agents won\'t claim more than the data supports. '
              'Ask about one street, one person, or a trend the data doesn\'t measure and you\'ll get CANNOT SAY '
              'with what it can tell you instead, for example about the wider region.'),
        ],
      );
}

class _ReviewHelp extends StatelessWidget {
  const _ReviewHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.how_to_reg_outlined,
        title: 'Human review',
        children: [
          _P('When a plan needs a person to sign off, a review card appears at the top of tab 1.'),
          _Term('Confirm venue', 'Enter the place that agreed to host the van, such as a library or church lot.'),
          _Term('Reject stop (×)', 'Drop a stop you can\'t use. It is crossed out.'),
          _Term('Approve plan', 'Sign off on the plan. Request changes sends it back; Reopen undoes a decision.'),
          _Row(
            badge: Icon(Icons.campaign, color: Palette.pass, size: 20),
            text: '"Approved: ready to announce" shows only once the plan is approved and every stop you kept '
                'has a confirmed venue. Until then, don\'t publish the flyers.',
          ),
        ],
      );
}

class _BadgesHelp extends StatelessWidget {
  const _BadgesHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.label_outline,
        title: 'Scale and source badges',
        children: [
          _P('Every number comes from data collected at some scale. The badge tells you which, so you know how '
              'local the claim really is. Hover or long-press a badge in the app for a reminder.'),
          _Row(badge: ScaleBadge('census_tract_11char'),
              text: 'A census tract, about 4,000 people. The most local data the app has.'),
          _Row(badge: ScaleBadge('epa_12km_grid_on_tract_id'),
              text: 'A 12 km modeling grid square. It carries a tract ID but describes a much larger area.'),
          _Row(badge: ScaleBadge('multi_county_health_service_area'),
              text: 'A multi-county health region. True of the region, not of any one neighborhood.'),
          _Row(badge: ScaleBadge('facility_lon_lat_point'),
              text: 'A single clinic or hospital location. Distances are straight-line, so real trips are longer.'),
          SizedBox(height: 8),
          _Row(badge: SourceBadge(measured: true),
              text: 'Counted or calculated directly, for example the distance to the nearest safety-net clinic.'),
          _Row(badge: SourceBadge(measured: false),
              text: 'An estimate for people like those who live there, from a statistical model. Useful for '
                  'ranking, not a head count.'),
        ],
      );
}

class _LimitsHelp extends StatelessWidget {
  const _LimitsHelp();

  @override
  Widget build(BuildContext context) => const _Section(
        icon: Icons.info_outline,
        title: 'What the data can\'t tell you',
        children: [
          _Bullets([
            'Which street or block needs the van most. The smallest unit is a census tract.',
            'How long the trip takes. Distances are straight lines, not bus or walking time.',
            'Whether a venue is available. Every stop is provisional until you confirm a host.',
            'Exact counts of uninsured or sick people. Several figures are modeled estimates.',
            'Whether illness is rising in one neighborhood. Some data is regional or a few years old.',
            'How many people will show up on the day.',
          ]),
          _P('Tab 4 lists the specific limits attached to each plan. When in doubt, check with partners who know '
              'the neighborhood.'),
        ],
      );
}

// ── Building blocks ─────────────────────────────────────────────────────────

class _Section extends StatelessWidget {
  const _Section({required this.icon, required this.title, required this.children});
  final IconData icon;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 28),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(icon, color: Palette.accent, size: 22),
            const SizedBox(width: 10),
            Expanded(
              child: Text(title,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Palette.ink)),
            ),
          ]),
          const SizedBox(height: 10),
          ...children,
        ]),
      );
}

const _body = TextStyle(fontSize: 14, height: 1.5, color: Palette.ink);

class _P extends StatelessWidget {
  const _P(this.text);
  final String text;

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(text, style: _body));
}

class _Bullets extends StatelessWidget {
  const _Bullets(this.items);
  final List<String> items;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final i in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('•  ', style: _body),
                Expanded(child: Text(i, style: _body)),
              ]),
            ),
        ]),
      );
}

/// A bold term followed by its explanation.
class _Term extends StatelessWidget {
  const _Term(this.term, this.text);
  final String term;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text.rich(TextSpan(style: _body, children: [
          TextSpan(text: '$term  ', style: const TextStyle(fontWeight: FontWeight.w700)),
          TextSpan(text: text),
        ])),
      );
}

/// A badge or icon in a fixed-width column, with its explanation beside it.
class _Row extends StatelessWidget {
  const _Row({required this.badge, required this.text});
  final Widget badge;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 104,
            child: Align(
                alignment: Alignment.topLeft,
                child: Padding(padding: const EdgeInsets.only(top: 2), child: badge)),
          ),
          Expanded(child: Text(text, style: _body)),
        ]),
      );
}

class _AgentRow extends StatelessWidget {
  const _AgentRow({required this.id, required this.text});
  final String id;
  final String text;

  @override
  Widget build(BuildContext context) {
    final a = agentInfo(id);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.all(5),
          decoration: BoxDecoration(
            color: a.color.withValues(alpha: 0.1),
            border: Border.all(color: a.color.withValues(alpha: 0.5)),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Icon(a.icon, size: 16, color: a.color),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text.rich(TextSpan(style: _body, children: [
            TextSpan(text: '${a.name.replaceAll(' (tool)', '')}  ',
                style: TextStyle(fontWeight: FontWeight.w700, color: a.color)),
            TextSpan(text: text),
          ])),
        ),
      ]),
    );
  }
}

/// A map mark drawn in a fixed box, with its meaning beside it.
class _Legend extends StatelessWidget {
  const _Legend({required this.swatch, required this.text});
  final Widget swatch;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 72,
            height: 36,
            margin: const EdgeInsets.only(right: 12),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Palette.surface,
              border: Border.all(color: Palette.line),
              borderRadius: BorderRadius.circular(6),
            ),
            child: swatch,
          ),
          Expanded(child: Text(text, style: _body)),
        ]),
      );
}

class _Dot extends StatelessWidget {
  const _Dot(this.size, this.color);
  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle, border: Border.all(color: Colors.white)),
      );
}

/// Same look as the map's stop pins.
class _Pin extends StatelessWidget {
  const _Pin(this.label, this.color, {this.hollow = false});
  final String label;
  final Color color;
  final bool hollow;

  @override
  Widget build(BuildContext context) => Container(
        width: 22,
        height: 22,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: hollow ? Colors.white : color,
          shape: BoxShape.circle,
          border: Border.all(color: hollow ? color : Colors.white, width: 2),
        ),
        child: Text(label,
            style: TextStyle(color: hollow ? color : Colors.white, fontWeight: FontWeight.w800, fontSize: 11)),
      );
}

class _Ring extends StatelessWidget {
  const _Ring();

  @override
  Widget build(BuildContext context) => Container(
        width: 32,
        height: 32,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: Palette.accent.withValues(alpha: 0.08),
          shape: BoxShape.circle,
          border: Border.all(color: Palette.accent.withValues(alpha: 0.6), width: 1.2),
        ),
        child: const _Pin('1', Palette.accent),
      );
}

class _RejectedPair extends StatelessWidget {
  const _RejectedPair();

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 60,
        height: 24,
        child: Stack(alignment: Alignment.center, children: [
          Container(height: 3, margin: const EdgeInsets.symmetric(horizontal: 10), color: Palette.reject),
          const Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            _Pin('2', Palette.reject),
            _Pin('3', Palette.reject),
          ]),
        ]),
      );
}

class _GhostPin extends StatelessWidget {
  const _GhostPin();

  @override
  Widget build(BuildContext context) => const Row(mainAxisSize: MainAxisSize.min, children: [
        _Pin('×', Color(0xFF9E9E9E), hollow: true),
        _Dashes(),
        _Pin('3', Palette.accent),
      ]);
}

class _Dashes extends StatelessWidget {
  const _Dashes();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          for (var i = 0; i < 3; i++)
            Container(width: 4, height: 2, margin: const EdgeInsets.symmetric(horizontal: 1), color: Palette.ink),
        ]),
      );
}

class _UnreachedTag extends StatelessWidget {
  const _UnreachedTag();

  @override
  Widget build(BuildContext context) => Container(
        width: 52,
        height: 26,
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: Palette.warn, width: 2.5)),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
          decoration: BoxDecoration(
              color: Colors.white, border: Border.all(color: Palette.warn), borderRadius: BorderRadius.circular(10)),
          child: const Text('#7', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: Palette.warn)),
        ),
      );
}
