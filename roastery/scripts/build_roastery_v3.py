#!/usr/bin/env python3
"""Build the Roastery v3 project (files only) on the Maker 2027
gateway (gateway-2027-maker/data/projects/Roastery).

V3 architecture (Eric's direction, 2026-11-11):

1. Previous batches are full CRUD in Postgres through NAMED QUERIES.
   batches table: surrogate id PK, batch_number UNIQUE, relational
   columns for listing (roast_start, roast_end, bean_name,
   drop_temp_f) and a `data` JSONB column with the whole batch
   document. batch_series table: one row per curve sample keyed by
   batch_number (FK cascade). Named queries live under
   Roastery/Batches/* and Roastery/Series/*. The Log page becomes a
   Batches page (table query binding to SelectAll, edit popup with
   the ia.input.form, delete with confirm, View as Background reads
   the series table). No embedded SQL in any binding or handler.

2. All Python logic lives in the project scripting library package
   `roastery` (modules roastery.core and roastery.batches). View
   handlers, startup scripts and the BeanTempF tag event script are
   thin calls into it. The gateway scripting project is Roastery.

3. Styling is Perspective style classes plus the advanced
   stylesheet, applied via style.classes. Inline style props remain
   only where a value is data driven (bound pill colors, phase
   segment widths, the EventCell done color, the Tile accent color,
   display toggles) or is a chart prop. Neutral theme via the built
   in session theme CSS variables, both dark and light.

4. RoasterSource UDT (see setup_roastery_v3_tags.py): BeanTempF is
   an expression over the selected source instance.

Usage: build_roastery_v3.py  (then POST /scan/projects)
Run with wsvenv python.
"""
import copy, json, os, shutil, sys

LAB = os.path.dirname(os.path.abspath(__file__))
GW = os.path.join(LAB, 'gateway-2027-maker')
PROJ = os.path.join(GW, 'data', 'projects', 'Roastery')
SCHEMAS = os.path.join(LAB, 'knowledge', 'schemas-2027')

RES = {'scope': 'G', 'version': 1, 'restricted': False, 'overridable': True,
       'files': ['view.json'], 'attributes': {'lastModificationSignature': ''}}

# Chart series colors cannot use CSS variables (amCharts parses
# them), so these stay hex values chosen to read on both themes.
AMBER = '#3b82f6'
SKY = '#14b8a6'
RED = '#ef4444'

B = '[default]Roastery/CurrentBatch'
LOG = '[default]Roastery/EventsLog'

def T(member):
    return f'{B}/{member}'

def ref(path):
    return '{' + path + '}'

def tag_binding(path, bidirectional=False):
    return {'type': 'tag',
            'config': {'tagPath': path, 'mode': 'direct',
                       'bidirectional': bidirectional},
            'bidirectional': bidirectional}

def fmt_tag(path, fmt):
    b = tag_binding(path)
    b['transforms'] = [{'type': 'format', 'formatType': 'numeric',
                        'formatValue': fmt}]
    return b

def expr_binding(expression):
    return {'type': 'expr', 'config': {'expression': expression}}

def prop_binding(path):
    return {'type': 'property', 'config': {'path': path}}

# ---------------------------------------------------------------- components
# Styling goes through style.classes (the v3 style class system).
# The `style` argument is reserved for data driven values a class
# cannot express; each use is documented in the docs note.

def label(name, text, classes=None, position=None, prop_config=None,
          style=None, extra_props=None):
    props = {'text': text}
    st = {}
    if classes:
        st['classes'] = classes
    if style:
        st.update(style)
    if st:
        props['style'] = st
    if extra_props:
        props.update(extra_props)
    c = {'type': 'ia.display.label', 'meta': {'name': name},
         'props': props}
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    return c

def flex(name, direction, children, classes=None, position=None,
         justify=None, align=None, wrap=None, extra_props=None,
         prop_config=None, style=None, scripts=None):
    props = {'direction': direction}
    if justify:
        props['justify'] = justify
    if align:
        props['alignItems'] = align
    if wrap:
        props['wrap'] = wrap
    st = {}
    if classes:
        st['classes'] = classes
    if style:
        st.update(style)
    if st:
        props['style'] = st
    if extra_props:
        props.update(extra_props)
    c = {'type': 'ia.container.flex', 'meta': {'name': name},
         'props': props, 'children': children}
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    if scripts:
        c['scripts'] = scripts
    return c

def button(name, text, classes=None, position=None, prop_config=None,
           events=None, style=None):
    props = {'text': text}
    st = {}
    if classes:
        st['classes'] = classes
    if style:
        st.update(style)
    if st:
        props['style'] = st
    c = {'type': 'ia.input.button', 'meta': {'name': name},
         'props': props}
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    if events:
        c['events'] = events
    return c

def script_event(script):
    return {'dom': {'onClick': {'scope': 'G', 'type': 'script',
                                'config': {'script': script}}}}

def lib_event(call):
    """A click handler that is one thin call into the library."""
    return script_event("\timport roastery.core, roastery.batches\n\t" + call + "\n")

def embed(name, path, params, position, prop_config=None):
    c = {'type': 'ia.display.view', 'meta': {'name': name},
         'props': {'path': path, 'params': params},
         'position': position}
    if prop_config:
        c['propConfig'] = prop_config
    return c

# ---------------------------------------------------------------- expressions

def mmss_int(sec_expr):
    return (f"numberFormat(floor({sec_expr} / 60), '00') + ':' + "
            f"numberFormat({sec_expr} % 60, '00')")

def mmss_ms(ms_expr):
    return (f"numberFormat(floor({ms_expr} / 60000), '00') + ':' + "
            f"numberFormat(floor(({ms_expr} / 1000) % 60), '00')")

ELAPSED_MS = f"(now() - {ref(T('StartTime'))})"
ELAPSED_SEC = f"({ELAPSED_MS} / 1000)"

POPUP_OPEN = {
    'dom': {'onClick': {
        'scope': 'C', 'type': 'popup',
        'config': {'type': 'open', 'id': 'roastery-config',
                   'viewPath': 'Views/Config',
                   'title': 'Roast Setup', 'modal': True,
                   'showCloseIcon': True, 'draggable': True,
                   'resizable': True, 'overlayDismiss': True,
                   'position': {'width': 'min(700px, 94vw)',
                                'height': 'min(880px, 94vh)'}}}}}

POPUP_CLOSE = {
    'dom': {'onClick': {'scope': 'C', 'type': 'popup',
                         'config': {'type': 'close',
                                    'id': 'roastery-config'}}}}

# ================================================================ library
# The roastery package: two modules. code.py files use normal Python
# indentation. A script package folder carries no code.py of its own;
# modules are subfolders (verified on this gateway).

CORE_CODE = '''# Roastery core library: roast flow control, RoR derivation, curve
# sampling, event stamping, overlay building, and form handling.
#
# Every Perspective component handler, view startup script and tag
# event script in this project is a thin call into this package (or
# roastery.batches). The logic lives here so it can be read and
# reused from any scope. The gateway scripting project is Roastery,
# so tag event scripts can import this module too.
#
# B is the one CurrentBatch UDT instance; tag paths are built from it
# in exactly one place.

B = '[default]Roastery/CurrentBatch'
EVENTS_LOG = '[default]Roastery/EventsLog'
CURVE_SAMPLES = '[default]Roastery/CurveSamples'
TARGET_DS = '[default]Roastery/TargetProfileDS'
BACKGROUND_DS = '[default]Roastery/BackgroundDS'
BACKGROUND_JSON = '[default]Roastery/BackgroundCurveJson'

FORM_MEMBERS = ['BeanName', 'Origin', 'Region', 'Farm', 'Altitude',
                'Variety', 'Process', 'HarvestYear', 'MoisturePct',
                'DensityGL', 'ChargeWeightG', 'TargetDropTempF',
                'RoastLevel', 'OperatorName', 'Notes', 'WeightOutG']
FORM_INTS = ('HarvestYear',)
FORM_FLOATS = ('MoisturePct', 'DensityGL', 'ChargeWeightG',
               'TargetDropTempF', 'WeightOutG')

EVENT_STEMS = ('DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
               'SecondCrackStart', 'SecondCrackEnd', 'Drop')
LOG_COLS = ['t_stamp', 'elapsedSec', 'kind', 'label', 'tempF', 'fan', 'heat']
CURVE_COLS = ['t_offset_sec', 't_stamp', 'bean_temp_f', 'rate_of_rise_f',
              'fan_level', 'heat_level']
SAMPLE_EVERY_SEC = 5


def path(member):
    return B + '/' + member


def read_members(members):
    qvs = system.tag.readBlocking([path(m) for m in members])
    return dict((m, qvs[i].value) for i, m in enumerate(members))


def write_members(pairs):
    system.tag.writeBlocking([path(m) for m, _v in pairs],
                             [v for _m, v in pairs])


def elapsed_sec(start, now=None):
    if start is None:
        return -1
    if now is None:
        now = system.date.now()
    return int((now.getTime() - start.getTime()) / 1000)


def empty_dataset(cols):
    return system.dataset.toDataSet(cols, [])


# system.dataset.toDataSet with zero rows types every column as
# String, and a dataset tag initialized over REST has the same
# problem: every cell then round trips as text. Seeding one typed
# row and deleting it produces a dataset whose columns keep their
# real types (Double, Date, Integer), so build empties this way.
CURVE_SEED = [0.0, None, 0.0, 0.0, 0, 0]
LOG_SEED = [None, 0.0, '', '', 0.0, 0, 0]


def typed_empty_dataset(cols, seed):
    row = list(seed)
    for i, v in enumerate(row):
        if v is None:
            row[i] = system.date.now()
    ds = system.dataset.toDataSet(cols, [row])
    return system.dataset.deleteRow(ds, 0)


def empty_curve_dataset():
    return typed_empty_dataset(CURVE_COLS, CURVE_SEED)


def empty_log_dataset():
    return typed_empty_dataset(LOG_COLS, LOG_SEED)


def coerce_ts(value):
    """Normalize a dataset timestamp cell to a java.util.Date.

    Cells read back from a string typed dataset arrive as unicode
    ('yyyy-MM-dd HH:mm:ss.SSS'); typed datasets give real Dates and
    some paths give epoch millis."""
    if value is None:
        return None
    import java.util.Date as _JDate
    if isinstance(value, _JDate):
        return value
    if isinstance(value, (int, long, float)):
        return _JDate(long(value))
    for fmt in ('yyyy-MM-dd HH:mm:ss.SSS', 'yyyy-MM-dd HH:mm:ss'):
        try:
            return system.date.parse(str(value), fmt)
        except Exception:
            pass
    return None


def append_log(kind, label, temp, elapsed, when, fan=None, heat=None):
    """Append one row to the EventsLog dataset (trace chart source)."""
    log = system.tag.readBlocking([EVENTS_LOG])[0].value
    if log is None or log.rowCount == 0:
        log = empty_log_dataset()
    log = system.dataset.addRow(log, [when, float(max(elapsed, 0)), kind,
                                      label, float(temp), fan, heat])
    system.tag.writeBlocking([EVENTS_LOG], [log])


# ---------------------------------------------------------------- RoR

def on_bean_temp(tag_path, current_value, initial_change):
    """BeanTempF valueChanged handler. The tag event script is a one
    line call to this function.

    Derives RateOfRiseF as an exponentially smoothed delta per minute
    (tau = RoRSmoothingSec). Scratch state (previous sample temp and
    timestamp) lives in the _RoRPrevTempF and _RoRPrevMs members.
    While State is Roasting it also appends throttled samples to the
    CurveSamples dataset, which roastery.batches writes to the
    batch_series table at save time.
    """
    temp = current_value.value
    if temp is None:
        return
    now_ms = long(current_value.timestamp.getTime())
    if initial_change:
        write_members([('_RoRPrevTempF', temp), ('_RoRPrevMs', now_ms)])
        return
    vals = read_members(['_RoRPrevTempF', '_RoRPrevMs', 'RoRSmoothingSec',
                         'RateOfRiseF', 'State', 'StartTime', 'FanLevel',
                         'HeatLevel'])
    prev_temp = vals['_RoRPrevTempF']
    prev_ms = vals['_RoRPrevMs']
    tau = vals['RoRSmoothingSec']
    if prev_temp is None or prev_ms is None or prev_ms <= 0 or tau is None or tau <= 0:
        write_members([('_RoRPrevTempF', temp), ('_RoRPrevMs', now_ms)])
        return
    dt = (now_ms - prev_ms) / 1000.0
    if dt <= 0:
        return
    if abs(temp - prev_temp) > 50.0:
        # Probe jump (transport switch or simulator program wrap):
        # reseed the scratch sample instead of deriving a spike.
        write_members([('_RoRPrevTempF', temp), ('_RoRPrevMs', now_ms)])
        return
    inst = (temp - prev_temp) * 60.0 / dt
    inst = max(-60.0, min(120.0, inst))
    alpha = dt / (float(tau) + dt)
    old = vals['RateOfRiseF']
    if old is None:
        old = inst
    new_ror = old + alpha * (inst - old)
    write_members([('RateOfRiseF', new_ror), ('_RoRPrevTempF', temp),
                   ('_RoRPrevMs', now_ms)])
    if vals['State'] == 'Roasting' and vals['StartTime'] is not None:
        elapsed = int((now_ms - vals['StartTime'].getTime()) / 1000)
        append_curve_sample(elapsed, current_value.timestamp, temp,
                            new_ror, vals['FanLevel'], vals['HeatLevel'])


def append_curve_sample(elapsed, t_stamp, temp, ror, fan, heat):
    ds = system.tag.readBlocking([CURVE_SAMPLES])[0].value
    if ds is None or ds.rowCount == 0:
        # An empty read also heals a legacy string typed dataset:
        # the tag value is replaced with a properly typed one.
        ds = empty_curve_dataset()
    if ds.rowCount > 0:
        last = ds.getValueAt(ds.rowCount - 1, 't_offset_sec')
        if last is not None and elapsed - int(float(last)) < SAMPLE_EVERY_SEC:
            return
    ds = system.dataset.addRow(ds, [float(elapsed), t_stamp, float(temp),
                                    float(ror), int(fan), int(heat)])
    system.tag.writeBlocking([CURVE_SAMPLES], [ds])


def clear_curve_samples():
    system.tag.writeBlocking([CURVE_SAMPLES], [empty_curve_dataset()])


def curve_points():
    """Recorded curve samples as a list of dicts, oldest first."""
    ds = system.tag.readBlocking([CURVE_SAMPLES])[0].value
    points = []
    if ds is None:
        return points
    # Dataset cells can round trip through the tag as strings on
    # this beta, so every numeric read coerces through float().
    for r in range(ds.rowCount):
        fan = ds.getValueAt(r, 'fan_level')
        heat = ds.getValueAt(r, 'heat_level')
        points.append({
            't': int(float(ds.getValueAt(r, 't_offset_sec'))),
            'ts': coerce_ts(ds.getValueAt(r, 't_stamp')),
            'bt': float(ds.getValueAt(r, 'bean_temp_f')),
            'ror': float(ds.getValueAt(r, 'rate_of_rise_f')),
            'fan': int(float(fan)) if fan is not None else None,
            'heat': int(float(heat)) if heat is not None else None})
    return points


# ---------------------------------------------------------------- events

def _stamp(stem, label):
    vals = read_members(['BeanTempF', 'StartTime'])
    now = system.date.now()
    elapsed = elapsed_sec(vals['StartTime'], now)
    write_members([(stem + 'Time', now), (stem + 'TempF', vals['BeanTempF']),
                   (stem + 'ElapsedSec', elapsed)])
    append_log('event', label, vals['BeanTempF'], elapsed, now)
    return elapsed


def stamp_event(stem, label):
    """Record one standard roast event (Controls event buttons)."""
    _stamp(stem, label)


def stamp_custom(index):
    """Record one of the four customizable events."""
    name_member = 'CustomEvent%dName' % index
    vals = read_members(['BeanTempF', 'StartTime', name_member])
    now = system.date.now()
    elapsed = elapsed_sec(vals['StartTime'], now)
    stem = 'CustomEvent%d' % index
    write_members([(stem + 'Time', now), (stem + 'TempF', vals['BeanTempF']),
                   (stem + 'ElapsedSec', elapsed)])
    append_log('event', vals[name_member], vals['BeanTempF'], elapsed, now)


def _clear_events():
    pairs = []
    for stem in EVENT_STEMS:
        pairs += [(stem + 'Time', None), (stem + 'TempF', 0.0),
                  (stem + 'ElapsedSec', -1)]
    for i in (1, 2, 3, 4):
        stem = 'CustomEvent%d' % i
        pairs += [(stem + 'Time', None), (stem + 'TempF', 0.0),
                  (stem + 'ElapsedSec', -1)]
    write_members(pairs)


def _clear_log():
    system.tag.writeBlocking([EVENTS_LOG], [empty_log_dataset()])


# ---------------------------------------------------------------- flow

def charge():
    vals = read_members(['BeanTempF', 'FanLevel', 'HeatLevel'])
    now = system.date.now()
    write_members([('State', 'Roasting'), ('StartTime', now),
                   ('ChargeTime', now), ('ChargeTempF', vals['BeanTempF']),
                   ('Mode', 'Roast'), ('WeightOutG', 0.0)])
    _clear_events()
    clear_curve_samples()
    _clear_log()
    append_log('event', 'Charge', vals['BeanTempF'], 0, now,
               float(vals['FanLevel']), float(vals['HeatLevel']))
    build_overlays()


def drop():
    _stamp('Drop', 'Drop')
    write_members([('State', 'Dropped'), ('Mode', 'Cool')])
    build_overlays()


def cool():
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Cooling')])
    append_log('state', 'Cooling', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())


def finish():
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Complete')])
    append_log('state', 'Finished', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())


def reset_batch():
    write_members([('State', 'Idle'), ('Mode', 'Off'), ('StartTime', None),
                   ('ChargeTime', None), ('ChargeTempF', 0.0),
                   ('WeightOutG', 0.0), ('RateOfRiseF', 0.0),
                   ('_RoRPrevTempF', 0.0), ('_RoRPrevMs', 0)])
    _clear_events()
    clear_curve_samples()
    _clear_log()


def stepper(member, delta, label):
    """Fan and Heat steppers (SR800 levels 1 to 9), with trace log."""
    vals = read_members([member, 'BeanTempF', 'StartTime', 'FanLevel',
                         'HeatLevel'])
    new = max(1, min(9, int(vals[member]) + int(delta)))
    if new == vals[member]:
        return
    write_members([(member, new)])
    fan = new if member == 'FanLevel' else vals['FanLevel']
    heat = new if member == 'HeatLevel' else vals['HeatLevel']
    append_log('stepper', label, vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now(),
               float(fan), float(heat))


# ---------------------------------------------------------------- overlays

def _plan_at(pts, s):
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if s <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (s - t0) / (t1 - t0)
    return pts[-1][1]


def build_overlays():
    """Rebuild the TargetProfileDS and BackgroundDS overlay datasets
    on the current roast's timeline. The background points come from
    the BackgroundCurveJson tag ([seconds, temp] pairs), which
    roastery.batches fills from the batch_series table."""
    from java.util import Date
    vals = read_members(['TargetChargeTempF', 'TargetDryEndSec',
                         'TargetDryEndTempF', 'TargetFCSec',
                         'TargetFCTempF', 'TargetDropSec',
                         'TargetDropTempF', 'StartTime'])
    start = vals['StartTime']
    if start is None:
        return
    pts = [(0.0, vals['TargetChargeTempF']),
           (float(vals['TargetDryEndSec']), vals['TargetDryEndTempF']),
           (float(vals['TargetFCSec']), vals['TargetFCTempF']),
           (float(vals['TargetDropSec']), vals['TargetDropTempF'])]
    start_ms = start.getTime()
    rows = []
    s = 0.0
    while s < pts[-1][0]:
        rows.append([Date(long(start_ms + s * 1000)), _plan_at(pts, s)])
        s += 15.0
    rows.append([Date(long(start_ms + pts[-1][0] * 1000)), pts[-1][1]])
    bg_rows = []
    bg_json = system.tag.readBlocking([BACKGROUND_JSON])[0].value
    if bg_json:
        for pair in system.util.jsonDecode(bg_json):
            bg_rows.append([Date(long(start_ms + float(pair[0]) * 1000)),
                            float(pair[1])])
    system.tag.writeBlocking(
        [TARGET_DS, BACKGROUND_DS],
        [system.dataset.toDataSet(['t_stamp', 'plan'], rows),
         system.dataset.toDataSet(['t_stamp', 'bg'], bg_rows)])


# ---------------------------------------------------------------- forms

def coerce(member, value):
    """Form payloads carry numbers as strings; coerce per member."""
    if member in FORM_INTS:
        return int(float(value))
    if member in FORM_FLOATS:
        return float(value)
    return str(value)


def config_form_data():
    """Prefill payload for the Config popup metadata form."""
    vals = read_members(FORM_MEMBERS)
    data = {}
    for m in FORM_MEMBERS:
        v = vals[m]
        if v is None:
            v = 0 if m in FORM_INTS else (0.0 if m in FORM_FLOATS else '')
        else:
            v = coerce(m, v)
        data[m] = v
    return data


def config_submit(self, event):
    """Config popup form submit: coerce the payload onto the batch
    tags and mirror the WebSocket URL into the WebSocket source."""
    paths = []
    values = []
    for k in FORM_MEMBERS:
        if k not in event:
            continue
        v = event[k]
        if v is None:
            continue
        try:
            v = coerce(k, v)
        except Exception:
            continue
        paths.append(path(k))
        values.append(v)
    if paths:
        system.tag.writeBlocking(paths, values)
    ws = read_members(['WsUrl'])['WsUrl']
    system.tag.writeBlocking([B + '/Sources/WebSocket/WsUrl',
                              B + '/Sources/WebSocket/Address'], [ws, ws])
    self.view.custom.formSaved = 'Batch details saved.'


# ---------------------------------------------------------------- session

def main_startup(self):
    self.view.custom.themeText = 'Theme: ' + str(self.session.props.theme)


def theme_toggle(self):
    cur = self.session.props.theme
    new = 'light' if cur == 'dark' else 'dark'
    self.session.props.theme = new
    self.view.custom.themeText = 'Theme: ' + new
'''

