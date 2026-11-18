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
- RoastPage AlarmBanner/AlarmBannerM,
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
