#!/usr/bin/env python3
"""Artisan-style Roastery tag setup for the Maker 2027 gateway.

FAITHFUL RECORD OF THE LIVE UDT. This file mirrors the RoastBatch UDT
(202 members plus the Sources folder) and the RoasterSource UDT (7
members) exactly as exported from the live Maker gateway, including
member names, data types, value sources, default values, history
settings (provider db), event scripts and documentation. The proof is
the member diff in /tmp/r6_udt_diff.py, which compares this module
against a fresh live export and must report zero differences. The
round 6 custom event defaults are in place on both sides: slot 1
'Fan Boost' / 'Airflow', slots 2 to 4 blank.

Model: Eric's real setup, a FreshRoast SR800 on a WebSocket feed with
ONE bean temp probe. BeanTempF is an expression tag switching on
ActiveSource over Sources/WebSocket, Sources/Mqtt and
Sources/Simulated; its valueChanged script calls
roastery.core.on_bean_temp for RoR derivation and curve sampling.
RateOfRiseF is derived, with history on db. Controls are FanLevel /
HeatLevel (1 to 9) and Mode (Off/Roast/Cool). Four custom events
(name/kind in tags) use the round 6 defaults: slot 1 'Fan Boost' /
'Airflow', slots 2 to 4 blank.

DO NOT RUN main() against the live lab. It deletes the Roastery tag
tree and both UDT types first, which is destructive by design. Run
with wsvenv python, lab only, and only when a rebuild is intended.
"""
import json, sys, time
from api27m import api

DEVICE = 'RoasterSim'
B = '[default]Roastery/CurrentBatch'

# Artisan-like profile on one clock: charge 200, dry end ~300 at 4:00,
# first crack ~385 at 8:30, drop ~412 at 11:30, cycle 690 s.
CSV = """TimeInterval,BrowsePath,ValueSource,DataType
0,BeanTemp,"ramp(200,300,240,true)",Double
240,BeanTemp,"ramp(300,352,150,true)",Double
390,BeanTemp,"ramp(352,385,120,true)",Double
510,BeanTemp,"ramp(385,397,90,true)",Double
600,BeanTemp,"ramp(397,412,90,true)",Double
690,BeanTemp,"ramp(397,412,90,true)",Double
"""

ON_BEAN_TEMP_SCRIPT = (
    "\timport roastery.core\n"
    "\troastery.core.on_bean_temp(tagPath, currentValue, initialChange)\n")

def mem(name, dtype, value, omit_value=False, doc=None, history=None):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
         'dataType': dtype}
    if not omit_value:
        t['value'] = value
    if history:
        t.update({'historyEnabled': True, 'historyProvider': history,
                  'historySampleMode': 'Periodic', 'historySampleRate': 2,
                  'historySampleRateUnits': 'SEC'})
    if doc:
        t['documentation'] = doc
    return t

def hist_mem(name, dtype, value, doc=None, provider='db'):
    """Memory tag with history on the given provider (live: db)."""
    return mem(name, dtype, value, doc=doc, history=provider)

def expr(name, expression, scripts=None, doc=None, history=None):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'expr',
         'dataType': 'Float8', 'expression': expression}
    if history:
        t.update({'historyEnabled': True, 'historyProvider': history,
                  'historySampleMode': 'Periodic', 'historySampleRate': 2,
                  'historySampleRateUnits': 'SEC'})
    if doc:
        t['documentation'] = doc
    if scripts:
        t['eventScripts'] = scripts
    return t

def _ovr(name, **kw):
    """One per-instance override inside a Sources UdtInstance."""
    t = {'name': name, 'tagType': 'AtomicTag'}
    t.update(kw)
    return t

# RoasterSource: one transport's live bean temp output plus its
# connection details. CurrentBatch/BeanTempF reads the instance
# named by ActiveSource. (7 members, live order.)
ROASTER_SOURCE_MEMBERS = [
    mem('BeanTempF', 'Float8', 0.0, doc="This transport's live bean temp output. The canonical CurrentBatch/BeanTempF expression reads the instance named by ActiveSource."),
    mem('Connected', 'Boolean', False, doc='Transport liveness, set by whatever populates the source.'),
    mem('WsUrl', 'String', '', doc='WebSocket endpoint (WebSocket source).'),
    mem('Topic', 'String', '', doc='MQTT topic (MQTT source).'),
    mem('Address', 'String', '', doc='Human readable address summary.'),
    mem('BrokerUrl', 'String', '', doc='MQTT broker URL (MQTT source).'),
    mem('Kind', 'String', '', doc='Transport kind: Simulated, WebSocket or MQTT.'),
]