BATCHES_CODE = '''# Roastery batch persistence: full CRUD for previous batches in
# Postgres, through NAMED QUERIES only. This module is the only
# caller of the batch named queries; no view binding or handler
# carries SQL.
#
# Data model (docs: roastery/docs/coffee-roaster-app.md):
# - batches: surrogate id PK, batch_number UNIQUE (the human batch
#   number), relational columns only for listing and sorting
#   (roast_start, roast_end, bean_name, drop_temp_f), and a `data`
#   JSONB column with the complete batch document (metadata, events
#   with times and temps, phase durations, DTR, AUC, weights, roast
#   degree, target profile, notes), so the batch schema can evolve
#   without migrations.
# - batch_series: one row per curve sample keyed by batch_number
#   (FK, ON DELETE CASCADE): t_offset_sec, sample_ts, bean_temp_f,
#   rate_of_rise_f, fan_level, heat_level. Written at save time from
#   the CurveSamples dataset roastery.core records during the roast,
#   through Series/InsertBatch (one call; the points travel as a
#   JSON array parameter unpacked in SQL). View as Background reads
#   the series back through Series/SelectByBatch, so every batch
#   carries its own curve like an Artisan roast file.

import roastery.core as core

NQ_SELECT_ALL = 'Roastery/Batches/SelectAll'
NQ_SELECT_BY_ID = 'Roastery/Batches/SelectById'
NQ_INSERT = 'Roastery/Batches/Insert'
NQ_UPDATE = 'Roastery/Batches/Update'
NQ_DELETE = 'Roastery/Batches/Delete'
NQ_SERIES_INSERT = 'Roastery/Series/InsertBatch'
NQ_SERIES_SELECT = 'Roastery/Series/SelectByBatch'

BACKGROUND_LABEL = '[default]Roastery/BackgroundLabel'
ROASTLOG_TAG = '[default]Roastery/RoastLog'
REFRESH_MESSAGE = 'roastery-batches-refresh'


def _run(path, params=None):
    return system.db.runNamedQuery(path, params or {})


def _iso(dt):
    if dt is None:
        return None
    return system.date.format(dt, "yyyy-MM-dd'T'HH:mm:ss")


def _doc_of(cell):
    """SelectById returns the JSONB document as JSON text."""
    if cell is None:
        return {}
    if isinstance(cell, basestring):
        return system.util.jsonDecode(cell)
    return system.util.jsonDecode(str(cell))


# ---------------------------------------------------------------- document

def roast_degree(drop_temp_f):
    t = drop_temp_f or 0.0
    if t < 390:
        return 'Cinnamon'
    if t < 396:
        return 'New England'
    if t < 401:
        return 'American'
    if t < 406:
        return 'City'
    if t < 411:
        return 'City+'
    if t < 416:
        return 'Full City'
    if t < 421:
        return 'Full City+'
    if t < 426:
        return 'Vienna'
    if t < 436:
        return 'French'
    return 'Italian'


def curve_auc(points, charge_temp_f):
    """Trapezoid area between the bean curve and the charge temp, in
    degree F minutes (same definition as the v2 roast log save)."""
    auc = 0.0
    base = charge_temp_f or 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        dt_min = (b['t'] - a['t']) / 60.0
        if dt_min <= 0:
            continue
        avg = (a['bt'] + b['bt']) / 2.0
        if avg > base:
            auc += (avg - base) * dt_min
    return auc


def _event_doc(vals, stem):
    elapsed = vals[stem + 'ElapsedSec']
    if elapsed is None or elapsed < 0:
        return None
    return {'t': elapsed, 'ts': _iso(vals[stem + 'Time']),
            'tempF': vals[stem + 'TempF']}


def _trace_summary():
    ds = system.tag.readBlocking([core.EVENTS_LOG])[0].value
    out = []
    if ds is None:
        return out
    for r in range(ds.rowCount):
        if ds.getValueAt(r, 'kind') == 'stepper':
            out.append({'t': float(ds.getValueAt(r, 'elapsedSec')),
                        'label': ds.getValueAt(r, 'label'),
                        'fan': float(ds.getValueAt(r, 'fan')),
                        'heat': float(ds.getValueAt(r, 'heat'))})
    return out


def build_document():
    """Assemble the JSONB batch document from the CurrentBatch tags."""
    members = ['BatchNumber', 'BeanName', 'ChargeTime', 'DropTime',
               'ChargeTempF', 'DropTempF', 'DropElapsedSec',
               'ActiveSource']
    members += list(core.FORM_MEMBERS)
    for stem in ('DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
                 'SecondCrackStart', 'SecondCrackEnd', 'Drop'):
        members += [stem + 'Time', stem + 'TempF', stem + 'ElapsedSec']
    for i in (1, 2, 3, 4):
        members += ['CustomEvent%dName' % i, 'CustomEvent%dKind' % i,
                    'CustomEvent%dTime' % i, 'CustomEvent%dTempF' % i,
                    'CustomEvent%dElapsedSec' % i]
    members += ['TargetChargeTempF', 'TargetDryEndSec',
                'TargetDryEndTempF', 'TargetFCSec', 'TargetFCTempF',
                'TargetDropSec', 'TargetDropTempF']
    vals = core.read_members(members)
    total = vals['DropElapsedSec'] or 0
    dry = vals['DryEndElapsedSec']
    dry = dry if dry is not None and dry >= 0 else 0
    fc = vals['FirstCrackStartElapsedSec']
    fc = fc if fc is not None and fc >= 0 else total
    charge_w = vals['ChargeWeightG'] or 0.0
    out_w = vals['WeightOutG'] or 0.0
    loss = ((charge_w - out_w) * 100.0 / charge_w) if out_w > 0 and charge_w > 0 else 0.0
    return {
        'batchNumber': vals['BatchNumber'],
        'beanName': vals['BeanName'],
        'roastStart': _iso(vals['ChargeTime']),
        'roastEnd': _iso(vals['DropTime']),
        'dropTempF': vals['DropTempF'],
        'roastDegree': roast_degree(vals['DropTempF']),
        'totalSec': total,
        'phases': {'dryingSec': dry, 'maillardSec': fc - dry,
                   'developmentSec': total - fc,
                   'dtrPct': ((total - fc) * 100.0 / total) if total > 0 else 0.0},
        'auc': curve_auc(core.curve_points(), vals['ChargeTempF']),
        'weightLossPct': loss,
        'source': vals['ActiveSource'],
        'metadata': dict((m, vals[m]) for m in core.FORM_MEMBERS),
        'events': {
            'charge': {'t': 0, 'ts': _iso(vals['ChargeTime']),
                       'tempF': vals['ChargeTempF']},
            'dryEnd': _event_doc(vals, 'DryEnd'),
            'fcStart': _event_doc(vals, 'FirstCrackStart'),
            'fcEnd': _event_doc(vals, 'FirstCrackEnd'),
            'scStart': _event_doc(vals, 'SecondCrackStart'),
            'scEnd': _event_doc(vals, 'SecondCrackEnd'),
            'drop': _event_doc(vals, 'Drop'),
            'custom': [
                {'name': vals['CustomEvent%dName' % i],
                 'kind': vals['CustomEvent%dKind' % i],
                 't': vals['CustomEvent%dElapsedSec' % i],
                 'tempF': vals['CustomEvent%dTempF' % i]}
                for i in (1, 2, 3, 4)
                if vals['CustomEvent%dElapsedSec' % i] is not None
                and vals['CustomEvent%dElapsedSec' % i] >= 0]},
        'target': {'chargeTempF': vals['TargetChargeTempF'],
                   'dryEndSec': vals['TargetDryEndSec'],
                   'dryEndTempF': vals['TargetDryEndTempF'],
                   'fcSec': vals['TargetFCSec'],
                   'fcTempF': vals['TargetFCTempF'],
                   'dropSec': vals['TargetDropSec'],
                   'dropTempF': vals['TargetDropTempF']},
        'fanHeatTrace': _trace_summary()}


# ---------------------------------------------------------------- CRUD

def get_batch(batch_number):
    ds = _run(NQ_SELECT_BY_ID, {'batch_number': int(batch_number)})
    if ds.rowCount == 0:
        return None
    return {'id': ds.getValueAt(0, 'id'),
            'batchNumber': ds.getValueAt(0, 'batch_number'),
            'roastStart': ds.getValueAt(0, 'roast_start'),
            'roastEnd': ds.getValueAt(0, 'roast_end'),
            'beanName': ds.getValueAt(0, 'bean_name'),
            'dropTempF': ds.getValueAt(0, 'drop_temp_f'),
            'document': _doc_of(ds.getValueAt(0, 'data'))}


def delete_batch(batch_number):
    """Delete named query; batch_series rows cascade in Postgres."""
    return _run(NQ_DELETE, {'batch_number': int(batch_number)})


def _insert_series(batch_number, points):
    if not points:
        return 0
    payload = []
    for p in points:
        item = {'t': p['t'], 'bt': p['bt'], 'ror': p['ror']}
        if p.get('ts') is not None:
            item['ts'] = system.date.format(p['ts'], "yyyy-MM-dd'T'HH:mm:ss.SSSZ")
        if p.get('fan') is not None:
            item['fan'] = p['fan']
        if p.get('heat') is not None:
            item['heat'] = p['heat']
        payload.append(item)
    return _run(NQ_SERIES_INSERT, {
        'batch_number': int(batch_number),
        'points': system.util.jsonEncode(payload)})


def save_current_batch(self):
    """Summary view Save button: persist the finished roast through
    the Insert named query, then its recorded curve through
    Series/InsertBatch."""
    vals = core.read_members(['BatchNumber', 'BeanName', 'ChargeTime',
                              'DropTime', 'DropTempF'])
    doc = build_document()
    _run(NQ_INSERT, {
        'batch_number': vals['BatchNumber'],
        'roast_start': vals['ChargeTime'],
        'roast_end': vals['DropTime'],
        'bean_name': vals['BeanName'],
        'drop_temp_f': vals['DropTempF'],
        'data': system.util.jsonEncode(doc)})
    _insert_series(vals['BatchNumber'], core.curve_points())
    self.view.custom.saveNote = 'Saved batch %d to the database.' % vals['BatchNumber']
    return vals['BatchNumber']


# ---------------------------------------------------------------- edit form

def _apply_form(doc, payload):
    meta = dict(doc.get('metadata') or {})
    for k in core.FORM_MEMBERS:
        if k not in payload:
            continue
        v = payload[k]
        if v is None:
            continue
        try:
            meta[k] = core.coerce(k, v)
        except Exception:
            continue
    doc['metadata'] = meta
    if meta.get('BeanName'):
        doc['beanName'] = meta['BeanName']
    return doc


def edit_form_data_for(view):
    """BatchEdit popup prefill (called from the view onStartup, so it
    receives the view). In create mode the form starts blank except
    the bean defaults; in edit mode it comes from the stored batch
    document (SelectById)."""
    if view.params.createMode:
        return {'BeanName': '', 'Origin': '', 'Region': '', 'Farm': '',
                'Altitude': '', 'Variety': '', 'Process': '',
                'HarvestYear': 2025, 'MoisturePct': 0.0,
                'DensityGL': 0.0, 'ChargeWeightG': 200.0,
                'TargetDropTempF': 415.0, 'RoastLevel': '',
                'OperatorName': '', 'Notes': '', 'WeightOutG': 0.0,
                'BatchNumber': 0}
    batch = get_batch(view.params.batchNumber)
    if batch is None:
        return {}
    meta = dict(batch['document'].get('metadata') or {})
    data = {}
    for m in core.FORM_MEMBERS:
        v = meta.get(m)
        if v is None:
            v = 0 if m in core.FORM_INTS else (0.0 if m in core.FORM_FLOATS else '')
        data[m] = v
    data['BatchNumber'] = batch['batchNumber']
    return data


def batch_edit_submit(self, event):
    """BatchEdit popup form submit for both modes."""
    if self.view.params.createMode:
        _create_submit(self, event)
    else:
        _update_submit(self, event)


def _update_submit(self, event):
    batch_number = int(self.view.params.batchNumber or 0)
    batch = get_batch(batch_number)
    if batch is None:
        self.view.custom.editNote = 'Batch %d no longer exists.' % batch_number
        return
    doc = _apply_form(batch['document'], event)
    _run(NQ_UPDATE, {
        'batch_number': batch_number,
        'bean_name': doc.get('beanName'),
        'drop_temp_f': batch['dropTempF'],
        'data': system.util.jsonEncode(doc)})
    self.view.custom.editNote = 'Saved batch %d.' % batch_number
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')


def _create_submit(self, event):
    try:
        number = int(float(event['BatchNumber']))
    except Exception:
        number = 0
    if not number:
        self.view.custom.editNote = 'Enter a batch number to create.'
        return
    if get_batch(number) is not None:
        self.view.custom.editNote = 'Batch %d already exists.' % number
        return
    doc = {'batchNumber': number, 'beanName': '', 'roastDegree': '',
           'totalSec': 0, 'phases': {}, 'events': {}, 'metadata': {},
           'manualEntry': True}
    doc = _apply_form(doc, event)
    now = system.date.now()
    _run(NQ_INSERT, {
        'batch_number': number, 'roast_start': now, 'roast_end': now,
        'bean_name': doc.get('beanName') or '', 'drop_temp_f': 0.0,
        'data': system.util.jsonEncode(doc)})
    self.view.custom.editNote = 'Created batch %d.' % number
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')


# ---------------------------------------------------------------- Batches page

def select_row(self, event):
    """Batches table row click: remember the selection in view
    custom props (the action buttons act on it)."""
    row = event.value
    try:
        number = row['batch_number']
        bean = row['bean_name']
    except Exception:
        number = row.get('batch_number')
        bean = row.get('bean_name')
    self.view.custom.selBatchNumber = int(number) if number is not None else 0
    self.view.custom.selLabel = 'Batch %s - %s' % (number, bean)
    self.view.custom.selNote = ('Selected batch %s (%s). Edit it, delete it, '
                                'or view it as a background.' % (number, bean))
    self.view.custom.confirmDelete = False


def refresh_table(self):
    """Re-run the table's SelectAll binding. Called by the panel's
    refresh message handler (self is the panel root) and by panel
    actions such as confirm_delete (self is a component in the
    panel); resolve the table either way. Note: self.view.root is
    not a valid path in this scripting model."""
    table = self.getChild('BatchTable')
    if table is None:
        # getChild returns None (does not raise) when the child is
        # not under this component; resolve from the view root.
        table = self.view.getChild('root').getChild('BatchTable')
    table.refreshBinding('props.data')


def open_editor(self, create=False):
    number = 0 if create else int(self.view.custom.selBatchNumber or 0)
    if not create and number <= 0:
        return
    system.perspective.openPopup(
        'roastery-batch-edit', 'Views/BatchEdit',
        {'batchNumber': number, 'createMode': bool(create)},
        {'title': 'New Batch' if create else 'Edit Batch %d' % number,
         'modal': True, 'showCloseIcon': True, 'draggable': True,
         'resizable': True, 'overlayDismiss': True,
         'position': {'width': 'min(660px, 94vw)',
                      'height': 'min(780px, 94vh)'}})


def arm_delete(self):
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    self.view.custom.confirmDelete = True
    self.view.custom.selNote = ('Delete batch %d and its curve? '
                                'Press Confirm Delete to proceed.' % number)


def cancel_delete(self):
    self.view.custom.confirmDelete = False
    self.view.custom.selNote = 'Delete cancelled.'


def confirm_delete(self):
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    delete_batch(number)
    self.view.custom.confirmDelete = False
    self.view.custom.selBatchNumber = 0
    self.view.custom.selLabel = ''
    self.view.custom.selNote = 'Deleted batch %d.' % number
    # Refresh through the panel's message handler (self is the
    # panel root there), the same path the edit popup saves use.
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')


def set_background(self):
    """View as Background: read the selected batch's curve from the
    batch_series table (Series/SelectByBatch) and stage it as the
    Main background overlay, then navigate to the console."""
    batch_number = int(self.view.custom.selBatchNumber or 0)
    if batch_number <= 0:
        return
    ds = _run(NQ_SERIES_SELECT, {'batch_number': batch_number})
    pairs = []
    for r in range(ds.rowCount):
        pairs.append([ds.getValueAt(r, 't_offset_sec'),
                      ds.getValueAt(r, 'bean_temp_f')])
    batch = get_batch(batch_number)
    label = 'Batch %d' % batch_number
    if batch is not None and batch['beanName']:
        label += ' - ' + batch['beanName']
    system.tag.writeBlocking(
        [core.BACKGROUND_JSON, BACKGROUND_LABEL],
        [system.util.jsonEncode(pairs), label])
    core.build_overlays()
    system.perspective.navigate(page='/')


# ---------------------------------------------------------------- seed

def seed_from_roastlog():
    """One time migration: copy the legacy RoastLog dataset tag rows
    into the batches and batch_series tables. All seven legacy rows
    carry batch number 1042 (v2 test saves), so duplicates are
    renumbered in chronological order and each document records
    seededFromRoastLog and originalBatchNumber. Curve points come
    from the stored curveJson ([seconds, temp] pairs); rate of rise
    is derived by finite difference; fan and heat were not recorded
    in v2 and stay null. Returns the number of batches inserted."""
    from java.util import Date
    ds = system.tag.readBlocking([ROASTLOG_TAG])[0].value
    if ds is None or ds.rowCount == 0:
        return 0
    existing = set()
    all_ds = _run(NQ_SELECT_ALL)
    for r in range(all_ds.rowCount):
        existing.add(all_ds.getValueAt(r, 'batch_number'))
    rows = []
    for r in range(ds.rowCount):
        rows.append(dict((c, ds.getValueAt(r, c)) for c in ds.columnNames))
    rows.sort(key=lambda d: d['roastDate'])
    inserted = 0
    next_number = 1042
    for row in rows:
        while next_number in existing:
            next_number += 1
        number = next_number
        existing.add(number)
        total = row['totalSec'] or 0.0
        end = row['roastDate']
        start = Date(long(end.getTime() - total * 1000)) if end is not None else None
        charge_g = row['chargeG'] or 0.0
        loss = row['weightLossPct'] or 0.0
        doc = {
            'batchNumber': number,
            'beanName': row['bean'],
            'roastStart': _iso(start),
            'roastEnd': _iso(end),
            'dropTempF': row['dropTempF'],
            'roastDegree': row['level'],
            'totalSec': total,
            'phases': {'dryingSec': row['drySec'],
                       'maillardSec': row['maillardSec'],
                       'developmentSec': row['devSec'],
                       'dtrPct': row['dtrPct']},
            'auc': row['auc'],
            'weightLossPct': loss,
            'seededFromRoastLog': True,
            'originalBatchNumber': row['batch'],
            'metadata': {'BeanName': row['bean'], 'Origin': row['origin'],
                         'ChargeWeightG': charge_g,
                         'WeightOutG': charge_g * (1.0 - loss / 100.0)},
            'events': {'charge': {'t': 0, 'ts': _iso(start),
                                  'tempF': None},
                       'drop': {'t': total, 'ts': _iso(end),
                                'tempF': row['dropTempF']}}}
        _run(NQ_INSERT, {
            'batch_number': number, 'roast_start': start,
            'roast_end': end, 'bean_name': row['bean'],
            'drop_temp_f': row['dropTempF'],
            'data': system.util.jsonEncode(doc)})
        pairs = system.util.jsonDecode(row['curveJson'] or '[]')
        by_sec = {}
        for sec, temp in pairs:
            by_sec[int(round(sec))] = temp
        secs = sorted(by_sec.keys())
        points = []
        for i, sec in enumerate(secs):
            if 0 < i < len(secs) - 1:
                ror = (by_sec[secs[i + 1]] - by_sec[secs[i - 1]]) * 60.0 / (secs[i + 1] - secs[i - 1])
            elif len(secs) > 1 and i == 0:
                ror = (by_sec[secs[1]] - by_sec[secs[0]]) * 60.0 / max(secs[1] - secs[0], 1)
            elif len(secs) > 1:
                ror = (by_sec[secs[-1]] - by_sec[secs[-2]]) * 60.0 / max(secs[-1] - secs[-2], 1)
            else:
                ror = 0.0
            ts = Date(long(start.getTime() + sec * 1000)) if start is not None else None
            points.append({'t': sec, 'ts': ts, 'bt': by_sec[sec],
                           'ror': ror})
        _insert_series(number, points)
        inserted += 1
    return inserted
'''

