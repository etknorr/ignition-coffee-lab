#!/usr/bin/env python3
"""Roastery v4 tag setup for the Maker 2027 gateway.

Changes from the v2 (Artisan) setup:

- RoasterSource UDT: a transport slot with Kind, BeanTempF (the
  transport's live output), Address, WsUrl, BrokerUrl, Topic and
  Connected members. RoastBatch gains a Sources folder holding three
  nested instances (Simulated, WebSocket, Mqtt) plus an ActiveSource
  selector member.
- The canonical CurrentBatch/BeanTempF is now an EXPRESSION tag that
  reads the selected source's BeanTempF, so Main, history and the
  batch save never care which transport is live. The Simulated
  instance overrides its BeanTempF member to the RoasterSim OPC path;
  the WebSocket and Mqtt instances keep memory BeanTempF slots that a
  future engine writes into.
- Tag history for BeanTempF and RateOfRiseF moves from CoreHistorian
  to the SQL historian on the `db` connection (historyProvider 'db').
  CoreHistorian stays defined but unused by these tags.
- The BeanTempF valueChanged event script is a thin call into the
  project scripting library (roastery.core.on_bean_temp); the gateway
  scripting project is Roastery, so tag scripts can import it.
- New Roastery level dataset tag CurveSamples: the library appends a
  curve sample every few seconds while roasting; at save time the
  samples are written to the batch_series table through a named
  query.
- Dataset tags created over REST get String typed columns (every
  cell round trips as text). The library defends against this: it
  builds empty datasets with real column types (typed seed row,
  deleted) and coerces numeric and timestamp cells on read.
- RoastLog dataset tag is recreated (the store moved to Postgres via
  named queries) and its existing rows are restored from
  roastlog-backup.json when that file is present, so the seed
  migration in roastery.batches can read them from the tag.
- Round 9 resync (2026-11-21): the UDT list now matches the live
  gateway exactly (203 members plus the Sources folder, 0
  differences by member diff against a fresh live export). It
  had drifted by two members added after v4 (CompareAlignEvent
  from round 8 HUNT-56, LastActionBatchNumber from round 5
  HUNT-45) and by the old custom event slot 2 to 4 defaults
  (now blank, per the round 6 defaults). The stepped simulator
  program this script generates matches the live RoasterSim
  instructions.csv exactly. This is the setup script the README
  and PACKAGING name for a fresh gateway; do not run it against
  the live lab except for an intended rebuild.

Run with wsvenv python. Destructive to the old Roastery tag tree by
design (lab): the old UDTs and instance are deleted first.
"""
import json, os, sys, time
from api27m import api

DEVICE = 'RoasterSim'
B = '[default]Roastery/CurrentBatch'
LAB = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(LAB, 'roastlog-backup.json')

# ------------------------------------------------------------------ sim
# RoasterSim program: a stepped, one row per second model of a real
# FreshRoast SR800 roast (built 2026-11-17, see the Simulator
# section in docs/coffee-roaster-app.md for the full model notes
# and the simulator capability evidence behind this shape).
#
# Why stepped static values instead of ramp() segments: the
# Programmable Device Simulator has no expression or cross
# reference value sources (proven on a scratch device), and its
# ramp() functions are wall clock anchored, so changing the
# device Base Rate meta node does NOT scale a ramp program (the
# program counter and the segment boundaries scale, the ramp
# progress does not, and the segments jump). Static rows step
# once per program interval, so the Base Rate node IS a clean
# speed control for a stepped program: 500 ms plays the curve at
# twice wall speed, 2000 ms at half. roastery.core uses that to
# let Fan and Heat levels visibly speed and slow the roast, and
# uses the Reset and Pause meta nodes to align the program clock
# with Charge and to hold the preheat plateau while Idle.
#
# The curve (bean probe, F), generated deterministically below:
# - charge at the 392 F preheat plateau (program value at t=0,
#   and the value the program returns to and holds at the end of
#   the cycle, so the loop wrap step is exactly zero);
# - a cosine eased dip to the turning point, 184 F at about
#   71 s (the dip slope is the real one: about minus 180 F/min
#   average, there is no step anywhere in the cycle);
# - drying: RoR about 38 F/min just after the turning point
#   declining to about 28, dry end zone 300 to 310 F crossed at
#   about 4:37 to 5:00;
# - maillard: RoR declining through the teens to about 11,
#   first crack 385 F at about 8:54 (534 s);
# - development: RoR inside 5 to 12 F/min throughout (polish
#   round 2 item 7 retune: measured 6.8 to 11.9 offline with
#   roastery.core.compute_ror_series at the standing RoR
#   parameters, FC Start to Drop; it was 9.1 to 15.5 before),
#   drop point anchor 419 F at 12:00 (720 s), program value
#   415.9 F at the 11:47 (707 s) press point;
# - cooling after the drop point: the probe falls to about
#   343 F, then the empty roaster reheats to the 392 F plateau
#   and holds it to the end of the 1020 s cycle.
# A 9 s moving average rounds the anchor corners, and a seeded
# jitter of plus/minus 0.6 F keeps the line from looking sterile
# (jitter is zero at the charge and wrap samples).
import math as _math
import random as _random

_SIM_RISE = [(72, 184), (110, 208), (150, 232), (190, 255),
             (230, 276), (265, 294), (295, 308), (335, 326),
             (375, 344.5), (415, 353.5), (455, 369), (495, 380),
             (530, 384.5), (558, 389.5), (600, 397.5),
             (642, 404.5), (682, 411), (720, 419)]
_SIM_COOL = [(735, 395), (755, 362), (785, 342), (830, 352),
             (880, 372), (930, 388), (960, 392)]
_SIM_END = 1020


def _sim_base(t):
    if t <= 72:
        return 184.0 + 208.0 * (1.0 + _math.cos(
            _math.pi * t / 72.0)) / 2.0
    pts = _SIM_RISE + _SIM_COOL
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * float(t - t0) / float(t1 - t0)
    return 392.0


def _build_sim_csv():
    raw = [_sim_base(t) for t in range(_SIM_END + 1)]
    sm = []
    for i in range(len(raw)):
        seg = raw[max(0, i - 4):min(len(raw), i + 5)]
        sm.append(sum(seg) / len(seg))
    rng = _random.Random(20261117)
    rows = ['TimeInterval,BrowsePath,ValueSource,DataType']
    for t in range(_SIM_END + 1):
        j = 0.0 if t < 3 or t > _SIM_END - 3 else rng.uniform(
            -0.6, 0.6)
        v = 392.0 if t in (0, _SIM_END) else round(sm[t] + j, 1)
        rows.append('%d,BeanTemp,%.1f,Double' % (t, v))
    return '\n'.join(rows) + '\n'