ROASTER_SOURCE_UDT = {'name': 'RoasterSource', 'tagType': 'UdtType',
                      'tags': ROASTER_SOURCE_MEMBERS}

# RoastBatch members, alphabetical by name so this list diffs cleanly
# against the gateway export. 202 members, live values throughout.
# Custom event slots use the round 6 defaults: slot 1 'Fan Boost' /
# 'Airflow', slots 2 to 4 blank (name '' and kind ''). The live gateway
# still holds the old slot 2 to 4 names; see the diff proof note.
MEMBERS = [
    mem('ActionCounter', 'Int8', 0, doc='Monotonically increasing press counter. Every control button press increments it (roastery.core.record_press); a SQLBridge group triggers on its change.'),
    mem('ActiveSource', 'String', 'Simulated', doc='Which Sources instance drives BeanTempF: Simulated, WebSocket or Mqtt.'),
    mem('AlarmActive', 'Boolean', False),
    mem('AlarmDefsJson', 'String', '[{"name": "High bean temp", "enabled": true, "guard": "None", "offsetSec": 0, "source": "BT", "cond": ">=", "value": 430, "message": "Bean temperature high", "action": "Banner"}, {"name": "Drop approaching", "enabled": true, "guard": "None", "offsetSec": 0, "source": "BT", "cond": ">=", "value": 410, "message": "Drop approaching", "action": "Banner"}, {"name": "First crack watch", "enabled": true, "guard": "Charge", "offsetSec": 420, "source": "Time", "cond": ">=", "value": 420, "message": "First crack watch: listen for cracks", "action": "Message"}]', doc='Alarm definitions (JSON list) evaluated by roastery.core.evaluate_alarms. Fields: name, enabled, guard (None, Charge, TP, Dry End, FC Start, FC End, SC Start, SC End, Drop), offsetSec, source (BT, RoR, Time), cond (>= or <=), value, message, action (Banner or Message).'),
    mem('AlarmDropDeltaF', 'Float8', 5.0),
    mem('AlarmDropEnabled', 'Boolean', True),
    mem('AlarmFCWatchEnabled', 'Boolean', True),
    mem('AlarmFCWindowSec', 'Int4', 90),
    mem('AlarmHighTempEnabled', 'Boolean', True),
    mem('AlarmHighTempF', 'Float8', 430.0),
    mem('AlarmHighTempMsg', 'String', 'Bean temperature high'),
    mem('AlarmMessageSeq', 'Int4', 0, doc='Polish phase 4 (HUNT-19): latch sequence counter, incremented by roastery.core.evaluate_alarms on every new Message latch batch. The Roast page watches this counter (not the message text) to fire its toast, so two latches carrying identical message text still toast once each.'),
    mem('AlarmMessageText', 'String', '', doc='Polish phase 3: the most recently latched Message alarm text, written by roastery.core.evaluate_alarms only when a Message alarm newly latches. The Roast page binds a custom prop to it and toasts the new value once per latch through Periscope.'),
    mem('AlarmText', 'String', '', doc='Current alarm banner text, written by roastery.core.evaluate_alarms.'),
    mem('Altitude', 'String', '2000 to 2200 masl'),
    mem('AmbientHumidityPct', 'Float8', 0.0),
    mem('AmbientPressureHPa', 'Float8', 0.0),
    mem('AmbientTempF', 'Float8', 0.0),
    mem('AnalyzerBgF', 'Float8', 0.0),
    mem('AnalyzerBgText', 'String', '--'),
    mem('AnalyzerBtF', 'Float8', 0.0),
    mem('AnalyzerBtText', 'String', '--'),
    mem('AnalyzerDevF', 'Float8', 0.0),
    mem('AnalyzerDevText', 'String', '--'),
    mem('AnalyzerHasBg', 'Boolean', False),
    mem('AnalyzerRorF', 'Float8', 0.0),
    mem('AnalyzerRorText', 'String', '--'),
    mem('AnalyzerSec', 'Int4', -1, doc='Tier 2 item 13: analyzer selected elapsed seconds on the live chart; -1 follows the latest sample.'),
    mem('AnalyzerTimeText', 'String', '--:--'),
    mem('AucBaseFromEvent', 'Boolean', False, doc='Artisan AUCbaseFlag: take the base from the bean temp at the begin event instead of AucBaseTempF.'),
    mem('AucBaseTempF', 'Float8', 212.0, doc='AUC base temperature (Artisan AUCbase, default 212 F).'),
    mem('AucBegin', 'String', 'TP', doc='AUC begin event: Charge, TP, Dry End or FC Start (Artisan AUCbegin, default TP).'),
    mem('AucGuideElapsedSec', 'Int4', -1, doc='Predicted elapsed seconds when the AUC target is reached; -1 when no prediction applies.'),
    mem('AucGuideEnabled', 'Boolean', True, doc='Artisan AUCguideFlag: predict when the target AUC is reached at the current RoR.'),
    mem('AucLiveFMin', 'Float8', 0.0, doc='Live AUC from the begin event, F min.'),
    mem('AucSinceFcFMin', 'Float8', 0.0, doc='Live AUC accumulated since FC Start, F min.'),
    mem('AucTargetFMin', 'Float8', 1152.0, doc='AUC target in F min (Artisan AUCtarget 640 is in C min; Roastery works in F throughout).'),
    mem('BatchNumber', 'Int4', 1042),
    mem('BeanName', 'String', 'Ethiopia Guji'),
    mem('BeanSizeMaxMm', 'Float8', 0.0),
    mem('BeanSizeMinMm', 'Float8', 0.0),
    # Canonical bean temp: expression over the Sources folder,
    # switching on ActiveSource. History on db. valueChanged
    # calls roastery.core.on_bean_temp (RoR + curve sampling).
    expr('BeanTempF', "if({[.]ActiveSource} = 'WebSocket', {[.]Sources/WebSocket/BeanTempF}, if({[.]ActiveSource} = 'Mqtt', {[.]Sources/Mqtt/BeanTempF}, {[.]Sources/Simulated/BeanTempF}))", scripts=[{'eventid': 'valueChanged', 'script': ON_BEAN_TEMP_SCRIPT}], doc='Canonical bean temp: the BeanTempF of the source named by ActiveSource. History on the SQL historian (db). Its valueChanged script calls roastery.core.on_bean_temp for RoR derivation and curve sampling.', history='db'),
    mem('BgDeviationText', 'String', '--', doc='Tier 2 item 10: live BT minus the staged background BT at the same elapsed time, written by roastery.core.update_bg_deviation.'),
    mem('BgPhaseDropSec', 'Int4', -1, doc='Tier 3 item 16: staged ghost drop, elapsed seconds.'),
    mem('BgPhaseDrySec', 'Int4', -1, doc='Tier 3 item 16: staged ghost dry end, elapsed seconds since its charge; -1 when no ghost phases are staged. Written by both ghost routes through roastery.core.stage_bg_phases and cleared with the ghost.'),
    mem('BgPhaseFcSec', 'Int4', -1, doc='Tier 3 item 16: staged ghost FC start, elapsed seconds.'),
    mem('ChargeTempF', 'Float8', 0.0),
    mem('ChargeTime', 'DateTime', None, omit_value=True),
    mem('ChargeWeightG', 'Float8', 200.0, doc='Green coffee charged, grams (SR800 home scale).'),
    mem('ColorSystem', 'String', '', doc='Color reading system (for example Agtron).'),
    mem('CompareAlignEvent', 'String', 'charge', doc='Polish round 8 (HUNT-56): compare alignment event, after Artisan 5.0.0 alignEvent. Stored keys: charge, dryEnd, fcStart, fcEnd, scStart, scEnd, drop (Artisan labels CHARGE, DRY, FCs, FCe, SCs, SCe, DROP). roastery.batches.build_compare shifts every compared curve so the chosen event lands on the same 30 s grid step, slot A as the reference; a batch missing the event falls back to its charge. Bound in Settings Display and on the Log compare row, one tag for both.'),
    mem('CuppingNotes', 'String', ''),
    mem('CustomEvent1ElapsedSec', 'Int4', -1),
    mem('CustomEvent1Enabled', 'Boolean', True, doc='Polish round 1 item 7: whether this custom event can be stamped (dock list and the library stamp guard both honor it).'),
    mem('CustomEvent1Kind', 'String', 'Airflow'),
    mem('CustomEvent1Name', 'String', 'Fan Boost'),
    mem('CustomEvent1TempF', 'Float8', 0.0),
    mem('CustomEvent1Time', 'DateTime', None, omit_value=True),
    mem('CustomEvent2ElapsedSec', 'Int4', -1),
    mem('CustomEvent2Enabled', 'Boolean', True, doc='Polish round 1 item 7: whether this custom event can be stamped (dock list and the library stamp guard both honor it).'),
    mem('CustomEvent2Kind', 'String', ''),
    mem('CustomEvent2Name', 'String', ''),
    mem('CustomEvent2TempF', 'Float8', 0.0),
    mem('CustomEvent2Time', 'DateTime', None, omit_value=True),
    mem('CustomEvent3ElapsedSec', 'Int4', -1),
    mem('CustomEvent3Enabled', 'Boolean', True, doc='Polish round 1 item 7: whether this custom event can be stamped (dock list and the library stamp guard both honor it).'),
    mem('CustomEvent3Kind', 'String', ''),
    mem('CustomEvent3Name', 'String', ''),
    mem('CustomEvent3TempF', 'Float8', 0.0),
    mem('CustomEvent3Time', 'DateTime', None, omit_value=True),
    mem('CustomEvent4ElapsedSec', 'Int4', -1),
    mem('CustomEvent4Enabled', 'Boolean', True, doc='Polish round 1 item 7: whether this custom event can be stamped (dock list and the library stamp guard both honor it).'),
    mem('CustomEvent4Kind', 'String', ''),
    mem('CustomEvent4Name', 'String', ''),
    mem('CustomEvent4TempF', 'Float8', 0.0),
    mem('CustomEvent4Time', 'DateTime', None, omit_value=True),
    mem('DTRTargetPct', 'Float8', 20.0, doc='Phase bar target: development time ratio, percent.'),
    mem('DefectDarkCut', 'Boolean', False),
    mem('DefectDivots', 'Boolean', False),
    mem('DefectDrops', 'Boolean', False),
    mem('DefectHeavyFC', 'Boolean', False),
    mem('DefectLightCut', 'Boolean', False),
    mem('DefectLowFC', 'Boolean', False),
    mem('DefectOily', 'Boolean', False),
    mem('DefectScorching', 'Boolean', False),
    mem('DefectTipping', 'Boolean', False),
    mem('DefectUneven', 'Boolean', False),
    mem('DefectsWeightG', 'Float8', 0.0, doc='Defects picked out, grams.'),
    mem('DensityGL', 'Float8', 680.0),
    mem('DispAxisFormat', 'String', 'm:ss', doc='Polish round 3 (HUNT-23): time axis label format on every roast chart, m:ss (Artisan style) or mm:ss. The charts run on a category axis whose names roastery.core.axis_label formats from this member, so the labels are true elapsed in any browser timezone.'),
    mem('DispBtStyle', 'String', 'solid', doc='Tier 3 item 15: bean temp line style (solid, dashed or dotted).'),
    mem('DispBtWidth', 'Int4', 3, doc='Tier 3 item 15: bean temp line width on the live chart (Settings Display; binds onto the canvas series line width). Default 3 is the fixed look from before Tier 3.'),
    mem('DispGhostStyle', 'String', 'solid', doc='Tier 3 item 15: ghost line style.'),
    mem('DispGhostWidth', 'Int4', 2, doc='Tier 3 item 15: ghost (background) line width, applies to the ghost BT and ghost RoR series.'),
    mem('DispMarkerSize', 'Int4', 4, doc='Tier 3 item 15: event marker size (the reference line endpoint size on the bean series).'),
    mem('DispRorFill', 'Boolean', False, doc='Tier 3 item 15: fill under the RoR curve on the live chart (series area opacity 0.22 when on).'),
    mem('DispRorStyle', 'String', 'solid', doc='Tier 3 item 15: rate of rise line style.'),
    mem('DispRorWidth', 'Int4', 2, doc='Tier 3 item 15: rate of rise line width.'),
    mem('DisplaySmoothing', 'Int4', 0, doc='Tier 2 item 12: display only smoothing level for the BT line in LiveCurveDS (0 off, 1 to 5). Stored temps and RoR are never smoothed.'),
    mem('DockActionsJson', 'String', '[]', doc='Polish phase 2 item 1: the phase aware dock set as a JSON list of descriptors, written by roastery.core.update_dock_actions; the dock views bind it instead of calling scripts.'),
    mem('DropElapsedSec', 'Int4', -1),
    mem('DropTempF', 'Float8', 0.0),
    mem('DropTime', 'DateTime', None, omit_value=True),
    mem('DryEndElapsedSec', 'Int4', -1),
    mem('DryEndTempF', 'Float8', 0.0),
    mem('DryEndTime', 'DateTime', None, omit_value=True),
    mem('FanLevel', 'Int4', 5, doc='SR800 fan level, 1 to 9.'),
    mem('Farm', 'String', 'Buku Abel'),
    mem('FirstCrackEndElapsedSec', 'Int4', -1),
    mem('FirstCrackEndTempF', 'Float8', 0.0),
    mem('FirstCrackEndTime', 'DateTime', None, omit_value=True),
    mem('FirstCrackStartElapsedSec', 'Int4', -1),
    mem('FirstCrackStartTempF', 'Float8', 0.0),
    mem('FirstCrackStartTime', 'DateTime', None, omit_value=True),
    mem('GreensTempF', 'Float8', 0.0),
    mem('GroundColor', 'Float8', 0.0, doc='Ground bean color reading.'),
    mem('HarvestYear', 'Int4', 2025),
    mem('HeatLevel', 'Int4', 5, doc='SR800 heat level, 1 to 9.'),
    mem('LastAction', 'String', '', doc='Name of the last control action pressed.'),
    mem('LastActionAt', 'DateTime', None, omit_value=True, doc='Wall clock time of the last press.'),
    mem('LastActionBatchNumber', 'Int4', 1042, doc='Batch number at the last press, stamped by roastery.core.record_press. The PressEvents group reads this instead of the live BatchNumber, so a press is recorded against the batch it belonged to even when the batch number changes before the group executes (polish round 5, HUNT-45).'),
    mem('LastActionElapsedSec', 'Int4', -1, doc='Seconds since charge at the last press.'),
    mem('Mode', 'String', 'Off', doc='Roaster mode: Off, Roast, Cool.'),
    mem('MoisturePct', 'Float8', 10.5),
    mem('Notes', 'String', ''),
    mem('OperatorName', 'String', 'Eric'),
    mem('Organization', 'String', ''),
    mem('Origin', 'String', 'Guji, Ethiopia'),
    mem('PhaseDevTargetSec', 'Int4', 150, doc='Phase bar target: development phase duration, seconds.'),
    mem('PhaseDryTargetSec', 'Int4', 270, doc='Phase bar target: drying phase duration, seconds.'),
    mem('PhaseFromBg', 'Boolean', False, doc='Tier 3 item 16: when on, the phase bar and the chart phase bands follow the staged ghost phase boundaries (BgPhase tags) instead of the saved phase targets. Saved targets are never overwritten by this option.'),
    mem('PhaseLabel', 'String', 'Pre-charge', doc='Polish round 1 item 6: current roast phase, written by roastery.core.update_phase_label from State plus the stamped events in roast order.'),
    mem('PhaseMaillardTargetSec', 'Int4', 210, doc='Phase bar target: maillard phase duration, seconds.'),
    mem('PlanDeviationText', 'String', '--', doc='Tier 3 item 17: live BT minus the target plan at the elapsed seconds, published by roastery.core.update_plan_deviation for the deviation tile. Two dashes outside a roast.'),
    mem('PlaybackActive', 'Boolean', False),
    mem('PlaybackEnabled', 'Boolean', True, doc='Tier 2 item 11: background playback prompts on. Prompts only; Fan and Heat stay manual.'),
    mem('PlaybackSound', 'Boolean', False, doc='Tier 2 item 11: beep with playback prompts. Stored setting; Perspective has no clean client beep API in this build, so prompts are visual only.'),
    mem('PlaybackText', 'String', '', doc='Current background playback prompt, written by roastery.core.evaluate_playback.'),
    mem('PressCaptureMode', 'String', 'Group', doc='Who writes batch_events rows: Library (named query) or Group (SQLBridge transaction group). Default is Group since 2026-11-17: the PressEvents transaction group is authored and RUNNING on the lab gateway.'),
    mem('Process', 'String', 'Washed'),
    mem('ProjectionEnabled', 'Boolean', True, doc='Tier 2 item 9: show the BT projection series on the live chart (roastery.core.projection_points).'),
    mem('ProjectionMode', 'String', 'Linear', doc='Projection mode: Linear (current RoR) or Quadratic (linear RoR trend, after five minutes elapsed).'),
    mem('RateOfRiseDisplayText', 'String', '--', doc='Polish round 1 item 4: HUD RoR reading under the Artisan display convention, written by roastery.core.update_ror_display. The RateOfRiseF tag always keeps the true computed value.'),
    hist_mem('RateOfRiseF', 'Float8', 0.0, doc='Derived from BeanTempF by roastery.core.on_bean_temp using the Artisan RoR parameterization (delta span, curve filter, delta filter tags). The same library calculation produces the live value, the saved batch RoR and ghost RoR. No RoR probe on an SR800.'),
    mem('Region', 'String', 'Guji Zone'),
    mem('RoRClipHighF', 'Float8', 81.0, doc='Artisan RoRlimit: offline RoR above this is dropped.'),
    mem('RoRClipLowF', 'Float8', -18.0, doc='Artisan RoRlimitm: offline RoR below this is dropped.'),
    mem('RoRCurveFilter', 'Int4', 1, doc='Artisan curvefilter (UI value 0 to 5, default 1): bean temp smoothing before differentiation. Internal window is 2x+1 with linear decay weights.'),
    mem('RoRDeltaFilter', 'Int4', 3, doc='Artisan deltafilter (UI value 0 to 40, default 3): RoR smoothing after differentiation. Internal value 2x+1; decay weights run to round(internal/2).'),
    mem('RoRDeltaSpanSec', 'Int4', 20, doc='Artisan DeltaSpan: seconds of bean temp history one RoR value spans. Artisan default 20, UI range 0 to 30.'),
    mem('RoROptimalSmoothing', 'Boolean', False, doc='Artisan optimalSmoothing (needs polyfit): Hanning smoothing offline, Savitzky-Golay derivative for RoR.'),
    mem('RoRPolyfit', 'Boolean', False, doc='Artisan polyfitRoRcalc: least squares slope over the delta span instead of the two point difference.'),
    mem('RoRSmoothSpikes', 'Boolean', True, doc='Artisan filterDropOuts (Smooth Spikes, default on): median filter k=5 on temps and k=3 on RoR in the offline recompute path (saved batches, ghosts).'),
    mem('RoRSmoothingSec', 'Int4', 30, doc='DEPRECATED in v4: the v3 EMA time constant. RoR is now computed with the Artisan parameterization below; this member is kept only so old references do not break.'),
    mem('RoastLevel', 'String', 'City+'),
    mem('RoastTitle', 'String', ''),
    mem('RoastedDensityGL', 'Float8', 0.0, doc='Roasted density, grams per litre.'),
    mem('RoastedMoisturePct', 'Float8', 0.0),
    mem('RoasterHeating', 'Int4', 0, doc='Artisan roasterheating code (0 is electric).'),
    mem('RoasterSizeKg', 'Float8', 0.25),
    mem('RoasterType', 'String', 'FreshRoast SR800'),
    mem('SecondCrackEndElapsedSec', 'Int4', -1),
    mem('SecondCrackEndTempF', 'Float8', 0.0),
    mem('SecondCrackEndTime', 'DateTime', None, omit_value=True),
    mem('SecondCrackStartElapsedSec', 'Int4', -1),
    mem('SecondCrackStartTempF', 'Float8', 0.0),
    mem('SecondCrackStartTime', 'DateTime', None, omit_value=True),
    mem('SeriesCaptureMode', 'String', 'Library', doc='Who writes batch_series rows: Library (CurveSamples at save) or Group (transaction group, live).'),
    mem('SimSeekTargetSec', 'Int4', -1, doc='Polish round 3 (HUNT-22): the program second the cooling seek is fast forwarding to, or -1 when no seek is armed. Written by roastery.core.sim_seek_cooling (the starter) and consumed by sim_seek_advance on each BeanTempF change, so the seek never blocks a press handler.'),
    mem('SimSeeking', 'Boolean', False, doc='Polish round 3 (HUNT-22): True while roastery.core.sim_seek_cooling fast forwards the simulator program after a Drop. While set, the BeanTempF change pipeline stays muted (the ticks are fast forward artifacts, and their render flood is the window in which dock clicks were lost). Read with a staleness expiry, so an interrupted seek can never mute the pipeline for good.'),
    mem('StartTime', 'DateTime', None, omit_value=True),
    mem('State', 'String', 'Idle', doc='Idle, Roasting, Dropped, Cooling, Complete.'),
    mem('StatsLineText', 'String', 'Dry --:-- -- · Mai --:-- -- · Dev --:-- -- · DTR --', doc='Polish round 1 item 5: the Roast page stats line, written by roastery.core.update_stats_line; durations and percentages always describe the same phases.'),
    mem('SuggestDryEndEnabled', 'Boolean', True, doc='Tier 2 item 14: suggest Dry End when BT crosses TargetDryEndTempF. Suggestion only.'),
    mem('SuggestFcEnabled', 'Boolean', True, doc='Tier 2 item 14: suggest FC Start when BT crosses TargetFCTempF. Suggestion only.'),
    mem('SuggestionActive', 'Boolean', False),
    mem('SuggestionKind', 'String', '', doc='Which event the live suggestion names: DryEnd or FCStart.'),
    mem('SuggestionText', 'String', '', doc='Current auto event suggestion, written by roastery.core.evaluate_suggestions.'),
    mem('TargetChargeTempF', 'Float8', 200.0),
    mem('TargetDropSec', 'Int4', 630),
    mem('TargetDropTempF', 'Float8', 415.0),
    mem('TargetDryEndSec', 'Int4', 240),
    mem('TargetDryEndTempF', 'Float8', 300.0),
    mem('TargetFCSec', 'Int4', 510),
    mem('TargetFCTempF', 'Float8', 385.0),
    mem('TargetPlanJson', 'String', '', doc='Tier 3 item 17: the target plan as a JSON list of [sec, tempF] pairs, written by the Settings Targets designer through roastery.core.set_target_plan. Empty means the plan is the legacy four points above (the default list). The plan line and the deviation tile read it through roastery.core.target_plan_points.'),
    mem('TurningPointElapsedSec', 'Int4', -1, doc='Live turning point: seconds since charge of the bean temp minimum after charge, once the curve has risen clear of it. -1 until detected.'),
    mem('TurningPointTempF', 'Float8', 0.0),
    mem('Variety', 'String', 'Heirloom'),
    mem('VolumeInMl', 'Float8', 0.0, doc='Green volume in, millilitres.'),
    mem('VolumeOutMl', 'Float8', 0.0, doc='Roasted volume out, millilitres.'),
    mem('WeightOutG', 'Float8', 0.0, doc='Roasted weight out, grams.'),
    mem('WholeColor', 'Float8', 0.0, doc='Whole bean color reading.'),
    mem('WsUrl', 'String', 'ws://sr800.local:8080', doc='SR800 WebSocket endpoint (placeholder). Mirrored into Sources/WebSocket/WsUrl by the config form submit.'),
    mem('_AlarmFiredJson', 'String', '', doc='Scratch: indexes of Message alarms already latched this roast (JSON list).'),
    mem('_DrySuggested', 'Boolean', False, doc='Scratch: Dry End already suggested this roast.'),
    mem('_FcSuggested', 'Boolean', False, doc='Scratch: FC Start already suggested this roast.'),
    mem('_PlaybackFiredJson', 'String', '', doc='Scratch: indexes of ghost playback events already prompted this roast (JSON list).'),
    mem('_RoRLiveJson', 'String', '', doc='Live RoR scratch buffer (JSON): recent bean temp samples and raw RoR values for roastery.core.'),
    mem('_RoRPrevMs', 'Int8', 0),
    mem('_RoRPrevTempF', 'Float8', 0.0),
    mem('_TpMinElapsedSec', 'Int4', -1),
    mem('_TpMinTempF', 'Float8', 0.0, doc='Scratch: running bean temp minimum since charge.'),
]