# ================================================================ named queries
# Resource format verified empirically on this gateway: folder
# ignition/named-query/<path>/ holding query.sql and a resource.json
# with "version": 2 and typed attributes. Parameters are
# {"type": "Parameter", "identifier": name, "sqlType": int} with
# DataType ints Int4=2, Float8=5, String=7, DateTime=8. cacheUnit is
# omitted (the beta throws deserializing it when caching is off).

NQ_INT4, NQ_FLOAT8, NQ_STRING, NQ_DATETIME = 2, 5, 7, 8

NAMED_QUERIES = [
    ('Roastery/Batches/SelectAll', 'Query',
     "SELECT id, batch_number, roast_start, roast_end, bean_name, drop_temp_f,\n"
     "       data->>'roastDegree' AS roast_degree,\n"
     "       (data->'phases'->>'dtrPct')::double precision AS dtr_pct,\n"
     "       (data->'metadata'->>'ChargeWeightG')::double precision AS charge_g,\n"
     "       (data->'metadata'->>'WeightOutG')::double precision AS weight_out_g,\n"
     "       data->'metadata'->>'Origin' AS origin,\n"
     "       (data->>'totalSec')::double precision AS total_sec\n"
     "FROM batches\n"
     "ORDER BY roast_start DESC NULLS LAST, batch_number DESC",
     []),
    ('Roastery/Batches/SelectById', 'Query',
     "SELECT id, batch_number, roast_start, roast_end, bean_name, drop_temp_f, data\n"
     "FROM batches WHERE batch_number = :batch_number",
     [('batch_number', NQ_INT4)]),
    ('Roastery/Batches/Insert', 'Query',
     "INSERT INTO batches (batch_number, roast_start, roast_end, bean_name, drop_temp_f, data)\n"
     "VALUES (:batch_number, :roast_start, :roast_end, :bean_name, :drop_temp_f, CAST(:data AS jsonb))\n"
     "RETURNING id",
     [('batch_number', NQ_INT4), ('roast_start', NQ_DATETIME),
      ('roast_end', NQ_DATETIME), ('bean_name', NQ_STRING),
      ('drop_temp_f', NQ_FLOAT8), ('data', NQ_STRING)]),
    ('Roastery/Batches/Update', 'UpdateQuery',
     "UPDATE batches SET bean_name = :bean_name, drop_temp_f = :drop_temp_f,\n"
     "       data = CAST(:data AS jsonb), updated_at = now()\n"
     "WHERE batch_number = :batch_number",
     [('batch_number', NQ_INT4), ('bean_name', NQ_STRING),
      ('drop_temp_f', NQ_FLOAT8), ('data', NQ_STRING)]),
    ('Roastery/Batches/Delete', 'UpdateQuery',
     "DELETE FROM batches WHERE batch_number = :batch_number",
     [('batch_number', NQ_INT4)]),
    ('Roastery/Series/InsertBatch', 'UpdateQuery',
     "INSERT INTO batch_series (batch_number, t_offset_sec, sample_ts, bean_temp_f, rate_of_rise_f, fan_level, heat_level)\n"
     "SELECT :batch_number, (e->>'t')::integer, (e->>'ts')::timestamptz,\n"
     "       (e->>'bt')::double precision, (e->>'ror')::double precision,\n"
     "       (e->>'fan')::integer, (e->>'heat')::integer\n"
     "FROM jsonb_array_elements(CAST(:points AS jsonb)) AS e",
     [('batch_number', NQ_INT4), ('points', NQ_STRING)]),
    ('Roastery/Series/SelectByBatch', 'Query',
     "SELECT t_offset_sec, sample_ts, bean_temp_f, rate_of_rise_f, fan_level, heat_level\n"
     "FROM batch_series WHERE batch_number = :batch_number ORDER BY t_offset_sec",
     [('batch_number', NQ_INT4)]),
]

