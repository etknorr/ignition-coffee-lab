# Roastery: Artisan Style Roast Console for Ignition 2027 Maker

A Perspective roast console for a FreshRoast SR800, modeled on
Artisan (the open source roasting software) and built with Ignition
2027 Maker Edition. V4 (current) is a professional UX rebuild
around the phone-as-remote-control pattern; see the v4 section of
docs/coffee-roaster-app.md for the full design record.

This is the Ignition side of the Ignition Coffee Lab. The SR800
temperature feed arrives over WebSocket (in the real setup, from the
Pico W monitor elsewhere in this repository), and this console is
where the roast is run, logged, and reviewed. Everything in this
folder is configuration and the scripts that generate it: the
Perspective project, the tag and UDT setup, and the view builder.

## Quick start

1. Have an Ignition 2027 gateway commissioned as Maker Edition
   (this build used 2027.2.0-beta1).
2. Create an API key through the gateway webpage and save it as
   `apitoken-2027-maker.txt` next to the scripts (format and two
   setup gotchas are in [Standing it up](#standing-it-up)).
3. Have Postgres running and create the batch tables: from
   `scripts/`, run `setup_roastery_db.py` (connection details
   come from its environment variables).
4. From `scripts/`, run `setup_maker_stack.py`, then
   `setup_roastery_v4_tags.py` (v4 tag model; the v3 and v2 tag
   scripts are kept for history). Set the gateway's Gateway
   Scripting Project to Roastery.
5. Either copy `project/Roastery` into the gateway at
   `data/projects/` and scan projects, or regenerate it with
   `build_roastery_v4.py`. Open the Roastery client.

## What it does

- App shell: a bottom tab bar (Roast, Settings, Log) as a shared
  docked view on every page; on mobile only, a sticky top HUD
  (bean temp, RoR, clock, state, phase) and a pinned control dock
  with the primary event flow and the Fan and Heat steppers. The
  Roast page uses a breakpoint container: trend first on desktop
  (chart hero plus a control rail), control first on the phone.
- Live roast curve (classic XY chart; the 2027 canvas line chart
  has no markLine support and drew dual axis history incorrectly
  on this beta) plotted against elapsed roast time (mm:ss,
  Artisan style): the bean temperature line and the rate of rise
  line are built by the library from the recorded curve samples
  (never a wall clock tag history query), with a dashed target
  profile from four editable target points, an optional
  background (ghost) roast, and labeled vertical marker lines at
  every stamped event (one named series per event over a
  column-per-event dataset built by the library).
- The full Artisan event set: Charge, Dry End, First Crack Start
  and End, Second Crack Start and End, and Drop, each stamping
  elapsed time and bean temperature, plus four custom event
  buttons whose names are set in the config popup.
- Phases bar with drying, Maillard, and development segments that
  fill in as events land, and the development time ratio (DTR)
  computed at Drop.
- Fan and Heat as SR800 style level steppers (1 to 9). Every
  change is logged with elapsed time and temperature and drawn
  as a step trace strip under the main curve, the way Artisan
  annotates control moves.
- A Settings page (the old Configure tab) with every setting in
  labeled, extensible sections: Roaster (source, WebSocket,
  MQTT), Targets including the phase bar target durations and
  the DTR target, the Artisan rate of rise parameters, Alarms,
  Metadata defaults (the ia.input.form metadata form over the
  current batch tags), and Custom Events. Settings write live
  tags and take effect during a roast.
- A Log tab with full database CRUD for previous batches.
  Batches live in Postgres and are reached only through named
  queries defined in the project (no embedded SQL anywhere):
  relational columns for listing and sorting, the complete
  batch document in a JSONB column, the roast curve in a
  separate series table keyed by batch number, and one
  batch_events row per control button press (the audit trail).
  Tapping a batch opens its detail (curve, events timeline,
  phases and DTR, metadata, captured presses); Edit opens a
  slide over panel (a right docked view, not a popup) whose form
  also edits event times and temps, with the library
  recomputing phases, DTR, total time and roast degree from the
  edited times and rejecting out-of-order times with a visible
  message. Any past roast can be set as the ghost overlay, and
  New Roast zeroes the workspace with the next batch number.
- Transport flexible temperature feed: nested source UDTs
  (simulated OPC, WebSocket, MQTT) under the batch with an
  ActiveSource selector; the console, history, and batch save
  read one canonical temperature tag regardless of which
  transport is live.
- A deviation tile showing live bean temperature minus the
  target curve temperature at the current elapsed time.
- Lite alarms surfaced as a banner on the main view.
- A neutral theme that follows the session dark or light mode.
- The header clock follows the timer rule: it counts up from
  Charge while roasting and its zero is set at Drop (a SINCE
  DROP post drop clock from then on).

## Design: one probe, derived rate of rise

The SR800 setup has a single bean temperature probe. There is no
drum or environmental probe, and the UDT models exactly that: one
`BeanTempF` member fed by the probe. Rate of rise is not a probe.
It is calculated by one library implementation
(`roastery.core.compute_ror_series`), an Artisan 5.0.0
parameterization built from the Artisan source: delta span
(default 20 s), curve filter, delta filter, optional polyfit
least squares and optimal smoothing, median spike filtering on
the offline path, and RoR clipping. The live `RateOfRiseF`, the
saved batch RoR and the ghost RoR all come from that one
function over stored temps, so they always agree; the parameters
live in Settings and apply live. (The v2/v3 EMA over
`RoRSmoothingSec` is superseded; the tag remains but is unread.)
Verified against the simulator's exact 25 F/min ramp in
`verify_roastery_ror.py`: the calculated RoR converges to 25
under the defaults, under a short span with no smoothing, at
5 s sampling, and under polyfit, and a +30 F spike is bounded
with Smooth Spikes on.

There is deliberately no PID anywhere in this design. The SR800
is run on manual Fan and Heat levels, so the console exposes
those levels and nothing else.

## Repository layout

- `project/Roastery/`: the Perspective project exactly as it
  runs on the Maker gateway (project.json, page config with the
  shared docks, the 22 views: RoastPage, SettingsPage, LogPage,
  BatchDetail, TabBar, HudBar, ControlDock, SettingsRoaster,
  SettingsTargets, SettingsRor, SettingsAlarms, SettingsMetadata,
  SettingsCustoms, BatchesPanel, BatchEdit, Tile, EventCell,
  EventsStrip, PhasesBar, Controls, MetaCard, Summary, the
  `roastery` scripting library, the ten named queries under
  `ignition/named-query/Roastery/`, and the Perspective style
  classes plus the advanced stylesheet). All application
  Python lives in the project library (packages `roastery.core`
  and `roastery.batches`); view and tag scripts are one line
  calls into it. Styling is organized as `roast-` style classes
  with the advanced stylesheet holding only global rules.
- `scripts/`: the Python that builds and reproduces the
  environment.
  - `api27m.py`: small helper for the gateway REST API. It reads
    the API token from a local `apitoken-2027-maker.txt` file
    (never committed; see below) and is imported by the other
    scripts.
  - `setup_maker_stack.py`: creates the shared stack the app
    depends on: the CoreHistorian provider and the Programmable
    Device Simulator devices with their programs.
  - `setup_roastery_artisan_tags.py`: creates the RoastBatch
    UDT (81 members) and the `Roastery/CurrentBatch` instance,
    including history on the probe tags and the RoR derivation
    event script.
  - `build_roastery_v4.py`: generates the whole v4 project:
    views, the `roastery` script library, the named queries,
    the style classes, the advanced stylesheet, and the page
    config (shared tab bar and HUD docks, the editor dock). On a
    fresh gateway you can equally copy `project/Roastery` into
    the gateway and scan it; see below. (The v2 and v3 builders
    are kept for history.)
  - `setup_roastery_v4_tags.py`: creates the v4 tag model: the
    RoastBatch UDT with the source abstraction (ActiveSource
    plus nested RoasterSource instances), the capture and RoR
    parameter members, history for the probe tags on the SQL
    historian, and the thin BeanTempF event script that calls
    the library.
  - `setup_roastery_db.py`: idempotent DDL for the Postgres
    batches, batch_series and batch_events tables.
  - `verify_roastery_v4.py`: the live session click test for
    the v4 flows (a full roast driven from the phone layout
    while a desktop session watches, save, Log detail, slide
    over edit with recompute proof, ghost, New Roast, Settings
    phase target, dark theme, log scan).
  - `verify_roastery_ror.py`: the RoR proof (see above).
  - `verify_roastery_v3.py`: the live session click test for
    the v3 flows (roast, save to the database, Batches page
    CRUD, background from a database batch).
  - `validate_roastery_artisan.py`: checks that the served
    views match the authored files, starts every view in a live
    session, and scans the gateway log for project warnings.
  - `screenshot_roastery_artisan.py`,
    `screenshot_roastery_artisan_verify.py`, and
    `screenshot_roastery_artisan_verify2.py`: Playwright click
    tests used to prove the interactions in the lab.
- `docs/coffee-roaster-app.md`: the full build note, including
  the Artisan feature mapping (implemented, adapted, and
  excluded, with reasons) grounded in the Artisan 5.0.0 source,
  the popup and navigation action shapes proven on 2027, and
  the beta quirks found along the way.

## Configuration

The batch UDT carries the app's configuration, editable from
the Roast Setup popup:

- `WsUrl`: the WebSocket endpoint the probe feed comes from
  (default `ws://sr800.local:8080`, a placeholder for the real
  Pico feed address).
- `RoRSmoothingSec`: the rate of rise smoothing time constant
  in seconds (default 30).
- Target points (charge, dry end, first crack, drop, each a
  time and a temperature) that generate the dashed target curve
  and drive the deviation tile.
- Alarm thresholds for the banner alarms.

## Development

The project is generated code. Edit `build_roastery_v3.py`,
run it, rescan projects on the gateway, and re-run
`validate_roastery_artisan.py` and `verify_roastery_v3.py`.
The tag model lives in `setup_roastery_v3_tags.py` and is
applied through the gateway REST API, and the database schema
lives in `setup_roastery_db.py`, so a fresh environment
reaches the same state by running the scripts in order.
Project files under `project/Roastery/` are the builder's
output, committed so the project can be installed by copying,
without running the builder.

## Standing it up

1. Install Ignition 2027 (this build used 2027.2.0-beta1) and
   commission it as Maker Edition, or point the scripts at an
   existing 2027 gateway. In the lab the Maker gateway was a
   direct install commissioned on first boot with
   `IGNITION_EDITION=maker`.
2. Create an API key through the gateway webpage: Platform,
   Security, API Keys, add a Basic Token named `claude-lab`.
   Two gotchas from the lab notes: a new key defaults to
   requiring a secure channel (it returns 401 over plain HTTP
   until that is unchecked), and the key level gets 403 until
   it is granted under Security, General Settings, Roles and
   Permissions.
3. Save the token in the three line labeled format the helper
   expects, as `apitoken-2027-maker.txt` next to the scripts
   (or set the `APITOKEN_FILE` environment variable). The file
   is gitignored and must never be committed. Format:

   ```
   key name: claude-lab
   token: <the secret from the gateway>
   header: X-Ignition-API-Token: claude-lab:<the secret>
   ```

4. Create the data stack, from `scripts/`:
   `python3 setup_maker_stack.py`, then
   `python3 setup_roastery_artisan_tags.py`.
5. Install the project: copy `project/Roastery` into the
   gateway at `data/projects/Roastery`, then ask the gateway
   to scan for it (POST `/data/api/v1/scan/projects` with the
   API token).
6. Open the Perspective client for the Roastery project. Note
   that Maker Edition opens every session behind a Personal
   Use Only agreement modal; click AGREE & CLOSE to reach the
   console.
7. Optionally run `validate_roastery_artisan.py` and the
   screenshot verify scripts to reproduce the lab proof.

## Gateway configuration

The gateway configuration this app depends on (historian,
database connection, devices) and its two deployment modes,
local Docker and production Kubernetes, live in the `gateway/`
folder at the root of this repository.

## Honest lab notes

- In the lab there is no physical SR800 attached. A
  Programmable Device Simulator device (RoasterSim) stands in
  for the WebSocket probe feed, and the SR800 CONNECTED pill
  on the console reads the probe tag quality. The app treats
  the feed exactly as it will treat the real WebSocket feed.
- The gateway runs in trial mode until a free Maker license
  key from an Inductive Automation account is applied.
  Everything above works in trial.
- Test roasts in the batch history from the lab verification
  were short click-through roasts (about 15 to 20 seconds)
  used to prove the event, phase, save, edit, delete, and
  background flows; their computed statistics are not
  meaningful roast data. The seven oldest rows were migrated
  from the v2 dataset tag log and renumbered 1042 to 1048.
- Tag history runs on the SQL historian (Postgres). On this
  beta the SQL historian sink is not idempotent across gateway
  restarts when its tables already exist; the recovery is in
  the build note in `docs/`.