# Sources folder, part of the RoastBatch type: three RoasterSource
# instances (WebSocket, Simulated, Mqtt). Each child lists only its
# per-instance overrides; anything not listed takes the type default.
# Simulated BeanTempF is the OPC simulator path [RoasterSim]BeanTemp.
SOURCES_FOLDER = {'name': 'Sources', 'tagType': 'Folder', 'tags': [
    {'name': 'WebSocket', 'tagType': 'UdtInstance', 'typeId': 'RoasterSource', 'tags': [
        _ovr('Address', value='ws://sr800.local:8080'),
        _ovr('BeanTempF'),
        _ovr('BrokerUrl'),
        _ovr('Connected'),
        _ovr('Kind', value='WebSocket'),
        _ovr('Topic'),
        _ovr('WsUrl', value='ws://sr800.local:8080'),
    ]},
    {'name': 'Simulated', 'tagType': 'UdtInstance', 'typeId': 'RoasterSource', 'tags': [
        _ovr('Address', value='[RoasterSim]BeanTemp'),
        _ovr('BeanTempF', opcItemPath='[RoasterSim]BeanTemp', opcServer='Ignition OPC UA Server', valueSource='opc'),
        _ovr('BrokerUrl'),
        _ovr('Connected', value=True),
        _ovr('Kind', value='Simulated'),
        _ovr('Topic'),
        _ovr('WsUrl'),
    ]},
    {'name': 'Mqtt', 'tagType': 'UdtInstance', 'typeId': 'RoasterSource', 'tags': [
        _ovr('Address', value='mqtt://localhost:1883 roastery/sr800/temp'),
        _ovr('BeanTempF'),
        _ovr('BrokerUrl', value='mqtt://localhost:1883'),
        _ovr('Connected'),
        _ovr('Kind', value='MQTT'),
        _ovr('Topic', value='roastery/sr800/temp'),
        _ovr('WsUrl'),
    ]},
]}