CSV = _build_sim_csv()

# Thin tag event script: all derivation logic lives in the library.
ROR_SCRIPT = (
    "\timport roastery.core\n"
    "\troastery.core.on_bean_temp(tagPath, currentValue, initialChange)\n")

HIST = {'historyEnabled': True, 'historyProvider': 'db',
        'historySampleMode': 'Periodic', 'historySampleRate': 2,
        'historySampleRateUnits': 'SEC'}

def mem(name, dtype, value, omit_value=False, doc=None):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
         'dataType': dtype}
    if not omit_value:
        t['value'] = value
    if doc:
        t['documentation'] = doc
    return t

def hist_mem(name, dtype, value, doc=None):
    t = mem(name, dtype, value, doc=doc)
    t.update(HIST)
    return t

def event_pair(stem):
    return [mem(stem + 'Time', 'DateTime', None, omit_value=True),
            mem(stem + 'TempF', 'Float8', 0.0)]

# ---------------------------------------------------------------- sources

SOURCE_TYPE = {'name': 'RoasterSource', 'tagType': 'UdtType', 'tags': [
    mem('Kind', 'String', '', doc='Transport kind: Simulated, WebSocket or MQTT.'),
    mem('BeanTempF', 'Float8', 0.0,
        doc='This transport\'s live bean temp output. The canonical '
            'CurrentBatch/BeanTempF expression reads the instance named '
            'by ActiveSource.'),
    mem('Address', 'String', '', doc='Human readable address summary.'),
    mem('WsUrl', 'String', '', doc='WebSocket endpoint (WebSocket source).'),
    mem('BrokerUrl', 'String', '', doc='MQTT broker URL (MQTT source).'),
    mem('Topic', 'String', '', doc='MQTT topic (MQTT source).'),
    mem('Connected', 'Boolean', False,
        doc='Transport liveness, set by whatever populates the source.'),
]}

def source_instance(name, overrides):
    return {'name': name, 'tagType': 'UdtInstance',
            'typeId': 'RoasterSource', 'tags': overrides}

SIMULATED = source_instance('Simulated', [
    {'name': 'Kind', 'value': 'Simulated'},
    {'name': 'BeanTempF', 'valueSource': 'opc',
     'opcServer': 'Ignition OPC UA Server',
     'opcItemPath': f'[{DEVICE}]BeanTemp'},
    {'name': 'Address', 'value': f'[{DEVICE}]BeanTemp'},
    {'name': 'Connected', 'value': True},
])
WEBSOCKET = source_instance('WebSocket', [
    {'name': 'Kind', 'value': 'WebSocket'},
    {'name': 'WsUrl', 'value': 'ws://sr800.local:8080'},
    {'name': 'Address', 'value': 'ws://sr800.local:8080'},
])
MQTT = source_instance('Mqtt', [
    {'name': 'Kind', 'value': 'MQTT'},
    {'name': 'BrokerUrl', 'value': 'mqtt://localhost:1883'},
    {'name': 'Topic', 'value': 'roastery/sr800/temp'},
    {'name': 'Address', 'value': 'mqtt://localhost:1883 roastery/sr800/temp'},
])

BEANTEMP_EXPR = (
    "if({[.]ActiveSource} = 'WebSocket', {[.]Sources/WebSocket/BeanTempF}, "
    "if({[.]ActiveSource} = 'Mqtt', {[.]Sources/Mqtt/BeanTempF}, "
    "{[.]Sources/Simulated/BeanTempF}))")

# Default alarm table (Tier 1 item 6): the three former lite
# alarms carried into the new definitions format. The drop
# approach value is the default target drop temp (415) minus the
# old 5 F delta; the FC watch latches as a message at the old
# window start (target FC 510 minus the 90 s window).
ALARM_DEFS_JSON = json.dumps([
    {'name': 'High bean temp', 'enabled': True, 'guard': 'None',
     'offsetSec': 0, 'source': 'BT', 'cond': '>=', 'value': 430,
     'message': 'Bean temperature high', 'action': 'Banner'},
    {'name': 'Drop approaching', 'enabled': True, 'guard': 'None',
     'offsetSec': 0, 'source': 'BT', 'cond': '>=', 'value': 410,
     'message': 'Drop approaching', 'action': 'Banner'},
    {'name': 'First crack watch', 'enabled': True, 'guard': 'Charge',
     'offsetSec': 420, 'source': 'Time', 'cond': '>=', 'value': 420,
     'message': 'First crack watch: listen for cracks',
     'action': 'Message'},
])

MEMBERS = [
    # canonical probe value, driven by the selected source (see above)
    {'name': 'BeanTempF', 'tagType': 'AtomicTag', 'valueSource': 'expr',
     'dataType': 'Float8', 'expression': BEANTEMP_EXPR,
     'documentation': 'Canonical bean temp: the BeanTempF of the source '
                      'named by ActiveSource. History on the SQL '
                      'historian (db). Its valueChanged script calls '
                      'roastery.core.on_bean_temp for RoR derivation '
                      'and curve sampling.',
     'eventScripts': [{'eventid': 'valueChanged', 'script': ROR_SCRIPT}],
     **HIST},
    hist_mem('RateOfRiseF', 'Float8', 0.0,
             doc='Derived from BeanTempF by roastery.core.on_bean_temp '
                 'using the Artisan RoR parameterization (delta span, '
                 'curve filter, delta filter tags). The same library '
                 'calculation produces the live value, the saved '
                 'batch RoR and ghost RoR. No RoR probe on an SR800.'),
    mem('_RoRPrevTempF', 'Float8', 0.0),
    mem('_RoRPrevMs', 'Int8', 0),
    # source selection
    mem('ActiveSource', 'String', 'Simulated',
        doc='Which Sources instance drives BeanTempF: Simulated, '
            'WebSocket or Mqtt.'),
    {'name': 'Sources', 'tagType': 'Folder',
     'tags': [SIMULATED, WEBSOCKET, MQTT]},
    # controls (SR800 steppers)
    mem('FanLevel', 'Int4', 5, doc='SR800 fan level, 1 to 9.'),
    mem('HeatLevel', 'Int4', 5, doc='SR800 heat level, 1 to 9.'),
    mem('Mode', 'String', 'Off', doc='Roaster mode: Off, Roast, Cool.'),
    # state
    mem('State', 'String', 'Idle',
        doc='Idle, Roasting, Dropped, Cooling, Complete.'),
    mem('StartTime', 'DateTime', None, omit_value=True),
]
for stem in ('Charge', 'DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
             'SecondCrackStart', 'SecondCrackEnd', 'Drop'):
    MEMBERS += event_pair(stem)
