import 'package:flutter/material.dart';

import '../models.dart';
import 'common.dart';
import 'side_panels.dart';

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
              _StateHelp(),
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
          _P('Each tab unlocks when the run reaches the agent that writes it. Until then it shows a lock and '
              'says what it is waiting for.'),
          _Sub('1 · Four Saturdays'),
          _P('One card per stop, numbered 1 to 4. While a run plays, you see the draft on screen. When the run '
              'ends, the cards are the final plan.'),
          _Term('Need score',
              'The big number at the top right, from 0 to 1. Higher means more need. The strategy you picked '
              'decides how much each part counts.'),
          _Term('Score parts',
              'The bars show the parts behind the score: uninsured adults, distance to a safety-net clinic, no '
              'vehicle, chronic and respiratory illness, and no routine checkup. Each is scaled from 0 to 1.'),
          _Row(badge: SourceBadge(measured: true),
              text: 'Only safety-net distance is measured. It is a straight-line distance from the tract to the '
                  'nearest clinic.'),
          _Row(badge: SourceBadge(measured: false),
              text: 'The other parts are modeled estimates, mostly from CDC PLACES. Use them to rank tracts, not '
                  'to count people.'),
          _Term('Reach',
              'The line under the reason gives the residents and tracts inside the stop\'s catchment circle.'),
          _Term('Sources and grain',
              'Tap to open. Each line has a scale badge and says what that number describes, followed by the '
              'datasets it came from.'),
          _Term('PROVISIONAL · host unconfirmed',
              'No one has confirmed a venue for this stop yet. Hover or long-press the tag for the warning. '
              'Treat the stop as a proposal until a host agrees.'),
          _Term('Planner note',
              'A blue box above the cards. The planner uses it to explain a choice, such as how it fixed a '
              'rejected draft.'),
          _Term('Review card',
              'Appears above the cards only when the finished plan needs a person to sign off. See "Human '
              'review" below.'),
          _P('A red banner means the auditor rejected the draft on screen. An orange banner means the equity '
              'check flagged groups for review in tab 3.'),
          _Sub('2 · Why not here?'),
          _P('The high-need tracts the four stops don\'t reach. The orange number is the tract\'s need rank in '
              'the county.'),
          _Term('Reason',
              'Why the planner left it out: already inside a stop\'s catchment, too close to another stop, no '
              'Saturday transit or venue, or less need reached than the chosen stops.'),
          _Term('Distance', 'Straight-line kilometers to the nearest chosen stop.'),
          _Term('Technical note',
              'The planner\'s reason, with its sources. It is written for you, not for residents.'),
          _Term('Resident note',
              'The shaded box below. Communications wrote it in plain words for people who ask why their '
              'neighborhood wasn\'t picked.'),
          _Term('English / Español',
              'Switches every resident note on this tab. The copy button copies the note in the language shown.'),
          _P('Use these notes when a resident, partner or council office asks. Check the nearest stop\'s date '
              'is right before you send one.'),
          _Sub('3 · Equity & rigor audit'),
          _Term('Verdict',
              'The auditor\'s decision on the last draft it checked: APPROVED, REJECTED REVISION REQUIRED, or '
              'NEEDS HUMAN REVIEW.'),
          _Term('Draft 0 vs final',
              'Shown only when the auditor rejected the first draft. Changed stops are red in draft 0 and green '
              'in the final plan. The reason for the rejection is listed underneath.'),
          _Term('Open defects', 'Problems the auditor found and the revision did not fix, with a suggested fix.'),
          _Term('Sensitivity',
              'The optimizer reruns the plan with each weight moved 15% up or down, one at a time. Jaccard '
              'measures how many of the four tracts stay the same.'),
          _P('A Jaccard of 1.00 means the same four tracts every time. Green means 0.80 or higher. Orange means '
              'small weight changes swap stops. Borderline tracts are the ones that move in or out.'),
          _Row(
            badge: Icon(Icons.shield_outlined, color: Color(0xFFAD1457), size: 20),
            text: 'The demographic comparison is auditor-only. It runs after the plan is drafted, using census '
                'race, ethnicity and language data the planner never receives.',
          ),
          _P('It compares each group\'s share inside the catchments with its share county-wide. Parity is the '
              'ratio of the two. 1.00 means the plan reaches the group in proportion.'),
          _P('A group below parity 0.80 is flagged and referred to a person for review. These findings are never '
              'sent back to the planner, so the planner never sees race or ethnicity.'),
          _Sub('4 · Flyers & data limits'),
          _Term('Flyers',
              'One bus-stop flyer per stop, in English or Spanish. Communications writes them from the final plan '
              'only. Use the copy button to paste one into your own template.'),
          _Term('Draft banner',
              'The orange line at the top. Flyers are drafts for internal review. Don\'t publish them until the '
              'plan is approved and venues are confirmed.'),
          _Term('Regional note',
              'The line under the flyers describes illness trends for a multi-county region, not any one '
              'neighborhood.'),
          _Term('What this plan cannot tell you',
              'The limits attached to this plan. Read them before you share the plan with partners.'),
          _Term('Evidence validator',
              'The checks run on the data before planning. PASS means the check held. WARN means it held with a '
              'caveat. "(note)" marks a check that informs but doesn\'t gate the run.'),
          _Term('Data availability',
              'One chip per dataset. A green tick means it was used. A grey cross means it was missing, and the '
              'plan says so instead of guessing.'),
          _Term('Provenance', 'The line at the bottom lists the data sources behind this plan.'),
        ],
      );
}

