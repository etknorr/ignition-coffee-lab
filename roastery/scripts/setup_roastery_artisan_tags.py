#!/usr/bin/env python3
"""Artisan-style Roastery tag setup for the Maker 2027 gateway.

Replaces the original RoastBatch UDT (which had DrumTempF, lb weights,
Gas/Airflow percents, Record/Stop states) with a model of Eric's real
setup: a FreshRoast SR800 on a WebSocket feed with ONE bean temp probe.

- BeanTempF: OPC on RoasterSim in the lab (the simulator stands in for
  the SR800 WebSocket feed; the member documentation says so). History
  ON. Carries a valueChanged event script that derives RateOfRiseF.
- RateOfRiseF: derived for real. The event script keeps the previous
  sample in two scratch members and writes an exponentially smoothed
  delta per minute (tau = RoRSmoothingSec). History ON.
- Controls: FanLevel / HeatLevel (Int 1..9), Mode (Off/Roast/Cool).
- Events: Charge, DryEnd, FirstCrackStart, FirstCrackEnd,
  SecondCrackStart, SecondCrackEnd, Drop; each a DateTime plus the
  bean temp captured with it. Four custom events (name/kind in tags).
- State: Idle, Roasting, Dropped, Cooling, Complete. StartTime kept.
- Metadata: Artisan Roast Properties style fields, grams (SR800 home
  scale, about 200 g charges).
- Config: WsUrl, RoRSmoothingSec, target profile points, alarms.
- Roastery-level tags (siblings of CurrentBatch): EventsLog and
  RoastLog datasets, TargetProfileDS and BackgroundDS overlay
  datasets, BackgroundCurveJson and BackgroundLabel.

Event script JSON shape (proven on this gateway by a scratch tag, see
knowledge/notes/coffee-roaster-app.md): the array key is "eventScripts"
and each entry is {"eventid": "valueChanged", "script": "..."}; the
REST serializer drops the newer "eventType" key form silently. The
event scope variables are tag, tagPath, previousValue, currentValue,
initialChange, missedEvents (from CommonTagScripts in common.jar).

Run with wsvenv python. Destructive to the old Roastery tag tree by
design (lab): the old UDT and instance are deleted first.
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

ROR_SCRIPT = (
    "\tbase = str(tagPath).rsplit('/', 1)[0]\n"
    "\tnowMs = long(currentValue.timestamp.getTime())\n"
    "\tif initialChange:\n"
    "\t\tsystem.tag.writeBlocking([base + '/_RoRPrevTempF', base + '/_RoRPrevMs'], [currentValue.value, nowMs])\n"
    "\telse:\n"
    "\t\tqvs = system.tag.readBlocking([base + '/_RoRPrevTempF', base + '/_RoRPrevMs', base + '/RoRSmoothingSec', base + '/RateOfRiseF'])\n"
    "\t\tprevTemp = qvs[0].value\n"
    "\t\tprevMs = qvs[1].value\n"
    "\t\ttau = qvs[2].value\n"
    "\t\tif prevTemp is None or prevMs is None or prevMs <= 0 or tau is None or tau <= 0:\n"
    "\t\t\tsystem.tag.writeBlocking([base + '/_RoRPrevTempF', base + '/_RoRPrevMs'], [currentValue.value, nowMs])\n"
    "\t\telse:\n"
    "\t\t\tdt = (nowMs - prevMs) / 1000.0\n"
    "\t\t\tif dt > 0 and abs(currentValue.value - prevTemp) > 50.0:\n"
    "\t\t\t\tsystem.tag.writeBlocking([base + '/_RoRPrevTempF', base + '/_RoRPrevMs'], [currentValue.value, nowMs])\n"
    "\t\t\telif dt > 0:\n"
    "\t\t\t\tinst = (currentValue.value - prevTemp) * 60.0 / dt\n"
    "\t\t\t\tinst = max(-60.0, min(120.0, inst))\n"
    "\t\t\t\talpha = dt / (float(tau) + dt)\n"
    "\t\t\t\told = qvs[3].value\n"
    "\t\t\t\tif old is None:\n"
    "\t\t\t\t\told = inst\n"
    "\t\t\t\tnew = old + alpha * (inst - old)\n"
    "\t\t\t\tsystem.tag.writeBlocking([base + '/RateOfRiseF', base + '/_RoRPrevTempF', base + '/_RoRPrevMs'], [new, currentValue.value, nowMs])")

def mem(name, dtype, value, omit_value=False, doc=None):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'memory',
         'dataType': dtype}
    if not omit_value:
        t['value'] = value
    if doc:
        t['documentation'] = doc
    return t

def opc(name, item, history=False, doc=None, scripts=None):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'opc',
         'dataType': 'Float8', 'opcServer': 'Ignition OPC UA Server',
         'opcItemPath': f'[{DEVICE}]{item}'}
    if history:
        t.update({'historyEnabled': True, 'historyProvider': 'CoreHistorian',
                  'historySampleMode': 'Periodic', 'historySampleRate': 2,
                  'historySampleRateUnits': 'SEC'})
    if doc:
        t['documentation'] = doc
    if scripts:
        t['eventScripts'] = scripts
    return t

def hist_mem(name, dtype, value, doc=None):
    t = mem(name, dtype, value, doc=doc)
    t.update({'historyEnabled': True, 'historyProvider': 'CoreHistorian',
              'historySampleMode': 'Periodic', 'historySampleRate': 2,
              'historySampleRateUnits': 'SEC'})
    return t

def event_pair(stem):
    return [mem(stem + 'Time', 'DateTime', None, omit_value=True),
            mem(stem + 'TempF', 'Float8', 0.0)]

MEMBERS = [
    # probe and derived
    opc('BeanTempF', 'BeanTemp', history=True,
        doc='SR800 bean temp probe (WebSocket). In the lab this OPC path '
            'is RoasterSim standing in for the WebSocket feed.',
        scripts=[{'eventid': 'valueChanged', 'script': ROR_SCRIPT}]),
    hist_mem('RateOfRiseF', 'Float8', 0.0,
             doc='Derived from BeanTempF by its valueChanged event script: '
                 'exponentially smoothed delta deg F per minute, tau = '
                 'RoRSmoothingSec. There is no RoR probe on an SR800.'),
    mem('_RoRPrevTempF', 'Float8', 0.0),
    mem('_RoRPrevMs', 'Int8', 0),
    # controls (SR800 steppers)
    mem('FanLevel', 'Int4', 5, doc='SR800 fan level, 1 to 9.'),
    mem('HeatLevel', 'Int4', 5, doc='SR800 heat level, 1 to 9.'),
    mem('Mode', 'String', 'Off', doc='Roaster mode: Off, Roast, Cool.'),
    # state
    mem('State', 'String', 'Idle',
        doc='Idle, Roasting, Dropped, Cooling, Complete.'),
    mem('StartTime', 'DateTime', None, omit_value=True),
]
# roast events, Artisan order. Each event also gets an elapsed-seconds
# shadow member (Int4, -1 = not recorded): view expressions do all
# phase math and presence tests on these ints, never on null dates.
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
        doc='SR800 WebSocket endpoint (placeholder). The probe feed '
            'arrives over this socket in production.'),
    mem('RoRSmoothingSec', 'Int4', 30,
        doc='Rate of rise smoothing time constant, seconds.'),
]
# four customizable event buttons (Artisan custom events)
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
                                            '[default]Roastery']}),
                  params={'confirm': 'true'})
    print('delete old tags HTTP', st, json.dumps(out)[:200])
    time.sleep(2)

    # ---- 3. import the new UDT definition
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