for stem in ('DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
             'SecondCrackStart', 'SecondCrackEnd', 'Drop'):
    MEMBERS.append(mem(stem + 'ElapsedSec', 'Int4', -1))
MEMBERS += [
    # batch metadata (Artisan Roast Properties model)
    mem('BatchNumber', 'Int4', 1042),
    mem('BeanName', 'String', 'Ethiopia Guji'),
    mem('Origin', 'String', 'Guji, Ethiopia'),
    mem('Region', 'String', 'Guji Zone'),
    mem('Farm', 'String', 'Buku Abel'),
    mem('Altitude', 'String', '2000 to 2200 masl'),
    mem('Variety', 'String', 'Heirloom'),
    mem('Process', 'String', 'Washed'),
    mem('HarvestYear', 'Int4', 2025),
    mem('MoisturePct', 'Float8', 10.5),
    mem('DensityGL', 'Float8', 680.0),
    mem('ChargeWeightG', 'Float8', 200.0,
        doc='Green coffee charged, grams (SR800 home scale).'),
    mem('WeightOutG', 'Float8', 0.0, doc='Roasted weight out, grams.'),
    mem('RoastLevel', 'String', 'City+'),
    mem('OperatorName', 'String', 'Eric'),
    mem('Notes', 'String', ''),
    mem('TargetDropTempF', 'Float8', 415.0),
    # target profile designer points (charge point is elapsed 0)
    mem('TargetChargeTempF', 'Float8', 200.0),
    mem('TargetDryEndSec', 'Int4', 240),
    mem('TargetDryEndTempF', 'Float8', 300.0),
    mem('TargetFCSec', 'Int4', 510),
    mem('TargetFCTempF', 'Float8', 385.0),
    mem('TargetDropSec', 'Int4', 630),
    # ---- Tier 3 item 17: full profile designer for the target plan ----
    mem('TargetPlanJson', 'String', '',
        doc='Tier 3 item 17: the target plan as a JSON list of '
            '[sec, tempF] pairs, written by the Settings Targets '
            'designer through roastery.core.set_target_plan. '
            'Empty means the plan is the legacy four points '
            'above (the default list). The plan line and the '
            'deviation tile read it through '
            'roastery.core.target_plan_points.'),
    mem('PlanDeviationText', 'String', '--',
        doc='Tier 3 item 17: live BT minus the target plan at '
            'the elapsed seconds, published by '
            'roastery.core.update_plan_deviation for the '
            'deviation tile. Two dashes outside a roast.'),
    # alarms (lite)
    mem('AlarmHighTempEnabled', 'Boolean', True),
    mem('AlarmHighTempF', 'Float8', 430.0),
    mem('AlarmHighTempMsg', 'String', 'Bean temperature high'),
    mem('AlarmDropEnabled', 'Boolean', True),
    mem('AlarmDropDeltaF', 'Float8', 5.0),
    mem('AlarmFCWatchEnabled', 'Boolean', True),
    mem('AlarmFCWindowSec', 'Int4', 90),
    # ---- Tier 1 (2026-11-17): Roast Properties completeness ----
    # The extended Artisan Roast Properties set. These are batch
    # metadata like the members above (core.FORM_MEMBERS carries
    # them into the form, the document and the .alog mapping).
    mem('RoastTitle', 'String', ''),
    mem('RoasterType', 'String', 'FreshRoast SR800'),
    mem('RoasterSizeKg', 'Float8', 0.25),
    mem('RoasterHeating', 'Int4', 0,
        doc='Artisan roasterheating code (0 is electric).'),
    mem('Organization', 'String', ''),
    mem('VolumeInMl', 'Float8', 0.0, doc='Green volume in, millilitres.'),
    mem('VolumeOutMl', 'Float8', 0.0,
        doc='Roasted volume out, millilitres.'),
    mem('DefectsWeightG', 'Float8', 0.0,
        doc='Defects picked out, grams.'),
    mem('RoastedDensityGL', 'Float8', 0.0,
        doc='Roasted density, grams per litre.'),
    mem('BeanSizeMinMm', 'Float8', 0.0),
    mem('BeanSizeMaxMm', 'Float8', 0.0),
    mem('DefectHeavyFC', 'Boolean', False),
    mem('DefectLowFC', 'Boolean', False),
    mem('DefectLightCut', 'Boolean', False),
    mem('DefectDarkCut', 'Boolean', False),
    mem('DefectDrops', 'Boolean', False),
    mem('DefectOily', 'Boolean', False),
    mem('DefectUneven', 'Boolean', False),
    mem('DefectTipping', 'Boolean', False),
    mem('DefectScorching', 'Boolean', False),
    mem('DefectDivots', 'Boolean', False),
    mem('WholeColor', 'Float8', 0.0, doc='Whole bean color reading.'),
    mem('GroundColor', 'Float8', 0.0, doc='Ground bean color reading.'),
    mem('ColorSystem', 'String', '',
        doc='Color reading system (for example Agtron).'),
    mem('AmbientTempF', 'Float8', 0.0),
    mem('AmbientHumidityPct', 'Float8', 0.0),
    mem('AmbientPressureHPa', 'Float8', 0.0),
    mem('RoastedMoisturePct', 'Float8', 0.0),
    mem('GreensTempF', 'Float8', 0.0),
    mem('CuppingNotes', 'String', ''),
    # ---- Tier 1: live turning point (roastery.core) ----
    mem('TurningPointElapsedSec', 'Int4', -1,
        doc='Live turning point: seconds since charge of the bean '
            'temp minimum after charge, once the curve has risen '
            'clear of it. -1 until detected.'),
    mem('TurningPointTempF', 'Float8', 0.0),
    mem('_TpMinTempF', 'Float8', 0.0,
        doc='Scratch: running bean temp minimum since charge.'),
    mem('_TpMinElapsedSec', 'Int4', -1),
    # ---- Tier 1: live AUC (Artisan settings shape) ----
    mem('AucBegin', 'String', 'TP',
        doc='AUC begin event: Charge, TP, Dry End or FC Start '
            '(Artisan AUCbegin, default TP).'),
    mem('AucBaseTempF', 'Float8', 212.0,
        doc='AUC base temperature (Artisan AUCbase, default 212 F).'),
    mem('AucBaseFromEvent', 'Boolean', False,
        doc='Artisan AUCbaseFlag: take the base from the bean temp '
            'at the begin event instead of AucBaseTempF.'),
    mem('AucTargetFMin', 'Float8', 1152.0,
        doc='AUC target in F min (Artisan AUCtarget 640 is in '
            'C min; Roastery works in F throughout).'),
    mem('AucGuideEnabled', 'Boolean', True,
        doc='Artisan AUCguideFlag: predict when the target AUC is '
            'reached at the current RoR.'),
    mem('AucLiveFMin', 'Float8', 0.0,
        doc='Live AUC from the begin event, F min.'),
    mem('AucSinceFcFMin', 'Float8', 0.0,
        doc='Live AUC accumulated since FC Start, F min.'),
    mem('AucGuideElapsedSec', 'Int4', -1,
        doc='Predicted elapsed seconds when the AUC target is '
            'reached; -1 when no prediction applies.'),
    # ---- Tier 2: BT projection + background deviation ----
    mem('ProjectionEnabled', 'Boolean', True,
        doc='Tier 2 item 9: show the BT projection series on the '
            'live chart (roastery.core.projection_points).'),
    mem('ProjectionMode', 'String', 'Linear',
        doc='Projection mode: Linear (current RoR) or Quadratic '
            '(linear RoR trend, after five minutes elapsed).'),
    mem('BgDeviationText', 'String', '--',
        doc='Tier 2 item 10: live BT minus the staged background '
            'BT at the same elapsed time, written by '
            'roastery.core.update_bg_deviation.'),
    # ---- Tier 2 items 11 to 14 (2026-11-17) ----
    mem('PlaybackEnabled', 'Boolean', True,
        doc='Tier 2 item 11: background playback prompts on. '
            'Prompts only; Fan and Heat stay manual.'),
    mem('PlaybackSound', 'Boolean', False,
        doc='Tier 2 item 11: beep with playback prompts. Stored '
            'setting; Perspective has no clean client beep API '
            'in this build, so prompts are visual only.'),
    mem('PlaybackText', 'String', '',
        doc='Current background playback prompt, written by '
            'roastery.core.evaluate_playback.'),
    mem('PlaybackActive', 'Boolean', False),
    mem('_PlaybackFiredJson', 'String', '',
        doc='Scratch: indexes of ghost playback events already '
            'prompted this roast (JSON list).'),
    mem('DisplaySmoothing', 'Int4', 0,
        doc='Tier 2 item 12: display only smoothing level for '
            'the BT line in LiveCurveDS (0 off, 1 to 5). Stored '
            'temps and RoR are never smoothed.'),
    # ---- Tier 3 items 15 and 16 (2026-11-17) ----
    mem('DispBtWidth', 'Int4', 3,
        doc='Tier 3 item 15: bean temp line width on the live '
            'chart (Settings Display; binds onto the canvas '
            'series line width). Default 3 is the fixed look '
            'from before Tier 3.'),
    mem('DispBtStyle', 'String', 'solid',
        doc='Tier 3 item 15: bean temp line style (solid, '
            'dashed or dotted).'),
    mem('DispRorWidth', 'Int4', 2,
        doc='Tier 3 item 15: rate of rise line width.'),
    mem('DispRorStyle', 'String', 'solid',
        doc='Tier 3 item 15: rate of rise line style.'),
    mem('DispGhostWidth', 'Int4', 2,
        doc='Tier 3 item 15: ghost (background) line width, '
            'applies to the ghost BT and ghost RoR series.'),
    mem('DispGhostStyle', 'String', 'solid',
        doc='Tier 3 item 15: ghost line style.'),
    mem('DispRorFill', 'Boolean', False,
        doc='Tier 3 item 15: fill under the RoR curve on the '
            'live chart (series area opacity 0.22 when on).'),
    mem('DispMarkerSize', 'Int4', 4,
        doc='Tier 3 item 15: event marker size (the reference '
            'line endpoint size on the bean series).'),
    mem('DispAxisFormat', 'String', 'm:ss',
        doc='Polish round 3 (HUNT-23): time axis label '
            'format on every roast chart, m:ss (Artisan '
            'style) or mm:ss. The charts run on a category '
            'axis whose names roastery.core.axis_label '
            'formats from this member, so the labels are '
            'true elapsed in any browser timezone.'),
    mem('PhaseFromBg', 'Boolean', False,
        doc='Tier 3 item 16: when on, the phase bar and the '
            'chart phase bands follow the staged ghost phase '
            'boundaries (BgPhase tags) instead of the saved '
            'phase targets. Saved targets are never '
            'overwritten by this option.'),
    mem('BgPhaseDrySec', 'Int4', -1,
        doc='Tier 3 item 16: staged ghost dry end, elapsed '
            'seconds since its charge; -1 when no ghost '
            'phases are staged. Written by both ghost routes '
            'through roastery.core.stage_bg_phases and '
            'cleared with the ghost.'),
    mem('BgPhaseFcSec', 'Int4', -1,
        doc='Tier 3 item 16: staged ghost FC start, elapsed '
            'seconds.'),
    mem('BgPhaseDropSec', 'Int4', -1,
        doc='Tier 3 item 16: staged ghost drop, elapsed '
            'seconds.'),
    mem('SuggestDryEndEnabled', 'Boolean', True,
        doc='Tier 2 item 14: suggest Dry End when BT crosses '
            'TargetDryEndTempF. Suggestion only.'),
    mem('SuggestFcEnabled', 'Boolean', True,
        doc='Tier 2 item 14: suggest FC Start when BT crosses '
            'TargetFCTempF. Suggestion only.'),
    mem('SuggestionText', 'String', '',
        doc='Current auto event suggestion, written by '
            'roastery.core.evaluate_suggestions.'),
    mem('SuggestionActive', 'Boolean', False),
    mem('SuggestionKind', 'String', '',
        doc='Which event the live suggestion names: DryEnd or '
            'FCStart.'),
    mem('_DrySuggested', 'Boolean', False,
        doc='Scratch: Dry End already suggested this roast.'),
    mem('_FcSuggested', 'Boolean', False,
        doc='Scratch: FC Start already suggested this roast.'),
    mem('AnalyzerSec', 'Int4', -1,
        doc='Tier 2 item 13: analyzer selected elapsed seconds '
            'on the live chart; -1 follows the latest sample.'),
    mem('AnalyzerTimeText', 'String', '--:--'),
    mem('AnalyzerBtText', 'String', '--'),
    mem('AnalyzerRorText', 'String', '--'),
    mem('AnalyzerBgText', 'String', '--'),
    mem('AnalyzerDevText', 'String', '--'),
    mem('AnalyzerBtF', 'Float8', 0.0),
    mem('AnalyzerRorF', 'Float8', 0.0),
    mem('AnalyzerBgF', 'Float8', 0.0),
    mem('AnalyzerDevF', 'Float8', 0.0),
    mem('AnalyzerHasBg', 'Boolean', False),
    # ---- Tier 1: full alarm table (replaces the lite alarms) ----
    mem('AlarmDefsJson', 'String', ALARM_DEFS_JSON,
        doc='Alarm definitions (JSON list) evaluated by '
            'roastery.core.evaluate_alarms. Fields: name, enabled, '
            'guard (None, Charge, TP, Dry End, FC Start, FC End, '
            'SC Start, SC End, Drop), offsetSec, source (BT, RoR, '
            'Time), cond (>= or <=), value, message, action '
            '(Banner or Message).'),
    mem('AlarmText', 'String', '',
        doc='Current alarm banner text, written by '
            'roastery.core.evaluate_alarms.'),
    mem('AlarmMessageText', 'String', '',
        doc='Polish phase 3: the most recently latched Message '
            'alarm text, written by roastery.core.evaluate_alarms '
            'only when a Message alarm newly latches. The Roast '
            'page binds a custom prop to it and toasts the new '
            'value once per latch through Periscope.'),
    mem('AlarmMessageSeq', 'Int4', 0,
        doc='Polish phase 4 (HUNT-19): latch sequence counter, '
            'incremented by roastery.core.evaluate_alarms on '
            'every new Message latch batch. The Roast page '
            'watches this counter (not the message text) to '
            'fire its toast, so two latches carrying identical '
            'message text still toast once each.'),
    mem('AlarmActive', 'Boolean', False),
    mem('_AlarmFiredJson', 'String', '',
        doc='Scratch: indexes of Message alarms already latched '
            'this roast (JSON list).'),
    # config
    mem('WsUrl', 'String', 'ws://sr800.local:8080',
        doc='SR800 WebSocket endpoint (placeholder). Mirrored into '
            'Sources/WebSocket/WsUrl by the config form submit.'),
    mem('RoRSmoothingSec', 'Int4', 30,
        doc='DEPRECATED in v4: the v3 EMA time constant. RoR is now '
            'computed with the Artisan parameterization below; this '
            'member is kept only so old references do not break.'),
    # ---- v4: Artisan RoR parameterization (see roastery.core) ----
    mem('RoRDeltaSpanSec', 'Int4', 20,
        doc='Artisan DeltaSpan: seconds of bean temp history one RoR '
            'value spans. Artisan default 20, UI range 0 to 30.'),
    mem('RoRCurveFilter', 'Int4', 1,
        doc='Artisan curvefilter (UI value 0 to 5, default 1): bean '
            'temp smoothing before differentiation. Internal window '
            'is 2x+1 with linear decay weights.'),
    mem('RoRDeltaFilter', 'Int4', 3,
        doc='Artisan deltafilter (UI value 0 to 40, default 3): RoR '
            'smoothing after differentiation. Internal value 2x+1; '
            'decay weights run to round(internal/2).'),
    mem('RoRSmoothSpikes', 'Boolean', True,
        doc='Artisan filterDropOuts (Smooth Spikes, default on): '
            'median filter k=5 on temps and k=3 on RoR in the '
            'offline recompute path (saved batches, ghosts).'),
    mem('RoRPolyfit', 'Boolean', False,
        doc='Artisan polyfitRoRcalc: least squares slope over the '
            'delta span instead of the two point difference.'),
    mem('RoROptimalSmoothing', 'Boolean', False,
        doc='Artisan optimalSmoothing (needs polyfit): Hanning '
            'smoothing offline, Savitzky-Golay derivative for RoR.'),
    mem('RoRClipLowF', 'Float8', -18.0,
        doc='Artisan RoRlimitm: offline RoR below this is dropped.'),
    mem('RoRClipHighF', 'Float8', 81.0,
        doc='Artisan RoRlimit: offline RoR above this is dropped.'),
    mem('_RoRLiveJson', 'String', '',
        doc='Live RoR scratch buffer (JSON): recent bean temp '
            'samples and raw RoR values for roastery.core.'),
    # ---- v4: phase bar targets (durations, not event times) ----
    mem('PhaseDryTargetSec', 'Int4', 270,
        doc='Phase bar target: drying phase duration, seconds.'),
    mem('PhaseMaillardTargetSec', 'Int4', 210,
        doc='Phase bar target: maillard phase duration, seconds.'),
    mem('PhaseDevTargetSec', 'Int4', 150,
        doc='Phase bar target: development phase duration, seconds.'),
    mem('DTRTargetPct', 'Float8', 20.0,
        doc='Phase bar target: development time ratio, percent.'),
    # ---- v4: button press capture surface (transaction groups) ----
    mem('ActionCounter', 'Int8', 0,
        doc='Monotonically increasing press counter. Every control '
            'button press increments it (roastery.core.record_press); '
            'a SQLBridge group triggers on its change.'),
    mem('LastAction', 'String', '',
        doc='Name of the last control action pressed.'),
    mem('LastActionElapsedSec', 'Int4', -1,
        doc='Seconds since charge at the last press.'),
    mem('LastActionAt', 'DateTime', None, omit_value=True,
        doc='Wall clock time of the last press.'),
    mem('LastActionBatchNumber', 'Int4', 1042, doc='Batch number at the last press, stamped by roastery.core.record_press. The PressEvents group reads this instead of the live BatchNumber, so a press is recorded against the batch it belonged to even when the batch number changes before the group executes (polish round 5, HUNT-45).'),
    mem('PressCaptureMode', 'String', 'Group',
        doc='Who writes batch_events rows: Library (named query) '
            'or Group (SQLBridge transaction group). Default is '
            'Group since 2026-11-17: the PressEvents transaction '
            'group is authored and RUNNING on the lab gateway.'),
    mem('SimSeekTargetSec', 'Int4', -1,
        doc='Polish round 3 (HUNT-22): the program second the '
            'cooling seek is fast forwarding to, or -1 when no '
            'seek is armed. Written by roastery.core.'
            'sim_seek_cooling (the starter) and consumed by '
            'sim_seek_advance on each BeanTempF change, so the '
            'seek never blocks a press handler.'),
    mem('SimSeeking', 'Boolean', False,
        doc='Polish round 3 (HUNT-22): True while '
            'roastery.core.sim_seek_cooling fast forwards the '
            'simulator program after a Drop. While set, the '
            'BeanTempF change pipeline stays muted (the ticks '
            'are fast forward artifacts, and their render flood '
            'is the window in which dock clicks were lost). '
            'Read with a staleness expiry, so an interrupted '
            'seek can never mute the pipeline for good.'),
    mem('SeriesCaptureMode', 'String', 'Library',
        doc='Who writes batch_series rows: Library (CurveSamples '
            'at save) or Group (transaction group, live).'),
    # Polish round 8 (HUNT-56): compare alignment event, after
    # Artisan 5.0.0 alignEvent. Added in the round 9 resync; the
    # live UDT gained it in round 8 and this script had not.
    mem('CompareAlignEvent', 'String', 'charge', doc='Polish round 8 (HUNT-56): compare alignment event, after Artisan 5.0.0 alignEvent. Stored keys: charge, dryEnd, fcStart, fcEnd, scStart, scEnd, drop (Artisan labels CHARGE, DRY, FCs, FCe, SCs, SCe, DROP). roastery.batches.build_compare shifts every compared curve so the chosen event lands on the same 30 s grid step, slot A as the reference; a batch missing the event falls back to its charge. Bound in Settings Display and on the Log compare row, one tag for both.'),
]
for i, (nm, kind) in enumerate([('Fan Boost', 'Airflow'),
                                ('', ''),
                                ('', ''),
                                ('', '')], start=1):
    MEMBERS += [
        mem(f'CustomEvent{i}Name', 'String', nm),
        mem(f'CustomEvent{i}Kind', 'String', kind),
        mem(f'CustomEvent{i}Time', 'DateTime', None, omit_value=True),
        mem(f'CustomEvent{i}TempF', 'Float8', 0.0),
        mem(f'CustomEvent{i}ElapsedSec', 'Int4', -1),
        # Polish round 1 item 7: a disabled custom leaves the
        # phase aware dock list, and roastery.core.stamp_custom
        # refuses to stamp it.
        mem(f'CustomEvent{i}Enabled', 'Boolean', True,
            doc='Polish round 1 item 7: whether this custom '
                'event can be stamped (dock list and the '
                'library stamp guard both honor it).'),
    ]