class _StateHelp extends StatelessWidget {
  const _StateHelp();

  @override
  Widget build(BuildContext context) => _Section(
        icon: Icons.data_object,
        title: 'The session.state drawer',
        children: [
          const _P('Press session.state (State on a phone) at the top right to open it. It shows how the agents '
              'hand work to each other.'),
          const _P('Each box is one key in the shared state. Each key has exactly one agent that writes it. The '
              'arrow points to the agents that read it.'),
          const _P('A key says "written" and turns teal once its writer has saved it during the run. Until then '
              'it says "empty". Replay fills the keys in the same order.'),
          for (final (key, writer, readers) in StateInspector.keys)
            _Term(key, 'Written by ${_name(writer)}. Read by ${readers.map(_name).join(', ')}.'),
          const _P('audit_report is never read by the planner. The only thing that goes back to the planner is '
              'non_demographic_feedback, such as two stops overlapping.'),
        ],
      );

  static String _name(String id) => agentInfo(id).name.replaceAll(' (tool)', '');
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
          _P('Ask is a conversation. Ask in your own words, follow up ("and the second stop?"), or say what you '
              'want planned, such as "focus on households without a car" or "show the auditor catching an overlap". '
              'Each answer names the agent whose data it rests on and the scale of that data.'),
          _P('When you ask for a plan, or ask something that needs one, the reply shows the request it would run: '
              'strategy, overlap demo and optional datasets. Nothing runs until you press Generate plan, and the '
              'request form changes to match. The county and the four Saturdays stay as shown. A question asked '
              'before there is a plan is answered once the plan is ready.'),
          _P('Some things it won\'t do. The planner is race-blind, so Ask can\'t set up a plan aimed at a group of '
              'people. It reports who the stops reach after the audit, and it never calls a plan fair or unfair; '
              'that is your call. Nothing here counts sick people or doctor visits, so a question like "who isn\'t '
              'being seen?" gets the closest neighborhood-level signals: modeled illness, missed checkups and '
              'distance to a safety-net clinic.'),
          _P('In the offline recorded version, Ask plans from keywords and answers with the closest suggested '
              'question, saying which one.'),
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
          _P('The review card appears at the top of tab 1 only when the finished plan is marked as needing human '
              'review. Not every plan gets one.'),
          _P('The card lists each stop with its date, tract and venue status. Its title shows where the review '
              'stands, starting at "Awaiting human review".'),
          _Term('Confirm venue',
              'Type the place that agreed to host the van, such as a library or church lot. The stop turns '
              'green. Change venue lets you edit it later.'),
          _Term('Reject stop (×)',
              'Drop a stop you can\'t use. It is crossed out and no longer needs a venue. The plan is not '
              'redrawn.'),
          _Term('Approve plan',
              'Sign off on the plan as a whole. If some kept stops still lack a venue, the card says so.'),
          _Term('Request changes', 'Send the plan back instead of approving it.'),
          _Term('Reopen', 'Undo an approval or a request for changes, so you can decide again.'),
          _P('Every action is saved in the Review log at the bottom of the card, with the reviewer\'s role and '
              'the time.'),
          _Row(
            badge: Icon(Icons.campaign, color: Palette.pass, size: 20),
            text: '"Approved: ready to announce" needs an approved plan and a confirmed venue for every stop you '
                'kept. Until then, don\'t publish the flyers.',
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

/// A small heading inside a section.
class _Sub extends StatelessWidget {
  const _Sub(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 6),
        child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: Palette.ink)),
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
