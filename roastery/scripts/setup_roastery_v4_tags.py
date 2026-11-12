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

Run with wsvenv python. Destructive to the old Roastery tag tree by
design (lab): the old UDTs and instance are deleted first.
"""
import json, os, sys, time
from api27m import api

DEVICE = 'RoasterSim'
B = '[default]Roastery/CurrentBatch'
LAB = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(LAB, 'roastlog-backup.json')

CSV = """TimeInterval,BrowsePath,ValueSource,DataType
0,BeanTemp,"ramp(200,300,240,true)",Double
240,BeanTemp,"ramp(300,352,150,true)",Double
390,BeanTemp,"ramp(352,385,120,true)",Double
510,BeanTemp,"ramp(385,397,90,true)",Double
600,BeanTemp,"ramp(397,412,90,true)",Double
690,BeanTemp,"ramp(397,412,90,true)",Double
"""

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
    # alarms (lite)
    mem('AlarmHighTempEnabled', 'Boolean', True),
    mem('AlarmHighTempF', 'Float8', 430.0),
    mem('AlarmHighTempMsg', 'String', 'Bean temperature high'),
    mem('AlarmDropEnabled', 'Boolean', True),
    mem('AlarmDropDeltaF', 'Float8', 5.0),
    mem('AlarmFCWatchEnabled', 'Boolean', True),
    mem('AlarmFCWindowSec', 'Int4', 90),
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
    mem('PressCaptureMode', 'String', 'Library',
        doc='Who writes batch_events rows: Library (named query) '
            'or Group (SQLBridge transaction group).'),
    mem('SeriesCaptureMode', 'String', 'Library',
        doc='Who writes batch_series rows: Library (CurveSamples '
            'at save) or Group (transaction group, live).'),
]
for i, (nm, kind) in enumerate([('Fan Boost', 'Airflow'),
                                ('Drum Note', 'Note'),
                                ('Custom 3', 'Info'),
                                ('Custom 4', 'Info')], start=1):
    MEMBERS += [
        mem(f'CustomEvent{i}Name', 'String', nm),
        mem(f'CustomEvent{i}Kind', 'String', kind),
        mem(f'CustomEvent{i}Time', 'DateTime', None, omit_value=True),
        mem(f'CustomEvent{i}TempF', 'Float8', 0.0),
        mem(f'CustomEvent{i}ElapsedSec', 'Int4', -1),
    ]

UDT = {'name': 'RoastBatch', 'tagType': 'UdtType', 'tags': MEMBERS}

def ds_tag(name):
    return {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
            'dataType': 'DataSet'}

INSTANCE_FOLDER = {'name': 'Roastery', 'tagType': 'Folder', 'tags': [
    {'name': 'CurrentBatch', 'tagType': 'UdtInstance', 'typeId': 'RoastBatch'},
    ds_tag('EventsLog'), ds_tag('RoastLog'),
    ds_tag('TargetProfileDS'), ds_tag('BackgroundDS'),
    ds_tag('CurveSamples'),
    mem('BackgroundCurveJson', 'String', ''),
    mem('BackgroundLabel', 'String', ''),
    # ---- v4 additions ----
    ds_tag('EventMarksDS'),
    ds_tag('BackgroundRorDS'),
    ds_tag('DetailDS'), ds_tag('DetailMarksDS'),
    mem('SelectedBatchNumber', 'Int4', 0,
        doc='Batch selected in the Log UI: detail view, slide over '
            'editor and ghost actions all read this.'),
    mem('EditorCreateMode', 'Boolean', False,
        doc='Slide over editor mode: True creates a manual batch.'),
    mem('DetailDocJson', 'String', '',
        doc='Staged batch document (JSON) for the detail view.'),
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

    # ---- 1. simulator program (unchanged from v2)
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