UDT = {'name': 'RoastBatch', 'tagType': 'UdtType',
       'tags': MEMBERS + [SOURCES_FOLDER]}

def ds_tag(name):
    return {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
            'dataType': 'DataSet'}

INSTANCE_FOLDER = {'name': 'Roastery', 'tagType': 'Folder', 'tags': [
    {'name': 'CurrentBatch', 'tagType': 'UdtInstance', 'typeId': 'RoastBatch'},
    ds_tag('EventsLog'), ds_tag('RoastLog'),
    ds_tag('TargetProfileDS'), ds_tag('BackgroundDS'),
    mem('BackgroundCurveJson', 'String', ''),
    mem('BackgroundLabel', 'String', ''),
]}

def ds_json(cols, rows):
    """Dataset value as the JSON string form /tags/write accepts:
    columns carry fully qualified Java class names."""
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

def main():
    # ---- 1. new simulator program (BeanTemp only; RoR is derived now)
    st, out = api('GET', f'/resources/find/com.inductiveautomation.opcua/device/{DEVICE}')
    if st != 200:
        print('device find failed', st, json.dumps(out)[:300]); sys.exit(1)
    sig = out.get('signature')
    st, out = api('PUT',
                  f'/resources/datafile/com.inductiveautomation.opcua/device/{DEVICE}/instructions.csv',
                  body=CSV, params={'signature': sig} if sig else None,
                  ctype='application/octet-stream')
    print('csv upload HTTP', st, str(out)[:150])

    # ---- 2. delete the old UDT and the whole old Roastery tree
    st, out = api('DELETE', '/tags/delete',
                  body=json.dumps({'tags': ['[default]_types_/RoastBatch',
                                            '[default]_types_/RoasterSource',
                                            '[default]Roastery']}),
                  params={'confirm': 'true'})
    print('delete old tags HTTP', st, json.dumps(out)[:200])
    time.sleep(2)

    # ---- 3. import the UDT definitions (RoasterSource first: RoastBatch
    # references it from its Sources folder)
    st, out = api('POST', '/tags/import', body=json.dumps(ROASTER_SOURCE_UDT),
                  params={'provider': 'default', 'type': 'json',
                          'collisionPolicy': 'Abort', 'path': '_types_'},
                  ctype='application/octet-stream')
    print('roastersource import HTTP', st, json.dumps(out)[:300])
    if st != 200:
        sys.exit(1)

    st, out = api('POST', '/tags/import', body=json.dumps(UDT),
                  params={'provider': 'default', 'type': 'json',
                          'collisionPolicy': 'Abort', 'path': '_types_'},
                  ctype='application/octet-stream')
    print('udt import HTTP', st, json.dumps(out)[:300])
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
             '[default]Roastery/BackgroundDS': ds_json(BGDS_COLS, [])}
    st, out = api('POST', '/tags/write',
                  body=json.dumps({'tagPaths': list(inits.keys()),
                                   'values': list(inits.values())}))
    print('dataset init HTTP', st, json.dumps(out)[:250])

if __name__ == '__main__':
    main()