def write_named_queries():
    for path, qtype, sql, params in NAMED_QUERIES:
        d = os.path.join(PROJ, 'ignition', 'named-query', *path.split('/'))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'query.sql'), 'w') as f:
            f.write(sql + '\n')
        attrs = {
            'type': qtype, 'database': 'db',
            'parameters': [{'type': 'Parameter', 'identifier': n,
                            'sqlType': t} for n, t in params],
            'permissions': [], 'enabled': True, 'fallbackEnabled': False,
            'fallbackValue': '', 'description': 'Roastery v3',
            'useMaxReturnSize': False, 'maxReturnSize': 1000,
            'cacheEnabled': False, 'cacheAmount': 1,
            'autoBatchEnabled': False}
        r = {'scope': 'G', 'version': 2, 'restricted': False,
             'overridable': True, 'files': ['query.sql'],
             'attributes': attrs}
        with open(os.path.join(d, 'resource.json'), 'w') as f:
            json.dump(r, f, indent=2)
    print('named queries written:', len(NAMED_QUERIES))

def write_library():
    base = os.path.join(PROJ, 'ignition', 'script-python', 'roastery')
    for mod, code in (('core', CORE_CODE), ('batches', BATCHES_CODE)):
        d = os.path.join(base, mod)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'code.py'), 'w') as f:
            f.write(code)
        r = {'scope': 'G', 'version': 1, 'restricted': False,
             'overridable': True, 'files': ['code.py'], 'attributes': {}}
        with open(os.path.join(d, 'resource.json'), 'w') as f:
            json.dump(r, f, indent=2)
    print('library modules written: roastery.core, roastery.batches')

# ================================================================ styles
# Style classes: com.inductiveautomation.perspective/style-classes/
# <name>/style.json = {"base": {"style": {...}}}. The advanced
# stylesheet holds .psc- prefixed global rules (Perspective prefixes
# style classes with psc- in the DOM).

STYLE_CLASSES = {
    'roast-app': {'backgroundColor': 'var(--containerRoot)',
                  'minHeight': '100%'},
    'roast-header': {
        'backgroundColor': 'var(--container)',
        'backgroundImage': 'linear-gradient(90deg, var(--container), var(--containerNested))',
        'padding': '10px 22px', 'boxShadow': 'var(--boxShadow1)',
        'gap': '10px'},
    'roast-title': {'fontSize': '21px', 'fontWeight': '700',
                    'color': 'var(--label)'},
    'roast-title-sm': {'fontSize': '19px', 'fontWeight': '700',
                       'color': 'var(--label)'},
    'roast-subtitle': {'fontSize': '12px', 'color': 'var(--neutral-70)'},
    'roast-card': {'backgroundColor': 'var(--container)',
                   'border': '1px solid var(--border)',
                   'borderRadius': '16px',
                   'boxShadow': 'var(--boxShadow2)',
                   'padding': '16px 18px'},
    'roast-card-sm': {'backgroundColor': 'var(--container)',
                      'border': '1px solid var(--border)',
                      'borderRadius': '16px',
                      'boxShadow': 'var(--boxShadow2)',
                      'padding': '12px 16px'},
    'roast-cell': {'backgroundColor': 'var(--containerNested)',
                   'border': '1px solid var(--border)',
                   'borderRadius': '12px', 'padding': '9px 6px',
                   'gap': '2px'},
    'roast-section-title': {'fontSize': '13px', 'fontWeight': '700',
                            'color': 'var(--callToAction)',
                            'textTransform': 'uppercase',
                            'letterSpacing': '0.08em'},
    'roast-caption': {'fontSize': '11px', 'fontWeight': '700',
                      'color': 'var(--neutral-60)',
                      'textTransform': 'uppercase',
                      'letterSpacing': '0.1em'},
    'roast-value': {'fontSize': '14px', 'fontWeight': '600',
                    'color': 'var(--label)'},
    'roast-value-strong': {'fontSize': '14px', 'fontWeight': '700',
                           'color': 'var(--label)'},
    'roast-value-lg': {'fontSize': '30px', 'fontWeight': '700',
                       'color': 'var(--label)', 'lineHeight': '1.05'},
    'roast-clock': {'fontSize': '27px', 'fontWeight': '700',
                    'color': 'var(--label)', 'fontFamily': 'monospace'},
    'roast-chip': {'fontSize': '13px', 'fontWeight': '600',
                   'color': 'var(--label)'},
    'roast-pill': {'fontSize': '12px', 'fontWeight': '700',
                   'color': '#ffffff', 'padding': '4px 14px',
                   'borderRadius': '999px', 'textAlign': 'center'},
    'roast-mode-pill': {'fontSize': '11px', 'fontWeight': '700',
                        'color': '#ffffff', 'padding': '3px 12px',
                        'borderRadius': '999px'},
    'roast-note': {'fontSize': '13px', 'color': 'var(--neutral-70)'},
    'roast-note-sm': {'fontSize': '11px', 'color': 'var(--neutral-60)'},
    'roast-note-success': {'fontSize': '13px', 'fontWeight': '700',
                           'color': 'var(--success)',
                           'minHeight': '18px'},
    'roast-banner': {'backgroundColor': '#991b1b',
                     'padding': '9px 22px',
                     'boxShadow': '0 0 18px rgba(239, 68, 68, 0.35)'},
    'roast-banner-text': {'fontSize': '14px', 'fontWeight': '700',
                          'color': '#ffffff'},
    'roast-btn': {'fontSize': '14px', 'fontWeight': '700',
                  'color': '#ffffff', 'borderRadius': '10px',
                  'padding': '10px 18px', 'cursor': 'pointer',
                  'border': 'none'},
    'roast-btn-sm': {'fontSize': '12px', 'fontWeight': '700',
                     'borderRadius': '8px', 'padding': '6px 14px',
                     'cursor': 'pointer'},
    'roast-btn-ghost': {'backgroundColor': 'transparent',
                        'color': 'var(--label)',
                        'border': '1px solid var(--border)'},
    'roast-btn-primary': {'backgroundColor': '#0c7bb3'},
    'roast-btn-green': {'backgroundColor': '#16a34a'},
    'roast-btn-purple': {'backgroundColor': '#7c3aed'},
    'roast-btn-event': {'fontSize': '13px', 'padding': '10px 6px',
                        'width': '100%'},
    'roast-btn-charge': {'backgroundColor': '#dc2626'},
    'roast-btn-blue': {'backgroundColor': '#0c7bb3'},
    'roast-btn-sc': {'backgroundColor': '#2563eb'},
    'roast-btn-drop': {'backgroundColor': '#334155'},
    'roast-btn-cool': {'backgroundColor': '#0284c7'},
    'roast-btn-reset': {'backgroundColor': '#6b7280'},
    'roast-btn-step': {'fontSize': '17px', 'padding': '6px 14px'},
    'roast-input': {'border': '1px solid var(--border)',
                    'borderRadius': '8px', 'padding': '8px 10px',
                    'fontSize': '14px', 'color': 'var(--label)',
                    'backgroundColor': 'var(--input)'},
    'roast-checkbox': {'color': 'var(--label)'},
    'roast-table': {'fontSize': '13px', 'color': 'var(--label)',
                    'backgroundColor': 'var(--container)'},
    'roast-accent-bar': {'height': '3px', 'borderRadius': '2px'},
    'roast-seg': {'borderRadius': '8px', 'padding': '7px 4px',
                  'minWidth': '86px'},
    'roast-seg-drying': {'backgroundColor': '#0284c7'},
    'roast-seg-maillard': {'backgroundColor': '#2563eb'},
    'roast-seg-development': {'backgroundColor': '#1e40af'},
    'roast-seg-text': {'fontSize': '12px', 'fontWeight': '700',
                       'color': '#ffffff', 'textAlign': 'center',
                       'whiteSpace': 'nowrap', 'overflow': 'hidden'},
    'roast-event-name': {'fontSize': '11px', 'fontWeight': '700',
                         'textTransform': 'uppercase',
                         'letterSpacing': '0.08em',
                         'textAlign': 'center'},
    'roast-event-time': {'fontSize': '17px', 'fontWeight': '700',
                         'color': 'var(--label)', 'textAlign': 'center'},
    'roast-event-temp': {'fontSize': '12px', 'fontWeight': '600',
                         'color': 'var(--neutral-70)',
                         'textAlign': 'center'},
    'roast-form-caption': {'fontSize': '11px', 'fontWeight': '700',
                           'color': 'var(--neutral-70)',
                           'textTransform': 'uppercase',
                           'letterSpacing': '0.06em'},
    'roast-section-div': {'borderTop': '1px solid var(--border)',
                          'paddingTop': '13px', 'gap': '9px'},
    'roast-scroll': {'backgroundColor': 'var(--containerRoot)',
                     'padding': '20px 22px', 'gap': '15px',
                     'height': '100%', 'overflowY': 'auto'},
    'roast-content': {'padding': '16px 20px', 'gap': '14px'},
    'roast-status': {'fontSize': '12px', 'fontWeight': '700'},
    'roast-alarm-cap': {'fontSize': '13px', 'fontWeight': '700',
                        'color': 'var(--label)', 'minWidth': '130px'},
    'roast-accent-text': {'fontSize': '13px', 'fontWeight': '700',
                          'color': 'var(--callToAction)'},
    'roast-stepper-value': {'fontSize': '26px', 'fontWeight': '700',
                            'color': 'var(--label)',
                            'textAlign': 'center', 'minWidth': '44px'},
    'roast-unit': {'fontSize': '12px', 'fontWeight': '600',
                   'color': 'var(--neutral-70)'},
    'roast-value-right': {'fontSize': '14px', 'fontWeight': '700',
                          'color': 'var(--label)', 'textAlign': 'right'},
    'roast-full': {'width': '100%'},
    'roast-gap-8': {'gap': '8px'},
    'roast-gap-10': {'gap': '10px'},
    'roast-gap-12': {'gap': '12px'},
    'roast-gap-14': {'gap': '14px'},
}

STYLESHEET_CSS = """/* Roastery advanced stylesheet.
   Perspective prefixes every style class with psc- in the DOM, so
   global rules target .psc-<classname>. Theme colors come from the
   built in session theme CSS variables; nothing here hard codes a
   surface color, so dark and light sessions both hold. */

/* Button feedback that a static style class cannot express. */
.psc-roast-btn:hover { filter: brightness(1.15); }
.psc-roast-btn:active { filter: brightness(0.9); }

/* Keyboard focus stays visible on form inputs. */
.psc-roast-input:focus { outline: 2px solid var(--callToAction); }

/* Slim scrollbar for the popup scroll areas. */
.psc-roast-scroll::-webkit-scrollbar { width: 10px; }
.psc-roast-scroll::-webkit-scrollbar-thumb {
  background: var(--neutral-60); border-radius: 6px; }
"""

def write_styles():
    base = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                        'style-classes')
    for name, style in STYLE_CLASSES.items():
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'style.json'), 'w') as f:
            json.dump({'base': {'style': style}}, f, indent=2)
        r = {'scope': 'G', 'version': 1, 'restricted': False,
             'overridable': True, 'files': ['style.json'], 'attributes': {}}
        with open(os.path.join(d, 'resource.json'), 'w') as f:
            json.dump(r, f, indent=2)
    sd = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                      'stylesheet')
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, 'stylesheet.css'), 'w') as f:
        f.write(STYLESHEET_CSS)
    r = {'scope': 'G', 'version': 1, 'restricted': False,
         'overridable': True, 'files': ['stylesheet.css'], 'attributes': {}}
    with open(os.path.join(sd, 'resource.json'), 'w') as f:
        json.dump(r, f, indent=2)
    print('style classes written:', len(STYLE_CLASSES), '+ stylesheet')

# ================================================================ form
# Batch metadata editing lives in ONE ia.input.form instance per
# popup. Widget JSON is built by deepcopying the schema example
# widget (the component expects the full per type config blocks).
# Widget ids equal the batch member names, so the submit payload
# maps straight onto fields; all coercion and persistence happens in
# the library (roastery.core for tags, roastery.batches for the DB).

FORM_SCHEMA = json.load(open(os.path.join(SCHEMAS, 'ia.input.form.json')))
_FORM_EX = FORM_SCHEMA['schema']['example']
WIDGET_TPL = _FORM_EX['columns']['items'][0]['rows']['items'][1]['widgets'][0]
HEADER_TPL = _FORM_EX['columns']['items'][0]['rows']['items'][0]['widgets'][0]

FORM_MEMBERS = ['BeanName', 'Origin', 'Region', 'Farm', 'Altitude',
                'Variety', 'Process', 'HarvestYear', 'MoisturePct',
                'DensityGL', 'ChargeWeightG', 'TargetDropTempF',
                'RoastLevel', 'OperatorName', 'Notes', 'WeightOutG']

def f_widget(wid, wtype, label_text, tpl=None):
    w = copy.deepcopy(tpl or WIDGET_TPL)
    w['id'] = wid
    w['type'] = wtype
    w['label'] = {'text': label_text, 'style': {'classes': ''}}
    w['info'] = {'text': '', 'type': 'caption',
                 'tooltip': {'icon': {'path': '', 'color': ''},
                             'location': 'above',
                             'pixelOffset': {'x': 0, 'y': 0},
                             'maxWidth': 360, 'tail': True,
                             'style': {'classes': ''}},
                 'style': {'classes': ''}}
    return w

