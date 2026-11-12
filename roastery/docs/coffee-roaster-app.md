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
| Turning point auto detection | Excluded | Artisan detects the post charge temperature minimum automatically; not reproduced. The derived RoR trace makes the turn visible by eye |
| Four custom event buttons, user named and typed | Implemented | CustomEvent1..4 name and kind members, edited in the Config popup, stamped like standard events |
| Phases (drying, maillard, development) with times, ratios, DTR | Implemented | PhasesBar and Summary compute from the elapsed shadows; verified 6 s phases and 33.3% DTR on a click-through roast |
| AUC statistic | Implemented | Computed by the Save script and stored per log row; values on 18 s test roasts are not meaningful |
| Roast degree from drop temp | Implemented | Map expression to degree names (292 F read Cinnamon in tests) |
| Event sliders (fan, heat, air) | Adapted | SR800 levels are 1..9, so steppers replace 0..100 sliders; every change is timestamped into EventsLog and drawn in the Fan / Heat trace strip |
| Alarms (time, temp, event conditions with actions) | Adapted (lite) | Three alarms as view expressions (high temp with message, drop approach within a delta, first crack watch window) driving a banner; no sounds, no external actions, no alarm driven control moves |
| Background profile | Implemented | Save stores the sampled curve with the log row; View as Background loads it as the Background series with a label chip |
| Profile designer | Adapted (lite) | Target is four editable points interpolated piecewise linearly, not a freehand curve editor; the deviation tile reads against it |
| Roast properties metadata | Implemented | 16 Artisan style fields in grams, bidirectional in the Config popup, shown on the MetaCard |
| Roast log and batch history | Implemented, adapted storage | RoastLog dataset tag plus the /log table page (row select, date rendering); no .alog files and no PDF or HTML report export |
| Roast comparator (multi roast overlays) | Excluded | The single background overlay covers Eric's comparison use; a multi-roast analysis view is a different tool |
| Calculators (loss, blend, moisture) | Adapted | Weight loss percent is computed in the Summary; blend and moisture calculators not reproduced |
| Flavor wheels and cupping profile | Excluded | Cupping is a post roast workflow, outside a roast time console; the Notes field is the capture point |
| Green bean stock and inventory | Excluded | Inventory is a separate system from roast time control and logging |
| Hardware PID output control (pid_dialogs.py) | Excluded | Eric confirmed on 2026-11-11 that his SR800 setup has no PID control and he is glad it is excluded. Manual Fan and Heat levels are his control surface, so the console exposes Fan and Heat steppers only, with no PID anywhere in the design. |
| Device connections incl. WebSocket (comm.py, wsport.py) | Adapted | Modeled by WsUrl plus the probe tag; the lab feed is the simulator, per the honesty note above |
| Sampling and RoR smoothing settings | Adapted | RoRSmoothingSec is the smoothing tau; chart history aggregates at 5 s intervals |
| Artisan simulator mode | Implemented in effect | RoasterSim drives the whole console in the lab, program: charge 200, dry end 300 at 4:00, FC 385 at 8:30, drop 412 at 11:30 on a 690 s cycle |

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