# ---- Polish round 1 display texts (2026-11-17) ----
# Library published texts the HUD and the Roast page bind to
# (roastery.core ror_display_text, phase_label, stats_line_text).
MEMBERS += [
    mem('RateOfRiseDisplayText', 'String', '--',
        doc='Polish round 1 item 4: HUD RoR reading under the '
            'Artisan display convention, written by '
            'roastery.core.update_ror_display. The RateOfRiseF '
            'tag always keeps the true computed value.'),
    mem('PhaseLabel', 'String', 'Pre-charge',
        doc='Polish round 1 item 6: current roast phase, '
            'written by roastery.core.update_phase_label from '
            'State plus the stamped events in roast order.'),
    mem('DockActionsJson', 'String', '[]',
        doc='Polish phase 2 item 1: the phase aware dock set '
            'as a JSON list of descriptors, written by '
            'roastery.core.update_dock_actions; the dock '
            'views bind it instead of calling scripts.'),
    mem('StatsLineText', 'String',
        'Dry --:-- -- \u00b7 Mai --:-- -- \u00b7 Dev --:-- -- '
        '\u00b7 DTR --',
        doc='Polish round 1 item 5: the Roast page stats line, '
            'written by roastery.core.update_stats_line; '
            'durations and percentages always describe the '
            'same phases.'),
]

