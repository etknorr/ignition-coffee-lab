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