def f_text(wid, label_text, required=False):
    w = f_widget(wid, 'text', label_text)
    if required:
        w['text']['validation']['constraints']['required'] = {
            'enabled': True}
    return w

def f_number(wid, label_text, vmin=None, vmax=None):
    w = f_widget(wid, 'number', label_text)
    c = w['number']['validation']['constraints']
    if vmin is not None:
        c['min'] = {'enabled': True, 'value': vmin}
    if vmax is not None:
        c['max'] = {'enabled': True, 'value': vmax}
    # Step must be enabled or the widget only accepts integers.
    c['step'] = {'enabled': True, 'value': 'any'}
    return w

def f_row(widgets):
    return {'align': 'start', 'justify': 'start', 'visible': True,
            'enabled': True, 'widgets': widgets, 'style': {}}

def metadata_form(name, header_text, submit_text, submit_script,
                  cancel_script, with_batch_number=False):
    header = f_widget('MetaHeader', 'none', header_text, tpl=HEADER_TPL)
    rows = [f_row([header])]
    if with_batch_number:
        rows.append(f_row([f_number('BatchNumber', 'Batch number',
                                    1, 99999)]))
    rows += [
        f_row([f_text('BeanName', 'Bean name', required=True),
               f_text('Origin', 'Origin')]),
        f_row([f_text('Region', 'Region'),
               f_text('Farm', 'Farm / station')]),
        f_row([f_text('Altitude', 'Altitude'),
               f_text('Variety', 'Variety')]),
        f_row([f_text('Process', 'Process'),
               f_number('HarvestYear', 'Harvest year', 1900, 2100)]),
        f_row([f_number('MoisturePct', 'Moisture (%)', 0, 100),
               f_number('DensityGL', 'Density (g/L)', 0, 2000)]),
        f_row([f_number('ChargeWeightG', 'Charge weight (g)', 1, 2000),
               f_number('TargetDropTempF', 'Target drop temp (F)',
                        200, 600)]),
        f_row([f_text('RoastLevel', 'Roast level'),
               f_text('OperatorName', 'Operator')]),
        f_row([f_widget('Notes', 'text-area', 'Notes')]),
        f_row([f_number('WeightOutG', 'Weight out (g)', 0, 2000)]),
    ]
    return {
        'type': 'ia.input.form', 'meta': {'name': name},
        'props': {
            'name': 'batchMetadata',
            'disabled': False,
            'readOnly': False,
            'columns': {'align': 'stretch', 'justify': 'start',
                        'items': [{'visible': True,
                                   'rows': {'align': 'start',
                                            'justify': 'start',
                                            'items': rows,
                                            'style': {}},
                                   'style': {}}],
                        'style': {}},
            'actions': {
                'disabled': False, 'fixed': False, 'layout': 'row',
                'align': 'center', 'justify': 'start',
                'submit': {'disabled': False,
                           'text': submit_text,
                           'icon': {},
                           'fireComponentEvent': True,
                           'fireSubmissionEvent': False,
                           'submissionHandler': '',
                           'includeDisabledFieldValues': True,
                           'includeHiddenFieldValues': True,
                           'autoDisable': True, 'resetOn': 'success',
                           'awaitResponse': False,
                           'responseDisplay': {'layout': 'column',
                                               'titleStyle': {},
                                               'messageStyle': {},
                                               'style': {}},
                           'style': {}},
                'cancel': {'disabled': False, 'text': 'Cancel',
                           'icon': {}, 'fireComponentEvent': True,
                           'reset': False, 'style': {}},
                'style': {}},
            'context': {},
            'data': {},
            'validation': {},
            'style': {}},
        'events': {'component': {
            'onSubmitActionPerformed': {
                'scope': 'G', 'type': 'script',
                'config': {'script': submit_script}},
            'onCancelActionPerformed': {
                'scope': 'G', 'type': 'script',
                'config': {'script': cancel_script}}}}}

# ================================================================ Tile

def tile_view():
    accent_bar = flex('AccentBar', 'row', [], classes='roast-accent-bar',
                      position={'grow': 0, 'shrink': 0, 'basis': '3px'},
                      prop_config={'props.style.backgroundColor': {
                          'binding': prop_binding('view.params.accent')}})
    title = label('TitleLabel', 'Stat', 'roast-caption',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.params.title')}})
    value = label('ValueLabel', '0.0', 'roast-value-lg',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.params.valueText')}})
    unit = label('UnitLabel', '', 'roast-unit',
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.params.unit')}})
    row = flex('ValueRow', 'row', [value, unit], align='baseline',
               classes='roast-gap-8')
    root = flex('root', 'column', [accent_bar, title, row],
                classes='roast-card-sm roast-gap-8')
    return {
        'custom': {},
        'params': {'title': 'Stat', 'valueText': '0.0', 'unit': '',
                   'accent': '#0c7bb3'},
        'propConfig': {
            'params.title': {'paramDirection': 'input'},
            'params.valueText': {'paramDirection': 'input'},
            'params.unit': {'paramDirection': 'input'},
            'params.accent': {'paramDirection': 'input'}},
        'props': {'defaultSize': {'width': 220, 'height': 104}},
        'root': root}

# ================================================================ EventCell

def event_cell_view():
    """One roast event: name, elapsed time, captured temp. The done
    param flips the name color; that color stays an expression
    binding (a map transform cannot emit var() colors, v2 trap), the
    rest of the styling is the roast-cell / roast-event-* classes."""
    name = label('NameLabel', 'Event', 'roast-event-name',
                 prop_config={
                     'props.text': {'binding': prop_binding(
                         'view.params.name')},
                     'props.style.color': {'binding': expr_binding(
                         "if({view.params.done}, 'var(--callToAction)', "
                         "'var(--neutral-60)')")}})
    time_l = label('TimeLabel', '--:--', 'roast-event-time',
                   prop_config={'props.text': {'binding': prop_binding(
                       'view.params.timeText')}})
    temp_l = label('TempLabel', '---', 'roast-event-temp',
                   prop_config={'props.text': {'binding': prop_binding(
                       'view.params.tempText')}})
    root = flex('root', 'column', [name, time_l, temp_l],
                align='center', classes='roast-cell')
    return {
        'custom': {},
        'params': {'name': 'Event', 'timeText': '--:--', 'tempText': '---',
                   'done': False},
        'propConfig': {
            'params.name': {'paramDirection': 'input'},
            'params.timeText': {'paramDirection': 'input'},
            'params.tempText': {'paramDirection': 'input'},
            'params.done': {'paramDirection': 'input'}},
        'props': {'defaultSize': {'width': 120, 'height': 84}},
        'root': root}

def event_embed(name, disp_name, stem, custom_idx=None):
    if custom_idx:
        nm = {'binding': tag_binding(T(f'CustomEvent{custom_idx}Name'))}
        elapsed = T(f'CustomEvent{custom_idx}ElapsedSec')
        temp = T(f'CustomEvent{custom_idx}TempF')
    else:
        nm = None
        elapsed = T(stem + 'ElapsedSec')
        temp = T(stem + 'TempF')
    pc = {
        'props.params.timeText': {'binding': expr_binding(
            f"if({ref(elapsed)} >= 0, {mmss_int(ref(elapsed))}, '--:--')")},
        'props.params.tempText': {'binding': expr_binding(
            f"if({ref(elapsed)} >= 0, numberFormat({ref(temp)}, '0') + ' F', '---')")},
        'props.params.done': {'binding': expr_binding(
            f"{ref(elapsed)} >= 0")}}
    if nm:
        pc['props.params.name'] = nm
    params = {'name': disp_name, 'timeText': '--:--', 'tempText': '---',
              'done': False}
    return embed(name, 'Views/EventCell', params,
                 {'grow': 1, 'shrink': 1, 'basis': '104px'}, pc)

def events_strip_view():
    heading = label('Heading', 'Roast Events', 'roast-section-title')
    charge_pc = {
        'props.params.timeText': {'binding': expr_binding(
            f"if({ref(T('State'))} != 'Idle', '00:00', '--:--')")},
        'props.params.tempText': {'binding': expr_binding(
            f"if({ref(T('State'))} != 'Idle', numberFormat({ref(T('ChargeTempF'))}, '0') + ' F', '---')")},
        'props.params.done': {'binding': expr_binding(
            f"{ref(T('State'))} != 'Idle'")}}
    charge = embed('ChargeCell', 'Views/EventCell',
                   {'name': 'Charge', 'timeText': '--:--',
                    'tempText': '---', 'done': False},
                   {'grow': 1, 'shrink': 1, 'basis': '104px'}, charge_pc)
    row1 = flex('StandardRow', 'row', [
        charge,
        event_embed('DryEndCell', 'Dry End', 'DryEnd'),
        event_embed('FCStartCell', 'FC Start', 'FirstCrackStart'),
        event_embed('FCEndCell', 'FC End', 'FirstCrackEnd'),
        event_embed('SCStartCell', 'SC Start', 'SecondCrackStart'),
        event_embed('SCEndCell', 'SC End', 'SecondCrackEnd'),
        event_embed('DropCell', 'Drop', 'Drop')],
        wrap='wrap', classes='roast-gap-8')
    row2 = flex('CustomRow', 'row', [
        event_embed(f'CustomCell{i}', f'Custom {i}', None, custom_idx=i)
        for i in (1, 2, 3, 4)],
        wrap='wrap', classes='roast-gap-8')
    root = flex('root', 'column', [heading, row1, row2],
                classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 210}},
            'root': root}

# ================================================================ PhasesBar

def phases_bar_view():
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))
    drop_e = ref(T('DropElapsedSec'))
    td = ref(T('TargetDryEndSec'))
    tf = ref(T('TargetFCSec'))
    tt = ref(T('TargetDropSec'))
    dry_w = (f"if({drop_e} >= 0, {dry_e} * 100.0 / {drop_e}, "
             f"{td} * 100.0 / {tt})")
    mai_w = (f"if({drop_e} >= 0, ({fc_e} - {dry_e}) * 100.0 / {drop_e}, "
             f"({tf} - {td}) * 100.0 / {tt})")
    dev_w = (f"if({drop_e} >= 0, ({drop_e} - {fc_e}) * 100.0 / {drop_e}, "
             f"({tt} - {tf}) * 100.0 / {tt})")

    def seg(name, caption, color_class, width_expr, text_expr):
        txt = label(name + 'Text', caption, 'roast-seg-text',
                    prop_config={'props.text': {'binding': expr_binding(
                        text_expr)}})
        # Segment width is a binding driven layout value: the one
        # inline style a class cannot express (documented exception).
        return flex(name, 'row', [txt], justify='center', align='center',
                    classes='roast-seg ' + color_class,
                    prop_config={'props.style.width': {'binding':
                        expr_binding(f"numberFormat({width_expr}, '0.0') + '%'")}})

    dry_t = (f"'DRYING  ' + if({dry_e} >= 0, {mmss_int(dry_e)} + ' · ' + "
             f"numberFormat({dry_w}, '0') + '%', 'target ' + {mmss_int(td)})")
    mai_t = (f"'MAILLARD  ' + if({fc_e} >= 0, "
             f"{mmss_int(f'({fc_e} - {dry_e})')} + ' · ' + "
             f"numberFormat({mai_w}, '0') + '%', 'target ' + "
             f"{mmss_int(f'({tf} - {td})')})")
    dev_t = (f"'DEVELOPMENT  ' + if({drop_e} >= 0, "
             f"{mmss_int(f'({drop_e} - {fc_e})')} + ' · ' + "
             f"numberFormat({dev_w}, '0') + '%', 'target ' + "
             f"{mmss_int(f'({tt} - {tf})')})")
    bar = flex('Bar', 'row', [
        seg('DrySeg', 'DRYING', 'roast-seg-drying', dry_w, dry_t),
        seg('MaiSeg', 'MAILLARD', 'roast-seg-maillard', mai_w, mai_t),
        seg('DevSeg', 'DEVELOPMENT', 'roast-seg-development', dev_w, dev_t)],
        classes='roast-gap-8 roast-full')
    heading = label('Heading', 'Phases', 'roast-section-title')
    dtr = label('DtrLabel', 'DTR', 'roast-accent-text',
                prop_config={'props.text': {'binding': expr_binding(
                    f"if({drop_e} >= 0, 'DTR ' + numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', "
                    f"'DTR target ' + numberFormat(({tt} - {tf}) * 100.0 / {tt}, '0.0') + '%')")}})
    head = flex('HeadRow', 'row', [heading, dtr],
                justify='space-between', align='center')
    root = flex('root', 'column', [head, bar],
                classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 108}},
            'root': root}

# ================================================================ Controls

EV_POS = {'grow': 1, 'shrink': 1, 'basis': '104px'}

def ev_button(name, text, color_class, enabled_expr, call):
    return button(name, text, 'roast-btn roast-btn-event ' + color_class,
                  position=dict(EV_POS),
                  prop_config={'props.enabled': {'binding': expr_binding(
                      enabled_expr)}},
                  events=lib_event(call))