UDT = {'name': 'RoastBatch', 'tagType': 'UdtType', 'tags': MEMBERS}

def ds_tag(name):
    return {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
            'dataType': 'DataSet'}

INSTANCE_FOLDER = {'name': 'Roastery', 'tagType': 'Folder', 'tags': [
    {'name': 'CurrentBatch', 'tagType': 'UdtInstance', 'typeId': 'RoastBatch'},
    # ---- simulator meta controls (lab only, like RoasterSim) ----
    # OPC tags onto the RoasterSim device's [Controls] meta nodes.
    # roastery.core writes these (Simulated source only) to align
    # the program clock with Charge (Reset), hold the preheat
    # plateau while Idle (Pause) and scale the program speed with
    # the Fan and Heat levels (BaseRate). See the sim notes at
    # the CSV generator above.
    {'name': 'SimReset', 'tagType': 'AtomicTag', 'valueSource': 'opc',
     'dataType': 'Boolean', 'opcServer': 'Ignition OPC UA Server',
     'opcItemPath': f'[{DEVICE}][Controls]/reset',
     'documentation': 'RoasterSim meta node: writing True restarts '
                      'the simulator program at interval 0 (the '
                      'node clears itself back to False).'},
    {'name': 'SimPause', 'tagType': 'AtomicTag', 'valueSource': 'opc',
     'dataType': 'Boolean', 'opcServer': 'Ignition OPC UA Server',
     'opcItemPath': f'[{DEVICE}][Controls]/pause',
     'documentation': 'RoasterSim meta node: True freezes the '
                      'simulator program at its current interval.'},
    {'name': 'SimBaseRate', 'tagType': 'AtomicTag', 'valueSource': 'opc',
     'dataType': 'Int4', 'opcServer': 'Ignition OPC UA Server',
     'opcItemPath': f'[{DEVICE}][Controls]/baseRateNode',
     'documentation': 'RoasterSim meta node: milliseconds per '
                      'program interval. 1000 is real time for '
                      'the stepped BeanTemp program; lower plays '
                      'the curve faster, higher slower.'},
    {'name': 'SimProgramCounter', 'tagType': 'AtomicTag',
     'valueSource': 'opc', 'dataType': 'Int4',
     'opcServer': 'Ignition OPC UA Server',
     'opcItemPath': f'[{DEVICE}][Controls]/programCounter',
     'documentation': 'RoasterSim meta node: the program interval '
                      'currently executing (seconds into the '
                      'stepped curve at the 1000 ms base rate).'},
    # ---- Polish phase 2 item 7: app settings ----
    {'name': 'AppSettings', 'tagType': 'Folder', 'tags': [
        mem('ThemeMode', 'String', 'System',
            doc='Roastery theme choice: System (follows the '
                'device via the roastsystem theme), Light or '
                'Dark. Written from Views/AppSettings through '
                'roastery.core.set_theme_mode.'),
        mem('PeriscopeAvailable', 'Boolean', False,
            doc='Polish phase 3: True only when the Embr '
                'Periscope module is installed and running on '
                'the gateway. roastery.core.show_toast no-ops '
                'while this is False, so a gateway without the '
                'module behaves exactly as before. Set True by '
                'hand after the module is verified on the '
                'gateway Modules page; never set by the app.'),
    ]},
    ds_tag('EventsLog'), ds_tag('RoastLog'),
    ds_tag('TargetProfileDS'), ds_tag('BackgroundDS'),
    ds_tag('CurveSamples'),
    # ---- Polish round 3 (HUNT-22): press capture ring ----
    # Sixteen memory slots; every press writes its context
    # into slot (ActionCounter mod 16) with a single tag
    # write, so concurrent press handlers cannot overwrite
    # each other. roastery.core.reconcile_press_pending
    # verifies each slotted press against batch_events and
    # inserts any the PressEvents group missed.
    {'name': 'PressSlots', 'tagType': 'Folder', 'tags': [
        mem('Slot%02d' % i, 'String', '') for i in range(16)]},
    # ---- Tier 3 item 20: between batch protocol staging ----
    # The BBP window samples (t_offset_sec is float seconds
    # since the previous DROP) live in their own dataset tag
    # and the staged metrics in the Bbp folder, outside the
    # batch workspace, so the window survives Save Batch.
    # Reset discards the window (roastery.core._bbp_clear_all).
    ds_tag('BbpSamplesDS'),
    {'name': 'Bbp', 'tagType': 'Folder', 'tags': [
        mem('WindowActive', 'Boolean', False,
            doc='A between batch window is open (DROP staged, '
                'next CHARGE not yet seen).'),
        mem('DropMs', 'Float8', 0.0,
            doc='Epoch milliseconds of the DROP that opened '
                'the window (float, so no Int4 overflow).'),
        mem('HasMetrics', 'Boolean', False,
            doc='Metrics were finalized at a CHARGE and are '
                'staged for the next batch document.'),
        mem('TimeSec', 'Float8', 0.0),
        mem('BottomTempF', 'Float8', 0.0),
        mem('BottomSec', 'Float8', 0.0),
        mem('RorInFMin', 'Float8', 0.0),
        mem('RorOutFMin', 'Float8', 0.0),
        mem('SampleCount', 'Int4', 0),
    ]},
    # ---- Tier 3 item 17: target plan editor staging ----
    {'name': 'TargetEditor', 'tagType': 'Folder', 'tags': [
        mem('Idx', 'Int4', 0),
        mem('TimeSec', 'Int4', 0),
        mem('TempF', 'Float8', 0.0),
    ]},
    mem('BackgroundCurveJson', 'String', ''),
    mem('BackgroundLabel', 'String', ''),
    mem('BackgroundDropSec', 'Float8', -1.0,
        doc='Drop elapsed seconds of the staged background '
            'profile, for the BT similarity alignment '
            '(roastery.batches.bt_similarity). -1 when none.'),
    mem('BackgroundEventsJson', 'String', '',
        doc='Tier 2 item 11: playback events of the staged '
            'background (JSON list of {t, kind, level}), '
            'written by both ghost staging routes and read by '
            'roastery.core.evaluate_playback.'),
    # ---- Tier 2 item 13: BatchDetail analyzer staging ----
    {'name': 'DetailAnalyzer', 'tagType': 'Folder', 'tags': [
        mem('Sec', 'Int4', -1),
        mem('TimeText', 'String', '--:--'),
        mem('BtText', 'String', '--'),
        mem('RorText', 'String', '--'),
        mem('BgText', 'String', '--'),
        mem('DevText', 'String', '--'),
        mem('BtF', 'Float8', 0.0),
        mem('RorF', 'Float8', 0.0),
        mem('BgF', 'Float8', 0.0),
        mem('DevF', 'Float8', 0.0),
        mem('HasBg', 'Boolean', False),
    ]},
    # ---- v4 additions ----
    ds_tag('EventMarksDS'),
    ds_tag('BackgroundRorDS'),
    # ---- v4.1: the chart's live curve dataset (elapsed axis) ----
    ds_tag('LiveCurveDS'),
    ds_tag('DetailDS'), ds_tag('DetailMarksDS'),
    mem('SelectedBatchNumber', 'Int4', 0,
        doc='Batch selected in the Log UI: detail view, slide over '
            'editor and ghost actions all read this.'),
    mem('EditorCreateMode', 'Boolean', False,
        doc='Slide over editor mode: True creates a manual batch.'),
    mem('DetailDocJson', 'String', '',
        doc='Staged batch document (JSON) for the detail view.'),
    # ---- Tier 3 item 21: yield and conversion calculator ----
    # Inputs are memory tags; the readouts are expression tags,
    # so the math (expected out from charge and loss percent,
    # loss percent from charge and out, F/C and g/oz) updates
    # live as the bidirectional tag bound inputs on BatchDetail
    # are edited. Added live on the gateway by a folder import
    # at Roastery/Calculator; this entry keeps a full tag
    # rebuild equivalent.
    {'name': 'Calculator', 'tagType': 'Folder', 'tags': [
        mem('ChargeG', 'Float8', 200.0),
        mem('LossPct', 'Float8', 15.0),
        {'name': 'ExpectedOutG', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '{[.]ChargeG} * (1 - {[.]LossPct} / 100.0)'},
        {'name': 'ExpectedOutOz', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '{[.]ExpectedOutG} / 28.349523125'},
        mem('OutG', 'Float8', 170.0),
        {'name': 'ActualLossPct', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': 'if({[.]ChargeG} > 0, ({[.]ChargeG} - {[.]OutG}) * 100.0 / {[.]ChargeG}, 0)'},
        mem('TempF', 'Float8', 415.0),
        {'name': 'TempC', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '({[.]TempF} - 32) * 5.0 / 9.0'},
        mem('TempCIn', 'Float8', 200.0),
        {'name': 'TempFOut', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '{[.]TempCIn} * 9.0 / 5.0 + 32'},
        mem('ConvG', 'Float8', 200.0),
        {'name': 'ConvOz', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '{[.]ConvG} / 28.349523125'},
        mem('ConvOzIn', 'Float8', 7.0),
        {'name': 'ConvGOut', 'tagType': 'AtomicTag',
         'valueSource': 'expr', 'dataType': 'Float8',
         'expression': '{[.]ConvOzIn} * 28.349523125'},
    ]},
    # ---- Tier 1: alarm editor staging (tag bound editor fields;
    # view.custom property bindings do not write user edits back
    # in this build, tags are the proven bidirectional path) ----
    {'name': 'AlarmEditor', 'tagType': 'Folder', 'tags': [
        mem('Idx', 'Int4', 0),
        mem('Name', 'String', ''),
        mem('Message', 'String', ''),
        mem('Enabled', 'Boolean', True),
        mem('Guard', 'String', 'None'),
        mem('OffsetSec', 'Int4', 0),
        mem('Source', 'String', 'BT'),
        mem('Cond', 'String', '>='),
        mem('Value', 'Float8', 0.0),
        mem('Action', 'String', 'Banner'),
    ]},
]}

def ds_json(cols, rows):
    return json.dumps({'columns': [{'name': n, 'type': t} for n, t in cols],
                       'rows': rows})

EVENTSLOG_COLS = [('t_stamp', 'java.util.Date'), ('elapsedSec', 'java.lang.Double'),
                  ('kind', 'java.lang.String'), ('label', 'java.lang.String'),
                  ('tempF', 'java.lang.Double'), ('fan', 'java.lang.Double'),
                  ('heat', 'java.lang.Double')]
ROASTLOG_COLS = [('batch', 'java.lang.Integer'), ('roastDate', 'java.util.Date'),
                 ('bean', 'java.lang.String'), ('origin', 'java.lang.String'),
                 ('chargeG', 'java.lang.Double'), ('dropTempF', 'java.lang.Double'),
                 ('totalSec', 'java.lang.Double'), ('drySec', 'java.lang.Double'),
                 ('maillardSec', 'java.lang.Double'), ('devSec', 'java.lang.Double'),
                 ('dtrPct', 'java.lang.Double'), ('weightLossPct', 'java.lang.Double'),
                 ('auc', 'java.lang.Double'),
                 ('level', 'java.lang.String'), ('curveJson', 'java.lang.String')]
TARGETDS_COLS = [('t_stamp', 'java.util.Date'), ('plan', 'java.lang.Double')]
BGDS_COLS = [('t_stamp', 'java.util.Date'), ('bg', 'java.lang.Double')]
CURVE_COLS = [('t_offset_sec', 'java.lang.Double'), ('t_stamp', 'java.util.Date'),
              ('bean_temp_f', 'java.lang.Double'), ('rate_of_rise_f', 'java.lang.Double'),
              ('fan_level', 'java.lang.Integer'), ('heat_level', 'java.lang.Integer')]
MARKS_COLS = [('t_stamp', 'java.util.Date'),
              ('charge', 'java.lang.Double'),
              ('dryEnd', 'java.lang.Double'),
              ('fcStart', 'java.lang.Double'),
              ('fcEnd', 'java.lang.Double'),
              ('scStart', 'java.lang.Double'),
              ('scEnd', 'java.lang.Double'),
              ('drop', 'java.lang.Double'),
              ('notes', 'java.lang.Double')]
BGROR_COLS = [('t_stamp', 'java.util.Date'), ('bgRor', 'java.lang.Double')]
BBP_COLS = [('t_offset_sec', 'java.lang.Double'),
            ('t_stamp', 'java.util.Date'),
            ('bean_temp_f', 'java.lang.Double')]
LIVE_COLS = [('t_stamp', 'java.util.Date'), ('bean', 'java.lang.Double'),
             ('ror', 'java.lang.Double'), ('fan', 'java.lang.Double'),
             ('heat', 'java.lang.Double'), ('bg', 'java.lang.Double'),
             ('bgRor', 'java.lang.Double'),
             ('plan', 'java.lang.Double'),
             ('proj', 'java.lang.Double')]
DETAIL_COLS = [('t_stamp', 'java.util.Date'), ('bt', 'java.lang.Double'),
               ('ror', 'java.lang.Double')]

def main():
    # ---- 0. stash the current RoastLog rows (seed migration source)
    st, out = api('GET', '/tags/read',
                  body=json.dumps({'tags': ['[default]Roastery/RoastLog']}))
    try:
        blob = out['results'][0]['value']
        if isinstance(blob, str) and json.loads(blob).get('rows'):
            with open(BACKUP, 'w') as f:
                f.write(blob)
            print('stashed RoastLog rows:',
                  len(json.loads(blob)['rows']))
    except Exception as e:
        print('roastlog stash skipped:', e)

    # ---- 1. simulator program (the stepped SR800 curve above;
    # uploading it restarts the program clock, proven live)
    st, out = api('GET', f'/resources/find/com.inductiveautomation.opcua/device/{DEVICE}')
    if st != 200:
        print('device find failed', st, json.dumps(out)[:300]); sys.exit(1)
    sig = out.get('signature')
    st, out = api('PUT',
                  f'/resources/datafile/com.inductiveautomation.opcua/device/{DEVICE}/instructions.csv',
                  body=CSV, params={'signature': sig} if sig else None,
                  ctype='application/octet-stream')
    print('csv upload HTTP', st, str(out)[:150])

    # ---- 2. delete the old UDTs and the whole old Roastery tree
    st, out = api('DELETE', '/tags/delete',
                  body=json.dumps({'tags': ['[default]_types_/RoastBatch',
                                            '[default]_types_/RoasterSource',
                                            '[default]Roastery']}),
                  params={'confirm': 'true'})
    print('delete old tags HTTP', st, json.dumps(out)[:200])
    time.sleep(2)

    # ---- 3. import the source type, then the batch UDT
    for udt in (SOURCE_TYPE, UDT):
        st, out = api('POST', '/tags/import', body=json.dumps(udt),
                      params={'provider': 'default', 'type': 'json',
                              'collisionPolicy': 'Abort', 'path': '_types_'},
                      ctype='application/octet-stream')
        print('udt import', udt['name'], 'HTTP', st, json.dumps(out)[:200])
        if st != 200:
            sys.exit(1)

    # ---- 4. import instance folder with the Roastery level tags
    st, out = api('POST', '/tags/import', body=json.dumps(INSTANCE_FOLDER),
                  params={'provider': 'default', 'type': 'json',
                          'collisionPolicy': 'Abort'},
                  ctype='application/octet-stream')
    print('instance import HTTP', st, json.dumps(out)[:300])
    if st != 200:
        sys.exit(1)

    # ---- 5. initialize the dataset tags with typed empty datasets
    inits = {'[default]Roastery/EventsLog': ds_json(EVENTSLOG_COLS, []),
             '[default]Roastery/RoastLog': ds_json(ROASTLOG_COLS, []),
             '[default]Roastery/TargetProfileDS': ds_json(TARGETDS_COLS, []),
             '[default]Roastery/BackgroundDS': ds_json(BGDS_COLS, []),
             '[default]Roastery/CurveSamples': ds_json(CURVE_COLS, []),
             '[default]Roastery/EventMarksDS': ds_json(MARKS_COLS, []),
             '[default]Roastery/BackgroundRorDS': ds_json(BGROR_COLS, []),
             '[default]Roastery/LiveCurveDS': ds_json(LIVE_COLS, []),
             '[default]Roastery/BbpSamplesDS': ds_json(BBP_COLS, []),
             '[default]Roastery/DetailDS': ds_json(DETAIL_COLS, []),
             '[default]Roastery/DetailMarksDS': ds_json(MARKS_COLS, [])}
    st, out = api('POST', '/tags/write',
                  body=json.dumps({'tagPaths': list(inits.keys()),
                                   'values': list(inits.values())}))
    print('dataset init HTTP', st, json.dumps(out)[:250])

    # ---- 6. restore the stashed RoastLog rows into the fresh tag
    if os.path.exists(BACKUP):
        blob = open(BACKUP).read()
        st, out = api('POST', '/tags/write',
                      body=json.dumps({'tagPaths': ['[default]Roastery/RoastLog'],
                                       'values': [blob]}))
        print('roastlog restore HTTP', st, json.dumps(out)[:200])

if __name__ == '__main__':
    main()
