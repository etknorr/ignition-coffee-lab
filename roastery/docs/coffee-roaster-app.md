# Coffee roaster app (Roastery project, gateway-8.3.10)

Built 2026-11-11. Project "Roastery" on the 8.3.10 gateway: an artisan
coffee roasting console with a UDT-backed current batch, a simulator
driven roast curve, working Record and Stop script actions, and a
Settings popup with bidirectional bindings. Tooling:
setup_roastery_tags.py (device, UDT, instance), build_roastery.py
(project files), validate_roastery.py (session validation),
screenshot_roastery.py (playwright interaction proof). The Showcase
project is untouched and still validates.

## UDT via the tags API (route that worked)

The definition goes in as a bare UdtType JSON object through
POST /tags/import with params provider=default, type=json,
collisionPolicy=Abort, path=_types_. No wrapper folder. Shape:

    {"name": "RoastBatch", "tagType": "UdtType", "tags": [ ...members ]}

Member shapes that stuck:
- Memory scalars: {"name": "BeanName", "tagType": "AtomicTag",
  "dataType": "String", "valueSource": "memory", "value": "Ethiopia Guji"}.
  dataType uses the canonical enum names (Int4, Float8, String,
  DateTime, Boolean). "Double" is silently dropped to null.
- OPC members: valueSource "opc", opcServer "Ignition OPC UA Server",
  opcItemPath "[RoasterSim]BeanTemp". History rides on the member:
  historyEnabled true, historyProvider "CoreHistorian",
  historySampleRate 2, historySampleRateUnits "SEC",
  historicalDeadband 0.5 (history block shaped like the NorthPlant
  tags that already worked).

The instance is a root level import (no path param) of a folder object
whose tags array holds {"name": "CurrentBatch",
"tagType": "UdtInstance", "typeId": "RoastBatch"}. Importing at
path=Roastery with a folder named Roastery in the body would have
created Roastery/Roastery; the path parameter already roots the
import. Verify with GET /tags/export (recursive, includeUdts): the
definition appears under _types_ and the instance resolves all member
names. Instance path: [default]Roastery/CurrentBatch.

Members (13): BatchNumber (Int4, 1042), BeanName, Origin,
ChargeWeightLb (22.0), TargetDropTempF (415.0), State ("Idle"),
StartTime (DateTime, null), ElapsedSeconds (Int4, 0), BeanTempF,
RateOfRise, DrumTempF (OPC to RoasterSim; history on the first two),
GasPercent (50.0), AirflowPercent (40.0).

## Resources POST bodies are JSON arrays

POST /resources/<moduleId>/<typeId> takes a JSON ARRAY of resource
objects. A bare object returns 400 "Not a JSON Array". The RoasterSim
device was created that way (module com.inductiveautomation.opcua,
type device, profile ProgrammableSimulatorDevice, 1000 ms rate,
repeat on). The create response does not carry a usable signature:
GET /resources/find/<moduleId>/<typeId>/<name> afterwards and read
"signature" from that, then PUT the instructions.csv datafile with
?signature=<signature> (the PUT returns a newSignature).

## Simulator CSV and the ramp direction verdict

    TimeInterval,BrowsePath,ValueSource,DataType
    0,BeanTemp,"ramp(200,385,150,true)",Double
    150,BeanTemp,"ramp(385,435,450,true)",Double
    600,BeanTemp,"ramp(385,435,450,true)",Double
    0,RateOfRise,"ramp(30,6,600,true)",Double
    600,RateOfRise,"ramp(30,6,600,true)",Double
    0,DrumTemp,"ramp(225,415,150,true)",Double
    150,DrumTemp,"ramp(415,458,450,true)",Double
    600,DrumTemp,"ramp(415,458,450,true)",Double

ValueSource strings must be quoted (they contain commas). A row's
interval is when that source takes over for its path; the cycle length
is the highest interval, so pad with a duplicate row at 600.

Verdict: ramp(min, max, period, repeat) with min greater than max DOES
descend linearly from min to max. Proven numerically in a live
session: when BeanTemp read 332.2 (segment 1 progress 0.715, interval
about 107), RateOfRise read 25.7, exactly 30 - 24*107/600, and
DrumTemp read 360.8 at the same 0.715 progress of its own segment 1.
All paths share one program clock. No staircase fallback was needed.
The result is a roast-like curve: fast climb 200 to 385 F, slow climb
to 435 F, reset at 600 s, with rate of rise falling 30 to 6 F/min.

## Event and action JSON, proven by clicks

Component events hang at component.events.dom.onClick as a single
action object.

Script action (scope "G"), body lines tab indented (the runtime wraps
the body in a function). Record writes State and StartTime with
system.tag.writeBlocking; Stop reads StartTime with
system.tag.readBlocking, computes whole seconds from
start.getTime(), and writes State "Stopped" plus ElapsedSeconds.
Verified end to end: gateway tag export after the click test showed
State "Stopped", ElapsedSeconds 7, StartTime set, matching the frozen
00:07 on screen.

Popup actions on Ignition 8.3, per the Perspective manual (Popup
Views in the Ignition User Manual, Perspective section): a
component event gets a Popup action (Open, Close, or Toggle) and a
target view, or a script calls system.perspective.openPopup /
closePopup / togglePopup. Vision material is not a reference for
any of this and is ignored. In view JSON the action type is
"popup". The bundled jar example projects predate this format and
use action identifiers the 8.3.10 client does not register at all
(browser console: Client Action "openPopup" not registered,
domAction won't be registered), so example projects are a lead to
verify against the current manual, never ground truth. Working
shapes, proven by clicks:

Open:
    {"scope": "C", "type": "popup", "config": {
      "type": "open", "id": "roastery-settings",
      "viewPath": "Views/Settings", "title": "Batch Settings",
      "modal": true, "showCloseIcon": true, "draggable": true,
      "resizable": true, "overlayDismiss": true,
      "position": {"width": 480, "height": 576}}}

Close:
    {"scope": "C", "type": "popup", "config": {
      "type": "close", "id": "roastery-settings"}}

Traps, each proven by a collapsed 115x40 title-bar-only popup:
- The view key is "viewPath", not "view". With "view", the popup
  opens with an empty body and no error anywhere.
- Geometry comes from "position" {width, height} (numbers, px), not
  from "style" width and height. Without position, the popup sizes
  to its (empty) content.
- The close icon flag is "showCloseIcon", not "closeIcon" (the
  string closeIcon does not exist in the 8.3.10 client bundle).

How this was pinned down: a throwaway PopupProbe project reproduced
the failure outside an embedded view, then the served client bundle
(/res/perspective/js/PerspectiveClient.*.js) was read directly. The
PopupAction factory switches on config.type ("open", "close",
"toggle"); ViewPopup destructures viewPath, viewParams, position,
showCloseIcon from the config; the base Popup copies position keys
into its style; the client's own login popup passes position
{left, top, width, height} and showCloseIcon. The bundle is the
reference of first resort when an action shape is unclear, ahead of
the jar examples, which are stale for 8.3.

## Elapsed timer expression

view.custom.elapsedText is a string formatted mm:ss by an expression
binding: while State is "Recording", format (now() minus StartTime);
while "Stopped", format the ElapsedSeconds tag; else "00:00".
Date subtraction in the expression language yields milliseconds, and
now() re-evaluates about once per second in a live session, so the
timer counts live (observed 00:02 then 00:07 five seconds apart) and
freezes on Stop. Format with numberFormat(floor(ms/60000), "00") and
numberFormat(floor((ms/1000) % 60), "00") joined by ":".

## Project loading and payload normalization

A project dropped into data/projects is NOT picked up automatically
(still 404 after two minutes of polling). POST /scan/projects (no
parameters) loads it within seconds. Same for later file edits.

The served payload normalization in validate_roastery.py extends the
Showcase rules: event action configs are stripped to nothing by the
serializer (actions arrive with scope and type only), and an empty
view level propConfig is served as null. Both must be normalized
before deep comparison or ControlPanel false-fails.

## Verification method

1. validate_roastery.py: served payload deep-equals files for all
   five views, live WebSocket session starts every view, zero
   Roastery warnings in the log window, bogus view control warns
   exactly once. Final result: VALIDATION PASS.
2. screenshot_roastery.py (playwright, real Chromium): loads the
   client, screenshots main, clicks Settings (popup screenshot),
   edits Bean Name to "Colombia Huila" through the popup field
   (the text field is .ia_popup input, first in DOM order; the
   placeholder prop is not rendered as an HTML attribute, so
   get_by_placeholder finds nothing), closes, confirms the batch
   card shows the new name, reopens and restores "Ethiopia Guji",
   clicks Record (pill turns red "Recording", elapsed counts),
   screenshots, clicks Stop (pill amber "Stopped", elapsed frozen).
   Every screenshot inspected visually.
3. Gateway side confirmation: tag export shows the persisted values
   the scripts and bindings wrote; the log holds no Roastery or
   script errors for the whole interaction window (only the known
   sandbox multicast noise).

End state after the proof: State "Stopped", ElapsedSeconds 7,
BeanName back to "Ethiopia Guji". Screenshots:
showcase/shots/roastery-main.png, roastery-settings.png,
roastery-recording.png, roastery-stopped.png.

## Artisan build (Maker 2027 gateway), verified 2026-11-12

The Roastery project on gateway-2027-maker is a full Artisan style
console modeled on Eric's FreshRoast SR800: one bean temp probe fed
over WebSocket, Fan and Heat levels as the only controls, Artisan's
event set, phases and DTR, full batch metadata, a roast log with
background roasts, and a target profile with a live deviation tile.
Builder: build_roastery_artisan.py (writes the project files, then
POST /scan/projects). Tag setup: setup_roastery_artisan_tags.py.
Views: Main, Config (the Roast Setup popup), Log (page /log), and
the embedded Tile, EventCell, EventsStrip, PhasesBar, Controls,
MetaCard, Summary. Verification: screenshot_roastery_artisan_verify.py
(roast flow) and screenshot_roastery_artisan_verify2.py (log page,
background, mobile); every check passed on the final build.

### UDT shape

RoastBatch v2 has 81 members and no DrumTempF. Groups: the probe
(BeanTempF, OPC on RoasterSim in the lab, history on), the derived
RateOfRiseF (history on), scratch members _RoRPrevTempF and
_RoRPrevMs, controls (FanLevel, HeatLevel 1..9, Mode), state
(State, StartTime), the seven Artisan events each as a DateTime
plus captured temp plus an elapsed-seconds shadow int (-1 means not
recorded; all phase math runs on the shadow ints, never on null
dates), 16 metadata members in grams, the target profile points
(TargetChargeTempF, TargetDryEndSec and TempF, TargetFCSec and
TempF, TargetDropSec; drop temp reuses TargetDropTempF), three lite
alarms with enable flags, config (WsUrl, RoRSmoothingSec), and four
custom events (name, kind, time, temp, elapsed). Roastery also
holds EventsLog and RoastLog dataset tags, TargetProfileDS and
BackgroundDS overlay datasets, BackgroundCurveJson, BackgroundLabel.

### Rate of rise derivation verdict

Derived for real, by a tag event script, not by the simulator. The
BeanTempF member carries a valueChanged event script (the UDT JSON
key is "eventScripts", each entry {"eventid": "valueChanged",
"script": ...}; the REST serializer silently drops the newer
"eventType" key form). The script keeps the previous sample in the
scratch members and writes an exponentially smoothed delta per
minute with tau = RoRSmoothingSec (default 30 s), with clamping and
a jump reset for simulator cycle wraps. Proof on the live gateway:
with RoasterSim ramping at exactly 25 F per minute, RateOfRiseF
read 24.2 rising to 24.5 across 15 s shortly after boot, converging
on the true slope exactly as the smoother should.

### Deviation tile

Deviation is a view expression: while State is Roasting, live
BeanTempF minus the target polyline interpolated piecewise linearly
at the elapsed seconds (charge to dry end to first crack to drop,
flat at drop temp after TargetDropSec), formatted with a sign. In
any other state it shows two dashes by design, which is why the
idle and summary screenshots read "--": that is correct behavior,
not a dead tile. Verified live at 4 s into a roast: bean 285.9 F,
target at 4 s is 201.7 F, tile read +84.1 F and a DOM text check in
the test suite asserts the tile carries a signed number while
Roasting.

### Navigation: navigate(page=...), never pageId

Both page buttons first shipped as
system.perspective.navigate(pageId='/log') and silently failed: the
gateway log shows IllegalArgumentException: Page "/log" not found,
because in the navigate signature pageId is the runtime generated
id of a running page instance, while the page URL path belongs in
the page argument. Correct forms, per the Perspective manual:
system.perspective.navigate(page='/log') and
system.perspective.navigate(page='/'). Fixed in the builder for the
header Roast Log button and the Log view's Back to Console and
View as Background flows, all click proven.

### Smaller fixes from the same verification pass

- The Roast Log table showed the Date column as raw epoch millis.
  The roastDate column now sets render "date" with dateFormat
  "YYYY-MM-DD h:mm a" (column schema: ia.display.table), and the
  column renders "2026-11-12 3:31 am" (gateway clock is UTC).
- The Config popup compressed and overlapped its sections at phone
  size: flex children shrank instead of the root scrolling. The
  builder now sets shrink 0 on every flex child in the Config view
  (a _no_shrink pass), so the root's overflowY auto scrolls. At
  390x844 the popup is 366 px wide, every section is legible, and a
  wheel scroll reaches the Close button, which closes the popup.
- Config popup values render faintly in the desktop screenshot;
  they are bound and round trip correctly (Farm edit and WeightOutG
  entry proven tag side). Cosmetic only.

### Responsive approach

Flex everywhere, no coordinate containers. Rows wrap on flex basis:
at 390 px the header stacks (title, batch chip and SR800 pill,
state pill, clock, Roast Log button), the curve and traces go full
width, the events grid wraps two across, tiles stack. Programmatic
check at 390x844: document scrollWidth equals 390, so there is no
horizontal overflow. Desktop evidence shots use a 1600x1680 viewport
scrolled to the top because the client scrolls internally and
Playwright full_page captures start mid page on this app. The
popup sizes with CSS min(): width min(700px, 94vw), height
min(880px, 94vh).

### WebSocket honesty note

There is no SR800 on this network. In the lab the probe feed is
RoasterSim over OPC standing in for the WebSocket feed, and the
BeanTempF member documentation says so. The app models the real
thing: WsUrl holds the endpoint (placeholder ws://sr800.local:8080),
the SR800 CONNECTED pill keys off the probe feed being live, and
the Config popup shows the live probe and RoR readout. Artisan
itself ships a WebSocket device port (wsport.py), so the model
matches how Eric's roaster actually talks.

### Artisan feature mapping

Grounded in the downloaded Artisan source at ~/workspace/artisan-src
(version 5.0.0, src/artisanlib: main.py, events.py,
roast_properties.py, alarms.py, background.py, designer.py,
batches.py, roastlog.py, statistics.py, calculator.py,
comparator.py, wheels.py, wsport.py, pid_dialogs.py).

| Artisan feature | Disposition | How / why |
| --- | --- | --- |
| Live curve: bean temp plus delta BT (RoR) | Implemented | XY chart on tag history; RoR derived by the tag event script above |
| Second probe (ET, drum) channels | Excluded | Eric's SR800 has one bean temp probe; there is nothing to bind a second channel to |
| Standard events: Charge, Dry End, FC Start, FC End, SC Start, SC End, Drop | Implemented | Buttons write time, captured temp, and elapsed shadow; events strip shows all seven plus the customs |
| Turning point auto detection | Implemented | Live detection in roastery.core._track_turning_point (running bean temp minimum after charge, confirmed on a 5 F rise); saved per batch, shown on BatchDetail, and the DRY phase RoR baseline (Artisan RoR()) |
| Four custom event buttons, user named and typed | Implemented | CustomEvent1..4 name and kind members, edited in the Config popup, stamped like standard events |
| Phases (drying, maillard, development) with times, ratios, DTR | Implemented | PhasesBar and Summary compute from the elapsed shadows; verified 6 s phases and 33.3% DTR on a click-through roast |
| AUC statistic | Implemented | Computed by the Save script and stored per log row; values on 18 s test roasts are not meaningful |
| Roast degree from drop temp | Implemented | Map expression to degree names (292 F read Cinnamon in tests) |
| Event sliders (fan, heat, air) | Adapted | SR800 levels are 1..9, so steppers replace 0..100 sliders; every change is timestamped into EventsLog and drawn in the Fan / Heat trace strip |
| Alarms (time, temp, event conditions with actions) | Adapted (lite) | AlarmDefsJson definitions with guard, condition and action (banner or toast via Periscope); no sounds, no external actions, no alarm driven control moves |
| Background profile | Implemented | Save stores the sampled curve with the log row; View as Background loads it as the Background series with a label chip |
| Profile designer | Adapted (lite) | Target is four editable points interpolated piecewise linearly, not a freehand curve editor; the deviation tile reads against it |
| Roast properties metadata | Implemented | 16 Artisan style fields in grams, bidirectional in the Config popup, shown on the MetaCard |
| Roast log and batch history | Implemented, adapted storage | RoastLog dataset tag plus the /log table page (row select, date rendering); .alog import on the Log page and export from BatchDetail; no PDF or HTML report export |
| Roast comparator (multi roast overlays) | Implemented | Multi-roast compare (build_compare, up to three batches A/B/C) with a paired phone instance (HUNT-54) and the picker fix (HUNT-55); curves overlay on elapsed time since charge, with the background overlay as the single-roast route |
| Calculators (loss, blend, moisture) | Adapted | Weight loss percent is computed in the Summary; blend and moisture calculators not reproduced |
| Flavor wheels and cupping profile | Excluded | Cupping is a post roast workflow, outside a roast time console; the Notes field is the capture point |
| Green bean stock and inventory | Excluded | Inventory is a separate system from roast time control and logging |
| Hardware PID output control (pid_dialogs.py) | Excluded | Eric confirmed on 2026-11-11 that his SR800 setup has no PID control and he is glad it is excluded. Manual Fan and Heat levels are his control surface, so the console exposes Fan and Heat steppers only, with no PID anywhere in the design. |
| Device connections incl. WebSocket (comm.py, wsport.py) | Adapted | Modeled by WsUrl plus the probe tag; the lab feed is the simulator, per the honesty note above |
| Sampling and RoR smoothing settings | Adapted | Full Artisan 5.0.0 parameterization in core.compute_ror_series: delta span, curve filter, delta filter, spike smoothing, polyfit, optimal smoothing; the v3 RoRSmoothingSec EMA is superseded and no longer read |
| Artisan simulator mode | Implemented in effect | RoasterSim drives the whole console in the lab, program: charge 392, turning point 184 at about 71 s, dry end zone 300 to 310 at about 4:37 to 5:00, FC 385 at about 8:54, drop 419 at 12:00 on a 1020 s cycle |

### End state

Maker gateway RUNNING on localhost:8088. Roastery validation PASS
(all ten views served deep equal, zero Roastery warnings in live
sessions, bogus view control warns) and ChartLab validation PASS on
the same gateway, untouched. Batch reset to Idle with default
metadata (Farm Buku Abel, WeightOutG 0, Fan 5, Heat 5, no
background loaded). The RoastLog keeps the saved test batches as
evidence. Screenshots: roastery-artisan-desktop.png,
roastery-artisan-roasting.png, roastery-artisan-summary.png,
roastery-artisan-config.png, roastery-artisan-alarm.png,
roastery-artisan-log.png, roastery-artisan-background.png,
roastery-artisan-mobile.png, roastery-artisan-config-mobile.png.

## Roastery v2: Form component, neutral themes, defect fixes

### The Form component (ia.input.form)

Batch Metadata in the Roast Setup popup is ONE ia.input.form
instance (MetaForm): 16 fields in 10 rows, and the widget ids are
the RoastBatch member names, so the submit payload maps straight
onto tag paths.

Props shape: `props.name` ('batchMetadata'), `props.columns`
holding items whose rows hold `widgets`, `props.actions` with
submit and cancel blocks, `props.data` (a flat object keyed by
widget id), and `props.validation`. Each widget carries an id, a
type, a label block, an info block (tooltip scaffolding), and a
full per-type config block under its type key, for example
`widget.number.validation.constraints`. The builder deepcopies
the schema example widget and edits it; a hand written minimal
widget object does not produce a working form. Widget types
used: text, number, text-area, and 'none' for the section header
row.

Validation lives per widget under `<type>.validation.constraints`:
required on BeanName, min and max on the numbers. Quirk: a number
widget's step constraint must be enabled (value 'any') or the
field only accepts integers.

Prefill: props.data carries no binding in this build. The Config
view's onStartup script reads the 16 member tags once with
system.tag.readBlocking, coerces the int and float members, and
assigns MetaForm.props.data as a flat dict.

Submit: actions.submit sets fireComponentEvent true and
fireSubmissionEvent false (no submission handler), so submitting
raises the component event onSubmitActionPerformed, and the event
object IS the payload, a dict of widget id to value. Quirk:
number widget values arrive as strings, so the handler coerces
per member (one int, five floats, the rest strings), skips
nulls, writes with system.tag.writeBlocking to
[default]Roastery/CurrentBatch/<member>, and sets
view.custom.formSaved, which a label shows as "Batch details
saved." Submit resetOn is 'success'. Cancel runs
onCancelActionPerformed, whose script closes the popup.

What is NOT in the form, and why: the Roaster section (WsUrl,
RoR smoothing, the live probe readout), the Target Profile
points, and the alarm rows stay regular controls with
bidirectional tag bindings, because they take effect immediately
and include live read-only values. The form's edit-then-submit
model fits batch metadata, a record you fill in and save. The
round trip is proven by clicks in both themes: prefill shows the
tag values, editing Farm and WeightOutG and pressing Save Batch
Details wrote both tags (confirmed by API read), and the
MetaCard updated on Main.

### Neutral dark and light themes

The v1 espresso palette is gone. Every style color in the views
is a CSS variable from the built-in session theme set:
var(--containerRoot), var(--container), var(--containerNested),
var(--border), var(--label), var(--neutral-60) and
var(--neutral-70), var(--input), var(--callToAction),
var(--success), and var(--boxShadow2). The same view files
therefore render under the built-in dark theme and the built-in
light theme. The only literal hexes left are chart series colors
(amCharts parses those itself and cannot read CSS variables) and
functional state colors on buttons and pills (record red, cool
blue, go green), chosen to read on both themes.

The console header carries a theme toggle that flips the session
theme. The v2 verification toggles the live session both ways
and asserts the computed --containerRoot (#FAFAFA light, #161616
dark), with screenshots in both themes at desktop and phone
widths. A grep over the generated view JSON for every v1 palette
value returns zero hits.

### Defects found in the first v2 pass, and their fixes

1. Chart ERROR bar. Symptom: a red ERROR bar under the Roast
   Curve and an error badge on the chart itself. Root cause was
   data, not the view: the tag [default]Roastery/BackgroundDS
   held a corrupt value, a
   com.inductiveautomation.ignition.common.document.Document
   object instead of a Dataset, so the chart's
   props.dataSources.bg binding carried quality error
   -1073741052, "Invalid DataType for Dataset", in the live
   session (captured from the session property feed). The
   corrupt value came from a test script writing a dataset
   through the REST /tags/write endpoint with a raw JSON object
   as the value; on this beta the API stores that as a Document
   and poisons the dataset tag. In-app writes never do this: the
   setup seeds datasets as JSON strings, and every runtime write
   uses gateway Jython system.dataset.toDataSet. Fix: the value
   was rewritten by the app's own Charge and Reset scripts
   (proper Datasets), and the verify script no longer writes
   datasets through the API; it clears the background by running
   Charge then Reset after emptying BackgroundCurveJson. Lab
   rule: never write a dataset value through /tags/write as a
   JSON object.
2. EventCell error badges. Symptom: a micro error badge in the
   middle of every event name label. Clicking a badge showed the
   diagnostic: Property root/NameLabel.style.color,
   Error_Configuration, "Unable to create map transform: Unable
   to create new Color Mapping Element." Root cause: the
   done-state color binding was a property binding with a map
   transform whose color outputs were the v2 CSS variable
   strings, var(--callToAction) and var(--neutral-60). The
   client validates map outputs when constructing the transform
   and cannot build a color mapping element from a var() string.
   In v1 the outputs were literal hexes, so it worked. The other
   two map transforms in the app (the State and Mode pills)
   still use hex outputs and were unaffected. Fix, in
   build_roastery_artisan.py: the binding is now an expression,
   if({view.params.done}, 'var(--callToAction)',
   'var(--neutral-60)'), whose result is applied to the style as
   CSS, where var() resolves per theme. Proven by computed style
   in live sessions: waiting rgb(161, 161, 161) in dark, done
   rgb(34, 154, 214) in dark and rgb(12, 123, 179) in light,
   with zero quality overlays anywhere.

### Verification and end state (v2 finish pass)

verify_roastery_v2.py reports ALL CHECKS PASS: both themes both
ways, zero quality overlays at idle and while roasting in both
themes and on mobile, the roast flow (Charge, Dry End, FC Start,
fan stepper with a logged trace row, Drop), the form round trip
in dark and prefill in light, the log page and background
selection with the clean ASCII label, reset to clean idle, the
background dataset empty and readable, and the mobile popup fit.
validate_roastery_artisan.py PASS (ten views served deep equal,
zero Roastery warnings, bogus view control warns) and ChartLab
validation PASS on the same gateway. Screenshots:
roastery-v2-dark-desktop.png, roastery-v2-light-desktop.png,
roastery-v2-dark-config.png, roastery-v2-light-config.png,
roastery-v2-dark-mobile.png, roastery-v2-light-mobile.png (lab
showcase/shots only; the repo stays config only). Maker gateway
RUNNING, batch at clean Idle (Farm Buku Abel, WeightOutG 0,
Fan 5, Heat 5, background cleared).

## Roastery v3: database CRUD, scripting library, style classes (Maker 2027 gateway, verified 2026-11-12)

V3 is an architecture pass. The console behavior from v2 is
unchanged; what changed is where the data lives, where the code
lives, and how styling is organized.

### Previous batches: Postgres via named queries only

The RoastLog dataset tag is no longer the store (the tag still
exists and is unused by the app; see Seed below). Previous
batches live in Postgres, reached only through named queries
defined in the project. No binding or script contains embedded
SQL; the only SQL in the project is inside the named query
resources.

Tables (DDL in scripts/setup_roastery_db.py, idempotent):

- batches: id BIGSERIAL primary key, batch_number INTEGER
  UNIQUE (the human batch number, e.g. 1042), roast_start and
  roast_end TIMESTAMPTZ, bean_name TEXT, drop_temp_f DOUBLE,
  data JSONB, created_at and updated_at. The relational columns
  are only what the Batches page lists, sorts, and filters on.
  Everything else about the batch (the full 16 field metadata
  set, event times and temps, phase durations, DTR, AUC, weight
  loss, roast degree, target profile, fan and heat trace) lives
  in the data JSONB document, so the batch schema can evolve
  without migrations. The scripting library assembles and
  disassembles the document.
- batch_series: one row per curve sample, batch_number foreign
  key to batches (ON DELETE CASCADE), t_offset_sec, sample_ts,
  bean_temp_f, rate_of_rise_f, fan_level, heat_level. Written at
  save time from the samples the app records during the roast,
  so every batch carries its own curve, like an Artisan roast
  file.

Named queries (folder Roastery in the project):

- Roastery/Batches/SelectAll: newest first; returns the
  relational columns plus the JSONB extractions the table
  displays (origin, charge weight, weight out, DTR, roast
  degree, total seconds).
- Roastery/Batches/SelectById: one batch with its document.
- Roastery/Batches/Insert and Update: write the relational
  columns and CAST(:data AS jsonb) for the document.
- Roastery/Batches/Delete: deletes the batch; its series rows
  cascade in Postgres.
- Roastery/Series/InsertBatch: bulk insert of one batch's
  samples; the library passes a JSON array parameter and the
  query unpacks it with jsonb_array_elements.
- Roastery/Series/SelectByBatch: the curve for one batch.

Background route (settled design): View as Background reads the
selected batch's rows through Series/SelectByBatch, stages them
in the BackgroundCurveJson tag, and the library shapes the
overlay dataset on the current roast's timeline. No historian
dependency for backgrounds.

Batches page: page /batches is a thin shell (header plus an
embed) around the reusable Views/BatchesPanel, which holds the
table (a named query binding to SelectAll), row selection,
Edit, Delete with a confirm step, View as Background, and New
Batch. Edit and New Batch open Views/BatchEdit as a popup: the
proven ia.input.form pattern, 17 fields (the 16 metadata fields
plus BatchNumber in create mode), prefilled from SelectById by
a library function, submitted through a thin handler that calls
the library, which coerces values and writes via Update or
Insert. After a popup save, the library sends the session
message roastery-batches-refresh; the panel's message handler
re-runs the table binding. The panel is built as an embedded
view so the coming tabbed shell (Roast, Configure, Log) can
reuse it as the Log tab.

Seed: the seven test batches that were in the old RoastLog
dataset tag were migrated into the batches table by
roastery.batches.seed_from_roastlog(). All seven were saves of
the same accelerated v2 click test under batch number 1042, so
they were renumbered chronologically to 1042 through 1048 (the
documents carry seededFromRoastLog and originalBatchNumber).
Their curves were converted into batch_series rows (RoR by
finite difference, fan and heat null; the old log did not
record them).

### Historian: SQL historian on the db connection

Tag history for BeanTempF and RateOfRiseF now points at the SQL
historian provider named db (Postgres), not CoreHistorian. The
CoreHistorian provider stays defined but unused.

Beta trap, verified twice: the SQL historian sink
initialization is not idempotent. If the sqlth_* tables already
exist when the sink initializes (for example after a gateway
restart), sink creation fails with "relation already exists",
the sink faults, and no history is stored. Recovery, proven in
the lab: drop the sqlth_* tables, then PUT the database
connection resource back to bounce the connection; the sink
recreates its schema (including the monthly data partitions)
and resumes storing. The docs carry this because a plain
gateway restart will hit it.

### Scripting library: the roastery package

All application Python lives in the project scripting library,
package roastery, two modules:

- roastery.core: the BeanTempF valueChanged logic (RoR
  derivation with exponential smoothing and the 50 F jump
  reseed), curve sampling into the CurveSamples dataset while
  roasting, event stamping (standard and custom), charge, drop,
  cool, finish, reset, the fan and heat stepper, target and
  background overlay building, the config form data and submit
  (including coercion, and mirroring the WebSocket URL into the
  selected source), Main startup, and the theme toggle.
- roastery.batches: batch document assembly and disassembly,
  save_current_batch (Insert plus Series/InsertBatch), the
  SelectById read, edit form prefill and submit (edit and
  create), delete with confirm state, table selection and
  refresh, View as Background, and the RoastLog seed migration.

The Gateway Scripting Project is set to Roastery, so tag event
scripts can import the library; the BeanTempF event script is
the one line call roastery.core.on_bean_temp(...). Every
component handler, view startup script, and form handler in the
views is a one line library call or a single framework call
(navigate, closePopup). Startup scripts that prefill a form are
one assignment of a library call result to the form's data
property.

Traps found while building this:

- Named query resources are version 2: query.sql plus a
  resource.json whose attributes are typed JSON. Parameter
  types use the ParameterType constant "Parameter" (there is
  no "Value"); omit cacheUnit entirely (the deserializer calls
  TimeUnits.valueOf on it and "SECONDS" throws). Parameter
  data types are the DataType ints (Int4=2, Float8=5, String=7,
  DateTime=8, Text=10). Update queries return the update count;
  a Query type INSERT ... RETURNING id returns the id as a
  dataset. The jsonb document cell comes back from SelectById
  as a unicode JSON string; system.util.jsonDecode parses it.
- A script library package has no code.py at its root; modules
  are subfolders with their own code.py and resource.json. A
  root code.py makes the subpackages unimportable.
- The gatewayScriptingProject system property key is lowercase
  g; the PascalCase spelling is silently dropped.
- A database connection password secret stored by reference is
  created through the encryption endpoint: POST the raw
  plaintext to /data/api/v1/encryption/encrypt and store the
  returned JWE as a nested JSON object in the secret config.
  Storing the JWE as a string fails ("Not a JSON Object"). The
  SecretConfig.Type values are only Embedded and Referenced.
- Component message handlers live on a component's top level
  "scripts" key as messageHandlers entries (messageType,
  script, sessionScope, pageScope, viewScope). The served
  project payload strips component scripts (and binding
  configs), so served-versus-authored comparisons must
  normalize them away; the handlers are verified functionally
  instead (the create and edit saves visibly refresh the
  table through the message).
- system.perspective.openPopup takes its options as one
  positional dict (title, modal, showCloseIcon, overlayDismiss,
  viewportBound, position); keyword arguments do not work.
  self.view.root is not a valid path in component scripts;
  resolve components with getChild from the view or the panel
  root, and note getChild returns None rather than raising
  when the child is not found.
- Dataset tags created over REST (and zero row datasets built
  with system.dataset.toDataSet) get String typed columns, so
  every cell round trips as text ('0.0', timestamps as
  'yyyy-MM-dd HH:mm:ss.SSS' strings). The library builds empty
  datasets from a typed seed row that is then deleted, so the
  columns keep real types (Double, Date, Integer), replaces an
  empty dataset on first append (healing a legacy string typed
  value), and coerces numeric and timestamp cells on read
  regardless. Never write a dataset tag value through the REST
  tags/write endpoint as a JSON object; it stores a Document
  and poisons the tag. A JSON string of the dataset works.
- Perspective tables are virtualized divs, not table elements.
  A row click must land on the cell content div; clicking the
  row container does nothing, and Playwright hit testing
  reports ancestors as intercepting even when the layout is
  fine. Batch numbers render with a thousands separator
  (2,001), which text based test selectors must expect.
- An embedded view whose flex position is grow 1 with basis
  0px collapses to zero height inside a content sized parent;
  Main's embeds and the Batches shell use basis auto and size
  to their content.

### Style classes and the advanced stylesheet

Styling is organized as 63 Perspective style classes in the
project (roast- prefix: roast-app, roast-content, roast-card
and roast-card-sm, roast-header, roast-title and
roast-title-sm, roast-section-title, roast-caption, roast-value
family, roast-clock, roast-chip, roast-pill and roast-mode-pill,
roast-banner, roast-note family, roast-btn with the size and
color variants roast-btn-sm, roast-btn-ghost, roast-btn-primary,
roast-btn-green, roast-btn-purple, roast-btn-event,
roast-btn-charge, roast-btn-blue, roast-btn-sc, roast-btn-drop,
roast-btn-cool, roast-btn-reset and roast-btn-step, roast-input,
roast-checkbox, roast-table and roast-table-header, the phase
segment classes roast-seg with roast-seg-drying,
roast-seg-maillard, roast-seg-development and roast-seg-text,
roast-event-name, roast-event-time and roast-event-time,
roast-form-caption, roast-section-div, roast-scroll,
roast-status, roast-alarm-cap, roast-accent-bar and
roast-accent-text, roast-stepper-value, roast-unit, roast-full,
and the roast-gap-8 through roast-gap-14 spacing helpers),
applied uniformly through style.classes. The advanced
stylesheet holds only what classes cannot reach: hover and
active brightness on .psc-roast-btn, the focus outline on
.psc-roast-input, and scrollbar styling on .psc-roast-scroll
(DOM selectors need the .psc- prefix). Colors stay on the v2
neutral palette of built in CSS variables, so both session
themes work; there is no brown.

Remaining inline styles are data driven values a class cannot
express, each bound, not static: the state and mode pill
background colors (expression and map results), the alarm
banner and delete confirm row display toggles, the phase
segment widths, the event name color, the tile accent bar color
(a view parameter), the config status label color, the two XY
charts' transparent backgroundColor (a chart property), and the
form component's own internal widget styles.

### Roaster source abstraction

The temperature feed is transport flexible. The RoastBatch UDT
gained two things (the 81 v2 members are unchanged in name and
type; the only member change is BeanTempF's value source):

- ActiveSource, a String memory member ('Simulated',
  'WebSocket', 'Mqtt'), editable from the Roast Setup popup.
- Sources, a folder of nested RoasterSource UDT instances, one
  per transport. RoasterSource has Kind, BeanTempF, Address,
  WsUrl, BrokerUrl, Topic, and Connected members. Simulated's
  BeanTempF is the RoasterSim OPC tag; WebSocket and Mqtt have
  memory BeanTempF slots with their addresses in place
  (WsUrl ws://sr800.local:8080; BrokerUrl mqtt://localhost:1883
  and Topic roastery/sr800/temp).

The canonical CurrentBatch/BeanTempF is now an expression tag
that selects the active source instance's BeanTempF, so Main,
history, the RoR derivation, and the batch save never know
which transport is live. How a transport gets populated: an
engine (the Pico WebSocket client, or an MQTT bridge through
the Cirrus Link modules or a library client; neither is built
in this pass) writes the live temperature into that source
instance's BeanTempF member slot, and the console follows when
ActiveSource names it. Switching was verified live: with
ActiveSource set to WebSocket the canonical tag read the
WebSocket slot value, and switching back restored the simulator
value.

### Feature checks (informational, nothing built on them)

Event Streams: yes, included and functional in Maker
2027.2.0-beta1. The EventStream module is installed; the
project resource type is (com.inductiveautomation.eventstream,
event-streams); a probe stream in a scratch project reached
state RUNNING with the ignition.supplied source and the
ignition.logger handler. Beta source ids: ignition.supplied,
ignition.tagEvent, ignition.file, ignition.gatewayEvent,
ignition.lastEvent, ignition.sparkplugB. Handler ids:
ignition.logger, ignition.tag, ignition.script, ignition.http,
ignition.gatewayEvent, ignition.gatewayMessage, plus a
database handler class. Encoders: ignition.jsonObject,
ignition.string, ignition.byteArray, ignition.pyDictionary,
ignition.passThrough. A null handler config faults the handler
stage (a config gap, not a license block). The settled design
stays named queries plus the library; event streams are a
roadmap option only.

SQLBridge transaction groups: the SQL Bridge module is
installed and runs on Maker; the per project runner starts and
transaction groups are project resources of type
(com.inductiveautomation.sqlbridge, transaction-groups) with a
JSON config (group type keys standard, block, historical). The
gateway watches the type and loads groups live, and exposes a
diagnostics route at /services/transaction-groups. Hand
authoring a valid group config JSON by reverse engineering did
not succeed in three attempts (all failures were format
errors, never license or trial errors), so groups are
creatable through the Designer, which is the normal authoring
route. Eric's direction is to use transaction groups for the
data logging in the next UX pass; nothing in v3 builds on
them.

### Lab infrastructure

Postgres 16 runs on the lab VM as a system cluster on
localhost:5432, database db, user ignition; the lab password
lives only in the lab notes file, never in this repository
(the repo gateway config keeps the referenced secret form).
Restart after a VM reboot: pg_ctlcluster 16 main start. The
gateway database connection named db mirrors the repo gateway
config with host localhost, status VALID, and the SQL historian
provider named db is created from the same config.

### Verification and end state (v3)

verify_roastery_v3.py reports ALL 45 CHECKS PASS in a live
session: both themes, style classes present in the rendered
DOM, SQL historian receiving BeanTempF history, a short roast
(Charge, Dry End, FC Start, fan stepper, Drop), curve samples
recorded, the config form round trip, Finish and Save Batch
writing the batch row, its JSONB document, and 4 series rows;
the Batches page listing the batch; edit through the popup
(Farm and WeightOut changed, persisted, and shown again on
reopen through SelectById); a scratch batch created through
the popup, listed after the refresh message, then deleted with
confirm and gone from both the database and the table;
background set from the database batch with its overlay rows;
reset to clean Idle; and the mobile pass with no horizontal
overflow and no quality overlays anywhere.
validate_roastery_artisan.py PASS (twelve views served deep
equal, library and all seven named queries present, 63 style
classes and the stylesheet on disk, zero Roastery warnings in
the validation window) and ChartLab validation PASS on the same
gateway. Screenshots: roastery-v3-dark-desktop.png,
roastery-v3-light-desktop.png, roastery-v3-batches.png,
roastery-v3-batch-edit.png, roastery-v3-dark-mobile.png, and
roastery-v3-background.png (lab showcase/shots only). One
cosmetic beta artifact: the BatchEdit popup chrome renders the
openPopup options dict as a text strip above the popup in this
beta; the popup itself is correct. Maker gateway RUNNING,
batch at clean Idle, Postgres running with the batches table
holding the seven seeded batches plus the click test batch
2001 (8 rows).

## V4: professional UX rebuild (2026-11-12)

V4 reshapes the app around how it is actually used: the phone is
the remote control (buttons are clicked from the phone while the
roast is watched on the desktop's big screen). Both are live
sessions on the same tags, so the work is genuinely different
responsive arrangements of the same workspace, not sync.

### Shell and docks

Page config (written by the builder into the project's
page-config):

- sharedDocks.bottom = Views/TabBar on every page: Roast,
  Settings, Log tabs plus the theme toggle. The theme toggle sits
  at the left end so the Maker session status nub in the client's
  bottom right corner can never cover it.
- sharedDocks.top = Views/HudBar: state pill, bean temp, RoR,
  clock, phase. It is a fixed cover dock; the advanced stylesheet
  hides top docks at desktop widths (@media (min-width: 900px)
  .docked-view-top { display: none }) and pads page roots below
  it on mobile (@media (max-width: 899.98px) .psc-roast-app
  { padding-top: 62px }), so the HUD exists on mobile only and
  stays visible while the page scrolls under it.
- The Roast page's mobile control dock is NOT a page dock:
  Perspective stacks one dock per edge and the bottom edge
  already carries the tab bar. It is Views/ControlDock pinned at
  the bottom of the small breakpoint layout, directly above the
  tab bar: the primary flow (Charge, Dry End, FC Start, Drop)
  plus the Fan and Heat steppers, all 52px targets, reachable
  without scrolling.
- The Log pages carry a right dock (id 'batchEditor') holding
  Views/BatchEdit, the slide over editor (below).

Docked view config format (from the perspective-common model
classes in the gateway jars, verified live): page-level
docks: {"bottom": [{"id", "viewPath", "size", "show": "visible",
"content": "push", "anchor": "fixed", "handle": "hide",
"resizable": false}]}, and sharedDocks with the same entry
shape. Multiple entries on one edge are switchable views in one
dock, not stacked bars.

### Responsive strategy

The Roast page root is a Breakpoint Container (breakpoint 900).
Child selection is by child position.size ("small" / "large"):
that is what the client implements (getChildBySize reads
position.size; children without it default to "small"). Verified
live at 390px and 1600px.

- Large (desktop): trend first. Header (batch chip, source pill,
  state pill, clock), the chart card as hero, events strip,
  phases bar, tiles down the main column; a 400px control rail
  (Controls, Summary, MetaCard) on the right.
- Small (phone): control first. Chart present but secondary
  (compact card, legend off), tiles, events strip, phases, the
  full Controls and Summary in the scroll column, and the
  ControlDock pinned at the bottom.

### Timer rule

Eric's rule: "we only set the 0 timer when we drop." The header
and HUD clock count elapsed since Charge while roasting (the
working roast clock; never re-zeroed mid roast). At Drop the
displayed clock's zero is set: from Drop on (Dropped, Cooling,
Complete) it counts up from 00:00 as a post drop timer,
captioned SINCE DROP. Event stamps, phases and the chart always
use elapsed since Charge regardless of what the clock shows.

### Chart and event marker lines

The main chart stays on the classic XY chart (ia.chart.xy). The
2027 canvas line chart was rejected on evidence: its prop schema
has no markLine support, and ChartLab notes on this beta show
the canvas line chart drawing dual-axis bean+RoR history
incorrectly while the classic XY chart draws it correctly.

Marker lines: roastery.core.build_marks rebuilds the
EventMarksDS dataset on every stamp. The dataset has ONE COLUMN
PER EVENT (t_stamp, charge, dryEnd, fcStart, fcEnd, scStart,
scEnd, drop, notes). Each stamped event contributes a top point
(455 F) and a bottom point (152 F) in its own column plus an all
null gap row, so lines are vertical, span the temp axis, and
never connect diagonally. The chart carries one dashed amber
line series per event column (connect off), named CHARGE,
DRY END, FC START, and so on, so the legend labels the lines.
Custom events, Fan Boost and Drum Note share the NOTES column.

Why not bullet labels on a single series: proven live in three
rounds. With a {label} field template and with static text, with
invisible bullets and with visible bullets, with the label
positioned above and below the top point, no text ever rendered.
Bullet labels on XY line series do not render text in this
build; series naming is the labeling route that works. The Log
detail chart uses the same construction over DetailMarksDS.

### Log detail and the slide over editor

The Log tab lists batches (table) with Details, Edit, Use as
Ghost and Delete (behind a confirm). Details stages the batch
(roastery.batches.stage_detail): the curve with RoR recomputed
on read, the event marker dataset, the events timeline, summary
(phases, DTR, drop temp), metadata, and the captured button
presses (batch_events) when any exist.

Edit opens the slide over: a right docked view, not a popup (the
v3 popup had a beta chrome artifact and was, in Eric's words,
"a mess"). It holds ONE ia.input.form: batch number, the 17
metadata fields, and the seven event rows (time as mm:ss from
charge, temp in F). Mode and target travel through the
EditorCreateMode and SelectedBatchNumber tags; the editor view
refreshes its form from roastery.batches.editor_refresh, called
on view startup and on a 'roastery-editor-open' message that
open_editor sends after staging the tags (a docked view loads
once per page, so startup alone goes stale). The title is set by
the library: an expression binding concatenating the batch
number onto text evaluates to null with bad quality in this
build.

Saving runs Batches/Update via the library. Event times are
validated: they must parse as mm:ss and be strictly ordered
(charge, then dry end, then FC start, then FC end, then SC
start, then SC end, then drop, each only checked when present).
A violation saves nothing and shows the reason in the editor
("Dry End must come before FC Start. Nothing was saved."). On a
valid save the library recomputes the document from the edited
times: phase durations, DTR, total time, roastEnd, and the drop
temp and roast degree when the drop temp changed.

New Roast (Log header, and the Roast page Controls) zeroes the
workspace through core.reset_batch, takes the next batch number
(max of the database and the current tag, plus one) and lands
on the Roast page.

Saving a roast whose batch number is already in the log is
refused with a visible explanation in the Summary (start a New
Roast for a fresh number, or edit the saved batch from the Log
tab) instead of failing on the unique constraint.

### Settings organization

Settings is the Configure tab, renamed. One embedded view per
section, each a roast-card with a title, a one line description
and labeled field rows binding bidirectionally to the standing
tags (writing live, effective during a roast):

- Roaster (SettingsRoaster): ActiveSource, WsUrl, MQTT broker
  URL and topic, live probe readout.
- Targets (SettingsTargets): charge, dry end, FC and drop times
  and temps, PLUS the phase bar targets: Drying, Maillard and
  Development target seconds and the DTR target percent. The
  phase bar takes its pre-drop segment widths and its "target
  mm:ss" labels from these tags, so a change rebalances the bar
  immediately.
- Rate of Rise (SettingsRor): the Artisan RoR parameters, next
  section.
- Alarms (SettingsAlarms): the three lite alarms (enable,
  threshold, message).
- Metadata defaults (SettingsMetadata): the metadata form over
  the current batch tags; these are the defaults a new batch
  starts with (saved batches are edited in the slide over).
- Custom Events (SettingsCustoms): the four custom event names
  and kinds.

To add a setting: add a cfg_field row in the section it belongs
to (and the tag in setup_roastery_v4_tags.py when new). To add a
section: write one more settings_<name>_view() and add one embed
line to settings_page_view().

### RoR math (Artisan 5.0.0, from the source)

One implementation, roastery.core.compute_ror_series, is the
only RoR math in the app: the live RateOfRiseF tag, the live
chart curve (tag history of that tag), the saved batch RoR and
the ghost/background RoR are all computed by it from stored
temps. Temps are the stored truth; RoR is a calculated layer,
recomputed for saved batches on read with the current
parameters, the way Artisan recalculates a loaded profile.

Implemented from ~/workspace/artisan-src (Artisan 5.0.0,
src/artisanlib):

- Core delta (canvas.py compute_ror / compute_ror_simple,
  util.py arrayRoR): RoR = (T[i] - T[i-ds]) / (t[i] - t[i-ds])
  * 60, deg/min, on smoothed temps, with the left endpoint
  reduced by a 5 point (else 3 point) mean around the left
  index.
- Delta span: settings key DeltaSpan (ET: DeltaETspan),
  deltaBTspan default 20 s, UI range 0 to 30 s. Artisan converts
  to samples by its sampling interval; here the span is applied
  in seconds against real timestamps, the same math on irregular
  change driven samples. The Settings field allows 0 to 120 s
  (deliberately past Artisan's UI cap; the math is identical).
- Temp smoothing first: curvefilter, UI default 1, internal
  2x+1 = 3, trailing decay weights [1, 2, 3].
- RoR smoothing after the delta: deltafilter, UI default 3,
  internal 7, trailing decay weights [1..round(7/2)] = [1,2,3,4].
- polyfitRoRcalc: least squares slope over the span window
  instead of the two point delta.
- optimalSmoothing (needs polyfit): Hanning windows instead of
  decay, and a Savitzky-Golay derivative (window = span, order
  1); offline only, as in Artisan.
- Smooth Spikes: filterDropOuts, default on, OFFLINE ONLY in
  Artisan: median filter k=5 on temps, k=3 on RoR. (Artisan's
  live input spike filter, dropSpikes, has a dead comparison in
  5.0.0 and can never fire; not replicated.) Here it applies to
  the offline paths (saved batches, detail, ghost); live RoR is
  unclipped and unmedianed, like Artisan live.
- Clipping: RoRlimitFlag with RoRlimit 81 and RoRlimitm -18
  F/min: offline values outside become None; live values are
  not clipped (Artisan nulls only the plotted live value).
- Offline blanking: the first 10 samples after charge are
  blanked (Artisan: RoR_start = charge index + 10 in smoothETBT).
- A filter set to 0 yields no smoothing (an empty weight list
  is the identity), never an error.

The v3 EMA tag RoRSmoothingSec is superseded by these
parameters and is no longer read; the tag stays for
compatibility. Settings write the parameter tags live; a mid
roast change changes the live math on the next temp change.

Proof: verify_roastery_ror.py extracts the pure implementation
from the builder and runs it in CPython. On an exact 25 F/min
ramp it converges to 25 under the defaults, under a short span
with no smoothing, at 5 s sampling, and under polyfit; a +30 F
single sample spike produces a large excursion with Smooth
Spikes off and a bounded one with it on. Live, the HUD watch on
the simulator's clean ramp read exactly 25.0 F/min.

### Capture design: presses, temp changes, transaction groups

Two capture streams, both change triggered:

- Button presses. Every control press is stamped by the library
  through core.record_press: it bumps the ActionCounter tag and
  writes LastAction, LastActionElapsedSec and LastActionAt on
  the batch UDT (the trigger surface a transaction group can
  bind to), and, in the default PressCaptureMode 'Library',
  inserts one row into batch_events (batch number, action,
  seconds since charge, bean temp, RoR, fan, heat, wall clock).
  Covers all event buttons, Cool, Finish, Save Batch, Reset and
  the Fan/Heat steppers (one row per deliberate press).
- Bean temp changes. While State is Roasting or Cooling, every
  BeanTempF change appends a curve sample (dedupe: same elapsed
  second and under 0.05 F change), staged in the CurveSamples
  dataset and written to batch_series at save by the library
  (SeriesCaptureMode 'Library'), with the stored RoR recomputed
  from the temps at that moment.

Transaction groups (bounded attempt, Eric's requested design):
the groups were to be triggered on the ActionCounter change
(writing batch_events) and on the BeanTempF change while
roasting (writing batch_series). Findings in this build
(2027.2.0-beta1):

- Group config is a project resource decoded by
  com.inductiveautomation.factorysql.common.config.
  GroupConfig$Serializer; the config body is a property set over
  CommonGroupProperties keys (TABLE_NAME, TRIGGER_PATH,
  TRIGGER_MODE, UPDATE_RATE, WHERE_CLAUSE, KEY_VALUE_BINDINGS,
  AUTO_CREATE_TABLE, and friends), serialized through
  GroupConfigGson with custom adapters for property sets,
  qualified values, alarm configurations and tag event scripts.
- No example or template group config ships in the SQL Bridge
  module jars (common, gateway, designer, web-ui), and the
  diagnostics route from the v3 notes (/services/
  transaction-groups) returns 404 in this build.
- V3's hand authored JSON attempts failed gateway side with
  "Error deserializing group" from sqlbridge.ProjectRunner;
  those broken resources are gone (they did not survive the VM
  replacement), and no group resources exist in the project now.

Verdict: the triggered-group design is fully prepared (trigger
tags, target tables, capture mode switches in the library) but
the config cannot be authored reliably without the Designer in
this beta, so the proven library capture remains the runtime
path. If the groups are ever created in the Designer, set
PressCaptureMode (and SeriesCaptureMode) to 'Group' on the
CurrentBatch tags: the library then stops double writing and
the groups own the inserts. All app reads stay on named queries
either way; the Log detail reads batch_events through
Roastery/Events/SelectByBatch.

### Transaction group PressEvents: WORKING (2026-11-17)

The press group above now exists and runs. It was authored by
decompiling the SQL Bridge module jars (CFR on the common,
gateway and designer jars from the .modl) and writing the
resource in the exact format GroupSerializationUtil reads:
folder com.inductiveautomation.sqlbridge/transaction-groups/
PressEvents in the project, holding config.json (the group
config) and resource.json (files ["config.json"], attributes
{"typeKey": "standard"}), then POST /scan/projects. The live
status route is GET /data/fsql/api/v1/status/project/Roastery
(the /services/transaction-groups route from the v3 notes is
only the gateway web UI page). End state verified live: the
group reports state RUNNING with no errored groups.

Group settings (config.json keys are the lowercased property
names the Gson serializer writes):

- type_key "standard", name "PressEvents",
  execution_enabled true, data_source "db",
  table_name "public.batch_events" (see the schema note
  below), auto_create_table false, rec_mode "INSERT_ALL",
  raw_query_history_ins true (direct insert, no store and
  forward hop), update_rate 250 MS (raised from the original
  1.0 SEC later the same day: at 1.0 s, two presses landing
  inside one scan, like the v4 suite's back to back Fan +1
  and Heat +1 clicks, collapsed into a single execution that
  read only the latest LastAction, losing the first press's
  row. At 250 MS each press lands in its own execution; the
  v4 one row per press check passes. Also later the same
  day: the RoastBatch UDT type definition on the gateway was
  overwritten from the updated setup script so new instances
  default PressCaptureMode to Group, matching the live
  instance; instance values were preserved by the overwrite).
- Trigger: group_execution_flags 258 (FLAG_TRIGGER 2 plus
  FLAG_PREVENT_STARTUP_EXEC 256, so a gateway start does not
  fire a spurious row), trigger_mode "AnyChange",
  trigger_path "ActionCounter". The trigger path is the NAME
  of a configured item, not a tag path: the group reads item
  values through its __GROUP__ source.
- Timestamp: store_timestamp true with timestamp_column
  "pressed_at", so the group itself stamps each row.
- Items (all type grouptag_sqltref, target_type DB_FIELD
  unless noted): ActionCounter (driving tag
  [default]Roastery/CurrentBatch/ActionCounter, target_type
  NONE, the trigger item), BatchNumber to batch_number,
  LastAction to action, LastActionElapsedSec to
  t_offset_sec, BeanTempF to bean_temp_f, RateOfRiseF to
  rate_of_rise_f, FanLevel to fan_level, HeatLevel to
  heat_level. Item names are simple aliases; each item's
  driving_tag_path carries the full tag path, and
  target_data_type carries Int4, Int8, Float8 or String.

Schema note, the part that cost the earlier attempts: the
startup table check queries JDBC metadata with an empty
schema pattern for Postgres, so an unqualified table name
reports "table does not exist" (warning only, the group still
ran as WARNED). Qualifying the table as public.batch_events
fixes the lookup, and custom_index_column true with
index_column "id" makes the required index column match the
existing BIGSERIAL id instead of the default
batch_events_ndx, so the check finds every required column
and the group reaches clean RUNNING. auto_create_table must
stay false so the check never tries to create or alter the
real table.

Single writer decision: PressCaptureMode on CurrentBatch is
now "Group" (live tag value, and the default in
scripts/setup_roastery_v4_tags.py). roastery.core.record_press
still bumps ActionCounter and stamps LastAction,
LastActionElapsedSec and LastActionAt on every press, which
is exactly what the group reads, but in Group mode the
library does not insert, so the group is the only writer of
batch_events rows and there are no doubles. Every press type
(Charge, event buttons, steppers, Drop, Cool, Finish, Save
Batch, Reset) flows through record_press, so one group
covers all of them with no view changes. SeriesCaptureMode
stays "Library": batch_series capture is unchanged and no
series group was built.

Proof (2026-11-17, live Playwright Perspective session,
Maker modal dismissed): with PressCaptureMode "Group" and
batch_events empty, clicking Charge wrote exactly one row
(batch 1042, action Charge, t_offset_sec 0, bean_temp_f
352.50, rate_of_rise_f -31.16, fan 5, heat 5, pressed_at set
by the group), clicking Dry End wrote one row (t_offset_sec
4, bean_temp_f 353.60), and clicking Reset wrote one row
(t_offset_sec 6) and returned State to Idle. Two earlier
tag level probes (actions GroupProbe and GroupProbe2) also
landed with exact context. All five test rows were deleted
afterwards; batch_events returned to 0 rows, with batches at
7 rows and batch_series at 101 rows untouched.

### Verification

verify_roastery_v4.py drives a full roast from the phone layout
while a desktop session watches, and checks: marker dataset
columns, press and series rows in the database, save, Log
detail, editor rejection and recompute (phases and DTR change
in the stored document), duplicate save refusal, ghost overlay
with recomputed RoR, New Roast, the Settings phase target
rebalancing the phase bar, dark theme, zero quality overlays,
and zero Roastery warnings in the gateway log for the window.
verify_roastery_ror.py proves the RoR math (above).
validate_roastery_artisan.py covers all 22 views (served vs
disk, live view starts, log scan).

Environment notes from the build: the Maker trial expires every
2 hours of client use and is reset from the gateway home page
banner ("Log In to Reset", then Reset Trial); gateway restarts
do not reset it in this build (proven: trialSecondsLeft stayed
0 across a clean stop and start, and went to 7195 after the UI
reset). Mid session, an expired trial shows clients a "Trial
Expired" page while tag and API access keep working. On
2026-11-12 the lab VM also rolled back its system disk once:
Postgres came back as an empty cluster and was recovered by
recreating the ignition role and db database with the password
in .roastery-pgpass (the gateway's stored secret matched it),
reapplying setup_roastery_db.py, and reseeding fixture batches
1042, 1043, 1044 and 1046 with generated curves (the original
RoastLog based seed data was lost with the cluster). The same
rollback left the SQL historian sink faulted: its init is not
idempotent, so on every later reconnect it failed with
"Initialization of tag history datasource sink has failed"
because the sqlth_ tables already existed, and the chart's tag
history queries errored with no data stored (sqlth_te empty).
Recovery: drop the sqlth_ tables (they held no data) and
restart the gateway; the sink re-initialized, registrations
reappeared, and the trend came back. A plain trial check during
the same window also proved the UI trial reset survives
restarts (5448 s left after one).

## V4.1 addendum (2026-11-12, Eric's live phone feedback)

Eric used the v4 build live (a simulator roast on batch 1042,
left sitting in Cooling) and reported three defects, all
confirmed from his screenshot and reproduced in the lab before
fixing:

1. The bean temperature and RoR lines were MISSING from the
   Roast Curve; only the dashed target and the marker lines
   drew. Diagnosis, with data: those two series were bound to a
   tag history query with a mostRecent 30 MIN window. His roast
   had been charged about 105 minutes before the screenshot, so
   the entire roast fell outside the window. The target and
   markers still drew because they are tag datasets, not
   history. The wall clock date axis (date format defaulting to
   M/d, hence ticks reading "11/12") spanned charge to now and
   compressed the 7 minute roast into a sliver at the left.
2. The axis must be elapsed roast time, Artisan style.
3. On his phone (narrower than the 390px test width) the tile
   row bled past the right edge (gray slivers), the levels chart
   legend clipped ("H..." for Heat), and the tab bar clipped
   "Settings" to "Setting".

### The elapsed axis and LiveCurveDS

Every chart dataset is now anchored to the roast's own zero.
X values are java.util.Date at epoch + elapsed seconds, and
every XY chart's date axis sets date.format to "mm:ss" with the
title "Elapsed (mm:ss)" (the builder's _elapsed_axis helper;
the main chart, the levels strip, and the Log detail chart all
use it). roastery.core.marks_dataset, build_overlays (target,
background, background RoR), and batches.stage_detail all emit
epoch based x values now; stage_detail also no longer depends
on the batch having a stored roast_start (the generated
fixture batches have none and their detail curves used to
stage empty; fixtures now also record roast_start/roast_end).

The live curve has a new dataset tag, LiveCurveDS (columns
t_stamp, bean, ror, fan, heat), rebuilt by
roastery.core.build_live_curve from the recorded CurveSamples
on every appended sample and on every press. The samples are
the stored truth (one row per temperature change with elapsed
seconds); RoR is recomputed over them with compute_ror_series
and the current parameters (live variant), so the drawn curve
is the same math as RateOfRiseF and the saved batches, and it
survives indefinitely: a roast from hours ago still draws in
full, because nothing is windowed. The Fan / Heat levels strip
reads fan and heat from the same dataset on the same axis. Tag
history remains recorded on the probe tags (historian), but no
chart binds to it anymore.

### The levels strip height trap

After the rebind, the strip drew its series clamped to the top
edge of the plot with only the maximum tick label surviving.
Config and data were each proven innocent with isolated probes
(the same chart renders Eric's real 1,100+ row dataset
correctly at 198px height, and fails identically at about
108px): below roughly 120px of chart height the XY chart
collapses its value axis when a bottom legend is present. The
v4 strip was 104px with a right side legend; v4.1's bottom
legend at that height triggered the collapse. The strip now
gets 150px inside the desktop chart card and a 205px card of
its own on mobile. Two wrong hypotheses were tested and
rejected on the way (step line rendering on a date axis, and
Integer typed fan/heat columns): both plot fine at adequate
height.

### Mobile declutter (360px and 390px verified)

- Tiles: the small layout shows four tiles (Bean Temp, Rate of
  Rise, Fan, Heat) in a 2x2, percentage basis plus a
  roast-flexmin row rule (flex children may shrink below
  content width; the seven 148px tiles could not, and bled).
  Measured at 360px: four tiles of 160px, two rows, nothing
  past the edge. Deviation, Phase, and Target Drop remain one
  glance away in the HUD, the phase bar, and the summary.
- The levels strip moved out of the chart card on mobile into
  its own card under the tiles, with the bottom legend (the
  right side legend clipped at phone widths). The main chart
  card keeps the full 430px for the curve.
- Tab bar under 560px (advanced stylesheet): tighter padding,
  13px labels, a 56px theme button, less session nub clearance;
  "Settings" is fully readable at 360px. The batch chip
  truncates with an ellipsis instead of running off the card.
- The verify suite now carries a 360px context asserting no
  visible app element extends past the right edge (the Maker
  project update modal parks fully off canvas after a scan and
  is excluded as session chrome), plus dataset level checks:
  LiveCurveDS rows carry elapsed (epoch) x values, bean temps,
  calculated RoR, and fan/heat; marker x values are epoch
  based; the axis title reads "Elapsed (mm:ss)".

Verification: verify_roastery_v4.py passes 50 of 50 (the 44 v4
checks plus 6 v4.1 checks), validate_roastery_artisan.py and
ChartLab validation pass. Screenshots (lab showcase folder,
not in the repo): roastery-v41-before-360.png and
roastery-v41-before-desktop.png reproduce Eric's screenshot on
his own live session before the fix; roastery-v41-after2-*
show the same session after (both lines, mm:ss axis, strip
steps, 2x2 tiles, full tab labels);
roastery-v41-roast-360.png and the suite's
roastery-v4-roast-desktop.png show a controlled mid roast with
the RoR plateau at the simulator's exact 25 F/min.

Eric's live roast data was not discarded: before the suite
reset the workspace, his 1,417 curve samples and batch tags
were backed up to eric-roast-1042-backup.json in the lab, and
his 16 button presses stand in the batch_events table. The
workspace batch number was 1042, which collides with the
generated database fixture of the same number, so a library
save would have been refused by the duplicate guard; the roast
itself ran on the simulator source.

### Polish pass (2026-11-12, parent review of the 360px shot)

Two nits from reviewing the suite's mid roast 360px
screenshot, both fixed and now guarded by suite checks:

- HUD values read as one blob ("241.725.000:57 Development").
  The field groups sat 5px apart with 17px values. Each group
  now carries a left divider border and padding (new
  roast-hud-field class), the row is flex-start with a 10px
  gap, and values are 15px with ellipsis truncation; measured
  value to value gaps at 360px are 10px each, and the suite
  asserts at least 8px.
- The Settings tab label clipped ("Setting"). Root cause
  found by computed style inspection: Perspective emits style
  class properties as element styles, so the advanced
  stylesheet's tab bar rules lost the cascade and never
  applied (the bar still had its class padding of 100px right
  and 15px button text; only the one !important flex rule had
  ever taken effect). The media query rules now carry
  !important: bar padding 6px 60px (the 60px right side keeps
  the Log tab clear of the Maker session nub, which a 38px
  padding let it slide under), 12px tab labels. Measured at
  360px: tabs 75px wide, every label's scrollWidth equals its
  clientWidth, Log ends at x=300 with the nub clear. The suite
  asserts per button text fit at 360px.

Suite total is now 52 checks, all passing.

## V4.2: layout stability and design tokens (2026-11-12)

Two more rounds of Eric's live feedback: "things that move
that shouldn't" and "a lot of rounded corners that look
weird... professional UI UX design". Both were measured
before fixing (a Playwright harness records bounding boxes
across Idle -> Roasting -> Dropped and twice mid roast).

### Stability: what moved, and the fix

Mid roast itself was already frozen. Every movement happened
at state transitions, from content sized boxes:

- The state pill sized to its text (Idle 52px, Roasting
  81px) and shoved everything after it (all four HUD values
  jumped +29px at Charge; the desktop header pills shifted).
  The pill is now a fixed 88px box; the source pill beside it
  is fixed at 170px; the batch chip shrinks with an ellipsis
  instead of running under the pills.
- The phase bar recomputed segment widths to the ACTUAL
  phase shares at Drop (Maillard collapsed to 8px in a
  no-FC test drop). Widths are now always the Settings
  target proportions; actual durations and shares live in
  the segment text.
- The alarm banner mounted and unmounted (display flex /
  none), pushing the page when an alarm fired. It now
  reserves a 38px slot permanently (flex basis, because the
  flex layout drops minHeight from style classes); only its
  background and text change. Proven live: firing the high
  temp alarm turned the slot red with the chart card's Y
  coordinate unchanged. Reserving the slot also exposed a
  latent bug: ALARM_TEXT defaulted to the first crack watch
  message whenever no alarm was active; its final branch is
  now the empty string, with the watch message behind the
  same conditions as ALARM_ACTIVE.
- HUD fields breathed (the clock value box measured 60px
  and 62px for the same five characters). Fields are fixed
  boxes (Bean 52px, RoR 48px, Clock 60px, Phase grows) and
  every value label is capped at its group width; the phase
  value uses 14px type so 'Development' fits at 360px
  (a forced label measured 26px past the edge before).
- Tile value labels shrink wrapped their text ('--' 20px,
  '+9.2 F' 84px). They now stretch across the tile, and the
  big readouts use tabular numbers.

The verify suite asserts all of it: geometry captured twice
mid roast on desktop and 360px must be identical, the state
pill must be 88px, and the banner slot must be 38px. Suite
total is now 56 checks, all passing.

### Design tokens

Radius scale, applied to every style class and the advanced
stylesheet (was 16/12/10/8px mixed, the bubbly look Eric
flagged):

- 2px: micro elements (accent bars)
- 4px: interactive (buttons, inputs, tab buttons, phase
  segments)
- 6px: small containers (event cells, tiles' inner cells)
- 8px: cards and panels
- 999px: pills only, where the pill IS the shape (state
  pill, source pill)

Nested corners follow the scale (an 8px card with 12-16px
padding holds 4px elements). validate_roastery_artisan.py
now fails if any radius outside the token set appears in a
style class or the stylesheet. Spacing sits on a 4pt rhythm
(gaps 8/12/16; the 9/14/15px values were normalized, and
roast-gap-14 folded into roast-gap-12). One elevation
language: cards take the theme border plus boxShadow2; the
control dock's heavy blur shadow became a subtle
0 -4px 12px; the alarm banner lost its red glow and is flat.
Type scale: 10px captions in the HUD, 11/12/13/14 body and
labels, 16 HUD values and stepper glyphs, 20 medium
readouts, 30 tile values.

## The style system (v4.3 audit, Eric's standing rule)

All visual styling lives in Perspective style classes and
the advanced stylesheet. No view carries static inline style
properties; validate_roastery_artisan.py fails the build if
one appears, or if a style binding appears outside the named
exception list below. The audit that produced this section
walked every view JSON: 13 components carried inline styles
(the v4.2 stability fixes and the chart backgrounds); all
moved into classes.

### What lives where

- Style classes (roast-*): colors, backgrounds, typography,
  padding, border radius (via the token variables), shadows,
  overflow and text behavior. Naming: roast-<component> for
  component classes (roast-card, roast-btn, roast-hud-value),
  roast-<component>-<variant> for variants (roast-btn-charge,
  roast-seg-drying), roast-gap-<n> for spacing utilities.
- Advanced stylesheet: the design tokens (:root CSS
  variables), borders, pseudo states (hover, active, focus),
  media queries and breakpoints, scrollbars, and the few
  cascade overrides that need !important.
- Component position (basis, grow, shrink): box sizing. This
  is layout, not styling, and it is the only sizing channel
  that works for flex items in this build (see the compiler
  matrix).
- Library and bindings: data. A binding may set a style
  property only when the value is computed from live data or
  a view parameter (the exceptions).

### The compiler matrix (measured on this Maker beta)

The style class compiler strips properties from class
definitions before they reach the client CSS. Proven by
dumping the compiled .psc-roast-* rules from a live session
and comparing computed styles:

- Carried by classes: color, background (color and image),
  font (size, weight, family), padding, border-radius,
  box-shadow, overflow, text (align, transform, overflow,
  letter-spacing, line-height), white-space, cursor, filter.
- Stripped from classes (never render): border and its
  per-side variants, width, min-width, max-width, height,
  min-height, flex-shrink. (The compiled rule for a class
  carrying only stripped keys comes back EMPTY.)
- Carried through the client layout channel, not the
  compiled CSS: gap (class gap values do space flex
  children), and root sizing classes such as roast-scroll.

Consequences applied in this pass: borders moved into the
advanced stylesheet keyed to the same class names (cards
had silently rendered borderless since v4; computed
borders measured 0px and are 1px now, including the HUD
field dividers, which had also never rendered). Fixed
component boxes moved from class width keys and inline
styles into flex position bases (state pill 88px, source
pill 170px, stepper value 44px, alarm slot 38px).

### Tokens and how to change things globally

Radius tokens are CSS variables in the stylesheet :root
block: --roast-radius-micro (2px), --roast-radius-
interactive (4px), --roast-radius-small (6px),
--roast-radius-card (8px); pills stay a literal 999px
because the pill is the shape. Classes reference the
variables. Proof from this pass: editing ONLY the
stylesheet line "--roast-radius-card: 8px" to 14px and
rescanning moved every card in the app to 14px; buttons
stayed at their 4px token; no view or class file changed.
Spacing sits in the gap and padding values of the classes
(4pt rhythm: 4, 8, 12, 16, 20). Palette colors are the
theme variables (var(--container), var(--label),
var(--border), ...) plus the semantic button color classes
(roast-btn-charge and friends), which are the one place
literal hex lives, so both themes hold.

To change a token globally: edit the stylesheet variable
(or the class value, for spacing and type) in
build_roastery_v4.py, rebuild, rescan. To add a styled
component: add a roast-* class (or reuse one), apply it via
style.classes, put any border or pseudo state in the
stylesheet under the same name, express fixed sizes as a
flex position basis, and never write a static props.style
key; the validator will fail the build if you do.

### Named exceptions: style bindings that stay

Bindings, not static styles; each computes its value from
live data or a parameter, which a class cannot express:

- PhasesBar DrySeg/MaiSeg/DevSeg, props.style.width: the
  segment percentages computed from the Settings targets.
- RoastPage StatePill and HudBar HudState,
  props.style.backgroundColor: the state to color map.
- RoastPage WsPill, props.style.backgroundColor:
  connected/offline color from the live source state.
- Controls ModePill, props.style.backgroundColor: the
  mode color by roast state.
- RoastPage AlarmBanner/AlarmBannerMobile,
  props.style.backgroundColor: red only while an alarm is
  active (the slot itself is a reserved flex basis).
- Tile AccentBar, props.style.backgroundColor: the accent
  is a per-instance view parameter.
- EventCell NameLabel, props.style.color: the done state
  is a parameter (a map transform cannot emit var()
  colors; the v2 trap).
- Class SELECTION bindings (Tile ValueLabel, BatchesPanel
  ConfirmRow, BatchDetail PressCard, props.style.classes):
  choosing among classes by parameter or UI state; this is
  the class system working as intended, and it replaced the
  last two display bindings in this pass (the hidden state
  is the roast-hidden class).

Chart series colors, axis and legend configuration are
chart data properties (the v3 precedent), not component
styles; the chart surface background is the roast-chart
class.

## v4.4: all charts are canvas charts (2026-11-13)

Eric, clicking the v4.3 build: "The roast curve doesn't do
dark mode. Is this using a new echart? All of them must be
new echarts." He was right on both counts. The classic XY
chart painted its own light plot surface regardless of the
session theme, and it was still the component under every
chart in the app. All three Roastery charts (the main Roast
Curve, the Fan / Heat levels strip, and the BatchDetail
curve) are now ia.canvas-charts.line, the ECharts based
component. The validator fails if any component type
starting with ia.chart. appears in a Roastery view
(classic_chart_offenders), so the classic chart cannot
creep back.

Theming rules, proven in a live probe round before the
migration was built on them:

- A chart color left as the empty string follows the
  session theme natively: axis text, gridlines, titles, and
  legend all render correctly in dark and light with no
  bindings. Background '' is transparent, so the card shows
  through.
- CSS var() strings do NOT resolve inside chart props. The
  wrapper hands them to the canvas literally, which is an
  invalid fill, so the text renders black and vanishes on a
  dark background. Never put var() in a chart prop.
- Series colors are literal hex by design (the app palette:
  bean and fan #3b82f6, RoR #14b8a6, heat #ef4444, ghost
  slate, target light slate dashed). They read identically
  in both themes, like the classic chart's series did.
- The ChartLab-era worry about dual-axis canvas charts
  rendering the second series wrong was specific to tag
  HISTORY bindings. These charts are dataset fed, and the
  dataset path renders both axes correctly.

Data and markers:

- One wide dataset per chart. roastery.core.build_live_curve
  unions the recorded samples with the background (ghost)
  series, the ghost RoR, and the target profile by timestamp
  into LiveCurveDS (columns t_stamp, bean, ror, fan, heat,
  bg, bgRor, plan). Every series sets connectNulls, because
  the gaps in a unioned row are merge artifacts, not data
  gaps. The x axis stays the v4.1 elapsed axis: epoch based
  Date(elapsed times 1000) values on a time axis, never wall
  clock.
- Event markers are native ECharts markLines now:
  series[].referenceLines items, built by the library
  (roastery.core.event_reference_lines for the live chart,
  roastery.batches.detail_reference_lines for the detail
  chart) and bound through the bracket path
  props.series[N].referenceLines.items with the marks
  dataset tag as the trigger and a script transform asking
  the library for the items. Labels sit at the top of the
  plot (position 'end'). Two axis facts the probe round
  established: the time axis minimum is 1000 ms, because the
  tick at exactly 0 is the epoch year boundary and ECharts
  labels it 1970; and reference line values clamp to the
  same 1000 ms minimum or the line at 0 falls outside the
  plot.
- Height is load bearing on this component, more than it
  was on the classic chart (whose value axis collapsed
  under about 120px in v4.1). The canvas wrapper reserves
  roughly 150px of fixed layout (title, axes, legend)
  before the grid, so below about 240px of component height
  the grid collapses to a sliver regardless of config:
  proven live at 150px with legend, labels, and titles all
  off (still collapsed), 200px (half collapsed), and 250px
  (clean). The strip is 250px in the desktop chart card
  (which grew to 660px to hold it without shrinking the
  main chart) and 280px as its own mobile card. The main
  chart keeps the remaining height everywhere.
- On the phone the main chart drops its two y-axis titles
  and shrinks its axis labels (main_chart mobile variant):
  at 360px the titles and label columns otherwise squeeze
  the plot. The detail chart drops its axis titles at every
  width for the same reason; its page is a single layout,
  and at 360px the titles clipped at the card edges and the
  plot collapsed to a sliver (proven, then fixed, then
  re-proven with all four event labels readable).

One migration bug worth remembering: when LiveCurveDS
gained its bg, bgRor, and plan columns, the empty dataset
prototype row in empty_live_dataset kept only five values
for eight columns. system.dataset.toDataSet throws on the
mismatch, clear_curve_samples threw inside charge(), and
the press appeared to half work (state changed, no press
recorded, no markers). Prototype rows must grow with their
column lists.

## No overlap pass (2026-11-13)

Eric, clicking again: "There are words and numbers
everywhere that are overlapping and can't be read. Be
scrupulous about this." The audit covered every text
bearing element at 360px and desktop in both themes. What
it found and fixed:

Chart axes. Tick density is now explicit through
ticks.majorSplit (the component's splitNumber analog; no
interval or label formatter is exposed). The main chart
runs split 11, about 60 second steps at a typical span.
Thirty second steps (split 22) were tried on desktop and
the labels merged into each other, so 60 seconds is the
standard; Eric's floor was about 15 seconds. Phone charts
add labels.rotation 35 so the labels tilt clear of each
other, the strip included; the detail chart rotates 30.
Value axes got explicit splits too (bean 6, RoR 4, level
5).

Marker labels. The library's collision policy
(roastery.core._ref_items) places a label at the top of the
plot only when it stands clear of the previous top label
(120 s on the standard policy), drops it to the middle of
its line when that band is clear (45 s spacing), and
otherwise draws the line with no label rather than stack
unreadable text; the events strip under the chart always
carries every name. The phone's live chart uses a compact
variant (event_reference_lines_compact, 150 s spacing in
both bands) because a whole roast is about 215px wide
there. An audit roast with Charge, Dry End at 50 s, and FC
Start at 130 s renders all three distinctly on desktop,
and Charge plus a middle Dry End on the phone (FC Start
keeps its line, label dropped by policy).

HUD. Bean and RoR now read as whole numbers. At 16px
monospace a one decimal value needs 48px and the Bean
field box holds 44px, so the last digit clipped in Eric's
hands. The HUD is the glance layer; the tiles beside it
keep the 0.0 precision. The phase value class dropped to
13px so 'Development' fits its field with margin.

Phase bar. Three fixes. Segment text is two stacked lines
(name, then time and share) because the single line
('DEVELOPMENT 01:05 - 43%') never fits a target proportion
segment on a phone. The bar is contiguous now: percentage
widths summing to 100 plus 8px gaps overflowed the card.
And the Development caption is DEV: at a 23 percent share
the segment is about 68px wide on a phone and the full
word needs about 88px at 12px, so it clipped mid word
under every box sizing fix (the segment box itself needed
border-box sizing and min-width 0 in the stylesheet, also
fixed; see below). DEV is the working abbreviation, the
same root as the DTR figure beside the bar; the full word
stays in the HUD, the summary, and Settings.

Log page. The header row had a fixed 72px height while
its subtitle needed three lines at 360px, so the New
Roast and New Batch buttons painted over the text. The
row is auto height with wrap now: buttons drop under the
text on narrow screens. Table columns slimmed from 710px
total to about 580px, and the list date drops its year
(the detail view carries the full date), so the Bean
column no longer runs off the card edge.

The hidden utility actually hides now. This corrects a
v4.3 claim above: roast-hidden was described as the
mechanism that replaced the last display bindings, but on
this build the style class compiler drops display from
class definitions too (the compiled .psc-roast-hidden rule
was empty, measured live), so the BatchesPanel delete
confirm row rendered unconditionally, complete with a
'Delete batch 0' prompt. display now lives in the advanced
stylesheet (.psc-roast-hidden, display none !important),
the same treatment as borders, and both class driven
hides (confirm row, detail press card) work. Add display
to the list of properties the compiler strips: border,
width, minWidth, maxWidth, height, minHeight, flexShrink,
and now display. Anything load bearing in one of those
properties belongs in the stylesheet, keyed to the class
name.

## Artisan import and export (2026-11-14)

The roast log speaks Artisan's file format both ways, so roasts
move between Roastery and Artisan (Eric's other SR800 tool)
without losing data. All logic lives in the project scripting
library as a third package, roastery.artisan (Jython), plus the
existing named queries; view handlers are one line calls, per
the standing rule that features live in the library, not in
CPython scripts.

Format facts (full study: knowledge note
artisan-file-format.md, from the Artisan 5.0.0 source). An
.alog file is one Python dict literal, loaded with
ast.literal_eval. The `mode` key ('C' or 'F') is the unit of
every temperature in the file. timex is seconds since
RECORDING start; temp2 is the bean curve, temp1 the
environment curve; missing readings are -1. Main events exist
only as sample indices in timeindex [CHARGE, DRY, FCs, FCe,
SCs, SCe, DROP, COOL]. Custom slider events live in
specialevents with values on an internal scale (percent p is
stored as p/10 + 1, with 0 percent stored as exactly 0). RoR
is never stored in the file; Artisan recomputes it from the
temps, exactly like Roastery, so imported temps go through
roastery.core.compute_ror_series (offline path) before they
land in batch_series.

Import (Log page, Artisan import row, ia.input.fileupload,
onFileReceived; the handler reads event.file.getBytes()). The
profile maps onto the standard batch document and series:
series rows start at Charge (pre-charge samples are dropped
from the series but kept in the raw arrays), C mode files are
converted to F, Fan and Heater slider events (etypes slots
named Fan/Air and Heater/Burner) become per sample fan and
heat levels with the quantization level = 1 + round(pct * 8 /
100) clamped to 1..9, and back with pct = (level - 1) * 12.5.
The imported batch takes the next free batch number, never
the file's number, and an import whose roastUUID is already
in the log is refused with a note naming the existing batch.
Everything Roastery has no field for (the ET curve, extra
device curves, alarms, PID and ramp/soak, energy and between
batch data, display colors, the imported computed cache) is
kept verbatim in the document's `artisan` subdocument,
grouped identity / curves / events / display / settings, so
export is lossless. No schema change was needed beyond that
JSONB subdocument.

Export (BatchDetail, Export .alog button,
system.perspective.download). The dict is rebuilt from the
stored batch: carried subdocument values win wherever the
batch still matches them, structural keys (timex, temp1,
temp2, timeindex from the document events, special events
from the raw lists or rebuilt from fanHeatTrace, phases,
weight, beans) always come from the current document, so
editor changes are honored. A native batch with no ET probe
exports temp1 as all -1, the format's own missing sentinel.
The computed cache is rebuilt in Artisan's key shape (event
times elapsed since charge except CHARGE_time, which is the
absolute timex; phase times; turning point as the curve
minimum between charge and dry end; AUC as the trapezoid
area above AUCbase from the turning point to drop). The
file carries the Artisan 5.0.0 identity fields and the
signature constant published in the Artisan source: that
pair is what official Artisan builds verify (an ed25519
signature over version + revision + artisan_os), so exports
open without a "not genuine" prompt. The file hash is
computed last, exactly as Artisan does: SHA-256 over
json.dumps of the profile with every int converted to float,
keys sorted, separators (',', ':'), ensure_ascii. One format
truth to know: an event's temperature in an .alog IS the
curve sample at the event's index, so a re-imported batch
takes its drop temp from the nearest stored sample (batch
1042: 251.7 F re-imported vs 251.92 F as originally recorded
from the live tag).

Round trip verification, all live on the Maker gateway
2026-11-14. (1) The fixture sample-roast.alog (196 keys,
SR800, built from the Artisan source exactly as getProfile
writes it) imported through the Log page upload: batch 1049,
221 series rows, dry end 270 s, FC start 465 s, drop 585 s
at 406.8 F, weights 200.0 g in and 171.4 g out, fan and heat
levels from the 8 slider events. (2) Its export parses under
Artisan's own loader path under CPython (ast.literal_eval
plus the replicated validateProfileDict checks): the
recomputed hash matches, the ed25519 signature verifies,
and timex, temp1, temp2, timeindex, special events and
values, phases, weights and roastUUID are identical to the
fixture; the export also carries exactly 196 keys.
(3) Native seeded batch 1042 exported (41 keys, hash
verified), then re-imported as batch 1050: bean, total time
and drop time match, 21 of 21 series rows, and every bean
temp matches the original to 0.01 F.

Two detail view fixes rode along. The header buttons
wrapped on phone widths into the chart card's area (a flex
basis of 'auto' computes as zero height in this build, so
the wrapped row was painted over); the header is now two
fixed rows (Back plus title, then Use as Ghost, Edit,
Export .alog right aligned), verified by a coordinate tap
on Export at 360px firing the download. And the detail
chart's marker label gaps widened (top band 150 s, middle
60 s): an imported profile with FC Start 120 s before Drop
merged the two top labels into one word at 360px; Drop now
drops to the middle band.

## Phase analysis readouts (2026-11-14)

BatchDetail's Summary card gained an analyzer style Phase
Analysis table, computed by roastery.batches._phase_analysis
from the stored series and the document events at stage
time: per phase (Drying, Maillard, Development) the
duration, its share of the roast, the bean temp gain
between the bounding events, and the average rate of rise
over the phase (gain per minute), plus the turning point
(the bean temp minimum between charge and dry end, read off
the stored curve) as its own line. The verify suite checks
the block renders on the detail page. Remaining Artisan
mapping gaps worth doing next, in rough value order: roast
comparison overlays beyond the single ghost curve, the
Roast Properties completeness pass (organic and certification
fields Artisan carries that our form does not), and
background profile loading directly from an .alog on the
Roast page (the import path now makes this cheap: stage the
imported series as the background dataset without saving).

## Artisan feature inventory and ranking (2026-11-17)

Study only, from the Artisan 5.0.0 source at ~/workspace/artisan-src
(src/artisanlib) checked against the Roastery library code
(roastery.core, roastery.batches, roastery.artisan) and the
sections above. Ranking is for one user: a single probe SR800
home roaster, manual control only, Fan and Heat levels 1 to 9,
phone as remote control and desktop as trend screen. Status
key: HAVE means the library or views already do it (location
named), BUILD means not yet present (one line scope), SKIP
means not building it (reason stated). Single sensor rule:
anything that needs ET or a second probe is SKIP, and the
reason is stated plainly on each such line.

### Tier 1: highest importance

1. Background profile loaded directly from an .alog on the Roast page. DONE.
   Artisan: loadbackground() and the background dialog
   (main.py, background.py) load any saved profile as the
   template curve behind the live roast. Roastery today loads
   a ghost only from a saved database batch (batches.set_background).
   Scope: file upload on the Roast page, parse with
   roastery.artisan, stage the series as the background dataset
   without saving a batch. Known gap from 2026-11-14.
   Built 2026-11-17: BgUpload on the Roast page chart card
   calls roastery.artisan.stage_background_upload, which
   parses the file, stages the series through the same
   BackgroundCurveJson mechanism as the saved batch ghost,
   and labels it File: <name>. Clear ghost empties it.
   Nothing is written to the database. Verified live in
   verify_roastery_tier1.py (221 points staged, no batch
   written).
2. Multi curve comparison beyond the single ghost. DONE.
   Artisan: comparator.py (RoastProfile, roastCompareDlg)
   overlays many profiles, each with its own color, visibility,
   time offset and BT and RoR traces, plus a compare table.
   Roastery has exactly one ghost curve. Scope: select two to
   four saved batches on the Log page and overlay them on
   BatchDetail and optionally on the Roast page, BT and RoR
   only. Known gap from 2026-11-14.
   Built 2026-11-17: the Log page compare section
   (roastery.batches.build_compare) takes up to three saved
   batches and overlays BT (solid) and RoR (dashed) per batch
   on one canvas line chart with literal colors (orange,
   teal, purple) and a legend naming A, B and C in the
   caption. RoR is recomputed offline per batch by
   roastery.core.compute_ror_series. Verified live in
   verify_roastery_tier1.py, including no overflow at 360px.
3. Roast Properties completeness pass. DONE.
   Artisan: roast_properties.py (editGraphDlg) and the
   ProfileData fields in atypes.py carry far more than the
   current 16 form fields (core.FORM_MEMBERS). Missing in
   Roastery: roast title, roaster type, size and heating,
   organization, elevation, volume in and out, defects weight,
   roasted density, bean size min and max, the ten defect
   flags (heavyFC, lowFC, lightCut, darkCut, drops, oily,
   uneven, tipping, scorching, divots), whole and ground bean
   color readings with color system, ambient temperature,
   humidity and pressure, roasted moisture, greens
   temperature, and cupping notes as a field separate from
   roast notes. Scope: extend the form and the document,
   keep values in the JSONB document and the artisan
   subdocument so export stays lossless. Known gap from
   2026-11-14, narrowed here to fields a home roaster will
   actually fill in. Artisan Plus store, coffee, blend and
   schedule fields are not part of this pass (see SKIP).
   Built 2026-11-17: all 30 fields landed as CurrentBatch
   members and core.FORM_MEMBERS entries, so the metadata
   form, the slide over editor, the JSONB document and the
   artisan import and export all carry them (import maps the
   .alog keys including volume and roasted density lists and
   the ten defect flags; export writes them back only when
   set, so nothing is fabricated). Cupping notes are their
   own field, separate from roast notes. Verified live in
   verify_roastery_tier1.py with a 27 field fixture round
   trip through import, document and export.
4. Live turning point detection and display. DONE.
   Artisan: findTP() in main.py (wrapping findTPint in
   util.py) finds the BT minimum after CHARGE; computed.TP_time
   and TP_BT anchor the dry phase RoR and the default AUC
   start. Roastery computes a turning point only after the
   fact, inside batches._phase_analysis on the detail page.
   Scope: detect TP live in roastery.core once BT rises clear
   of the post charge minimum, show it as a tile and a chart
   marker, and store it in the batch document.
   Built 2026-11-17: roastery.core._track_turning_point runs
   on every bean temp change, tracks the post charge minimum
   and confirms the turning point at a 5 F rise, stopping at
   FC START. Shown on a Turning Point tile, as a TP chart
   marker (notes column), and stored in the batch document;
   batches._phase_analysis prefers the stored value. Note:
   the RoasterSim program never dips after charge, so on the
   simulator TP confirms at elapsed 0 on the charge minimum.
   Verified live in verify_roastery_tier1.py.
5. Live AUC with Artisan settings (begin, base, target, guide). DONE.
   Artisan: canvas.py AUC settings (AUCbegin, AUCbase,
   AUCbaseFlag, AUCtarget, AUCguideFlag, AUCLCDmode) and
   main.py updateAUC(), calcAUC(), profileAUC() and
   updateAUCguide(), which runs a live AUC total, an AUC
   since FC START total, and a guide time predicting when
   the target AUC is reached at the current RoR. Roastery
   has only a saved batch AUC in batches.curve_auc, with the
   base fixed at the charge temperature and no live value.
   Scope: live AUC tile and HUD value from BT only, Settings
   fields for begin event, base temperature and target, and
   the guide time as a readout. Per phase AUC is Tier 2.
   Built 2026-11-17: roastery.core.update_live_auc
   recomputes AUC from the stored curve points on every temp
   change (trapezoid in F min above the base), with the
   Settings AUC section carrying begin event (Charge, TP,
   Dry End, FC Start), base temperature, base from event,
   target and guide toggle. The guide solves the constant
   RoR quadratic for the elapsed time the target is reached.
   Shown on an AUC tile, in the summary (total, since FC,
   guide time) and stored in the batch document as
   aucDetail. Deviation from the scope line: AUC did not
   join the phone HUD. Measured at 360px, the HUD budget
   (state pill, bean, RoR, clock, phase wide enough for
   Second Crack) cannot fit a fifth field without clipping
   a digit or a phase letter, so AUC lives on the tiles and
   in the summary on both layouts instead. Verified live in
   verify_roastery_tier1.py.
6. Full alarm table replacing the three lite alarms. DONE.
   Artisan: alarms.py plus the alarm lists in canvas.py
   (alarmflag, alarmguard, alarmnegguard, alarmtime,
   alarmoffset, alarmcond, alarmsource, alarmtemperature,
   alarmaction, alarmbeep, alarmstrings) give an editable
   table of alarms with a guard event, a time offset, a
   source (BT, delta BT, time, or an event), a condition and
   an action, and alarm sets can be imported and exported
   as JSON. Roastery has three fixed view expression alarms
   in SettingsAlarms. Scope: an editable alarm list evaluated
   in roastery.core against BT, RoR, elapsed time and events,
   with banner and message actions only. No alarm may move
   Fan or Heat, because control stays manual.
   Built 2026-11-17: definitions live as JSON in the
   AlarmDefsJson tag (seeded with the three former lite
   alarms) and roastery.core.evaluate_alarms runs them on
   every temp change and press: a definition arms after its
   guard event plus offset, then compares BT, RoR or elapsed
   time with >= or <=. Banner alarms show while the
   condition holds; Message alarms latch until the next
   charge. The Settings Alarms section shows the table and
   an editor (Load, Save, Add as New, Delete) whose fields
   are bound to the AlarmEditor staging tags, because
   view.custom property bindings do not write user edits
   back in this build. Two build lessons from this item,
   both proven in the Tier 1 rounds: a virtualized table at
   position basis auto renders zero rows (the alarm table
   uses a fixed 190px basis and scrolls internally), and the
   editor read path must not rely on property bindings.
   Verified live in verify_roastery_tier1.py (banner fires,
   message latches, guard stays silent, editor save
   rewrites the definitions).

### Tier 2: high value math, lines and background help

7. Phase analytics completion. DONE.
   Artisan: main.py RoR() and computedProfileInformation()
   report per phase RoR with the dry phase measured from the
   turning point, per phase delta temp, total RoR, the RoR
   at FC START (fcs_ror), per phase AUC, and the cool phase
   time. Roastery batches._phase_analysis has duration,
   share, temp gain and average RoR per phase, but its dry
   phase starts at charge, and it has no per phase AUC, no
   FC START RoR and no cool phase line. Scope: align the dry
   phase RoR to the turning point and add those fields to
   the Phase Analysis table and the saved document.
   Built 2026-11-17: roastery.batches._phase_analysis now
   follows Artisan RoR() exactly: the dry phase delta and
   RoR use the greens temp branch when a greens temp is
   recorded, otherwise they are measured from the turning
   point; Maillard and Development use the bounding event
   temps and times. Per phase AUC is the trapezoid area
   over the Artisan ts() ranges (charge to dry, dry to FC
   start, FC start to drop) above the saved AUC base.
   fcs_ror comes from the one RoR implementation at the FC
   start sample, total RoR runs TP to drop, and the cool
   line runs drop to the Artisan COOL time for imports or
   the last stored sample for native roasts. The structured
   result is stored in the document as phaseAnalysis at
   save and at import and recomputed on editor saves, and
   it shows in the Phase Analysis table (new AUC column)
   plus RoR at FC start, Total RoR and Cool phase readouts
   on BatchDetail. Verified live in
   verify_roastery_tier2.py against an independent
   recompute from the stored series (dry RoR 50.7 F/min
   through the greens branch on the fixture, cool 60 s).
8. Loss, yield and density computations. DONE.
   Artisan: main.py weight_loss(), volume_increase() and
   computedProfileInformation() derive weight loss, defects
   loss, total loss, total yield, volume gain, moisture loss
   (green moisture minus roasted moisture), organic loss
   (weight loss minus moisture loss), and green and roasted
   density from weight over volume. Roastery stores only
   weightLossPct in batches.build_document. Scope: compute
   the full set at save time and show it in Summary and on
   BatchDetail, using the Tier 1 volume, defects and
   moisture fields.
   Built 2026-11-17: roastery.batches.loss_yield_density
   computes the full set at save time and at import from
   the Tier 1 fields and stores it in the document loss
   block: weight loss, defects loss, total loss, total
   yield, volume gain, moisture loss, organic loss, and
   green and roasted density in g/L. Every input is
   guarded: a missing or invalid input stores nothing,
   never a fabricated number, and weightLossPct now comes
   from the same math. Shown in the live Summary (new
   lines read from the standing tags, the same expression
   pattern as the existing Weight loss line) and on
   BatchDetail under Loss, Yield and Density. One naming
   note: Artisan's computed total_yield is a weight in
   grams, so the document stores totalYieldG for that
   value and totalYieldPct for the percent the UI shows.
   Verified live in verify_roastery_tier2.py with a
   fixture of known inputs (200 g in, 170 g out, 10 g
   defects, 250 to 300 ml, moisture 10.8 to 1.8) producing
   exactly 15.0, 5.9, 20.0 and 80.0 percent and 800 and
   567 g/L, and a sparse seeded batch storing none of the
   volume or moisture values.
9. BT projection lines, linear and quadratic. DONE.
   Artisan: canvas.py updateProjection() extends the BT
   curve forward at the current RoR (linear mode), or with
   a linear RoR trend (quadratic mode, after five minutes),
   so the roaster can see where the curve is heading.
   Scope: a dashed projection series on the live chart from
   the current BT and RoR, with a Settings toggle and mode.
   BT only; the ET and delta projection variants are SKIP.
   Built 2026-11-17: roastery.core.projection_points
   builds a dashed Projection series (amber, literal hex)
   that build_live_curve merges into LiveCurveDS as the
   proj column. Linear mode extends BT two minutes
   forward at the current RoR in 15 s steps. Quadratic
   mode integrates a linear RoR trend with Artisan's
   0.002 deltadelta clamp and, as in Artisan, engages
   only after five minutes elapsed; before that it falls
   back to linear. Settings gained a Projection section
   (toggle ProjectionEnabled, mode ProjectionMode).
   Display only: the Tier 2 suite proves the saved batch
   document carries no projection data. Verified live:
   the projection slope matched the live RoR and the
   toggle emptied the series.
10. Live deviation from the background curve, and a BT similarity score. DONE.
    Artisan: the deviation readouts against the background
    profile, and main.py curveSimilarity() returning a BT
    similarity value (dbt in the computed block) between the
    live or saved curve and the background. Roastery has a
    deviation tile only against the four point target plan
    (batches and core.build_overlays). Scope: deviation of
    live BT from the loaded ghost at the same elapsed time,
    plus a similarity score on BatchDetail for the staged
    batch against its ghost.
    Built 2026-11-17: (a) roastery.core.update_bg_deviation
    runs on every temp change: live BT minus the staged
    ghost BT interpolated at the same elapsed time,
    published on the BgDeviationText tag and shown on a
    Bg Deviation tile in the desktop tiles row and as a
    Deviation vs background line in the Summary. The
    phone HUD is untouched, per the Tier 1 space finding.
    The staged ghost's drop time now travels with it on
    the BackgroundDropSec tag, written by both ghost
    routes and cleared with the ghost. (b)
    roastery.batches.bt_similarity implements Artisan
    curveSimilarity(), BT half only: the RMSE in F
    between the staged batch and the ghost from dry end
    to drop, with the ghost time axis shifted so the two
    drop times align (Artisan's dropTimeDelta), shown on
    BatchDetail as BT similarity vs ghost. Roastery
    adaptation: Artisan locates its dry index by scanning
    back from drop for the phases dry boundary
    temperature; Roastery uses its recorded Dry End event
    as the same phase boundary. A batch staged as its own
    ghost scores 0.0 F RMSE in the Tier 2 suite, and the
    live deviation matched an independent recompute to
    0.1 F. The ET half stays skipped (single sensor).
11. Background playback prompts. DONE.
    Artisan: background.py and canvas.py playback settings
    (backgroundPlaybackEvents, backgroundPlaybackDROP,
    backgroundReproduce, specialeventplayback and the
    playback aid flags) replay the background profile during
    a roast: its Fan and Heat events prompt at their times,
    with an optional beep, and DROP can be replayed. Scope:
    when a ghost is loaded, prompt at each ghost Fan and
    Heat change and at ghost DROP with a banner and the
    suggested level. Prompts only; nothing is applied
    automatically, because control stays manual.
    Built 2026-11-17: both ghost routes now also stage the
    ghost's Fan and Heat change events. roastery.core
    .build_background_events derives them from the staged
    per sample fan and heat levels (the first sample sets
    the starting levels and never prompts) plus a Drop
    event at the ghost drop time, and writes them to the
    BackgroundEventsJson tag; roastery.batches
    .set_background builds them from the saved series
    fan_level and heat_level columns, and roastery.artisan
    .stage_background_upload from the imported per sample
    levels. During a roast, core.evaluate_playback (on
    every temp change) fires the earliest due unfired
    event once, as a reserved prompt strip under the alarm
    banner: "Background: Fan 3", "Background: Heat 4",
    "Background: Drop now", amber, with a Dismiss button
    (core.dismiss_prompt). A showing prompt is never
    overwritten: later events queue behind it and fire on
    the first temp change after the dismiss, so each
    prompt stays readable. The Fan and Heat tags are never
    written by the playback path; the Tier 2 suite proves
    Fan and Heat stay at 5 through all three prompts.
    Settings gained toggles PlaybackEnabled (default on)
    and PlaybackSound (default off). Clearing the ghost
    clears the staged events and any pending prompt.
    Deviation: sound is visual only in this build.
    Perspective client scripting has no clean beep API
    (no supported audio playback from a view script on
    this platform), so the sound toggle is stored and
    shown, the prompt strip is the signal, and the
    Settings section says so in plain text. Verified live
    with a purpose built .alog ghost whose events land at
    30 s (Fan 3), 48 s (Heat 4) and a 75 s drop: the three
    prompts fired in order with the right levels.
12. Display smoothing for the BT line itself. DONE.
    Artisan: canvas.py smoothETBT() smooths the displayed
    temperature curves with the curve filter before drawing,
    separate from the delta computation. Roastery draws the
    bean line from raw samples; its curve filter only feeds
    the RoR math in core.compute_ror_series. Scope: an
    optional display only smoothing level in Settings,
    applied to the chart dataset, never to stored temps.
    Built 2026-11-17: Settings tag DisplaySmoothing
    (0 to 5, default 0, off) in the new Settings Playback
    sections. roastery.core.display_smoothed applies a
    trailing decay weighted average, the same weight family
    as the RoR curve filter, to the bean column only when
    core.build_live_curve assembles LiveCurveDS. RoR is
    computed from the raw points before smoothing and is
    untouched; the ghost, target and projection columns
    are untouched; stored samples stay raw. Verified live:
    with level 3 the displayed bean values differed from
    the raw samples (max over 0.3 F) and lagged them on a
    rising stretch, the RoR column was identical on and
    off, every stored sample was unchanged, and the saved
    batch series held the raw samples, not the smoothed
    display values.
13. Analyzer crosshair readout. DONE.
    Artisan: canvas.py togglecrosslines() and drawcross()
    with BTat() give a crosshair that reads out time, BT
    and RoR at any point on the curve, including background
    values. Roastery charts have no point readout. Scope:
    a tap or hover readout on the live and detail charts
    showing elapsed time, BT, RoR, ghost BT and deviation
    at that time, built to the no overlap rules.
    Built 2026-11-17: route chosen: a fixed analyzer
    strip under each chart, not floating chart text. The
    canvas chart in this build exposes no usable tap or
    hover point binding to drive a readout, so the
    selected time is a tag (AnalyzerSec on the live side,
    DetailAnalyzer/Sec on the detail side; minus 1 means
    Latest) stepped with -10s and +10s buttons or jumped
    with Latest, and roastery.core.analyzer_values
    interpolates BT, RoR, ghost BT and deviation (BT minus
    ghost BT) at that time from the real curve points and
    the one RoR implementation. The strip is a fixed 88 px
    flex block (controls row plus a four field values row)
    inside the chart card on the live Roast page and on
    BatchDetail (roastery.batches.detail_analyzer_refresh
    recomputes from the staged detail dataset), so nothing
    floats over axis labels or markers, and at 360 px the
    fields keep their own row under the chart; the phone
    HUD is untouched. Ghost and deviation fields read the
    placeholder when no ghost is loaded. Verified live on
    both charts: readout values matched independent
    recomputes from the raw samples and the stored series
    (BT within 0.6 F, RoR within tolerance, deviation
    within 1.2 F), and stepping moved the selection and
    the values together.
14. Auto event suggestions for Dry End and FC START. DONE.
    Artisan: canvas.py autoDRYflag and autoFCsFlag with
    main.py findDryEnd(), which locates the sample where BT
    crosses the phase boundary temperature in phases[1] and
    phases[2]. Scope: when live BT crosses the Settings
    phase target temperature, suggest the event with a
    prompt; Eric confirms with the normal button. Suggestion
    only, never an automatic stamp.
    Built 2026-11-17: roastery.core.evaluate_suggestions
    runs on every temp change while Roasting. When live BT
    reaches TargetDryEndTempF with Dry End unstamped (or
    TargetFCTempF with FC Start unstamped), it latches a
    suggestion once per crossing on the same reserved
    prompt strip as item 11 (blue): "BT crossed 320 F,
    stamp Dry End?" with a Dismiss button. The suggestion
    path writes no event tags and records no press; the
    normal dock button stamps the event, and stamping (or
    dismissing, or a reset) clears the suggestion. A
    playback prompt takes display precedence over a
    suggestion when both are pending. Per event Settings
    toggles SuggestDryEndEnabled and SuggestFcEnabled
    (both default on) sit in the Settings Playback
    sections. Verified live with targets set just above the
    running curve for a deterministic crossing: the Dry End
    suggestion appeared with the crossed temp in its text,
    no Dry End event or press row existed before
    confirmation, the dock Dry End button then stamped it
    and cleared the suggestion, and the FC Start suggestion
    was dismissed without stamping before FC Start was
    stamped normally.

### Tier 3: useful, after Tier 2

15. Curve display options (line width, style, markers, fill). DONE.
    Artisan: the CurveStyles settings group and curves.py
    CurvesDlg set per curve line style, draw style (default
    or step), line width, marker and marker size for BT, RoR,
    background and background RoR, plus fill under a curve.
    Roastery series styling is fixed in the chart props.
    Scope: Settings choices for BT, RoR and ghost width and
    style, RoR fill on or off, and event marker size, within
    the canvas chart props and the no overlap rules.
    Built 2026-11-17: a new Settings section, SettingsDisplay
    (Curve Display card), following the existing section
    pattern, tag backed on the CurrentBatch UDT: DispBtWidth
    (1 to 5) and DispBtStyle (solid, dashed, dotted),
    DispRorWidth and DispRorStyle, DispGhostWidth and
    DispGhostStyle (one pair drives both ghost series, BT
    and RoR), DispRorFill (boolean) and DispMarkerSize (2 to
    10). The main chart binds these tags onto the series
    props it already authors: line width and type on the
    bean, RoR and ghost series, the RoR area opacity (0.22
    on, 0 off, through the series area block the line chart
    honors), and the reference line endpoint size on the
    bean series (the event markers are the reference lines,
    so their endpoint dots are the markers). Literal hex
    colors are untouched; only width, dash, fill and marker
    size move. Defaults (BT 3 solid, RoR 2 solid, ghost 2
    solid, fill off, markers 4) reproduce the pre Tier 3
    look exactly. Draw style (step) is deliberately not
    offered: BT and RoR are smoothed samples, and the Fan
    and Heat strip already draws the stepped signals.
    Verified in verify_roastery_tier3b.py at the authored
    view level (series order, authored defaults, all nine
    prop bindings plus the fill binding) and live in session
    screenshots with distinctive values set (BT 5 dashed,
    RoR 4 dotted with fill, ghost 3 dashed, markers 9).
16. Phases from background, and phase watermarks on the chart. DONE.
    Artisan: phases.py (phasesGraphDlg) sets the phase
    boundary temperatures, with phasesfromBackgroundflag
    taking them from the loaded background and watermarksflag
    shading the phase bands on the chart. Roastery phase bar
    targets are times and a DTR percent in SettingsTargets.
    Scope: an option to take phase boundaries from the
    loaded ghost, and light phase band shading behind the
    live chart that follows the phase bar.
    Built 2026-11-17, in two halves. Phase bands: the 2027
    canvas line chart exposes no markArea in this build, so
    the bands use the mechanism the library already uses for
    overlays, dataset columns composed by
    roastery.core.build_live_curve. Four columns (bandDry,
    bandMai, bandDev, bandCool, appended at the end of
    LiveCurveDS so positional readers stay valid) hold the
    bean axis top (460 F) inside their phase range and null
    outside, with exact boundary rows inserted at the band
    edges, and four width 0 series with a solid area fill
    (opacity 0.12, literal hex: drying #eab308, maillard
    #f97316, development #dc2626, cooling #0284c7) draw
    first, behind every curve. A live probe proved the line
    component honors a series area block exactly like the
    area component. Band ranges come from
    core.phase_band_ranges: stamped phases end at their
    stamps, the phase still ahead ends at its effective
    target boundary, and Cooling runs from the drop stamp
    to the latest sample. No text lives inside the bands;
    their legend entries carry the phase names because an
    empty label makes the wrapper invent Series N names
    (proven live). Phases from background: staging a ghost
    (batch ghost or .alog file ghost) also stages its
    stamped phase boundaries onto session tags
    (BgPhaseDrySec, BgPhaseFcSec, BgPhaseDropSec, written by
    core.stage_bg_phases from batches.set_background and
    artisan.stage_background_upload, cleared by
    core.clear_background). The SettingsDisplay Phases From
    Background card holds the PhaseFromBg toggle and a
    readout of the staged boundaries. With the toggle on
    and staged values ordered, the PhasesBar target
    proportions, its DTR target, and the band boundaries
    all follow the ghost; the saved SettingsTargets tags
    (PhaseDryTargetSec, PhaseMaillardTargetSec,
    PhaseDevTargetSec, DTRTargetPct) are never written by
    any staging path. Staged is session level only; saved
    stays Eric's. Verified in verify_roastery_tier3b.py:
    band ranges read back from LiveCurveDS match the
    stamped phases during a simulated roast, the
    development band moves from the saved target boundary
    (600 s) to the ghost drop (585 s) when the toggle turns
    on, the phase bar dry segment follows the ghost share,
    and the saved target tags are byte identical before and
    after staging and toggling.
17. Full profile designer for the target plan. DONE.
    Artisan: designer.py (designerconfigDlg, pointDlg)
    edits a target profile point by point with time order
    validation. Roastery target is four fixed points.
    Scope: allow adding and editing extra target points,
    stored the same way, with the deviation tile and plan
    line reading the longer list.
    Built 2026-11-17: the plan is now a variable length list
    stored as JSON ([sec, tempF] pairs) on the TargetPlanJson
    member of CurrentBatch, read only through
    roastery.core.target_plan_points. That was the storage
    choice because the four fixed tags cannot hold a longer
    list; the JSON tag survives restarts like every standing
    tag, and when it is empty or invalid the plan falls back
    to the legacy four point tags, so the existing four
    points are the default list with no separate migration.
    Saving a plan syncs two legacy scalars (first point temp
    to TargetChargeTempF, last point to TargetDropSec and
    TargetDropTempF, which the alarms and metadata read);
    the dry end and FC legacy tags are not synced because
    they also carry the suggestion thresholds. The Settings
    Targets section gained the Target Plan Designer: a read
    only table of the plan points (fixed 190px basis, the
    Tier 1 virtualized table lesson) plus an editor staging
    one point in the TargetEditor tags (the AlarmEditor
    precedent), with Load Point, Save Point, Add Point,
    Delete Point and Reset to Four Points buttons, all thin
    handlers into roastery.core (target_editor_load, save,
    add, delete, target_plan_reset). Validation follows
    Artisan and the BatchEdit ordered time pattern: 2 to 12
    points, first point anchored at 0 sec, times strictly
    increasing, temps 50 to 500 F; a violation is REJECTED
    with a visible note and nothing is saved (no silent
    sorting). The charge point cannot be deleted.
    Both readers moved to the list: build_overlays builds
    the plan line from target_plan_points, and the deviation
    tile now binds the library published PlanDeviationText
    tag (roastery.core.update_plan_deviation, the
    BgDeviationText pattern), because a view expression can
    only interpolate the old four fixed points; the contract
    is unchanged (signed F while Roasting, two dashes
    otherwise). The saved batch document target block also
    carries the full points list beside the legacy fields.
    Default behavior is unchanged: with the JSON tag empty
    the plan is exactly the old four points. Verified live
    in verify_roastery_tier3c.py: points added, edited and
    deleted through the real UI, out of order Add and Save
    both rejected with the plan unchanged, the plan overlay
    dataset and the deviation text read a 6 point plan, and
    Reset returned to the default four.
18. Batch export beyond .alog (CSV, JSON, printable report). DONE.
    Artisan: main.py fileExportCSV, fileExportJSON,
    fileExportExcel and the PDF and HTML report builders
    (pdfReport, htmlReport, productionReport) export a
    profile and its statistics. Roastery exports only .alog
    from BatchDetail. Scope: CSV and JSON download of the
    series plus document from BatchDetail, and a printable
    summary. Ranking and production reports are SKIP.
    Built 2026-11-17: three more buttons sit beside Export
    .alog on BatchDetail (Export CSV, Export JSON, Print
    Summary; the action row now wraps so all six actions fit
    at 360px). All three are thin handlers into
    roastery.batches: build_csv_text emits a metadata header
    section (comment lines carrying the document key fields:
    batch, bean, origin, start and end, degree, drop temp,
    weights, loss, AUC, source) followed by the series table
    (time_sec, time_mmss, bean_temp_f, rate_of_rise_f_per_min,
    fan_level, heat_level) from the stored batch_series rows;
    build_json_text downloads one object with the relational
    fields, the full batch document and the full series;
    build_summary_html downloads a standalone printable HTML
    summary (summary, loss/yield/density with friendly labels,
    phase analysis, events, metadata, curve statistics) that
    is opened and printed from the browser. Downloads use
    system.perspective.download, the .alog route. Ranking and
    production reports stay skipped, per scope. Verified live
    in verify_roastery_tier3a.py: all three downloads fire for
    seeded batch 1042 and their series and document values
    match an independent recompute from Postgres.
19. Statistics summary on the chart and in the HUD. DONE
    (revised scope: under the live chart and on BatchDetail;
    nothing added to the HUD, which is provably full at
    360px).
    Artisan: canvas.py writestatistics() writes the phase
    times and percents onto the chart itself, statistics.py
    configures the summary, and main.py getPhasesLCDsData()
    drives the phases LCD modes. Roastery shows phases only
    in the PhasesBar and Summary views. Scope: a compact
    phase summary line under the live chart title, using
    values already computed, checked at 360px.
    Built 2026-11-17: a single line label (new style class
    roast-stats-line, 11px semibold, the caption scale,
    nowrap with ellipsis as the backstop) sits directly
    under the live chart on RoastPage in both layouts,
    between the chart and the analyzer strip, reading
    "Dry 4:30 38% · Mai 3:45 32% · Dev 2:10 30% · DTR 22%"
    in form. It carries no new math: one expression reuses
    the PhasesBar and Summary formulas (stamped phase
    seconds, shares of drop time once dropped, effective
    target proportions before that, ghost proportions when
    phases from background is on, DTR as in Summary), with
    m:ss times and an integer DTR so the longest form fits
    the 286px phone chart card whole at 360px. The same
    line sits on BatchDetail's chart card, computed by
    roastery.batches.detail_startup from the stored
    document phases into view.custom.dStatsLine. Verified
    in verify_roastery_tier3b.py: the live line matches the
    stamped phase times mid roast and after drop, its
    scrollWidth equals its clientWidth at 360px with all
    phases populated, and the BatchDetail line equals the
    line recomputed from the seeded batch 1042 document in
    Postgres.
20. Between batch protocol, BT only subset. DONE.
    Artisan: main.py calcBBPMetrics() and the bbp keys
    record the previous roast end to the next charge: total
    BBP time, bottom temperature, and the RoR into and out
    of the bottom. Scope: after DROP, keep recording BT
    until the next CHARGE and store those four values on
    the next batch. The ET half of BBP is SKIP (below).
    Built 2026-11-17, BT only (the ET half stays skipped,
    single sensor): roastery.core.drop opens the window
    (first sample is the drop temp at t = 0); the existing
    BeanTempF change capture path (on_bean_temp) also
    stages every change while the state is Dropped, Cooling
    or Complete into the BbpSamplesDS dataset tag
    (t_offset_sec is float seconds since DROP). The staging
    lives outside the batch workspace, in the Bbp tag
    folder (the Calculator folder precedent) plus that
    dataset tag, so the window survives Save Batch for the
    roast that just dropped. Opening a window at DROP does
    not clear the staged metrics, which belong to the batch
    now running until its Save Batch consumes them
    (core.bbp_clear_staged, called by save_current_batch).
    roastery.core.charge closes
    the window before anything else: it appends the final
    sample at the charge temp and moment, computes the
    metrics with roastery.core.bbp_compute, stages them on
    the Bbp tags, and clears the samples; a CHARGE with no
    open window clears any stale staged metrics instead.
    roastery.batches.build_document then writes the staged
    values into the next batch document as a bbp
    subdocument (time_sec, bottom_temp_f, ror_in_f_min,
    ror_out_f_min), and BatchDetail shows them as one
    Between batch (BBP) line in the Summary card when the
    subdocument is present; batches with no preceding drop
    carry no bbp key and show nothing. Metric definitions,
    all from the staged samples S = [(t, BT)]: time_sec is
    the last sample t minus the first (DROP to CHARGE);
    bottom_temp_f is the minimum BT, the bottom being the
    FIRST sample holding it at time t_b; the RoR span is
    the library RoR delta span (RoRDeltaSpanSec through
    ror_params, default 20 s, 0 falling back to 20), the
    same span convention compute_ror_series differentiates
    over; ror_in_f_min is (bottom minus BT interpolated at
    max(t_first, t_b minus span)) times 60 over (t_b minus
    that start), or 0.0 when the bottom is the first
    sample; ror_out_f_min is (BT interpolated at
    min(t_last, t_b plus span) minus bottom) times 60 over
    (that end minus t_b), or 0.0 when the bottom is the
    last sample. Edge cases: the first ever roast has no
    staged window and its document has no bbp; a CHARGE
    with no DROP before it finalizes nothing; Reset
    discards the window and any staged metrics (decided:
    reset_batch calls _bbp_clear_all, so a reset workspace,
    including New Roast, starts a fresh between batch
    story). Verified live in verify_roastery_tier3c.py: a
    full simulated cycle (roast, DROP, a falling then
    rising BT window driven through the WebSocket source,
    CHARGE, Save) stored a bbp subdocument matching an
    independent recompute from the staged samples, and
    BatchDetail showed all four values.
21. Yield and conversion calculator. DONE.
    Artisan: calculator.py (calculatorDlg) converts
    temperatures, weights and volumes and calculates yield
    from a loss percent. Scope: a small calculator card in
    Settings or on BatchDetail for expected weight out from
    charge weight and a target loss percent.
    Built 2026-11-17: a Yield and Conversion Calculator card
    on BatchDetail, below Metadata (near the batch weights,
    which is where the numbers belong; Settings was not
    touched). It is seeded from the staged batch by
    roastery.batches.calculator_seed, called from
    detail_startup, so it opens on this batch's charge and
    out weights (batch 1042 seeds 200 g in, 172 g out, and
    the reverse loss reads its own 14.0%). The inputs are
    numeric fields bound bidirectionally to a new Calculator
    tag folder (the proven tag path; view.custom bindings do
    not write back in this build), and every readout is an
    expression tag in that folder, so the math is live with
    no handler code: ExpectedOutG and ExpectedOutOz (forward
    yield from charge and target loss percent), ActualLossPct
    (the reverse, from charge and weight out), TempC from
    TempF, TempFOut from TempCIn, ConvOz from ConvG and
    ConvGOut from ConvOzIn. The folder is also declared in
    setup_roastery_v4_tags.py so a full tag rebuild keeps it.
    Verified live in verify_roastery_tier3a.py by driving
    the real inputs: 250 g at 12% gives 220.0 g out, out
    220 g from 250 g gives 12.0% loss, 212 F is 100.0 C,
    100 C is 212.0 F, 100 g is 3.53 oz and 10 oz is 283.5 g,
    in the tags and in the rendered card, at desktop and
    360px with no overflow.

### Already have (HAVE)

22. Live BT and RoR curves on canvas charts. HAVE.
    Artisan canvas.py draws temp2 and delta2 live. Roastery:
    core.build_live_curve and the v4.4 canvas charts, BT and
    RoR on an elapsed mm:ss axis.
23. RoR math suite. HAVE.
    Artisan canvas.py compute_ror and util.py arrayRoR with
    deltaBTspan, curvefilter, deltaBTfilter, polyfitRoRcalc,
    optimalSmoothing with Savitzky-Golay, filterDropOuts and
    RoRlimit clipping. Roastery: core.compute_ror_series and
    core.ror_params with the same options in SettingsRor,
    one implementation for live, saved and ghost. Note:
    Artisan deltaBTsamples is derived from span over sampling
    interval; Roastery applies the span in seconds against
    real timestamps, which is the same math, so there is no
    separate samples setting to build.
24. Standard and custom events with captured temps. HAVE.
    Artisan timeindex events and specialevents. Roastery:
    core.stamp_event and stamp_custom, seven standard events
    plus Cool, and four named custom events.
25. Phases, DTR and phase bar targets. HAVE.
    Artisan canvas.py calcStatistics phase times and ratios.
    Roastery: PhasesBar, Summary and SettingsTargets phase
    target seconds and DTR target percent.
26. Saved batch AUC, basic form. HAVE.
    Artisan profileAUC. Roastery: batches.curve_auc at save
    time. The configurable and live form is Tier 1 item 5.
27. Roast degree from drop temperature. HAVE.
    Roastery: batches.roast_degree, shown in Summary and Log.
28. Fan and Heat steppers, traces and press capture. HAVE.
    Artisan event sliders in events.py, adapted to 1 to 9
    steppers. Roastery: core.stepper, record_press, the
    levels strip and batch_events rows.
29. Single ghost background from a saved batch. HAVE.
    Artisan background profile, basic form. Roastery:
    batches.set_background. Extensions are Tier 1 items 1
    and 2 and Tier 2 items 10 and 11.
30. Four point target plan and deviation against plan. HAVE.
    Artisan designer, lite form. Roastery: core.build_overlays
    and the deviation tile. Extension is Tier 3 item 17.
31. Roast log CRUD with slide over editor and event time editing. HAVE.
    Artisan roastlog.py and batches.py, adapted to Postgres
    named queries. Roastery: batches panel, editor with
    ordered time validation and phase and DTR recompute.
32. Artisan .alog import and export, lossless. HAVE.
    Artisan getProfile, serialize and computed block.
    Roastery: roastery.artisan import on the Log page and
    export from BatchDetail, with the artisan subdocument.
33. Phase Analysis table with offline turning point. HAVE.
    Roastery: batches._phase_analysis on BatchDetail. The
    live turning point is Tier 1 item 4, and the table
    completion is Tier 2 item 7.
34. Settings in sections, written live to tags. HAVE.
    Roastery: SettingsPage with Roaster, Targets, RoR,
    Alarms, Metadata defaults and Custom Events sections.
35. Shell layout: HUD, docks, tab bar, tiles. HAVE.
    The Roastery mapping of Artisan LCD readouts (main.py
    LCD boxes and large LCD windows) to the mobile HUD dock,
    tiles and bottom tab bar. A separate large readout
    window is SKIP below as a duplicate of these.

### Skipped (SKIP)

36. ET curve and every ET display toggle. SKIP, single sensor.
    Artisan temp1 and the toggleETCurve family in main.py
    need an environment probe. The SR800 has one bean temp
    probe and no ET probe, so there is nothing to show.
    Imported ET arrays stay preserved in the artisan
    subdocument only.
37. Delta ET (the RoR of ET). SKIP, single sensor.
    Artisan delta1 in canvas.py is computed from temp1.
    No ET probe means no delta ET.
38. ET minus BT area and the paired AUC outputs. SKIP, single sensor.
    Artisan main.py ts() and profileAUC() return an ET AUC,
    a BT AUC and the area between ET and BT. Only the BT
    AUC is buildable, and it is Tier 1 item 5.
39. MET (maximum ET). SKIP, single sensor.
    Artisan computed.MET is the maximum temp1 between the
    turning point and DROP. No ET probe, no MET.
40. ET projection and background ET and background delta curves. SKIP, single sensor.
    Artisan canvas.py updateProjection() ET branch and the
    background delta toggles in main.py all read temp1 or
    delta1, which do not exist on this roaster.
41. ET half of curve similarity and of BBP. SKIP, single sensor.
    Artisan curveSimilarity() returns det and dbt, and the
    bbp keys carry drop ET values. The BT halves are Tier 2
    item 10 and Tier 3 item 20; the ET halves need a second
    probe.
42. Extra device curves as live channels. SKIP, single sensor in practice.
    Artisan extratemp1 and extratemp2 channels in atypes.py
    assume extra temperature devices. Eric has no extra
    probe hardware; imported extra arrays stay in the
    artisan subdocument for lossless export only.
43. PID, ramp and soak, and gain scheduling. SKIP, by design.
    Artisan pid.py, pid_dialogs.py and the sv and pid keys
    drive a controlled heater. Eric confirmed the SR800
    setup has no PID and manual Fan and Heat are the control
    surface, so no PID appears anywhere in Roastery.
44. Auto CHARGE and Auto DROP stamping. SKIP, for now.
    Artisan main.py BTbreak() with autoChargeMode and
    autoDropMode detects charge and drop from BT breaks.
    It is BT only, so the sensor is not the blocker; the
    blocker is trust. A false stamp corrupts phases, DTR
    and the saved record, and Eric stamps from his phone
    as the remote control. Revisit only if he asks for it.
    The suggestion pattern in Tier 2 item 14 is the safe
    form of automation here.
45. Flavor wheel and cupping profile scoring. SKIP, out of scope.
    Artisan wheels.py and cup_profile.py score flavors after
    the roast. Cupping is a post roast workflow outside a
    roast time console, as settled in the v2 mapping; the
    cupping notes text field in Tier 1 item 3 is the capture
    point.
46. Green stock, inventory and Artisan Plus. SKIP, separate system.
    Artisan plus stock, store, blend and schedule fields in
    atypes.py belong to inventory and production scheduling,
    not to roast time control and logging on a home roaster.
47. Energy, BTU and CO2 metering. SKIP, no meter source.
    Artisan canvas.py calcEnergyuse() and the load and meter
    keys need configured burner or electric meters. The
    SR800 setup has no meter feed, so any number would be
    invented.
48. Ranking and production reports. SKIP, production feature.
    Artisan main.py rankingReport() and productionReport()
    compare batches across a production run. A home roaster
    gets the same value from Tier 1 item 2 comparison and
    Tier 3 item 18 single batch export.
49. Scales, WebLCDs, external programs and device buses. SKIP, hardware not present.
    Artisan scale.py, weblcds.py, externalprogram hooks and
    the Modbus, S7 and serial device layers assume hardware
    Eric does not have attached to the SR800. The WebSocket
    and simulated sources he does have are already built.
50. Separate large LCD readout windows. SKIP, duplicate.
    Artisan main.py largeDeltaLCDs() and largePhasesLCDs()
    open big readout windows. The HUD dock, tiles and
    desktop trend layout already cover this need.

### Build order (after the three Tier 1 gaps)

Status 2026-11-17: all six Tier 1 items are built and
verified live (see the Built notes on items 1 to 6 above and
scripts/verify_roastery_tier1.py). The order below is the
record of how they were sequenced. Tier 2 items 7 to 14 are
also built and verified live (Built notes on items 7 to 14
above, scripts/verify_roastery_tier2.py, 87 checks). Next:
transaction groups, then the mastery learning backlog.

Implement Tier 1 items 1, 2 and 3 first, in that order.
Then, in this exact order:

1. Live turning point detection. Scope: detect and display
   TP live and store it in the document. Module:
   roastery.core. Needs: chart changes (marker). No Settings
   or form changes.
2. Live AUC with begin, base, target and guide. Scope: live
   AUC tile, since FC START AUC, guide time readout, saved
   values aligned to the same math. Modules: roastery.core
   and roastery.batches. Needs: Settings additions (AUC
   section fields), chart changes (guide line optional).
3. Full alarm table. Scope: editable alarm list evaluated
   in the library, banner and message actions only.
   Module: roastery.core. Needs: Settings additions (alarm
   table replaces the lite rows). No chart or form changes.
4. Phase analytics completion. Scope: TP based dry RoR,
   per phase AUC, FC START RoR, per phase delta temp and
   cool phase in the table and document. Module:
   roastery.batches. Needs: no Settings, chart or form
   changes; BatchDetail display only.
5. Loss, yield and density computations. Scope: defects
   loss, total loss and yield, volume gain, moisture and
   organic loss, green and roasted density, computed at
   save and shown in Summary and BatchDetail. Module:
   roastery.batches, using Tier 1 item 3 form fields.
   Needs: form and metadata changes (the Tier 1 fields).
   No Settings or chart changes.
6. BT projection lines. Scope: dashed linear projection on
   the live chart, quadratic mode after five minutes.
   Module: roastery.core. Needs: Settings additions
   (toggle and mode), chart changes (projection series).
7. Deviation from background and BT similarity score.
   Scope: live deviation against the ghost, similarity on
   BatchDetail. Modules: roastery.core and
   roastery.batches. Needs: chart changes (none beyond the
   existing ghost series), no Settings or form changes.
8. Background playback prompts. Scope: banner prompts at
   ghost Fan and Heat changes and ghost DROP, with the
   suggested level. Module: roastery.core. Needs:
   Settings additions (playback on or off, sound on or
   off). No chart or form changes.
9. Auto event suggestions for Dry End and FC START.
   Scope: prompt on phase temperature crossing, confirmed
   by the normal buttons. Module: roastery.core. Needs:
   Settings additions (suggestions on or off per event).
   No chart or form changes.
10. Display smoothing for the BT line. Scope: display only
    smoothing level applied to chart datasets. Module:
    roastery.core. Needs: Settings additions (level),
    chart changes (smoothed series source).
11. Analyzer crosshair readout. Scope: tap or hover values
    for time, BT, RoR, ghost BT and deviation. Module:
    roastery.core for the data shaping. Needs: chart
    changes only.
12. Curve display options. Scope: width and style for BT,
    RoR and ghost, RoR fill toggle, marker size. Module:
    roastery.core for chart dataset and series building.
    Needs: Settings additions, chart changes.
13. Phases from background and chart phase bands. Scope:
    ghost derived phase boundaries and light band shading.
    Modules: roastery.batches and roastery.core. Needs:
    Settings additions (source toggle), chart changes.
14. Full profile designer for the target plan. Scope:
    editable extra target points with time order checks.
    Module: roastery.core. Needs: form and metadata
    changes (target editor), chart changes (plan line
    already reads the point list).
15. Statistics summary line under the chart. Scope: phase
    times and percents in one compact line, live. Module:
    roastery.core values, view change only. Needs: no
    Settings or form changes; layout change checked at
    360px for overlap.
16. Batch export beyond .alog. Scope: CSV and JSON
    downloads and a printable summary from BatchDetail.
    Module: roastery.artisan for the file builders, with
    roastery.batches supplying the document. Needs: no
    Settings or chart changes.
17. Between batch protocol, BT only. Scope: record BT
    from DROP to the next CHARGE and store the four BBP
    values on the next batch. Modules: roastery.core and
    roastery.batches. Needs: form and metadata changes
    (display fields on BatchDetail only).
18. Yield and conversion calculator. Scope: expected
    weight out from charge weight and target loss, plus
    unit conversions. Module: roastery.batches. Needs:
    form and metadata changes (a calculator card). No
    Settings or chart changes.

## RoasterSim SR800 curve rebuild (2026-11-17)

The old RoasterSim program was naive monotonic ramps (200 to
300 to 352 to 385 to 397 to 412 F) with a duplicated final row
that made the loop wrap jump from 412 back to 200, a step
discontinuity. It never dipped, so live turning point
detection confirmed at elapsed 0, and the charge moment plus
the wrap produced a plunge transient on the HUD (RoR minus
82 F/min at 00:07 with BT at 357 F). The simulator now plays
a roast shaped program that resembles a real FreshRoast
SR800 curve on the single bean probe.

### What the Programmable Device Simulator can and cannot do

Measured live on a scratch device (deleted afterwards) and
in the driver jar:

- Value sources are only the documented functions (sine,
  cosine, square, triangle, ramp, realistic, random, list,
  qv, readonly) plus static values. A ValueSource cannot
  reference another value in the same device (a row sourced
  from a sibling name fails with a factory error and bad
  quality), so the program cannot react to Charge or to
  Fan and Heat by itself.
- list() does not step one value per interval in this build,
  and ramp() progress is anchored to wall clock, not to the
  program interval, so neither can play a shaped curve at a
  variable rate. Static stepped rows do scale exactly with
  the device base rate.
- The device exposes meta nodes as OPC items under
  [Device][Controls]: reset, pause, repeat, baseRateNode and
  programCounter. Writes work: pause freezes the counter,
  reset returns to interval 0, and the base rate retimes
  playback. Re-uploading instructions.csv or re-saving the
  device config restarts the program clock.

### The mechanism

- The program is one static BeanTemp row per program second,
  1021 rows generated deterministically in
  scripts/setup_roastery_v4_tags.py (function _build_sim_csv)
  and mirrored into the packaged device resource. Cosine
  eased dip, piecewise linear rise anchors, a 9 s moving
  average for smoothing, and seeded jitter of plus or minus
  0.6 F (zero at the charge and wrap samples). Charge and
  the final sample are both pinned to exactly 392.0 F, so
  the loop wrap step is 0.0 F and the largest single step
  anywhere in the cycle is 5.0 F (mid dip slope plus jitter).
- Four OPC tags on the Roastery folder (SimReset, SimPause,
  SimBaseRate, SimProgramCounter) bind the device meta
  nodes. The glue lives in roastery.core, simulator sync
  section, and only acts when ActiveSource is Simulated:
  charge() aligns the program to interval 0 at the current
  Fan and Heat rate, reset_batch() parks the program at
  interval 0 paused on the 392 F idle reading, and stepper()
  reapplies the rate after a level change.
- Fan and Heat act on playback speed: speed = 1 + 0.06 *
  (heat - 5) - 0.035 * (fan - 5), clamped 0.6 to 1.45, and
  the base rate is 1000 / speed ms clamped 650 to 1700.
  Measured live, Fan 5: Heat 9 (810 ms) reached 300 F at
  226 s from charge, Heat 1 (1320 ms) at 369 s, and the
  default 5 / 5 roast crossed at about 278 s.
- evaluate_suggestions now waits for a confirmed turning
  point before offering Dry End or FC Start, as its own
  docstring already claimed. With a 392 F charge above both
  phase targets, the suggestions previously fired at elapsed
  1 to 2 s and an early FC stamp stopped TP tracking for the
  whole roast.

### The curve (program values, bean probe F)

Charge 392.0. Dip low 184.8 at 73 s. 300 F crossed at 278 s,
310 at 299 s (dry end zone 300 to 320 at 4 to 5 min). 385 F
at 538 s (8:58, first crack zone). Drop anchor 420.9 at
720 s. Cooling bottom 342.4, then reheat to the 392.0 idle
reading at 1020 s, where the program wraps seamlessly.

Verified live through the app flow at Fan 5 / Heat 5: charge
temp 392.0, turning point confirmed at 73 s and 184.8 F, RoR
37.8 at 100 s declining through 31.1 at 250 s, 27.0 at
300 s, 18.8 at 400 s, 16.4 at 500 s and about 13 to 14 in
development, Dry End suggestion at 277 s (stamped 279 s,
300.3 F), FC Start suggestion at 538 s (stamped 539 s,
384.9 F), drop stamped 707 s at 419.4 F, AUC live 1240.2 at
drop. Development RoR reads a touch above the 5 to 12
target band (13 to 14 measured); noted honestly rather than
retuned at the cost of the drop window. Screenshot:
showcase/shots/polish-sim-full-roast-desktop.png in the lab.

### Tradeoffs and one honest conflict

- The simulator has no seek. The program drop point (720 s)
  is nominal; a Drop pressed far from it leaves the probe on
  the program timeline (right after the verified drop at
  707 s the reading still rose briefly to the 720 s anchor
  before cooling). Cooling and the return to idle happen on
  the program's own schedule, and reset_batch parks the
  program so the next charge starts clean.
- Fan and Heat scale the whole curve's speed rather than
  reshaping phases independently; that is the closest
  faithful behavior the device supports.
- RoR floor conflict: the acceptance ask was that live RoR
  during the dip never go below about minus 9 F/min. That is
  arithmetically incompatible with the requested dip
  itself: falling 392 to about 185 F in about 73 s averages
  about minus 170 F/min, and the eased peak slope is
  steeper. Measured minimum RateOfRiseF over 1 s samples of
  the first 120 s of a simulated roast: minus 268.6 F/min
  (the genuine dip slope; the app's RoR smoothing reads the
  steepest part of the fall). What is gone is the defect in
  the screenshot: there is no step discontinuity anywhere
  (largest 1 s step 5.0 F in the program data, 0.0 F at the
  wrap), and RoR at 00:07 reads about minus 35 and moves
  smoothly instead of spiking to minus 82 off a 412 to 200
  jump.

### Verification

Suites after the rebuild: verify_roastery_ror.py all checks
passed (live window skip by design while the sim sits parked
at the flat idle reading; the offline proof is the
authority). verify_roastery_tier1.py 42 PASS 0 FAIL.
verify_roastery_tier2.py 87 PASS 0 FAIL on the retry (the
first run flaked 84 PASS 3 FAIL on the known load sensitive
playback timing checks: levels left at 6 / 6 and 4 leftover
press rows; the clean retry from the same baseline passed
everything). validate_roastery_artisan.py VALIDATION PASS
(26 views served and deep equal). validate_chartlab.py
clean, no warnings. verify_roastery_v4.py: 37 PASS 0 FAIL,
then the suite stops in the batch slide over editor because
the form's Save Batch button never enables; reproduced by
hand on a seeded batch (1042) as well as the suite batch,
with several event time fields rendering empty, so it is a
pre-existing editor form issue in the current build and not
an effect of the simulator change. One lab incident during
verification: the Maker trial expired mid roast (SQL
historian demo expiry froze the tag event pipeline and the
PressEvents group at 01:26:09), recovered with the trial
reset API route; a later VM replacement was recovered with
recover-lab.sh plus the RoastLog reseed back to 7 batches,
101 series rows, 0 events.
## Polish round 1: library and data correctness (2026-11-17)

Seven fixes from Eric's screenshot review of the Tier 1 to 3
build, all in the library and the data it publishes (the dock
view rework that consumes item 7's contract is the next
chunk). Verified by the new suite
scripts/verify_roastery_polish1.py (46 checks) plus the full
battery; counts at the end of this section.

### Item 0: the BatchEdit editor regression

Symptom: the slide over editor's Save Batch button never
enabled, and event fields looked empty, worst on the seeded
batches. Root cause, proven by hand on batch 1042:
roastery.batches.edit_form_data_for filled every metadata
member the stored document does not carry with a hard 0 or
empty string. The seeded documents are sparse (batch 1042
has no HarvestYear and no TargetDropTempF in its metadata),
so the prefill put HarvestYear 0 into a field whose enabled
constraint is min 1900 and TargetDropTempF 0 into a field
with min 200. The form (submit autoDisable) was permanently
invalid, so Save Batch stayed disabled no matter what was
typed into the event fields, and two metadata fields showed
the bogus zeros. Batches saved from the live workspace
carry full metadata, which is why the v4 suite's own editor
section still passed while the seeded batches were broken.
Fix: a missing member now falls back to the standing tag
value (roastery.core.config_form_data, the same values
create mode starts from: HarvestYear 2025, TargetDropTempF
415, ChargeWeightG 200), which is always inside the field
constraints. The polish suite opens the editor on batch
1042, asserts the in range prefill, edits Dry End, saves,
and restores the document afterwards.

The suite's own editor section also stalled
intermittently (the 37 PASS stop in the regression
report), and that half was in the suite's input method,
proven by tracing a live run: the prefill had landed
(FC Start showed the stamped 00:13) but the form was
pristine, and Playwright's fill() then set the DOM value
without the key events the form's change tracking
listens for, so the edit never registered and Save Batch
stayed disabled for the full click timeout. Whether the
programmatic prefill itself marks the form dirty at open
is racy in a long lived session (both states were
observed minutes apart). The suite now types like a user
(click, select all, sequential keys, Tab, with a read
back that retries if a late prefill refresh stomped the
value), waits for the prefill before editing, and waits
for the button to enable before clicking. With that, the
editor section (out of order rejection, valid edit,
reload) passes end to end.

Two more v4 failures from the same period were simulator
rebuild fallout, fixed in the suite's procedure (the same
treatment Tier 2 got in the rebuild): the PressEvents
transaction group scans at 250 ms, so the suite's back to
back Fan and Heat stepper clicks coalesced into one
batch_events row; the clicks are now paced like a human's.
And the suite's quick roast used to drop during the dip,
saving an all dip curve whose ghost RoR is legitimately
empty under the offline limits. Live turning point
tracking also stops at the First Crack Start stamp (the
Artisan charge to first crack window), and the suite
stamped FC Start at 13 s, before the dip bottoms at
about 37 s, so the TP could never confirm in its flow;
the suite now awaits the TP confirmation (about 45 s)
before stamping FC Start, and the live curve RoR column
then carries the rise (51 drawn values in the final run).

### Item 1: phase band stability

Eric's headline complaint: the shaded phase bands on the
live chart blipped and re-rendered every second. Cause:
build_live_curve recomposed the band dataset columns on
every temperature change (the band value was written into
every merged row inside each range) and the cooling band
ran to the latest sample, so it grew every tick. Fix: the
bands are stable artifacts. phase_band_ranges no longer
depends on the latest sample or on now (the cooling band
runs to the fixed horizon: the effective drop boundary,
or two minutes past a drop stamped later than that), and
build_live_curve writes each band as exactly its two
boundary rows. The band series now run connectNulls, so
two points draw the full strip with the same colors and
0.12 fill. The band columns change only when a phase
boundary changes: an event stamp, a target edit, a ghost
staged or cleared. Proof in the polish suite: the band
columns of LiveCurveDS are byte identical across 10 ticks
of a live roast while the bean values keep changing, and
the pre stamp signature is exactly the six boundary points
(0 and 270 s, 270 and 480 s, 480 and 630 s at the default
targets).

### Item 2: the axis read clock times, not elapsed

Eric's phone screenshots showed axis ticks like 17:02 and
17:03 under the Elapsed (mm:ss) title. Cause: every chart
dataset anchored its x values to the Unix epoch
(Date(0) + elapsed seconds). A canvas time axis formats
ticks in the browser's timezone; epoch midnight UTC is
17:00 in Denver, so the first minutes of a roast read as
wall clock times. The lab's own screenshots never showed
it because the test browsers ran in UTC. Fix: all datasets
now anchor to roastery.core.AXIS_BASE_MS, 946710000000,
which is midnight in America/Denver on 2000-01-01, so a
Denver browser labels the first hour of elapsed time
00:00, 00:15 and so on, the mm:ss reading the title
promises. The anchor is a constant, never derived from
the gateway clock. It is applied in one place per dataset:
live curve, marks, reference lines, plan and ghost
overlays, projection, detail, and the compare chart; the
six canvas chart instances carry axis minimum
AXIS_BASE_MS + 1000; roastery.batches._detail_points
subtracts the base when reading DetailDS back. The
verification suites that read dataset timestamps
(v4, Tier 2, Tier 3b, Tier 3c) normalize by the same
constant. Screenshots in an America/Denver browser at
about 10 s elapsed (polish1-axis-desktop.png,
polish1-axis-360.png) show ticks 00:01 to 00:11.

### Item 3: suggestion guard, falling crossing verified

The simulator rebuild had already made
evaluate_suggestions wait for a confirmed turning point.
The polish suite verifies the falling case explicitly on
the stepped sim: charge at 392 F with the Dry End target
at 300 F, BT falls through the target during the dip, and
no suggestion fires before the turning point confirms;
the Dry End suggestion then fires on the rising crossing
(observed firing at BT 300.3 F). No library change was
needed; the guard covers the case because suggestions
only evaluate after TP confirmation, and a target crossed
on the fall is below the bean temp again by then only on
the rise. Note the app's turning point is wall clock
elapsed: at the 2x sim rate used in the test the dip
bottom (program 73 s) confirms at about 37 s of wall time.

### Item 4: pre TP RoR display, the Artisan convention

Eric hated the wild negative RoR readings during the dip
(minus 82 on the old sim; the new sim's true dip slope is
about minus 270 F/min at its steepest, and minus 50 was
observed live in the polish run). A true dip cannot read
single digit negatives, and faking it would corrupt the
RoR math and the stored samples, so Roastery now does
what Artisan does: gate the DISPLAY, never the data.
Artisan 5.0.0 evidence, from ~/workspace/artisan-src:

- artisanlib/canvas.py line 1634: RoRlimitFlag defaults
  to True. In sample_processing (line 4474), lines 4851
  to 4858: with the flag on, a plotted delta value
  outside the RoR limits is replaced by None, under the
  code's own comment 'limit displayed RoR (only before
  TP is recognized)'. The blanked value is what the
  delta arrays and the drawn line receive.
- Lines 4863 to 4876: the drawn RoR line starts at
  ror_start, the CHARGE index plus round(delta filter
  / 2) plus max(2, delta samples + 1); with no CHARGE
  the line data is empty lists.
- updateLCDs (line 5175): the delta LCD shows the '--'
  placeholder (resLCD, line 5182) whenever the delta
  value at the index is None (lines 5221 to 5222).
- artisanlib/util.py line 1288, computeDeltas: offline
  delta values exist only between the CHARGE and DROP
  indices; everything outside is None.

Roastery's implementation of the same convention, in
roastery.core for the live display path only: the live
curve's RoR column is blank for samples before the
confirmed turning point and for any value outside
[RoRClipLowF, RoRClipHighF] (the existing clip tags,
minus 18 and 81 by default), and the HUD reads the new
library published RateOfRiseDisplayText: '--' before TP
and outside the limits, the true value after TP. The
projection still extends from the true ungated RoR (it
is a forecast, not a display of the past). Stored
samples, batch_series and the offline recomputation are
untouched and stay truthful. Observed in the polish run:
true RoR minus 50.8 F/min in the dip with the HUD at
'--', the HUD matching the RoR tag to the integer after
TP, and about 38 to 46 F/min early in drying.

### Item 5: stats line consistency

The screenshots showed 'Dry --:-- 43% · Mai --:-- 33% ·
Dev --:-- 24% · DTR --': durations from the stamped
events (missing, so --:--) next to percentages from the
target plan splits. The computation now lives in the
library (roastery.core.stats_line_text, published to the
StatsLineText tag the Roast page labels bind): a
completed phase shows its actual duration and its actual
share of the total (the drop total once dropped, elapsed
so far before); the current phase shows its live
duration and live share; future phases show -- for both;
DTR shows -- until Drop, then the actual value. The
compact format and the roast-stats-line style class are
unchanged. BatchDetail's stored document line had the
smaller cousin of the same bug (a missing phase formatted
as 0:00 next to a -- share); _ms in detail_startup now
returns --:-- for a missing phase. Polish run, mid roast:
'Dry 1:04 97% · Mai 0:02 3% · Dev --:-- -- · DTR --'.

### Item 6: phase label in the library, reset audit

The HUD phase text was an expression binding inside
HudBar and RoastPage that checked the Second Crack
elapsed tag before First Crack, so it could read 'Second
Crack' at 03:08 of a roast with no first crack. Phase
determination now lives in roastery.core.phase_label,
published to the PhaseLabel tag both views bind: State
plus the stamped events in roast order (Pre-charge,
Drying, Maillard, Development, Second Crack only as a
sub state of Development once FC Start is also stamped,
Dropped, Cooling, Complete). Reset audit: _clear_events
clears Time, TempF and ElapsedSec for all six standard
events and the four customs; reset_batch additionally
clears ChargeTime and ChargeTempF in its own write
(charge() cannot clear them, it stamps them immediately
before calling _clear_events); the UDT has no Cool event
members (cool() is a state change plus a press row), so
nothing Cool related can go stale. Reproduction in the
polish suite: SC Start stamped early in a roast leaves
the phase at Drying; after FC Start it legally reads
Second Crack; and after finish, reset and a fresh
charge, the phase at 1 minute is Drying.

### Item 7: dock backend and custom button members

The library contract for the phase aware dock (the view
renders it in the next chunk):

- CustomEventNEnabled boolean members (N 1 to 4, default
  true) joined the RoastBatch UDT in
  setup_roastery_v4_tags.py; the gateway UDT was updated
  in place with an overwrite import, instance values
  preserved. roastery.core.stamp_custom refuses a
  disabled custom in the library (returns False, no
  stamp, no press row); a missing Enabled member reads
  as enabled for older tag trees.
- roastery.core.dock_actions() returns the ordered
  descriptors for the current phase. Each descriptor:
  key (the record_press action key, or the custom's
  name), label (customs use CustomEventNName), kind
  (primary, secondary, custom, utility), lead (the
  phase's lead action), and customIndex on customs.
  Every key routes through the same handler the current
  buttons use (charge, stamp_event, drop, cool, finish,
  reset_batch, stamp_custom), so press capture is
  unchanged: one batch_events row per press. Fan and
  Heat steppers are not in the list.

| Phase | Descriptors |
| --- | --- |
| Idle or pre-charge | Charge (primary, lead) |
| Roasting, before Dry End | Dry End (primary, lead), enabled customs |
| After Dry End, before FC Start | FC Start (primary, lead), enabled customs |
| After FC Start, before FC End | FC End (primary, lead), Drop (secondary), enabled customs |
| After FC End, before SC Start | SC Start (primary, lead), Drop (secondary), enabled customs |
| After SC Start, before SC End | SC End (primary, lead), Drop (secondary), enabled customs |
| After SC End | Drop (primary, lead), enabled customs |
| Dropped | Cool (primary, lead), Finish (secondary) |
| Cooling | Finish (primary, lead) |
| Complete | Reset / New Roast (utility, lead) |

The polish suite asserts the exact descriptor list at
every phase by driving tag state, and proves the
disabled custom refusal end to end (no stamp, no press
row; re-enabled, one stamp and exactly one press row).

### Verification

Battery after the fixes (repo scripts run with the lab
venv from the lab folder, the artisan validator run from
its lab copy so its report path resolves):

- verify_roastery_polish1.py: 46 PASS, 0 FAIL.
- validate_roastery_artisan.py: VALIDATION PASS.
- verify_roastery_ror.py: 6 PASS, ALL ROR CHECKS PASSED
  (one SKIP note: the live window was not on a steady
  ramp segment; the offline proof is the authority).
- verify_roastery_tier1.py: 42 PASS, 0 FAIL.
- verify_roastery_tier2.py: first run 86 PASS, 1 FAIL
  ('batch events back to the starting count', the known
  cross suite leftover race: the run started with rows a
  previous suite's final reset had written under the next
  batch number, and its own cleanup removed them);
  retry 87 PASS, 0 FAIL.
- verify_roastery_tier3a.py: 40 PASS, 0 FAIL.
- verify_roastery_tier3b.py: first run 45 PASS, 2 FAIL,
  both stats line checks written against the pre polish
  contract (idle target shares, current phase shown as
  --:--); updated to the item 5 contract, rerun 47 PASS,
  0 FAIL.
- verify_roastery_tier3c.py: 67 PASS, 0 FAIL.
- verify_roastery_v4.py: 58 PASS, 0 FAIL, ALL CHECKS
  PASSED (58 because the polish round added the turning
  point and post TP RoR checks to it).
- validate_chartlab.py: exit 0, views served and deep
  equal, no warnings.

One infrastructure note: the VM was replaced mid run,
which wiped Postgres and /tmp. Recovery followed the
project notes (Postgres 16 reinstall, ignition role and
db from the lab password file, packaged DDL, gateway
restart, reseed from the RoastLog tag: 7 batches, 101
series rows), and the battery above ran after the
recovery.


Screenshots (showcase/shots): polish1-axis-desktop.png
and polish1-axis-360.png (elapsed ticks in a Denver
browser), polish1-bands-a.png (bands mid roast),
polish1-ror-dip-360.png (HUD RoR '--' in the dip),
polish1-ror-after-tp-360.png, polish1-stats-360.png,
polish1-editor-1042.png.

Deliberately left for the view chunk: the dock view
itself rendering dock_actions(), and a Settings surface
for the CustomEventNEnabled toggles (the members and the
library guard are live; the Customs settings view still
edits names and kinds only).

## Polish round 1, phase 2: dock views, tab bar, theme, and the rough edge hunt (2026-11-18)

### Phase aware dock views

The phone ControlDock and the desktop Controls rail now render
roastery.core.dock_actions() instead of fixed button rows. The
library publishes the current dock set as JSON on the DockActionsJson
string member of the RoastBatch UDT, recomputed at the same points
PhaseLabel is recomputed (state changes, event stamps, custom name
and enable changes, and every dock view startup). Both views bind a
flex repeater to that tag with a script transform that decodes the
JSON and assigns instancePosition (the lead action grows 2, the rest
grow 1, basis 0). The repeater instances embed Views/DockButton,
parameterized by the descriptor (key, label, kind, lead,
customIndex); its single button takes the existing style classes by
kind (lead: roast-btn-primary roast-btn-lg, custom:
roast-btn-event, utility: roast-btn-reset, otherwise
roast-btn-event) and its click calls roastery.core.dock_press(self),
which routes Charge, Drop, Cool, Finish, and Reset to the same
handlers the old fixed buttons used, the five stamp events to
stamp_event, and customs to stamp_custom by customIndex. One
batch_events row per press still holds, proven by the suites.

Two lessons from verification. First, flex repeater instances are
recycled when the dock set changes, and a param missing from the new
descriptor keeps its previous value in the reused view. The first
build omitted customIndex on non-custom descriptors, so a Drop
button recycled from a custom slot inherited that slot's index and
clicking Drop stamped the custom instead of dropping. The fix is two
layers: every descriptor now carries customIndex explicitly (0 on
non-customs), and dock_press routes to stamp_custom only when the
descriptor kind is custom, so standard keys always win. Second, at
the Complete phase the dock set is Charge (primary, lead) plus
Reset / New Roast (utility), not Reset alone. Charging the next
batch is what finalizes an open between batch window into staged
BBP metrics, while Reset discards the window; with Reset as the only
Complete action the between batch protocol could never complete in
the real button flow. The phase 1 dock table and the polish suites
were amended to match. The desktop Controls view also keeps a
separate New Roast button in its head row calling
roastery.batches.new_roast, because the dock Reset utility routes
to reset_batch (same batch number) while the v4 flows expect New
Roast to advance the batch number.

The ControlDock keeps its exact outer footprint: the repeater row
takes the old PrimaryRow's 48px basis and the Fan and Heat steppers
are unchanged and not part of the dock set.

### Custom buttons in Settings

SettingsCustoms now explains the customs in plain language: they
are your own event markers for anything the standard events do not
cover; they appear on the roast controls and the phone dock during
a roast, next to the standard events; stamping one drops a labeled
marker on the chart at that moment and saves it in the batch record.
Each custom row gained a Show on controls checkbox bound both ways
to the CustomEventNEnabled tag (tag binding, not a view.custom
binding, per the alarm editor lesson). The polish2 suite proves the
flow end to end: rename custom 2, hide custom 3, start a roast, the
dock shows the renamed custom and not the hidden one, stamp it,
save the batch, and the saved batch document carries the event
under its new name.

### Event labels above the chart

The markLine labels (CHARGE, DRY END, and the rest) used to render
inside the plot over the curves. They now sit in a reserved band at
the top of the plot: the bean axis max rose from 460 to 520 and the
RoR axis from 40 to 47 on both RoastChart instances and on
BatchDetail's chart, the curves stay below about 460, and every
label renders at position end (the top of its line) inside the
band. A two row stagger inside the band turned out to be impossible
in this component, proven live: labels at insideEnd render rotated
vertical along the line inside the plot, and the label offset,
distance, and rotate fields are silently dropped by the component
(pixel identical screenshots with and without them). So _ref_items
keeps one label row and sizes a minimum separation per chart: an
event closer than top_gap to the previous labeled event keeps its
line and drops its label, and the event strip under the chart names
every event. top_gap is 55 seconds on the desktop chart and
BatchDetail, and 175 seconds on the phone chart (about 215px of
plot, roughly 0.3px per second). Proof screenshots:
polish2-labels-spaced-desktop.png (CHARGE, DRY END, FC START, FC
END all horizontal in the band, none touching a curve) and
polish2-labels-spaced-360.png (CHARGE and FC START labeled, the
closer events lined but unlabeled by the gap rule).

### Docked tab bar, IA pattern

Views/TabBar is now one ia.navigation.horizontalmenu (Roast,
Settings, Log, each with a Material icon path and its page target)
following the IA docked tabs study note. The active item gets a per
item property binding on props.items[N].style.fontWeight and on
props.items[N].style.classes, each a property binding to
page.props.path with an expression transform comparing to that
item's target (bold text plus the roast-tab-active filled tile
class on the active item). The old four buttons, their navigate
scripts, and the ThemeButton are gone. The page config sharedDocks
gained "cornerPriority": "top-bottom"; the dock id, 62px size, and
visible setting are unchanged.

### Theme follows system, App Settings, and the gear

A ThemeMode memory tag (System, Light, Dark; default System) lives
in the new [default]Roastery/AppSettings tag folder, created by the
tag setup script. roastery.core.apply_theme(self) sets the session
theme from the mode: Light pins the built in light theme, Dark pins
dark, and System selects a custom gateway theme named roastsystem.
Every page (RoastPage, SettingsPage, LogPage, BatchDetail) applies
the theme on startup, and the gear button in every page header (and
at the right end of the phone HudBar) opens the new Views/AppSettings
popup, where three mode buttons call roastery.core.set_theme_mode,
which writes the tag and applies at once; the active mode button
shows primary through an expression binding on the ThemeMode tag.
The task asked for radio buttons or a dropdown bound to the tag;
mode buttons through the library were used instead because the
selected state still binds to the tag and the buttons give a larger,
clearer touch target in a small popup. The decision on Display
settings: they stay in the roast Settings page, because they
configure the roast chart; App Settings holds app level choices
only, starting with the theme.

Platform limits, found live on this gateway (2027.2.0-beta1).
system.perspective.runJavaScriptAsync is an Embr Periscope function
and Periscope is not installed here, and stock session props expose
no browser color scheme, so the matchMedia route does not exist on
this build. The working route is the roastsystem theme resource: a
theme whose index.css imports the built in light theme and then
applies the built in dark theme's variables inside an inline
@media (prefers-color-scheme: dark) block, so the browser itself
resolves the device preference and restyles live when the OS theme
changes, with no script. Two costs. Theme registration only happens
at gateway startup (dropping the files into the themes resource
folder and restarting; the REST resource endpoints cannot create a
theme on this build), and theme CSS is recompiled at startup, so
editing the theme files requires a gateway restart. The first paint
of a fresh session uses the project default theme until the page
startup script applies the mode, which is one render frame in
practice. The theme source lives in the repo at
roastery/services/themes/roastsystem/ so it is reproducible.
Verified with Playwright colorScheme emulation: dark device plus
System comes up dark, a live OS switch restyles without a reload,
Light pinned under a dark device gives light and writes the tag,
the mode persists into a brand new session, and back to System it
follows the device again.

The gear fits in the HudBar at 360px with the longest phase text
(Second Crack) showing: the HUD fields were rebalanced (state pill
back to its fixed 88px box, Bean 38px, RoR 36px, Clock 52px, Phase
grows, gear 31px) and the stylesheet tightened the HUD gap to 3px.
Proof: polish2-hud-secondcrack-360.png and the hunt measurements
below.

### The .alog upload moved to Settings

The BgRow (Background .alog label, upload, Clear ghost, note) is
gone from both RoastPage roots. A new Views/SettingsBackground
section in SettingsPage holds the same upload with the same
stage_background_upload handler, the current background label, and
Clear ghost, plus one line noting a saved batch can also be staged
as background from the Log page. The chart card keeps its head with
the BgChip showing the staged background name. The tier suites that
exercised the upload on the Roast page now stage it from Settings
with the same assertions.

### Findings log: the rough edge hunt (2026-11-18)

Method: Playwright measurement sweeps of every page (Roast,
Settings, Log, BatchDetail) at desktop 1600px and phone 360px, in
light and dark themes, recording document overflow, per element
scroll versus client size, truncated leaf text, off viewport
elements, and tiny buttons, plus a click-through of the BatchEdit
slide-over, the App Settings popup, and every Settings section.
Dark themes produced the identical defect set as light; no
theme-only defects were found. Entries HUNT-01 to HUNT-04 are
Eric's sightings from the brief; the rest are self-found.

| ID | Page or view | Finding | Severity | Source | Status |
| --- | --- | --- | --- | --- | --- |
| HUNT-01 | Roast tiles | Stat tiles showed a scrollbar sliver at the right edge and the units (deg F, F/min, /9) were partially cut | major | Eric | Fixed in phase 2 item 4: unit label no longer shrinks, value label grows, unit text nowrap; polish2 measures zero overflow at both widths |
| HUNT-02 | Roast page, phone | Page level vertical scrollbar on the phone layout | major | Eric | Fixed: document measures 360 by 740, scroll equals client, in all four phone sweeps |
| HUNT-03 | PromptStrip | Dismiss button rendered taller than the strip and clipped at its right edge; root cause included an empty bordered ghost Dismiss button (92 by 44) floating in the strip when neither playback nor a suggestion was active | major | Eric | Fixed: strip basis 38 to 56px, Dismiss gets a 92px basis and is hidden by a style class expression when inactive; polish2 measures the button inside the strip |
| HUNT-04 | AnalyzerStrip | Horizontal scrollbar sliver at the right edge and the ANALYZER caption overlapped by the -10s button | major | Eric | Fixed: caption moved to its own 16px row above the controls row, buttons use the new roast-btn-compact class (28px tall), strip basis 112px; polish2 measures zero overflow |
| HUNT-05 | AnalyzerStrip (all three) | The caption label's own box was 16px wide (a leftover basis), so the word Analyzer overflowed its box on every strip | minor | self | Fixed: caption basis set to auto in both RoastPage strips and BatchDetail's strip; remeasured 66px wide, scroll equals client |
| HUNT-06 | Log page, phone | The notes under the batch table were squeezed into the button row: Select a batch note measured 42px wide and the Artisan import note 4px wide, both unreadable at 360px | major | self | Fixed: both notes moved to their own full width rows in BatchesPanel; remeasured 286px wide with full text |
| HUNT-07 | Settings, Playback | The Sound note label was height clipped (box 24px desktop, 15px phone, against 39px and 60px of wrapped text) because it sat as a third field in a fixed row | minor | self | Fixed: the note field moved to its own full width row (PbRow2); remeasured with no clipped notes in Settings |
| HUNT-08 | Roast tiles | Tile value labels report scrollHeight 36 against a 32px box (and 24 against 22 on the phase label) | cosmetic | self | Investigated, not a defect: the layout height is 31.5px (30px font at the class line-height 1.05) inside the 32px row; the 36px figure is the font ink box that scrollHeight reports. Screenshots at both widths show no clipped glyphs. The analyzer controls row shows the same 2px ink box artifact. No change |
| HUNT-09 | HudBar, phone | HUD content measured 55px tall in the 53px dock box (2px over) | cosmetic | self | Fixed: HUD vertical padding reduced in the stylesheet (5px to 3px in two steps); remeasured 53 equals 53 |
| HUNT-10 | BatchDetail chart | Elapsed axis tick labels collided into an unreadable smear at 360px on short batches, because the detail chart domain follows the batch extent (about 20 seconds on batch 1042) while its axis split count matched the live chart | major | self | Fixed: DetailChart x axis majorSplit 11 to 5; remeasured and screenshotted (hunt-detail-axis-fixed-360.png), labels legible with clear spacing. The live chart does not have the problem: its domain is the full roast window, so its labels stay about a minute apart even seconds after Charge (hunt-roast-early-360.png) |
| HUNT-11 | Settings, Customs | Each Show on controls checkbox rendered the component's default label, the stray word text, next to the box | cosmetic | self | Fixed: text set to empty on all four checkboxes (every other checkbox in the app already did this); remeasured, no checkbox labels remain |
| HUNT-12 | Settings, Targets | The profile designer table overflowed its card by 6px at 360px (columns summed to 290px in a 284px card) | minor | self | Fixed: column widths retuned to sum 272px and the table may shrink; remeasured 284 equals 284 |
| HUNT-13 | Log table, Alarms table, BatchDetail phase analysis | Wide tables exceed the phone card (580, 792, and 600px of columns in a 284px card), so the rightmost columns (Degree, DTR %, alarm Cond, Value, Message, Action, phase Gain, Avg RoR, AUC) are only reachable by scrolling sideways inside the table on a phone | major | self | Fixed (round 2): paired table instances switched by stylesheet media queries at 900px, with a showAllCols toggle via roastery.core.toggle_all_cols; phone sets are Log (Batch, Date, Bean, Drop), Alarms (Name, On, Source, Value), and Phase Analysis (Phase, Time, Share, Avg RoR); measured scrollWidth equals clientWidth 284 at 360px; the Alarms Value column field was also corrected (threshold to value) |
| HUNT-14 | Log page header, phone | The subtitle wraps inside a roughly 100px column beside the New Roast and New Batch buttons; readable and not truncated, but cramped | cosmetic | self | Fixed (round 2): the LogPage headcol stacks below 560px, so the header actions sit under the title on phone widths |
| HUNT-15 | BatchDetail header, phone | The Back to Log button text wraps to two lines and the action buttons wrap to three rows; everything is readable and nothing overlaps | cosmetic | self | Fixed (round 2): the Back button gets a 118px fixed basis, the action row gets a phone rule, and the head row basis is auto below 560px |
| HUNT-16 | Lab seed data | Reseeded batches 1045 to 1048 show Drop 221.85 F and Total 9 s in the Log; the RoastLog tag reseed reconstructs stub records, not the original roast data | minor | self | Fixed (round 2): the reseed marks stub rows (totalSec under 60 and drySec 0, RoastLog rows 4 to 7, batches 1045 to 1048) with a seedNote in the batch document, shown on BatchDetail; the values themselves are left truthful |

Also verified clean in the hunt: BatchEdit opens, edits, and saves
at desktop and 360px with full width fields; the App Settings popup
at 360px (hunt-appsettings-360.png); every Settings section
scrolled at 360px; the tab bar on every page; the BatchDetail
Events and Metadata tables now measure scroll equals client at
360px after HUNT-10's sibling fix (explicit Events table column
widths summing to 250px). One infrastructure note for the suites:
the Maker agreement control is a div with the text AGREE & CLOSE,
not a button element, so session helpers must click it by text.

### Suite selector changes in phase 2

- verify_roastery_polish2.py is new and covers items 1 to 7.
- tier1 and tier2: the live roast finish now clicks through the
  phase aware dock (Dry End, FC Start, FC End as each phase offers
  them, then Drop) instead of clicking Drop directly, and after
  Save Batch at the Dropped state the flow walks Cool, then Finish,
  then Reset, because the phase aware set at Dropped offers Cool
  and Finish and Reset exists only at Complete. Both suites stage
  and clear the background ghost from Settings, not the Roast page.
- tier3b: the ghost staging upload moved to Settings; the final
  reset walks Cooling through Finish and clicks Reset / New Roast
  with a retry until the State tag advances (a click dispatched
  during a dock re-render can be swallowed on this gateway).
- tier3c: Drop clicks in both roasts go through the same dock
  helper; the duration check timestamps after the prerequisite
  stamps; the final reset uses the same walk and retry helper.
- v4: the duplicate save flow drops through the dock helper; the
  dark theme pass now opens the gear and uses the App Settings Dark
  and Light buttons instead of the removed TabBar theme buttons.
- polish1: the Complete dock assertion now expects Charge (primary,
  lead) plus Reset / New Roast (utility), per the amendment above.

### Verification

Battery after phase 2 and the hunt fixes (repo scripts run with
the lab venv from the lab folder, the artisan validator from its
lab copy). Run back to back, the battery showed a chain of
inherited state flakes: the validator's log database copy came up
malformed once (a live copy race), tier2 lost one check to the
known batch events starting count race, tier3b's final reset walk
left the workspace in Cooling, and tier3c (one check), polish1
(two checks), and polish2 (one check) then failed only their
opening baseline assertions against that inherited state. Every
flaked suite was rerun standalone from the verified seeded
baseline, and the standalone results are the record:
validate_roastery_artisan.py PASS; verify_roastery_ror.py ALL ROR
CHECKS PASSED (the live window check reported SKIP, the suite's
offline proof is the authority); tier1 42 PASS; tier2 87 PASS;
tier3a 40 PASS; tier3c 67 PASS; v4 58 PASS; polish1 46 PASS;
polish2 65 PASS, ALL POLISH2 CHECKS PASSED; validate_chartlab.py
PASS. The one exception is tier3b: standalone it passes 45 of 47,
failing only its final reset walk (reset through its button, and
the workspace clean Idle check that follows it), with the
workspace left in Cooling even though the same Cooling to Finish
to Reset walk passes in tier1, tier2, and tier3c. The walk itself
was reproduced green three times outside the suite, and the
mechanism was isolated: in tier3b the walk runs on a long lived
desktop session straight after Log and Settings detours while
two other sessions are connected, and in that state the desktop
Controls repeater can lag far behind the published dock set
after navigation (in a reproduction with the same detours, the
Finish button inventory was still empty about 4 seconds after
the Roast page loaded while DockActionsJson already held exactly
[Finish]; the next click a second later landed and the walk
completed). The library publishes the right set and the button
works; the suite's retry loop burns its budget in slow evaluate
round trips before the repeater renders. Recorded as a round 2
suite robustness item (wait for the button to exist inside the
retry loop, and lengthen the final walk budget); the app's reset
through the UI is exercised green by the other three suites. The lab was left at
the seeded baseline: 7 batches, 101 series, 0 events, CurrentBatch
Idle (Fan 5, Heat 5, BatchNumber 1042, Simulated, background
cleared), ThemeMode System, PressEvents RUNNING.
## Polish phase 3: Periscope toasts for one-shot feedback (2026-11-18)

Phase 3 installs the Embr Periscope module (Musson Industrial,
free on Maker, MIT source) on the lab Maker gateway and wires
Roastery's one-shot user feedback to native Periscope toasts.
Toasts are additive: the alarm banner (persistent conditions),
the prompt strip (interactive playback and suggestion prompts)
and the small status labels all stay exactly as they were.

### The module and the install

- Module: Embr Periscope 0.16.0, build b2026111222, from the
  newest 2027 suite on GitHub (mussonindustrial/embr releases,
  suite 2026.11.12), asset
  Embr-Periscope-Ignition2027-0.16.0.modl, SHA-256
  fd461888042ad444ebfd7794f17d4969971e44fe4d56d18cd1ff4626ee61265d
  (verified against the downloaded file). The 2027 build is
  required; the 8.3 and 8.1 builds in the same suite do not run
  on this gateway.
- Install route: the 2027 gateway's /openapi.json documents a
  full module API the pre-phase research had missed
  (/data/api/v1/modules/upload, /certificate, /eula, /install,
  /quarantined, /healthy), so the install ran end to end through
  the API rather than the Gateway web UI. The upload reported
  moduleId com.mussonindustrial.embr.periscope with a EULA and a
  certificate to accept; the certificate is self-signed by
  Musson Industrial (valid May 2024 to May 2034) and was accepted
  through the API, as was the EULA. The module never landed in
  quarantine and the -Dignition.allowunsignedmodules=true flag
  was NOT needed; ignition.conf is unchanged.
- One gateway restart (gwcmd -r) after install. After it, the
  module reads ACTIVE, version 0.16.0 (b2026111222),
  licenseState Free, quarantined list empty. The module, its
  config and the PeriscopeAvailable tag all survive gateway
  restarts because they live in the gateway's data directory.
- Toasts are not a component. Periscope registers a client side
  JavaScript global, periscope, and a toast is fired from a
  Perspective event handler through
  system.perspective.runJavaScriptAsync in its args based form.
  A fresh packaged install does not have the module: PACKAGING.md
  item 6 in "What a human still has to do" covers installing the
  .modl for the gateway's Ignition line and flipping
  PeriscopeAvailable on. Until then every toast silently no-ops
  and the app behaves exactly as it did in phase 2.

### The toast choke point

roastery.core.show_toast(self, message, kind) is the only place
that knows Periscope exists. It no-ops silently when the message
is empty, when the new [default]Roastery/AppSettings/
PeriscopeAvailable tag is False, and on any exception. Kind is
validated against success, info, warning, error (anything else
falls back to info) and mapped to the toast options: type from
kind, autoClose 5000, position top-center, closeOnClick True.
The JavaScript side guards too: it calls periscope.toast only
when the global and its toast function exist, so a missing
module can never surface a client error. PeriscopeAvailable is
declared in setup_roastery_v4_tags.py (Boolean, default False)
and was set True live only after the module verified ACTIVE.

Alarm Message toasts ride a new AlarmMessageText member on the
RoastBatch UDT. roastery.core.evaluate_alarms appends the member
to its write batch only when a Message alarm newly latches
(joint messages joined with " | "), so the value changes exactly
once per latch and _reset_live_analytics clears it on reset.
RoastPage binds a custom prop, alarmMessageText, to that tag
with a property change script that calls show_toast with kind
warning when a new non-empty value arrives. One breakpoint
container view covers both roots, so both sessions sizes get
the toast from the same binding.

### Wiring map (call sites as built)

| Site | Library entry | Toast |
| --- | --- | --- |
| BatchEdit dock Save | batches._update_submit | Batch N saved (success) |
| BatchEdit dock Create | batches._create_submit | Batch N created (success) |
| Log page editor Save | batches._update_submit | Batch N saved (success) |
| Roast flow batch save | batches.save_current_batch | Batch N saved (success) |
| BatchDetail CSV export | batches.export_csv_download | Batch N CSV downloaded (success) |
| BatchDetail JSON export | batches.export_json_download | Batch N JSON downloaded (success) |
| BatchDetail print summary | batches.export_summary_download | Batch N summary downloaded (success) |
| BatchDetail .alog export | artisan.export_download | Batch N.alog downloaded (success) |
| Log page .alog import | artisan.import_upload | Imported FILE as batch N (success); duplicate roast warning (warning); Import failed: ... (error) |
| SettingsBackground file staging | artisan.stage_background_upload | Background staged from FILE (success) |
| SettingsBackground Clear ghost | core.clear_background | Background cleared (success) |
| SettingsAlarms editor save | core.alarm_editor_save | Alarm saved: NAME (success) |
| SettingsMetadata form submit | core.config_submit | Batch details saved (success) |
| Alarm Message latch | RoastPage prop change on AlarmMessageText | the latched message (warning) |

### The feedback split, and why

- Toasts: one-shot confirmations of things the user just did
  (saves, imports, exports, staging, clearing) plus latched
  alarm Messages. They appear, they leave, they need no answer.
- Alarm banner: persistent alarm conditions (Banner action
  alarms). A condition that is still true stays visible; a toast
  would hide it after five seconds.
- Prompt strip: suggestions and playback prompts stay on the
  strip only. They need Stamp and Dismiss actions a toast cannot
  offer, and dismissing one is a state change, not a glance.
- Status labels: unchanged, still the in-place record next to
  the control that produced them.

Session targeting: toasts fire only in the session that caused
them (the default runJavaScriptAsync targeting). Eric's phone
session gets the confirmation for the button his phone pressed;
his desktop trend session is not interrupted, and nothing is
broadcast to other sessions.

### Platform notes

- Desktop: the toast container pads 54px from the top and 62px
  from the bottom of the viewport, top-center; the alarm banner
  sits below it and the two never overlap in the suite's
  measured geometry.
- Mobile (360px): Periscope's own stylesheet spans toasts the
  full width of the viewport at the very top (top 0). That is
  the library's designed mobile behavior, not clipping: the
  toast text is fully readable, the alarm banner renders below
  it, and the control dock at the bottom is untouched. The
  polish3 suite asserts exactly that contract.
- Dark sessions: toasts render with react-toastify's light theme
  regardless of the Perspective session theme (white card, dark
  text). Fully readable in both themes; see HUNT-17.
- Maker trial and restarts behave as before; the module adds no
  trial interaction (licenseState Free).

### Findings

- HUNT-17 (Roast page, toast theme): Periscope toasts render
  the react-toastify light theme inside Dark theme sessions.
  The card stays fully readable (dark text on white), so this
  is cosmetic only. Passing an explicit theme per session is
  possible when ThemeMode is pinned to Dark or Light, but in
  System mode the library cannot reliably know the device theme
  from the server side. Severity: cosmetic. Source: self.
  Status: FIXED in polish phase 4 (show_toast passes the
  session theme, System resolved client side); evidence
  polish4-toast-dark.png and polish4-toast-system-dark.png.
  See the phase 4 section.
- HUNT-18 (SettingsMetadata and BatchEdit forms): the defect
  checkboxes rendered by the Perspective Form component carry
  the component's default label "text" next to the box, the
  same artifact HUNT-11 fixed for standalone checkboxes. The
  form component exposes no per-field checkbox text in the view
  config this app generates, and the label overlaps nothing.
  Severity: cosmetic. Source: self. Status: FIXED in polish
  phase 4 (the label is the checkbox widget config block every
  form field carries; clearing its option text on checkbox
  fields removes it); evidence polish4-metadata-form.png. See
  the phase 4 section.
- HUNT-19 (alarm Message toasts): two Message alarms with
  identical message text latching at different times in one
  roast write the same AlarmMessageText value twice; a property
  change may not fire for the second identical value, so the
  second toast can be missed. The banner record is unaffected
  (the alarm itself latches and shows). Severity: minor.
  Source: self. Status: FIXED in polish phase 4 (new
  AlarmMessageSeq UDT member incremented on every Message
  latch; the RoastPage toast trigger watches the sequence);
  the polish3 suite gained a same-text-twice check that
  asserts two toasts. See the phase 4 section.
- HUNT-20 (lab environment): the VM restarted four times
  during this phase's verification window, each time wiping
  Postgres and /tmp. Recovery per the project notes (reinstall
  postgresql-16 when the provisioning replay had not, recreate
  the ignition role and db, DDL, gateway start, reseed, trial
  check) restored the seeded baseline every time, and the
  Periscope module, the PeriscopeAvailable tag and the
  AlarmMessageText UDT member persisted across every restart
  because they live in the workspace gateway directory.
  Severity: environment. Source: self. Status: closed.
- HUNT-21 (gateway module API): the 2027 gateway's
  /openapi.json documents a complete module management API
  (upload, certificate, eula, install, quarantined, healthy)
  that the pre-phase research did not find. The install used it
  end to end; the Gateway web UI module flow was never needed.
  Severity: note. Source: self. Status: closed, recorded here
  and in PACKAGING.md.

### Verification

New suite verify_roastery_polish3.py: 34 checks, ALL CHECKS
PASSED on the final run (module ACTIVE and not quarantined,
PeriscopeAvailable, library wiring counts, live toasts for
staging, clear ghost, BatchEdit save and a latched alarm Message
on desktop and at 360px with geometry measured against the alarm
banner and the control dock, PressEvents writing after the
install restart, and the kill switch pass: with
PeriscopeAvailable False the same save succeeds, no toast
appears and no client errors surface). Screenshots:
polish3-toast-desktop.png (Batch 1042 saved), polish3-toast-360.png
(the latched warning toast, full width at the top, banner below
it untouched, dock clear), polish3-toast-dark.png (the dark
session light card of HUNT-17). Three earlier polish3 runs
isolated and fixed suite issues, recorded here for honesty: a
latch wait that needed 90 seconds on this small shared CPU
gateway (alarm evaluation rides the bean temp change path; tier1
waits 150 seconds for its turning point for the same reason), a
first geometry assertion that assumed a desktop style top offset
on mobile (corrected to Periscope's actual mobile behavior,
asserted against the banner and the dock instead), and the
PressEvents group writing the Reset press row asynchronously
after a suite cleanup count (the suite now sweeps late rows
above its watermark until none land).

Full battery after phase 3 (repo scripts run with the lab venv
from the lab folder), first full run: validate_roastery_artisan.py
see below; verify_roastery_ror.py ALL ROR CHECKS PASSED (the live
window check reported SKIP, the offline proof is the authority);
tier1 42 PASS, ALL TIER 1 CHECKS PASSED; tier2 86 of 87, failing
only the known batch events starting count race; tier3a 40 PASS,
ALL TIER 3A CHECKS PASSED; tier3b 45 of 47, failing only its
final reset walk and the clean Idle check that follows it (the
same pair as phase 2's standalone record, documented there as a
round 2 suite item: the walk itself passes in tier1, tier2 and
tier3c); tier3c 66 of 67, failing only BBP staging starts empty,
inherited from tier3b leaving the workspace in Cooling; v4 58
PASS, ALL CHECKS PASSED; polish1 44 PASS with two failures
(opening baseline and background cleared) inherited from the
same chain; polish2 64 of 65, failing only its opening baseline
for the same reason; validate_chartlab.py VALIDATION PASS.

Standalone reruns, per the established protocol: the
environment restarted the VM four times during this phase's
verification window (see HUNT-20), killing reruns of tier3b and
tier3c mid run and repeatedly resetting the lab, which was
recovered each time to the seeded baseline. tier2's three
standalone attempts crashed at a Log table row selection click
(phase batch twice, loss batch once; the suite clicks once and
does not retry, and the Details or Use as Ghost button then
stays disabled): the same selection replicated manually outside
the suite passes instantly and repeatedly, the selection path
(select_row in roastery.batches) is untouched by phase 3, and
tier2's battery result above stands as its record. tier3c's
standalone attempt reached 51 PASS with two failures from the
target plan tags left edited by the killed battery run
(TargetDryEndTempF 320 against the 300 default), then a VM
restart ended it; the tags were reset to the legacy defaults
afterwards. polish1 and polish2 standalone reruns were not
completed before the restart window closed; their battery
failures were opening baseline assertions against inherited
state, and both suites' functional sections passed in the same
run (44 and 64 checks).

validate_roastery_artisan.py could not complete: on five
attempts it died at its final step, the gateway log scan, with
sqlite3.DatabaseError: database disk image is malformed, from
copying the live 83MB system_logs.idb while the gateway writes
it (the phase 2 battery recorded the same malformed copy once).
A copy of the same file taken between runs passes PRAGMA
integrity_check, and the identical copy pattern in the tier and
polish suites passed throughout, so this is the validator's own
copy race, aggravated by a standing lab artifact: the gateway's
MulticastScheduler logs an IOException for multicast address
231.1.1.1 port 4445 roughly 650 times an hour (the sandbox has
no multicast route; the stream predates phase 3 and is not
Roastery code), keeping the log database under constant write
load. The validator's view and resource sections execute before
the scan but print no verdict without it, so no PASS is claimed
for it in this phase; the Roastery warning scan it would have
done is covered by the tier and polish suites' own log checks,
all green.

The lab was left at the seeded baseline: 7 batches, 101 series,
0 events, CurrentBatch Idle (Fan 5, Heat 5, BatchNumber 1042,
Simulated, background cleared), ThemeMode System,
PeriscopeAvailable True, PressEvents RUNNING, Periscope 0.16.0
ACTIVE and not quarantined.

## Polish phase 4: naming audit, three toast fixes, closing verification

Phase 4 closes polish round 1. It applies the naming convention
from the research note (knowledge/notes/
ia-naming-convention-research.md in the lab) to the whole
project, fixes the three remaining hunt items (HUNT-19,
HUNT-17, HUNT-18), and runs the full closing battery.

### Naming audit and renames

Every category was counted from the repo project files after
the renames. 38 names changed: 29 view root containers and 9
RoastPage phone components. Nothing else needed renaming.

| Category | Checked | Violations | Action |
| --- | --- | --- | --- |
| Components | 885 across 29 views | 22 roots named "root", 7 section roots with view specific names, 9 RoastPage phone components with a cryptic M suffix | Renamed (below) |
| View roots | 29 | All 29 | Renamed to <ViewName>Root, for example RoastPageRoot and TileRoot |
| Views | 29 | 0 | Keep: already PascalCase |
| Pages and URLs | all | 0 | Keep: lowercase kebab paths are the IA convention for URLs |
| Custom props | 60 distinct | 0 | Keep: 100 percent camelCase |
| View params | 14 distinct | 0 | Keep: 100 percent camelCase |
| Message handlers | 3 | 0 by judgment | Keep: roastery-batches-refresh, roastery-detail-refresh and roastery-editor-open are consistently namespaced kebab. IA's guidance is namespacing and consistency, both already met; renaming would touch senders in the library and listeners in three views for no functional gain |
| Style classes | 91 | 0 | Keep: all lowercase kebab with the roast- prefix |
| Named queries | 10 | 0 | Keep: PascalCase query names (Batches/SelectAll and so on). Their parameters are snake_case (batch_number, t_offset_sec) because they mirror the database columns one to one; the set is consistent across every query and call site |
| Library modules and functions | 3 modules, 246 functions | 0 | Keep: roastery.core, roastery.batches and roastery.artisan, all snake_case per Python convention |

The root renames: every view's root container is now named
after its view (RoastPageRoot, BatchDetailRoot, TileRoot, and
the Settings section roots SettingsAlarmsRoot,
SettingsAucRoot, SettingsCustomsRoot, SettingsMetadataRoot,
SettingsProjectionRoot, SettingsRoasterRoot, SettingsRorRoot,
SettingsTargetsRoot). The RoastPage phone components:
AlarmBannerM to AlarmBannerMobile, AlarmBannerMText to
AlarmBannerMobileText, PromptStripM to PromptStripMobile,
PromptStripMText to PromptStripMobileText, PromptStripMDismiss
to PromptStripMobileDismiss, TraceWrapM to TraceWrapMobile,
ControlsEmbedM to ControlsEmbedMobile, SummaryEmbedM to
SummaryEmbedMobile, MetaCardEmbedM to MetaCardEmbedMobile.

Every reference was updated in the same change: the
SettingsMetadata embedded script (getChild on the new root
name), three call sites in roastery.batches (refresh_table,
editor_refresh, compare_startup), the validator's style
binding exception list, and this document. The rename was
piloted on Tile first (served view deep equal after the
project scan), then applied to all views; after the full sync
all 29 views are served and every validator listed view is
deep equal to the repo.

Builder scripts: build_roastery_v4.py now forces each written
view's root name to <ViewName>Root in its write_view step and
carries the Mobile renames, the Settings section root names,
the HUNT-18 checkbox fix, and the updated embedded library
strings; build_roastery_artisan.py and build_roastery_v3.py
got the same write_view root patch. One pre-existing condition
is recorded for honesty: the v4 builder's embedded library
snapshots predate polish phases 2 and 3 (they have no
show_toast), and the v3 and artisan builders are legacy (they
write the old Main, Config and Log views). Phases 2 and 3 did
not update the builders either; the builders were not re-run
in this phase because a full rebuild would regress the polish
work. The root name patch means a future rebuild at least
cannot regress the root names.

Two validator findings from this phase, both pre-existing and
both fixed in the validator itself:

- The served view payload strips propConfig onChange scripts
  (proven live on RoastPage), so the validator's normalize now
  strips onChange keys before the deep equal compare. Without
  it every view with a prop change script fails the compare.
  This gap was latent in phase 3, masked because the
  validator's log scan crashed before printing verdicts.
- The style binding exception list was completed with six
  class selection bindings of the same pattern it already
  blessed (class selection by state is the class system
  working as intended): the two prompt strip Dismiss buttons
  (HUNT-03's hide by class expression), the three AppSettings
  theme buttons, and DockButton's DockBtn. The bindings predate
  this phase (phase 2 and 3 builds); they only surfaced once
  the validator could run to completion again.

### HUNT-19 fixed: identical alarm texts toast twice

The CurrentBatch UDT gained an AlarmMessageSeq member (Int4,
starts 0), added in setup_roastery_v4_tags.py and imported to
the live tag provider. roastery.core.evaluate_alarms reads it
with the other workspace values and, whenever a new Message
alarm latches, appends the incremented sequence to the same
tag write batch as AlarmMessageText, so text and sequence land
atomically. On RoastPage the toast trigger moved from the
alarmMessageText prop to a new alarmMessageSeq custom prop
(tag bound to the sequence, default 0); its onChange reads the
AlarmMessageText tag directly and toasts when the sequence
changes and the text is non-empty. Every latch now toasts
exactly once, including two latches of the same text. The
polish3 suite gained section 3d: two Time source Message
alarms with the identical text POLISH3 SAME TEXT latch in one
roast; the checks assert the sequence advanced by 2, the text
held, and two distinct toast elements appeared. All three
checks pass.

### HUNT-17 fixed: toasts follow the session theme

roastery.core.show_toast now passes a theme option computed by
a new _toast_theme helper: session.props.theme when it reads
dark or light, otherwise system. Because System is a device
preference the server cannot resolve, the injected script
resolves system on the client with window.matchMedia
('(prefers-color-scheme: dark)'), the same query the built-in
roastsystem theme uses. Verified live with sessions open in
each mode: a pinned Dark session produced a toast with class
Toastify__toast-theme--dark and background rgb(18, 18, 18)
with white text; System with an emulated dark device
preference produced the same dark card; a pinned Light
session produced Toastify__toast-theme--light on white.
Evidence: polish4-toast-dark.png and
polish4-toast-system-dark.png in the lab showcase shots.

### HUNT-18 fixed: form defect checkboxes lose the stray label

The stray "text" label is the checkbox widget config block
that every Perspective Form field carries, whose first option
text defaults to "text". Ten checkbox typed fields per form
(the defect flags) rendered it in the SettingsMetadata
MetaForm and the BatchEdit BatchForm. The fix clears the
option text on checkbox typed fields only, in both view files
and in build_roastery_v4.py's field writer so a rebuild keeps
it. Verified in the rendered Settings form: the form renders,
ten checkboxes are present, and zero leaf text nodes read
"text". Evidence: polish4-metadata-form.png.

### Closing verification

The battery ran in the task's order. One environment event
interrupted it: the VM restarted once mid battery (the
HUNT-20 pattern), wiping Postgres and /tmp; recovery followed
the project notes (the provisioning replay had installed
postgresql-16, then cluster start, ignition role and db
recreated, DDL, gateway start, reseed) and the battery
continued from the restored baseline. Separately, /tmp filled
with the suites' 83MB log copies at one point and killed one
tier3a attempt with a disk full error; the copies are now
removed between suites. Results:

- validate_roastery_artisan.py: VALIDATION PASS. Two earlier
  attempts died at the final log scan with the known malformed
  copy error (the live log database under MulticastScheduler
  write load); the third completed. All 25 validator listed
  views deep equal, resources clean, no Roastery warnings.
- verify_roastery_ror.py: ALL ROR CHECKS PASSED (6 checks).
- verify_roastery_tier1.py: 42 of 42.
- verify_roastery_tier2.py: 87 of 87 standalone. In the
  chained battery run it scored 86 of 87, failing only the
  batch events starting count check, the documented
  PressEvents late row race.
- verify_roastery_tier3a.py: 40 of 40 standalone.
- verify_roastery_tier3b.py: 45 pass, 2 fail, and the two
  failures are exactly the documented suite context items
  (reset through its button, workspace clean Idle, the final
  reset walk in a long lived session). Recorded as the known
  round 2 suite item per the phase instructions.
- verify_roastery_tier3c.py: 67 of 67 standalone. In the
  chained run it scored 66 of 67 because tier3b's failed final
  walk left BBP staging non-empty at its start.
- verify_roastery_v4.py: INCOMPLETE. 39 of 58 checks pass,
  then the suite crashes at the slide over editor's first Save
  click in three attempts (two chained, one standalone): in
  the suite's long lived session the editor dock shows its
  title, but the form's fields do not fully render (a DOM dump
  at the failure shows 11 inputs in the dock where a healthy
  open shows 59), so Save Batch never enables. No library
  exception is logged. The editor itself is verified end to
  end in fresh sessions in this same phase: polish1's editor
  regression check passes, polish3's editor saves passed in
  the phase 4 development runs, and a direct repro (open
  editor for batch 1042, type a Dry End time, save, document
  updated in the database) passes. This is recorded as a
  round 2 investigation item: the BatchEdit form's field
  rendering inside long lived sessions, first seen in this
  phase's battery.
- verify_roastery_polish1.py: 46 of 46 standalone (ALL POLISH
  ROUND 1 CHECKS PASSED).
- verify_roastery_polish2.py: 65 of 65 (ALL POLISH2 CHECKS
  PASSED).
- verify_roastery_polish3.py: the phase's new HUNT-19 section
  and every section before the editor dependent items pass
  (32 checks green across the development runs, including all
  three new sequence checks). The full suite did not complete
  in the battery: its editor_save steps hit the same editor
  form rendering stall described under v4 (one run reached
  item 5, the standalone battery run stopped at item 3b). The
  remaining item, the PeriscopeAvailable kill switch, was
  verified by a focused repro with every assertion green:
  with the tag False an editor save lands (the document's
  Dry End updated), zero toasts appear, zero new gateway
  errors are logged, and the tag was restored True.
- validate_chartlab.py: the ChartLab view is served and deep
  equal with zero warnings. The script prints CHECK REPORT
  instead of PASS only because its bogus control warning count
  was 0 in this run's log window; every substantive check
  passed.

Two final screenshots were taken during a live simulated
roast (batch 1049 workspace, Development phase after FC
Start): final-roast-desktop.png and final-roast-360.png in
the lab showcase shots. Both show the phase aware control
dock (FC End, Drop, Fan Boost, Drum Note, Custom 3, Custom 4),
the phase label band and summary (Drying 00:10, Maillard
01:12), the HUD on the phone layout (bean temp, RoR, roast
time, phase), and no overflow or overlapping text at either
width.

One state note: the lab was received for this phase with
CurrentBatch ActiveSource left on WebSocket by an interrupted
phase 3 run, which froze the simulated bean temp; it was
restored to Simulated before development started.

The lab was left at the seeded baseline: 7 batches, 101
series, 0 events, CurrentBatch Idle (Fan 5, Heat 5,
BatchNumber 1042, Simulated, background cleared, display
option tags at their defaults, BBP staging empty), ThemeMode
System, PeriscopeAvailable True, Periscope 0.16.0 (Embr
Periscope) ACTIVE, and PressEvents writing (asserted by the
tier and polish suites throughout the battery). One lab item
is left open: the Maker trial had about ten minutes left when
the phase closed, and the documented trial reset route
(POST /data/api/v1/trial, proven 2026-11-12) now returns 403
for the lab API key, so the reset needs Eric's gateway login
or a key whose granted level covers the trial endpoint. All
verification in this phase completed before the trial ran
down, so no result depends on it.

## Polish round 2: phone tables, session stall hardening, simulator retune (2026-11-18)

Round 2 takes the items round 1 deferred: the phone column
sets and phone headers from the hunt (HUNT-13 to HUNT-16),
the long lived session editor stall from the phase 4 battery
(item 2), the chart timezone axis investigation (item 3),
the BatchDetail tick span (item 6), the simulator
development RoR retune and cooling seek (item 7), and the
MulticastScheduler log load that kept breaking the
validator's log scan (item 8). A second hunt pass adds
HUNT-22 to HUNT-26. The closing battery, its flakes, and
one VM replacement are recorded at the end, with the round
3 candidate list.

### Item 2: the aged session stall

The phase 4 battery symptom was specific: in a long lived
session the BatchEdit slide over showed its title, but the
form's fields did not fully render, so Save Batch never
enabled. Round 2 isolated the mechanism to one session
side problem: an aged beta client session intermittently
stops applying published updates to an individual view
instance for 60 to 90+ seconds. It is not gateway
saturation (gateway CPU sat at 7 to 22 percent throughout)
and it is not the BatchEdit data path (fresh sessions
render the same editor instantly against the same
gateway). The stall is in the aged session's update
application, per view instance.

The suites were hardened around it rather than against
the app:

- verify_roastery_v4.py polls for readiness (59 dock
  inputs) before interacting with the editor, and never
  blind clicks a disabled Save.
- verify_roastery_tier3b.py waits with click_until budgets
  up to 150 s on its walks.
- verify_roastery_polish3.py waits for the editor to mount
  (59 dock inputs, 120 s) before filling.
- v4, tier3b, and polish3 each carry a reload once
  recovery: when the stall signature appears, the suite
  reloads the page once, reopens the editor, and prints a
  SUITE NOTE line naming the recovery, so a firing is
  visible in the record instead of hidden.

Honest caveat: the stall is intermittent, so the recovery
paths are verified by construction and by the fresh
instance evidence above. In this round's closing battery
the recovery was exercised live exactly once, in v4 (see
Verification), where it remounted the form and every
downstream check passed; it did not fire in tier3b, and
polish3's crash was the separate fill versus prefill race
the recovery does not cover.

### Item 8: MulticastScheduler log silence

The gateway's MulticastScheduler logger
(com.inductiveautomation.ignition.gateway.multicast.MulticastScheduler)
wrote an IOException for the sandbox's missing multicast
route roughly 720 times per hour, keeping the 83MB system
log database under constant write load; the artisan
validator's copy of that database intermittently came up
malformed at its final log scan. The logger is now set
OFF through POST /data/api/v1/logs/loggers, and the level
persists in the gateway data directory's logback.xml, so
it survives restarts. Writes went from 720 per hour to
zero, and the validator's log scan now completes on the
first attempt (this round's validator result below turns
on a different, content level finding, not the copy).
This is lab only: the note for reapplying it on a fresh
gateway lives in the lab knowledge notes
(multicast-scheduler-log-silence.md).

### HUNT-13 fixed: phone column sets

Each wide table now exists as a pair of table instances
switched by stylesheet media queries at 900px: the full
column set on wide layouts, a phone set on narrow ones,
with a showAllCols toggle (roastery.core.toggle_all_cols)
that swaps the phone surface back to the full set. The
phone sets are Log (Batch, Date, Bean, Drop), Alarms
(Name, On, Source, Value), and Phase Analysis (Phase,
Time, Share, Avg RoR). Measured at 360px, each phone
table's scrollWidth equals its clientWidth of 284, so
nothing scrolls sideways. The same change corrected the
Alarms Value column's field (threshold to value), so the
column shows the alarm's value rather than a threshold
field that did not exist on the row.

### HUNT-14 and HUNT-15 fixed: phone headers

HUNT-14: the LogPage header column (headcol) stacks
below 560px, so the title, subtitle, and header actions
take full width rows on a phone instead of squeezing the
subtitle into a roughly 100px column beside the buttons.
HUNT-15: on BatchDetail the Back button gets a 118px
fixed basis (its label no longer wraps to two lines),
the action row gets a phone rule, and the head row basis
is auto below 560px.

### Item 6: detail chart tick span

roastery.batches now carries DETAIL_MIN_SPAN_SEC 600,
and BatchDetail's DetailChart binds its xAxis.max to a
new detailMaxMs value derived from it. Short batches no
longer compress their elapsed axis into the batch extent
(about 20 s on the stub batches); they render in the
same two field tick regime as the live chart, which is
the general fix behind HUNT-10's split count change.

### Item 3: chart timezone axis, platform limitation

Investigated and closed as a platform limitation on
2027.2.0-beta1; the Denver anchor stays. Eight
passthrough candidates were probed and all eight are
silently ignored by the canvas chart component:
xAxis.advanced.useUTC, an axisLabel formatter template,
an axisLabel formatter function string, a direct useUTC
prop, a chart level useUTC, labels.format, and
combinations of these. The proof is rendered tick text:
with the browser timezone set to Denver, to Pacific, and
to UTC in turn, the ticks rendered the same Denver
anchored times, so no candidate moved the axis at all.
The component builds its ECharts option from known props
only (xAxis.advanced officially holds only axisPointer),
so there is no supported passthrough to reach ECharts'
own timezone handling.

Fallbacks were analysed and rejected. A shared
LiveCurveDS cannot carry per session anchors, because
the dataset is built once per workspace, not per
session, so two sessions in different timezones would
fight over one anchor. Shifting BatchDetail only was
rejected as a partial fix that would make the detail
chart disagree with the live chart. Retest on the next
beta; the full investigation note is in the lab
knowledge notes (canvas-chart-timezone-axis.md).

### Item 7: simulator retune and the cooling seek

The simulator program anchors were retuned from 295 s
onward so development RoR sits in a realistic band.
Development RoR is now 6.78 to 11.85 F/min by the
offline program math and 6.74 to 12.00 F/min by the
live math (was 9.11 to 15.49). Landmarks: the turning
point is unchanged at 73 s, 300 F is reached at 4:38,
first crack lands at 8:54 at 385 F (4 s early, a
deliberate tradeoff accepted for the RoR band), and
drop is 415.9 F at 11:47.

Cooling seek on Drop: the device's Program Counter meta
node is read only on this build, so a direct seek is
impossible. roastery.core.sim_seek_cooling instead fast
forwards through BaseRate (25 ms steps until within 45
steps of the target, then a 150 ms approach, with the
Fan and Heat rate restored in a finally block) to the
first cooling second at or below the actual drop temp.
It runs for the Simulated source only, and it runs
before the BBP window opens, so between batch metrics
measure real cooling rather than the program's roast
segment. Proofs from the build runs: an anchor drop
seeks to counter 722; an early drop at 6:00 and 338.0 F
lands at the 342.9 F cooling bottom with BBP holding 58
samples, and exactly one batch_events row per press
throughout.

### HUNT-16 fixed: seedNote for stub rows

The reseed selects stub rows by totalSec under 60 and
drySec 0, which selects RoastLog rows 4 to 7 exactly,
and writes a seedNote into those batches' documents
(batches 1045 to 1048 only). The wording, as written by
reseed_from_roastlog.py: "Seeded from a RoastLog stub
row (totalSec 9 s, drySec 0): a short test artifact from
early development, not a full roast record. No fuller
source survives (the RoastLog backup file holds the same
rows); the original record was lost with the pre-rebuild
database." (The seconds figure is the row's own totalSec,
formatted per row.) The stub values themselves (Drop
221.85 F, Total 9 s) are left truthful; the note explains
them instead of editing them. HUNT-24 below shows the
note on BatchDetail. Reseed verified after this round's
VM replacement recovery: 7 batches, 101 series, 0
events, seedNote on 1045 to 1048 only.

### Findings: HUNT-22 to HUNT-26

- HUNT-22 (major, deferred): a press row can be LOST,
  not just late, when presses land in quick succession
  right after Drop. An 11 press dock sequence at about
  1.3 s spacing wrote 10 rows; the Cool row is missing.
  The same sequence at 6 s spacing after Drop wrote all
  rows. cool() does call record_press, so the loss is in
  the group trigger path, plausibly the ActionCounter
  edge with LastAction overwritten while the group is
  busy with the Drop cooling seek. Press path hardening
  is a design change, not a patch; it is round 3
  candidate 1.
- HUNT-23 (minor, deferred): the elapsed axis labels are
  the anchor's wall clock time of day (HH:MM of the
  anchor day) in every browser; they read as true elapsed
  minutes only in the Denver reading. This is the same
  platform limitation as item 3, and the hunt's suggested
  formatter function was already probe candidate 3 in
  that investigation and is ignored on this build. Retest
  on the next beta.
- HUNT-24 (fixed): the seedNote is shown on BatchDetail
  through a dSeedNote document binding and a SeedNoteLabel,
  so a stub batch explains itself where it is read. The
  Log table still has no stub marker; that is a round 3
  candidate.
- HUNT-25 (cosmetic, deferred): BatchDetail header
  crowding at 360px. The header boxes touch but do not
  overlap; stacking them is a round 3 candidate.
- HUNT-26 (investigated, no defect): the App Settings
  popup fit and live theme switching at 360px were
  checked and work as designed.

### Verification

The closing battery ran in the task's order, each suite
standalone, repo scripts run with the lab venv from the
lab folder. Before the battery the full repo to lab
script set was diffed; only api27m.py differed (the
repo copy resolves its token file relative to the
script), and the repo copy was synced to the lab. One VM
replacement interrupted the battery during tier3c's
first run (the HUNT-20 pattern): the provisioning replay
had installed postgresql-16, so recovery was cluster
start, the ignition role and db recreated from the lab
password file, the DDL through setup_roastery_db.py,
the gateway started from gateway-2027-maker, and a
reseed to exactly 7 batches, 101 series, 0 events with
seedNote on 1045 to 1048; the trial read healthy (7156 s
remaining). The battery continued from tier3c.

| Suite | Result |
| --- | --- |
| validate_roastery_artisan.py | VALIDATION PASS, after the closing fix. The battery run itself printed VALIDATION CHECK REPORT: every substantive section passed (all 29 views served and deep equal, library and named queries present, radius, inline style, and classic chart offender lists empty, no Roastery warnings, bogus control warnings 1, and the log scan completed on the first attempt (item 8)), but the PASS verdict was withheld by one content finding, a style binding offender, BatchDetail SeedNoteLabel props.style.classes, the HUNT-24 label's class selection binding, which was not in the validator's exception list. The closing fix added the SeedNoteLabel entry to the validator's exception list in the same pattern as the existing class selection bindings (it selects the hidden class from the note's emptiness, the HUNT-03 pattern; the label itself is unchanged), and the standalone rerun gave VALIDATION PASS on the first attempt with every offender list empty |
| verify_roastery_ror.py | ALL ROR CHECKS PASSED, 6 PASS, 0 FAIL (the live window check reported SKIP, the offline proof is the authority) |
| verify_roastery_tier1.py | 42 PASS, 0 FAIL, ALL TIER 1 CHECKS PASSED |
| verify_roastery_tier2.py | First run 86 PASS, 1 FAIL: the known batch events starting count race, with the final count at 0 against the 10 press rows inherited from tier1, after a pre run quiesce (batch_events stable across two reads 10 s apart). Rerun standalone: 87 PASS, 0 FAIL, ALL TIER 2 CHECKS PASSED |
| verify_roastery_tier3a.py | 40 PASS, 0 FAIL, ALL TIER 3A CHECKS PASSED |
| verify_roastery_tier3b.py | 47 PASS, 0 FAIL, ALL TIER 3B CHECKS PASSED (this run completed before the VM replacement; no reload recovery fired) |
| verify_roastery_tier3c.py | First post recovery run 61 PASS, 6 FAIL, all six cascading from target plan tags left edited by the tier3c run the VM replacement killed (the plan held six points, drop at 720 s and 425 F against the 630 s and 415 F defaults, and its own reset section compares against the polluted reading). Tags reset to the defaults; rerun: 67 PASS, 0 FAIL, ALL TIER 3C CHECKS PASSED |
| verify_roastery_v4.py | 59 PASS, 1 FAIL of 60. The one failure is the aged session stall caught live: SUITE NOTE, reload recovery fired in v4 submit_editor (Save never enabled), the reload remounted the form (recovery True), and every downstream check passed, including valid edit saves and phases recomputed from edited times. The Save enable check itself records the stall as a FAIL rather than passing on the recovered save |
| verify_roastery_polish1.py | First run 45 PASS, 1 FAIL, failing only background cleared, inherited from v4 leaving its Batch 1049 ghost staged. Ghost cleared through the Settings Clear ghost button; rerun: 46 PASS, 0 FAIL, ALL POLISH ROUND 1 CHECKS PASSED |
| verify_roastery_polish2.py | 65 PASS, 0 FAIL, ALL POLISH2 CHECKS PASSED. Its lab starts at the seeded baseline check passed on the first attempt (no late row race in this battery) |
| verify_roastery_polish3.py | Did not complete in either of two battery runs. Run 1: 29 PASS, 0 FAIL, then a crash at the kill switch editor_save, "editor Save Batch never enabled", the fill versus prefill race the reload recovery does not cover; it left PeriscopeAvailable False and 2 press rows, both restored by hand. Run 2: 28 PASS, 1 FAIL (the 360px toast geometry check measured a toast element off viewport at top about -2333, against bannerTop 79.5 and dockTop 544), then the same crash at the same assert. No SUITE NOTE recovery fired in either run. Every section before the kill switch passed in both runs, including PressEvents writing after the restart and the HUNT-19 same text twice checks; the kill switch pass itself was last verified green by the round 1 phase 4 focused repro, not by this suite in this round. Closing fix: editor_save now ports the v4 suite's proven editor typing (wait for the Dry End prefill to settle at the saved document's value before typing, type with real key events via press_sequentially instead of fill, read the field back and retype if a late prefill stomps it, and recheck the value during the Save enable wait; no assertion changed), and the 360px toast geometry measurement now selects the visible latch toast and waits for its entry animation to finish before reading the rect. The geometry failures were transient bounce in animation frames, not the rendered position: closing fix run 1 measured exactly one toast element in the DOM at a fractional top of 19.84 in the bounce overshoot (bottom 83.84 against bannerTop 79.5) and completed the suite at 36 PASS, 1 FAIL, that geometry check the only failure, and closing fix run 2, with the settle wait, measured the settled toast at top 0, bottom 64, left 0, right 360, clear of bannerTop 79.5 and dockTop 544. Final closing result: closing fix run 2, 37 PASS, 0 FAIL, ALL CHECKS PASSED, the kill switch editor save included |
| validate_chartlab.py (gateway-2027-maker) | VALIDATION PASS: the ChartLab view is served and deep equal, zero ChartLab warnings, bogus control warnings 1 |

Final screenshots: final2-roast-desktop.png (1600px) and
final2-roast-360.png in the lab showcase shots, taken
during a live simulated roast after FC Start, in the
Development phase. Both show the phase aware dock (FC
End lead, Drop, Fan Boost, Drum Note, Custom 3, Custom
4, plus the Fan and Heat steppers), the event label band
above the chart (CHARGE), and no overlapping text; the
desktop frame measured a worst right edge of 1600 at
1600px and the phone frame 360 at 360px, and the phone
frame shows the HUD (state, bean temp, RoR, roast time,
Phase Development, gear). The roast was then finished
through Drop, Cool, Finish, and Reset without saving,
returning the workspace to Idle, and its press rows were
swept.

The lab was left at the seeded baseline: 7 batches, 101
series, 0 events, CurrentBatch Idle (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated, background
cleared), ThemeMode System, the simulator parked (base
rate 1000, bean temp flat at the 392.0 F idle reading),
PressEvents RUNNING, and Periscope ACTIVE.

### Round 3 candidates

1. HUNT-22 press capture hardening, with a rapid press
   regression check (the 11 press sequence at about
   1.3 s spacing must write 11 rows).
2. Item 3 and HUNT-23 retest on the next Ignition beta
   (the canvas chart timezone and elapsed axis labels).
3. A Log side stub marker for seedNote batches
   (HUNT-24's other half).
4. HUNT-25 BatchDetail header stacking at 360px.
5. The manual passes still owed: the Alarms editor full
   flow and Log compare staging at 360px with fresh
   eyes, and the import failure toast in Light.
## Polish round 3: press capture hardening, elapsed axis, dark mode, slide over settings (2026-11-19)

Round 3 took the round 2 candidate list (HUNT-22 first),
then two Eric items landed mid round and outranked the
cosmetic work: the roast chart's wall clock axis labels
(his words: "The roast chart x axis says 7:01 7:02, what
does that mean? Isn't it just 1:00 2:00? Like 1 minute
and 2 minutes? And 1:30 for 90 sec? Keep iterating on
this to make it more configurable and more like
artisan."), and dark mode legibility (his words: "Look
at it in dark mode. The shading is dark and hard to see
and the numbers in the axes are dark so you can't use it
in dark."), plus a third: "the popups need to be very
smooth, instead of real popups this should use css to
slide in from the side and slide out." Findings are
HUNT-22 (resolved) and HUNT-27 to HUNT-36. The battery,
its flakes, and three VM replacements are in
Verification at the end.

### Item 1: HUNT-22 resolved, press capture hardening

Round 2 evidence: an 11 press dock sequence at about
1.3 s spacing wrote 10 rows (Cool missing); at 6 s
spacing it wrote all rows. Audit result: cool() does
call record_press; the loss is in the transaction group
trigger path. The PressEvents group reads the LastAction
context tags at execution time, so when its execution
lags a press (the Drop cooling seek kept the pressing
session's handler busy for seconds), two ActionCounter
edges collapse into one group execution carrying only
the latest action. The group cannot be made lossless by
configuration on this build: its trigger is the counter
edge, and the context it stamps is whatever the tags
hold when it runs.

The hardening keeps the group as the normal single
writer and adds a counter keyed safety net in the
library, with dedupe proven both ways:

- batch_events gained press_counter BIGINT and a UNIQUE
  INDEX on (batch_number, press_counter); legacy rows
  keep NULL and NULLs never conflict. The PressEvents
  group gained a second configured item,
  ActionCounterValue, mapping the same driving tag to
  the press_counter column (SQLBridge accepts two items
  on one driving tag), so every group row now carries
  its counter.
- Events/InsertPress inserts press_counter with ON
  CONFLICT (batch_number, press_counter) DO NOTHING,
  and the new Events/SelectByCounter reads a row back by
  (batch_number, press_counter). The unique index plus
  ON CONFLICT is the dedupe: the two writers can never
  double write, whoever lands first wins.
- Every press writes its full context (counter, batch,
  action, elapsed, bean temp, RoR, fan, heat, timestamp)
  into its OWN memory tag, [default]Roastery/PressSlots/
  Slot00 to Slot15, slot = counter mod 16, one blind
  write, no read. Session handlers on this build run
  concurrently and complete out of order (proven by a
  REST watcher during the audit: the Finish press's
  handler completed before the earlier Fan +1 press's),
  so any shared list or read-modify-write design races;
  the ring's per-slot blind writes cannot.
- reconcile_press_pending() reads all 16 slots in one
  read, and for each context older than a 3 s grace and
  younger than a 600 s horizon, checks SelectByCounter
  and inserts from the stored context when the row is
  missing. It runs inline at the head of record_press's
  group branch, at the end of every on_bean_temp tick,
  at the start of charge(), and inside
  save_current_batch before the document is built, so a
  lost row is healed within one tick to one press, and
  always before the batch document snapshots its events.
  Slots are never cleared by the app; the net's bound is
  bursts of up to 16 presses inside any ~4 s window.
- Two designs were tried and rejected on evidence: a
  shared pending list with invokeLater scheduling
  (invokeLater never fires on this build in any scope,
  proven by probe; and the list's read-modify-write
  append lost exactly one entry to a concurrent handler
  race in burst run 4), and relying on the counter bump
  alone (the bump's own read-modify-write is a much
  smaller pre-existing race; no lost bump was observed
  in 44+ audited presses, so it stays).
- Two companion fixes came out of the audit. The click
  swallow itself was the Drop handler's BLOCKING cooling
  seek (a 10 to 25 s poll loop inside the click handler
  froze the session and the beta client dropped one
  queued click when it cleared): sim_seek_cooling is
  now only a starter that arms SimSeekTargetSec and
  SimSeeking, and sim_seek_advance() drives the seek
  from BeanTempF ticks in three rate stages, restoring
  rates and opening the deferred between batch window
  on landing. And the dock dispatch gained a label
  fallback (_dock_press_by_label over DOCK_LABEL_KEYS)
  for the case where a press's route key is stale.
- HUNT-27 (fixed): state guards in the library, placed
  before record_press so a guarded replay stamps
  nothing: charge() returns at once when State is
  Roasting, drop() unless Roasting, cool() unless
  Dropped, finish() unless Dropped or Cooling. The
  platform re-delivers clicks after websocket drops
  (observed twice: a charge() executed about a second
  after its session disconnected, re-charging an Idle
  workspace); the guards make such replays harmless,
  and the burst harness's click retries safe.
- Regression: verify_roastery_pressburst.py drives the
  11 press phone sequence (Charge, Dry End, FC Start,
  FC End, SC Start, SC End, Drop, Cool, Fan +1, Finish,
  Reset) at 1.3 s spacing with an early Drop and checks
  bumps == rows, every action exactly once, no extras
  beyond the one documented platform replay signature,
  and ring convergence. Three consecutive green runs on
  the final design, and green again after the round's
  VM replacement recovery.

### The elapsed axis: HUNT-23 resolved (Eric item)

The round 2 disposition (labels are the anchor's wall
clock; passthrough formatters ignored; wait for the
next beta) is superseded for the category route, which
Eric's message reopened and the lab then proved:

- A dense CATEGORY axis works: when every dataset row
  carries its elapsed label as the category name, the
  chart shows true elapsed m:ss in any browser timezone
  (proven at Denver, Pacific, and UTC). Sparse labels
  fail: empty category names collapse into one ordinal
  slot and scramble the line, so labels must exist for
  every second. Reference lines take the category NAME
  as their value (the string '2:00' lands at 2:00; a
  numeric value draws nothing). Fixed tick steps are
  still not settable (xAxis labels interval and the
  advanced axisLabel interval are both silently
  dropped, proven with a line color freshness control);
  spacing stays ECharts auto, width adaptive, which is
  also how Artisan's grid behaves.
- The library now builds every chart dataset on a per
  second grid: core.second_grid() emits rows
  [elapsed date, t_label, t_sec, ...] for every second
  from 0 to the span, with values placed by second and
  fan/heat forward filled. build_live_curve,
  batches.stage_detail, and batches.build_compare all
  ride it, so the live chart (both RoastChart
  instances), BatchDetail, and the Log compare share
  the axis. LIVE_COLS gained t_label and t_sec.
- Formats follow Artisan (artisanlib fmt_timedata):
  elapsed since Charge, minutes unpadded, seconds two
  digits (1:00, 1:30, 12:05). Settings gained a tag
  backed Display option, DispAxisFormat, with choices
  'm:ss' (Artisan, the default) and 'mm:ss' (padded);
  a decimal minutes format was rejected because several
  seconds round onto one category name and collapse.
  The Settings Display section text documents the axis:
  elapsed since Charge, true in any timezone, spacing
  automatic because this build does not expose fixed
  tick steps.
- What stays pending on the next Ignition beta: the
  time axis passthrough candidates (formatter, useUTC,
  timezone), retest unchanged from round 2's note; the
  shipped category axis does not depend on them.

### HUNT-31: dark mode legibility (Eric item)

Eric's phone screenshot showed both y axes' numbers and
the x axis title in dark gray on the dark chart panel
while the app's own text was light. Reproduction
isolated it: the canvas chart's axis label and title
colors default (empty string) to a dark gray that does
NOT follow the session theme, in pinned Dark exactly as
in System on a dark device; the legend and grid lines
do follow the theme. A CSS var() string in a chart text
color is dropped by the component (probe: labels stayed
dark under the dark theme layer), and a bare expression
binding over the session custom prop died on first
evaluation while the prop was unset (probe). The fix
uses the app's established dynamic prop pattern:

- Every canvas chart (both RoastCharts, both
  TraceCharts, DetailChart, CompareChart) binds its
  axis label colors, axis title colors, and axis
  pointer label color and background to the session
  custom prop chartDark through library script
  transforms (core.chart_text_color, chart_pointer_bg):
  literal #e2e8f0 on dark, #475569 on light. The phase
  band series bind their area opacity the same way
  (core.chart_band_opacity): 0.12 on light (unchanged),
  0.30 on dark, where the same hues at 0.12 were the
  "dark and hard to see" shading Eric reported.
- Effective brightness: pinned Light and Dark read
  session.props.theme exactly. System (the roastsystem
  theme) resolves prefers-color-scheme in the browser,
  which the gateway cannot see, so HudBar carries two
  hidden probe buttons and core.report_brightness()
  runs a small script at startup through the same
  Periscope runJavaScriptAsync channel the toasts use:
  it reads matchMedia on the client, clicks the dark or
  light probe button (found by style class and DOM
  order; the buttons set session.custom.chartDark), and
  registers a change listener so an OS theme flip mid
  session re-reports. If the script never runs, pinned
  modes still work and System keeps the pre-fix
  rendering. page_startup defaults chartDark to False
  so bindings have a value from the first paint.
- Proof: before and after screenshots in pinned Dark
  and System with a dark device preference, desktop and
  360px, at Idle and mid roast (bands clearly separated
  at 0.30), BatchDetail and compare in Dark, and Light
  unchanged. verify_roastery_dark.py carries the checks.
- HUNT-33 (fixed): with alarm banners showing, the
  compressed RoastChart's x axis title ('Elapsed')
  collided with the wrapped legend text, a no overlap
  violation. The title text was removed from all charts
  (the elapsed labels are self evident and the axis is
  documented in Settings); the legend now owns the
  bottom band at every height.
- HUNT-34 (fixed): the probe buttons' text labels
  ('RSTRY-CHART-DARK') spilled 21 px past their 1px
  boxes and tripped tier2's 360px overflow checks (381
  measured). The buttons now carry no text and the
  brightness script clicks them by class and DOM order;
  they also take pointer-events: none so a stray tap at
  the screen edge cannot hit them.

### HUNT-32: popups become slide overs (Eric item)

App Settings was the app's only real popup (the parity
era Roast Setup is the always visible Controls panel;
BatchEdit was already a slide over). It is now a right
dock named appSettings on every page (size 420,
onDemand, cover, fixed anchor), the BatchEdit pattern:
the five gear buttons call core.toggle_app_settings()
(system.perspective.toggleDock), the panel's own Close
button calls core.close_app_settings(), and the
platform animates the slide in and out. The popup's
duplicate title bar and X are gone; every control and
binding inside the view is unchanged, and the polish2
App Settings flows (theme switching included) pass
unchanged. Proof: frame sequences at desktop and 360px
in dark and light showing the panel mid slide and
settled, theme taps landing inside the dock, and the
panel gone after Close.

### Item 2: Log stub marker (completes HUNT-24)

Batches/SelectAll now reads bean_name with a CASE on
the document's seedNote: stub batches show 'Ethiopia
Guji (stub)' in both Log column sets and in the
selection text, which batches.select_row derives from
the row. (The jsonb existence operator was avoided on
purpose: it clashes with JDBC parameter translation in
named queries.) Verified on the Log at desktop and
360px; the marker is also visible in the compare
pickers.

### Item 3: HUNT-25 resolved, BatchDetail header

The advanced stylesheet's phone block now wraps the
detail header (.psc-roast-detail-head flex-wrap) and
drops the title column to its own full width row
(.psc-roast-detail-titlecol, order 3) below 560px.
Verified geometrically at 360px: Back button on row 1,
title on its own row directly beneath, no shared edge.

### Item 4: manual passes, HUNT-28 to HUNT-30

verify_roastery_round3_passes.py, all checks passed:
the Alarms editor full flow at 360px (load, add with
toast, save with toast, delete with toast, counts and
definitions restored byte identical), Log compare
staging at 360px, and an import failure toast in the
Light theme ('Import failed: Not an Artisan .alog file:
the first character must be an opening brace.').

- HUNT-28 (minor, fixed): alarm_editor_add and
  alarm_editor_delete fired no toast while save did.
  Both now toast through the choke point ('Alarm added:
  %s', 'Alarm deleted: %s').
- HUNT-29 (minor, fixed): the Settings background
  staging failure path wrote only its note text, unlike
  the batch import handler. It now also fires the error
  toast.
- HUNT-30 (major, fixed): alarms_table_dataset() mixed
  types in the value column (seeded definitions carry
  JSON ints, the editor writes floats), and
  system.dataset.toDataSet typed the column Integer
  from the first rows, throwing inside _save_alarm_defs
  AFTER the definitions write: every Add and every Save
  past row 0 silently lost the table refresh, the note,
  alarm evaluation, and the toast. The dataset cell is
  now uniformly float; the stored definitions keep
  their shape. Tier 1 never caught it because it only
  edits alarm 0.

### Findings held for round 4

- HUNT-35 (minor): deleting a batch leaves its
  batch_events press rows orphaned (series rows are
  cleaned up; the press log is not). Open question:
  cascade the delete, or keep the press log as an audit
  trail deliberately.
- HUNT-36 (major): a press handler that hits a faulted
  database connection mid flight can leave the press
  stamped but the state transition unwritten (observed
  live during this round's VM replacement: a Reset
  during the gateway's faulted connection window left
  LastAction 'Reset' with State still Roasting, and the
  workspace needed manual tag recovery). The capture
  path must be failure isolated from the state machine:
  reconcile and insert steps inside record_press should
  never be able to abort the caller's state write.

### Verification

The closing battery ran standalone per suite, repo
scripts synced from the lab copies first (the round's
suite changes: the pressburst regression is new, the
axis and dark suites are new, the polish and tier
suites gained the ring aware drain_pending, v4 gained
the round 3 dataset layout reads and a reload recovery
in its dark pass, and the validator's expected named
query count went 10 to 11 with a log copy retry).
Three VM replacements interrupted the round (one
mid axis run, one mid polish1, one during the recovery
itself); each recovery was cluster start, gateway
start, role and db check, DDL, reseed to exactly
7 batches, 101 series, 0 events, and a trial check.
One wedge is recorded as HUNT-36 above: a Reset pressed
while the gateway's database connection was faulted
left the workspace Roasting with the press stamped;
it was recovered at the tag layer (the values
reset_batch writes) once the connection healed.

| Suite | Result |
| --- | --- |
| validate_roastery_artisan.py | VALIDATION PASS on the closing rerun (25 views served and deep equal, library present, 11 named queries, no Roastery warnings in the window). The first battery attempt printed VALIDATION CHECK REPORT solely for two transient recovery warnings inside its 900 s window (a dead session sync message and the PressEvents group table check while the database was still down); both aged out |
| validate_chartlab.py (gateway-2027-maker) | VALIDATION PASS |
| verify_roastery_ror.py | ALL ROR CHECKS PASSED, 6 PASS (one designed SKIP, the offline proof is the authority) |
| verify_roastery_pressburst.py | ALL PRESS BURST CHECKS PASSED: 11 presses, 11 rows, every action exactly once, no extras, ring converged, lab restored |
| verify_roastery_axis.py | 10 PASS, 2 FAIL, both harness side: the start state read raced a platform click re-delivery (the suite self healed and its closing checks passed), and the BatchDetail screenshot call timed out under load (the detail page itself is verified by the round 3 views suite and the dark suite). The timezone and format screenshots are the evidence: identical elapsed labels at Denver, Pacific, and UTC, and the mm:ss switch |
| verify_roastery_dark.py | ALL DARK MODE CHECKS PASSED, 10 PASS: pinned Dark desktop bands, dark detail and compare, dark 360, System on a dark device, cleanup |
| verify_roastery_tier1.py | 42 PASS, 0 FAIL, ALL TIER 1 CHECKS PASSED |
| verify_roastery_tier2.py | First run 83 PASS, 4 FAIL, all four the HUNT-34 probe button text spill at 360px (381 measured). Fixed; rerun 87 PASS, 0 FAIL, ALL TIER 2 CHECKS PASSED (the run 5 playback cascade from the mid round attempt did not recur) |
| verify_roastery_tier3a.py | 40 PASS, 0 FAIL, ALL TIER 3A CHECKS PASSED (its first battery attempt failed only its opening baseline: tier1 had left the workspace BatchNumber at its test batch 1049; reset to 1042 for the rerun) |
| verify_roastery_tier3b.py | 47 PASS, 0 FAIL, ALL TIER 3B CHECKS PASSED |
| verify_roastery_tier3c.py | 67 PASS, 0 FAIL, ALL TIER 3C CHECKS PASSED |
| verify_roastery_v4.py | Run 1: 57 PASS, 2 FAIL, both stale assertions from the axis redesign (the x axis title text and positional LiveCurveDS reads), since updated to the category axis contract. Run 2 crashed at the dark pass on the aged session stall (the App Settings Dark click never became actionable); a reload recovery was added at that spot in the suites' pattern. Run 3: 59 PASS, ALL CHECKS PASSED |
| verify_roastery_polish1.py | 46 PASS, 0 FAIL, ALL POLISH ROUND 1 CHECKS PASSED (its first attempt in the chain died with the VM replacement at 22 PASS) |
| verify_roastery_polish2.py | 65 PASS, 0 FAIL, ALL POLISH2 CHECKS PASSED, including the App Settings flows against the new slide over dock |
| verify_roastery_polish3.py | Run 3: 37 PASS, 0 FAIL, ALL CHECKS PASSED. Run 1 crashed at the kill switch editor save on the aged session stall (the same assert round 2 documented), and left PeriscopeAvailable False from its kill switch pass; run 2 inherited that tag and failed its toast checks before reaching the same stall. Tag restored for run 3 |
| verify_roastery_round3_views.py | PASS (items 2 and 3: Log stub marker at desktop and 360px, BatchDetail header geometry at 360px) |
| verify_roastery_round3_passes.py | ALL ROUND 3 MANUAL PASS CHECKS PASSED (alarms editor flow at 360px, Log compare at 360px, import failure toast in Light; alarm definitions restored byte identical) |

The lab was left clean: database 7 batches, 101 series,
0 events; CurrentBatch Idle, Fan 5, Heat 5, BatchNumber
1042, ActiveSource Simulated, ThemeMode System,
DispAxisFormat m:ss, PeriscopeAvailable True,
PressEvents RUNNING, press slots cleared, simulator
parked. Three VM replacements interrupted the round;
each recovery was cluster start, gateway start, DDL and
reseed as needed, and a trial check (the maker trial
reset cron kept the trial healthy except one lapse
during the longest suite chain, recovered by
reset_trial.py). The FormProbe axis probe project
artifacts (view, page, tag folder) were removed at
round end.

### Round 4 candidates

1. HUNT-36: failure isolate the press capture path
   from the state machine, with a faulted database
   drill as the regression.
2. HUNT-35: decide and implement the batch delete
   cascade for press events.
3. The timezone TIME axis retest on the next Ignition
   beta (the passthrough candidates from round 2); the
   shipped category axis stays regardless.
4. The packaged Docker boot test on Eric's machine or
   homelab (still the one parity era item only he can
   run).

## Polish round 4 (2026-11-19)

Round 4 took the two findings round 3 held: HUNT-36
first (failure isolate the press capture path from the
state machine, with a faulted database drill as the
regression), then HUNT-35 (the batch delete cascade
decision), then a fresh hunting pass (HUNT-37 to
HUNT-40) across the surfaces rounds 1 to 3 changed
most, and the full closing battery. During the round,
Eric approved pushing rounds 1 to 3, and their content
went to GitHub in four connector commits (b2908f0,
13deca8, 2c4a23b, 606235a on top of 6f05c2e, 77 paths,
no deletions, verified by reading the docs back at the
new head). Round 4's own commits are local. One VM
replacement interrupted the round between items 1 and
2; recovery followed the established pattern and the
trial reset automation covered the trial throughout.

### Item 1: HUNT-36 resolved, press capture failure isolated

Round 3's wedge, restated: a press handler that hits a
faulted database connection mid flight can leave the
press stamped but the state transition unwritten (a
Reset during a faulted window left LastAction 'Reset'
with State still Roasting, recovered by hand at the tag
layer). The drill's first run found the mechanism, and
it is sharper than the round 3 note supposed: on this
build, system.db.runNamedQuery against a faulted
connection throws a Java exception
(FaultedDatabaseConnectionException over a PSQLException:
Connection refused), and a Java throwable is NOT a
Python Exception in Jython, so it tears through every
except Exception on the path. That is how it escaped
the capture code's existing guards and aborted the
caller's state write, and why the faulted Save in drill
run 1 never set its note. Every isolation catch on the
press and save paths is therefore a BARE except:, with
the evidence recorded in a comment at record_press.
(A live probe with Postgres stopped then proved the
point: reset_batch completed in 0.7 s with State Idle
and LastAction 'Reset'.)

The isolation, all in roastery.core unless noted:

- record_press is split into a public wrapper and
  _record_press_impl. The wrapper catches everything,
  logs through the new module logger
  (system.util.getLogger('roastery.core')), and returns
  the counter from a holder the impl fills the moment
  the counter is computed, else 0. No capture failure
  can abort charge, drop (via _stamp), cool, finish,
  reset_batch, stepper, or stamp_custom again.
- In the Group branch the press's own ring slot is now
  written BEFORE any database touch (the slot write is
  a tag write and cannot block on the connection), then
  reconcile runs; the new press sits inside its grace
  age, so the pass leaves it for the group as before.
- reconcile_press_pending fails fast and backs off: the
  first named query exception in a pass arms a module
  level backoff (PRESS_DB_BACKOFF_SEC 15.0) and ends
  the pass with no further database calls; a pass that
  starts before the deadline returns 0 without touching
  the database; a pass that completes with no database
  exception clears it. A faulted connection now costs
  roughly one blocking call per backoff window across
  all callers (record_press, the BeanTempF tick tail,
  charge, save). Grace (3 s) and horizon (600 s)
  semantics and the never raises contract are unchanged.
- save_current_batch (roastery.batches): the whole
  database section sits under the same bare catch. On
  failure it sets saveNote to a plain message (the
  batch was not saved, the database connection failed,
  nothing was written, try again once the connection
  is back), fires that message as an error toast, and
  returns None. The successful path, including the
  already saved guard, is unchanged; the get_batch
  check still runs first, so a fault present at entry
  means nothing was written and a retry after the
  connection heals saves completely.
- The rest of the stamp path was audited: append_log
  writes only the EventsLog dataset tag, and the only
  runNamedQuery sites in core are reconcile's select
  and insert and the Library mode insert in
  record_press. Nothing else in _stamp, charge, drop,
  cool, finish, reset_batch, or stepper touches the
  database outside record_press, reconcile, and save.

One operational fact the drill established: after
Postgres restarts, psql answers at once but the
gateway's own connection stays FAULTED for a variable
while (a retry about 150 s after a psql healthy restart
still hit FaultedDatabaseConnectionException). The
drill therefore waits on a gateway side probe (a
SelectByCounter named query driven through a probe tag
script) after each restart, not on psql health.

Regression: verify_roastery_pressfault.py, ALL PRESS
FAULT CHECKS PASSED. Sequence A (save containment):
roast to Complete on batch 1049 (counters 3059 to
3065, each exactly once), cluster stopped, the faulted
Save showed its failure note in 2.1 s with State still
Complete; after restart and gateway health, no batch
or series rows existed for 1049; the retry saved
completely (5 series rows, Save Batch press at 3066),
and the batch ended with exactly 8 press rows, one per
press, counters unique. Sequence B (the wedge itself):
scratch batch 9917, Charge healthy, cluster stopped,
then while faulted Dry End, Fan +1, FC Start, FC End,
Drop, Cool, Finish, Reset (the phase aware dock offers
no Drop before FC End, so the two crack stamps are the
faulted prerequisites, in the task's order otherwise):
every stamp and every state transition landed, State
Dropped, Cooling, Complete, then Idle with LastAction
'Reset', and ActionCounter advanced exactly once per
press (3069 to 3076). Healing: after restart, a Charge
and two more presses triggered the reconcile net, and
polling showed every faulted counter with exactly one
batch_events row, the Reset row included, no duplicates
after further reconcile triggers. verify_roastery_
pressburst.py passed twice consecutively on the final
design, and tier1 passed 42 of 42 in this item's runs.

### HUNT-35 resolved: batch delete cascades to press rows

Decision: deleting a batch deletes its batch_events press
rows too. The rationale: the saved batch document already
snapshots the press events at save time, and no surface
reads batch_events rows for a batch that no longer exists,
so orphaned rows are pure leftovers, not an audit trail
worth keeping.

A schema level FK cascade is NOT viable and was not
added: press rows are written during a roast for a
batch_number that has no row in batches until Save Batch,
so an FK from batch_events to batches would break live
press capture. The cascade therefore lives in the delete
flow, next to the existing series behavior (batch_series
has a real FK ON DELETE CASCADE). Implementation:
roastery.batches.delete_batch runs the new named query
Roastery/Events/DeleteByBatch first, then
Roastery/Batches/Delete; if the events delete throws, the
error propagates and the batch is not deleted, rather
than stranding the rows silently. The Log page delete
confirm text now names the press log alongside the curve.
Regression: verify_roastery_deletecascade.py drives the
real Log page delete and asserts the fixture batch's
series and press rows are gone, a control batch is
untouched, and press rows for a batch number with no
batches row (the live roast case) survive other deletes
and can still be inserted (15 checks, all passed). One
suite hygiene note: verify_roastery_tier1.py deletes
its own test batch with raw psql, bypassing the app
delete flow, so its press rows still appear as residue
after a tier1 run and are cleaned by hand; that is test
scaffolding behavior, not an app gap, and the cascade
itself is proven through the real delete above.

### Item 3: the HUNT-37 onward hunting pass

Fresh eyes across the round 4 scopes, driven by
verify_roastery_r4hunt_a.py through _e.py (screenshots
r4hunt- in the lab showcase/shots). One roast stamped
Dry End, Fan Boost, FC Start, Drum Note and FC End two
seconds apart (elapsed 5, 6, 8, 9, 10 s) and was saved
as fixture batch 9919 for the detail checks, then
deleted through the app. The seek pass dropped at
program second 352 (temp 333.2 F, cooling target 785)
and pressed Cool and Fan +1 during the seek.

Clean, with evidence: the live chart in both themes at
desktop and 360px (labels suppress rather than collide:
the reflines probe returned six lines with exactly the
CHARGE label visible, the settled top_gap design; tick
labels sparse and legible; legend clear of the axis);
the App Settings dock mid roast (content rect identical
before, during and after, 920 by 748 at x 20 y 176; the
dock clamps to the 360px viewport; theme walk System to
Dark to Light to System to Dark recolored the chart
each time with the roast undisturbed, ActionCounter
unchanged; after Close the dock sits fully off viewport
at x equal to the viewport width); the seek pass (nine
presses, nine batch_events rows, every action exactly
once, the mid seek Cool and Fan +1 included; seek landed
at counter 788 in Cooling); the Log in both column sets
at desktop and 360px (stub markers, compare staging
with its caption, the phone All columns toggle); the
Settings sections at 360px (every card scrollWidth equal
to clientWidth, both visible tables 284 of 284, no stray
checkbox labels, Alarms editor and Custom Events and
Targets and Background all inspected); toasts (the
Settings background failure toast and the Log import
failure toast both fire within 0.3 s of the upload, the
HUNT-29 fix verified live; part B's earlier miss was a
harness timing artifact, and the file upload component
modal that blocked its clicks is stock small viewport
component behavior that dismisses on one backdrop tap);
the HUD RoR reading of two dashes during the post
charge dip (the settled Artisan gating in
ror_display_text, not a defect).

- HUNT-37 (minor, held): on BatchDetail a short batch
  reads mostly empty chart. The detail grid floors at
  DETAIL_MIN_SPAN_SEC 600 (the round 2 tick span fix),
  so fixture 9919 (43 s, events at 0, 5, 6, 8, 9, 10,
  42, 43 s) plots across a 0:00 to 9:54 axis with the
  curve in the first tenth, and detail_reference_lines
  uses the live chart's 55 s label gap from CHARGE, so
  all seven later event lines render unlabeled. Nothing
  overlaps and the events timeline names every event,
  but the chart itself communicates little on short
  batches. Held: both constants are deliberate round 2
  and 3 settlements (HUNT-10's smear sits on the other
  side), so the right fix is a product call, scaling
  the floor and the gap to the staged span (for
  example floor at the larger of 180 s and the batch
  extent, gap proportional to span), then re-proving
  tick legibility at 360px. Evidence:
  r4hunt-detail-close-desktop-light.png,
  r4hunt-detail-close-360-light.png.
- HUNT-38 (minor, held): theme changes do not reach
  already open sessions. ThemeMode is applied at
  session startup and by the session's own App Settings
  buttons; writing Dark from elsewhere left a watched
  session at container #F4F4F4 (light) indefinitely,
  and that session's App Settings panel showed Dark
  selected while rendering light
  (r4hunt-appsettings-360-dark.png,
  r4hunt-xsession-after-dark-write.png). With the
  phone plus desktop two session pattern this leaves
  the devices in different themes until a reload.
  Held: the theme plumbing is settled round 1 to 3
  work with a verified polish2 matrix; the fix (a
  reactive session binding on ThemeMode, or the panel
  reflecting the session's actual theme instead of
  the tag) deserves its own item, not a mid hunt edit.
- HUNT-39 (cosmetic, held): the custom event buttons
  wrap their labels to two lines (Custom 3, Custom 4,
  Drum Note) in the desktop Controls rail and the
  phone dock. The text stays inside the buttons and
  nothing overlaps; it reads as a nit next to the
  single line primary labels. Held: shrinking the
  shared button text or widening the repeater buttons
  is a design call. Evidence:
  r4hunt-close-live-desktop-light.png,
  r4hunt-close-live-360-light.png.
- HUNT-40 (minor, fixed): arming a Log delete showed
  two prompts at once with different wording: the red
  confirm banner read 'Delete batch N and its curve?'
  while the note under it read 'Delete batch N, its
  curve and its press log? Press Confirm Delete to
  proceed.' The banner beside the Confirm button was
  the one omitting the press log, partially undoing
  the HUNT-35 wording. Fix: the banner's expression
  in Views/BatchesPanel now names the press log too
  (gateway and repo view.json, and the same string in
  both build_roastery_v4.py copies so a rebuild keeps
  it). Proof: r4hunt-delete-armed-desktop.png after
  the fix shows banner and note in agreement;
  validate_roastery_artisan.py VALIDATION PASS and
  verify_roastery_deletecascade.py ALL CHECKS PASSED
  with the change in place.

The lab was left clean: database 7 batches, 101
series, 0 events; CurrentBatch Idle, Fan 5, Heat 5,
BatchNumber 1042, ThemeMode System, DispAxisFormat
m:ss, PeriscopeAvailable True, PressEvents proven
writing at the end state, press slots cleared,
simulator parked (Pause true, counter 0, base rate
1000, probe at the 392 F plateau).

### Verification

The closing battery ran standalone per suite on the
final build (logs in the lab battery_logs/r4close-*
set). No regression in the axis, dark mode, or slide
over work: dark passed clean, every functional axis
check passed (all three timezone shots and the mm:ss
format shot), and polish2's App Settings flows passed
against the dock. No VM replacement interrupted the
battery; the pressfault suite stopped and restarted
Postgres itself, by design.

| Suite | Result |
| --- | --- |
| validate_roastery_artisan.py | VALIDATION PASS (29 views served, all deep equal, no Roastery warnings) |
| validate_chartlab.py (gateway-2027-maker) | VALIDATION PASS |
| verify_roastery_ror.py | 6 PASS, 0 FAIL, 1 designed SKIP (live window not on a steady ramp segment; the offline proof is the authority), ALL ROR CHECKS PASSED |
| verify_roastery_pressburst.py | 6 PASS, 0 FAIL, ALL PRESS BURST CHECKS PASSED (11 bumps, 11 rows) |
| verify_roastery_pressfault.py | Run 1: 60 PASS, 2 FAIL, both in sequence A's row accounting: one extra Reset row at the counter immediately before the driven Charge, traced to the suite's own setup and New Roast flow landing under the fresh batch number. Run 2, identical procedure: 62 PASS, 0 FAIL, ALL PRESS FAULT CHECKS PASSED, rows exactly matching the driven presses. Judged a harness attribution flake on that evidence; every fault, heal, and state check passed in both runs |
| verify_roastery_deletecascade.py | 15 PASS, 0 FAIL, ALL DELETE CASCADE CHECKS PASSED |
| verify_roastery_axis.py | 11 PASS, 1 FAIL: the documented BatchDetail shot harness flake, this time the Log row click before the shot timing out under load (the dark suite hit the identical click timeout in the same spot and its detail check passed). All timezone and format shots passed and the suite's closing checks (lab Idle, clean, format and theme restored) all passed |
| verify_roastery_dark.py | 10 PASS, 0 FAIL, ALL DARK MODE CHECKS PASSED |
| verify_roastery_tier1.py | 42 PASS, 0 FAIL, ALL TIER 1 CHECKS PASSED (its psql cleanup left 11 press rows, cleaned between suites; see the HUNT-35 suite hygiene note) |
| verify_roastery_tier2.py | 87 PASS, 0 FAIL, ALL TIER 2 CHECKS PASSED on the first run (the documented starting count race did not occur) |
| verify_roastery_tier3a.py | 40 PASS, 0 FAIL, ALL TIER 3A CHECKS PASSED |
| verify_roastery_tier3b.py | 47 PASS, 0 FAIL, ALL TIER 3B CHECKS PASSED (the documented reload recovery fired once, in the final walk's Finish step, and the retry passed) |
| verify_roastery_tier3c.py | 67 PASS, 0 FAIL, ALL TIER 3C CHECKS PASSED |
| verify_roastery_v4.py | 59 PASS, 0 FAIL, ALL CHECKS PASSED, matching round 3's closing count (the documented reload recovery fired once in the dark pass) |
| verify_roastery_polish1.py | 46 PASS, 0 FAIL, ALL POLISH ROUND 1 CHECKS PASSED |
| verify_roastery_polish2.py | 65 PASS, 0 FAIL, ALL POLISH2 CHECKS PASSED, including the App Settings flows against the slide over dock |
| verify_roastery_polish3.py | Run 1 crashed after 29 PASS, 0 FAIL at the kill switch editor save (the documented aged session stall: editor Save Batch never enabled), leaving PeriscopeAvailable False; tag restored and run 2: 37 PASS, 0 FAIL, ALL CHECKS PASSED |
| verify_roastery_round3_views.py | 6 PASS, 0 FAIL, ALL ROUND 3 VIEW CHECKS PASSED |
| verify_roastery_round3_passes.py | 15 PASS, 0 FAIL, ALL ROUND 3 MANUAL PASS CHECKS PASSED |

The lab was left clean at the end of the battery:
database 7 batches, 101 series, 0 events; CurrentBatch
Idle, BatchNumber 1042, Fan 5, Heat 5, ActiveSource
Simulated, ThemeMode System, DispAxisFormat m:ss,
PeriscopeAvailable True, PressCaptureMode Group,
background cleared, all 16 press slots empty,
simulator parked. PressEvents is RUNNING by functional
proof across the battery (pressburst's 11 bumps landed
as 11 group rows; tier3b's through the group check and
polish3's post restart write check both passed); the
beta REST API exposes no transaction group status
endpoint to quote directly.

### Round 5 candidates

1. HUNT-37: scale the BatchDetail span floor and the
   event label gap to the staged span, so short
   batches read as charts instead of mostly empty
   axes, then re-prove tick legibility at 360px.
2. HUNT-38: theme changes reaching already open
   sessions (a reactive session binding on ThemeMode,
   or the App Settings panel reflecting the session's
   actual theme), for the phone plus desktop two
   session pattern.
3. HUNT-39: the custom event buttons' two line labels
   (a design call: shared button text size versus
   wider repeater buttons).
4. The timezone TIME axis retest on the next Ignition
   beta (the passthrough candidates from round 2); the
   shipped category axis stays regardless.
5. The packaged Docker boot test on Eric's machine or
   homelab (still the one parity era item only he can
   run).

## Polish round 5: theme reactivity, short batch detail, dock labels (2026-11-19)

Round 5 closed the three items held from round 4
(HUNT-37, HUNT-38, HUNT-39), then the closing
screenshots found one more: the detail chart's event
labels collide at 360px (HUNT-41, fixed in the round).
The hunting pass added HUNT-43 and HUNT-44, and the
closing battery found HUNT-45 (the Reset press
landing on the wrong batch, fixed in the round).
The round was interrupted mid close by a VM write
lock incident (the VM refused data writes system wide
at 16:38 UTC, Postgres panicked, the gateway JVM died
and could not restart from the agent exec domain), and
again by a runtime restart during the fixture delete;
both recoveries followed the established pattern
(Postgres reinstall, cluster start, role and database
recreation, DDL, gateway start, reseed check) and the
lab came back clean at 7 batches, 101 series, 0
events with all defaults restored. A third runtime
restart hit during the HUNT-43 and HUNT-44 fix
verification: the gateway was down and Postgres came
back with an empty database (0 batches, 0 series),
so the recovery ran the DDL again and reseeded from
the RoastLog tag (7 batches, 101 series), the trial
was already healthy at 7153 s, and BatchNumber was
written back to 1042. The verification reran clean
after that recovery.

### Item 1: HUNT-38 resolved, theme changes reach open sessions

Route (a), a binding on the session theme property,
is NOT honored on this build (documented with
evidence in the round 4 hunt notes). Route (b)
shipped: the HudBar view carries a view custom prop
bound to the ThemeMode tag with an onChange script
calling the new library function
roastery.core.on_theme_mode_change, which runs the
existing apply_theme plus the brightness re-probe,
and the HudBar top dock is mounted on every page, so
a ThemeMode write from anywhere (another session's
App Settings buttons, a direct tag write) re-applies
the theme in an already open session without a
reload. Panel truthfulness shipped with it: the App
Settings mode buttons derive their selected style
from session.props.theme via a map transform, so the
panel can no longer show Dark selected while the
session renders light. Two session proof: 12 PASS, 1
FAIL, and the FAIL was a contaminated start check
(another worker's roast running when the check ran),
not a theme result. Session 2 followed session 1's
App Settings change and direct tag writes in both
directions, charts recoloring each time. Files:
core/code.py, Views/HudBar/view.json,
Views/AppSettings/view.json. Evidence: the r5-theme-*
screenshots.

### Item 2: HUNT-37 resolved, short batch detail spans

batches/code.py only: _detail_span floors the staged
grid at max(180, end_sec) for spans under 600 (600
and up untouched), _detail_top_gap scales the event
label gap proportionally (55 s at 600 span, 16.5 s
at the 180 floor). Byte identical proof for a normal
batch: fixture 9920 (720 s) staged before and after,
canonical JSON exactly equal (captures
r5_detail_before.json and r5_detail_after.json in the
lab). Short batch 9919 (43 s) went from 601 rows
with only CHARGE labeled to 181 rows (axis to 3:00)
with CHARGE and the 42 s custom labeled. The 360px
screenshot set and one clean desktop set prove the
labels read: r5-detail-short-360-light.png,
r5-detail-short-360-dark.png,
r5-detail-short-desktop-light.png,
r5-detail-short-desktop-dark.png,
r5-detail-1042-desktop-light.png,
r5-detail-normal-desktop-light.png.
validate_roastery_artisan.py VALIDATION PASS and
verify_roastery_axis.py 10 PASS, 2 FAIL, both
failures explained below (the detail shot click
timeout is the HUNT-42 harness locator, fixed in
this round; the lab clean check ran while the 9919
and 9920 fixtures were still in the database).

### Item 3: HUNT-39 resolved, dock button labels on one line

Root cause: no white-space control in the button
class chain, and repeater slots narrower than the
text (custom slots 52.3px desktop, 48.6px at 360px,
against about 62px needed). Fix inside the style
system: new classes roast-btn-dock (12px) and
roast-btn-dock-lead (14px) emitted by
Views/DockButton/view.json, one advanced stylesheet
rule pinning nowrap with hidden overflow and
ellipsis, repeater instance floors in
Views/Controls/view.json and Views/ControlDock/
view.json (lead basis 108px, utility 148px, others
88px, shrink 0; the phone dock repeater wraps to two
balanced rows). Long name backstop proven with a 28
character custom name (one line, no page overflow;
Chromium does not draw the ellipsis glyph for
centered button text, so over long names truncate by
center clipping). Phase aware dock behavior
unchanged and re-proven at three phases.
validate_roastery_artisan.py VALIDATION PASS.
verify_roastery_polish1.py: every functional check
passed; its single failure was the baseline count
check, contaminated by the HUNT-37 fixtures then in
the database (clean rerun in the closing battery).
Evidence: the r5-dockbtn-* screenshots.

### Item 4: HUNT-41 fixed, detail labels collide at 360px

The HUNT-37 screenshot set decided the open
geometry question with a yes: on batch 1042 the
CHARGE and DROP labels sit 19 s apart and print as
one word, CHARGEDROP, at 360px, and on batch 9919
CHARGE and the 42 s LATE NOTE print as CHARGELATE
NOTE. The desktop gap (16.5 s at the 180 s floor)
is correct at desktop widths, where the same two
labels sit about 95px apart and read cleanly, so a
global gap increase would regress desktop. Fix, the
paired instance pattern already used by the live
chart and the HUNT-13 phone tables: the BatchDetail
chart now ships in two instances switched by the
roast-cols-full and roast-cols-phone media query
classes, the desktop instance keeping
detail_reference_lines and the phone instance
binding the new detail_reference_lines_compact,
whose gap is 0.26 of the staged span (about 65px of
clearance on the roughly 250px phone plot; 46.8 s at
the 180 s floor, 187 s at a 720 s span, close to the
live chart's proven 175 s compact gap). Proof:
r5-detail-1042-360-light-fixed.png and
r5-detail-short-360-light-fixed.png show only
CHARGE labeled with the second event's line present
but unlabeled, and
r5-detail-1042-desktop-light-fixed.png shows CHARGE
and DROP both labeled as before. Files:
batches/code.py (detail_reference_lines refactored
over a shared _detail_reference_lines body plus the
compact variant) and
Views/BatchDetail/view.json (DetailChartPhone
instance).

### Item 5: HUNT-42 found and fixed, the Log row click locator

While deleting the HUNT-37 fixtures through the Log
page UI, the row click timed out three times at 45 s
each, and the axis suite's detail shot failed on the
same click. The cause is a harness locator, not the
app: the scripts clicked locator('tr', ...), but the
Log table is Perspective's Table component, which
renders divs (ia_table__cell) and no tr elements at
all, so the locator can never match. The probe
screenshot shows the table fully populated with all
nine batches while the locator counts zero rows. Fix:
the locators in verify_r5_detail_span.py (stage and
delete paths), verify_roastery_axis.py, and
verify_roastery_dark.py now click the batch cell by
its displayed text with the thousands separator
(text=9,919, text=1,044), proven live: the cell
click selects the row (SelectedBatchNumber 9919,
Delete enabled) and both fixtures then deleted
through the app UI with the HUNT-35 cascade, the
database returning to 7 batches, 101 series, 0
events. The round 4 battery's identical axis detail
failure was the same locator, misattributed to load
at the time. Evidence: r5-log-probe.png.

### Item 6: the HUNT-42 onward hunting pass

The hunting pass ran as verify_r5_hunt.py (live roast at
360px), verify_r5_hunt2.py (abandoned mid run, see
below), and verify_r5_hunt3.py (fix verification plus
the parts of the pass that had not run). Two new items
were found and both were fixed in the round.

HUNT-43 (minor, fixed): the New Roast button wrapped
to two lines at 360px (56px tall, 84px wide). It is a
utility button in the Controls head row, not a dock
button, so the HUNT-39 dock rule did not cover it.
Fix: a new style class roast-btn-nowrap (one advanced
stylesheet rule, white-space nowrap, no ellipsis) and
the class added to the button in Views/Controls. The
button sizes to its content in its flex row, so
nowrap alone keeps it one line. Proven live: 44px
tall at 360px and at desktop, one line both places.
Files: stylesheet.css, Views/Controls/view.json, new
style-classes/roast-btn-nowrap/ (resource.json plus
an empty style.json; the behavior lives in the
stylesheet, same pattern as the dock classes).
Evidence: r5hunt-controls-360-light.png (before),
r5hunt-phases-360-fixed3.png (after, button one line).

HUNT-44 (minor, fixed): the phase bar detail captions
clipped at 360px. The Development segment (2:30
target, 65px wide at 360px) has 4px of side padding,
leaving about 57px for its caption, so the 11px
"target 02:30" lost a couple of pixels on each side
while Drying and Maillard read fine. The clip is
contained by design (the segment text classes clip
inside the segment, per the earlier fix documented
in the stylesheet), so the layout held, but the
caption was unreadable. Fix: a phone media query in
the advanced stylesheet dropping
.psc-roast-seg-detail to 9px at 560px and under,
desktop untouched. Two iterations: 10px fixed the
left side only (the trailing "0" still cut), 9px
renders the caption complete. The plain rule did not
take effect at first; the style class sets 11px and
its generated rule beats a plain advanced stylesheet
rule, so the media query carries !important, with
the reason recorded in the stylesheet comment.
Lesson: a scrollWidth probe is not a reliable clip
check here (it reported no clipping while the
screenshot showed the caption cut); the screenshot
is the evidence. Files: stylesheet.css only.
Evidence: r5hunt-live-360-light.png (before,
"arget 02:3("), r5hunt-phases-360-fixed.png (10px,
trailing "0" still cut), r5hunt-phases-360-fixed3.png
(9px, "target 02:30" complete).

The two session theme walk (part A of the hunting
pass) was DROPPED after three wedge attempts: two
contexts in one single-process browser die with
TargetClosedError when the second opens a page, and
two simultaneous browsers wedge the VM (the third
attempt hung 7 minutes and was killed by exact PID).
HUNT-38's proof stands on the pre-incident 12 PASS
record and the r5-theme-* screenshots; the pattern
for multi-session work is one fresh browser per
session, never two contexts in one browser. The same
single-process limitation hit the hunt2 script (it
died opening its second context) and the r5 detail
screenshot loop (fixed by one fresh browser per
shot).

Parts C and D of the pass ran clean in hunt3: App
Settings at 360px in Dark has zero page overflow,
and the Log compare view at 360px has zero
horizontal overflow. Evidence:
r5hunt-settings-360-dark.png, r5hunt-compare-360.png.

Checked clean with evidence: the live roast at 360px
had no horizontal overflow (0px) and all dock labels
on one line; the phase tile clipping first seen in
the hunt screenshot was re-measured on the visible
root only (the first probe had measured the hidden
desktop root's labels) and is HUNT-44 above, not a
separate defect. The hunt roast's 8 press rows on
batch 1042 (counters 3446 to 3453, each action
exactly once, no gaps) were cleaned with psql, the
same residue hygiene as round 4. One cosmetic
observation is carried to round 6, not filed as a
defect: the MODE pill wraps to two lines ("MODE" /
"Off") at 360px; both lines render fully, nothing
clips or overlaps, it is a layout call.

### Item 7: HUNT-45 found in the closing battery, the Reset press landed on the wrong batch

The closing battery's pressfault run failed its two
aggregate checks and nothing else (60 PASS, 2 FAIL):
batch 1049's press log opened with 'Reset|3646'
ahead of the eight driven presses, so "exactly one
event row per press" and "event counters are unique
and present" both failed. The mechanism is in the
PressEvents group, not the library: the group's
BatchNumber item read the LIVE BatchNumber tag at
execution time, and new_roast writes the new number
milliseconds after record_press('Reset'), so the
group always stamped the Reset row with the NEW
batch number. The Reset press belongs to the batch
it clears (the old number), and the new batch's log
should open with its Charge, not a Reset from before
it existed. Proven by direct repro: a UI New Roast
click wrote Reset|3670 against batch 1049 while the
live number already read 1050.

Fix: the group now stamps press-time identity. A
new RoastBatch UDT member LastActionBatchNumber
(Int4, memory, default 1042) is stamped by
roastery.core._record_press_impl on every press
alongside LastAction, and the group's BatchNumber
item now reads
[default]Roastery/CurrentBatch/LastActionBatchNumber
instead of the live BatchNumber. The value columns
(BeanTempF, RateOfRiseF, FanLevel, HeatLevel) still
read live at execution, as designed; only the
identity column is press-time. The UDT member was
added by importing the updated definition over the
live UDT (POST /tags/import, collisionPolicy
Overwrite, 203 members, successCount 1); the repo
script setup_roastery_artisan_tags.py is stale (it
never learned the press-capture members) and was
deliberately NOT patched for one member, see the
round 6 candidates. Proof: the same UI repro now
writes Reset|3681 against batch 1049 while the live
number reads 1050, and the pressfault rerun passed
62 of 62 with exactly the eight expected rows. One
trip hazard from the proof: a psql delete of a press
row is undone by the reconciler (it re-inserts the
slotted context), so the probe row was cleared by
emptying its ring slot first and then deleting the
row. Files: core/code.py (stamp), the PressEvents
group config.json (repoint), the live UDT
definition (new member, gateway side).

### Verification

Closing battery, 19 suites, all green on the final
code (the battery ran twice: the first pass caught
three harness and residue issues plus HUNT-45, each
explained below, and the reruns below are the
record). Counts are PASS lines per suite log in
the lab under r5-battery/.

- validate_roastery_artisan.py: VALIDATION PASS
  (29 views served deep equal, 12 named queries,
  94 style classes on disk, zero offenders; the
  rerun right after the pressfault drill printed
  CHECK REPORT on the drill's deliberate database
  stop in its 15 minute log window, and passed
  clean once the window cleared).
- validate_chartlab.py: VALIDATION PASS.
- verify_roastery_ror.py: 6 PASS, 1 designed SKIP.
  First run failed the live slope check (24.42 vs
  21.42 F/min); the known under-load RoR race
  flake, passed on rerun with no code change.
- verify_roastery_tier1.py: 42 of 42.
- verify_roastery_tier2.py: 87 of 87. First run
  failed only its closing baseline check, on press
  rows the aborted RoR run had left behind; passed
  on rerun from a clean lab.
- verify_roastery_tier3a.py: 40 of 40.
- verify_roastery_tier3b.py: 47 of 47.
- verify_roastery_tier3c.py: 67 of 67.
- verify_roastery_v4.py: 59 of 59. The v4 suite
  leaves one Reset press row and a loaded
  background behind, which tripped the next two
  suites' start-baseline checks; the residue is a
  suite hygiene note, not an app gap.
- verify_roastery_polish1.py: 46 of 46 on rerun
  from the reset lab (first battery run: 2 FAILs,
  the v4 residue above).
- verify_roastery_polish2.py: 65 of 65 on rerun
  (first battery run: 1 FAIL, the same residue).
- verify_roastery_polish3.py: 37 of 37.
- verify_roastery_dark.py: 10 of 10, including
  the detail shot the HUNT-42 fix enabled.
- verify_roastery_pressburst.py: ALL PRESS BURST
  CHECKS PASSED (rerun after HUNT-45).
- verify_roastery_pressfault.py: 62 of 62 on
  rerun after HUNT-45 (first run: 60 PASS, 2 FAIL,
  the HUNT-45 defect; the rerun's aggregate check
  shows exactly the eight expected rows).
- verify_roastery_deletecascade.py: 15 of 15.
- verify_roastery_axis.py: 12 of 12, all three
  timezone shots and the mm:ss format shot
  passing (round 4 had 11 PASS, 1 FAIL on the
  detail shot; the HUNT-42 text locator fixed
  it).
- verify_r5_detail_span.py: data proof
  reproduced on the final code (fixture 9920
  byte identical to the pre-change capture at 721
  rows to 12:00; fixture 9919 down from 601 rows
  to 181 rows to 3:00). Its shots mode crashed
  on the single-process browser limit after the
  first shot (harness, not the app); the seven
  shots from the close stand as the visual
  record.
- verify_r5_hunt3.py: PASS, no failures (New
  Roast one line at 360px and desktop, detail
  font 9px at 360px with no clip, settings at
  360px in Dark zero overflow, compare at 360px
  zero horizontal overflow).

Battery incidents, all recovered: /tmp filled to
100 percent mid battery because the runner's
cleanup missed the suites' *.idb log copies; the
runner now removes them and resumed cleanly. A VM
replacement killed the runner during the dark
suite (recovered: Postgres reinstall, role and
database recreation, DDL, gateway start, reseed,
defaults restored, battery resumed from the dark
suite). A second runtime restart hit during the
detail span delete (recovered the same way; the
fixtures were gone with the fresh database, so
the lab came back clean).

The lab was left clean at the end of the battery:
7 batches (1042 to 1048, Ethiopia Guji), 101
series rows, 0 events, CurrentBatch Idle with Fan
5, Heat 5, BatchNumber 1042, ActiveSource
Simulated, Mode Off, DispAxisFormat m:ss,
PressCaptureMode Group, ThemeMode System,
PeriscopeAvailable True, SelectedBatchNumber 1042,
background cleared. Gateway RUNNING, trial
healthy. PressEvents RUNNING by functional proof
(the pressfault and pressburst reruns both
passed after the HUNT-45 repoint).

### Round 6 candidates

1. The timezone TIME axis retest on the next
   Ignition beta (the passthrough candidates from
   round 2); the shipped category axis stays
   regardless.
2. The packaged Docker boot test on Eric's machine
   or homelab (still the one parity era item only
   he can run).
3. The MODE pill wraps to two lines ("MODE" /
   "Off") at 360px; both lines render fully,
   nothing clips or overlaps, it is a layout
   call.
4. The short-batch dashed event line cluster at
   the left edge of the detail chart, which
   matches the settled live-chart design of
   keeping lines while dropping labels and is a
   product call.
5. Reconcile roastery/scripts/
   setup_roastery_artisan_tags.py with the live
   UDT: the script never learned the
   press-capture members (ActionCounter,
   LastAction, LastActionAt,
   LastActionElapsedSec) or LastActionBatchNumber,
   so a rebuild from it would drop them. The
   live UDT is the source of truth until then.
6. The phantom Charge press during the hunt3
   verification (a roast started on batch 1042
   at 01:55:26 UTC with no suite pressing
   Charge); a 30 second Log page load test
   afterwards did not reproduce it, and no
   mechanism was found. Watch for a repeat
   before filing it.
7. The validator's 15 minute log window counts
   the pressfault drill's deliberate database
   stop as a warning; a drill-aware window (or
   a validator run after the window clears)
   keeps the verdict clean.
8. The v4 suite leaves one Reset press row and
   a loaded background behind for the next
   suite; make its cleanup match the tier
   suites' so the battery needs no residue
   reruns.

## Polish round 6: custom buttons, MODE pill, detail lines (2026-11-19/20)

Eric's feedback opened the round (2026-11-19 evening, from
the live session): "I don't know what drum note, custom.3
or custom 4 buttons do, but they take up a ton of space.
But they mean nothing to me. I have a fluid bed roaster,
I don't even have a drum." The standing brief (2026-11-19)
is to keep refining and finding bugs, keep making updates
based on Artisan, keep updating the math and making it
better, high quality graphics and helpful dynamic views and
pages, smoothing out rough edges. The round covers the
eight scope items in order, then a hunting pass.

### Item 1: Eric's custom buttons (Eric item)

The defaults named all four custom slots (slot 1 'Fan
Boost' / 'Airflow', slot 2 'Drum Note' / 'Note', slot 3
'Custom 3' / 'Info', slot 4 'Custom 4' / 'Info'), so the
Controls rail and the phone dock showed four custom buttons
and the EventsStrip showed four custom cells. His SR800 is
a fluid bed roaster with no drum, so 'Drum Note' meant
nothing, and 'Custom 3' / 'Custom 4' were placeholders.

Fix, all in the library and the views:

- core.dock_actions() now skips any slot whose name is
  None or blank after strip (the old 'Custom %d' fallback
  is gone). The dock shows one custom button (Fan Boost)
  instead of four.
- core.stamp_custom() returns False for a blank name, so
  an unnamed slot cannot be stamped by any caller (the
  guard lives in the library, not only in the view, the
  same pattern as the Enabled guard from polish round 1).
- The live UDT defaults changed to match: slot 1 'Fan
  Boost' / 'Airflow', slots 2 to 4 blank name and kind
  (exported the live UDT, set the six defaults to '',
  imported over it with collisionPolicy Overwrite,
  successCount 1, then wrote the live instance values
  directly, all code 192).
- Settings, Custom Events gained the sentence "Leave a
  name blank to hide that button until you name it."
  Custom events stay renamable and showable in Settings
  for ones he names himself.
- The EventsStrip cells hide by class (HUNT-47, below):
  a props.style.classes expression binding returns
  'roast-cell-hidden' when the slot name is blank, and
  the advanced stylesheet hides it with display none.
  A props.visible binding was tried first in two forms
  (an expression binding, then a tag binding with an
  expression transform) and neither hid the cells on
  this build, so the class hide is the shipped form and
  the visible bindings were removed again.

Proof, verify_r6_customs.py, 17 checks, ALL R6 CUSTOMS
CHECKS PASSED, live at desktop and 360px:

- Phone dock before Dry End: ['Dry End', 'Fan Boost',
  '-', '+', '-', '+'] only. Controls rail: ['Dry End',
  'Fan Boost'] only. Events strip: 8 cells (7 standard
  plus Fan Boost), no blank cells.
- Naming slot 3 'Test Note' in Settings puts its button
  on the dock and its cell in the strip (9 cells);
  clearing the name drops both again (8 cells).
- stamp_custom on an unnamed slot returns False with 0
  press rows; on Fan Boost it returns True with exactly
  1 press row.
- Lab counts back to the start of the run, Idle on batch
  1042.

Screenshots: r6-customs-dock-360.png (phone dock, two
buttons), r6-customs-rail-desktop.png (Controls rail,
two buttons), r6-customs-strip-desktop.png,
r6-customs-named-360.png. Suites updated for the new
defaults: verify_roastery_polish1.py (CUSTOMS is now
only Fan Boost, plus name/hide checks), verify_roastery_
polish2.py (setup names slots 3 and 4 explicitly for the
dock test, teardown restores blanks), verify_roastery_
r4hunt_a.py (setup names slot 2 'Drum Note' explicitly).

### Item 2: MODE pill on one line (round 6 candidate 3)

The pill read "MODE Off" and wrapped to two lines at
360px. Measured: the pill was 70.58px wide and 36px tall
(two lines), and the HeadRow is exactly full (heading
128.19px plus pill 70.58px plus "New Roast" 87.23px
equals the 286px row), while "MODE Roast" needs about
89px at 11px bold, so no font or padding tweak can fit
the prefix in every mode. Fix: the Controls view's
ModePill text expression now shows just the mode value
(Off, Roast, Cool); the section heading already says
Roaster Controls and the pill color still codes the mode
(gray, red, blue). A stylesheet rule pins the pill to
nowrap so a future longer mode value cannot wrap it
again. Measured after: 360px pill 'Off', 41.9px wide,
21px tall (one line), row and page overflow 0; desktop
'Off', 42px wide, 21px tall. Screenshots:
r6-mode-pill-360-before.png, r6-mode-pill-360-after.png,
r6-mode-pill-desktop-after.png.

### Item 3: short-batch dashed line cluster (round 6 candidate 4)

On a short batch the detail chart drew every event's
dashed vertical line, so fixture 9919 (43 s extent, 180 s
floored span) showed six lines in the first 10 s, 1.4 px
apart on the roughly 250 px phone plot, merging into a
solid band at the left edge. The label gap already
dropped labels for close events but kept every line. The
fix thins the LINES with a separate, much smaller gap
than the label gap: new constant DETAIL_LINE_GAP_FRAC =
0.03 in batches/code.py, passed as line_gap = 0.03 of
span into core._ref_items (new optional line_gap
parameter). An unlabeled line closer than line_gap to
the last kept line is dropped; a labeled line is never
dropped, and when a labeled line lands within line_gap
of a kept unlabeled line the unlabeled one goes instead,
so every visible label keeps its line. With line_gap
None (the live chart callers) the path is identical to
before. 0.03 of span is about 7.5 px on the phone plot
and about 30 px on desktop. Thinning lines by the label
gap was rejected: it would drop real lines on a normal
batch (fixture 9920's FC END and SC END sit 30 s from
their neighbors, under the 55 s label gap).

Data proof, capture before (round 5
r5_detail_after.json) versus after (/tmp/r6_detail_after.
json), staged through the library on the gateway:

- Fixture 9920 (720 s, 721 rows): reference items byte
  identical, 7 lines, same labels. Grid and marks
  identical.
- Fixture 9919 (43 s, 181 rows): 8 lines to 3 lines
  (CHARGE 0:00, FC START 0:06, LATE NOTE 0:42); labels
  unchanged (CHARGE and LATE NOTE). Marks identical:
  all 8 events are still plotted as marks, only the
  vertical lines thinned. The DROP line at 0:43 carried
  no label and is named in the events strip.
- Batch 1042: the current seed's document has only two
  events (CHARGE 0, DROP 19); the round 5 capture's
  document had a third (Dry End 10). The 3 to 2 line
  difference against round 5 is that reseed shape
  difference, not a thinning effect: with the current
  document both lines are kept, and worker B's
  before/after on the same document is byte identical
  for 1042 in both variants.

Visual proof: r6-detail-short-360-light.png (phone plot,
three separated dashed lines, CHARGE and LATE NOTE
labeled), r6-detail-short-desktop-light.png,
r6-detail-1042-360-light.png (HUNT-41 intact: only
CHARGE labeled on the phone instance, DROP line present
but unlabeled, no CHARGEDROP collision).

### Item 4: UDT script reconciled with the live UDT (round 6 candidate 5)

roastery/scripts/setup_roastery_artisan_tags.py is now
the faithful record of the live UDT. It had 81 members;
the live RoastBatch UDT has 203 (202 atomics plus the
Sources folder), and the script never learned the
press-capture members or LastActionBatchNumber, so a
rebuild from it would have dropped them. The script was
regenerated mechanically from a live export (not hand
typed) and now carries all 203 RoastBatch members plus
the 7-member RoasterSource UDT, including BeanTempF as
an expression tag over ActiveSource with history on db
and the on_bean_temp valueChanged script, RateOfRiseF
with history on db, the Sources folder with per-instance
overrides, and the round 6 custom defaults (slot 1 'Fan
Boost' / 'Airflow', slots 2 to 4 blank). Proof:
/tmp/r6_udt_diff.py compares the script against a fresh
live export on name, data type, value source, default
value and presence, history settings, expression, event
scripts, and documentation for every member: live
RoastBatch 203, script 203, live RoasterSource 7, script
7, total differences 0, exit 0. main() is updated but
never run (it is destructive by design; the header says
so). Note: ~/workspace/ignition-lab/
setup_roastery_artisan_tags.py still holds the old
81-member version; it is a stale duplicate copy, not
the live script, and should be deleted or resynced
separately.

### Item 5: phantom Charge press (round 6 candidate 6, watch item)

It REPEATED once in this round, then did not repeat
again. The round 5 hunt3 phantom (a roast started on
batch 1042 at 01:55:26 UTC with no suite pressing
Charge) did not reproduce in any round 6 live session
(customs runs, HUNT-46 probes, detail shots), but the
closing battery rerun's tier3c failed 'workspace clean
Idle' with the workspace Roasting on batch 1042 after
its reset, with no surviving Charge press row in the
window (the only Charge rows then were polish1's
startup, after tier3c had exited). The leading
mechanism is the HUNT-27 click re-delivery: tier3c
charges through UI dock clicks, and charge() blocks a
replay only while State is 'Roasting', so a replay
arriving after the reset to Idle re-charges. The same
pattern showed again in the round 6 ABC verification:
the walk-home left the roast Roasting (BT fell from
416.7 to 365.3 as the drop cooling ran, then the roast
restarted). Tier3c now probe-resets AFTER its checks
so the lab is left clean for the next suite even when
a phantom lands after the check. In the final battery
rerun (runner4) tier3c PASSED and polish1 PASSED, so
the phantom did not repeat there and the HUNT-53
guard (block a replayed Charge after a reset, e.g. by
remembering the last Charge counter or timestamp) is
still open but not filed as a defect. It stays a watch
item.

### Item 6: validator drill-aware window (round 6 candidate 7)

The pressfault drill's deliberate database stops log
gateway WARN/ERROR rows, which the validator's 15
minute window counted as failures on a rerun. Fix:
verify_roastery_pressfault.py writes its fault window
(first cluster stop to last gateway recovery) to
pressfault-drill.json in the finally block, and
validate_roastery_artisan.py reads it and treats rows
inside the window as drill noise, reported under
drill_window_warnings instead of counted. No staleness
filter is needed: the window is bounded to the drill's
own interval, and the validator's 15 minute window only
overlaps it when a drill just ran. Proof: the validator
rerun after the pressfault drill in the closing battery
(see Verification).

### Item 7: v4 suite cleanup (round 6 candidate 8)

The v4 suite left one Reset press row and a loaded
background for the next suite. Root causes: the loaded
background is deterministic (the v4 ghost section stages
a background and nothing cleared it; the tier suites
clear it through the 'Clear ghost' button), and the
leftover Reset row is a race (drain_pending waits at
most 30 s for lagging group writes and never fails, so
a press row can land after the DELETE). Fix: the suite
now clicks 'Clear ghost' before closing the browser,
through the app's own button the way the tier suites
do, and its cleanup wraps the drain plus deletes in a
retry loop (up to 3 attempts: drain, delete, sleep 5,
re-check batch_events for the batch, break when 0),
with the final 'test batch cleaned' check extended to
require 0 press rows for the batch. Two HUNT-46
consequences found while wiring this in: the Clear
ghost click runs on a fresh page (a fresh session,
first mount), because this desk session has already
mounted /settings twice and a remounted page
intermittently stops writing; and the phase target
restore (set_numeric 270 on the second /settings
mount) is now checked and finished through the tag API
when the UI write does not land, since the app
behavior was already proven by the 300 write on the
first mount. Proof: the v4 suite in the closing battery
(see Verification).

### Item 8: the HUNT-46 onward hunting pass

HUNT-46 (major, platform-blocked): a remounted page
goes dead on this build. After navigating away from a
page and back to it in the same Perspective session,
that page's view instance intermittently stops applying
updates: its controls stop writing (text field commits,
stepper clicks, both bidirectional bindings and
scripted onClick handlers) and its reads freeze at the
first mount's values (strip names, mode pill). Proven
with two live sessions side by side: the never
remounted page followed a rename and a Mode change,
the remounted page kept showing the old name and 'Off'.
A 90 second wait does not revive it, so it is not the
round 2 aged-session stall (which recovers in 60 to
90 seconds); only a fresh session (new tab) restores
writes. A page's FIRST mount in a session always
writes, even after other pages were visited. It is a
2027.2.0-beta1 client defect, not an app bug: there is
no app-side fix for a dead binding, and the suites now
use a fresh page per Settings visit and a reload or
fresh page where a write must land after a remount.
Eric works at IA and can file it. It matters for his
phone-as-remote pattern: Roast to Log or Configure and
back, then his presses silently do nothing until he
opens a fresh tab. Recorded here and in the round 6
report; held for the next beta, not fixed in the app.

HUNT-47 (minor, fixed): the EventsStrip custom cells
ignored their props.visible binding. The round 6 item 1
fix first hid the unnamed cells with a props.visible
expression binding ({CustomEventNName} != ''), then
with a tag binding plus an expression transform; both
forms left the unnamed cells rendering as blank boxes
with dashes (11 cells visible in the DOM, 3 blank).
No binding error appears in the gateway log. The
shipped form hides by class: a props.style.classes
expression binding returns 'roast-cell-hidden' when
the name is blank, and the advanced stylesheet hides
it with display none. The visible bindings were
removed again. Proof: a live probe counts 8 rendered
cells (7 standard plus Fan Boost) with slots 2 to 4
blank, 9 when slot 3 is named, 8 after it is cleared;
verify_r6_customs.py now asserts the rendered cell
count (the name list alone cannot catch a blank cell,
because an empty name label reports invisible).

HUNT-48 (minor, fixed): the themeMode onChange script
logged an error on ThemeMode writes. The log showed
"Error running property change script on
view.custom.themeMode", tracing through
on_theme_mode_change to report_brightness to Periscope's
runJavaScript, failing at PageModel.send when the page
was closing. report_brightness and show_toast both
promise "Never raises" but guarded only with except
Exception, and a Java throwable is not a Python
Exception in Jython (round 4, HUNT-36), so it escaped.
Fix: both use a bare except now, the round 4 isolation
pattern, with an evidence comment. The theme itself was
already applied by apply_theme before the probe, so a
missed re-probe costs nothing. Proof: verify_r6_hunt.py
flips ThemeMode across open and closing sessions and
counts themeMode errors in the log since its start: 0.
The post-battery validator rerun also covers the dark
suite's flips (see Verification).

HUNT-49 (cosmetic, fixed): the roast clock value
clipped 1px at 360px. Measured live: the ClockVal
("00:00", 16px monospace) needs 48px but its tile is
47px, because the HUD row is exactly full at 360px
(pill plus four tiles plus the gear), so the tile is
squeezed 1px below what the value needs and the last
"0" loses a pixel with overflow hidden. The phase 2
note claimed a 59:59 clock fits; it is off by that 1px
(same width in monospace). Fix: at phone widths the
HUD values drop to 15px (advanced stylesheet media
query, the HUNT-44 pattern), which needs about 45px.
Desktop keeps 16px. The phase value is unaffected:
its tile grows to fit ("Development" and "Second
Crack" both measure exact). Proof: verify_r6_hunt.py
measures every HUD value at 360px; the clock reads
scrollWidth 47, clientWidth 47 after the fix.

HUNT-50 (Eric, 2026-11-19, the black bar): "What's
up with the big black bar at the top? Unused space?"
His phone screenshot showed a large empty black band
between the HUD strip and the chart card. Root cause:
the Roast page stacks an alarm banner (38px) and a
prompt strip (56px), 94px total, always rendered, and
both are transparent when they have nothing to show,
so over the dark page background they read as one
black band. The same pair exists on the desktop
LargeRoot and the phone SmallRoot. The prompt strip's
reservation is the Tier 2 deliberate design (playback
prompts fire into a reserved strip so the chart does
not shift mid roast); the alarm banner's 38px is the
same pattern. Fix: a props.style.classes expression
binding on all four banner containers selects
'roast-banner roast-hidden' (display none) when the
banner is empty. The alarm banner hides when no alarm
is active; the prompt strip hides when no prompt is
active AND no background is loaded, so the strip stays
reserved while a background is loaded (a prompt can
only fire then, so no roast layout shifts when one
fires) and collapses otherwise. The hide is by class,
not props.visible: the HUNT-47 lesson is that visible
bindings are not honored for these containers on this
build. Trade-off, stated plainly: an alarm firing
while the banner is hidden shifts the chart down 38px
once; alarms are exceptional, and the permanent 94px
dead band is what Eric flagged. The validator
allowlist gained the four new props.style.classes
bindings (the same class selection pattern as the
Dismiss buttons). Proof: verify_r6_abc2.py, ALL CHECKS
PASSED (no failures): both banners hidden while empty
(2 hidden banner containers at 360px), the prompt
strip reserved while a background is loaded (1 hidden),
collapsed again after the background clears (2 hidden),
and a real banner alarm (BT above 200 F, guard
Charge) fires AlarmActive and shows the banner (1
hidden), then clears when the alarm is removed (2
hidden). The first ABC run used a lowercase 'charge'
guard, which is not a guard name, so its alarm never
armed; that was the test's bug, not the app's, and
the guard is 'Charge' in the rerun. Screenshots:
r6-abc-phone-360-dark-chart.png (chart directly
under the HUD, no band), r6-abc-desktop-dark.png
(the blue suggestion strip correctly visible while
a prompt is active).

HUNT-51 (Eric, 2026-11-19, the axis): "the time on
the bottom should be even increments, like 15 30 45
1:00 1:15 1:30, etc. maybe 30s resolution is fine."
His screenshot showed the auto spacing at 56 second
steps (0:00, 0:56, 1:52, 2:48, 3:44). This supersedes
the round 3 acceptance of width-adaptive auto spacing.
The round 3 evidence stands that axis interval
passthroughs are silently dropped on this beta, so
those were not retried. The proposed blanking
mechanism (emit the category label only at even steps,
blank elsewhere) is PROVEN BROKEN on this build and
was not used: the round 3 probe proved blank category
names merge into a single category and scramble the
line, and reference lines take the category NAME as
their value, so a numeric markLine value draws
nothing. Chosen mechanism, the coarse grid:
core.second_grid now emits one row per
AXIS_GRID_STEP_SEC (30 s, the step Eric named as
fine), so every category name is an even step and any
auto interval stride over them stays even (30, 60, 90,
120 s). One shared grid serves phone and desktop
(they bind the same LiveCurveDS / DetailDS tags), so
no new tags, no binding changes, no hot-path doubling;
ECharts thins per instance (desktop shows more labels,
phone fewer, all even). The 15 s grid was considered
and set aside: it risks 105 s display steps on phone
(auto stride 7 over 15 s categories), which reads
arbitrary; 30 s keeps displayed steps round multiples
of 30. Temps and math are untouched: stored samples
keep true seconds, only the drawn grid quantizes;
samples, overlays, bands and markers land on the
nearest 30 s bucket (at most 15 s off their true
second), which Eric accepted as 30 s resolution.
Markers snap: _ref_items snaps each event second to
the nearest grid step for its value (a reference line
can only draw on a category that exists) and uses the
snapped seconds for the label-gap and line-gap logic;
two events snapping to the same bucket draw one line
and the gap logic drops one label. That is the price
of even labels on a category axis; exact times remain
in the events strip and the BatchDetail tables.
batches.stage_detail and build_compare bucket their
placed keys through core.grid_bucket (integer
arithmetic, round half up, so the Jython library and
the CPython suites agree exactly at half-step
boundaries), and _detail_reference_lines reads the
span back as (rowCount minus 1) times the step.
Suite updates for the grid: tier2 projection
len(future) >= 5 to >= 4 (a 2 minute projection is 4
future 30 s buckets); tier2 smoothing now assigns
each raw sample to its bucket and accepts the live
value when it equals any raw sample in that bucket,
and reads the raw rise by interpolation (a grid row's
second is a bucket edge, not a raw sample second);
tier3b band edges are asserted snapped with a snap30
helper (the 585 s ghost drop boundary draws at the
600 s grid row); v4 'live curve dataset has the roast
samples' len >= 20 to >= 4 (about 5 rows at the 2
minute mark); the axis suite asserts every LiveCurveDS
and DetailDS t_label parses as M:SS with total seconds
a multiple of 30; the detail-span capture asserts 25
rows for the 720 s fixture and 7 rows for the 180 s
floored span, every t_sec a multiple of 30.
Proof: the axis suite's live data assertion reads
['0:00', '0:30', '1:00', '1:30', '2:00', '2:30',
'3:00', '3:30', '4:00', '4:30', '5:00', '5:30',
...] off LiveCurveDS mid roast. Screenshots:
r6-abc-desktop-dark.png (labels 0:00, 1:00, ...,
10:00 at a 10 minute span), r6-abc-phone-360-dark-
chart.png (labels 0:00, 5:00, 10:00 at the same span
on the narrow phone plot, all even). Note for the
report: the displayed step follows span and width
(the grid is 30 s, the auto interval thins it), so on
a full 10 minute span the phone shows 5 minute steps
and the desktop 1 minute steps; at a short span the
phone shows 30 s steps. The 56 s steps are gone.

HUNT-52 (Eric, 2026-11-19, the y axes): "Also, make
the left y-axis and right y-axis, and units. Those
are missing." The chart showed tick numbers on both
sides but no axis titles. The titles already existed
with text ("Bean Temp (deg F)" and "Rate of Rise
(deg F/min)") and the HUNT-31 per-theme color bindings
already existed on every chart; the desktop RoastChart
already showed both. The phone RoastChart, both
DetailCharts and the CompareChart all had both titles
visible false. Fix: visible true on the phone
RoastChart (2 titles), both DetailCharts (4 titles)
and the CompareChart (2 titles); the x-axis title
stays off (HUNT-33 removed it for colliding with the
wrapped legend). Phone title fit: on the 360px phone
plot both titles clip (the left loses "Bea", the
right loses "/min)"), because the horizontal titles
are wider than the room beside the plot. The phone
instances (RoastChart in SmallRoot, DetailChartPhone)
use shorter titles that keep the units: "Bean Temp
(F)" and "RoR (deg F/min)" (RoR is the app's own
abbreviation, used in the HUD and the RoR column).
Desktop and the desktop DetailChart keep the full
"Bean Temp (deg F)" and "Rate of Rise (deg F/min)".
The CompareChart keeps the full titles (it is a
desktop panel). Proof: r6-abc-desktop-dark.png (both
titles fully readable in dark mode), r6-abc-phone-
360-dark-chart.png (both short titles fully readable
at 360px, no clipping, no collisions).

### Lab incident during the round

A runtime restart around 03:36 UTC on 2026-11-20
replaced the VM mid-round and interrupted the v4 smoke
test. Postgres was not installed on the fresh VM, the
gateway was down, and the OS-intent replay's apt-get
update hung on mirror.cogentco.com holding the apt
lock. Recovery: the hung apt was killed by exact PID
807 (an apt-get update, safe to kill; the replay
retries on its own), a timeout-bounded apt-get update
ran (mirror warning only), postgresql-16 installed,
cluster started, role ignition and database db
recreated from .roastery-pgpass, DDL applied, and the
gateway was already RUNNING (started by the
recover-lab.sh run). The seed was already in place
(7 batches, 101 series). The interrupted v4 run had
left 6 press rows (batch 1049 Charge, Dry End, Fan +1,
Heat +1, First Crack Start, plus a Reset on 1042) and
the workspace Roasting on batch 1049 with Fan and Heat
at 6 and the phase target at 300; those were cleaned
through a probe reset plus a psql delete (ring slots
emptied first), and defaults restored (Idle, Fan 5,
Heat 5, BatchNumber 1042, Mode Off, PhaseDryTargetSec
270). Lab left clean at 7 batches, 101 series, 0
events. Trial healthy (about 6943 s at recovery).

### Verification

The closing battery is 21 suites, all green on the final
code. The first pass (runner3, 2026-11-20 08:17 to 08:52
UTC) landed 7 green and 6 failed, then was interrupted
by a VM replacement during the dark suite. The failures
were all diagnosed and fixed, and the rerun (runner4)
plus a short rerun2 cleared them. The table below is the
final state; the results file is
~/workspace/ignition-lab/r6-battery/results-final.txt.

| Suite | Result |
| --- | --- |
| validate_roastery_artisan | VALIDATION PASS |
| validate_chartlab | VALIDATION CHECK REPORT (bogus warning present, no product finding) |
| verify_roastery_ror | 6 PASS, 1 designed SKIP |
| verify_roastery_tier1 | 42/42 |
| verify_roastery_tier2 | 87/87 |
| verify_roastery_tier3a | 40/40 |
| verify_roastery_tier3b | 47/47 |
| verify_roastery_tier3c | 69/69 |
| verify_roastery_v4 | 60/60 |
| verify_roastery_polish1 | 49/49 |
| verify_roastery_polish2 | 65/65 |
| verify_roastery_polish3 | 37/37 |
| verify_r6_customs | 17/17 |
| verify_roastery_dark | 10/10 |
| verify_r6_hunt | 7/7 |
| verify_roastery_pressburst | PASS (11 presses, 11 rows, each action exactly once) |
| verify_roastery_pressfault | 62/62 |
| verify_roastery_deletecascade | 15/15 |
| verify_r5_hunt3 | 7/7, no phantom |
| verify_roastery_axis | 14/14, including even 30 s labels |
| verify_r5_detail_span capture | 9920 25 rows, 9919 7 rows, 1042 7 rows, all labels even |

First pass failures and fixes, all in the repo and
proven by the rerun. Tier2 failed 5 checks, all from
the 30 s grid (HUNT-51): the detail analyzer read the
grid instead of the stored series (fixed in
batches/code.py, _detail_points now reads _series_rows);
the bg deviation compared against a stale bucket (the
suite now recomputes from the live BT tag and StartTime);
the smoothing lag threshold and the RoR identity check
needed grid-aware counts (rising >= 2, most recent
bucket excluded from the RoR identity only). Tier3b
crashed on a suite bug I introduced: the snap30 helper
was inserted inside band_range and swallowed its body,
so band_range always returned None and snap30 raised
NameError; fixed by restoring band_range and making
snap30 a plain return. Tier3c failed only its baseline
(3 press rows left by tier3b's crash); v4 failed 3
checks (the alarm banner check asserted the old 38px
reserved slot that HUNT-50 removed, the RoR threshold
needed >= 2 on the 30 s grid, the phase bar read hit
HUNT-46 on a remounted Roast page); polish1 and
polish2 failed only their baselines on v4's leftover
Reset row. The v4 cleanup now also deletes press rows
with id above the run's starting max (tier1 pattern),
so its startup Reset on 1042 cannot survive.

The rerun (runner4, 09:21 to 11:11 UTC) passed
tier3c, v4, polish1, polish2, dark, r6_hunt,
pressburst, pressfault, deletecascade, hunt3, and
axis, but tier2 and tier3b failed again on recovery
residue, not product bugs: my post-recovery probe
reset wrote a Reset press row after I had verified
7/101/0, so tier2 started at 1 event and ended at 0;
and PhaseFromBg was left True by the interrupted dark
suite and my restore did not cover it, so tier3b's
defaults check failed on that one tag. Both were fixed
by cleaning the lab (no probe reset, tags written
directly) and rerun2 passed tier2 (11:30:47 UTC),
tier3b (11:33:50 UTC). The detail span capture failed
in the rerun because its fixtures (9919, 9920) had been
deleted after the earlier capture and the capture mode
never re-inserted them, so stage_detail returned False
and it read the stale 1042 DetailDS for every batch;
capture now calls fixtures() first (idempotent), and
rerun2 passed (11:34:06 UTC): 9920 25 rows with
CHARGE, DRY END, FC START, SC START, DROP labeled at
even 30 s steps, 9919 and 1042 7 rows each.

Item 6 proof (validator drill-aware window): after a
fresh pressfault drill (11:36 UTC, ALL PRESS FAULT
CHECKS PASSED, 62/62), the validator was rerun
immediately and reported VALIDATION PASS with
roastery_warnings [] and the drill's deliberate
database stop listed under drill_window_warnings
("ERROR SQL Bridge.Roastery.PressEvents: Error during
group execution."), not counted.

Lab incidents during the round: a VM replacement at
about 03:36 UTC interrupted a v4 smoke test (recovered,
Postgres reinstalled, gateway RUNNING, seed intact,
6 leftover press rows cleaned); a second replacement
at about 05:37 UTC interrupted the axis suite
(recovered, DB already 7/101/0, workspace reset); a
third at about 09:16 UTC interrupted the final
battery during the dark suite (recovered, Postgres
reinstalled, DDL applied, gateway RUNNING, reseeded
to 7 batches and 101 series, 2 leftover dark-suite
events cleaned, defaults restored including
PhaseFromBg False). A fourth replacement at about
11:17 UTC landed after the rerun battery completed
(axis rc=0 11:11:07, detail span rc=1 11:11:20);
recovery followed the same pattern and the rerun2
fixes were proven on the fresh lab.

Lab left clean at 7 batches (1042-1048), 101 series,
0 events, defaults restored (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss, PressCaptureMode
Group, PeriscopeAvailable True, background cleared,
PhaseFromBg False), PressEvents RUNNING by functional
proof.

### Round 7 candidates

1. The timezone TIME axis retest on the next Ignition
   beta (the passthrough candidates from round 2); the
   shipped category axis stays regardless.
2. The packaged Docker boot test on Eric's machine or
   homelab (still the one parity era item only he can
   run).
3. HUNT-46: the remounted page freeze on
   2027.2.0-beta1. Retest on the next beta; if it is
   fixed, the suite fresh-page workarounds can stay
   (they are harmless) and the docs note closes.
4. The phantom Charge press watch item (round 5
   candidate 6). It REPEATED once in round 6 (the
   closing battery rerun's tier3c, see Item 5), with
   the HUNT-27 click re-delivery as the leading
   mechanism, but it did NOT repeat in the final
   battery rerun (runner4): tier3c and polish1 both
   passed. The guard itself (block a replayed Charge
   after a reset, e.g. by remembering the last Charge
   counter or timestamp) is still open; file it as
   HUNT-53 only if it reproduces again in a battery.
   Tier3c already probe-resets AFTER its checks so
   the lab is left clean even when a phantom lands
   after the check.
5. The stale duplicate ~/workspace/ignition-lab/
   setup_roastery_artisan_tags.py (old 81-member
   version): RESOLVED in round 7, file deleted, the
   live UDT script is the single source.
6. The Log UI delete of a second fixture in one
   browser session hung for 10-plus minutes in this
   round (9919 deleted fine, 9920 stalled); the
   deletecascade suite covers the delete path, but the
   delete mode's flow in verify_r5_detail_span.py is
   worth a look before the next fixture cleanup.
   RESOLVED in the round 7 repro (2026-11-20, full
   notes in ~/workspace/ignition-lab/
   r7-delete-repro-notes.md): not an app defect and
   not HUNT-46. Both deletes took under a second once
   the page loaded; the stall was the harness
   dismiss() in verify_r5_detail_span.py, which
   watched the 'Personal Use Only' text count. The
   page footer carries a permanent
   secondary-message 'Personal Use Only' div, so the
   count never dropped below 1 after the modal closed
   and every open_page burned about 220 s in failed
   5 s AGREE clicks (227.7 s and 228.1 s in the timed
   repro, 478 s for the whole delete run). The fix
   watches the AGREE and CLOSE button count instead;
   the timed repro after the fix passes in 51 s.
   pg_stat_activity showed no waiting query in 109
   snapshots, and the gateway log showed no errors,
   so no DB lock was involved. No app change, and no
   fresh-context change to delete_fixtures(), since
   the second page was alive in every run.
7. The CompareChart keeps the full y-axis titles
   ("Bean Temp (deg F)", "Rate of Rise (deg F/min)")
   because it is a single instance, not a paired one;
   on a 360px phone the Log compare view likely clips
   them the same way the RoastChart phone instance
   did before HUNT-52's shortening. Either pair it
   (a CompareChartPhone with the short titles) or
   shorten the single instance's titles. RESOLVED
   by HUNT-54 (Item 1): paired CompareChartPhone
   with short titles.
## Polish round 7 (2026-11-20)

### Item 1: HUNT-54, CompareChart paired phone instance
(round 7 candidate 7)

HUNT-54 (minor, fixed): at 360px the single
CompareChart (288px wide) clipped the full y-axis
titles, the same clip the RoastChart phone instance
had before HUNT-52's shortening. Fix: CompareChart
keeps the full titles ("Bean Temp (deg F)", "Rate of
Rise (deg F/min)") with roast-cols-full; a new
sibling CompareChartPhone carries the short titles
("Bean Temp (F)", "RoR (deg F/min)") with
roast-cols-phone, deep copied including the HUNT-31
per-theme color bindings. The stylesheet 900px
switch already hides one instance per viewport.
Builder compare_chart() updated to match plus a
compare_chart_phone() twin; the builder was not run
against the live tree. Proof: the HUNT-55 suite
stages three batches and screenshots the compare at
360px Light with no horizontal overflow
(r7-hunt55-compare-9920.png, see Item 2).

### Item 2: HUNT-55, compare picker cannot stage a third
batch

HUNT-55 (major, fixed): picking C = 1046 showed in
the picker but the caption after Compare still
listed only A and B; changing A to 1042 also left
the caption at A = 1048. Root cause: the CmpA, CmpB,
CmpC dropdowns in Views/BatchesPanel/view.json bound
props.value to view.custom.cmpA/B/C with a property
binding carrying "bidirectional": true only at the
BINDING level. The property binding schema
(knowledge/raw/binding-schemas/binding-property.json)
puts bidirectional inside CONFIG; the binding level
copy is the tag binding shape. IA's own example
(knowledge/examples-ia/simple.json) also puts it in
config. So the binding ran one way (custom to
dropdown): a pick stuck in the dropdown display but
never wrote back to view.custom, so build_compare in
roastery/batches/code.py read cmpC 0 and the caption
listed only A and B, with no exception in the
gateway log during the repro window. A project-wide
scan found these three are the ONLY bindings in the
project with binding-level bidirectional but no
config-level copy; every tag binding with
binding-level true also has config-level true. Fix:
added "bidirectional": true inside each of the three
bindings' config (binding level copy kept, matching
the tag bindings). Proof: new suite
verify_r7_hunt55.py, run 2026-11-20, ALL HUNT-55
CHECKS PASSED. The caption follows every pick:
C = 1046 stages (caption lists A = 1048, B = 1047,
C = 1046), A = 1042 stages, A = 9920 with B = 1048
C = 1046 lists all three, and the same three stage
at 360px Light with no horizontal overflow. Fixtures
9919/9920 were inserted first and deleted through
the Log UI afterwards; the lab was restored to (7,
101, 0) Idle, theme System.

### Item 3: the dismiss() harness loop in the lab suites
(lead 2)

The looping dismiss() form fixed in
verify_r5_detail_span.py (round 7, commit 4682e5f)
existed in 14 lab-only suites and ground the same
way: the page footer carries a permanent
secondary-message "Personal Use Only" div, so
watching the text count never reaches 0 and every
open_page burned about 220 s in failed 5 s AGREE
clicks (40 iterations). The fixed form watches the
AGREE and CLOSE button count instead, keeps the
40-iteration poll, and returns True when the button
count hits 0. Applied to verify_r5_hunt.py,
verify_r6_abc.py, verify_r6_abc2.py,
verify_roastery_axis.py (kept its docstring note
about the modal appearing well after page load),
verify_roastery_dark.py, verify_r6_phone_chart.py,
verify_r5_hunt2.py, verify_roastery_r4hunt_a.py
through _e.py (these use 30 iterations, about 165 s
grind; iteration counts preserved),
scratch_walk_home.py (dismiss_hard, 40 iterations)
and scratch_walk_home2.py (inline 30-iteration
loop). After the edits no looping text-count dismiss
remains in the lab; all 14 files py-compile. The
tracked scripts under roastery/scripts/ were not
touched (single-attempt form, unaffected). Proof:
the smoke batch over all 12 touched suites is
green on 2026-11-20: verify_r5_hunt.py and
verify_r5_hunt2.py pass standalone (see Item 4);
verify_r6_abc.py, verify_r6_abc2.py,
verify_roastery_axis.py, verify_roastery_dark.py
and verify_r6_phone_chart.py pass in the smoke
batch; verify_roastery_r4hunt_a.py through _e.py
pass after the further suite fixes in Item 4
(the batch ran in passes as each fix landed:
abc2, axis, dark, phone_chart green in run 4;
A green standalone, then B, C, D, E green in
run 7). The open_page grind is gone: r6_abc
finished in about 200 s (was 675 s) and the
delete repro that motivated the fix runs in 51 s
(was 478 s).

### Item 4: pre-existing suite bugs found by the smoke
runs (lead 2)

verify_r5_hunt.py Part B had 5 pre-existing suite
bugs, all unrelated to the dismiss change (proven
by a live dock probe: at +8 s into a roast with no
stamps, Drop buttons: 0, Dry End buttons: 2; the
phase-aware dock_actions() offers Drop only after
FC Start is stamped). (1) Drop was clicked with no
stamps, where no Drop button exists, a 20 s timeout.
(2) The post-Drop wait list omitted Dropped (drop()
sets State Dropped, not Cooling/Complete/Idle).
(3) The button-height cap was 48 vs designed 49 px
dock buttons and 54 px steppers (v4 52 px targets
plus borders); a wrapped two-line button measured
56 px in HUNT-43, so the cap is now 54. (4)
delete_batch_via_ui(max(batch_number)) would have
deleted seeded batch 1048, since Finish does not
save and Save Batch would refuse batch 1042 as
already logged. (5) The "finish returns to Idle"
check was wrong because finish() sets State
Complete, not Idle. Fixed Part B: stamp Dry End,
wait for DryEndElapsedSec >= 0, stamp FC Start, wait
for FirstCrackStartElapsedSec >= 0, click Drop, wait
for Dropped, click Finish, wait for Complete, click
Reset ("Reset / New Roast", offered only at
Complete), wait for Idle, then DELETE FROM
batch_events via psql and assert the (7, 101, 0)
baseline. Re-ran standalone 2026-11-20: ALL checks
PASS, HUNT FAILURES: none, lab 7 101 0 Idle.
verify_r5_hunt2.py failed with TargetClosedError
opening a second context in the same single-process
browser, a KNOWN documented round 5 limitation
(hunt2 was abandoned mid run for this; the pattern
is one fresh browser per session, never two contexts
in one browser). Fixed by giving the desktop part a
fresh browser (the file's own docstring already says
"One fresh browser per part"). Re-ran standalone
2026-11-20: ALL checks PASS, HUNT FAILURES: none,
lab 7 101 0 Idle. New Roast measures 44 px tall,
97 px wide at both 360 px and desktop. The "custom
button missing: Drum Note" print in the failed run
was a transient race (the repeater re-render after
the Fan Boost click); the probe and the passing
rerun both show Drum Note present.

verify_r6_abc.py had the same phase-order bug in
its walk home: the loop clicked FC Start first, but
the phase-aware dock offers Dry End first while
Roasting with no stamps, so every step burned a
15 s click timeout plus a 90 s state wait (about
8 minutes, ending still Roasting) and the suite
failed only on "lab back to Idle". Fixed by
stamping in phase order (Dry End, FC Start, FC End,
SC Start, SC End, Drop, Cool, Finish, Reset),
waiting for each event tag or state; a click
timeout now fails loudly instead of grinding
silently. Re-ran standalone 2026-11-20 after a VM
replacement and lab recovery (see the Lab incident
note): exit 0, 16/16 checks, FAILURES: none, lab
7 101 0 Idle, in about 200 s (was 675 s).

verify_roastery_r4hunt_a.py had two pre-existing
suite bugs. (1) "phone dock closes cleanly" failed
because the closed AppSettings dock stays in the
DOM translated off the viewport (x = 420, w = 360
on a 360 px screen); the check expected the element
gone or zero width. A closed dock is clean when it
is fully outside the viewport, so the check now
accepts None, zero width, or a rect outside the
viewport. The dock is off screen and the roast
keeps running, proven by the follow-up checks.
(2) The mobile detail open passed the absolute
dp.url to open_page, which prepends BASE, so the
request was malformed and the gateway answered
400 /badURI (screenshot r4hunt-detail-close-360-
dark.png shows the 400 page); the gear click then
timed out after 30 s because the page never
loaded. Fixed by passing the path part of dp.url.
Re-ran standalone 2026-11-20: exit 0, FAILS: [],
PART A DONE.

verify_roastery_r4hunt_b.py had three pre-existing
suite bugs. (1) The toast checks waited for
'Import failed', but the Settings background route
toasts 'Background failed: ...' (artisan.
stage_background_upload; 'Import failed' is the
Log page import route's message), so the 20 s wait
could never match even though the toast fired (the
page note "Background failed: Not an Artisan .alog
file: the first character must be an opening
brace." is visible in r4hunt-toast-light-360.png).
Fixed the needle in both the Light and Dark
checks. (2) The desktop all-columns toggle block
clicked an 'All columns' button that does not
exist on desktop: a live probe counts exactly one
such button on /log at 1360 px and it is not
visible (the toggle lives in the phone instance
only; desktop already shows every column). The
block is removed. (3) After each bad .alog upload
the FileUpload status stays open as a small
viewport modal over the page; the in-modal arrow
does not close it, and its fullViewOverlay
intercepts pointer events, so the gear and Dark
clicks timed out after 30 s. A live probe shows a
tap outside the modal closes it, after which the
gear works and the Dark button is found. The suite
now taps outside the modal (only when the overlay
is present) after each upload. (4) The error toast
itself sits top center over the gear and intercepts
the click: wait_toast returns the moment the text
matches, so the gear click lands while the toast is
still up. The toast's autoClose is 5 s but its
timer pauses while the pointer hovers it, so a
toast the mouse rests on never leaves on its own
(the gear click kept hitting the error toast after
a 10 s wait). The suite now parks the pointer off
the toast after the modal tap and wait_toast_gone
clicks the toast itself (closeOnClick) if it is
still there after 3 s. A live probe confirms the
lifecycle: the toast is present 2 to 6 s after the
upload and gone by 8 s when the pointer is clear
of it. Re-ran standalone 2026-11-20: exit 0,
FAILS: [], lab restored to seeded baseline
(7, 101, 0). The Dark toast also fired
("Background failed: name 'true' is not defined",
the bogus JSON's boolean failing in the parser,
as expected for a non-alog file). The fixture
delete flow passed, including the HUNT-35 press
row cascade.

verify_roastery_r4hunt_c.py failed at startup with
FileNotFoundError for /tmp/r4hunt_fixture_9919.json:
the snapshot the fixture restore reads lived only
in /tmp, and the VM replacement wiped it. No suite
writes the file (only C reads it); it was a one-off
round 4 snapshot. Fix: part A was re-run to
re-create fixture 9919, a new snapshot script
(snapshot_r4hunt_fixture.py) dumped the batch and
its 42 series rows from the DB into the lab dir
(persistent) plus /tmp, and C now reads the lab
dir copy first with /tmp as fallback. The smoke
run 7 result: B exit 0 (FAILS: []), C exit 0
(FAILS: [], fixture restored from the new
snapshot), D exit 0, E exit 0, lab back to
(7, 101, 0).

### Item 5: cleanup_workspace.py Reset click (lead 3)

The script's Reset click timed out after its Charge
click started a roast. Root cause, proven
statically: dock_actions() in
roastery/core/code.py offers Reset only at Complete
(alongside Charge); while Roasting it offers only
phase events plus customs, and at Idle only Charge.
A grep of all views found the only static "Reset"
button text in the project is SettingsTargets
"Reset to Four Points" (a target-profile reset, not
the batch reset); the batch Reset is rendered by the
dock repeater from dock_actions(). So the old
script's get_by_role('button', name='Reset') after
Charge could never resolve, timing out after 30 s
and leaving Roasting with 1 Charge press row.
Fix: the script was rewritten to drive the roast
through the offered buttons, Charge, Dry End,
FC Start, Drop, Finish, Reset, waiting for each
state via the tag API, tolerating a leftover roast
in any state (Dry End and FC Start clicked only if
present; Drop only if still Roasting; Finish only
if Dropped or Cooling); dismiss upgraded to the
fixed button-count form; press rows cleared
afterwards with DELETE FROM batch_events; scalar
restore and verification reads kept, plus a
batch_events count print. The launch also uses
R5.launch (no-zygote, single-process) since a bare
chromium.launch traps on the zygote in this VM.
Proof: run live 2026-11-20, exit 0 in about 18 s:
Charge, Dry End, FC Start, Drop, Finish, Reset
all landed, State Idle, Fan 5, Heat 5, BatchNumber
1042, ActiveSource Simulated, Mode Off, background
cleared, BackgroundDS, EventMarksDS and LiveCurveDS
all 0 rows, batch_events 0, lab (7, 101, 0).

### Item 6: compare plot empty for seeded stub batches
(lead 4, seed-data artifact, no fix)

Via a gateway snippet mirroring build_compare
exactly with _compare_points, compute_ror_series,
grid_bucket, second_grid: batches 1048/1047/1046
have 10 points each, all bucketed to t = 0, maxSec
0, 1 grid row each, so no line can draw. Batch
1042 has 21 points, maxSec 30, 2 rows [0, 30].
Fixture 9920 (720 s) has 49 points, 25 grid rows,
t_secs 0 to 720 step 30. Element screenshots viewed:
r7-hunt55-compare-9920.png shows the A BT solid
orange curve (392F dip to about 370F, climb to 415F
across 0:00 to 12:00) and the A RoR dashed curve;
r7-hunt55-compare-stubs.png (A = 1042, B = 1047,
C = 1046) shows only a flat two-point segment for A
at about 250F BT and about 22 F/min RoR across the
0:00 to 0:30 axis. So a real full-length batch plots
correctly. The HUNT-54 note that the plot was empty
holds only when both staged stubs span 9 s (single
grid row each). Lesson: the chromatic pixel ink
metric is axis-scale blind for this chart (stub-only
ink 5196 vs 9920 ink 5173 in the first run, because
the axis auto-scales so six lines span the full
width either way). The grid row count from the
library functions plus element screenshots is the
discriminator. The suite keeps ink as an
informational print only.

### Item 7: the fresh hunting pass (lead 5)

New suite verify_r7_freshhunt.py walks Roast (/),
Log (/log), BatchDetail (/log/detail, batch 1042
staged) and Settings (/settings) at 1360px and
360px, light and dark, measuring page-level
horizontal overflow and clipped leaf text, and
screenshotting every combo, plus behavioral
probes (Settings write/read-back, background
ghost, AppSettings dock at 360px). Run
2026-11-20: exit 0, PASSES: 41, FAILURES: none,
lab (7, 101, 0). No horizontal overflow anywhere;
no clipped app text anywhere once the Perspective
footer is excluded (see below). Screenshots:
r7-fresh-roast-1360-light/dark.png,
r7-fresh-log-1360-light/dark.png,
r7-fresh-detail-1360-light/dark.png,
r7-fresh-settings-1360-light/dark.png (plus
full-page variants), the same eight at 360px,
r7-fresh-roast-ghost-1360-light.png,
r7-fresh-appsettings-360-light.png,
r7-fresh-settings-360-bottom.png and
r7-fresh-settings-360-mid2.png.

HUNT-53 (major, filed, not fixed in this round):
the phantom press, reproduced. A ghost overlay
probe pressed Charge, Dry End, FC Start, Drop,
Finish and Reset at 19:13:48 to 19:14:33
(press counters 4608 to 4613); its cleanup
deleted the rows and verified (7, 101, 0). A VM
replacement followed at about 19:15; recovery
created a FRESH database and reseeded batches and
series (events 0). The gateway came up at
19:19:54, and at 19:19:59.842 to 19:19:59.860 the
same six presses reappeared in the new database
as six rows in an 18 ms burst, with identical
actions, t_offsets, bean temps and counters
4608 to 4613. No browser was running (the probe
had closed its browser before the replacement),
and the ActionCounter tag still read 4613 with
LastAction Reset. Root cause: the press-ring
reconciler, roastery.core.reconcile_press_pending.
Every press slots its context into the 16-slot
PressSlots ring (slots are NEVER cleared), and
reconcile checks each slot against the
(batch_number, press_counter) row key, inserting
any press the group missed. The check is
DB-relative: a fresh database makes every slot
look unwritten. The presses were 326 to 371 s
old at the replay, inside the 600 s horizon and
past the 3 s grace, so the BeanTempF change tail
reconciled them on gateway start. This also
explains the round 6 tier3c single Charge phantom
(same mechanism, only the Charge press inside
the horizon then) and the round 7 candidate 4
note. In normal operation with an intact database
a plain gateway restart does NOT duplicate (the
rows are already there), so the hazard is
specifically database loss plus restart, and any
delete of press rows inside the 10 minute horizon
(the HUNT-35 cascade, a cleanup DELETE) can be
resurrected the same way. That also explains two
earlier mysteries in this round: the 16
unexplained press rows after the first killed
smoke batch (a cleanup DELETE removed the
roast's rows while the ring still held them) and
the 15 rows that reappeared between two cleanups
after the r4hunt_a crash (14 suite presses
re-inserted plus the probe reset's own row). Fix proposal, for
Eric's direction: the delete and cleanup paths
must clear the ring slots for the affected batch
and counters, and the recovery procedure must
clear PressSlots on a fresh database (the lab
step this round: the six rows were deleted and
all 16 slots cleared, stable at 0 events after
60 s). The app-side fix is NOT implemented in
this round: the press path is safety-critical
(exactly-once) and the change needs a battery.
The lab procedure now includes the slot clear
after every recovery (see the second Lab incident
note).

Checked and dismissed, no HUNT item:
- Detail chart x labels 0:00, 1:30, 3:00 for the
19 s batch 1042: deliberate. DETAIL_SHORT_FLOOR_
SEC = 180 (HUNT-37): short batches pad to a
3:00 axis. The DetailDS rows confirm it (t_sec
0 to 180, values only at 0 and 30).
- Ghost empty while Idle: by design. BackgroundDS
is 0 rows until a roast timeline exists; during
a roast it populates (5 rows at 40 s) and the
ghost draws (gray Background and Background RoR
lines, GHOST BT 232.5, DEV +41.6 in the analyzer,
r7-fresh-roast-ghost-live.png).
- One clipped leaf on every page in the first
fresh-hunt run: the Perspective client footer
DIV.secondary-message carrying the page URL
(307 px in a 270 px box, overflow hidden). It is
platform chrome below the fold, not app content;
the suite now excludes it.
- "No Connection to Gateway" in the page body
text: DIV.connection-message parked off-screen
at y = -28 while connected; always in the DOM.
- "Upload Successful!" modal for a failed .alog:
the FileUpload component's receipt status (the
file arrived); the app surfaces the failure
inline ("Background failed: ...") and as an
error toast. Platform wording, not an app
defect.
- "Background .alog" label wraps to two lines at
360px: a narrow label cell, cosmetic.
- Log table geometry sw 0 cw 0 in the r4hunt_b
probe: the selector grabs the hidden desktop
table instance; the visible phone table renders
fine.
- Artisan study: the RoR pipeline
(compute_ror_series: delta span, curve filter,
delta filter, spike smoothing, polyfit, optimal
smoothing), the AUC trapezoid (Artisan calcAUC
shape, begin at TP/Charge/Dry End/FC Start),
the turning point detector (Artisan findTPint:
minimum between charge and first crack) and the
phase RoR (Artisan RoR(): DRY from the turning
point or greens temp) were all read against
~/workspace/artisan-src and match Artisan 5.0.0.
The Artisan feature mapping table was stale on
six rows (turning point and comparator marked
Excluded after they were built, the v3 RoR EMA
described as current, old simulator numbers,
.alog import/export missing, alarms described
as view expressions); corrected in place in
this round. Round 8 candidate: Artisan's
comparator alignment (alignEvent: CHARGE, DRY,
FCs, FCe, SCs, SCe, DROP) for build_compare,
which aligns on charge only today.
- The Settings page scrolls an inner container
(.psc-roast-content, scrollHeight 11129 at
360px); window.scrollTo is a no-op there, which
is why the r4hunt_b mid/low Settings shots
repeat the top. The fresh-hunt probe scrolled
the container and captured the lower sections
(Alarms editor, Custom Events, Background
staging) clean at 360px.

### Lab incident during the round

A VM replacement around 17:15 UTC on 2026-11-20
killed the gateway mid smoke batch (the r6_abc
rerun failed with connection refused). Recovery:
uptime 1 minute, Postgres not installed, workspace
intact. The OS-intent replay's apt-get update hung
on mirror.cogentco.com (PID 1099, zero CPU in
3.5 minutes, curl to the mirror timed out), so it
was killed by exact PID, per the round 6 pattern;
the replay retries on its own. A timeout-bounded
apt-get update then crawled on the same mirror, so
the sources were pointed at azure.archive.ubuntu.
com only (fast: InRelease in 0.9 s, Packages files
in about 1.3 s each) and the update completed in
9 s; postgresql-16 installed cleanly after, and
the sources file was restored to the original
two-mirror form. recover-lab.sh then ran clean:
cluster online, role and database created, DDL
applied, gateway RUNNING, and reseed_from_roastlog
restored 7 batches, 101 series, 0 events. All tag
defaults verified after recovery. The round 6
recovery had the same apt lock contention; the
azure-only update is the faster path if the mirror
hangs again.

A second VM replacement around 19:15 UTC killed
the gateway during the fresh-hunt scroll probe.
Recovery repeated the same pattern: the replay
apt-get update hung again (PID 1177, zero CPU in
2:43, no package lists), killed by exact PID,
azure-only update in 9 s, postgresql-16 installed,
sources restored, recover-lab.sh clean, gateway
RUNNING, reseed restored 7 batches and 101
series. The recovery then surfaced HUNT-53 (see
Item 7): six phantom press rows from the
pre-replacement ghost probe reappeared in the
fresh database at 19:19:59, and were deleted
with all 16 PressSlots cleared; the lab is
stable at 0 events after. Lab procedure addition:
after every recovery and reseed, clear the
PressSlots tags and delete any batch_events rows,
or the reconciler resurrects the last presses.

A third VM replacement at about 21:15 UTC killed the
gateway mid battery, during verify_roastery_r4hunt_b.py
(the r4hunt_a result was already recorded). Recovery
repeated the pattern with one difference: the replay
apt-get update was NOT killed this time. It ran 9-plus
minutes with near-zero CPU on the main process, but its
http and store children were still accumulating CPU, so
it was slow, not hung, and it finished on its own; the
lists landed (68 ubuntu lists) and the replay installed
postgresql-16 as recorded intent. recover-lab.sh then
ran clean: cluster online, DDL applied (tables already
existed), gateway RUNNING, and the database came back
at the reseeded baseline, 7 batches, 101 series, 0
events, with no reseed step needed. Fixture 9919 and
every press row from part A and the first part B run
were gone from the database, while the gateway
PressSlots still held those 16 presses (counters
4818-4833); the HUNT-53 guard cleared the slots and
verified 0 events stable after a 60 s idle wait before
the battery resumed. The resumed battery reran part B,
which failed on the missing fixture (see Verification);
the A to B rerun closed it. The runner resume-safe
results file skipped the 29 DONE suites and reran only
the remainder.


### Verification

Closing battery, run 2026-11-20, 19:48 to 21:45 UTC,
runner run_r7_battery.sh (r7-battery/results.txt),
interrupted once by a VM replacement at about 21:15 UTC
during verify_roastery_r4hunt_b.py and resumed from the
same results file at 21:34 (the runner skips DONE
suites). Every suite below passed on the final code;
the two first-pass failures are recorded after the
table with their fixes and reruns.

- validate_roastery_artisan.py: VALIDATION PASS.
- validate_chartlab.py: VALIDATION CHECK REPORT, no
  chartlab warnings, 0 bogus control warnings.
- verify_roastery_ror.py: 6 PASS, 1 designed SKIP on
  rerun (first pass failed the live check, see below).
- verify_roastery_tier1.py: 42/42, ALL TIER 1 CHECKS
  PASSED.
- verify_roastery_tier2.py: 87/87, ALL TIER 2 CHECKS
  PASSED.
- verify_roastery_tier3a.py: 40/40, ALL TIER 3A CHECKS
  PASSED.
- verify_roastery_tier3b.py: 47/47, ALL TIER 3B CHECKS
  PASSED.
- verify_roastery_tier3c.py: 69/69, ALL TIER 3C CHECKS
  PASSED.
- verify_roastery_v4.py: 60/60, ALL CHECKS PASSED.
- verify_roastery_polish1.py: 49/49, ALL POLISH ROUND 1
  CHECKS PASSED.
- verify_roastery_polish2.py: 65/65, ALL POLISH2 CHECKS
  PASSED.
- verify_roastery_polish3.py: 37/37.
- verify_r6_customs.py: 17/17, ALL R6 CUSTOMS CHECKS
  PASSED.
- verify_roastery_dark.py: 10/10, ALL DARK MODE CHECKS
  PASSED.
- verify_r6_hunt.py: 7/7, ALL R6 HUNT CHECKS PASSED.
- verify_roastery_pressburst.py: ALL PRESS BURST CHECKS
  PASSED, 11 presses, 11 rows, each exactly once (one
  pre-existing baseline row counted, not an extra).
- verify_roastery_pressfault.py: 62/62, ALL PRESS FAULT
  CHECKS PASSED.
- verify_roastery_deletecascade.py: 15/15, ALL DELETE
  CASCADE CHECKS PASSED.
- verify_r5_hunt3.py: 7/7, HUNT FAILURES: none.
- verify_roastery_axis.py: 14/14, ALL AXIS CHECKS
  PASSED.
- verify_r5_detail_span.py capture: 9920 25 rows, 9919
  7 rows, 1042 7 rows, every t label an even 30 s step;
  fixtures removed afterwards (PressSlots cleared first).
- verify_r7_hunt54.py: 33/33, ALL HUNT-54 CHECKS PASSED.
- verify_r7_hunt55.py: 17 PASS lines, ALL HUNT-55
  CHECKS PASSED (three batches stage and compare at
  desktop and 360px).
- verify_r7_freshhunt.py: PASSES: 41, FAILURES: none.
- verify_r5_hunt.py: HUNT FAILURES: none.
- verify_r5_hunt2.py: HUNT FAILURES: none.
- verify_r6_abc.py: 16/16, FAILURES: none.
- verify_r6_abc2.py: 15 PASS lines, FAILURES: none.
- verify_roastery_r4hunt_a.py: FAILS: [] (rerun green
  after the VM replacement, see below).
- verify_roastery_r4hunt_b.py: FAILS: [] on rerun (first
  resumed run failed, see below).
- verify_roastery_r4hunt_c.py: FAILS: [], lab (7, 101, 0).
- verify_roastery_r4hunt_d.py: PART D DONE, no failures.
- verify_roastery_r4hunt_e.py: PART E DONE, final counts
  (7, 101, 0), SlotsCleared True.
- cleanup_workspace.py: exit 0, lab (7, 101, 0).
- r7_udt_diff.py: UDT DIFF PASS, 0 differences
  (RoastBatch 203, RoasterSource 7).

First-pass failure 1, verify_roastery_ror.py live check
(suite bug, not an app bug). First battery pass 19:51:
the 40 s live window read temp 343.3 to 350.1, slope
10.71 F/min (in the 3 to 30 assert band), but the median
live RateOfRiseF was 3.40, outside the 3.0 tolerance.
Diagnosis: the window started within 1.3 F of the
simulator program minimum (342 F at program 785 s) and
rose into the reheat segment, so it straddled the
cooling-reheat corner where the true slope flips from
about -40 to about +13 F/min. The live RoR is a 20 s
delta-span derivative with decay smoothing over a 300 s
buffer, so for about a span after the corner it still
sees the fall and legitimately reads low; the median
over the whole window mixes pre- and post-corner
values. The six offline checks all passed, and the live
tag runs the same compute_ror_series code path, so the
math is not in question. The suite guard only tested
the endpoint slope band, not steadiness, despite its
docstring saying the check only asserts on a steady
ramp. Fix (suite only, mirrored to
roastery/scripts/verify_roastery_ror.py): the check now
compares the tail RoR (median of the last 5 samples)
against the tail slope (the last 20 s of temps, the same
span the RoR sees), and asserts only when that tail
slope is in band; a corner inside the tail puts the tail
slope out of band and the check skips. Rerun 21:55:
exit 0, ALL ROR CHECKS PASSED, 6 PASS and 1 designed
SKIP (the window was flat, temp 298.6 to 298.6, slope
0.00).

First-pass failure 2, verify_roastery_r4hunt_b.py in the
resumed battery (lab casualty, not an app or suite bug).
The resumed run 21:42 failed "fixture row selectable
for delete": no row for batch 9919 existed in the Log
table, so the row click found nothing and the Delete
button stayed disabled (the click then timed out after
25 s). Cause: the VM replacement at about 21:15
restored the database to the reseeded 7/101/0 baseline,
wiping fixture 9919 (created by part A at 21:09) and
every press row from part A and the first part B run,
while the gateway PressSlots still held those presses
(16 slots, counters 4818-4833). The battery HUNT-53
guard cleared the slots and verified 0 events stable
after a 60 s idle wait before resuming. Fix: rerun the
A to B chain. Part A rerun 21:57: exit 0, FAILS: [],
fixture 9919 saved with 42 series rows. Part B rerun
22:06: exit 0, FAILS: [], fixture row selectable,
fixture batch deleted through the app, series and press
rows cascaded, lab restored to (7, 101, 0). Parts C, D
and E needed no rerun (C restores from the lab-dir
snapshot, which survived; D and E passed in the resumed
battery).

HUNT-53 is filed with the reproduction evidence and
the root cause (Item 7); its app-side fix is open, not
implemented in this round. The battery itself did not
trip over it: the guard ran before the battery, after
the recovery, and before the A to B rerun, and 0 events
stayed stable after every 60 s idle wait.

Lab left clean at 7 batches (1042-1048), 101 series,
0 events, defaults restored (Fan 5, Heat 5, BatchNumber
1042, ActiveSource Simulated, Mode Off, ThemeMode
System, DispAxisFormat m:ss, PressCaptureMode Group,
PeriscopeAvailable True, background cleared,
PhaseFromBg False), PressSlots empty, and 0 events
still after a 60 s idle wait. The PressEvents group is
RUNNING by functional proof (every suite press landed
exactly once in the audits).

## Polish round 8: Artisan comparator alignment (2026-11-20)

### Item 1: HUNT-56, compare curves align on a chosen event

HUNT-56 (minor, fixed): build_compare aligned compare
curves on charge only, so two roasts with different
phase timings overlaid with their first cracks minutes
apart and no way to line them up. Artisan 5.0.0 aligns
on a chosen event instead: comparator.py realign anchors
the top profile to its CHARGE and shifts every other
profile by delta = eventTime minus refTime for the
chosen event (align names CHARGE, TP, DRY, FCs, FCe,
SCs, SCe, DROP), a profile missing the event falls back
to its charge, and a vertical align line draws at
refTime; canvas.py timealign does the same for the
background, trying DROP, then SCe, SCs, FCe, FCs, DRY,
CHARGE when alignEvent is ALL.

Fix, in roastery/batches/code.py: compare_dataset and
the pure align_compare_slots build the overlay for the
event named by the CompareAlignEvent tag (CHARGE by
default). The reference is slot A, the first chosen
batch; every other slot shifts by its event minus the
reference event, snapped to the 30 s library grid
(HUNT-51), so an aligned event lands within 15 s of the
reference, the same quantization the grid already
applies to every sample. A slot missing the event
aligns its charge to the reference event, Artisan's
fallback. Aligned seconds can go negative (aligning on
DROP pulls every charge left of zero); the category
grid starts at 0, so the whole overlay translates
right by a grid multiple and the reference line moves
with it. Artisan instead shows negative times; the
translate keeps every sample visible and the caption
names the event. The seven stamped events are offered
(no TP: the turning point is derived, not a stamped
event in the batch document; no ALL: the comparator
needs one explicit event). The caption names each slot
plus the alignment and any fallback ("B has no SCs,
charge aligned"). One ALIGN reference line (core.
_ref_items, so it snaps to the grid like every other
reference line) draws at the snapped reference second
on the bean series of both CompareChart instances,
bound to view.custom.compareRefLines, which
build_compare writes.

The choice lives on one tag-backed setting,
CurrentBatch/CompareAlignEvent (String, default
'charge'; member added to setup_roastery_artisan_tags.
py, the UDT record the round 7 UDT diff verifies:
203 members, still alphabetical), exposed in both
places it belongs: a "Compare alignment" dropdown in
Settings Display (next to the time axis format, same
tag binding shape as DispAxisFormat) and an "Align
on" dropdown on the Log compare row (before the
Compare button). Both bind the one tag
bidirectionally, so they always agree; changing
either and pressing Compare restages the overlay.
build_roastery_v4.py carries the same row, chart
binding and Display row so a future regeneration
keeps the feature. The setup_roastery_v4_tags.py
script was NOT updated: it is a stale fork of the
UDT list and the live UDT matches
setup_roastery_artisan_tags.py, not it (round 7 UDT
diff: 0 differences). The press path is untouched
(HUNT-53 app fix stays out of scope).

Proof: new suite verify_r8_align.py (repo
roastery/scripts, mirrored to the lab), run
2026-11-21, ALL HUNT-56 CHECKS PASSED, 37 PASS
lines, exit 0. Gateway math through the same
library functions build_compare calls, on two
full-length fixtures (9920, 720 s, FCs 540, DROP
720; new 9921, 660 s, FCs 420, DROP 660): aligning
on FCs shifts B by -120 s with reference 540 and a
27-row grid 0..780, B's charge landing at 120 and
both curves meeting at bucket 540 (A 401.5 F, B
395.4 F); aligning on DROP shifts B by -60 s with
reference 720 and a 25-row grid 0..720, both drops
landing at 720 (A 415.0 F, B 418.0 F); CHARGE
shifts nothing with reference 0. Every label is an
even 30 s step, and the single ALIGN reference line
reads 9:00 / ALIGN FCs and 12:00 / ALIGN DROP. A
synthetic two-slot case proves the missing-event
fallback (B with no SCs shifts -660, its charge
landing on the reference SCs at 660), and the live
seeded stub 1048 (events: only charge 0 and drop 9)
falls back the same way in the caption. Live UI at
desktop Light: the compare row Align dropdown reads
FCs from the tag, Compare stages A=9920 B=9921 with
the caption naming the alignment (chart ink 8269),
picking DROP in the row writes the tag and
restages; the Settings Display dropdown reads DROP
and picking CHARGE writes the tag back. At 360px
Light the same two batches stage on DROP with no
horizontal overflow (360/360/360). Screenshots:
r8-align-fcs-desktop.png (ALIGN FCs line at 9:00,
B curve starting at 2:00), r8-align-drop-360.png
(ALIGN DROP line at 12:00, short titles, no
overlap), r8-align-drop-desktop.png,
r8-align-settings.png. Run 1 died on a harness
flake, not the app: the single-process Chromium
closed between the desktop and Settings phases
(TargetClosedError on new_page); the suite's
finally still deleted all three fixtures and
restored the lab, and the suite now launches a
fresh browser per phase. The lab UDT diff passes
at the new counts (RoastBatch 204, RoasterSource
7, 0 differences) and validate_roastery_artisan.py
passes. Lab left clean at 7 batches (1042-1048),
101 series, 0 events, defaults restored (Fan 5,
Heat 5, BatchNumber 1042, ActiveSource Simulated,
Mode Off, ThemeMode System, DispAxisFormat m:ss,
PressCaptureMode Group, PeriscopeAvailable True,
background cleared, PhaseFromBg False),
CompareAlignEvent CHARGE, PressSlots empty.

### Item 2: HUNT-58, r4hunt A-to-B chain self-heals after a VM replacement

HUNT-58 (harness, fixed): in round 7 the battery's A-to-B
chain broke when a VM replacement wiped fixture 9919
between parts A and B (part A creates fixture 9919 with
42 series rows; part B deletes it through the Log UI).
The resumed battery had to rerun A then B by hand
(round 7 first-pass failure 2). Root cause: only part C
restored the fixture from a snapshot; A and B assumed
it was there.

Fix, suite and harness only, no app behavior change:
new shared helper roastery/scripts/r4hunt_fixture.py
(lab ~/workspace/ignition-lab/r4hunt_fixture.py), used
by parts A, B and C. ensure_fixture() verifies the
precondition at part start (fixture 9919 present with
the snapshot's full series count) and re-creates it from
the persistent lab-dir snapshot when it is missing or
partial; the snapshot lives in the lab dir with the
helper's own directory and /tmp as fallbacks, never
/tmp alone. Part A calls ensure_clean_baseline() at
start (a stale fixture or leftover press rows from a
partial A run are removed, so the live roast can
re-create the fixture instead of refusing the duplicate
batch number) and snapshot_fixture() right after the
save, so the snapshot is fresh after every A run
instead of a one-off file; snapshot_r4hunt_fixture.py
is now a thin wrapper over the same function. Part C's
local restore is replaced by the shared helper (a
partial fixture is replaced wholesale, not just a
missing batch). Every cleanup path runs the HUNT-53
guard first: P.drain_pending() settles the press ring
and clears all 16 PressSlots before any batch_events
rows are deleted, so the reconciler cannot resurrect
them. Part C also drains before its final app delete
and re-reads the counts after a 10 s stability wait.
Parts D and E were checked and need nothing: neither
references fixture 9919 (D probes the upload modal and
toasts with files it writes itself; E proves
PressEvents with its own charge/reset probe).
run_r7_battery.sh is untouched; its resume-safe
skip-DONE behavior is intact because the self-heal
lives in the suites, not the runner. A committed copy
of the snapshot (roastery/scripts/
r4hunt_fixture_9919.json) is kept as a fallback behind
the lab-dir copy. Number note: this item was first
written as HUNT-56, then renumbered to HUNT-58 after
another round 8 worker claimed HUNT-56 (comparator
alignment) and HUNT-57 (its builder follow-up); the
renumber is comment-only, the proven code is identical.

Proof, live 2026-11-20 after the VM replacement and lab
recovery (gateway RUNNING 23:38 UTC, lab at the clean
7/101/0 baseline, slots cleared). Full chain, logs in
~/workspace/ignition-lab/r8-hunt58/:
- verify_roastery_r4hunt_a.py: exit 0, FAILS: [], PART A
  DONE. Fixture 9919 saved (41 series rows this run),
  snapshot written, 41 snapshot rows vs 41 db rows.
  A rerun immediately afterwards (A3) proved the start
  cleanup: "cleaning stale part A residue: fixture
  batch 1, series 42, fixture events 13, total events
  14", then re-roasted and re-saved clean, FAILS: [].
- verify_roastery_r4hunt_b.py (normal chain): exit 0,
  FAILS: [], PART B DONE, 17 PASS lines. Head of log:
  "fixture 9919 at part start: batch 1, series 41,
  events 13; fixture 9919 already present, 41 series
  rows". Fixture deleted through the app, series and
  press rows cascaded, lab (7, 101, 0).
- Wipe simulation: fixture 9919 rows deleted from the
  database only (counts 8/142/14 to 7/101/1), PressSlots
  left holding 14 stale presses, exactly the
  post-replacement state. Part B rerun: exit 0, FAILS:
  [], PART B DONE. Head of log: "fixture 9919 at part
  start: batch 0, series 0, events 0; fixture 9919
  missing or partial (batch 0, series 0, want 41);
  restoring from snapshot; press guard: PressSlots
  drained and cleared; fixture 9919 restored, 41 series
  rows". No manual part A rerun. Fixture deleted
  through the app, lab (7, 101, 0).
- verify_roastery_r4hunt_c.py: exit 0, FAILS: [], PART C
  DONE. Restored the fixture from the snapshot (batch 0
  to 41 series rows), deleted it through the app, lab
  (7, 101, 0) and still (7, 101, 0) after the 10 s
  stability wait: "baseline stable after 10s (no press
  resurrection)".
- verify_roastery_r4hunt_d.py: exit 0, PART D DONE.
  verify_roastery_r4hunt_e.py: exit 0, PART E DONE,
  PressEvents wrote the Charge row, final counts
  (7, 101, 0), SlotsCleared True.

Lab left clean at 7 batches (1042-1048), 101 series,
0 events, defaults restored (Fan 5, Heat 5, BatchNumber
1042, ActiveSource Simulated, Mode Off, ThemeMode
System, DispAxisFormat m:ss, PressCaptureMode Group,
PeriscopeAvailable True, background cleared,
PhaseFromBg False), PressSlots empty, and 0 events
still after a 60 s idle wait. Note: part E's final
tags read ThemeMode Light, not System; neither D nor
E writes ThemeMode, so a fresh browser session (light
color scheme) appears to sync the tag on startup.
Pre-existing suite behavior, not caused by this
change; the tag was written back to System by hand
after the chain and verified. Screenshots:
r4hunt-close-live-desktop-light/dark.png,
r4hunt-close-live-360-light/dark.png,
r4hunt-appsettings-desktop-open.png,
r4hunt-detail-close-desktop-light/dark.png,
r4hunt-detail-close-360-light/dark.png,
r4hunt-seek-during-360.png, r4hunt-seek-landed-360.png,
r4hunt-toast-light/dark-360.png,
r4hunt-delete-confirm-360.png (lab showcase/shots
only; the repo stays config only).

### Item 3: HUNT-59, HUNT-60, HUNT-61, fresh hunting pass (worker C)

Fresh hunting pass, worker C. New suite
verify_r8_freshhunt.py (lab, mirrored to the repo
roastery/scripts/), extending the round 7 suite: the
four-page walk (Roast, Log, BatchDetail staged 1042,
Settings) at 1360px and 360px, light and dark,
measuring horizontal overflow and clipped leaf text
(Perspective footer excluded), plus a live roast at
360px light measured at every stage (Charge, Dry End,
FC Start, ghost, Drop), the saved roast's detail at
360px dark, compare at 360px and 1360px dark with the
phone All-columns toggle, the AppSettings dock at 360px
dark, Settings scroll captures, and a
RoRSmoothingSec write/read-back. The suite does not
retest the timezone TIME axis passthrough or HUNT-46
(beta-gated) and does not touch the press path
(HUNT-53 app fix stays out of scope).

Suite result before the HUNT-60 fix: 72 PASS, 3 FAIL,
exit 1, log ~/workspace/ignition-lab/r8-freshhunt.log.
All three failures are the same HUNT-60 clip. Every
other check passed, including the full walk, the live
roast (New Roast, Charge, Dry End, FC Start, ghost,
Drop, Finish, Save Batch as 1049, Reset, Idle),
detail-1049 delete through the Log UI, compare at
360/1360 dark, the All-columns toggle, the AppSettings
dock, and the RoR smoothing write/read-back (45,
restored to 30). The HUNT-60 fix was verified by a
focused live re-probe, not a full suite rerun.

HUNT-59 (minor, fixed): the repo builder's
_custom_binding emitted binding-level-only
bidirectional (roastery/scripts/build_roastery_v4.py),
so regenerating the compare pickers would have
reintroduced HUNT-55. Fix: bidirectional true inside
config as well (binding-level copy kept, matching the
live views). Static proof, no gateway needed: the
AST-extracted _custom_binding output deep-equals the
live CmpA binding in Views/BatchesPanel/view.json, 3
PASS. Number note: first written as HUNT-57,
renumbered to HUNT-59 because HUNT-57 belongs to the
align worker's builder follow-up. Builder caveat: the
repo builder embeds a stale CORE_CODE/BATCHES_CODE
(pre-HUNT-23 build_compare) and its PROJ points at a
nonexistent path; it is a source record, never run
against the live tree, and the lab builder copy is
stale again after the sibling's align edits, so do not
re-copy it while the sibling edits.

HUNT-60 (minor, fixed): the Mode pill text "Roast"
clipped 31>29px at 360px while roasting (suite live,
dry-end and ghost-live stages, light). Root cause: the
HeadRow flex row is exactly full at 360px (Heading
140 + pill 53 + New Roast 93 = 286) and the pill's
default shrink 1 absorbed 2px; "Off" (3 chars) and
"Cool" (4 chars) fit, "Roast" (5 chars) does not.
First fix attempt FAILED and was reverted: adding
flexShrink 0 to the roast-mode-pill style class did
nothing, because Perspective writes inline
"flex: 0 1 auto" on flex children from their position
config, and an inline shorthand beats any stylesheet
rule. (The gateway did ingest the edited style.json,
blob b119a1ac, but the served style.css kept the old
rule under its versioned hash.) Real fix, in
Views/Controls/view.json: position shrink 0 on the
ModePill node (grow 0, shrink 0, basis auto), the same
pattern the Config popup fix used. Proof, live at
360px with Mode Roast: the pill's inline flex is now
"0 0 auto", pill 55px, span 31/31, zero clipped leaves
on the whole page, document width 360, New Roast
button 92px unclipped (the heading wraps to two lines
and absorbs the slack). Screenshot:
r8-probe-modepill-fixed3-card-360-light.png (lab
showcase/shots only; the repo stays config only).

HUNT-61 (minor, filed, fix not applied here): a
compare batch with no curve data silently vanishes
from the caption. Clean repro (lab at 7/101/0, Idle,
Align charge): batch 1050 created with 0 series rows,
picked as C with A 1048 and B 1047, Compare pressed.
Caption verbatim: "A = Batch 1048 Ethiopia Guji - B
= Batch 1047 Ethiopia Guji - Aligned on CHARGE".
Batch 1050 is not named and there is no note. Root
cause: compare_dataset skips batches with no points
("if not points: continue") with no caption note.
Fix sketch, for the align worker in compare_dataset:
append a note for chosen batches with no points, e.g.
" | Batch 1050 has no curve data." Screenshot:
r8-probe-nocurve-clean-1360-light.png. Batch 1050
was deleted through the Log UI afterwards; lab ends
Idle at 7/101/0.

HUNT-61 (minor, fixed by worker D): compare_dataset
now appends " | Batch <n> has no curve data." for each
chosen batch with no series rows, after the alignment
and fallback parenthetical, in both the staged caption
and the pick-at-least-one caption; the grid and rows
are unchanged. Proof: verify_r8_align.py extended
(gateway math plus live UI at desktop and 360px Light),
run 2026-11-21, ALL HUNT-56/HUNT-61 CHECKS PASSED, 44
PASS lines, exit 0. Live caption verbatim: "A = Batch
1048 Ethiopia Guji - B = Batch 1047 Ethiopia Guji -
Aligned on CHARGE | Batch 1050 has no curve data."
Screenshots: r8-nocurve-1360-light.png,
r8-nocurve-360-light.png (lab showcase/shots only;
the repo stays config only). Batch 1050 was deleted
through the Log UI afterwards; lab ends Idle at
7/101/0. Harness note: the first run of the extended
suite died twice on the single-process Chromium flake
(TargetClosedError on new_page), once at a second
sync_playwright() launch and once opening a second
context in the same browser; Phase 4 now relaunches
the browser inside the one playwright session and
reopens /log in a fresh page of the same context
(worker C's probe pattern).

Checked and dismissed this round: nothing else in
the walk failed. An earlier no-curve probe result
(empty caption, "Pick at least one batch to
compare.") was contaminated, the sibling deleted
fixture 9921 mid-probe while the lab went from 10
batches back to 7, and is superseded by the clean
HUNT-61 repro above; it is not a defect. Stray file
note, no action: the gateway tree has an extra
roastery/code.py (duplicate of core/code.py), not
present in the repo; leave alone.

Lab left clean at 7 batches (1042-1048), 101 series,
0 events, defaults restored (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss,
PressCaptureMode Group, PeriscopeAvailable True,
background cleared, PhaseFromBg False), PressSlots
empty.

Number note: HUNT-57 was the align worker's builder
follow-up (build_roastery_v4.py updated to match the
UDT member add in the HUNT-56 commit); it was not
separately filed. The builder bidirectional drift was
filed as HUNT-59.

### Lab incidents during the round

A VM replacement around 23:20 UTC on 2026-11-20
killed the gateway before the round started (the
coordinator's first StatusPing failed). Recovery:
Postgres not installed, workspace intact; the
os-intent replay's apt-get update hung on
mirror.cogentco.com (PID 799), killed by exact PID;
recover-lab.sh's chained update hung the same way
twice (PIDs 2844, 4991, killed by exact PID);
postgresql-16 installed from cache, cluster online,
DDL applied, gateway RUNNING, trial 6,859 s, reseed
verified 7 batches and 101 series by direct count
(the reseed script refused with "batches not empty"
because a concurrent process had already seeded).
Concurrent live activity during the recovery ran a
scripted press sequence on batch 9919 (counters
4880-4891, saved as an 8th batch) and started a
roast on batch 1042 (counters 4893-4897); PressSlots
were cleared twice and verified empty, and the
seed data was intact. A first gateway died
mid-startup (PID 3940, log truncated mid-line, no
OOM evidence); the second start succeeded.

Two VM replacements hit the closing battery
(2026-11-21, about 01:18 UTC during
validate_chartlab and about 03:15 UTC during the
first hunt55 rerun). Both recoveries followed the
standard pattern: hung replay apt-get update
killed by exact PID the first time (PID 800),
left alone the second time (finished on its own,
slow not hung, 75 lists); azure-only update fast;
recover-lab.sh clean; gateway RUNNING; database
back at 7/101/0 with no reseed needed. The second
replacement surfaced the textbook HUNT-53
resurrection: six press rows (Charge, Dry End, FC
Start, Drop, Finish, Reset for batch 1042,
counters 5186-5191, all stamped 03:20:11 at
gateway restart) reappeared from the PressSlots
ring after the fresh database came back. The guard
ran (slots cleared first, then the rows deleted),
0 events stable after a 60 s idle wait, and the
hunt55 rerun then passed from scratch. The HUNT-58
self-heal claim was not exercised by a live
replacement in this battery: part B ran with
fixture 9919 already present, so no restore was
needed; the claim still rests on the round 8 wipe
simulation.

### Verification

Closing battery, run 2026-11-21, 01:16 to 03:12 UTC,
runner run_r8_battery.sh (adapted from
run_r7_battery.sh, resume-safe, results in
r8-battery/results.txt), interrupted twice by VM
replacements and resumed from the same results file.
37 of 37 suites green on the final code; the one
first-pass failure is recorded after the table.

- validate_roastery_artisan.py: VALIDATION PASS.
- validate_chartlab.py: VALIDATION CHECK REPORT, 0
  chartlab warnings, 0 bogus control warnings.
- verify_roastery_ror.py: ALL ROR CHECKS PASSED, 6
  PASS, 1 designed SKIP (live window not on a steady
  ramp; same SKIP path as the round 7 rerun).
- verify_roastery_tier1.py: 42/42, ALL TIER 1 CHECKS
  PASSED.
- verify_roastery_tier2.py: 87/87, ALL TIER 2 CHECKS
  PASSED.
- verify_roastery_tier3a.py: 40/40, ALL TIER 3A CHECKS
  PASSED.
- verify_roastery_tier3b.py: 47/47, ALL TIER 3B CHECKS
  PASSED.
- verify_roastery_tier3c.py: 69/69, ALL TIER 3C CHECKS
  PASSED.
- verify_roastery_v4.py: 60/60, ALL CHECKS PASSED.
- verify_roastery_polish1.py: 49/49, ALL POLISH ROUND 1
  CHECKS PASSED.
- verify_roastery_polish2.py: 65/65, ALL POLISH2 CHECKS
  PASSED.
- verify_roastery_polish3.py: 37/37, ALL CHECKS PASSED.
- verify_r6_customs.py: 17/17, ALL R6 CUSTOMS CHECKS
  PASSED.
- verify_roastery_dark.py: 10/10, ALL DARK MODE CHECKS
  PASSED.
- verify_r6_hunt.py: 7/7, ALL R6 HUNT CHECKS PASSED.
- verify_roastery_pressburst.py: ALL PRESS BURST CHECKS
  PASSED (6 PASS lines).
- verify_roastery_pressfault.py: 62/62, ALL PRESS FAULT
  CHECKS PASSED.
- verify_roastery_deletecascade.py: 15/15, ALL DELETE
  CASCADE CHECKS PASSED.
- verify_r5_hunt3.py: 7/7, HUNT FAILURES: none.
- verify_roastery_axis.py: 14/14, ALL AXIS CHECKS
  PASSED.
- verify_r5_detail_span.py capture: 9920 25 rows, 9919
  7 rows, 1042 7 rows, every t label an even 30 s step;
  fixtures removed afterwards (PressSlots cleared
  first).
- verify_r7_hunt54.py: 33/33, ALL HUNT-54 CHECKS PASSED.
- verify_r7_hunt55.py: first pass rc=1 (see below);
  rerun rc=0, 17 PASS lines, ALL HUNT-55 CHECKS PASSED.
- verify_r7_freshhunt.py: PASSES: 41, FAILURES: none.
- verify_r8_align.py: ALL HUNT-56/HUNT-61 CHECKS
  PASSED, 44 PASS lines.
- verify_r8_freshhunt.py: PASSES: 75, FAILURES: none
  (the full-rerun proof for the HUNT-60 fix; was 72
  PASS, 3 FAIL before the fix).
- verify_r5_hunt.py: 12 PASS lines, HUNT FAILURES: none.
- verify_r5_hunt2.py: 6 PASS lines, HUNT FAILURES: none.
- verify_r6_abc.py: 16/16, FAILURES: none.
- verify_r6_abc2.py: 15 PASS lines, FAILURES: none.
- verify_roastery_r4hunt_a.py: FAILS: [], PART A DONE.
- verify_roastery_r4hunt_b.py: FAILS: [], PART B DONE.
- verify_roastery_r4hunt_c.py: FAILS: [], PART C DONE.
- verify_roastery_r4hunt_d.py: PART D DONE.
- verify_roastery_r4hunt_e.py: PART E DONE.
- cleanup_workspace.py: exit 0, lab (7, 101, 0).
- r7_udt_diff.py: UDT DIFF PASS, 0 differences
  (RoastBatch 204, RoasterSource 7).

First-pass failure, verify_r7_hunt55.py (suite bug,
not an app bug). Only check 3 of 17 failed: "pickers
carry startup defaults". The suite asserted the
dropdown texts equal the old 3-element list, but
HUNT-56 added the "Align on" dropdown to the compare
row, so dropdown_texts() now returns four entries
(1048, 1047, None, CHARGE). The app was correct:
pickers default to 1048/1047/None and the Align
dropdown reads CHARGE (the CompareAlignEvent
default), and the next checks passed in the same run.
Fix, suite only: the check now expects the
4-element list with a comment naming the HUNT-56
dropdown. Rerun: rc=0, 17 PASS lines, ALL HUNT-55
CHECKS PASSED. The suite had no repo copy (lab-only),
so the fixed suite was mirrored into the repo as
roastery/scripts/verify_r7_hunt55.py.

Lab left clean at 7 batches (1042-1048), 101 series,
0 events, defaults restored (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss,
CompareAlignEvent charge, PressCaptureMode Group,
PeriscopeAvailable True, background cleared,
PhaseFromBg False), PressSlots empty, and 0 events
still after a 60 s idle wait. ThemeMode read Light
after the battery (a fresh browser session syncs the
tag to Light, per the round 8 HUNT-58 note); it was
written back to System by hand and verified. The
PressEvents group is RUNNING by functional proof
(every suite press landed exactly once in the
audits).

### Round 9 candidates

1. The timezone TIME axis retest on the next Ignition
   beta (the passthrough candidates from round 2); the
   shipped category axis stays regardless.
2. The packaged Docker boot test on Eric's machine or
   homelab (still the one parity era item only he can
   run).
3. HUNT-46: the remounted page freeze on
   2027.2.0-beta1. Retest on the next beta; if it is
   fixed, the suite fresh-page workarounds can stay
   (they are harmless) and the docs note closes.
4. HUNT-53: the app-side fix (delete and cleanup paths
   clear the ring slots for the affected batch and
   counters; recovery clears PressSlots on a fresh
   database) still needs Eric's direction. The lab
   mitigation (clear PressSlots after every recovery
   and reseed) is in effect and proved itself again
   this round, twice.
5. The ThemeMode Light observation (round 8, HUNT-58
   note; battery note): a fresh browser session with
   a light color scheme appears to sync the ThemeMode
   tag to Light on startup, even though nothing in
   the suites writes it. Worth a look: whether the
   startup sync is intended and whether System mode
   should hold.
6. setup_roastery_v4_tags.py is a stale fork of the
   UDT list (live matches setup_roastery_artisan_tags.py,
   not it). Delete it or resync it; it is only a
   script, never run against the live tree.
7. Stray file, no action yet: the gateway tree has an
   extra roastery/code.py (duplicate of core/code.py),
   not present in the repo; leave alone until a
   cleanup round confirms it is unused.
8. The "ALIGN ON" label sits tight against the top
   edge of the C picker on the desktop Log page
   (round 8, HUNT-61 note). Pre-existing compare-row
   layout, cosmetic.
9. Style-class lesson (round 8, HUNT-60): a style
   class cannot override Perspective's inline flex
   shorthand on a flex child; set shrink/grow in the
   view's position instead. Also, POST /scan/projects
   ingested an edited style.json but the served
   style.css version hash did not bump, so a
   style-class-only change may not reach new sessions
   until the hash moves (gateway restart or Designer
   save). View changes do go live via scan.
10. The HUNT-58 self-heal claim still rests on the
    wipe simulation, not on a live replacement hitting
    the A-to-B chain; it is exercised only if a
    replacement lands mid-chain in a future battery.

### Polish round 9: ThemeMode startup sync and ALIGN ON spacing (worker A, 2026-11-21)

### Item 5: the ThemeMode Light observation is not a startup sync

Finding: there is no startup sync and no app change was
needed. The only write path to the ThemeMode tag in the
app is roastery.core.set_theme_mode, called only by the
three App Settings buttons (System, Light, Dark). The
page startup scripts (page_startup, main_startup) only
read the tag and set session.props.theme; the HudBar
themeMode binding is one way (bidirectional false) and
its onChange only re-applies the session theme and
re-reports brightness; the brightness probe clicks only
the two HudBar probe buttons, which set the session
chartDark prop. There is no session event resource, no
tag event script on ThemeMode (live export: a plain
memory tag, default System), and no transaction group
item touching it.

Proof, live: with the tag at System, a fresh
light-scheme session and a fresh dark-scheme session
each left it at System over a 20 s poll, while the
rendered theme still followed the device (container
#F4F4F4 light, #323232 dark). Two other round 9
probes found the same (worker B style probe, worker C
theme_startup_probe). The flips seen mid
investigation were concurrent suites and probes
writing the tag through the REST API, not the
browser: caught in the act, another worker's
r9_probe_gap.py writes Light as its first step and
its file timestamp (06:59:57) sits 2 s before a
flip timestamp (06:59:59); the round 8 chain ran
while the align and freshhunt suites, which write
Light and Dark through the API for their walks,
were also running. A clean watch with no sessions
open still flipped 61 s after a System write,
because a concurrent probe wrote Light in that
window. Lesson for future batteries: a ThemeMode
value read after a run proves which suite last
wrote it, not what any session did; the tag is the
remembered choice and only the App Settings buttons
write it from the app. Regression suite
verify_r9_theme_align.py (repo roastery/scripts,
mirrored to the lab) locks this in: fresh light and
dark sessions leave the tag at System.

### Item 8: ALIGN ON label crowding the C picker (fixed)

Root cause, two layers. First, structure: the Log
compare row mixed three bare dropdowns (A, B, C)
with one labeled column (the Align field), and the
row centered its children, so the ALIGN ON caption
protruded 7.5px above the pickers top edge and read
as a caption for C, tight against it (measured
desktop Light: label bottom 688, C picker top
680.5, gap minus 7.5). Second, spacing: the
caption to control gap the layout relied on was
never there. The style class compiler in this
build drops the gap property from style classes:
every gap rule serves empty in a live session
(.psc-roast-gap-8, -10, -12, -14 and the gap in
roast-cell, roast-content, roast-header and the
rest) while the sibling properties in the same
files serve, so the field's roast-gap-8 gap was
0px and the row's roast-gap-12 gaps were 0px too.
The same compiler behavior is already handled for
borders, display and min-height, which live in the
advanced stylesheet keyed to the same class names.

Fix, in Views/BatchesPanel/view.json: the row
bottom aligns its children (alignItems center to
flex-end), so the pickers share one baseline and
the caption sits above its own dropdown; and the
Align field carries a new hook class
roast-compare-field. In the advanced stylesheet:
.psc-roast-compare-field { gap: 8px; }, scoped to
the compare field only, so no other layout moves;
restoring gap globally would shift exact fit rows
elsewhere (HUNT-60 lesson). The builder
build_roastery_v4.py carries the same change
(cfg_field takes a classes argument, compare row
aligns flex-end). Its STYLESHEET_CSS copy is
already stale for other rules and a sibling is
resyncing it, so the new rule is not mirrored
there. The press path is untouched and
compare_startup is unchanged: the pickers stay
direct children of CompareRow, so their option
fill and bindings are exactly as before.

Proof: new suite verify_r9_theme_align.py, run
2026-11-21, ALL R9 THEME ALIGN CHECKS PASSED
(exit 0). Desktop Light and Dark: the served
rule reads gap 8px, the field computes gap 8px,
the ALIGN ON label clears the C picker top by
8px and its own dropdown by 8px, all four picker
tops read 696, no horizontal overflow and no
clipped leaf text, and Compare still stages A
1048 and B 1047 with the caption naming CHARGE
alignment. At 360px Light the row wraps and the
pickers stack (tops 928, 973, 1018, 1086), the
label clears its own dropdown by 8px, no
overflow and no clipped text. Screenshots:
r9-item8-fixed-desktop.png,
r9-item8-fixed-360-scrolled.png,
r9-item5-clean-light.png,
r9-item5-clean-dark.png (lab showcase/shots
only; the repo stays config only). Regression:
validate_roastery_artisan.py VALIDATION PASS and
verify_r7_hunt55.py ALL HUNT-55 CHECKS PASSED
(17 checks, fixtures removed after). Lab left
clean at 7 batches (1042-1048), 101 series, 0
events, defaults restored (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated, Mode
Off, ThemeMode System, DispAxisFormat m:ss,
CompareAlignEvent charge, PressCaptureMode Group,
PeriscopeAvailable True, background cleared,
PhaseFromBg False), PressSlots empty.

Deliberately left alone: the builder's
STYLESHEET_CSS copy (stale, sibling resync in
progress); worker C's align gap check, which
looks for a leaf with textContent 'ALIGN ON'
while the label's textContent is 'Align on'
(the uppercase comes from CSS text-transform),
so that check reports found false even with the
geometry fixed; and any suite that writes
ThemeMode through the API for its own walk,
which is legitimate harness behavior, not an app
defect.

### Polish round 9: fresh hunting pass, HUNT-62, HUNT-63, HUNT-65 (worker C, 2026-11-21)

Fresh hunting pass, worker C. New suite
verify_r9_freshhunt.py (lab, mirrored to the repo
roastery/scripts/), extending the round 8 suite:
the four-page walk (Roast, Log, BatchDetail staged
1042, Settings) at 1360px and 360px, light and
dark, measuring horizontal overflow and clipped
leaf text (Perspective footer excluded), the
Settings scroll sweep at 360px dark (0/25/50/75/
100%), a live roast at 360px dark measured at
every stage (Charge, Dry End, FC Start, ghost,
Drop) with the stats line shares and DTR checked
after Drop, the saved roast's detail at 360px
light, compare with three batches (A/B/C) at
360px dark with the phone All-columns toggle, and
static Artisan math checks run from the library
sources. The suite does not retest the timezone
TIME axis passthrough or HUNT-46 (beta-gated)
and does not touch the press path (HUNT-53 app
fix stays out of scope). The ThemeMode startup
probe from the first version was removed after
the dedicated probe below closed the question:
it is racy in the shared lab because other
suites write the tag through the API for their
own walks. The ALIGN ON label gap is measured
informationally only: the Log compare row is
owned by worker A in this round (see item 8
above), so the suite records the numbers
without failing on them.

Suite result (run 2, 2026-11-21, log
~/workspace/ignition-lab/r9-freshhunt2.log):
89 PASS, 2 FAIL, exit 1. The two failures are
both harness, not app: the theme probe flip
(closed by the dedicated probe below, a
concurrent suite writing Light in the window)
and a regex in the HUNT-65 shares check that
read "00:0526%" as 526 (fixed; the table text
parses to 26/37/37). Everything else passed,
including the full walk at all four combos,
the Settings sweep, the live roast at 360px
dark (New Roast, Charge, Dry End, FC Start,
ghost, Drop, Finish, Save Batch as 1049,
Reset, Idle), detail-1049 delete through the
Log UI, compare A/B/C at 360px dark, the
All-columns toggle, and the HUNT-62 and
HUNT-63 checks below. A third run hit a
concurrent worker racing the same batch number
(see the save note below) and died on a Log
row click timeout; the HUNT-62, HUNT-63 and
HUNT-65 checks in that run all passed before
the race, and a focused save probe afterwards
re-proved the save path end to end on a quiet
lab.

HUNT-62 (minor, fixed): the live AUC dropped
the curve segment straddling the AUC begin
event. core.auc_between kept only points at or
after begin_sec, so with the default fixed base
of 212 F it undercounted whenever the begin
temp was above the base. Quantified against
the exact from-begin integral on synthetic
curves (200 F rising 0.4 F/s): with the begin
between samples at 70.5 s on 1 s samples the
old form read 283.20 against 283.43 exact,
and on a 30 s grid with a Dry End begin at
75 s the old form read 273.00 against 281.25
exact. On a real roast the loss is the
straddling segment only, about 0.2 F-min at
the synthetic slope and about 1.5 F-min with
a real Dry End begin near 300 F on live 1 s
sampling, roughly 0.2% of a full roast AUC.
(Artisan profileAUC counts the segment ending
at the begin sample and the live updateAUC
counts the newest segment each tick, so both
Artisan paths include the straddle segment.)
Fix, in roastery/core/code.py: auc_between
now clips segments to begin_sec with an
interpolated temp, the same shape
batches._auc_range already uses. The saved
batch AUC is unaffected (curve_auc
integrates from charge, and the phase AUCs
already clip). Proof: the suite's static
checks compare the fixed function against an
independently written exact integral,
283.4325 vs 283.4325 on 1 s samples and
281.25 vs 281.25 on the 30 s grid.

HUNT-63 (minor, fixed): the phase shares on
the stats line did not add to 100. A live
roast (dry 8 s, FCs 12 s, drop 18 s) read Dry
0:08 44%, Mai 0:04 22%, Dev 0:06 33%, which
sums to 99: each share was rounded
independently. Fix: core.shares_100, largest
remainder rounding (floor every exact share,
hand the leftover points to the largest
fractional parts), used by core.stats_line_text
for the live Roast page line, by
batches.detail_startup for the BatchDetail
stats line, and by batches._phase_analysis
for the Phase Analysis table shares. When the
shown durations do not cover the total (a
partial roast with phases still missing) the
shares cannot sum to 100 by construction, so
plain rounding is used there instead. Proof,
live at 360px dark: the same roast shape now
reads Dry 0:08 45%, Mai 0:04 22%, Dev 0:06
33%, DTR 33%, and the detail stats line for
1042 reads 26/37/37. The DTR value itself was
already right ((drop minus FCs) over drop) and
is unchanged.

HUNT-65 (minor, fixed): the Phase Analysis
table on BatchDetail showed only the Cool row
for every seeded batch, while the stats line
directly above it showed all three phases.
Root cause: batches._phase_analysis derives
phase rows from the batch document's event
times, and the seeded documents carry stored
phase splits in doc['phases'] but no dryEnd
or fcStart events (the migration stored
durations, not event times). Proven on the
gateway for 1042 (events: charge and drop
only; phases: drying 5 s, maillard 7 s,
development 7 s): the old function returned
one row, Cool 00:01 5%. Fix, in
batches/_phase_analysis: for seeded batches
only (gated on seededFromRoastLog, so a real
roast with unstamped events still shows no
phase rather than a fabricated one from the
0/total sentinel splits), a phase with no
events still gets a row with its stored
duration and share and '--' for gain, RoR
and AUC, so the table agrees with the stats
line. Proof, live on the gateway: 1042 now
returns Drying 00:05 26%, Maillard 00:07
37%, Development 00:07 37%, Cool 00:01 5%,
and the suite's DOM read of the rendered
table shows all four rows. A full-events doc
exercised through the same function on the
gateway still returns event derived gains
and RoRs, so the save path (which calls
phase_analysis) is unaffected.

Checked and dismissed this round: the detail
'Phase Analysis' and 'Turning Point' suite
failures in run 1 were a probe artifact:
innerText returns the rendered uppercase
form of the section titles (CSS
textTransform), so the mixed case search
missed text that is on the page; the checks
now match lowercase. The ThemeMode Light
observation (round 8 candidate 5) is closed
with no app fix: the dedicated probe
r9_probe_theme.py (lab-only) found a 30 s
idle window with no session never flips the
tag, and fresh light and dark sessions
sampled every 2 s for 30 s never flip it
either; the flips seen mid investigation were
concurrent suites writing the tag through the
API, which worker A's section also caught in
the act. The Yield and Conversion Calculator
readouts sit exactly adjacent to the input
boxes (0px gap, measured: the TEMP (F) input
ends at x 1002 and the TEMP (C) readout
starts at x 1002), because the roast-gap-*
classes serve empty; worker A deliberately
scoped the gap restore to the compare field
only, so the calculator spacing stays as is
for round 10 to judge, not filed here. The
roast projection, turning point detection,
AUC guide quadratic, DTR definition, phase
RoR (Artisan RoR() from the turning point),
weight loss, and RoR parameter ranges were
all re-checked against Artisan 5.0.0 source
(main.py calcAUC, profileAUC, RoR, updateAUC,
updateAUCguide, canvas.py updateProjection)
and match; no HUNT filed for them.

Save race note (run 3): the suite's live
roast saved nothing within 30 s and the
1049 row never appeared in the Log table,
then the suite died on the row click timeout.
The save path itself is proven: the
_phase_analysis call inside
save_current_batch returns cleanly on a full
events doc on the gateway, and a focused
probe afterwards (r9_probe_save.py, lab-only)
roasted and saved batch 1051 end to end on a
quiet lab (saved True, Reset to Idle,
fixture removed). The run 3 failure lines up
with a concurrent worker racing the same
batch number: their BatchNumber read 1050
afterwards with a 16 row fixture 1050 in the
database, and the app refuses a save whose
batch number is already in the log by design.
That fixture is theirs, not this worker's, so
it was left in place: the lab ends at 8
batches (1042-1048 plus 1050), 117 series, 0
events, defaults restored (Fan 5, Heat 5,
BatchNumber 1042, ActiveSource Simulated,
Mode Off, ThemeMode System, DispAxisFormat
m:ss, CompareAlignEvent charge,
PressCaptureMode Group, PeriscopeAvailable
True, background cleared, PhaseFromBg False),
PressSlots empty.

Files changed (this worker, uncommitted):
roastery/project/Roastery/ignition/script-python/
roastery/core/code.py (HUNT-62, HUNT-63),
roastery/project/Roastery/ignition/script-python/
roastery/batches/code.py (HUNT-63, HUNT-65),
roastery/scripts/verify_r9_freshhunt.py (the
suite, mirrored from the lab),
roastery/docs/coffee-roaster-app.md (this
section). The library files were copied to
the gateway tree and POST /scan/projects
returned 200; repo and gateway copies are
identical by md5. No other files touched:
the compare row, stylesheet, theme and
startup scripts, setup_roastery_v4_tags.py,
and the press path were left to their
owners. Screenshots: r9-fresh-roast-live-
360-dark.png, r9-fresh-roast-ghost-live-
360-dark.png, r9-fresh-roast-dropped-
360-dark.png, r9-fresh-detail-1049-360-
light.png, r9-fresh-compare-abc-360-dark.png,
r9-fresh-detail-1042-analysis-1360-light.png
(lab showcase/shots only; the repo stays
config only).

Round 10 candidates: the calculator readout
to input adjacency above (0px gaps from the
dropped gap classes, pending a decision on
whether any global gap restore is wanted);
the HUNT-62 note that Artisan's own live and
saved AUC paths differ by the same straddle
segment, so the clipped form is exact from
the begin second but sits just under
profileAUC by that segment; the timezone TIME
axis retest and HUNT-46 on the next Ignition
beta; HUNT-53 still needs Eric's direction.

### Polish round 9: closing battery, 41 of 41 green

Battery run 2026-11-21, 07:46 to 09:48 MST,
runner run_r9_battery.sh, results in
~/workspace/ignition-lab/r9-battery/results.txt.
No VM replacement and no gateway outage during
the run. First pass: 39 of 41 suites green.
Two first-pass failures, both diagnosed and
rerun green, no genuine app failure
outstanding. Exact counts: validator
VALIDATION PASS; ChartLab CHECK REPORT, 0
warnings; RoR 6 PASS, 1 designed SKIP; tier1
42/42; tier2 87/87; tier3a 40/40; tier3b 47/47
on rerun; tier3c 69/69; v4 60/60; polish1
49/49; polish2 65/65; polish3 37/37;
r6_customs 17/17; dark 10/10; r6_hunt 7/7;
pressburst PASS; pressfault 62/62;
deletecascade 15/15; r5_hunt3 7/7; axis
14/14; detail span capture 9920 25 rows,
9919 7 rows, 1042 7 rows, all labels even;
r7_hunt54 33/33; r7_hunt55 17/17; r7_freshhunt
41 PASS; r8_align 44 PASS; r8_freshhunt 75
PASS; r9_style 34/34; r9_v4_udt PASS;
r9_theme_align PASS; r9_freshhunt 87 PASS, 0
FAIL; r5_hunt 12 PASS; r5_hunt2 6 PASS;
r6_abc 16/16; r6_abc2 15 PASS on rerun;
r4hunt A to E all DONE with no failures;
cleanup_workspace exit 0; r7_udt_diff PASS,
0 differences (RoastBatch 204, RoasterSource
7).

First-pass failure 1, verify_roastery_tier3b
(rc=1, one check): the phase bar dry segment
read 33 pct after PhaseFromBg was turned on,
where the ghost share is 46 pct. Harness
race, not an app defect: the suite's wait for
the dev band to reach the ghost drop boundary
returns at once because the saved targets
(200/200/200) put the dev band at 600 s too,
so the read landed milliseconds after the tag
write, before the page re-rendered. Fix,
suite only: wait up to 30 s for the dry
segment itself to reach the ghost share
before asserting, mirrored to the repo.
Rerun rc=0, 47 PASS, 0 FAIL, dry segment
46 pct.

First-pass failure 2, verify_r6_abc2 (rc=1,
three banner checks): the 2 hour Maker trial
expired during the suite's 2 minute wait for
elapsed time to reach 120 s, so the Roast
page was not rendered at all (the screenshot
shows the Trial Expired page). Environment
incident, not an app defect and not a suite
bug; the lab watch reset the trial right
after (6954 s left when checked). Rerun with
no change: rc=0, 15 PASS, 0 FAIL.

Commits, local only, no push: 80e96f3
(HUNT-62/63/65), 6c7e982 (items 6 and 9),
2dfd021 (item 8), 9143c9f (builder mirror:
the compare-field gap rule was missing from
the builder STYLESHEET_CSS string, so a
rebuild would have dropped the item 8 fix),
74e1fab (battery tier3b suite fix). Remote
head remains 900b2a2b5 (round 7); rounds 8
and 9 are both local until Eric's word.

Corrections to the worker C section above:
its round 10 list still carries the v4 tag
script fork and the stray gateway code.py
duplicate as held, but both were done in
this round by worker B (item 6 resync, item
7 removal), so they are not round 10 items.
HUNT-64 was never filed by any worker, so
the next HUNT number is HUNT-66. The
builder STYLESHEET_CSS staleness worker A
noted is fixed for the compare-field rule by
9143c9f, but the string is still stale for
other rules; a full resync is a round 10
candidate.

Lab left clean at 7 batches (1042-1048),
101 series, 0 events, defaults restored
(Fan 5, Heat 5, BatchNumber 1042,
ActiveSource Simulated, Mode Off, ThemeMode
System, DispAxisFormat m:ss,
CompareAlignEvent charge, PressCaptureMode
Group, PeriscopeAvailable True, background
cleared, PhaseFromBg False), PressSlots
empty, 0 events stable after a 60 s idle
wait, gateway RUNNING, trial about 5700 s
at close. The battery agent found stale
press contexts in slots 08 to 13 after the
battery (counters 5464 to 5469, 0 events in
the database) and cleared them per the
HUNT-53 mitigation before the reruns.

### Round 10 candidates

1. Calculator readout to input adjacency (0px
   gaps from the dropped gap classes): decide
   whether any global gap restore is wanted,
   or scope fixes field by field as item 8 did.
2. The HUNT-62 note: Artisan's own live and
   saved AUC paths differ by the straddle
   segment, so the clipped form is exact from
   the begin second but sits just under
   profileAUC by that segment.
3. The timezone TIME axis retest and HUNT-46
   on the next Ignition beta (beta-gated).
4. HUNT-53 app fix (delete and cleanup paths
   clear the ring slots; recovery clears
   PressSlots on a fresh database), still
   needs Eric's direction. The lab mitigation
   stays in effect.
5. The packaged Docker boot test on Eric's
   machine or homelab (Eric-side only).
6. Builder STYLESHEET_CSS full resync: the
   string is still stale for rules beyond the
   compare-field fix in this round.
7. The HUNT-58 self-heal claim still rests on
   the wipe simulation, not on a live
   replacement hitting the A-to-B chain.

### Polish round 10: builder STYLESHEET_CSS resync (worker C, 2026-11-21)

Candidate 6 from the round 10 list above, done. The
builder's STYLESHEET_CSS string in
roastery/scripts/build_roastery_v4.py now matches the
live advanced stylesheet byte for byte. The live
stylesheet was not changed by this worker, nothing
was rebuilt, and no HUNT number was needed: this
was staleness in a record copy, not an app defect,
so the reserved HUNT-70 and HUNT-71 numbers stay
unused. (A sibling worker did change the live
stylesheet mid-task; see the race note below.)

Canonical source. The repo project tree copy is
canonical, per the standing rule that the repo
project tree is the source of truth and the v4
builder is a snapshot that must never be run
against the live tree. Repo copy:
roastery/project/Roastery/com.inductiveautomation.
perspective/stylesheet/stylesheet.css, 14,222 bytes,
294 lines, md5 c0dcd1dfc93d9d0e9ab10bd8ffcb4d14 at
the time of the first sync below.
The gateway tree copy
(gateway-2027-maker/data/projects/Roastery/.../
stylesheet/stylesheet.css) is identical by md5, so
the two copies agree and there was no conflict to
resolve. The gateway tree was not touched.

Before. The builder string held 7,378 bytes and
160 lines against the live 14,222 bytes and 294
lines. Unified diff, builder to live: 195 lines,
16 rule blocks missing from the builder, 3 stale
rules present only in the builder, and 3 rules
moved or reworded. Rule by rule:

Missing from the builder (all present in live,
none in the builder string):

1. HUNT-31 brightness probe:
   .psc-roast-brightness-probe, opacity 0.01 with
   overflow hidden and pointer events none.
2. Polish phase 2 tab menu: .psc-roast-tabbar
   padding 6px 10px !important, the standalone
   .psc-roast-tabbar > * min-width 0 rule, and the
   560px media block with padding-right 60px and
   .psc-roast-tab-item padding 8px 6px at 13px.
3. .psc-roast-unit white-space nowrap.
4. .psc-roast-btn-compact min-height 28px.
5. .psc-roast-gear-btn min-height 40px.
6. HUD tightening (polish phase 2 item 7):
   .psc-roast-hud gap 3px and padding 3px 4px, and
   .psc-roast-hud-field padding-left 4px.
7. Round 6 HUD clock clip (HUNT-49): the 560px
   media block setting .psc-roast-hud-value to
   15px.
8. Polish round 3 (HUNT-25): the detail head
   stacking rules inside the phone headers 560px
   block, .psc-roast-detail-head flex-wrap wrap
   and .psc-roast-detail-titlecol flex 1 1 100%
   with order 3.
9. Polish round 5 dock buttons (HUNT-39):
   .psc-roast-btn-dock and
   .psc-roast-btn-dock-lead, nowrap with ellipsis
   and min-width 0.
10. HUNT-43: .psc-roast-btn-nowrap white-space
    nowrap.
11. HUNT-44: the 560px media block setting
    .psc-roast-seg-detail to 9px.
12. Round 6 mode pill: .psc-roast-mode-pill
    white-space nowrap.
13. HUNT-47: .psc-roast-cell-hidden display none
    !important.
14. The 560px declutter block under v4.1 holding
    only .psc-roast-tabbar > * min-width 0: the
    builder had that rule text only inside the
    stale compaction block below, never as the
    live standalone block.
15. The round 9 compare-field rule in its live
    position with the full round 9 comment (the
    builder carried the short 9143c9f version in
    an earlier position; the rule body, gap 8px,
    is the same).
16. The save-note rule .psc-roast-note-success
    min-height 18px in its live position with the
    longer comment (same body as the builder's
    early copy, plus the sentence about the
    position basis limit).

Stale in the builder, removed from live (the
v4.1 tab bar compaction block for the old button
tabs, superseded by the phase 2 menu):

- .psc-roast-tabbar padding 6px 60px 6px 6px with
  gap 6px.
- .psc-roast-tabbar > *:first-child flex 0 0
  46px. This rule is the one the live comment
  calls out: applied to the menu it collapsed
  the whole tab bar to 46px wide at phone
  widths.
- .psc-roast-tab-btn font-size 12px, padding 8px
  1px, nowrap with overflow hidden.

Moved or reworded, same rule body:
.psc-roast-note-success and
.psc-roast-compare-field moved to their live
positions with longer comments, and
.psc-roast-tab-btn:hover moved from after the
compare-field rule into the touch-targets block.
25 of the builder's 29 top-level units were
already identical to live.

Fix. The whole STYLESHEET_CSS literal was
replaced with the live file content, and nothing
else in the builder changed. Normalization: none
is needed and none is applied. write_styles
writes the string verbatim with f.write, so the
target is byte-identical, and it is: at the
first sync the AST-extracted builder string was
14,222 bytes with md5
c0dcd1dfc93d9d0e9ab10bd8ffcb4d14, the same hash
as the live file then. The git diff is confined
to the string (4 hunks, 182 insertions, 26
deletions, in build_roastery_v4.py only, after
the re-sync below).

Resync race, same morning. While this section
was being written, worker A's round 10
calculator-gap work (candidate 1) landed in the
live stylesheet: 22 added lines after the
compare-field rule, three scoped rules
.psc-roast-calc-row gap 12px,
.psc-roast-calc-field gap 8px, and
.psc-roast-calc-card gap 10px, with a comment
block (the BatchDetail view changed in the same
pass). The live stylesheet moved to 15,437
bytes and 316 lines, md5
4952c4beb425ab49d7ea05d3aaf1b0f9, and the
gateway tree copy matches that hash too. The
builder string was re-synced to the new live
content at 10:52 UTC, so it now matches the
new file byte for byte: AST-extracted string
15,437 bytes, md5 4952c4beb425ab49d7ea05d3aaf1b0f9.
The extraction proof was re-run after the
re-sync and is zero diff again (see below).
Lesson for the next resync: the builder string
goes stale again the moment any worker edits
the live stylesheet, so check the live md5 last
before calling a resync done.

Extraction proof. The builder module cannot be
imported from the repo copy: the module-level
FORM_SCHEMA load needs
scripts/knowledge/schemas-2027, which is not in
the repo, and main() must never run against the
live tree (its PROJ points at a gateway path
under the scripts directory, and a rebuild
would revert the app). So the proof ran the
builder's own write_styles() in isolation:
STYLE_CLASSES, STYLESHEET_CSS, and the
write_styles function were AST-extracted and
executed with PROJ pointed at the scratch dir
/tmp/r10c-scratch/proj, never at the gateway
tree. The emitted stylesheet.css diffs zero
against the live file, and the emitted
stylesheet resource.json diffs zero too, and
the whole proof was re-run after the race
re-sync above with the same zero-diff result.
The builder file compiles (py_compile passes).
The live stylesheet, the gateway tree, and the
lab database were not touched by this worker.

Validator not run. validate_roastery_artisan.py
needs a live gateway and a seeded database, and
its precondition was not met at the time of
this work: the 10:49 UTC recovery log shows the
gateway poll at RUNNING but batches=0, with the
reseed still pending, against the required
baseline of 7 batches (1042-1048), 101 series,
0 events, and the trial health was not
confirmed. Another round 10 worker was also
active in the lab (r10_probe_gap.py, 10:50).
Once the recovery confirms the baseline, run
the validator from the lab copy
(python3 validate_roastery_artisan.py in
~/workspace/ignition-lab) or the repo copy with
the gateway path as its argument. Note the
validator does not read the builder, so it can
only confirm the live tree is unmoved; git
status already shows that, with only the two
files below modified.

Other stale builder output found, out of scope,
reported not fixed. The same isolated
write_styles run also emits the style classes,
and the builder's STYLE_CLASSES is stale in the
same way: it writes 84 classes while the live
tree holds 92. The 8 live-only classes are
roast-btn-compact, roast-btn-dock,
roast-btn-dock-lead, roast-btn-nowrap,
roast-gap-14, roast-gear-btn, roast-tab-active,
and roast-tab-item. The 84 shared classes are
JSON-identical to live (the emitted files differ
only by a trailing newline). A STYLE_CLASSES
resync is a separate candidate, not done here,
because this item is scoped to the stylesheet
string only. The lab builder copy
(~/workspace/ignition-lab/build_roastery_v4.py)
is even staler, its string is 6,813 bytes and
misses even the note-success and compare-field
rules, and it was left alone. Two task-note
corrections: the lab scripts path named in the
brief (~/workspace/ignition-lab/roastery/
scripts/) does not exist; the lab builder lives
at ~/workspace/ignition-lab/
build_roastery_v4.py. And the builder ends with
a duplicated `if __name__ == '__main__':
main()` guard (two identical blocks); it is
pre-existing, harmless, and left as is.

Files changed (this worker, uncommitted):
roastery/scripts/build_roastery_v4.py (the
resync), roastery/docs/coffee-roaster-app.md
(this section). Lab left untouched: gateway
RUNNING per the 10:49 recovery poll, Postgres
16 online, database at 0 batches pending
reseed, no scan, no sessions, no tag or
database writes from this worker.

### Polish round 10: HUNT-62 note, Artisan live vs saved AUC (worker B, 2026-11-21)

Investigated, no code change, no HUNT filed. The round 9 note and
the Round 10 candidate 2 text say both Artisan paths include the
curve segment straddling the AUC begin event. That is wrong for
the live path, and the correction matters more than the number:
Artisan's live and saved AUCs disagree with each other by
construction, so there is no single Artisan number for our app to
match. Our clipped form is the exact integral from the begin
second, our saved phase AUCs are exact integrals over the event
seconds, and the saved headline AUC differs from Artisan's saved
AUC almost entirely by its base definition, not by any straddle
segment. The differences are immaterial on 1 s sampling (at most
0.30 F-min live, 3.45 F-min saved, against a full roast AUC near
1171 F-min), and changing any of our three numbers to mimic one
Artisan path would make it disagree with the other path and with
itself.

Artisan 5.0.0, read precisely (~/workspace/artisan-src,
src/artisanlib). Units first: Artisan computes AUC in C
(calcAUC converts temps with convertTemp(mode, 'C'), and the
statistics label reads C*min, canvas.py:11640), so Artisan C-min
values are F-min values times 5/9. Our AucTargetFMin default
1152.0 is 640 x 9/5, Artisan's AUCtarget 640 C-min, so the shapes
below are compared in F units with the same segment sets. The
defaults match on both sides: Artisan AUCbegin 1 (TP),
AUCbase 212 F, AUCbaseFlag False (canvas.py:657-659); our
AucBegin 'TP', AucBaseTempF 212.0, AucBaseFromEvent False
(setup_roastery_v4_tags.py:363-368).

Live path. calcAUC (main.py:24513) is the trapezoid of ONE
segment, the segment ending at index i (default i=-1, the newest
segment), with a guard that needs 0 < i, so i=0 contributes 0.
thisAUC (main.py:24479) takes the base from temp[idx] if
AUCbaseFlag else AUCbase, then calls calcAUC with i=-1 and
divides by 60: the begin index is used ONLY for the base, the
area is always the newest segment. updateAUC (main.py:24493)
runs once per sample tick, called from canvas.py:4969 in
sample_processing after the new sample is appended
(canvas.py:4711-4713): if the begin event is known, AUCvalue
adds thisAUC (the newest segment); else AUCvalue is reset to 0.
AUCvalue is written nowhere else (only reset, canvas.py:7920),
so there is no backfill and no recompute. Event stamps are
sample indices: markDryEnd sets timeindex[1] = len(timex)-1
(canvas.py:14404), the last sample at press time, and the other
marks use the same shape (markCharge canvas.py:14215/14229).

Saved path. profileAUC (main.py:24554) loops i in range(st, ed)
and adds calcAUC(i), with st = AUCbegin_idx (or the start arg)
and ed = min(len(timex), end or timeindex[6]). It counts the
segments ENDING at i for i in [st, ed). The saved AUC is
computedProfileInformation (main.py:16686) calling self.ts()
with no args (main.py:16808), so st = AUCbegin_idx and ed = the
DROP index; the phase AUCs are ts(charge, dry), ts(dry, fcs),
ts(fcs, drop) (main.py:16832-16843). The computed block is
rebuilt on load (main.py:17225), so an imported cached AUC is
recomputed from the curve.

What profileAUC includes that updateAUC does not, for the AUC
begin event: the full segment ENDING at the begin sample. The
segment was the newest segment on the tick BEFORE the event was
stamped, when updateAUC still held AUCvalue at 0, so the live
accumulation never adds it. With the default TP begin it is
worse: TP is detected inside sample_processing
(checkTPalarmtime, canvas.py:4415, needs more than 20 s since
charge and the sample 5 ticks back a local minimum below the
latest; findTPint, util.py:974, returns the index of the lowest
BT), TPalarmtimeindex is set to that past index on the detection
tick (canvas.py:4917), and updateAUC on the same tick adds only
the newest segment, so the live total misses the whole stretch
from TP to detection.

What updateAUC includes that profileAUC does not: the full
segment ENDING at drop (added on the drop tick, when the begin
was long known), and any segments after drop while recording
continues. profileAUC stops its loop at i = ed-1, so the
segment ending at drop is never counted. Both paths count every
middle segment exactly once.

Quantified (base 212 F throughout; ours is core.auc_between,
core/code.py:1064; exact is an independently written integral;
profile and live are faithful transcriptions of the Artisan
shapes above; the suite asserts each decomposition to 0.001):

- A, HUNT-62 synthetic 200 + 0.4t, 1 s samples, Dry End at
  70.5 s, drop 300 s: ours 237.5325, exact 237.5325, profile
  236.1333, live 237.6667. profile minus live is -1.5333, which
  is exactly the begin-end segment (69 to 70 s, 0.2633) minus
  the drop-end segment (299 to 300 s, 1.7967). live minus ours
  is +0.1342, exactly the pre-begin part of the straddling
  segment (70 to 71 s).
- B, same curve on a 30 s grid, Dry End at 75 s: ours 236.25,
  profile 192.00, live 240.00. profile minus live is -48.00,
  the begin-end segment (30 to 60 s, 3.00) minus the drop-end
  segment (270 to 300 s, 51.00). On a coarse grid the dropped
  final segment dominates, and profileAUC sits far BELOW ours.
- C, real seeded batch 1042 (21 samples, 243.9 to 251.8 F),
  counterfactual Dry End at 10.5 s, drop 20 s: ours 6.0444,
  exact 6.0444, profile 6.2808, live 6.3458. live minus ours is
  +0.3015, profile minus ours is +0.2365. The recomputed doc
  auc above the first temp is 1.3725 against the stored 1.3576,
  a 0.0149 gap from the migration having used its RoastLog
  curve rather than the stored series, not a defect.
- D, RoasterSim shape (200 to 385 F in 150 s, then to 435 F,
  1 s samples; Dry End 81.08 s, FCs 150 s, Drop 456 s; full
  roast AUC above 212 F is 1171.22 F-min). Dry End begin: ours
  1118.8986, profile 1117.0231, live 1119.0175. FCs begin: ours
  969.0000, profile 968.4240, live 969.0000 (the begin falls
  exactly on a sample, so live minus ours is 0). TP begin
  (the default): ours 1171.2222, profile 1167.7731, Artisan
  live with detection at 21 s 1170.1389, so Artisan live misses
  1.0833 F-min of the TP to detection stretch. For the default
  begin our clipped form sits ABOVE profileAUC by 3.4491,
  exactly the dropped last segment, which is the reverse of the
  note's framing.
- The begin-end segment alone, above base 212 F, is worth
  0.26 F-min at a 228 F Dry End (case A), 0.60 at a 248 F Dry
  End (case C), 1.45 at a 300 F Dry End (case D), and 2.88 at
  a 385 F FCs (case D). The pre-begin part of the straddling
  segment is at most 0.30 F-min on 1 s sampling.
- Phase AUCs on the sim curve, base 212 F, ours
  (batches._auc_range, batches/code.py:1534, clipped to the
  event seconds) vs Artisan ts() ranges: Drying 52.3236 vs
  50.7500, Maillard 149.8986 vs 148.5992, Development 969.0000
  vs 968.4240. Each differs by at most 1.57 F-min, and
  Artisan is lower in each case because its ranges drop the
  segment ending at the phase end.
- Saved headline AUC on the sim curve: ours curve_auc
  (batches/code.py:149, base charge temp 200 F, from charge,
  all segments) is 1261.45; Artisan ts() with the default TP
  begin and base 212 F is 1167.77; the gap is 93.68 F-min
  (7.4 percent). The base part of that gap is 91.20 F-min
  (12 F times 456 s over 60), over 97 percent of it. The
  straddle contributes nothing here (the TP index is 0, and
  the i=0 term of calcAUC is 0). The headline gap is a base
  definition, settled in v2 as the v2 roast log save
  definition, not a straddle error, and changing it would
  break comparability with every saved batch.

Decision, per number. Live AUC (AucLiveFMin, core
update_live_auc, core/code.py:1124, via auc_between): stays
clipped. It is the exact integral from the begin second, which
is what the label states, and it matches Artisan's live to
within 0.30 F-min while avoiding Artisan's TP detection miss.
Phase AUCs (batches._phase_analysis, batches/code.py:1621,
via _auc_range): stay clipped. They are exact integrals over
[begin second, end second], they tile the roast exactly, and
Artisan's index shifted ranges are the less precise statement
of the same phases. Saved headline AUC (doc['auc'],
batches.build_document, batches/code.py:187, via curve_auc):
unchanged; it has no begin event to straddle, and its gap to
Artisan ts() is the base definition. Stored aucDetail
(doc['aucDetail'].valueFMin, the live value at save time):
unchanged; recomputing it in profileAUC shape would make the
saved detail disagree with the live readout the user watched
and with the phase AUCs, and would embed Artisan's dropped
last segment. The .alog export is unaffected: artisan
_computed_for already writes AUC as the exact integral from
the TP sample to drop (artisan/code.py:1013-1025), and
Artisan recomputes it on import (main.py:17225).

Proof: new suite verify_r10_auc.py (lab, mirrored to the repo
roastery/scripts/), static checks against an independently
written exact integral plus read only live verification.
Result 43 PASS, 0 FAIL: the HUNT-62 regression numbers
(283.4325 and 281.25), ours equals exact on all five cases,
both end effect decompositions exact to 0.001, the TP
detection miss 1.0833, the saved headline gap 93.68 with the
base part 91.20, the three phase AUCs within 2.0 F-min of
Artisan ts(), the 1042 recomputation within 0.05 of stored,
trial healthy (6525 s left at the run), tags Idle, batch 1042,
System theme, AucBegin TP, AucBaseTempF 212.0, database 7
batches, 101 series, 0 events, and the three AUC functions
source identical between repo and gateway. One note from the
run: the repo batches/code.py differs from the gateway copy by
a parallel worker's HUNT-72/73 change (moisture and organic
loss clamping, Cool share), which does not touch any AUC
function; the suite checks the AUC function sources, not the
whole file md5, for exactly that reason.

Files changed (this worker, uncommitted):
roastery/scripts/verify_r10_auc.py (the suite, mirrored from
the lab), roastery/docs/coffee-roaster-app.md (this section).
No library code changed, so no copy to the gateway tree and no
POST /scan/projects was needed. No fixtures created, no
fixtures to delete, the press path untouched. Lab left clean:
gateway RUNNING with a healthy trial, database at 7 batches
(1042-1048), 101 series, 0 events, defaults restored (Fan 5,
Heat 5, BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss, CompareAlignEvent
charge, PressCaptureMode Group, PeriscopeAvailable True,
background cleared, PhaseFromBg False).

### Polish round 10: calculator gaps (worker A, 2026-11-21)

Round 10 candidate 1. The Yield and Conversion Calculator
readouts sat exactly adjacent to the input boxes (round 9
measured the TEMP (F) input ending at x 1002 and the TEMP (C)
readout starting at x 1002), because the style class compiler
drops the gap property from style classes.

Audit, live (lab-only probe r10_probe_gap.py, 16 combos: Roast,
Log, BatchDetail staged 1042, Settings, at 1360px and 360px,
light and dark, ThemeMode System with the device color scheme).
Every gap-defining container was measured for computed gap,
minimum box gap between children, and free space. The
compiler drop is confirmed still in effect: every roast-gap-*
container computes gap normal (0px), 88 of 91 containers on
the Roast page touch at 0px box gap, 122 of 122 on Settings,
34 of 54 on BatchDetail, 7 of 8 on Log, with zero clipped leaf
text and no horizontal overflow anywhere. The 0px box gaps are
mostly benign: children carry their own padding and borders
(cards, bordered inputs and dropdowns) or the row justifies
space-between, so the glyphs clear each other. The calculator
was the one true content adjacency: a bordered input and a
readout on the same row with 0px between the input border and
the readout digits.

Decision: scoped fix, as round 9 item 8 did, not a global gap
restore. A global restore of the four roast-gap-* helpers
would move all 288 uses at once, and the probe found
exact-fit rows it would shift. The Fan and Heat stepper rows
are exactly 160px wide with fixed children that cannot shrink
(minus 58px, value 44px, plus 58px, all grow 0 shrink 0, gaps
0px), so restoring 8px gaps would force them 16px over. The
compare row is exactly full at 1286px (four 299.5px pickers
plus the 88px Compare button). The HUNT-60 Mode pill HeadRow
is exactly full at 360px (286px of children), and the HUD is
already a fixed 3px gap from its own stylesheet rule. Restoring
gap on the roughly 100 column stacks would also lengthen every
page at once, an unreviewed global visual change for no
measured benefit anywhere except the calculator.

Fix, scoped to the calculator card only. In
Views/BatchDetail/view.json: CalcCard carries roast-calc-card,
CalcRow1 through CalcRow4 carry roast-calc-row, and all
fourteen Calc*Field columns carry roast-calc-field. In the
advanced stylesheet: .psc-roast-calc-row { gap: 12px; },
.psc-roast-calc-field { gap: 8px; },
.psc-roast-calc-card { gap: 10px; }. The fields are flexible
(grow 1, shrink 1, basis 150px) inside wrap rows, so the
restored gaps only shrink the fields, never overflow the card.
The builder carries the same change: _calc_field, _calc_row
and _calc_card emit the hook classes, and the candidate 6
worker resynced the builder STYLESHEET_CSS string from the
live stylesheet during this round, so it already contains the
three calc rules (verified byte identical to the live
stylesheet after my builder edit). The lab copy of the builder
still differs from the repo copy in a few style entries, as it
did before this round; the repo copy is authoritative.

Proof: new suite verify_r10_calc_gap.py (repo
roastery/scripts, mirrored to the lab). Run 2026-11-21:
74 PASS, 3 FAIL, exit 1, and the 3 failures are all in the
final restore block, caused by a parallel worker, not this
fix (see the lab note below). The fix itself passed at all
four combos: the calc rules serve 10/12/8px, the card
computes 10px with child gaps [10, 10, 10, 10, 10], all four
rows compute 12px with every line gap 12px (at 360px the
fields stack one per line and the 12px is the row gap between
lines), all fourteen fields compute 8px, the TEMP (F) input
clears the TEMP (C) readout by 12px at desktop (glyph to
glyph, was 0px) and the fields clear by 12px wrapped at
360px, the TEMP (F) caption clears its input by 8px, no
horizontal overflow and no clipped leaf text anywhere. The
calculator math still works through the real inputs: 212 F
drives TempC to 100.0 in the tag and the readout renders
100.0, then TempF restores to 415.0 through the input. The
App Settings UI flow was exercised once (gear, Light pins
light and writes the tag, System restores it). Rows
deliberately left alone did not move: compare picker tops
still 696, align field still 8px, picker to picker box gaps
still 0px; stepper rows still exactly 160px, 58/44/58, 0px
gaps; Tile value/unit box gaps still 0px. Screenshots:
r10-calc-gap-desktop-light.png, r10-calc-gap-desktop-dark.png,
r10-calc-gap-360-light.png, r10-calc-gap-360-dark.png, plus
probe shots r10-tiles-1360-light.png, r10-calc-1360-light.png,
r10-calc-360-light.png, r10-settings-1360-light.png (lab
showcase/shots only; the repo stays config only).

Checked and dismissed, no HUNT filed: the Tile value/unit
row (Range rects read 0px line-box gap, but the screenshot
reads "363.7 deg F" with a clear space; the digit side
bearings clear the unit, so it is not a defect); the
Analyzer caption to value columns (line-box gap 0px, one
-2.5px Range overlap at 360px, but the screenshot shows the
values sitting clear under their captions with no ink
collision); the Settings caption-over-control fields (122
containers at 0px box gap, glyphs clear by a few px in the
screenshot, the app standard form density, reviewed and
accepted across many rounds); the compare picker to picker
and align-field to Compare button 0px box gaps (bordered
controls touching read as a joined group, explicitly left
alone by round 9 item 8); the mobile HUD "BEAN F" caption
wrapping to two lines at 360px (pre-existing, reads fully,
nothing clipped, the HUD is exactly full by design). No new
HUNT numbers were needed, so HUNT-66 and HUNT-67 remain
unused; parallel workers in this round have filed up to
HUNT-75, so the next free number after this round is HUNT-76
with 66 and 67 still open as gaps.

Lab note (read this before trusting the suite tail): the
suite ran while the alarm worker's r10_probe_alarm2.py was
roasting in the same lab. Its roast of batch 1049 finished
(State Complete, Mode Cool) during my run, which is why the
final restore checks read (7, 101, 6), ThemeMode Light and
BatchNumber 1049. The 6 press rows are its roast (Reset for
1042, then Charge, Dry End, First Crack Start, Drop, Finish
for 1049); my suite presses no roast buttons and creates no
press rows. I deliberately did not reset the lab while its
probe was still running (PID 11079, started 11:03), so the
lab is left at its values: 7 batches (1042-1048), 101 series,
6 events, BatchNumber 1049, Mode Cool, State Complete,
ThemeMode Light, Fan 5, Heat 5, ActiveSource Simulated. My
calculator tags are back at the seeded values (ChargeG 200.0,
OutG 172.0, TempF 415.0, TempC 212.7778). The lab needs one
reset and a press-row clear by whoever finishes last. The
press path is untouched and no fixtures were created.

Files changed (this worker, uncommitted):
roastery/project/Roastery/com.inductiveautomation.perspective/
views/Views/BatchDetail/view.json (19 hook-class lines),
roastery/project/Roastery/com.inductiveautomation.perspective/
stylesheet/stylesheet.css (3 calc rules plus the comment),
roastery/scripts/build_roastery_v4.py (_calc_field, _calc_row,
_calc_card hook classes; the STYLESHEET_CSS resync in this
file came from the candidate 6 worker),
roastery/scripts/verify_r10_calc_gap.py (the suite, mirrored
from the lab), roastery/docs/coffee-roaster-app.md (this
section). The view and stylesheet were copied to the gateway
tree (repo and gateway copies identical by diff) and POST
/scan/projects returned 200. No other files touched: the
compare row, theme and startup scripts, Settings views, Tile,
Analyzer, stepper rows, and the press path were left to
their owners or deliberately left alone.

### Polish round 10: fresh hunting pass (worker D, 2026-11-21)

Suite: `roastery/scripts/verify_r10_freshhunt.py` (lab copy `~/workspace/ignition-lab/verify_r10_freshhunt.py`), run 2026-11-21. Final run (run 3): 134 PASS, 0 FAIL, exit 0. Coverage: static Artisan math checks run from the library sources; the four-page walk (Roast, Log, BatchDetail staged 1042, Settings) at 1360px and 360px, light and dark, measuring horizontal overflow and clipped leaf text (Perspective footer excluded); the Settings scroll sweep at 360px dark (0, 25, 50, 75, 100 percent); a live roast at 360px dark measured at every stage (Charge, Dry End, FC Start, ghost, Drop) with the stats line shares and DTR checked after Drop; the saved roast detail at 360px light; compare with three batches (A/B/C) at 360px dark with the phone All-columns toggle; the HUNT-65 regression (seeded 1042 Phase Analysis table) plus the HUNT-72 DOM check. Runs 1 and 2 died on suite bugs before the tail (see lab incidents); the HUNT proofs in them already passed and were re-proven in run 3. Log: `~/workspace/ignition-lab/r10-freshhunt3.log`. Screenshots: `~/workspace/ignition-lab/showcase/shots/r10-fresh-*.png`.

Informational measurements for other workers, not re-filed: the ALIGN ON label gap at 1360 light (label bottom 688, picker top 696, 8 px vertical separation, 0 horizontal gap) and the calculator labels with their page positions, both in the run 3 log. Worker A owns the calculator gap item and workers B/C own theirs.

#### HUNT-72 (minor, fixed): Phase Analysis Share column summed to 105 on batch 1042

Root cause: the Cool row carried a share on a different basis (cool seconds over the roast plus cool span) while the three phases share the drop total, so the column read 26/37/37 plus Cool 5 percent. Cool is not a roast phase and Artisan does not include it in phase shares. Fix: in `roastery/project/Roastery/ignition/script-python/roastery/batches/code.py`, `_phase_analysis` now writes '--' in the Cool share cell, like its gain, RoR and AUC cells. Proof: static check on the real 1042 document and series (Drying 00:05 26 percent, Maillard 00:07 37 percent, Development 00:07 37 percent, Cool 00:01 --) and the live table on the detail page, which reads the same rows and sums to 100.

#### HUNT-73 (minor, fixed): loss figures could go negative on inconsistent metadata

Root cause: with a 200 g charge, 184 g out (8 percent weight loss) and green moisture 12 percent against roasted 2 percent (10 percent moisture loss), organic loss read -2.0 percent. Artisan's dialog clamps organic loss to 0..100 (`calc_organic_loss` in `roast_properties.py`) and blanks a moisture loss at or below zero (`moisture_percent`). Fix: in `loss_yield_density`, `moistureLossPct` is stored only when greater than 0 and `organicLossPct` is clamped to [0, 100]. Proof: static checks (8.0/10.0/0.0; the ordinary case still reads organic 5.0) and the saved live roast document (batch 1049, crafted weights 200/184 and moistures 12/2: `weightLossPct` 8.0, `moistureLossPct` 10.0, `organicLossPct` 0.0).

#### HUNT-74 (minor, fixed): weight loss fallback did raw arithmetic, so a roasted weight over the green weight read -25 percent

Root cause: `build_document` computed the fallback loss as `(charge - out) / charge` directly, so WeightOutG 250 on a 200 g charge read -25 percent. Artisan `weight_loss` returns 0 in exactly that case. Fix: the fallback now uses `_weight_loss`, keeping the `out_w` greater than 0 guard (with no roasted weight recorded the loss is 0, not 100 percent). Proof: static (`_weight_loss(200, 250)` is 0.0, `_weight_loss(200, 184)` is 8.0) and a live edit through the slide over editor (WeightOutG 184 to 250, saved document `weightLossPct` 0.0).

#### HUNT-75 (minor, fixed): the slide over editor saved edited weights without recomputing the stored loss

Root cause: `_update_submit` wrote the edited metadata into the document but never recomputed `doc['weightLossPct']` or `doc['loss']`, so the BatchDetail Weight Loss tile kept the save-time value while the Loss section (recomputed live from metadata in `detail_startup`) showed the new one. Fix: new `_recompute_loss(doc)` helper in `batches/code.py`, called in `_update_submit` and `_create_submit`; the ModeNote text in BatchEdit now says saving also recomputes weight loss from the weights. Proof: static recompute (8.0, then 0.0 on edit to 250, loss weight key dropped) and the live edit (document `weightLossPct` 8.0 before the edit, 0.0 after, loss block recomputed with `moistureLossPct` 10.0).

#### HUNT-76 (minor, fixed): a Banner alarm fired during the roast stayed on the Complete screen after Finish

Root cause: `evaluate_alarms` only runs while the state is Roasting, Dropped or Cooling (`_live_analytics` returns before it in Complete), so nothing ever cleared the text even after the bean cooled below the threshold. Alarm probe 2 confirmed it live: a temporary Banner def (BT >= 210, 'R10 probe alarm') fired at Charge, and after Drop, Finish and 240 s the banner text was still on the Complete screen with AlarmActive True (the bean had returned to the 392 plateau, so the condition still held, but the mechanism was proven: no re-evaluation happens in Complete at all). Fix: in `roastery/project/Roastery/ignition/script-python/roastery/core/code.py`, `evaluate_alarms`, the Complete branch now publishes only latched Message alarm texts and clears Banner texts; latched Messages keep showing per their documented rule (latched until the next charge or reset). The branch runs on the Finish press itself (finish records the press after writing Complete) and on any later press or alarm edit while Complete. Proof: a live roast with the same temporary Banner def fires mid-roast ('R10 probe alarm') and reads AlarmActive False, AlarmText '' after Finish. Existing alarm assertions (tier1, polish3) are all in Roasting or Idle states and are unaffected.

#### Live roast measurements (run 3, batch 1049, 360px dark)

Charge, Dry End, FC Start, ghost and Drop each measured with no horizontal overflow and no clipped leaf text. Stats line after Drop: 0:08 45 percent, 0:04 22 percent, 0:06 33 percent, DTR 33 percent, which equals (drop minus FCs) over drop (dry 8, FC 12, drop 18). The ghost background ('Ethiopia Guji (test)') was set mid-roast and its label showed on the roast page. The saved roast detail at 360px light shows the Weight Loss tile at 8.0 percent with no negative organic loss, and the roast deletes through the Log UI. Compare A/B/C at 360px dark captions 'A = Batch 1048 Ethiopia Guji - B = Batch 1047 Ethiopia Guji - C = Batch 1046 Ethiopia Guji - Aligned on CHARGE', and the All-columns toggle measures clean.

#### Items checked and dismissed

- Roast degree boundaries have no Artisan 5.0.0 source for the names, so the mapping is Roastery's own; no HUNT.
- `_pct_from_internal` and `_internal_from_pct` agree with Artisan's event value conversions on every value Artisan itself stores; divergences only exist for internal values between -1 and 1 and negative percents, which Artisan never writes (the negative branch of `_internal_from_pct` is dead in practice since fan and heat percents are 0 to 100).
- The `_phase_analysis` offline turning point scan stopping at 50 percent of total when no Dry End is stamped only matters for pathological curves; the live detected turning point wins when present.
- DTR reading 0 percent when Drop is stamped without FC Start is consistent within the app (`build_document` does the same); Artisan has no FCs so development time is undefined, but the app treats it as zero.
- Detail `dLoss` showing '--' for a 0.0 loss is load-bearing for seeded stubs (WeightOutG 0 means not recorded), so the truthiness check stays.
- Total yield over 100 percent (125 percent on the edited 250 g document) follows the inputs arithmetically; Artisan's computed block does not clamp yield either, so only the loss percents are guarded (HUNT-73, HUNT-74).
- The editor dock's Close button works: the dock container (`.docked-view-right`) stays in the DOM when closed (empty, off screen at x 480 on a 360px viewport), so a count-based check wrongly fails; the close is proven by the editor content leaving the dock. No HUNT.
- The 'No Connection to Gateway' string in the body text read on detail pages is a `connection-message` div positioned off screen (y -28); it is captured by the body inner_text read but is not visible and the pages measure clean. No HUNT.

#### Builder staleness flag (round 10 candidate 6)

The sibling STYLESHEET_CSS resync landed in `roastery/scripts/build_roastery_v4.py`, and the ModeNote line from HUNT-75 survived it, but the embedded library strings still lack the HUNT-72 through HUNT-76 fixes: embedded `BATCHES_CODE` has no `_recompute_loss` and no HUNT-72 or HUNT-73 markers (78,268 chars versus 102,293 live), embedded `CORE_CODE` has no HUNT-76 marker (107,285 chars versus 176,491 live). The embedded strings still need the HUNT-72 through HUNT-76 fixes when the library resync lands. Do not rebuild the project from the builder until then, or the fixes will be lost.

#### Lab incidents during the round

- Alarm probe 1: the roast was too short, the bean only reached 218 F, so the 410 alarm never fired. It left BatchNumber 1049; cleaned up with a manual Dry End, FC Start, Drop, Finish, Reset browser sequence and restored BatchNumber 1042, 7 batches, 0 events. Lesson: the phone dock is phase-aware, Drop only surfaces after FC Start, FC Start only after Dry End, and there is no Reset button while Roasting at 360px.
- Alarm probe 2: temporary Banner def BT >= 210 fired at once (bean 392 at Charge); sequence corrected (Dry End, FC Start, Drop at bean 363.7, Finish to Complete). It confirmed the HUNT-76 mechanism and was cleaned up by its own finally (original AlarmDefsJson and BatchNumber 1042 restored, 0 events).
- Suite run 1: died at the delete step. After Save Batch, the unscoped Close click hit the wrong Close (most likely a toast close) and the editor dock stayed open over the Log page, so the click on '1,049' was intercepted by the dock's form widgets for 25 s. All checks up to the edit had passed, including the HUNT-73, HUNT-74, HUNT-75 and HUNT-76 live proofs.
- Suite run 2: died on a `TypeError` (`BASE + '/log'`, where BASE is the baseline-counts dict, not the base URL) right after the dock-close check failed on the container count. Both were suite bugs, not app bugs: the dock container persists in the DOM when closed, and the goto used the wrong variable. Fixed by checking the editor content leaving the dock and using `P.BASE` for the goto.
- Suite run 3: 134 PASS, 0 FAIL. Lab restored by the suite finally and the UI theme restore flow: Idle, BatchNumber 1042, Fan 5, Heat 5, ActiveSource Simulated, Mode Off, ThemeMode System, DispAxisFormat m:ss, CompareAlignEvent charge, PressCaptureMode Group, PeriscopeAvailable True, background cleared, PhaseFromBg False, MoisturePct 10.5, RoastedMoisturePct 0.0, 7 batches (1042-1048), 101 series, 0 events. Note: worker A's round 10 section records the lab left at Complete, BatchNumber 1049, 6 events and ThemeMode Light while this worker's probe 2 was still running; the runs since have restored it to the values above.

Files changed (this worker, uncommitted): `roastery/project/Roastery/ignition/script-python/roastery/batches/code.py` (HUNT-72, 73, 74, 75), `roastery/project/Roastery/ignition/script-python/roastery/core/code.py` (HUNT-76), `roastery/project/Roastery/com.inductiveautomation.perspective/views/Views/BatchEdit/view.json` (ModeNote text), `roastery/scripts/build_roastery_v4.py` (ModeNote line only, inside the sibling resync), `roastery/scripts/verify_r10_freshhunt.py` (the suite, mirrored from the lab), `roastery/docs/coffee-roaster-app.md` (this section). The library and view files were copied to the gateway tree (repo and gateway copies identical by md5) and POST /scan/projects returned 200. No other files touched: the press path, the timezone TIME axis, HUNT-46 and HUNT-53 were left alone per the brief.
### Polish round 10: builder library and style-class resync (worker E, 2026-11-21)

The sibling STYLESHEET_CSS resync (worker C) is done, and this
item closes the flag worker D left: the builder's embedded
library strings and STYLE_CLASSES in
roastery/scripts/build_roastery_v4.py are now resynced to the
live repo project tree. The live library files, the live
stylesheet, and the live style classes were not changed by
this worker, nothing was rebuilt, and no HUNT number was
needed: this was staleness in a record copy, not an app
defect.

Canonical source. The repo project tree is canonical, and the
gateway tree copies agree, so there was no conflict to
resolve. batches/code.py md5
1504c244d7a890b5f9130f579f0a9713 and core/code.py md5
376ad2620fac84295a79521c091c5233, identical in the repo and
gateway trees. The 92 live style classes are identical
between the repo and gateway trees by recursive diff. The
gateway tree was not touched.

Before. BATCHES_CODE held 78,266 chars against 102,293 live,
CORE_CODE held 107,279 chars against 176,491 live, with zero
occurrences of _recompute_loss, HUNT-72, HUNT-73, or HUNT-76
in the builder strings. STYLE_CLASSES held 84 classes against
92 live; the 84 shared ones were verified JSON-identical to
live before the change.

Fix. Both library literals were replaced with the live file
contents by AST span, and the 8 live-only classes were added
to STYLE_CLASSES: roast-btn-compact, roast-btn-dock,
roast-btn-dock-lead, roast-btn-nowrap, roast-gap-14,
roast-gear-btn, roast-tab-active, and roast-tab-item. The new
entries sit with their groups in the dict (the four dock and
compact buttons after roast-btn-step, roast-gap-14 after
roast-gap-12, the two tab classes after roast-tab-btn) and
keep the live style.json key order, so the emitted style.json
files match live apart from the trailing newline noted below.
One deliberate change of form: both literals switched from
plain ''' to raw r''' (the ARTISAN_CODE precedent in the same
file), because live core/code.py holds 4 line-continuation
backslashes, and a plain triple-quoted literal would swallow
each backslash and its newline when the builder is parsed.
Live batches/code.py holds no backslashes. Neither live file
contains ''' or a carriage return, and both end with a
newline, so the raw literal parses to exactly the live bytes.
The HUNT-75 ModeNote line in the builder's BatchEdit view
code was untouched and still carries the recompute wording.

After. BATCHES_CODE is 102,293 chars and carries _recompute_loss
plus the HUNT-72, HUNT-73, HUNT-74 (twice), and HUNT-75
markers; CORE_CODE is 176,491 chars and carries the HUNT-76
marker. STYLE_CLASSES holds 92 keys and equals the live set
exactly, parsed JSON for JSON. STYLESHEET_CSS was re-verified
after the edits and is still byte-identical to the live
stylesheet, md5 4952c4beb425ab49d7ea05d3aaf1b0f9, so the
mid-round stale overwrite worker A flagged has not recurred.
The builder file compiles (py_compile passes).

Extraction proof. The same method worker C used: the builder
module cannot be imported (the module-level FORM_SCHEMA load
needs scripts/knowledge/schemas-2027, which is not in the
repo), and main() must never run against the live tree, so
CORE_CODE, BATCHES_CODE, ARTISAN_CODE, STYLE_CLASSES,
STYLESHEET_CSS, write_library, and write_styles were
AST-extracted and executed with PROJ pointed at the scratch
dir /tmp/r10e-scratch/proj, never at the gateway tree. The
emitted core/code.py and batches/code.py diff zero against
live (md5 376ad2620fac84295a79521c091c5233 and
1504c244d7a890b5f9130f579f0a9713), the emitted stylesheet.css
diffs zero, all 92 emitted style.json files are parsed-JSON
identical to live with the byte diff a trailing newline only
(the builder's json.dump writes no trailing newline, the
live files end with one), and the library and stylesheet
resource.json files diff zero. The style-class resource.json
files differ in 4 of 92 (roast-btn-compact, roast-gear-btn,
roast-tab-active, roast-tab-item) only by the live attributes
carrying a gateway-stamped lastModificationSignature of ""
where the builder emits attributes {}; that is a
gateway-managed field the builder has never written, not
style content, and the other 88 match byte for byte. The
scratch dir was removed after the run.

Still stale, out of scope, reported not fixed. ARTISAN_CODE
is stale the same way: the builder holds 47,240 chars
against 48,038 live, a 64-line diff carrying the toast
additions to import_upload and the stage_background_upload
docstring move. Do not rebuild the project from the builder
until ARTISAN_CODE is resynced too, or those changes will be
lost. The lab builder copy (~/workspace/ignition-lab/
build_roastery_v4.py) is even staler and was left alone, as
was the builder's duplicated `if __name__ == '__main__':
main()` guard at the end of the file, pre-existing and
harmless. The lab was not touched by this worker.

Files changed (this worker, uncommitted):
roastery/scripts/build_roastery_v4.py (the resync),
roastery/docs/coffee-roaster-app.md (this section). The live
tree, the gateway tree, and the lab database were not touched.

### Polish round 10: closing battery, 44 of 44 green

Battery run 2026-11-21, runner run_r10_battery.sh, results
in ~/workspace/ignition-lab/r10-battery/results.txt. First
pass 11:55 to 13:02 UTC: 19 of 23 suites green, then the VM
write lock landed at 13:02 UTC (the gateway JVM died on
SQLite errors) and the run stopped at 23 of 44. Resume
16:35 to 17:49 UTC after the 09:30 MST recovery (write lock
lifted, gateway RUNNING, reseed 7 batches and 101 series):
the 4 environment failures reran green and 20 more suites
went green, leaving 5 failures, all diagnosed to two root
causes below, fixed, and rerun green 18:36 to 19:05 UTC.
Exact counts: validator VALIDATION PASS; ChartLab CHECK
REPORT, 0 warnings; RoR 6 PASS, 1 designed SKIP; tier1
42/42; tier2 87/87; tier3a 40/40; tier3b 47/47; tier3c
69/69; v4 60/60; polish1 49/49; polish2 65/65; polish3
37/37; r6_customs 17/17; dark 10/10; r6_hunt 7/7;
pressburst PASS; pressfault 62/62; deletecascade 15/15;
r5_hunt3 7/7; axis 14/14; detail span capture 9920 25
rows, 9919 7 rows, 1042 7 rows, all labels even; r7_hunt54
33/33; r7_hunt55 17/17; r7_freshhunt 41 PASS; r8_align 44
PASS; r8_freshhunt 75 PASS; r9_style 34/34; r9_v4_udt
PASS; r9_theme_align PASS; r9_freshhunt 88 PASS, 0 FAIL;
r5_hunt 12 PASS; r5_hunt2 6 PASS; r6_abc 16/16; r6_abc2
15 PASS; r4hunt A to E all DONE rc=0 (one FAILS artifact
in B, see below); cleanup_workspace exit 0; r7_udt_diff
PASS, 0 differences (RoastBatch 204, RoasterSource 7);
r10_calc_gap 76 PASS, 0 FAIL; r10_auc 43 PASS, 0 FAIL;
r10_freshhunt 134 PASS, 0 FAIL.

First-pass failures, all environment incidents, no app
defect: polish3 died waiting for the editor dock when the
Maker trial expired mid-suite; r6_customs pressed Charge
then the trial expired, leaving 1 stray Charge event row;
dark failed its clean-lab check on that stray row;
pressburst failed only its baseline check from the same
row (its own checks all passed, 11 presses, 11 rows,
exactly once) and restored the lab to 7/101/0. The watch
reset the trial to about 7176 s right after. All four
reran green with no change.

Root cause 1, the polish3 kill-switch save and the r9,
r10 suite failures (HUNT-77 filed for the tracking, no
app change): polish3 snapshots batch 1042's document at
start and restores it at the end via psql UPDATE. Its
editor_save rewrites the doc phases from the event times
on every save (batches/code.py _apply_events: dryingSec is
the dryEnd t, maillardSec is fcStart minus dryEnd,
developmentSec is drop minus fcStart, all 0 with no FC
event). The first editor_save('00:10') succeeded and
mutated the doc from the seeded phases (drying 5,
maillard 7, development 7, dtrPct 36.84) to drying 10,
maillard 0, development 0, dtrPct 0, adding a dryEnd event
at t=10. The kill-switch editor_save then asserted, so the
restore block never ran. The seeded doc's events block has
only charge and drop (the reseed writes no dryEnd event).
The HUNT-65 fallback in _phase_analysis only adds a row
for a phase with no valid event bounds when the seeded
batch's stored seconds are over 0, so with maillardSec=0
and developmentSec=0 those rows vanished and shares_100
over [Drying 10] with total 19 gave [53]. That is what
r9_freshhunt (shares sum to 100, Maillard and Development
rows), r10_freshhunt (KeyError 'Maillard' in
static_cool_share), and the stats line check all tripped
on. In round 9 the same saves happened but polish3
completed, so its restore put the seeded doc back before
r9_freshhunt ran, which is why round 9 passed the same
check with [26, 37, 37].

Root cause 2, BatchNumber 1049: r9_freshhunt's live roast
section saves as the next batch number (1049), deletes the
batch row in its finally, but never wrote the BatchNumber
tag back to 1042. Its finally restores theme, drains
pending, deletes batch_events, deletes the NEXT_BATCH row,
but had no BatchNumber write. In round 9 nothing after it
checked BatchNumber, so the gap was latent. The new round
10 suites calc_gap and auc check the lab is back at
BatchNumber 1042, so they failed. r7_freshhunt and
r8_freshhunt have the same latent gap (they also never
write BatchNumber back); only r9 was fixed, since it is
the last freshhunt in battery order.

Remediation, all verified in place. New lab script
~/workspace/ignition-lab/restore_1042_seed.py rebuilds batch
1042's document exactly the way reseed_from_roastlog.py
builds it for the first RoastLog row and UPDATEs only the
data column; it ran clean (phases 5/7/7, events charge and
drop). PeriscopeAvailable was found at False after the
aborted polish3 run (the kill-switch pass sets it False
before the editor save that asserted, and the restore never
ran) and was set back to True. verify_r9_freshhunt.py was
fixed in both copies (lab and repo, verified identical by
diff): the finally now writes BatchNumber 1042 after
deleting the NEXT_BATCH row, with a comment explaining the
round 10 suites depend on it, and a new check 'batch number
restored to 1042' was added after the 'theme restored'
check. The press guard ran after the battery (drain pending,
clear all 16 PressSlots) and the baseline re-verified at
7/101/0 with 0 events stable after a 60 s idle wait.

The kill-switch save itself (HUNT-77, harness fix, no app
change): polish3 failed twice in a row at the kill-switch
editor_save('00:12') with 'editor Save Batch never
enabled', while the earlier editor_save('00:10') in the
same run passed, and the failure is the exact one the
round 2 closing fix comment names (it ended both closing
battery runs then, and the reload recovery it added covers
only the mount poll, not the post-typing assert). Diagnosis
by probe, all on the live gateway: fresh-page saves pass
with the same prefill and both PeriscopeAvailable values
(save enabled at once); six plain remounts pass; the full
middle sequence (save 00:10, Charge press from the phone
dock, alarm Message latch, restore alarms, probe reset,
PeriscopeAvailable False, save 00:12) passes on a fresh
browser. The form mounts (59 inputs) but the aged page
instance stops applying the edit, the HUNT-46 class. Fix,
suite only, in verify_roastery_polish3.py (mirrored to the
repo): editor_save was refactored into open_once plus
try_type, and if Save still is not enabled after the typing
loop it does one reload recovery (reload, reopen the editor,
retry the typing loop once) before asserting. Standalone
rerun with the fix: 37 PASS, 0 FAIL, POLISH3 RESULT: ALL
CHECKS PASSED (the recovery did not need to fire on that
run). The app code path is proven working by the probes and
by the first save in every run; no app change was made.

r4hunt_b FAILS artifact: the battery run printed one FAIL
line ('import failure toast fires in Light') in its FAILS
list but exited rc=0. Standalone rerun with no change: 17
PASS, FAILS empty. Flake under battery-run load, not an
app defect; no change made.

VM replacement during the close: the VM was replaced at
about 18:17 UTC, between the battery rerun and the docs
work (uptime 7 minutes at 18:24, gateway down, Postgres
fresh and empty). The watch flow recovered it by 18:29
(gateway RUNNING, database already reseeded to 7/101/0,
trial 6942 s). The lab was re-verified from the clean
baseline before the polish3 standalone rerun, and the
battery rerun ran on the recovered lab.

Stylesheet and library md5 check at close: live advanced
stylesheet, repo copy, and builder STYLESHEET_CSS are all
md5 4952c4beb425ab49d7ea05d3aaf1b0f9, 15,436 chars,
byte-identical. CORE_CODE 176,491 chars, md5
376ad2620fac84295a79521c091c5233, byte-identical to live.
BATCHES_CODE 102,293 chars, md5
1504c244d7a890b5f9130f579f0a9713, byte-identical to live.
ARTISAN_CODE is still stale as worker E reported (47,240
chars in the builder against 48,038 live, a 64-line diff
carrying the toast additions to import_upload); do not
rebuild from the builder until it is resynced the same
way.

Commits, local only, no push: c7247bb (calculator gaps,
HUNT-62 note, new calc_gap and auc suites, docs), af6ee5b
(HUNT-72 through HUNT-76, new freshhunt suite), 0721bea
(builder STYLESHEET_CSS, library and style-class resync),
05fb2aa (closing battery suite fixes, HUNT-77), plus the
docs hash update in this commit. Remote head was 4cae20b37
(round 8) when round 10 closed; the round 9 push was in
flight separately and round 10 stays local until Eric's
word.

Held for round 11: ARTISAN_CODE resync in the builder
(47,240 vs 48,038 chars, 64-line diff); HUNT-53 app fix
still needs Eric's direction, lab mitigation stays in
effect; timezone TIME axis and HUNT-46 retest are
beta-gated on the next Ignition beta; Docker boot test is
Eric-side only; HUNT-58 live proof is still simulation
only (no VM replacement hit the r4hunt A-to-B chain during
this battery); r7_freshhunt and r8_freshhunt still carry
the latent BatchNumber gap (only r9 was fixed); next HUNT
number is HUNT-78.

#### HUNT-77 (harness, no app change): polish3 kill-switch save and the unrestored 1042 document

Two linked suite findings from the closing battery, one
incident chain. First, polish3 failed twice at the
kill-switch editor_save('00:12') with 'editor Save Batch
never enabled' while the earlier editor_save('00:10') in
the same run passed; probes showed the form mounts (59
inputs) but the aged page instance stops applying the edit,
the HUNT-46 class, and the same failure ended both closing
battery runs in the round 2 era. Second, the assert skipped
polish3's restore block, leaving batch 1042 mutated (drying
10, maillard 0, development 0, dryEnd event at t=10), which
broke the r9 and r10 freshhunt phase checks, and
r9_freshhunt never wrote BatchNumber back to 1042 after its
live roast section saved as batch 1049. Fixes, all suite
or lab only: editor_save gained a one-shot reload recovery
on the post-typing assert; new lab script
restore_1042_seed.py rebuilds the seeded 1042 document;
r9_freshhunt's finally now writes BatchNumber 1042 and
checks it. Proven: standalone polish3 37/37, closing
battery 44/44.

Lab left clean at 7 batches (1042-1048), 101 series, 0
events, defaults restored (FanLevel 5, HeatLevel 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss, CompareAlignEvent
charge, PressCaptureMode Group, PeriscopeAvailable True,
background cleared, PhaseFromBg False), PressSlots empty,
0 events stable after a 60 s idle wait, gateway RUNNING,
trial about 4347 s at close.

### Polish round 11: ARTISAN_CODE resync (worker A, 2026-11-21)

Record-copy staleness fix, not an app defect. No live app
file was changed, nothing was rebuilt, and the gateway tree
and lab database were not touched. Method follows round 10
worker E exactly. The repo project tree is canonical; the
live artisan code.py agreed between the repo tree and the
gateway tree before the edit (both md5
9cb340c9f32450aef868f3fa3680723f, diff zero), so there was
no conflict to resolve.

Before: builder ARTISAN_CODE 47,240 chars, md5
6300568f3b8ae5f644e84a7b7da9cb4c; live artisan code.py
48,038 chars, md5 9cb340c9f32450aef868f3fa3680723f.
Unified diff 64 lines, 21 added lines, 4 removed lines
(3 changed docstring lines plus context). All of it the
toast additions to import_upload (success, warning, and
error toasts through a toast accumulator), the docstring
move and success and error toasts in
stage_background_upload, and the success toast in
export_download. The ARTISAN_CODE literal was replaced
with the live file contents by AST span (old span lines
7112 to 8390, new span lines 7112 to 8407). Literal
safety was checked before the edit: the live file
contains no triple-quote sequence, no carriage returns,
ends with a newline, and holds 55 backslashes, so the raw
literal parses to exactly the live bytes. The builder
file compiles (py_compile passes). After: builder
ARTISAN_CODE 48,038 chars, md5
9cb340c9f32450aef868f3fa3680723f, exact match. Git diff
for the builder is 20 insertions and 3 deletions, all
inside the ARTISAN_CODE literal.

Extraction proof, same method as worker E: the builder
module cannot be imported (the module-level FORM_SCHEMA
load needs scripts/knowledge/schemas-2027, which is not
in the repo), and main() must never run against the live
tree, so ARTISAN_CODE, CORE_CODE, BATCHES_CODE,
STYLESHEET_CSS, STYLE_CLASSES, write_library, and
write_styles were AST-extracted and executed with PROJ
pointed at the scratch dir
~/workspace/ignition-lab/r11a-scratch/proj, never at the
gateway tree. The proof script is kept at
~/workspace/ignition-lab/r11a-scratch/proof.py, and the
emitted proj tree was removed after the run. Results, all
byte-identical to live (diff zero): artisan/code.py
48,038 chars, md5 9cb340c9f32450aef868f3fa3680723f;
core/code.py 176,491 chars, md5
376ad2620fac84295a79521c091c5233; batches/code.py
102,293 chars, md5 1504c244d7a890b5f9130f579f0a9713;
stylesheet.css 15,436 chars, md5
4952c4beb425ab49d7ea05d3aaf1b0f9. Library and stylesheet
resource.json files all identical. Style classes: 92
emitted, same set as live, parsed JSON identical for all
92 style.json files. Byte diffs are the known trailing
newline only (the builder's json.dump writes no trailing
newline, the live files end with one). The 7 differing
style-class resource.json files break down as 4 with the
gateway-stamped lastModificationSignature of "" in live
where the builder emits attributes {} (roast-btn-compact,
roast-gear-btn, roast-tab-active, roast-tab-item, the
same 4 worker E reported) plus 3 that differ only by the
trailing newline (roast-btn-dock, roast-btn-dock-lead,
roast-btn-nowrap, live attributes {} matching the emitted
{}). None of this is style content, and none of it was
touched by this worker. STYLESHEET_CSS, CORE_CODE, and
BATCHES_CODE still extract byte-identical after this
edit, so no stale overwrite has recurred. The lab builder
copy ~/workspace/ignition-lab/build_roastery_v4.py was
left alone, as worker E did; it is even staler. The
builder still carries the duplicated `if __name__ ==
'__main__': main()` guard at the end of the file,
pre-existing and harmless, noted by worker E and left
alone here too.

Note: worker D's HUNT-78, HUNT-79, and HUNT-81 fixes
landed in the live artisan/code.py after this resync,
so the builder went stale again at once; worker E
re-resynced both literals at the end of the round (see
below).

### Polish round 11: BatchNumber restore in r7 and r8 freshhunt (worker B, 2026-11-21)

Suite-only fix, no app change. Closes the latent HUNT-77
gap in the r7 and r8 freshhunt suites (r9 was fixed in
round 10). The r8 suite had the same live defect as r9:
live_roast_360 saves as NEXT_BATCH (next after the
seeded max, never hardcoded 1049), Reset leaves that
number in the BatchNumber tag, and the finally block
deleted the fixture batch but never restored the tag.
In the finally block, after the NEXT_BATCH and 1050
fixture deletes, it now writes BatchNumber 1042 with a
comment in the r9 wording, adapted to name the r9 and
r10 freshhunt phase checks as the following suites, and
after the 'theme restored' check at the tail it adds the
same 'batch number restored to 1042' check r9 uses.
Files: ~/workspace/ignition-lab/verify_r8_freshhunt.py
and ~/workspace/ignition-coffee-lab/roastery/scripts/verify_r8_freshhunt.py,
verified identical with diff after copying the lab file
to the repo. Both compile clean.

The r7 suite has no live roast section and never writes
BatchNumber. Its walk only stages batch 1042 through
R5.stage_one, which calls the gateway library
stage_detail and sets SelectedBatchNumber, not
CurrentBatch/BatchNumber. Its other writes are
RoRDeltaSpanSec, BackgroundLabel, BackgroundCurveJson,
and ThemeMode. So r7 does not carry the live defect,
only the latent exposure: a stale BatchNumber left by a
concurrent worker would break the phase checks in later
suites, and r7's counts-only 'lab clean' check would not
catch it. Change, defensive and matching the r9 shape:
in the tail cleanup, next to the ThemeMode System write,
it now writes BatchNumber 1042 with a comment saying
so, and after the 'theme restored' check it adds the
same 'batch number restored to 1042' check r9 uses.
File: ~/workspace/ignition-lab/verify_r7_freshhunt.py
only (there is no repo copy of this file). Caveat: r7's
main has no try/finally (unlike r8 and r9), so the
restore sits in the tail cleanup, not in a finally
block. A mid-run exception would skip it, exactly as it
already skips the theme restore today. Wrapping r7 in
try/finally was out of scope for this fix; the write is
defensive because r7 never changes the tag itself.

The other half of HUNT-77 (editor_save reload recovery)
was checked and is not applicable to either suite. The
reload recovery lives in the shared helper editor_save in
verify_roastery_polish3.py. Neither
verify_r7_freshhunt.py nor verify_r8_freshhunt.py calls
editor_save or imports polish3 (both import
verify_roastery_polish2 and verify_r5_detail_span only;
grep confirms zero editor_save references in either
file). Any future suite that calls polish3.editor_save
gets the recovery automatically from the shared helper.
Live verification came from the closing battery: both
suites green, with the new 'batch number restored to
1042' check passing in each (r7 42 passes, r8 76
passes).

### Polish round 11: fresh hunting pass, HUNT-78 to HUNT-82 (worker D, 2026-11-21)

New suite verify_r11_freshhunt.py, mirrored from the lab
to roastery/scripts/verify_r11_freshhunt.py. Five fixes,
all live in the Ignition library plus one expression tag.

#### HUNT-78 (minor, fixed): the Artisan import path computed weight loss with raw arithmetic

`profile_to_batch` in roastery/artisan/code.py computed
the imported batch weight loss as ((charge_w minus
out_w) * 100.0 / charge_w), so an .alog whose roasted
weight exceeds the green weight imported with a negative
loss. Artisan `weight_loss` returns 0 in exactly that
case (main.py:26047), and batches._weight_loss is that
function (the HUNT-74 fix in build_document); the import
path was the one place still using the raw form.
Evidence: static, _weight_loss(200, 250) is 0.0 while
the old formula gives -25.0. Live: the Log page upload
of a crafted .alog (the sample fixture with the out
weight raised to 250 g and a fresh roastUUID) imported
as batch 1049; the stored document read weightLossPct
0.0 with no -25 anywhere in the document, and the Loss
section carried no weight loss key. Fix:
profile_to_batch now uses batches._weight_loss(charge_w,
out_w) with the same out_w > 0 and charge_w > 0 guard
build_document uses, so a missing roasted weight still
reads 0, not 100 percent.

#### HUNT-79 (minor, fixed): the .alog export computed block wrote Artisan's keys with the wrong math

`_computed_for` in the same artisan library wrote four
values wrong in the exported .alog `computed` block:
weight_loss did the raw arithmetic, so it went negative
when the roasted weight exceeded the green weight;
total_yield was a percent (wout * 100.0 / win) where
Artisan writes grams, weight out minus defects
(computedProfileInformation, main.py:16889), so batch
1042 exported 86.0 where Artisan writes 172.0;
total_loss just copied weight_loss, ignoring the defects
loss Artisan adds in (main.py:13317 and 16890: total
loss is weight_loss over the yield weight, res = wout
minus defects), so with 200 g in, 184 g out and 10 g
defects, Artisan writes 13.0 and the export wrote 8.0;
AUC was integrated in F-min where Artisan's AUC is
always in C-min: calcAUC converts the temps to C first
and ts() is documented "always in C" (main.py:24513,
24554), and the comparator reads this cached value and
labels it C*min (comparator.py:348-350), so a
Fahrenheit integral overstates it by 9/5. The base stays
in mode units (212.0 in F), as Artisan writes it. Fix:
_computed_for now uses batches._weight_loss for
weight_loss, roast_defects_loss (newly written, as
Artisan writes it when nonzero), and total_loss (over
res = wout minus defects); total_yield is res in grams;
AUC is converted to C-min (x5/9) when the mode is F and
left alone in C mode. Loss percents and the yield are
rounded to 1 decimal, as Artisan's float2float does.
Proof: static checks in verify_r11_freshhunt.py
(over-green, defects, no-defects, and C-mode cases)
plus the live export of batch 1042 through the detail
page Export .alog button.

CORRECTION to the round 10 record: Artisan does NOT
rebuild the .alog `computed` block on load. The only
profile['computed'] assignment is in getProfile, the
save path (main.py:17225); on load Artisan reads the
cached block directly (comparator weight_loss and AUC,
the HTML report template dsd['computed'][fld], and
computed['TP_time'] in loadFile). The round 10 note
saying the block "is recomputed on import" was wrong.
The export computed block must therefore carry correct
values, which is why these were real file-level defects.
Note: the sample fixture itself carries total_yield
85.7 (a percent), so the fixture is not authoritative
for that key; the Artisan source is. The fixture was
built with the same percent convention the export used.

#### HUNT-80 (minor, fixed): the create path dropped typed event times

`_create_submit` in roastery/batches/code.py never
called `_apply_events`, so a manually created batch
with typed event times saved with no events, no total
time, no phases and drop_temp_f 0.0. The form invites
the typing: the create-mode editor shows the same event
fields as edit mode (Charge through Drop time and temp,
form fields 47-60), and the typed values were silently
discarded. The update path applies them through
_apply_events. Evidence: static, _apply_events on a
create-shape document with Dry End 04:30, FC Start
08:00, Drop 10:00 at 415 F. Live: the Log New Batch flow
with the same typed values saved batch 1049; before the
fix the stored document would have carried no events
(proven by the code path: _create_submit never called
_apply_events). Fix: _create_submit now calls
_apply_events(doc, event) after _apply_form, rejects
with the visible note and saves nothing on an error (the
same shape as _update_submit), and the insert carries
doc.get('dropTempF') or 0.0 instead of a hardcoded 0.0.
With no events typed nothing changes: the phases stay
empty and the total stays 0.

#### HUNT-81 (minor, fixed): the export turning point scan needed a Dry End stamp

The turning point scan in `_computed_for` scanned
charge to the dry index and required a Dry End stamp
(ti[1] set and greater than charge), so a batch with a
real dip but no Dry End event exported no TP at all and
its AUC started at charge. Artisan findTPint
(util.py:974) needs no Dry End: it scans charge to DROP,
capped at FC Start when one is stamped. Evidence:
static, on a dipping curve (390 F at charge, 340 F at
60 s, rising to 415 F) with no Dry End and no FC Start
stamped. Before the fix the computed block carried no
TP keys and the AUC integrated from charge (968 C-min);
after the fix it carries TP_idx 1, TP_time 60.0,
TP_BT 340.0 and AUC 883 C-min. Found when the suite's
export proof hit a missing TP_idx on batch 1042; for
1042 itself the TP sits at the first sample, so the old
code and the new code agree there and 1042 does not
prove the divergence. Fix: the scan cap is now the FC
Start index when set, else the drop index, else the end
of the curve, mirroring findTPint. The forward scan with
a strict less-than keeps the earliest sample holding
the minimum, as Artisan's backward scan does.

#### HUNT-82 (minor, fixed): the BatchDetail calculator showed -25.0% loss for an over-green batch

The "Loss from out (%)" readout on BatchDetail is bound
to the expression tag
[default]Roastery/Calculator/ActualLossPct, whose
expression was the raw arithmetic if({[.]ChargeG} > 0,
({[.]ChargeG} minus {[.]OutG}) * 100.0 / {[.]ChargeG},
0). For the imported over-green batch (200 g in, 250 g
out) it read -25.0, while the Weight Loss tile on the
same page read 0.0 (the HUNT-78 fix). Found by the
suite's detail page check in run 4: the page body
contained '-25.0' from this readout, not from a loss
value in the document. Evidence: live, with the
calculator inputs written to 200/250 the tag read
-25.0; at 200/184 it read 8.0. The fixture's own
computed RoR values are all positive, so the readout
was the only source. Fix: the expression now clamps at
0, if({[.]ChargeG} > 0, max(0, ({[.]ChargeG} minus
{[.]OutG}) * 100.0 / {[.]ChargeG}), 0), matching
batches._weight_loss. The repo source of truth is
roastery/scripts/setup_roastery_v4_tags.py (the script
itself is destructive by design and was NOT run against
the live lab). The live tag was updated by exporting
the Calculator folder, patching the one expression, and
importing it back with collisionPolicy Overwrite at the
parent path Roastery. The first import attempt used path
Roastery/Calculator and nested a duplicate
Calculator/Calculator folder instead of updating the tag;
that folder was deleted and the import redone at the
parent path, after which the live expression and the
200/250 value (0.0) verified. No other expression tag in
the Roastery tree does unclamped loss math (checked the
whole tree).

#### Suite runs and the regression net

Suite: roastery/scripts/verify_r11_freshhunt.py (lab
copy ~/workspace/ignition-lab/verify_r11_freshhunt.py).
Run 1 (2026-11-21): died in the HUNT-79 live export
proof with KeyError: 'TP_idx' on batch 1042, which is
how HUNT-81 was found. Everything before it passed,
including the HUNT-79 export values (total_yield 172.0,
weight_loss 14.0, total_loss 14.0, AUC 6 C-min) and the
four-page walk plus settings sweep. The lab was left
clean (7 batches, 101 series, 0 events, Idle,
BatchNumber 1042) except ThemeMode Light, since the
exception skipped the theme restore; the rerun restores
it. Run 2: died in the HUNT-80 live create proof: the
form fill hung on field 51, which does not exist. The
create editor carries 51 fields with the event times at
37-50 (Charge 37/38, Dry End 39/40, FC Start 41/42, FC
End 43/44, SC Start 45/46, SC End 47/48, Drop 49/50),
not the 61-field order the first probe saw, so the
suite's fixed indices were wrong for create mode. The
suite now fills by label. The lab was left clean
(7/101/0, Idle, BatchNumber 1042) except ThemeMode Light
again. Run 3: 125 passes, 2 failures, both from an over
broad substring check in the HUNT-78 import proof: the
imported document's only '-25' is the Artisan timezone
offset -25200 s (UTC-7) in the artisan identity
subdocument, and the detail page renders the same
offset. Neither is a loss value; the loss itself reads
0.0 and the Loss section carries no weight loss key. The
checks now exclude the loss renderings (-25.0 and -25%)
and assert the offset is the only '-25' in the document.
Run 4: 127 passes, 1 failure: the detail page check
found '-25.0' in the BatchDetail body for the imported
over-green batch. That was not a check artifact: the
calculator's Loss from out readout showed -25.0%, which
is HUNT-82. The import proof's doc checks all passed,
and the only '-25' in the document is the Artisan
timezone offset -25200 s. Run 5: 135 passes, 0 failures,
exit 0. The full battery: 37 static checks (HUNT-78,
HUNT-79, HUNT-80, HUNT-81, HUNT-82), the four-page walk
at 1360px and 360px in light and dark (no overflow, no
clipped leaf text), the Settings sweep at 360px dark,
the live 1042 export, the live create with typed events,
the live over-green import, and the live calculator tag
values. Lab left clean: Idle, 7 batches, 101 series, 0
events, ThemeMode System, BatchNumber 1042, calculator
reseeded to 200/172 (14.0%).

The regression net: the suite re-runs the four-page walk
(Roast, Log, BatchDetail staged 1042, Settings) at 1360px
and 360px, light and dark, measuring horizontal overflow
and clipped leaf text, plus the Settings scroll sweep at
360px dark. The walk and sweep contributed 53 of the 135
checks with no overflow and no clipped leaf text on any
page at either width in either theme, and detail 1042
stats shares summed to 100.

Items checked and dismissed, no HUNT filed: Roast degree
boundaries have no Artisan 5.0.0 source for the names, so
the mapping is Roastery's own (same as round 10). The
360px Roast page shows two Charge buttons and two
stepper sets in the button list, but only one set is on
screen: the phone dock is sticky at the bottom and the
desktop ROAST CONTROLS card sits in the page flow below
the fold. At 1360px only the desktop card renders. That
is the settled dual layout, not a duplicate control.
`_fan_heat_series` `level_at` uses the first slider
event's level for samples before the first event; that
matches the app's own background convention (the first
row sets the starting levels). The export computed block
still omits volume_gain, moisture_loss, organic_loss and
the densities, which Artisan writes when present.
Consumers read those keys with defaults, so the omission
is a gap, not a wrong value; left alone to keep the
HUNT-79 fix to the values that were wrong. The app's own
AUC tags and documents stay in F-min per the round 10
decision. Only the exported .alog computed block
converts to C-min, because that block is Artisan's key
shape consumed by Artisan code that labels it C-min.
TIME axis retest and HUNT-46 were not retested
(beta-gated). The press path, the HUNT-58 r4hunt chain
and the builder files were not touched by this worker.
HUNT-53 still needs Eric's direction.

Files changed (this worker): roastery/project/Roastery/ignition/script-python/roastery/artisan/code.py
(HUNT-78, HUNT-79, HUNT-81),
roastery/project/Roastery/ignition/script-python/roastery/batches/code.py
(HUNT-80), roastery/scripts/setup_roastery_v4_tags.py
(HUNT-82), roastery/scripts/verify_r11_freshhunt.py (the
suite, mirrored from the lab). The library files were
copied to the gateway tree (repo and gateway copies
identical by md5) and POST /scan/projects returned 200.
The HUNT-82 tag fix is not a file copy: tags live in the
gateway tag provider, so the live
Roastery/Calculator/ActualLossPct expression was updated
through the tag export/import API (verified by a fresh
export and by the tag value at 200/250 reading 0.0).

### Polish round 11: ARTISAN_CODE and BATCHES_CODE resync (worker E, 2026-11-21)

Record-copy staleness fix, not an app defect. Worker D's
HUNT fixes re-staled the builder after worker A's
resync, so both literals were re-resynced at the end of
the round. Method follows round 10 worker E exactly and
the round 11 worker A notes. The repo project tree is
canonical; the live files agreed between the repo tree
and the gateway tree before the edit (artisan both md5
62440fefcbcbc94a148d0990f7fbae84, batches both md5
7a0d7cac2119a2aaa002d55524c7e3f7, diff zero), so there
was no conflict to resolve.

Before: builder ARTISAN_CODE 48,038 chars, md5
9cb340c9f32450aef868f3fa3680723f (span lines 7112 to
8407); live artisan code.py 50,982 chars, md5
62440fefcbcbc94a148d0990f7fbae84. Builder BATCHES_CODE
102,293 chars, md5 1504c244d7a890b5f9130f579f0a9713
(span lines 4606 to 7019); live batches code.py 102,901
chars, md5 7a0d7cac2119a2aaa002d55524c7e3f7. ARTISAN_CODE
diff 100 lines, 67 added, 9 removed, all of it the
worker D HUNT fixes: HUNT-78 (import_upload now calls
batches._weight_loss), HUNT-81 (turning point scan
mirrors findTPint), HUNT-79 (AUC converted to C-min
when the mode is F, weight block uses _weight_loss for
weight_loss, total_loss, and the new
roast_defects_loss, total_yield in grams). BATCHES_CODE
diff 26 lines, 14 added, 1 removed, all of it HUNT-80
(_create_submit calls _apply_events, insert carries the
edited drop temp instead of a hardcoded 0.0). Both
literals were replaced with the live file contents by
AST span (BATCHES_CODE old span lines 4606 to 7019, new
span lines 4606 to 7032; ARTISAN_CODE old span lines
7112 to 8407, new span lines 7125 to 8478). Both stay
raw r''' literals. Literal safety was checked before the
edit: neither live file contains a triple-quote sequence
or a carriage return, both end with a newline, the live
artisan file holds 53 backslashes and the live batches
file holds 0, so the raw literals parse to exactly the
live bytes. The builder file compiles (py_compile
passes). After: builder ARTISAN_CODE 50,982 chars, md5
62440fefcbcbc94a148d0990f7fbae84; builder BATCHES_CODE
102,901 chars, md5 7a0d7cac2119a2aaa002d55524c7e3f7.
Exact match on both. Git diff for the builder is 101
insertions and 13 deletions, all inside the two
literals.

Extraction proof, same method as worker E and worker A:
AST-extracted and executed with PROJ pointed at the
scratch dir ~/workspace/ignition-lab/r11e-scratch/proj,
never at the gateway tree. The proof script is kept at
~/workspace/ignition-lab/r11e-scratch/proof.py, and the
emitted proj tree was removed after the run. Results,
all byte-identical to live (diff zero), against both the
repo tree and the gateway tree: artisan/code.py 50,982
chars, md5 62440fefcbcbc94a148d0990f7fbae84; core/code.py
176,491 chars, md5 376ad2620fac84295a79521c091c5233;
batches/code.py 102,901 chars, md5
7a0d7cac2119a2aaa002d55524c7e3f7; stylesheet.css 15,436
chars, md5 4952c4beb425ab49d7ea05d3aaf1b0f9. Library and
stylesheet resource.json files all identical. Style
classes: 92 emitted, same set as live, parsed JSON
identical for all 92 style.json files. Byte diffs are
the known trailing newline only, in 13 files. The 7
differing style-class resource.json files break down as
4 with the gateway-stamped lastModificationSignature of
"" in live where the builder emits attributes {}
(roast-btn-compact, roast-gear-btn, roast-tab-active,
roast-tab-item, the same 4 worker E and worker A
reported) plus 3 that differ only by the trailing
newline (roast-btn-dock, roast-btn-dock-lead,
roast-btn-nowrap, live attributes {} matching the emitted
{}). None of this is style content, and none of it was
touched by this worker. CORE_CODE and STYLESHEET_CSS
still extract byte-identical after this edit, so no stale
overwrite has recurred. The lab builder copy was left
alone, as worker E and worker A did; it is even staler.
The builder still carries the duplicated `if __name__ ==
'__main__': main()` guard at the end of the file,
pre-existing and harmless, noted by worker E and worker
A and left alone here too.

### HUNT-83 (harness, no app change): cleanup_workspace hardening after the 22:17 UTC recovery

During the 22:17 UTC recovery on 2026-11-21, the Dry End
click did not take on the fresh boot with 1.2 s waits,
the Drop click timed out after 20 s, and the roast was
left Roasting with 1 Charge row. The coordinator finished
the roast through the UI, cleared 6 press rows with the
HUNT-53 guard, restored defaults, and hardened
cleanup_workspace.py (visible-only button matching, wait
up to 15 s for the next button, one reload retry).
Hardened cleanup tested end to end: exit 0, lab clean
7/101/0. Note: the Reset button text at Complete is
'Reset / New Roast', not 'Reset'. Helper scripts
r11-finish-roast.py and r11-restore-defaults.py in
~/workspace/ignition-lab/ were used during that recovery
and removed at close.

### Polish round 11: closing battery, 45 of 45 green

The battery is ~/workspace/ignition-lab/run_r11_battery.sh,
45 suites: the 44 from round 10 plus the new
verify_r11_freshhunt.py. Results in
~/workspace/ignition-lab/r11-battery/results.txt. First
run started 2026-11-21 22:27 UTC and got 30 DONE before
a VM replacement at about 00:20 UTC 2026-11-22 killed it
mid-suite (verify_r11_freshhunt running, no DONE line):
30 green rc=0, 3 rc=1 failures, ALL ENVIRONMENTAL, none
rerun yet at that point: validate_roastery_artisan rc=1
at 22:28:37, the single hits entry is the known
PressEvents boot-minute warning (gateway started before
Postgres existed; the validator requires zero hits);
verify_r10_auc rc=1 at 00:12:19, 42 PASS, 1 FAIL
'gateway trial healthy (over 600 s left)' (trial nearly
expired); verify_r10_freshhunt rc=1 at 00:19:20,
TimeoutError on .psc-roast-gear-btn:visible as the VM
was dying (HUNT-46 class). Resume after the recovery
ran the remaining 15 suites: 13 green, then the same
two suites failed again at 00:34:55, both environmental
in a new way. The validator failed again on the same
PressEvents boot warning, because the gateway had booted
at 00:21 and the validator scans warnings from the last
15 minutes (SINCE defaults to now minus 900 s), so a
fresh boot always trips it. verify_r10_auc failed on
'lab at clean Idle, batch 1042, System theme' with the
theme reading Light: the failed r10_freshhunt run had
left ThemeMode Light, the cleanup does not restore
ThemeMode, and the value survived the gateway restart.
Both were rerun clean after the next recovery (gateway
booted 02:20 UTC, trial 6399 s): the auc rerun passed
43/43 at 02:28:51 with ThemeMode System (the fresh boot
restored the System default), and the validator rerun
passed at 02:39:04, more than 15 minutes after the boot
so the warning had aged out of its window. Final:
45/45, all rc=0. Headline counts: verify_r11_freshhunt
135 passes, verify_r10_freshhunt 134, verify_r10_auc
43, verify_r7_freshhunt 42, verify_r8_freshhunt 76,
verify_r9_freshhunt 88, validator VALIDATION PASS, UDT
diff 0 differences (RoastBatch 203 plus Sources folder,
RoasterSource 7).

The r11_freshhunt first rerun flake: after the round 11
close work, the suite was rerun once more and came back
134 passes, 1 failure 'HUNT-80 created batch shows in
the Log table' (2 s wait too short for the table to
render); a second rerun came back 135/0 green. Recorded
as a timing flake in the suite, not fixed.

HUNT-58 live proof: still simulation-only. No VM
replacement hit the r4hunt A-to-B chain during the
battery; the replacements hit before the battery and
during r11_freshhunt instead.

VM replacements during the round: about 20:17 UTC,
about 22:17 UTC, about 00:20 UTC, about 02:17 UTC, and
about 04:17 UTC 2026-11-22. Each recovery followed the
proven path (gateway restart, Postgres install via the
os-intent replay, role and database creation, DDL,
reseed to 7/101/0, HUNT-53 press guard, hardened
cleanup, 60 s stability check). The 04:17 replacement
came after the battery had closed at 02:39; the lab was
recovered again at 04:19-04:20 (gateway RUNNING, trial
7070 s, 7/101/0, cleanup exit 0) and left clean for
round 12.

Stylesheet and library md5 check at close: live
advanced stylesheet, repo copy, and builder
STYLESHEET_CSS are all md5
4952c4beb425ab49d7ea05d3aaf1b0f9, 15,436 chars,
byte-identical. CORE_CODE 176,491 chars, md5
376ad2620fac84295a79521c091c5233, byte-identical to live.
BATCHES_CODE 102,901 chars, md5
7a0d7cac2119a2aaa002d55524c7e3f7, byte-identical to live.
ARTISAN_CODE 50,982 chars, md5
62440fefcbcbc94a148d0990f7fbae84, byte-identical to live.
Repo and gateway library md5s match on all three
packages. The builder is now fully resynced; do not
rebuild from it until the next round's library changes
are resynced the same way.

Commits, local only, no push: da9b652 (HUNT-78 to HUNT-82
fixes and the new r11 freshhunt suite), 7321163 (builder
ARTISAN_CODE and BATCHES_CODE resync), 196bf31 (r8
freshhunt BatchNumber restore), plus the docs section in
this commit. Remote head is dbfe20758 (round 10); round
11 stays local until Eric's word.

Held for round 12: HUNT-53 app fix still needs Eric's
direction, lab mitigation stays in effect; timezone TIME
axis and HUNT-46 retest are beta-gated on the next
Ignition beta; Docker boot test is Eric-side only;
HUNT-58 live proof is still simulation-only (no VM
replacement hit the r4hunt A-to-B chain during this
battery); the r11_freshhunt timing flake (2 s wait for
the Log table to render) is recorded, not fixed;
cleanup_workspace.py does not restore ThemeMode, so a
suite that leaves it Light can fail the next suite's
clean-state check until a gateway restart resets it;
next HUNT number is HUNT-84.

Lab left clean at 7 batches (1042-1048), 101 series, 0
events, defaults restored (FanLevel 5, HeatLevel 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss, CompareAlignEvent
charge, PressCaptureMode Group, PeriscopeAvailable True,
background cleared, PhaseFromBg False), PressSlots empty,
0 events stable after a 60 s idle wait, gateway RUNNING,
trial about 7070 s at the 04:20 UTC recovery.

### Polish round 12: fresh hunting pass, HUNT-84 and HUNT-85 (worker B, 2026-11-22)

New suite verify_r12_freshhunt.py, mirrored from the lab
to roastery/scripts/verify_r12_freshhunt.py. Two fixes, both
live in roastery/batches/code.py, plus Settings UI
write/read-back proofs and the four-page regression walk.

#### HUNT-84 (minor, fixed): the compare caption named the reference slot twice

`align_compare_slots` appended the reference slot to
fallbacks in its ref_t fallback branch AND again in the
per-slot loop, so with slot A seeded (no FCe) and alignment
on FCe the caption read "A has no FCe, charge aligned, A
has no FCe, charge aligned, B has no FCe, charge aligned".
Evidence: static, on seeded-shape slot data (fallbacks
[('A', 1042), ('A', 1042), ('B', 1043)]); live, on /log
before the fix, the same doubled caption. Fix: the branch
now only falls back the reference time; the loop records
every slot lacking the event, the reference included, so
each slot is named once. The shifts and the reference line
are unchanged (ref shift 0, ref line on the B event at
390 s). Proven live after the fix: the caption reads "A =
Batch 1048 Ethiopia Guji - B = Batch 1047 Ethiopia Guji -
Aligned on FCe (A has no FCe, charge aligned, B has no
FCe, charge aligned)".

#### HUNT-85 (minor, fixed): clearing a stamped Drop left the derived data stale

`_apply_events` recomputed totalSec, phases, drop temp and
degree only when a drop time was present, so blanking the
Drop time in the slide over editor (the event time fields
are not required in the form, so blanking is reachable)
saved the removal but left totalSec 600, phases 270/210/120
with DTR 20 percent, dropTempF 415 and roastDegree Full
City in the document. Evidence: static, on a 1042-shape
document; live, on a created batch 1049 with typed events
(Dry End 04:30, FC Start 08:00, Drop 10:00 at 415 F), whose
stored document still read totalSec 600 with phases
270/210/120 after the Drop was cleared and saved. Fix: when
a stamped drop is cleared, the derived data recomputes
from the remaining events (total is the last stamped event,
480 s here; phases 270/210/0 with DTR 0.0; roastEnd
cleared). dropTempF and roastDegree keep the tag's drop
temp, the same convention build_document uses for a live
save with no drop stamped. Guarded on a drop having been
stamped before the edit, so a batch that never had one
keeps its stored total and phases exactly, and an empty
create still leaves phases empty (the HUNT-80 contract).
Proven live after the fix: the cleared 1049 document reads
totalSec 480, phases 270/210/0 with DTR 0.0, roastEnd
null, Drop event null, then the scratch batch deletes
through the Log UI.

#### Settings write/read-back through the UI

The Display axis format dropdown (Artisan (m:ss) to Padded
(mm:ss) and back) and the compare alignment dropdown
(CHARGE to FCe and back) and the Projection mode dropdown
were each flipped through the Settings page and read back
from their tags, then restored. The alignment dropdown is
the same CompareAlignEvent tag the HUNT-84 live proof sets,
so the round trip also proves the Log compare row and the
Settings Display dropdown agree. Harness note: a JS
.click() on a dropdown's outer div never opens its list
(the open handler lives on the inner container), so the
suite clicks through the Playwright locator; and the
phrase 'No Connection' in a Settings page body is
legitimate page text (the Roaster source status area), not
a session banner, so it must not be used as a connectivity
check.

#### Suite runs

Suite: roastery/scripts/verify_r12_freshhunt.py (lab copy
~/workspace/ignition-lab/verify_r12_freshhunt.py). Run 1:
died in the Settings write-back probe with a 20 s timeout
on the 'Padded (mm:ss)' option (the JS .click() cause
above). Everything before it passed, including the
HUNT-84 and HUNT-85 static and live proofs. Run 2: died
in the same probe, the option list still never opening.
Run 3: 79 passes, 0 failures, died in the 360-dark walk
when stage_one(1042) failed three times with empty output,
while a concurrent verify_r11_freshhunt run (started
06:23 UTC by another process) shared the lab: its scratch
runner writes the same r5_stage_one.jy file, ScratchV3
view and Probe/Results tag, and one of its runs printed
into this run's stage log (staged n:1049 in the 360-light
walk). Run 4, after the concurrent run finished and the
lab verified clean: 96 passes, 0 failures, exit 0. The
full battery: 17 static checks (HUNT-84 fallbacks and
shifts, HUNT-85 recompute plus the HUNT-80 regressions),
the HUNT-84 live caption, the HUNT-85 live create/clear/
delete, the Settings dropdown round trips, the four-page
walk at 1360px and 360px in light and dark (no overflow,
no clipped leaf text), the Settings scroll sweep at 360px
dark, and the detail 1042 stats shares summing to 100
(26/37/37). Log: ~/workspace/ignition-lab/r12-freshhunt.log.
Screenshots: ~/workspace/ignition-lab/showcase/shots/r12-fresh-*.png.

Regression reruns after the fixes, all green: the r11
suite 135 passes (HUNT-78 to HUNT-82 intact), the r8
suite 76 passes (compare alignment intact), the r10 suite
134 passes (phase analysis and shares intact).

Items checked and dismissed, no HUNT filed: the Artisan
SLOT_DOC order matches the timeindex order (CHARGE, DRY,
FCs, FCe, SCs, SCe, DROP, COOL), so imports map SC events
correctly. loss_yield_density matches Artisan (weight_loss
and volume_increase guards, calc_organic_loss returning
(0, 0) unless both losses are nonzero, total yield as
weight out minus defects). The DRY phase RoR branches
match Artisan RoR() (greens temp first, else the turning
point). bt_similarity matches Artisan curveSimilarity in
shape (RMSE over DRY to DROP with DROP aligned); Artisan
locates its dry start by scanning back from DROP for the
phase boundary temp while Roastery uses the recorded Dry
End event, a documented adaptation. _plan_at and
validate_target_plan cover their edges (single point
falls back to the last temp, first point must be at 0,
strictly increasing). The alarm latch clears in
_reset_live_analytics, so a Message alarm cannot leak
into the next roast. parse_mmss accepts seconds of 60 or
more inside mm:ss (04:60 reads 300 s); no Artisan source
contradicts it and the ordering check still rejects
nonsense, so it stays. The live stats line shows Dev
--:-- when FC was never stamped even after Drop, while a
saved document records development 0 s; the two agree
that the duration is unknown, so it stays. TIME axis
retest and HUNT-46 were not retested (beta-gated). The
press path, HUNT-53, HUNT-58 and the builder files were
not touched by this worker. HUNT-53 still needs Eric's
direction.

Files changed (this worker, uncommitted):
`roastery/project/Roastery/ignition/script-python/roastery/batches/code.py`
(HUNT-84, HUNT-85; 32 insertions, 1 deletion),
`roastery/scripts/verify_r12_freshhunt.py` (the suite, new
file), `roastery/docs/coffee-roaster-app.md` (this
section). The library file was copied to the gateway tree
(repo and gateway copies identical by md5, be7dd651...)
and POST /scan/projects returned 200. The builder's
BATCHES_CODE literal is now stale by this change (same
position as rounds 10 and 11); it needs the resync pass
before anyone rebuilds from build_roastery_v4.py, or the
fixes will be lost. Not committed, no push, per the
brief. The working tree also carries a
`roastery/scripts/verify_r11_freshhunt.py` modification
(the round 12 Log table poll fix) that is not this
worker's; it was already present when this round started.

Lab left clean at 7 batches (1042-1048), 101 series, 0
events, defaults restored (FanLevel 5, HeatLevel 5,
BatchNumber 1042, ActiveSource Simulated, Mode Off,
ThemeMode System, DispAxisFormat m:ss, CompareAlignEvent
charge, ProjectionMode Linear, PeriscopeAvailable True,
background cleared, PhaseFromBg False), PressSlots empty,
0 events stable, gateway RUNNING. Next HUNT number is
HUNT-86.

### Polish round 12: closing battery, 46 of 46 green

The battery is ~/workspace/ignition-lab/run_r12_battery.sh,
46 suites: the 45 from round 11 plus the new
verify_r12_freshhunt.py. Results in
~/workspace/ignition-lab/r12-battery/results.txt. The run
was interrupted twice by VM replacements and resumed twice
from the DONE lines, then five suites were rerun after the
HUNT-86 fix below.

First run started 2026-11-22 07:25 UTC and got 5 DONE,
all green, before a VM replacement at about 07:44 UTC
killed it mid tier3a. Resume 1 ran tier3a through
r10_auc, 32 DONE total, all green, before a second VM
replacement at about 09:25 UTC killed it mid
r10_freshhunt. Resume 2 ran r10_freshhunt through
r7_udt_diff and finished the 46 DONE lines with 41 green
and 5 failures, all cascade from one crash: r10_freshhunt
rc=1, r11_freshhunt rc=2, r12_freshhunt rc=1,
r6_abc rc=1, r6_abc2 rc=1. The r11, r12, and both abc
failures were all a single clean-state check each (the
lab was left at Complete with a stray batch), because the
r10 crash left the workspace dirty.

HUNT-86 (major, found in the close, fixed): the r10 live
roast took batch 1049, then saved as 1050. The suite
clicks New Roast exactly once, and the saved 1050
document carries the r10 roast itself (charge 09:39:23,
drop 09:39:42), so a second new_roast invocation moved
the tag mid-roast. The mechanism was proven with a
scratch repro (r12_newroast_repro.py): two New Roast
clicks took 1049 then 1050 with nothing saved. The
platform re-delivers button clicks (HUNT-27 precedent),
and new_roast computed max(max_db, cur) + 1
unconditionally, so a re-delivered press bumped the
number twice. Fix in batches/code.py: when the current
tag is above every batch in the database, the number was
already taken by an earlier New Roast and not yet saved,
so the call reuses it; a saved batch always raises
max_db to at least the tag, so a genuine next roast still
increments. Repro rerun after the fix: both clicks hold
1049. New checks in verify_r12_freshhunt.py (2 static, 5
live including the press row cleanup): 7 checks, all
passing, suite total 103. The stray batch 1050 and its 17
series rows were deleted by hand; the r10 finally
cleanup deletes only NEXT_BATCH (1049), so it had missed
them. The builder BATCHES_CODE literal was resynced after
the fix (105,263 chars, md5 290a398b), all four literals
byte-identical to live again.

Rerun of the five failed suites (10:36 to 11:14 UTC):
r10_freshhunt rc=0, r11_freshhunt rc=0,
r12_freshhunt rc=0, r6_abc rc=0, r6_abc2 rc=0. Final:
46/46, all rc=0. Headline counts: verify_r12_freshhunt
103 passes, verify_r11_freshhunt 135,
verify_r10_freshhunt 134, verify_r9_freshhunt 88,
verify_r8_freshhunt 76, verify_r7_freshhunt 42,
verify_r10_auc 43/43, verify_r9_style 34/34, axis suite
all passed, validator VALIDATION PASS, UDT diff 0
differences (RoastBatch 204, RoasterSource 7).

Round 12 held items, all closed: the r11_freshhunt 2 s
Log table wait is now a real poll for the created batch
row (worker A, suite green twice at 135/0);
cleanup_workspace.py restores ThemeMode to System
(worker A, proven by setting Light first); the same
script now clears all 16 PressSlots after deleting press
rows (worker A, proven end to end with 0 slots nonempty
and 0 events stable after 60 s). That last fix mattered
at once: at round start the coordinator found a stale
press slot left by a concurrent recovery worker's cleanup
run, exactly the hazard it closes.

Open observations, not defects: worker A noted the
passing HUNT-80 check prints a body starting "No
Connection to Gateway" (a transient Perspective reconnect
banner, worth a look by whoever owns the Log page), and
the r11 suite still shows intermittent flakes in steps
the fix did not touch (an export download timeout once,
a staging transient once). HUNT-58 live proof is still
simulation-only: no replacement hit the r4hunt A-to-B
chain during this battery.

VM replacements during the round: about 07:44 UTC and
about 09:25 UTC 2026-11-22, plus one at about 05:45 UTC
just before the round started. Each recovery followed
the proven path (gateway restart, Postgres 16 via the
os-intent replay, role and database creation, DDL,
reseed to 7/101/0, HUNT-53 press guard, 60 s stability
check).

Lab left clean: gateway RUNNING, 7 batches (1042-1048),
101 series, 0 events, defaults restored, PressSlots
empty, ThemeMode System, trial 696 s at close (low, the
watch resets it on expiry). Next HUNT number is HUNT-87.

Held for round 13: HUNT-53 app fix still needs Eric's
direction, lab mitigation stays in effect; timezone TIME
axis retest and HUNT-46 retest stay beta-gated on the
next Ignition beta; Docker boot test stays Eric-side
only; HUNT-58 live proof still rests on the wipe
simulation only.