def controls_view():
    st = ref(T('State'))
    heading = label('Heading', 'Roaster Controls', 'roast-section-title')
    mode = label('ModePill', 'Off', 'roast-mode-pill',
                 prop_config={
                     'props.text': {'binding': expr_binding(
                         f"'MODE ' + {ref(T('Mode'))}")},
                     'props.style.backgroundColor': {'binding': {
                         'type': 'tag',
                         'config': {'tagPath': T('Mode'), 'mode': 'direct',
                                    'bidirectional': False},
                         'transforms': [{'type': 'map',
                             'inputType': 'scalar', 'outputType': 'color',
                             'fallback': '#6b7280',
                             'mappings': [
                                 {'input': 'Off', 'output': '#6b7280'},
                                 {'input': 'Roast', 'output': '#dc2626'},
                                 {'input': 'Cool', 'output': '#0284c7'}]}]}}})
    head = flex('HeadRow', 'row', [heading, mode],
                justify='space-between', align='center')

    def ev(stem):
        return ref(T(stem + 'ElapsedSec'))
    roasting = f"{st} = 'Roasting'"
    row1 = flex('EventRow1', 'row', [
        ev_button('ChargeButton', 'Charge', 'roast-btn-charge',
                  f"{st} = 'Idle' || {st} = 'Complete'",
                  'roastery.core.charge()'),
        ev_button('DryEndButton', 'Dry End', 'roast-btn-blue',
                  f"{roasting} && {ev('DryEnd')} < 0",
                  "roastery.core.stamp_event('DryEnd', 'Dry End')"),
        ev_button('FCStartButton', 'FC Start', 'roast-btn-blue',
                  f"{roasting} && {ev('DryEnd')} >= 0 && {ev('FirstCrackStart')} < 0",
                  "roastery.core.stamp_event('FirstCrackStart', 'First Crack Start')"),
        ev_button('FCEndButton', 'FC End', 'roast-btn-blue',
                  f"{roasting} && {ev('FirstCrackStart')} >= 0 && {ev('FirstCrackEnd')} < 0",
                  "roastery.core.stamp_event('FirstCrackEnd', 'First Crack End')")],
        wrap='wrap', classes='roast-gap-8')
    row2 = flex('EventRow2', 'row', [
        ev_button('SCStartButton', 'SC Start', 'roast-btn-sc',
                  f"{roasting} && {ev('FirstCrackStart')} >= 0 && {ev('SecondCrackStart')} < 0",
                  "roastery.core.stamp_event('SecondCrackStart', 'Second Crack Start')"),
        ev_button('SCEndButton', 'SC End', 'roast-btn-sc',
                  f"{roasting} && {ev('SecondCrackStart')} >= 0 && {ev('SecondCrackEnd')} < 0",
                  "roastery.core.stamp_event('SecondCrackEnd', 'Second Crack End')"),
        ev_button('DropButton', 'Drop', 'roast-btn-drop',
                  f"{roasting} && {ev('Drop')} < 0",
                  'roastery.core.drop()'),
        ev_button('CoolButton', 'Cool', 'roast-btn-cool',
                  f"{st} = 'Dropped'",
                  'roastery.core.cool()')],
        wrap='wrap', classes='roast-gap-8')
    row3 = flex('EventRow3', 'row', [
        ev_button('FinishButton', 'Finish', 'roast-btn-green',
                  f"{st} = 'Cooling'",
                  'roastery.core.finish()'),
        ev_button('ResetButton', 'Reset', 'roast-btn-reset',
                  f"{st} != 'Idle'",
                  'roastery.core.reset_batch()')] +
        [ev_button(f'CustomButton{i}', f'Custom {i}', 'roast-btn-purple',
                   roasting, f'roastery.core.stamp_custom({i})')
         for i in (1, 2, 3, 4)],
        wrap='wrap', classes='roast-gap-8')
    for i, comp in enumerate(row3['children'][2:], start=1):
        comp['propConfig']['props.text'] = {'binding': tag_binding(
            T(f'CustomEvent{i}Name'))}

    def stepper(name, caption, member, color_class):
        val = label(name + 'Value', '5', 'roast-stepper-value',
                    prop_config={'props.text': {'binding': fmt_tag(
                        T(member), '0')}})
        minus = button(name + 'Minus', '−',
                       'roast-btn roast-btn-step roast-btn-reset',
                       events=lib_event(
                           f"roastery.core.stepper('{member}', -1, '{caption}')"))
        plus = button(name + 'Plus', '+',
                      'roast-btn roast-btn-step ' + color_class,
                      events=lib_event(
                          f"roastery.core.stepper('{member}', 1, '{caption}')"))
        cap = label(name + 'Caption', caption.upper(), 'roast-caption')
        inner = flex(name + 'Row', 'row', [minus, val, plus],
                     align='center', justify='center',
                     classes='roast-gap-8')
        return flex(name, 'column', [cap, inner], align='center',
                    classes='roast-gap-8',
                    position={'grow': 1, 'shrink': 1, 'basis': '150px'})

    steppers = flex('Steppers', 'row', [
        stepper('FanStepper', 'Fan', 'FanLevel', 'roast-btn-blue'),
        stepper('HeatStepper', 'Heat', 'HeatLevel', 'roast-btn-charge')],
        wrap='wrap', classes='roast-gap-14')
    setup_btn = button('RoastSetupButton', 'Roast Setup',
                       'roast-btn roast-btn-primary', events=POPUP_OPEN)
    footer = flex('FooterRow', 'row', [setup_btn], justify='flex-end')
    root = flex('root', 'column',
                [head, row1, row2, row3, steppers, footer],
                classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 560, 'height': 430}},
            'root': root}

# ================================================================ MetaCard

def meta_card_view():
    heading = label('Heading', 'Batch Metadata', 'roast-section-title')
    edit_btn = button('EditButton', 'Edit',
                      'roast-btn roast-btn-sm roast-btn-primary',
                      events=POPUP_OPEN)
    head = flex('HeadRow', 'row', [heading, edit_btn],
                justify='space-between', align='center')

    def pair(caption, value_comp):
        cap = label(caption.replace(' ', '') + 'Cap', caption,
                    'roast-caption')
        return flex(caption.replace(' ', '') + 'Pair', 'column',
                    [cap, value_comp], classes='roast-gap-8',
                    position={'grow': 1, 'shrink': 1, 'basis': '128px'})

    def val(name, binding):
        return label(name, '', 'roast-value',
                     prop_config={'props.text': {'binding': binding}})

    def tagval(member, fmt=None, suffix=''):
        if fmt:
            return fmt_tag(T(member), fmt)
        b = tag_binding(T(member))
        if suffix:
            b = {'type': 'tag', 'config': b['config'],
                 'transforms': [{'type': 'expr', 'expression':
                                 '{value} + \'' + suffix + '\''}]}
        return b

    rows = [
        [('Bean', tagval('BeanName')), ('Origin', tagval('Origin'))],
        [('Region', tagval('Region')), ('Farm', tagval('Farm'))],
        [('Altitude', tagval('Altitude')), ('Variety', tagval('Variety'))],
        [('Process', tagval('Process')), ('Harvest', fmt_tag(T('HarvestYear'), '0'))],
        [('Moisture', fmt_tag(T('MoisturePct'), '0.0')), ('Density', fmt_tag(T('DensityGL'), '0'))],
        [('Charge', fmt_tag(T('ChargeWeightG'), '0')), ('Operator', tagval('OperatorName'))],
    ]
    kids = [head]
    for ri, rowpairs in enumerate(rows):
        kids.append(flex(f'Row{ri}', 'row',
                         [pair(cap, val(f'V{ri}{ci}', b))
                          for ci, (cap, b) in enumerate(rowpairs)],
                         wrap='wrap', classes='roast-gap-12'))
    kids.append(label('UnitsNote',
                      'Moisture in %, density in g/L, charge in g',
                      'roast-note-sm'))
    root = flex('root', 'column', kids, classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 460, 'height': 430}},
            'root': root}

# ================================================================ Summary

def summary_view():
    heading = label('Heading', 'Roast Summary', 'roast-section-title')
    drop_e = ref(T('DropElapsedSec'))
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))

    def line(name, caption, text_expr):
        cap = label(name + 'Cap', caption, 'roast-caption',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
        v = label(name + 'Val', '', 'roast-value-right',
                  prop_config={'props.text': {'binding': expr_binding(
                      text_expr)}})
        return flex(name, 'row', [cap, v], justify='space-between',
                    align='baseline', classes='roast-gap-10')

    def mmss_or_dash(e):
        return f"if({e} >= 0, {mmss_int(e)}, '--:--')"
    lines = [
        line('Total', 'Total time', mmss_or_dash(drop_e)),
        line('Dry', 'Drying', mmss_or_dash(dry_e)),
        line('Mai', 'Maillard',
             f"if({fc_e} >= 0 && {dry_e} >= 0, {mmss_int(f'({fc_e} - {dry_e})')}, '--:--')"),
        line('Dev', 'Development',
             f"if({drop_e} >= 0 && {fc_e} >= 0, {mmss_int(f'({drop_e} - {fc_e})')}, '--:--')"),
        line('Dtr', 'Dev ratio (DTR)',
             f"if({drop_e} > 0 && {fc_e} >= 0, numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', '--')"),
        line('DropT', 'Drop temp',
             f"if({drop_e} >= 0, numberFormat({ref(T('DropTempF'))}, '0') + ' F', '--')"),
        line('Degree', 'Roast degree',
             f"if({drop_e} < 0, '--', "
             f"if({ref(T('DropTempF'))} < 390, 'Cinnamon', "
             f"if({ref(T('DropTempF'))} < 396, 'New England', "
             f"if({ref(T('DropTempF'))} < 401, 'American', "
             f"if({ref(T('DropTempF'))} < 406, 'City', "
             f"if({ref(T('DropTempF'))} < 411, 'City+', "
             f"if({ref(T('DropTempF'))} < 416, 'Full City', "
             f"if({ref(T('DropTempF'))} < 421, 'Full City+', "
             f"if({ref(T('DropTempF'))} < 426, 'Vienna', "
             f"if({ref(T('DropTempF'))} < 436, 'French', 'Italian'))))))))))"),
        line('WOut', 'Weight out',
             f"if({ref(T('WeightOutG'))} > 0, numberFormat({ref(T('WeightOutG'))}, '0') + ' g', 'not entered')"),
        line('Loss', 'Weight loss',
             f"if({ref(T('WeightOutG'))} > 0 && {ref(T('ChargeWeightG'))} > 0, numberFormat(({ref(T('ChargeWeightG'))} - {ref(T('WeightOutG'))}) * 100.0 / {ref(T('ChargeWeightG'))}, '0.0') + '%', '--')"),
    ]
    save_btn = button('SaveButton', 'Save Batch',
                      'roast-btn roast-btn-green',
                      prop_config={'props.enabled': {'binding': expr_binding(
                          f"{drop_e} >= 0")}},
                      events=lib_event(
                          'roastery.batches.save_current_batch(self)'))
    note = label('SaveNote', '', 'roast-note-success',
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.custom.saveNote')}})
    foot = flex('FootRow', 'column', [save_btn, note],
                classes='roast-gap-8')
    root = flex('root', 'column', [heading] + lines + [foot],
                classes='roast-card roast-gap-8')
    return {'custom': {'saveNote': ''}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 380, 'height': 430}},
            'root': root}

# ================================================================ charts (XY)

def _xy_templates():
    schema = json.load(open(os.path.join(SCHEMAS, 'ia.chart.xy.json')))
    ex = schema['schema']['properties']
    return (copy.deepcopy(ex['series']['example'][0]),
            copy.deepcopy(ex['xAxes']['example'][0]),
            copy.deepcopy(ex['yAxes']['example'][0]))

def _history_binding(minutes=15):
    return {'type': 'tag-history', 'config': {
        'dateRange': {'type': 'mostRecent', 'mostRecent': minutes,
                      'mostRecentUnits': 'MIN'},
        'tags': [{'path': T('BeanTempF'), 'alias': 'bean',
                  'aggregate': 'Average'},
                 {'path': T('RateOfRiseF'), 'alias': 'ror',
                  'aggregate': 'Average'}],
        'queryOptions': {'returnFormat': 'wide',
                         'returnSize': {'type': 'interval',
                                        'interval': '5 sec'}},
        'polling': {'enabled': True, 'rate': 5},
        'valueFormat': 'dataset', 'ignoreBadQuality': True}}

def main_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, source, y, axis, color, width, render='line',
               dash=None, opacity=1.0, fill_opacity=0.0):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': source, 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = axis
        s['render'] = render
        key = 'stepLine' if render == 'step line' else 'line'
        s[key]['appearance']['stroke']['color'] = color
        s[key]['appearance']['stroke']['width'] = width
        s[key]['appearance']['stroke']['opacity'] = opacity
        if dash:
            s[key]['appearance']['stroke']['dashArray'] = dash
        if fill_opacity:
            s[key]['appearance']['fill']['color'] = color
            s[key]['appearance']['fill']['opacity'] = fill_opacity
        s[key]['appearance']['bullets'][0]['enabled'] = False
        return s

    xaxis = copy.deepcopy(xaxis_tpl)
    xaxis['name'] = 'time'
    xaxis['render'] = 'date'
    xaxis['label'] = {'enabled': True, 'text': 'Time', 'color': ''}

    temp_axis = copy.deepcopy(yaxis_tpl)
    temp_axis['name'] = 'temp'
    temp_axis['render'] = 'value'
    temp_axis['label'] = {'enabled': True, 'text': 'Bean Temp (deg F)',
                          'color': ''}
    temp_axis['value']['range'] = {'min': 150, 'max': 460,
                                  'useStrict': True}
    ror_axis = copy.deepcopy(yaxis_tpl)
    ror_axis['name'] = 'ror'
    ror_axis['render'] = 'value'
    ror_axis['label'] = {'enabled': True,
                         'text': 'Rate of Rise (deg F/min)', 'color': ''}
    ror_axis['value']['range'] = {'min': 0, 'max': 40, 'useStrict': True}
    ror_axis['appearance']['opposite'] = True

    return {
        'type': 'ia.chart.xy', 'meta': {'name': 'RoastChart'},
        'props': {
            'dataSources': {'trend': [], 'plan': [], 'bg': []},
            'xAxes': [xaxis], 'yAxes': [temp_axis, ror_axis],
            'series': [
                series('Background', 'bg', 'bg', 'temp', '#64748b', 2,
                       opacity=0.5),
                series('Target', 'plan', 'plan', 'temp', '#94a3b8', 2,
                       dash='7 5', opacity=0.85),
                series('Bean Temp', 'trend', 'bean', 'temp', AMBER, 3,
                       fill_opacity=0.13),
                series('Rate of Rise', 'trend', 'ror', 'ror', SKY, 2)],
            'legend': {'enabled': True, 'position': 'bottom'},
            # Chart surface transparency is an amCharts prop, not a
            # style class concern (documented exception).
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {
            'props.dataSources.trend': {'binding': _history_binding()},
            'props.dataSources.plan': {'binding': tag_binding(
                '[default]Roastery/TargetProfileDS')},
            'props.dataSources.bg': {'binding': tag_binding(
                '[default]Roastery/BackgroundDS')}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}

def trace_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, y, color):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': 'events', 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = 'level'
        s['render'] = 'step line'
        s['stepLine']['appearance']['stroke']['color'] = color
        s['stepLine']['appearance']['stroke']['width'] = 2
        s['stepLine']['appearance']['connect'] = True
        s['stepLine']['appearance']['bullets'][0]['enabled'] = False
        return s

    xaxis = copy.deepcopy(xaxis_tpl)
    xaxis['name'] = 'time'
    xaxis['render'] = 'date'
    xaxis['label'] = {'enabled': False, 'text': '', 'color': ''}
    lvl = copy.deepcopy(yaxis_tpl)
    lvl['name'] = 'level'
    lvl['render'] = 'value'
    lvl['label'] = {'enabled': True, 'text': 'Level', 'color': ''}
    lvl['value']['range'] = {'min': 0, 'max': 10, 'useStrict': True}
    return {
        'type': 'ia.chart.xy', 'meta': {'name': 'TraceChart'},
        'props': {
            'dataSources': {'events': []},
            'xAxes': [xaxis], 'yAxes': [lvl],
            'series': [series('Fan', 'fan', AMBER),
                       series('Heat', 'heat', RED)],
            'legend': {'enabled': True, 'position': 'right'},
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {'props.dataSources.events': {'binding':
                       tag_binding(LOG)}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}

# ================================================================ Main

TARGET_AT = (
    f"if({ELAPSED_SEC} <= {ref(T('TargetDryEndSec'))}, "
    f"{ref(T('TargetChargeTempF'))} + ({ref(T('TargetDryEndTempF'))} - {ref(T('TargetChargeTempF'))}) * {ELAPSED_SEC} / {ref(T('TargetDryEndSec'))}, "
    f"if({ELAPSED_SEC} <= {ref(T('TargetFCSec'))}, "
    f"{ref(T('TargetDryEndTempF'))} + ({ref(T('TargetFCTempF'))} - {ref(T('TargetDryEndTempF'))}) * ({ELAPSED_SEC} - {ref(T('TargetDryEndSec'))}) / ({ref(T('TargetFCSec'))} - {ref(T('TargetDryEndSec'))}), "
    f"if({ELAPSED_SEC} <= {ref(T('TargetDropSec'))}, "
    f"{ref(T('TargetFCTempF'))} + ({ref(T('TargetDropTempF'))} - {ref(T('TargetFCTempF'))}) * ({ELAPSED_SEC} - {ref(T('TargetFCSec'))}) / ({ref(T('TargetDropSec'))} - {ref(T('TargetFCSec'))}), "
    f"{ref(T('TargetDropTempF'))})))")

ALARM_ACTIVE = (
    f"({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}) || "
    f"({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}) || "
    f"({ref(T('AlarmFCWatchEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('FirstCrackStartElapsedSec'))} < 0 && "
    f"{ELAPSED_SEC} >= ({ref(T('TargetFCSec'))} - {ref(T('AlarmFCWindowSec'))}) && "
    f"{ELAPSED_SEC} <= ({ref(T('TargetFCSec'))} + {ref(T('AlarmFCWindowSec'))}))")

ALARM_TEXT = (
    f"if({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}, "
    f"{ref(T('AlarmHighTempMsg'))} + ' -- now ' + numberFormat({ref(T('BeanTempF'))}, '0') + ' F', "
    f"if({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}, "
    f"'Drop approaching -- target ' + numberFormat({ref(T('TargetDropTempF'))}, '0') + ' F', "
    f"'First crack watch -- listen for cracks'))")

CLOCK_EXPR = (
    f"if({ref(T('State'))} = 'Roasting', {mmss_ms(ELAPSED_MS)}, "
    f"if({ref(T('DropElapsedSec'))} >= 0, {mmss_int(ref(T('DropElapsedSec')))}, '00:00'))")

DEVIATION_EXPR = (
    f"if({ref(T('State'))} != 'Roasting', '--', "
    f"numberFormat({ref(T('BeanTempF'))} - ({TARGET_AT}), '+0.0;-0.0') + ' F')")

PHASE_EXPR = (
    f"if({ref(T('State'))} = 'Idle', 'Pre-charge', "
    f"if({ref(T('State'))} = 'Dropped', 'Dropped', "
    f"if({ref(T('State'))} = 'Cooling', 'Cooling', "
    f"if({ref(T('State'))} = 'Complete', 'Complete', "
    f"if({ref(T('SecondCrackStartElapsedSec'))} >= 0, 'Second Crack', "
    f"if({ref(T('FirstCrackStartElapsedSec'))} >= 0, 'Development', "
    f"if({ref(T('DryEndElapsedSec'))} >= 0, 'Maillard', 'Drying')))))))")

NAV_BATCHES_SCRIPT = "\tsystem.perspective.navigate(page='/batches')\n"
NAV_CONSOLE_SCRIPT = "\tsystem.perspective.navigate(page='/')\n"

def main_view():
    title = label('TitleLabel', 'Ember & Oak Roastery', 'roast-title')
    sub = label('SubLabel', 'Artisan Roast Console · FreshRoast SR800',
                'roast-subtitle')
    title_block = flex('TitleBlock', 'column', [title, sub],
                       classes='roast-gap-8')

    batch_chip = label('BatchChip', '', 'roast-chip',
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' · ' + {ref(T('BeanName'))}")}})
    # Pill background is state driven (connected or not), so it stays
    # a bound inline style (documented exception); the pill shape and
    # text come from roast-pill.
    ws_pill = label('WsPill', 'SR800', 'roast-pill',
                    prop_config={
                        'props.text': {'binding': expr_binding(
                            f"if({ref(T('BeanTempF'))} > 0, {ref(T('ActiveSource'))} + ' CONNECTED', {ref(T('ActiveSource'))} + ' OFFLINE')")},
                        'props.style.backgroundColor': {'binding':
                            expr_binding(
                                f"if({ref(T('BeanTempF'))} > 0, '#166534', '#7f1d1d')")}})
    state_pill = label('StatePill', 'Idle', 'roast-pill',
                       prop_config={
                           'props.text': {'binding': tag_binding(T('State'))},
                           'props.style.backgroundColor': {'binding': {
                               'type': 'tag',
                               'config': {'tagPath': T('State'),
                                          'mode': 'direct',
                                          'bidirectional': False},
                               'transforms': [{'type': 'map',
                                   'inputType': 'scalar',
                                   'outputType': 'color',
                                   'fallback': '#6b7280',
                                   'mappings': [
                                       {'input': 'Idle',
                                        'output': '#6b7280'},
                                       {'input': 'Roasting',
                                        'output': '#dc2626'},
                                       {'input': 'Dropped',
                                        'output': '#475569'},
                                       {'input': 'Cooling',
                                        'output': '#0284c7'},
                                       {'input': 'Complete',
                                        'output': '#16a34a'}]}]}}})
    clock = label('ClockLabel', '00:00', 'roast-clock',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.clockText')}})
    batches_btn = button('BatchesButton', 'Batches',
                         'roast-btn roast-btn-sm roast-btn-ghost',
                         events=script_event(NAV_BATCHES_SCRIPT))
    theme_btn = button('ThemeButton', '',
                       'roast-btn roast-btn-sm roast-btn-ghost',
                       prop_config={'props.text': {'binding': prop_binding(
                           'view.custom.themeText')}},
                       events=lib_event('roastery.core.theme_toggle(self)'))
    right = flex('HeaderRight', 'row',
                 [batch_chip, ws_pill, state_pill, clock, theme_btn,
                  batches_btn],
                 align='center', wrap='wrap', classes='roast-gap-12')
    header = flex('HeaderBar', 'row', [title_block, right],
                  justify='space-between', align='center', wrap='wrap',
                  position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
                  classes='roast-header')

    alarm = flex('AlarmBanner', 'row', [
        label('AlarmText', '', 'roast-banner-text',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.alarmText')}})],
        align='center',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
        classes='roast-banner',
        prop_config={'props.style.display': {'binding': expr_binding(
            f"if({ALARM_ACTIVE}, 'flex', 'none')")}})

    chart_title = label('ChartTitle', 'Roast Curve', 'roast-value-strong')
    bg_chip = label('BgChip', '', 'roast-note',
                    prop_config={'props.text': {'binding': expr_binding(
                        f"if({ref('[default]Roastery/BackgroundLabel')} != '', 'Background: ' + {ref('[default]Roastery/BackgroundLabel')}, 'Background: none')")}})
    chart_head = flex('ChartHead', 'row', [chart_title, bg_chip],
                      justify='space-between', align='center',
                      position={'grow': 0, 'shrink': 0, 'basis': '24px'})
    trace_cap = label('TraceCaption', 'Fan / Heat Levels', 'roast-caption',
                      position={'grow': 0, 'shrink': 0, 'basis': '16px'})
    chart_card = flex('ChartCard', 'column', [
        chart_head, main_chart(), trace_cap,
        flex('TraceWrap', 'row', [trace_chart()],
             position={'grow': 0, 'shrink': 0, 'basis': '104px'})],
        classes='roast-card roast-gap-8',
        position={'grow': 0, 'shrink': 0, 'basis': '560px'})

    strip = embed('EventsStripEmbed', 'Views/EventsStrip', {},
                  {'grow': 0, 'shrink': 0, 'basis': 'auto'})
    phases = embed('PhasesBarEmbed', 'Views/PhasesBar', {},
                   {'grow': 0, 'shrink': 0, 'basis': 'auto'})

    tile_pos = {'grow': 1, 'shrink': 1, 'basis': '148px'}
    tiles = flex('TilesRow', 'row', [
        embed('BeanTile', 'Views/Tile',
              {'title': 'Bean Temp', 'valueText': '0.0', 'unit': 'deg F',
               'accent': AMBER}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('BeanTempF'), '0.0')}}),
        embed('RorTile', 'Views/Tile',
              {'title': 'Rate of Rise', 'valueText': '0.0',
               'unit': 'F/min', 'accent': SKY}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('RateOfRiseF'), '0.0')}}),
        embed('DevTile', 'Views/Tile',
              {'title': 'Deviation', 'valueText': '--', 'unit': '',
               'accent': '#0c7bb3'}, dict(tile_pos),
              {'props.params.valueText': {'binding': prop_binding(
                  'view.custom.deviationText')}}),
        embed('FanTile', 'Views/Tile',
              {'title': 'Fan', 'valueText': '5', 'unit': '/ 9',
               'accent': AMBER}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('FanLevel'), '0')}}),
        embed('HeatTile', 'Views/Tile',
              {'title': 'Heat', 'valueText': '5', 'unit': '/ 9',
               'accent': RED}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('HeatLevel'), '0')}}),
        embed('PhaseTile', 'Views/Tile',
              {'title': 'Phase', 'valueText': 'Pre-charge', 'unit': '',
               'accent': '#16a34a'}, dict(tile_pos),
              {'props.params.valueText': {'binding': prop_binding(
                  'view.custom.phaseText')}}),
        embed('TargetTile', 'Views/Tile',
              {'title': 'Target Drop', 'valueText': '415',
               'unit': 'deg F', 'accent': '#64748b'}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('TargetDropTempF'), '0')}})],
        wrap='wrap', classes='roast-gap-12',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'})

    bottom = flex('BottomRow', 'row', [
        embed('ControlsEmbed', 'Views/Controls', {},
              {'grow': 5, 'shrink': 1, 'basis': '430px'}),
        embed('MetaCardEmbed', 'Views/MetaCard', {},
              {'grow': 4, 'shrink': 1, 'basis': '360px'}),
        embed('SummaryEmbed', 'Views/Summary', {},
              {'grow': 3, 'shrink': 1, 'basis': '300px'})],
        wrap='wrap', align='flex-start', classes='roast-gap-14',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'})

    content = flex('Content', 'column',
                   [chart_card, strip, phases, tiles, bottom],
                   position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
                   classes='roast-content')
    root = flex('root', 'column', [header, alarm, content],
                classes='roast-app')
    return {
        'custom': {'clockText': '00:00', 'deviationText': '--',
                   'phaseText': 'Pre-charge', 'alarmText': '',
                   'themeText': 'Theme: light'},
        'params': {},
        'propConfig': {
            'custom.clockText': {'binding': expr_binding(CLOCK_EXPR)},
            'custom.deviationText': {'binding': expr_binding(
                DEVIATION_EXPR)},
            'custom.phaseText': {'binding': expr_binding(PHASE_EXPR)},
            'custom.alarmText': {'binding': expr_binding(ALARM_TEXT)}},
        'props': {'defaultSize': {'width': 1440, 'height': 1240}},
        'events': {'system': {'onStartup': {
            'scope': 'G', 'type': 'script',
            'config': {'script': "\timport roastery.core\n\troastery.core.main_startup(self)\n"}}}},
        'root': root}

# ================================================================ Config (popup)

def text_in(name, member, placeholder=''):
    return {'type': 'ia.input.text-field', 'meta': {'name': name},
            'props': {'text': '', 'placeholder': placeholder,
                      'style': {'classes': 'roast-input'}},
            'propConfig': {'props.text': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def num_in(name, member, fmt='0'):
    return {'type': 'ia.input.numeric-entry-field', 'meta': {'name': name},
            'props': {'value': 0, 'format': fmt,
                      'style': {'classes': 'roast-input'}},
            'propConfig': {'props.value': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def check_in(name, member):
    return {'type': 'ia.input.checkbox', 'meta': {'name': name},
            'props': {'selected': False,
                      'style': {'classes': 'roast-checkbox'}},
            'propConfig': {'props.selected': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def cfg_field(name, caption, comp, basis='180px'):
    cap = label(name + 'Cap', caption, 'roast-form-caption')
    return flex(name, 'column', [cap, comp], classes='roast-gap-8',
                position={'grow': 1, 'shrink': 1, 'basis': basis})

def cfg_row(name, fields):
    return flex(name, 'row', fields, wrap='wrap', classes='roast-gap-12')

def cfg_section(name, title, children):
    head = label(name + 'Head', title, 'roast-section-title')
    return flex(name, 'column', [head] + children,
                classes='roast-section-div')

CONFIG_STARTUP_SCRIPT = (
    "\timport roastery.core\n"
    "\tself.getChild('root').getChild('MetaForm').props.data = roastery.core.config_form_data()\n")
CONFIG_SUBMIT_SCRIPT = (
    "\timport roastery.core\n"
    "\troastery.core.config_submit(self, event)\n")
FORM_CANCEL_SCRIPT = "\tsystem.perspective.closePopup('roastery-config')\n"

def source_dropdown():
    options = [{'value': 'Simulated', 'label': 'Simulated (RoasterSim)'},
               {'value': 'WebSocket', 'label': 'WebSocket (SR800 feed)'},
               {'value': 'Mqtt', 'label': 'MQTT (broker feed)'}]
    return {'type': 'ia.input.dropdown', 'meta': {'name': 'SourceDropdown'},
            'props': {'options': options, 'value': 'Simulated',
                      'style': {'classes': 'roast-input'}},
            'propConfig': {'props.value': {'binding': tag_binding(
                T('ActiveSource'), bidirectional=True)}}}

def config_view():
    title = label('Title', 'Roast Setup', 'roast-title-sm')
    status = label('StatusLabel', '', 'roast-status',
                   prop_config={
                       'props.text': {'binding': expr_binding(
                           f"if({ref(T('BeanTempF'))} > 0, 'SR800 Connected', 'SR800 Disconnected')")},
                       'props.style.color': {'binding': expr_binding(
                           f"if({ref(T('BeanTempF'))} > 0, 'var(--success)', '#ef4444')")}})
    head = flex('HeadRow', 'row', [title, status],
                justify='space-between', align='center')

    probe = label('ProbeReadout', '', 'roast-value',
                  prop_config={'props.text': {'binding': expr_binding(
                      f"'Probe now: ' + numberFormat({ref(T('BeanTempF'))}, '0.0') + ' F · RoR ' + numberFormat({ref(T('RateOfRiseF'))}, '0.0') + ' F/min'")}})
    src_note = label('SourceNote', '', 'roast-note',
                     prop_config={'props.text': {'binding': expr_binding(
                         f"'Active source: ' + {ref(T('ActiveSource'))} + ' · ' + "
                         f"if({ref(T('ActiveSource'))} = 'WebSocket', {ref(T('Sources/WebSocket/WsUrl'))}, "
                         f"if({ref(T('ActiveSource'))} = 'Mqtt', {ref(T('Sources/Mqtt/Address'))}, "
                         f"{ref(T('Sources/Simulated/Address'))}))")}})
    roaster = cfg_section('RoasterSection', 'Roaster', [
        cfg_row('SourceRow', [
            cfg_field('SourceField', 'Active source', source_dropdown(),
                      basis='300px'),
            cfg_field('ProbeField', 'Live probe', probe, basis='240px')]),
        cfg_row('SrcNoteRow', [src_note]),
        cfg_row('WsRow', [cfg_field('WsField', 'WebSocket URL',
                                    text_in('WsUrlField', 'WsUrl',
                                            'ws://sr800.local:8080'),
                                    basis='300px')]),
        cfg_row('RoasterRow2', [
            cfg_field('RorSmoothField', 'RoR smoothing (sec)',
                      num_in('RorSmoothNum', 'RoRSmoothingSec'))]),
    ])

    target = cfg_section('TargetSection', 'Target Profile', [
        cfg_row('TargetRow1', [
            cfg_field('TChargeField', 'Charge temp (F)',
                      num_in('TChargeNum', 'TargetChargeTempF')),
            cfg_field('TDrySecField', 'Dry end time (sec)',
                      num_in('TDrySecNum', 'TargetDryEndSec')),
            cfg_field('TDryTempField', 'Dry end temp (F)',
                      num_in('TDryTempNum', 'TargetDryEndTempF'))]),
        cfg_row('TargetRow2', [
            cfg_field('TFcSecField', 'First crack time (sec)',
                      num_in('TFcSecNum', 'TargetFCSec')),
            cfg_field('TFcTempField', 'First crack temp (F)',
                      num_in('TFcTempNum', 'TargetFCTempF')),
            cfg_field('TDropSecField', 'Drop time (sec)',
                      num_in('TDropSecNum', 'TargetDropSec')),
            cfg_field('TDropTempField', 'Drop temp (F)',
                      num_in('TDropTempNum', 'TargetDropTempF', '0'))]),
    ])

    meta = metadata_form(
        'MetaForm', 'Batch Metadata', 'Save Batch Details',
        CONFIG_SUBMIT_SCRIPT, FORM_CANCEL_SCRIPT)
    saved_lbl = label('FormSavedLabel', '', 'roast-note-success',
                      prop_config={'props.text': {'binding': prop_binding(
                          'view.custom.formSaved')}})

    custom_rows = []
    for i in (1, 2, 3, 4):
        custom_rows.append(cfg_row(f'CustomRow{i}', [
            cfg_field(f'CustomNameField{i}', f'Custom {i} name',
                      text_in(f'CustomNameIn{i}', f'CustomEvent{i}Name')),
            cfg_field(f'CustomKindField{i}', f'Custom {i} kind',
                      text_in(f'CustomKindIn{i}', f'CustomEvent{i}Kind'))]))
    customs = cfg_section('CustomSection', 'Custom Events', custom_rows)

    def alarm_row(name, caption, check_member, fields):
        chk = check_in(name + 'Check', check_member)
        cap = label(name + 'Cap', caption, 'roast-alarm-cap')
        return flex(name, 'row', [chk, cap] + fields, align='center',
                    wrap='wrap', classes='roast-gap-10')
    alarms = cfg_section('AlarmSection', 'Alarms', [
        alarm_row('AlarmHigh', 'High bean temp', 'AlarmHighTempEnabled', [
            num_in('AlarmHighNum', 'AlarmHighTempF'),
            text_in('AlarmHighMsgIn', 'AlarmHighTempMsg')]),
        alarm_row('AlarmDrop', 'Drop approaching', 'AlarmDropEnabled', [
            num_in('AlarmDropNum', 'AlarmDropDeltaF')]),
        alarm_row('AlarmFC', 'First crack watch', 'AlarmFCWatchEnabled', [
            num_in('AlarmFCNum', 'AlarmFCWindowSec')]),
    ])

    close_btn = button('CloseButton', 'Close',
                       'roast-btn roast-btn-primary', events=POPUP_CLOSE)
    footer = flex('Footer', 'row', [close_btn], justify='flex-end')
    root = flex('root', 'column',
                [head, roaster, target, meta, saved_lbl, customs,
                 alarms, footer],
                classes='roast-scroll')

    def _no_shrink(node):
        if isinstance(node, dict):
            for child in node.get('children', []) or []:
                pos = child.setdefault('position', {})
                pos['shrink'] = 0
                _no_shrink(child)
    _no_shrink(root)
    return {'custom': {'formSaved': ''}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 700, 'height': 880}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script': CONFIG_STARTUP_SCRIPT}}}},
            'root': root}

# ================================================================ Batches (page /batches)

def batches_panel_view():
    """The reusable batches panel: table, actions, confirm row. The
    /batches page embeds it, and the coming tabbed shell can embed
    the same view, so all batch CRUD UI lives here exactly once."""
    cols = [
        {'field': 'batch_number', 'header': {'title': 'Batch'},
         'width': 70},
        {'field': 'roast_start', 'header': {'title': 'Date'},
         'width': 150, 'render': 'date',
         'dateFormat': 'YYYY-MM-DD h:mm a'},
        {'field': 'bean_name', 'header': {'title': 'Bean'}, 'width': 150},
        {'field': 'origin', 'header': {'title': 'Origin'}, 'width': 130},
        {'field': 'charge_g', 'header': {'title': 'Charge (g)'},
         'width': 90},
        {'field': 'drop_temp_f', 'header': {'title': 'Drop (F)'},
         'width': 80},
        {'field': 'total_sec', 'header': {'title': 'Total (s)'},
         'width': 80},
        {'field': 'dtr_pct', 'header': {'title': 'DTR %'}, 'width': 70},
        {'field': 'weight_out_g', 'header': {'title': 'Out (g)'},
         'width': 80},
        {'field': 'roast_degree', 'header': {'title': 'Degree'},
         'width': 100},
        {'field': 'id', 'header': {'title': 'ID'}, 'width': 50,
         'visible': False},
    ]
    table = {'type': 'ia.display.table', 'meta': {'name': 'BatchTable'},
             'props': {'data': [], 'columns': cols,
                       'pager': {'enabled': False},
                       'rows': {'height': 34},
                       'header': {'height': 36, 'style': {
                           'classes': 'roast-table-header'}},
                       'style': {'classes': 'roast-table'}},
             'propConfig': {'props.data': {'binding': {
                 'type': 'query',
                 'config': {'queryPath': 'Roastery/Batches/SelectAll',
                            'returnFormat': 'dataset',
                            'parameters': {},
                            'polling': {'enabled': False, 'rate': 5},
                            'designerUseLimit': True,
                            'bypassCache': False}}}},
             'events': {'component': {'onRowClick': {
                 'scope': 'G', 'type': 'script',
                 'config': {'script':
                     "\timport roastery.batches\n"
                     "\troastery.batches.select_row(self, event)\n"}}}},
             'position': {'grow': 0, 'shrink': 0, 'basis': '420px'}}
    sel_enabled = "({view.custom.selBatchNumber} > 0)"
    edit_btn = button('EditButton', 'Edit',
                      'roast-btn roast-btn-sm roast-btn-primary',
                      prop_config={'props.enabled': {'binding':
                          expr_binding(sel_enabled)}},
                      events=lib_event(
                          'roastery.batches.open_editor(self)'))
    del_btn = button('DeleteButton', 'Delete',
                     'roast-btn roast-btn-sm roast-btn-charge',
                     prop_config={'props.enabled': {'binding':
                         expr_binding(sel_enabled)}},
                     events=lib_event('roastery.batches.arm_delete(self)'))
    bg_btn = button('BgButton', 'View as Background',
                    'roast-btn roast-btn-sm roast-btn-purple',
                    prop_config={'props.enabled': {'binding':
                        expr_binding(sel_enabled)}},
                    events=lib_event(
                        'roastery.batches.set_background(self)'))
    note = label('SelNote',
                 'Select a batch to edit it, delete it, or view it as a background.',
                 'roast-note',
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.custom.selNote')}})
    foot = flex('FootRow', 'row', [note, edit_btn, del_btn, bg_btn],
                justify='space-between', align='center',
                classes='roast-gap-12')
    confirm_lbl = label('ConfirmLabel', '', 'roast-banner-text',
                        prop_config={'props.text': {'binding': expr_binding(
                            "'Delete batch ' + {view.custom.selBatchNumber} + ' and its curve?'")}})
    confirm_btn = button('ConfirmDeleteButton', 'Confirm Delete',
                         'roast-btn roast-btn-sm roast-btn-charge',
                         events=lib_event(
                             'roastery.batches.confirm_delete(self)'))
    cancel_btn = button('CancelDeleteButton', 'Cancel',
                        'roast-btn roast-btn-sm roast-btn-ghost',
                        events=lib_event(
                            'roastery.batches.cancel_delete(self)'))
    confirm_row = flex('ConfirmRow', 'row',
                       [confirm_lbl, confirm_btn, cancel_btn],
                       justify='space-between', align='center',
                       classes='roast-banner roast-gap-12',
                       prop_config={'props.style.display': {'binding':
                           expr_binding(
                               "if({view.custom.confirmDelete}, 'flex', 'none')")}})
    root = flex('root', 'column', [table, confirm_row, foot],
                classes='roast-card roast-gap-12',
                scripts={'messageHandlers': [{
                    'messageType': 'roastery-batches-refresh',
                    'script': ("\timport roastery.batches\n"
                               "\troastery.batches.refresh_table(self)\n"),
                    'sessionScope': True, 'pageScope': True,
                    'viewScope': False}]})
    return {'custom': {'selBatchNumber': 0, 'selLabel': '',
                       'selNote': 'Select a batch to edit it, delete it, or view it as a background.',
                       'confirmDelete': False},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 560}},
            'root': root}

def batches_view():
    """Page shell for /batches: header plus the BatchesPanel embed.
    Kept deliberately thin; the tabbed shell redesign will reuse the
    panel and retire this page."""
    title = label('Title', 'Roast Batches', 'roast-title')
    new_btn = button('NewButton', 'New Batch',
                     'roast-btn roast-btn-sm roast-btn-primary',
                     events=lib_event(
                         'roastery.batches.open_editor(self, create=True)'))
    console_btn = button('ConsoleButton', 'Back to Console',
                         'roast-btn roast-btn-sm roast-btn-ghost',
                         events=script_event(NAV_CONSOLE_SCRIPT))
    head = flex('HeadRow', 'row', [title, new_btn, console_btn],
                justify='space-between', align='center')
    panel = embed('BatchesPanelEmbed', 'Views/BatchesPanel', {},
                  {'grow': 0, 'shrink': 0, 'basis': 'auto'})
    content = flex('Content', 'column', [head, panel],
                   classes='roast-content')
    root = flex('root', 'column', [content], classes='roast-app')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 700}},
            'root': root}

# ================================================================ BatchEdit (popup)

BATCHEDIT_STARTUP_SCRIPT = (
    "\timport roastery.batches\n"
    "\tself.getChild('root').getChild('BatchForm').props.data = roastery.batches.edit_form_data_for(self)\n")
BATCHEDIT_SUBMIT_SCRIPT = (
    "\timport roastery.batches\n"
    "\troastery.batches.batch_edit_submit(self, event)\n")
BATCHEDIT_CANCEL_SCRIPT = "\tsystem.perspective.closePopup('roastery-batch-edit')\n"

def batch_edit_view():
    title = label('Title', 'Edit Batch', 'roast-title-sm',
                  prop_config={'props.text': {'binding': expr_binding(
                      "if({view.params.createMode}, 'New Batch', "
                      "'Edit Batch ' + {view.params.batchNumber})")}})
    note = label('ModeNote', '', 'roast-note',
                 prop_config={'props.text': {'binding': expr_binding(
                     "if({view.params.createMode}, "
                     "'Manual batch entry: the batch number is required, "
                     "everything else is what you know.', "
                     "'Editing the stored batch document. The batch "
                     "number is the batch identity and does not change.')")}})
    form = metadata_form('BatchForm', 'Batch Details', 'Save Batch',
                         BATCHEDIT_SUBMIT_SCRIPT, BATCHEDIT_CANCEL_SCRIPT,
                         with_batch_number=True)
    saved = label('EditNoteLabel', '', 'roast-note-success',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.editNote')}})
    close_btn = button('CloseButton', 'Close',
                       'roast-btn roast-btn-primary',
                       events={'dom': {'onClick': {
                           'scope': 'C', 'type': 'popup',
                           'config': {'type': 'close',
                                      'id': 'roastery-batch-edit'}}}})
    footer = flex('Footer', 'row', [close_btn], justify='flex-end')
    root = flex('root', 'column', [title, note, form, saved, footer],
                classes='roast-scroll')

    def _no_shrink(node):
        if isinstance(node, dict):
            for child in node.get('children', []) or []:
                pos = child.setdefault('position', {})
                pos['shrink'] = 0
                _no_shrink(child)
    _no_shrink(root)
    return {'custom': {'editNote': ''},
            'params': {'batchNumber': 0, 'createMode': False},
            'propConfig': {
                'params.batchNumber': {'paramDirection': 'input'},
                'params.createMode': {'paramDirection': 'input'}},
            'props': {'defaultSize': {'width': 660, 'height': 780}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script': BATCHEDIT_STARTUP_SCRIPT}}}},
            'root': root}

# ================================================================ write out

def write_view(path_parts, doc):
    d = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                     'views', *path_parts)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'view.json'), 'w') as f:
        json.dump(doc, f, indent=2)
    with open(os.path.join(d, 'resource.json'), 'w') as f:
        json.dump(RES, f, indent=2)

OLD_VIEWS = ('Log', 'BatchCard', 'StatTile', 'ControlPanel', 'Settings',
             'Probe')

def main():
    views_root = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                              'views', 'Views')
    for old in OLD_VIEWS:
        p = os.path.join(views_root, old)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print('removed old view', old)
    write_view(['Views', 'Main'], main_view())
    write_view(['Views', 'Config'], config_view())
    write_view(['Views', 'Batches'], batches_view())
    write_view(['Views', 'BatchesPanel'], batches_panel_view())
    write_view(['Views', 'BatchEdit'], batch_edit_view())
    write_view(['Views', 'Tile'], tile_view())
    write_view(['Views', 'EventCell'], event_cell_view())
    write_view(['Views', 'EventsStrip'], events_strip_view())
    write_view(['Views', 'PhasesBar'], phases_bar_view())
    write_view(['Views', 'Controls'], controls_view())
    write_view(['Views', 'MetaCard'], meta_card_view())
    write_view(['Views', 'Summary'], summary_view())
    pc = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                      'page-config')
    os.makedirs(pc, exist_ok=True)
    pages = {'/': {'viewPath': 'Views/Main'},
             '/batches': {'viewPath': 'Views/Batches'}}
    with open(os.path.join(pc, 'config.json'), 'w') as f:
        json.dump({'pages': pages}, f, indent=2)
    r = dict(RES, files=['config.json'])
    with open(os.path.join(pc, 'resource.json'), 'w') as f:
        json.dump(r, f, indent=2)
    write_library()
    write_named_queries()
    write_styles()
    print('Roastery v3 written to', PROJ)

if __name__ == '__main__':
    main()
