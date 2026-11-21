#!/usr/bin/env python3
"""Build the Roastery v4 project (files only) on the Maker 2027
gateway (gateway-2027-maker/data/projects/Roastery).

V4 (Eric's direction, 2026-11-12) keeps the v3 architecture
below and adds: a docked app shell (shared bottom tab bar,
mobile top HUD dock, right slide over editor dock), a
breakpoint container Roast page (control first on phones,
trend first on desktop), chart event marker lines, a Log
detail view, a sectioned Settings page, button press and
temp change capture, and the Artisan RoR parameterization
in roastery.core (one implementation for live, saved and
ghost RoR). The v3 architecture:


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

Usage: build_roastery_v4.py  (then POST /scan/projects)
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
BACKGROUND_DROP_TAG = '[default]Roastery/BackgroundDropSec'
BACKGROUND_EVENTS_TAG = '[default]Roastery/BackgroundEventsJson'
DETAIL_ANALYZER = '[default]Roastery/DetailAnalyzer'
MARKS_DS = '[default]Roastery/EventMarksDS'
BGROR_DS = '[default]Roastery/BackgroundRorDS'
LIVE_DS = '[default]Roastery/LiveCurveDS'
# fan and heat are Double in the chart dataset, matching the
# EventsLog doubles the v4 strip chart read; the stored
# CurveSamples keep Integer levels.
LIVE_COLS = ['t_stamp', 'bean', 'ror', 'fan', 'heat',
             'bg', 'bgRor', 'plan', 'proj',
             'bandDry', 'bandMai', 'bandDev', 'bandCool']
SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
NQ_EVENTS_INSERT = 'Roastery/Events/InsertPress'
# Tier 3 item 17: the target plan list lives in the TargetPlanJson
# member (JSON list of [sec, tempF] pairs); the editor staging
# tags follow the AlarmEditor precedent.
TARGET_EDITOR = '[default]Roastery/TargetEditor'
# Tier 3 item 20: between batch protocol staging (BT only). The
# scalar staging tags live in the Bbp folder (Calculator folder
# precedent) and the samples in their own dataset tag, so the
# window survives a batch save. Reset discards the window.
BBP_ROOT = '[default]Roastery/Bbp'
BBP_DS = '[default]Roastery/BbpSamplesDS'
BBP_COLS = ['t_offset_sec', 't_stamp', 'bean_temp_f']
BBP_SEED = [0.0, None, 0.0]

FORM_MEMBERS = ['BeanName', 'Origin', 'Region', 'Farm', 'Altitude',
                'Variety', 'Process', 'HarvestYear', 'MoisturePct',
                'DensityGL', 'ChargeWeightG', 'TargetDropTempF',
                'RoastLevel', 'OperatorName', 'Notes', 'WeightOutG',
                'RoastTitle', 'RoasterType', 'RoasterSizeKg',
                'RoasterHeating', 'Organization', 'VolumeInMl',
                'VolumeOutMl', 'DefectsWeightG', 'RoastedDensityGL',
                'BeanSizeMinMm', 'BeanSizeMaxMm', 'WholeColor',
                'GroundColor', 'ColorSystem', 'AmbientTempF',
                'AmbientHumidityPct', 'AmbientPressureHPa',
                'RoastedMoisturePct', 'GreensTempF', 'CuppingNotes',
                'DefectHeavyFC', 'DefectLowFC', 'DefectLightCut',
                'DefectDarkCut', 'DefectDrops', 'DefectOily',
                'DefectUneven', 'DefectTipping', 'DefectScorching',
                'DefectDivots']
FORM_INTS = ('HarvestYear', 'RoasterHeating')
FORM_FLOATS = ('MoisturePct', 'DensityGL', 'ChargeWeightG',
               'TargetDropTempF', 'WeightOutG', 'RoasterSizeKg',
               'VolumeInMl', 'VolumeOutMl', 'DefectsWeightG',
               'RoastedDensityGL', 'BeanSizeMinMm', 'BeanSizeMaxMm',
               'WholeColor', 'GroundColor', 'AmbientTempF',
               'AmbientHumidityPct', 'AmbientPressureHPa',
               'RoastedMoisturePct', 'GreensTempF')
FORM_BOOLS = ('DefectHeavyFC', 'DefectLowFC', 'DefectLightCut',
              'DefectDarkCut', 'DefectDrops', 'DefectOily',
              'DefectUneven', 'DefectTipping', 'DefectScorching',
              'DefectDivots')

EVENT_STEMS = ('DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
               'SecondCrackStart', 'SecondCrackEnd', 'Drop')
LOG_COLS = ['t_stamp', 'elapsedSec', 'kind', 'label', 'tempF', 'fan', 'heat']
CURVE_COLS = ['t_offset_sec', 't_stamp', 'bean_temp_f', 'rate_of_rise_f',
              'fan_level', 'heat_level']


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


def empty_live_dataset():
    # The seed row fixes the column types; it must carry one
    # value per LIVE_COLS entry (growing the columns without
    # growing the seed made charge() abort here, v4.4).
    return typed_empty_dataset(
        LIVE_COLS, [None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                    0.0, 0.0, 0.0, 0.0])


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
# Artisan 5.0.0 parameterization, implemented from the Artisan
# source (~/workspace/artisan-src, src/artisanlib):
# - canvas.py tgraphcanvas.compute_ror / compute_ror_simple and
#   util.py computeDeltas / arrayRoR: RoR is a difference over a
#   time span, (T[i] - T[i-ds]) / (t[i] - t[i-ds]) * 60, deg/min.
# - Delta span: settings key DeltaSpan, deltaBTspan default 20 s
#   (UI 0 to 30), converted to samples by the sampling interval;
#   here the span is applied in seconds against real timestamps,
#   which is the same math on irregular (change driven) samples.
# - Temp smoothing BEFORE differentiation: curvefilter, UI default
#   1, internal 2x+1 = 3, trailing decay weights [1..internal].
# - RoR smoothing AFTER differentiation: deltafilter, UI default
#   3, internal 2x+1 = 7, trailing decay weights [1..round(7/2)] =
#   [1,2,3,4].
# - Left endpoint noise reduction (compute_ror_simple): the left
#   point is a 5 point (else 3 point) mean around the left index.
# - polyfitRoRcalc: least squares slope over the span window.
# - optimalSmoothing (needs polyfit): Hanning windows offline and
#   a Savitzky-Golay derivative (order 1) for the RoR itself.
# - filterDropOuts (Smooth Spikes, default on): OFFLINE ONLY in
#   Artisan: median filter k=5 on temps, k=3 on RoR.
# - RoRlimitFlag: offline RoR outside [RoRlimitm, RoRlimit] =
#   [-18, 81] deg F/min becomes None. Live values are not clipped
#   (Artisan nulls only the plotted live value).
# - Offline, the first 10 samples after charge are blanked
#   (smoothETBT passes RoR_start = charge index + 10).
# - Temps are the stored truth; RoR is always (re)calculated from
#   temps by THIS implementation: the live RateOfRiseF tag, the
#   saved batch series and ghost overlays all come from here.
# The v3 EMA (tau = RoRSmoothingSec) is superseded; the tag stays
# for compatibility and is no longer read.
#
# The pure functions below use only math and builtins so the exact
# shipping math can be exercised outside the gateway (proof script
# verify_roastery_ror.py).

import math


def _median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (float(s[mid - 1]) + float(s[mid])) / 2.0


def _median_filter(values, k):
    if k <= 1 or len(values) < 3:
        return list(values)
    half = k // 2
    out = []
    for i in range(len(values)):
        out.append(_median(values[max(0, i - half):
                                  min(len(values), i + half + 1)]))
    return out


def _decay_weights(n):
    return [float(i + 1) for i in range(n)]


def _decay_avg_tail(values, weights):
    if not values:
        return None
    if not weights:
        # A filter set to 0 can yield an empty weight list (the
        # delta filter at UI 0: round(1/2) is 0 under CPython's
        # round-half-even; Jython rounds it to 1). Empty weights
        # mean no smoothing, never a division by zero.
        return values[-1]
    w = weights[-len(values):] if len(values) < len(weights) else weights
    seg = values[-len(w):]
    num = 0.0
    den = 0.0
    for v, wi in zip(seg, w):
        num += v * wi
        den += wi
    return num / den


def _decay_smooth_series(values, weights):
    out = []
    for i in range(len(values)):
        out.append(_decay_avg_tail(values[:i + 1], weights))
    return out


def _hanning_smooth_series(values, window):
    if window <= 1 or len(values) < 3:
        return list(values)
    w = [0.5 - 0.5 * math.cos(2 * math.pi * i / (window - 1))
         for i in range(window)]
    tot = sum(w)
    w = [x / tot for x in w]
    half = window // 2
    ext = [values[0]] * half + list(values) + [values[-1]] * half
    out = []
    for i in range(len(values)):
        acc = 0.0
        for j in range(window):
            acc += ext[i + j] * w[j]
        out.append(acc)
    return out


def _linreg_slope(pts):
    n = len(pts)
    if n < 2:
        return None
    mt = sum(p[0] for p in pts) / n
    mv = sum(p[1] for p in pts) / n
    num = 0.0
    den = 0.0
    for t, v in pts:
        num += (t - mt) * (v - mv)
        den += (t - mt) * (t - mt)
    if den <= 0:
        return None
    return num / den


def _left_value(sm, j):
    """Artisan compute_ror_simple left endpoint: 5 point mean
    around the left index when available, else 3 point, else raw."""
    n = len(sm)
    if j - 2 >= 0 and j + 2 < n:
        return sum(sm[j - 2:j + 3]) / 5.0
    if j - 1 >= 0 and j + 1 < n:
        return sum(sm[j - 1:j + 2]) / 3.0
    return sm[j]


def _sg_series(ts, sm, span):
    """Savitzky-Golay derivative (poly order 1) on a uniform grid,
    Artisan's optimal + polyfit path. Returns per point slopes in
    units per second, or None entries where undefined."""
    n = len(ts)
    if n < 3:
        return [None] * n
    diffs = [ts[i + 1] - ts[i] for i in range(n - 1) if ts[i + 1] > ts[i]]
    if not diffs:
        return [None] * n
    dt = _median(diffs)
    if not dt or dt <= 0:
        return [None] * n
    # linearize to the uniform grid (Artisan resamples first)
    grid_t = []
    t = ts[0]
    while t <= ts[-1] + 1e-9:
        grid_t.append(t)
        t += dt
    grid_v = []
    j = 0
    for gt in grid_t:
        while j < n - 2 and ts[j + 1] < gt:
            j += 1
        t0, t1 = ts[j], ts[j + 1]
        if t1 <= t0:
            grid_v.append(sm[j])
        else:
            grid_v.append(sm[j] + (sm[j + 1] - sm[j])
                          * (gt - t0) / (t1 - t0))
    samples = int(round(span / dt))
    if samples < 2:
        samples = 2
    if samples % 2 == 0:
        samples += 1
    half = samples // 2
    den = sum(float(k * k) for k in range(-half, half + 1))
    m = len(grid_v)
    if m <= 2 * half:
        return [None] * n
    out_grid = []
    for i in range(m):
        c = min(max(i, half), m - 1 - half)
        num = 0.0
        for k in range(-half, half + 1):
            num += k * grid_v[c + k]
        out_grid.append(num / den / dt)
    out = []
    for t in ts:
        gi = int(round((t - ts[0]) / dt))
        gi = min(max(gi, 0), len(out_grid) - 1)
        out.append(out_grid[gi] if out_grid else None)
    return out


def compute_ror_series(points, params, offline=False):
    """The one RoR implementation. points: [(t_sec, temp)] oldest
    first. params: the dict from ror_params(). Returns
    [(t_sec, ror_or_None)] aligned with the input."""
    if len(points) < 2:
        return [(t, None) for t, _v in points]
    ts = [float(p[0]) for p in points]
    temps = [float(p[1]) for p in points]
    if offline and params['spikes']:
        temps = _median_filter(temps, 5)
    curve_internal = 2 * params['curve_ui'] + 1
    if offline and params['optimal'] and params['polyfit']:
        sm = _hanning_smooth_series(temps, curve_internal)
    else:
        sm = _decay_smooth_series(temps, _decay_weights(curve_internal))
    span = float(params['span'])
    sg = offline and params['optimal'] and params['polyfit']
    sg_vals = _sg_series(ts, sm, span) if sg else None
    raw = []
    for i in range(len(points)):
        if sg:
            raw.append(sg_vals[i] * 60.0 if sg_vals[i] is not None
                       else None)
        elif params['polyfit']:
            lo_t = ts[i] - span
            window = [(ts[k], sm[k]) for k in range(len(points))
                      if lo_t - 1e-9 <= ts[k] <= ts[i]]
            slope = _linreg_slope(window)
            raw.append(slope * 60.0 if slope is not None else None)
        else:
            target = ts[i] - span
            j = -1
            for k in range(i, -1, -1):
                if ts[k] <= target + 1e-9:
                    j = k
                    break
            if j < 0:
                j = 0
            if j == i or ts[i] - ts[j] <= 0:
                raw.append(None)
            else:
                raw.append((sm[i] - _left_value(sm, j)) * 60.0
                           / (ts[i] - ts[j]))
    # delta smoothing (decay weights [1..round(internal/2)])
    delta_internal = 2 * params['delta_ui'] + 1
    filled = []
    last = None
    for r in raw:
        if r is None:
            filled.append(last if last is not None else 0.0)
        else:
            filled.append(r)
            last = r
    if offline and params['optimal'] and params['polyfit']:
        smoothed = _hanning_smooth_series(filled, delta_internal)
    else:
        smoothed = _decay_smooth_series(
            filled, _decay_weights(int(round(delta_internal / 2.0))))
    if offline and params['spikes']:
        smoothed = _median_filter(smoothed, 3)
    out = []
    for i in range(len(points)):
        r = smoothed[i]
        if raw[i] is None and i == 0:
            r = None
        if offline:
            if i < min(10, len(points)):
                r = None
            elif r is not None and (r < params['clip_lo']
                                    or r > params['clip_hi']):
                r = None
        out.append((ts[i], r))
    return out


def ror_params():
    """Current RoR parameters from the batch tags, clamped to the
    Artisan UI ranges (span is allowed past the Artisan 30 s combo
    limit up to 120 s for slow home roasts; filters are not)."""
    vals = read_members(['RoRDeltaSpanSec', 'RoRCurveFilter',
                         'RoRDeltaFilter', 'RoRSmoothSpikes',
                         'RoRPolyfit', 'RoROptimalSmoothing',
                         'RoRClipLowF', 'RoRClipHighF'])

    def _clamp(v, lo, hi, dflt):
        try:
            v = int(v)
        except Exception:
            return dflt
        return max(lo, min(hi, v))

    lo = vals['RoRClipLowF']
    hi = vals['RoRClipHighF']
    return {
        'span': _clamp(vals['RoRDeltaSpanSec'], 0, 120, 20),
        'curve_ui': _clamp(vals['RoRCurveFilter'], 0, 5, 1),
        'delta_ui': _clamp(vals['RoRDeltaFilter'], 0, 40, 3),
        'spikes': bool(vals['RoRSmoothSpikes']),
        'polyfit': bool(vals['RoRPolyfit']),
        'optimal': bool(vals['RoROptimalSmoothing']),
        'clip_lo': float(lo) if lo is not None else -18.0,
        'clip_hi': float(hi) if hi is not None else 81.0}


# Live RoR keeps a trailing buffer of (epoch ms, temp) samples in
# the _RoRLiveJson member (JSON), trimmed to the last 300 s. Every
# BeanTempF change recomputes the current RoR from the buffer with
# compute_ror_series, so the live value can never drift from the
# saved and ghost math.
ROR_BUFFER_MS = 300000


def _ror_buffer(temp, now_ms):
    raw = read_members(['_RoRLiveJson'])['_RoRLiveJson']
    samples = []
    if raw:
        try:
            samples = system.util.jsonDecode(raw)
        except Exception:
            samples = []
    if samples and abs(temp - samples[-1][1]) > 50.0:
        # Probe jump (transport switch or simulator program wrap):
        # reseed instead of deriving a spike (kept from v3).
        samples = []
    samples.append([now_ms, float(temp)])
    cutoff = now_ms - ROR_BUFFER_MS
    samples = [s for s in samples if s[0] >= cutoff][-900:]
    system.tag.writeBlocking([path('_RoRLiveJson')],
                             [system.util.jsonEncode(samples)])
    return samples


def _live_ror(temp, now_ms):
    samples = _ror_buffer(temp, now_ms)
    if len(samples) < 2:
        return None
    t0 = samples[0][0]
    points = [((s[0] - t0) / 1000.0, s[1]) for s in samples]
    series = compute_ror_series(points, ror_params(), offline=False)
    for _t, r in reversed(series):
        if r is not None:
            return r
    return None


def on_bean_temp(tag_path, current_value, initial_change):
    """BeanTempF valueChanged handler. The tag event script is a
    one line call to this function.

    Two jobs, both change driven (Eric, 2026-11-12):
    1. Derive RateOfRiseF with the Artisan parameterization
       (compute_ror_series over the live buffer).
    2. While a roast is active (State Roasting or Cooling), append
       one curve sample per temperature change to CurveSamples;
       roastery.batches writes those to batch_series at save time.
       In SeriesCaptureMode 'Group' a transaction group owns the
       series rows and this append is skipped.
    """
    temp = current_value.value
    if temp is None:
        return
    now = current_value.timestamp
    now_ms = long(now.getTime())
    if initial_change:
        _ror_buffer(temp, now_ms)
        return
    ror = _live_ror(temp, now_ms)
    if ror is not None:
        write_members([('RateOfRiseF', ror)])
    vals = read_members(['State', 'StartTime', 'FanLevel', 'HeatLevel',
                         'SeriesCaptureMode'])
    if (vals['State'] in ('Roasting', 'Cooling')
            and vals['StartTime'] is not None
            and vals['SeriesCaptureMode'] != 'Group'):
        elapsed = int((now_ms - vals['StartTime'].getTime()) / 1000)
        append_curve_sample(elapsed, now, temp,
                            ror if ror is not None else 0.0,
                            vals['FanLevel'], vals['HeatLevel'])
    try:
        # Between batch capture (Tier 3 item 20) rides the same
        # change path: after DROP, samples stage into the BBP
        # window until the next CHARGE finalizes them.
        _bbp_capture(float(temp), now, now_ms)
    except Exception:
        pass
    try:
        _live_analytics(float(temp), now_ms, ror)
    except Exception:
        # Turning point, AUC and alarms ride on the temp change;
        # a failure here must never break RoR or sampling.
        pass


# ------------------------------------------------------- live analytics
# Turning point, AUC and the alarm table, all computed on the
# bean temp change path from the same stored samples and tags
# the rest of the app reads (single sensor: the one BT curve).

TP_RISE_F = 5.0


def _track_turning_point(temp, elapsed):
    """Live turning point: the running bean temp minimum after
    charge, confirmed once the temp has risen TP_RISE_F above
    that minimum. Artisan reads the TP off a finished curve as
    the minimum between charge and first crack (findTPint);
    live, the same point is published as soon as the rise
    confirms it, and a lower minimum before first crack moves
    it, matching the offline read."""
    vals = read_members(['_TpMinTempF', '_TpMinElapsedSec',
                         'TurningPointElapsedSec',
                         'TurningPointTempF'])
    min_t = vals['_TpMinTempF']
    min_e = vals['_TpMinElapsedSec']
    if min_e is None or min_e < 0 or temp < min_t:
        min_t, min_e = temp, elapsed
        write_members([('_TpMinTempF', min_t),
                       ('_TpMinElapsedSec', min_e)])
    if temp >= min_t + TP_RISE_F:
        if (vals['TurningPointElapsedSec'] != min_e
                or vals['TurningPointTempF'] != min_t):
            write_members([('TurningPointElapsedSec', int(min_e)),
                           ('TurningPointTempF', float(min_t))])
            build_marks()


def auc_between(points, begin_sec, base):
    """Trapezoid area between the bean curve and the base temp,
    from begin_sec on, in degree minutes. Per segment the
    average of the two endpoint temps above the base times the
    segment minutes; segments at or below the base contribute
    nothing (Artisan calcAUC shape). points: [(t_sec, temp)]
    oldest first."""
    pts = [(float(t), float(v)) for t, v in points if t >= begin_sec]
    auc = 0.0
    for i in range(len(pts) - 1):
        dt = (pts[i + 1][0] - pts[i][0]) / 60.0
        if dt <= 0:
            continue
        avg = (pts[i][1] + pts[i + 1][1]) / 2.0
        if avg > base:
            auc += (avg - base) * dt
    return auc


def _auc_begin(vals):
    """Resolve the AUC begin setting to (begin_sec, base_temp).
    begin_sec is None while the chosen begin event has not
    happened yet. With AucBaseFromEvent the base is the bean
    temp at the begin event (Artisan's AUCbaseFlag)."""
    name = vals['AucBegin'] or 'TP'
    base = float(vals['AucBaseTempF'] or 0.0)
    if name == 'Charge':
        if vals['AucBaseFromEvent']:
            base = float(vals['ChargeTempF'] or base)
        return 0, base
    if name == 'Dry End':
        sec, tmp = vals['DryEndElapsedSec'], vals['DryEndTempF']
    elif name == 'FC Start':
        sec, tmp = (vals['FirstCrackStartElapsedSec'],
                    vals['FirstCrackStartTempF'])
    else:
        sec, tmp = (vals['TurningPointElapsedSec'],
                    vals['TurningPointTempF'])
    if sec is None or sec < 0:
        return None, base
    if vals['AucBaseFromEvent']:
        base = float(tmp or base)
    return int(sec), base


def update_live_auc(ror):
    """Recompute the live AUC readouts from the recorded curve
    samples: temps are the truth, the integral is recomputed
    from them on every change and never accumulated, so it
    cannot drift. The guide projects when the AUC target is
    reached at the current RoR, solving Artisan's quadratic
    (RoR/2) t^2 + (BT - base) t + (AUC - target) = 0 for its
    smallest positive root (updateAUCguide)."""
    vals = read_members(['State', 'StartTime', 'AucBegin',
                         'AucBaseTempF', 'AucBaseFromEvent',
                         'AucTargetFMin', 'AucGuideEnabled',
                         'ChargeTempF', 'DryEndElapsedSec',
                         'DryEndTempF', 'FirstCrackStartElapsedSec',
                         'FirstCrackStartTempF',
                         'TurningPointElapsedSec',
                         'TurningPointTempF', 'DropElapsedSec',
                         'BeanTempF'])
    if vals['StartTime'] is None or vals['State'] == 'Idle':
        return
    begin_sec, base = _auc_begin(vals)
    points = [(float(p['t']), float(p['bt']))
              for p in curve_points()]
    drop_sec = vals['DropElapsedSec']
    if drop_sec is not None and drop_sec >= 0:
        points = [p for p in points if p[0] <= drop_sec]
    auc = (auc_between(points, begin_sec, base)
           if begin_sec is not None else 0.0)
    fc_sec = vals['FirstCrackStartElapsedSec']
    since_fc = (auc_between(points, int(fc_sec), base)
                if fc_sec is not None and fc_sec >= 0 else 0.0)
    guide = -1
    target = float(vals['AucTargetFMin'] or 0.0)
    bt = float(vals['BeanTempF'] or 0.0)
    if (vals['AucGuideEnabled'] and ror is not None and ror > 0
            and 0 < auc < target):
        disc = (bt - base) ** 2 - 2.0 * ror * (auc - target)
        if disc >= 0:
            t_min = (-(bt - base) + math.sqrt(disc)) / ror
            if t_min > 0:
                guide = (elapsed_sec(vals['StartTime'])
                         + int(t_min * 60))
    write_members([('AucLiveFMin', auc),
                   ('AucSinceFcFMin', since_fc),
                   ('AucGuideElapsedSec', guide)])


ALARM_GUARD_MEMBERS = {'Dry End': 'DryEndElapsedSec',
                       'FC Start': 'FirstCrackStartElapsedSec',
                       'FC End': 'FirstCrackEndElapsedSec',
                       'SC Start': 'SecondCrackStartElapsedSec',
                       'SC End': 'SecondCrackEndElapsedSec',
                       'Drop': 'DropElapsedSec'}


def alarm_definitions():
    """The alarm table from the AlarmDefsJson tag: a JSON list
    of Artisan style definitions {name, enabled, guard,
    offsetSec, source, cond, value, message, action}, where
    guard is an event the alarm arms after, source is BT, RoR
    or Time (elapsed seconds), cond is >= or <=, and action is
    Banner (shows while the condition holds) or Message
    (latches until the next charge or reset)."""
    raw = read_members(['AlarmDefsJson'])['AlarmDefsJson']
    if not raw:
        return []
    try:
        defs = system.util.jsonDecode(raw)
    except Exception:
        return []
    return defs if isinstance(defs, list) else []


def _alarm_guard_elapsed(guard, vals):
    if guard in (None, '', 'None', 'Charge'):
        return 0
    if guard == 'TP':
        v = vals['TurningPointElapsedSec']
    else:
        member = ALARM_GUARD_MEMBERS.get(guard)
        if member is None:
            return None
        v = vals[member]
    if v is None or v < 0:
        return None
    return int(v)


def evaluate_alarms():
    """Evaluate the alarm table against the live tags and
    publish AlarmText / AlarmActive for the Roast page banner.
    An alarm arms only once its guard event has happened plus
    its offset seconds."""
    members = ['State', 'StartTime', 'BeanTempF', 'RateOfRiseF',
               '_AlarmFiredJson', 'TurningPointElapsedSec']
    members += list(ALARM_GUARD_MEMBERS.values())
    vals = read_members(members)
    if (vals['State'] not in ('Roasting', 'Dropped', 'Cooling')
            or vals['StartTime'] is None):
        if vals['State'] == 'Idle':
            write_members([('AlarmText', ''), ('AlarmActive', False)])
        return
    elapsed = elapsed_sec(vals['StartTime'])
    fired = []
    if vals['_AlarmFiredJson']:
        try:
            fired = system.util.jsonDecode(vals['_AlarmFiredJson'])
        except Exception:
            fired = []
    texts = []
    fired_changed = False
    for i, a in enumerate(alarm_definitions()):
        if not a.get('enabled', True):
            continue
        g = _alarm_guard_elapsed(a.get('guard'), vals)
        if g is None or elapsed < g + int(a.get('offsetSec') or 0):
            continue
        src = a.get('source') or 'BT'
        if src == 'RoR':
            v = float(vals['RateOfRiseF'] or 0.0)
        elif src == 'Time':
            v = float(elapsed)
        else:
            v = float(vals['BeanTempF'] or 0.0)
        try:
            target = float(a.get('value'))
        except Exception:
            continue
        hit = (v >= target if (a.get('cond') or '>=') == '>='
               else v <= target)
        msg = a.get('message') or a.get('name') or 'Alarm'
        if a.get('action') == 'Message':
            if hit and i not in fired:
                fired.append(i)
                fired_changed = True
            if i in fired:
                texts.append(msg)
        elif hit:
            texts.append(msg)
    pairs = [('AlarmText', ' | '.join(texts)),
             ('AlarmActive', bool(texts))]
    if fired_changed:
        pairs.append(('_AlarmFiredJson',
                      system.util.jsonEncode(fired)))
    write_members(pairs)


def _live_analytics(temp, now_ms, ror):
    try:
        # The deviation tile reads the variable length target
        # plan (Tier 3 item 17), which a view expression cannot
        # do; the library publishes the text instead, the same
        # pattern as BgDeviationText.
        update_plan_deviation(temp)
    except Exception:
        pass
    vals = read_members(['State', 'StartTime',
                         'FirstCrackStartElapsedSec'])
    state = vals['State']
    if (state not in ('Roasting', 'Cooling', 'Dropped')
            or vals['StartTime'] is None):
        return
    elapsed = int((now_ms - vals['StartTime'].getTime()) / 1000)
    if (state == 'Roasting'
            and (vals['FirstCrackStartElapsedSec'] or -1) < 0):
        _track_turning_point(temp, elapsed)
    update_live_auc(ror)
    evaluate_alarms()
    update_bg_deviation(temp, elapsed)
    # Tier 2 items 11, 13 and 14 ride the same temp change path.
    # Each is isolated: a failure in one must never break the
    # others or the RoR and sampling work above.
    for fn in (evaluate_playback, evaluate_suggestions):
        try:
            fn(temp, elapsed)
        except Exception:
            pass
    try:
        update_analyzer()
    except Exception:
        pass


def _reset_live_analytics():
    write_members([('TurningPointElapsedSec', -1),
                   ('TurningPointTempF', 0.0),
                   ('_TpMinTempF', 0.0), ('_TpMinElapsedSec', -1),
                   ('AucLiveFMin', 0.0), ('AucSinceFcFMin', 0.0),
                   ('AucGuideElapsedSec', -1),
                   ('AlarmText', ''), ('AlarmActive', False),
                   ('_AlarmFiredJson', ''),
                   ('BgDeviationText', '--'),
                   ('PlaybackText', ''), ('PlaybackActive', False),
                   ('_PlaybackFiredJson', ''),
                   ('SuggestionText', ''),
                   ('SuggestionActive', False),
                   ('SuggestionKind', ''),
                   ('_DrySuggested', False),
                   ('_FcSuggested', False),
                   ('AnalyzerSec', -1),
                   ('AnalyzerTimeText', '--:--'),
                   ('AnalyzerBtText', '--'),
                   ('AnalyzerRorText', '--'),
                   ('AnalyzerBgText', '--'),
                   ('AnalyzerDevText', '--'),
                   ('AnalyzerHasBg', False)])


def clear_background():
    """Clear the staged background ghost (Roast page chart
    card Clear button): drop the staged points and label and
    rebuild the overlays. Pending playback prompts die with
    the ghost (Tier 2 item 11)."""
    system.tag.writeBlocking(
        [BACKGROUND_JSON, '[default]Roastery/BackgroundLabel',
         BACKGROUND_DROP_TAG, BACKGROUND_EVENTS_TAG],
        ['', '', -1.0, ''])
    write_members([('BgPhaseDrySec', -1), ('BgPhaseFcSec', -1),
                   ('BgPhaseDropSec', -1),
                   ('BgDeviationText', '--'),
                   ('PlaybackText', ''), ('PlaybackActive', False),
                   ('_PlaybackFiredJson', '')])
    build_overlays()


# ------------------------------------------------------- alarm editor
# The Settings Alarms section edits the AlarmDefsJson table
# through these functions: a read only table dataset plus a
# per alarm editor on view custom props (the same custom prop
# plus library pattern the batch editor uses).

ALARM_EDITOR_COLS = ['idx', 'name', 'enabled', 'guard',
                     'offsetSec', 'source', 'cond', 'value',
                     'message', 'action']
ALARM_GUARDS = ['None', 'Charge', 'TP', 'Dry End', 'FC Start',
                'FC End', 'SC Start', 'SC End', 'Drop']
ALARM_SOURCES = ['BT', 'RoR', 'Time']
ALARM_ACTIONS = ['Banner', 'Message']


def alarms_table_dataset():
    rows = []
    for i, a in enumerate(alarm_definitions()):
        rows.append([i, a.get('name') or '',
                     bool(a.get('enabled', True)),
                     a.get('guard') or 'None',
                     int(a.get('offsetSec') or 0),
                     a.get('source') or 'BT',
                     a.get('cond') or '>=',
                     a.get('value') if a.get('value') is not None
                     else '',
                     a.get('message') or '',
                     a.get('action') or 'Banner'])
    return system.dataset.toDataSet(ALARM_EDITOR_COLS, rows)


def alarms_startup(self):
    self.view.custom.alarmsDs = alarms_table_dataset()
    self.view.custom.alarmCount = len(alarm_definitions())
    if alarm_definitions():
        alarm_editor_load(self, 0)


ALARM_EDITOR = '[default]Roastery/AlarmEditor'
ALARM_EDITOR_FIELDS = ('Idx', 'Name', 'Message', 'Enabled',
                       'Guard', 'OffsetSec', 'Source', 'Cond',
                       'Value', 'Action')


def _ed_paths():
    return [ALARM_EDITOR + '/' + f for f in ALARM_EDITOR_FIELDS]


def alarm_editor_load(self, idx):
    defs = alarm_definitions()
    idx = int(idx)
    if idx < 0 or idx >= len(defs):
        return
    a = defs[idx]
    self.view.custom.alarmIdx = idx
    system.tag.writeBlocking(
        _ed_paths(),
        [idx, a.get('name') or '', a.get('message') or '',
         bool(a.get('enabled', True)), a.get('guard') or 'None',
         int(a.get('offsetSec') or 0), a.get('source') or 'BT',
         a.get('cond') or '>=', float(a.get('value') or 0),
         a.get('action') or 'Banner'])


def alarm_editor_load_idx(self):
    """Load whichever alarm the index dropdown currently
    shows (its value lives in the AlarmEditor/Idx tag)."""
    idx = system.tag.readBlocking(
        [ALARM_EDITOR + '/Idx'])[0].value
    alarm_editor_load(self, int(idx or 0))


def _alarm_editor_idx(self):
    idx = system.tag.readBlocking(
        [ALARM_EDITOR + '/Idx'])[0].value
    return int(idx or 0)


def _alarm_from_editor(self):
    # The editor fields are bound to the AlarmEditor staging
    # tags: view.custom property bindings push library values
    # into components but never write user edits back in this
    # build (proven in the Tier 1 verify round), while tag
    # bindings are the app's proven bidirectional path.
    vals = system.tag.readBlocking(_ed_paths())
    d = dict((f, v.value) for f, v in
             zip(ALARM_EDITOR_FIELDS, vals))
    return {'name': d.get('Name') or 'Alarm',
            'enabled': bool(d.get('Enabled')),
            'guard': d.get('Guard') or 'None',
            'offsetSec': int(d.get('OffsetSec') or 0),
            'source': d.get('Source') or 'BT',
            'cond': d.get('Cond') or '>=',
            'value': float(d.get('Value') or 0),
            'message': d.get('Message') or '',
            'action': d.get('Action') or 'Banner'}


def _save_alarm_defs(self, defs):
    system.tag.writeBlocking([path('AlarmDefsJson')],
                             [system.util.jsonEncode(defs)])
    self.view.custom.alarmsDs = alarms_table_dataset()
    self.view.custom.alarmCount = len(defs)
    try:
        evaluate_alarms()
    except Exception:
        pass


def alarm_editor_save(self):
    defs = alarm_definitions()
    idx = _alarm_editor_idx(self)
    entry = _alarm_from_editor(self)
    if 0 <= idx < len(defs):
        defs[idx] = entry
    else:
        defs.append(entry)
        idx = len(defs) - 1
    _save_alarm_defs(self, defs)
    self.view.custom.alarmIdx = idx
    self.view.custom.alarmNote = ('Saved alarm %d: %s'
                                  % (idx + 1, entry['name']))


def alarm_editor_add(self):
    defs = alarm_definitions()
    entry = _alarm_from_editor(self)
    defs.append(entry)
    _save_alarm_defs(self, defs)
    alarm_editor_load(self, len(defs) - 1)
    self.view.custom.alarmNote = ('Added alarm %d: %s'
                                  % (len(defs), entry['name']))


def alarm_editor_delete(self):
    defs = alarm_definitions()
    idx = _alarm_editor_idx(self)
    if 0 <= idx < len(defs):
        gone = defs.pop(idx)
        _save_alarm_defs(self, defs)
        self.view.custom.alarmNote = ('Deleted alarm: %s'
                                      % (gone.get('name') or ''))
        if defs:
            alarm_editor_load(self, min(idx, len(defs) - 1))


# ---------------------------------------------------------------- press capture

def record_press(action):
    """Capture one control button press (Eric, 2026-11-12: the
    button presses are the trigger). Every press bumps the
    ActionCounter trigger surface and stamps LastAction tags; in
    PressCaptureMode 'Library' the press row is also written to
    batch_events through the Events/InsertPress named query. In
    'Group' mode a SQLBridge transaction group bound to
    ActionCounter writes the row instead. Returns the counter."""
    vals = read_members(['ActionCounter', 'BatchNumber', 'StartTime',
                         'BeanTempF', 'RateOfRiseF', 'FanLevel',
                         'HeatLevel', 'PressCaptureMode'])
    elapsed = elapsed_sec(vals['StartTime'])
    counter = int(vals['ActionCounter'] or 0) + 1
    write_members([('ActionCounter', counter), ('LastAction', action),
                   ('LastActionElapsedSec', elapsed),
                   ('LastActionAt', system.date.now())])
    if vals['PressCaptureMode'] != 'Group':
        try:
            system.db.runNamedQuery(NQ_EVENTS_INSERT, {
                'batch_number': int(vals['BatchNumber'] or 0),
                'action': action,
                't_offset_sec': elapsed,
                'bean_temp_f': vals['BeanTempF'],
                'rate_of_rise_f': vals['RateOfRiseF'],
                'fan_level': int(vals['FanLevel'] or 0),
                'heat_level': int(vals['HeatLevel'] or 0)})
        except Exception:
            # Capture must never break the control it rides on.
            pass
    try:
        # A press can move fan or heat between temperature
        # changes; refresh the chart dataset so the levels strip
        # shows the step at once (build_live_curve is also called
        # on every appended curve sample).
        build_live_curve()
    except Exception:
        pass
    try:
        # A press can stamp the event an alarm guards on; let
        # the table see it without waiting for a temp change.
        evaluate_alarms()
    except Exception:
        pass
    return counter


# ---------------------------------------------------------------- chart marks

MARK_TOP = 455.0
MARK_BOTTOM = 152.0
MARK_EVENTS = (('Charge', 'CHARGE'), ('DryEnd', 'DRY END'),
               ('FirstCrackStart', 'FC START'),
               ('FirstCrackEnd', 'FC END'),
               ('SecondCrackStart', 'SC START'),
               ('SecondCrackEnd', 'SC END'), ('Drop', 'DROP'))


MARK_COLS = ['t_stamp', 'charge', 'dryEnd', 'fcStart', 'fcEnd',
             'scStart', 'scEnd', 'drop', 'notes']
_MARK_COL_FOR = {'CHARGE': 'charge', 'DRY END': 'dryEnd',
                 'FC START': 'fcStart', 'FC END': 'fcEnd',
                 'SC START': 'scStart', 'SC END': 'scEnd',
                 'DROP': 'drop'}


def marks_dataset(evs):
    """Build the marker dataset shared by the live chart and the
    Log detail chart. One column per event: an event's line lives
    in its own column, so the chart can give it its own series,
    named in the legend. Bullet labels on XY line series do not
    render text in this build (proven live: neither a {label}
    field template nor static text appeared, with visible and
    invisible bullets, inside or below the plot area), so series
    naming is the labeling route. Each event contributes a top
    point (455 F), a bottom point (152 F) and an all null gap row
    in its column so consecutive events never connect.

    X values are ELAPSED dates (epoch + elapsed seconds), the
    v4.1 axis: every chart dataset is anchored to the roast's own
    zero, never to wall clock, and the axis formats them mm:ss."""
    from java.util import Date
    idx = dict((c, i + 1) for i, c in enumerate(MARK_COLS[1:]))
    rows = []
    for e, lbl in sorted(evs):
        col = _MARK_COL_FOR.get(lbl, 'notes')
        ts = Date(long(e * 1000))
        top = [ts] + [None] * (len(MARK_COLS) - 1)
        top[idx[col]] = MARK_TOP
        bot = [ts] + [None] * (len(MARK_COLS) - 1)
        bot[idx[col]] = MARK_BOTTOM
        gap = [ts] + [None] * (len(MARK_COLS) - 1)
        rows += [top, bot, gap]
    return system.dataset.toDataSet(MARK_COLS, rows)


def _live_events():
    """The current roast's stamped events as (elapsed sec,
    label) pairs, charge first: the single source both marker
    representations read (the EventMarksDS dataset and the
    canvas charts' reference lines)."""
    members = ['StartTime', 'State', 'TurningPointElapsedSec']
    for stem, _lbl in MARK_EVENTS[1:]:
        members.append(stem + 'ElapsedSec')
    for i in (1, 2, 3, 4):
        members += ['CustomEvent%dElapsedSec' % i,
                    'CustomEvent%dName' % i]
    vals = read_members(members)
    evs = []
    if vals['StartTime'] is not None and vals['State'] != 'Idle':
        evs = [(0, 'CHARGE')]
        tp = vals['TurningPointElapsedSec']
        if tp is not None and tp >= 0:
            # 'TP' has no column of its own in MARK_COLS, so the
            # marks dataset files it under notes; the canvas
            # reference lines carry the label.
            evs.append((int(tp), 'TP'))
        for stem, lbl in MARK_EVENTS[1:]:
            e = vals[stem + 'ElapsedSec']
            if e is not None and e >= 0:
                evs.append((int(e), lbl))
        for i in (1, 2, 3, 4):
            e = vals['CustomEvent%dElapsedSec' % i]
            if e is not None and e >= 0:
                nm = vals['CustomEvent%dName' % i] or 'CUSTOM'
                evs.append((int(e), nm.upper()))
    return evs


def build_marks():
    """Rebuild EventMarksDS from the stamped event tags, as a
    column-per-event marker dataset (marks_dataset). Kept as
    the marker record of the roast (the verification suite
    asserts it); the canvas charts render the same events from
    event_reference_lines instead."""
    ds = marks_dataset(_live_events())
    system.tag.writeBlocking([MARKS_DS], [ds])


def _ref_items(evs, top_gap=120.0, mid_gap=45.0, mid_top_gap=45.0):
    """Canvas chart reference line items for (elapsed sec,
    label) events: native ECharts markLines through the
    component's series referenceLines. Labels sit at the top
    of the plot (position 'end', proven in the 2026-11-13
    probe round) unless the collision policy in the loop
    moves or drops them. Values are epoch milliseconds on the
    elapsed time axis, clamped to the axis minimum of
    1000 ms: the axis starts 1 s in so its first tick reads
    00:01 instead of the year 1970 (the epoch boundary tick
    gets a year format from ECharts), and a line at 0 would
    fall outside the plot."""
    items = []
    last_top = None
    last_mid = None
    for sec, lbl in sorted(evs, key=lambda e: float(e[0])):
        sec = float(sec)
        # Label collision policy (Eric, 2026-11-13, no overlap
        # pass): labels ride the top of the plot ('end') only
        # when they stand at least 120 s clear of the previous
        # top label. (An audit roast with FC Start 100 s after
        # Charge still merged the two top labels on the phone
        # chart, where 100 s is only about 30px.) A closer event
        # drops its label to the middle of the line when the
        # middle slot is also clear (45 s from the last middle
        # label and from the top one); anything tighter renders
        # the line with no label at all rather than print
        # unreadable stacked text. The event strip under the
        # chart always carries the name.
        if last_top is None or sec - last_top >= top_gap:
            pos, vis = 'end', True
            last_top = sec
        elif (sec - last_top >= mid_top_gap
                and (last_mid is None or sec - last_mid >= mid_gap)):
            pos, vis = 'middle', True
            last_mid = sec
        else:
            pos, vis = 'end', False
        items.append({
            'value': max(1000, int(sec * 1000)),
            'orientation': 'vertical',
            'label': {'visible': vis, 'position': pos,
                      'text': lbl, 'color': '#f59e0b',
                      'fontSize': 11, 'elementStyle': {}},
            'line': {'color': '#f59e0b', 'width': 1.5,
                     'type': 'dashed', 'opacity': 0.9}})
    return items


def event_reference_lines():
    """Reference line items for the live chart's bean series,
    bound through a script transform triggered by the
    EventMarksDS tag (rewritten on every press)."""
    return _ref_items(_live_events())


def event_reference_lines_compact():
    """Phone variant of the marker labels (no overlap pass):
    the phone chart squeezes a whole roast into about 215px,
    so two labels in the same band need roughly 150 s of
    separation not to touch. The compact policy spaces top
    labels 150 s apart and middle labels 150 s apart; an
    event that fits neither band keeps its line and drops
    its label. The events strip directly under the phone
    chart names every event, so nothing is lost."""
    return _ref_items(_live_events(), top_gap=150.0,
                      mid_gap=150.0, mid_top_gap=30.0)


def append_curve_sample(elapsed, t_stamp, temp, ror, fan, heat):
    """Append one curve sample (temp change capture). Dedupes only
    an unchanged second with an unchanged temp, so a steady probe
    cannot flood the dataset; every real change lands."""
    ds = system.tag.readBlocking([CURVE_SAMPLES])[0].value
    if ds is None or ds.rowCount == 0:
        # An empty read also heals a legacy string typed dataset:
        # the tag value is replaced with a properly typed one.
        ds = empty_curve_dataset()
    if ds.rowCount > 0:
        last_t = ds.getValueAt(ds.rowCount - 1, 't_offset_sec')
        last_bt = ds.getValueAt(ds.rowCount - 1, 'bean_temp_f')
        if (last_t is not None and int(float(last_t)) == int(elapsed)
                and last_bt is not None
                and abs(float(last_bt) - float(temp)) < 0.05):
            return
    ds = system.dataset.addRow(ds, [float(elapsed), t_stamp, float(temp),
                                    float(ror), int(fan), int(heat)])
    system.tag.writeBlocking([CURVE_SAMPLES], [ds])
    build_live_curve()



# ------------------------------------------------------- Tier 2: projection
# BT projection lines (item 9) and live deviation from the
# background (item 10a).

PROJECTION_HORIZON_SEC = 120
PROJECTION_STEP_SEC = 15


def projection_points(points, rors):
    """BT projection, Artisan canvas.py updateProjection shape.
    Linear mode extends the curve forward at the current RoR.
    Quadratic mode (only after five minutes elapsed, as in
    Artisan) lets the RoR itself drift linearly: the RoR trend
    over the lookback window gives deltadelta in F/sec/sec,
    clamped to Artisan's deltadeltalimit of 0.002, and the
    projection integrates it step by step. points and rors are
    the aligned live curve lists from build_live_curve.
    Display only: the points merge into LiveCurveDS and are
    never stored. Returns [(t_sec, temp)] including the anchor
    point, or [] when projection is off, the roast is not
    running (Artisan draws projections only after CHARGE and
    before DROP), or the current RoR is zero or unknown."""
    vals = read_members(['ProjectionEnabled', 'ProjectionMode',
                         'State'])
    if not vals['ProjectionEnabled'] or vals['State'] != 'Roasting':
        return []
    if len(points) < 2:
        return []
    t_last, bt_last = points[-1]
    ror_last = None
    for _t, r in reversed(rors):
        if r is not None:
            ror_last = r
            break
    if ror_last is None or ror_last == 0:
        return []
    quad = ((vals['ProjectionMode'] or 'Linear') == 'Quadratic'
            and t_last > 300)
    deltadelta = 0.0
    if quad:
        old = None
        for i in range(len(rors) - 1, -1, -1):
            if (rors[i][1] is not None and rors[i][0] <= t_last - 30
                    and i <= len(rors) - 11):
                old = rors[i]
                break
        if old is None or old[1] <= 0 or ror_last <= 0:
            quad = False
        else:
            deltadelta = ((ror_last - old[1]) / 60.0) / (t_last - old[0])
            deltadelta = max(-0.002, min(0.002, deltadelta))
    out = [(t_last, bt_last)]
    temp = float(bt_last)
    delta_sec = ror_last / 60.0
    steps = PROJECTION_HORIZON_SEC // PROJECTION_STEP_SEC
    for k in range(1, steps + 1):
        temp += delta_sec * PROJECTION_STEP_SEC
        if quad:
            delta_sec += deltadelta * PROJECTION_STEP_SEC
        out.append((t_last + k * PROJECTION_STEP_SEC, temp))
    return out


def background_points():
    """The staged ghost curve as sorted [(t_sec, temp)] pairs,
    from the BackgroundCurveJson tag both ghost routes write
    (saved batch via roastery.batches.set_background, file via
    roastery.artisan.stage_background_upload)."""
    raw = system.tag.readBlocking([BACKGROUND_JSON])[0].value
    if not raw:
        return []
    try:
        pairs = system.util.jsonDecode(raw)
    except Exception:
        return []
    out = [(float(p[0]), float(p[1])) for p in pairs]
    out.sort()
    return out


def interp_at(pairs, t):
    """Piecewise linear interpolation over sorted (t, v) pairs;
    None outside the covered range."""
    if not pairs or t < pairs[0][0] or t > pairs[-1][0]:
        return None
    for i in range(len(pairs) - 1):
        t0, v0 = pairs[i]
        t1, v1 = pairs[i + 1]
        if t0 <= t <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pairs[-1][1]


def update_bg_deviation(temp, elapsed):
    """Live deviation from the background (Tier 2 item 10a):
    live BT minus the ghost BT at the same elapsed time,
    published as text on the BgDeviationText tag for the Roast
    page tile and summary. '--' when no ghost is staged or the
    elapsed time is outside the ghost's range."""
    bg = interp_at(background_points(), float(elapsed))
    text = '--' if bg is None else '%+.1f F' % (float(temp) - bg)
    write_members([('BgDeviationText', text)])


# ------------------------------------------------------- Tier 2 items 11 to 14
# Background playback prompts (11), display smoothing for the
# BT line (12), the analyzer crosshair readout (13) and auto
# event suggestions for Dry End and FC Start (14). All four are
# advisory or display only: nothing in this section ever writes
# FanLevel, HeatLevel or an event tag. Control stays manual.


def build_background_events(rows, drop_sec):
    """Derive the playback event list for a staged ghost from
    its per sample levels. rows: [(t_sec, fan, heat)] oldest
    first (batch_series rows for a saved batch, imported
    samples for an .alog). The first row sets the starting
    levels (no prompt: the roaster sets those before charge);
    every later change of Fan or Heat becomes one event, and
    the ghost DROP time becomes a Drop event when known.
    Returns [{'t': sec, 'kind': 'Fan'|'Heat'|'Drop',
    'level': int or None}] sorted by time. Both ghost staging
    routes (roastery.batches.set_background and
    roastery.artisan.stage_background_upload) store the result
    as JSON on the BackgroundEventsJson tag."""
    events = []
    prev_fan = prev_heat = None
    for t, fan, heat in sorted(rows):
        if fan is not None:
            fan = int(float(fan))
            if prev_fan is not None and fan != prev_fan:
                events.append({'t': float(t), 'kind': 'Fan',
                               'level': fan})
            prev_fan = fan
        if heat is not None:
            heat = int(float(heat))
            if prev_heat is not None and heat != prev_heat:
                events.append({'t': float(t), 'kind': 'Heat',
                               'level': heat})
            prev_heat = heat
    if drop_sec is not None and float(drop_sec) > 0:
        events.append({'t': float(drop_sec), 'kind': 'Drop',
                       'level': None})
    events.sort(key=lambda e: e['t'])
    return events


def background_events():
    """The staged ghost's playback events from the
    BackgroundEventsJson tag ([] when no ghost is staged)."""
    raw = system.tag.readBlocking([BACKGROUND_EVENTS_TAG])[0].value
    if not raw:
        return []
    try:
        evs = system.util.jsonDecode(raw)
    except Exception:
        return []
    return evs if isinstance(evs, list) else []


def evaluate_playback(temp, elapsed):
    """Background playback prompts (item 11). Artisan
    background.py / canvas.py playbackevent() replays the
    background profile's slider events by time, each exactly
    once (its replayedBackgroundEvents set), with DROP behind
    its own flag (backgroundPlaybackDROP); the
    backgroundReproduceBeep option beeps. Roastery keeps the
    by time, once each shape and the DROP event, but the
    prompt is ALL that happens: the suggested level is shown
    on the PlaybackText tag for the Roast page prompt strip
    and FanLevel / HeatLevel are never written from here.
    Sound: the PlaybackSound setting is stored and shown, but
    Perspective has no clean beep API reachable from the
    client scripting layer (no system.perspective audio call
    and no media component in this project), so the prompt
    itself is the signal; the flag changes nothing audible in
    this build, which the Settings section states plainly."""
    vals = read_members(['PlaybackEnabled', 'State',
                         '_PlaybackFiredJson', 'PlaybackActive'])
    if not vals['PlaybackEnabled'] or vals['State'] != 'Roasting':
        return
    if vals['PlaybackActive']:
        # A prompt is already showing: later events queue
        # behind it instead of overwriting it, so each prompt
        # stays readable until it is dismissed (the next one
        # fires on the first temp change after the dismiss).
        return
    events = background_events()
    if not events:
        return
    fired = []
    if vals['_PlaybackFiredJson']:
        try:
            fired = system.util.jsonDecode(vals['_PlaybackFiredJson'])
        except Exception:
            fired = []
    for i, e in enumerate(events):
        if i in fired or float(e.get('t') or 0) > elapsed:
            continue
        # Fire the earliest due event only; the next temp
        # change fires the next one, so prompts never stack.
        fired.append(i)
        if e.get('kind') == 'Drop':
            text = 'Background: Drop now'
        else:
            text = 'Background: %s %d' % (e.get('kind'),
                                          int(e.get('level')))
        write_members([('PlaybackText', text),
                       ('PlaybackActive', True),
                       ('_PlaybackFiredJson',
                        system.util.jsonEncode(fired))])
        return


def evaluate_suggestions(temp, elapsed):
    """Auto event suggestions (item 14). Artisan canvas.py
    checks on every sample: with autoDRYflag set, once CHARGE
    and the turning point exist and neither DRY nor FCs is
    stamped, BT at or above phases[1] marks DRY; with
    autoFCsFlag set, once FCs and FCe are unstamped, BT at or
    above phases[2] marks FCs (main.py findDryEnd locates the
    same crossing on a finished curve). Roastery's phase
    boundary temperatures are the Settings Targets temps
    (TargetDryEndTempF, TargetFCTempF). The Artisan build
    STAMPS the event; Roastery only suggests: the text lands
    on SuggestionText and Eric confirms with the normal event
    button, whose stamp path clears the suggestion. Each
    crossing suggests once per roast (the _DrySuggested /
    _FcSuggested latches, reset at charge)."""
    vals = read_members(['State', 'SuggestDryEndEnabled',
                         'SuggestFcEnabled', 'DryEndElapsedSec',
                         'FirstCrackStartElapsedSec',
                         'TargetDryEndTempF', 'TargetFCTempF',
                         '_DrySuggested', '_FcSuggested',
                         'SuggestionActive'])
    if vals['State'] != 'Roasting' or vals['SuggestionActive']:
        return
    if (vals['SuggestDryEndEnabled']
            and not vals['_DrySuggested']
            and (vals['DryEndElapsedSec'] or -1) < 0
            and (vals['FirstCrackStartElapsedSec'] or -1) < 0
            and temp >= float(vals['TargetDryEndTempF'] or 0)):
        write_members([
            ('SuggestionText',
             'BT crossed %g F, stamp Dry End?'
             % float(vals['TargetDryEndTempF'])),
            ('SuggestionActive', True),
            ('SuggestionKind', 'DryEnd'),
            ('_DrySuggested', True)])
        return
    if (vals['SuggestFcEnabled']
            and not vals['_FcSuggested']
            and (vals['FirstCrackStartElapsedSec'] or -1) < 0
            and temp >= float(vals['TargetFCTempF'] or 0)):
        write_members([
            ('SuggestionText',
             'BT crossed %g F, stamp FC Start?'
             % float(vals['TargetFCTempF'])),
            ('SuggestionActive', True),
            ('SuggestionKind', 'FCStart'),
            ('_FcSuggested', True)])


def dismiss_prompt():
    """Prompt strip Dismiss button (thin handler target):
    clear whichever prompt is showing. A dismissed playback
    event stays fired (it does not re-prompt) and a dismissed
    suggestion stays latched for this roast; stamping the
    event is the other way a suggestion clears."""
    write_members([('PlaybackText', ''), ('PlaybackActive', False),
                   ('SuggestionText', ''),
                   ('SuggestionActive', False),
                   ('SuggestionKind', '')])


def _clear_suggestion(kind):
    vals = read_members(['SuggestionActive', 'SuggestionKind'])
    if vals['SuggestionActive'] and vals['SuggestionKind'] == kind:
        write_members([('SuggestionText', ''),
                       ('SuggestionActive', False),
                       ('SuggestionKind', '')])


def display_smoothed(temps):
    """Display smoothing for the BT line (item 12). Artisan
    canvas.py smoothETBT smooths the DRAWN temperature curves
    with the curve filter, separate from the delta math.
    Roastery applies the same trailing decay filter family
    compute_ror_series uses (_decay_smooth_series) to the
    bean column of LiveCurveDS only, at the DisplaySmoothing
    level (0 is off, 1 to 5 map to internal windows 3 to 11).
    Stored CurveSamples stay raw and the RoR column is
    computed from the raw temps before this runs, so RoR and
    every saved value are untouched."""
    try:
        level = int(read_members(['DisplaySmoothing'])
                    ['DisplaySmoothing'] or 0)
    except Exception:
        level = 0
    level = max(0, min(5, level))
    if level <= 0 or len(temps) < 2:
        return list(temps)
    return _decay_smooth_series(
        [float(v) for v in temps],
        _decay_weights(2 * level + 1))


def _mmss(sec):
    sec = int(max(0, sec))
    return '%02d:%02d' % (sec // 60, sec % 60)


def analyzer_values(points, rors, t_sec):
    """Analyzer readout values at one elapsed time (item 13):
    BT and RoR interpolated over the curve's own samples and
    its one RoR implementation output, ghost BT interpolated
    over the staged background, and the deviation between
    them. points: [(t, bt)], rors: [(t, ror_or_None)] aligned
    with points. Returns a dict with None where a value does
    not exist at that time."""
    bt = interp_at([(float(t), float(v)) for t, v in points],
                   float(t_sec))
    ror_pairs = [(float(t), float(r)) for t, r in rors
                 if r is not None]
    ror = interp_at(ror_pairs, float(t_sec)) if ror_pairs else None
    bg = interp_at(background_points(), float(t_sec))
    return {'t': float(t_sec), 'bt': bt, 'ror': ror, 'bg': bg,
            'dev': (bt - bg) if (bt is not None and bg is not None)
            else None}


def _analyzer_write(prefix_paths, vals):
    """Publish one analyzer readout to a set of tags. Paths are
    full tag paths (the live readout lives on CurrentBatch
    members, the detail readout on the DetailAnalyzer folder),
    so this takes an explicit path map."""
    def fmt(v, suffix=''):
        return '--' if v is None else '%.1f%s' % (v, suffix)
    system.tag.writeBlocking(
        [prefix_paths['timeText'], prefix_paths['btText'],
         prefix_paths['rorText'], prefix_paths['bgText'],
         prefix_paths['devText'], prefix_paths['btF'],
         prefix_paths['rorF'], prefix_paths['bgF'],
         prefix_paths['devF'], prefix_paths['hasBg']],
        [_mmss(vals['t']), fmt(vals['bt']), fmt(vals['ror']),
         fmt(vals['bg']),
         '--' if vals['dev'] is None else '%+.1f' % vals['dev'],
         float(vals['bt'] or 0.0), float(vals['ror'] or 0.0),
         float(vals['bg'] or 0.0), float(vals['dev'] or 0.0),
         vals['bg'] is not None])


def _live_analyzer_paths():
    names = {'timeText': 'AnalyzerTimeText', 'btText': 'AnalyzerBtText',
             'rorText': 'AnalyzerRorText', 'bgText': 'AnalyzerBgText',
             'devText': 'AnalyzerDevText', 'btF': 'AnalyzerBtF',
             'rorF': 'AnalyzerRorF', 'bgF': 'AnalyzerBgF',
             'devF': 'AnalyzerDevF', 'hasBg': 'AnalyzerHasBg'}
    return dict((k, path(v)) for k, v in names.items())


def update_analyzer():
    """Recompute the live analyzer readout (item 13) from the
    recorded curve samples. AnalyzerSec -1 means Latest: the
    readout follows the newest sample. Called on every temp
    change through _live_analytics and by the strip steppers.
    The readout is a fixed strip under the chart (values on
    tags the strip labels bind), never floating chart text,
    so it cannot collide with axis labels or marker labels
    and it fits 360px as four short fields."""
    points = curve_points()
    if not points:
        return
    pts = [(float(p['t']), float(p['bt'])) for p in points]
    rors = compute_ror_series(pts, ror_params(), offline=False)
    sec = read_members(['AnalyzerSec'])['AnalyzerSec']
    t = pts[-1][0] if sec is None or int(sec) < 0 else float(sec)
    t = max(pts[0][0], min(pts[-1][0], t))
    _analyzer_write(_live_analyzer_paths(),
                    analyzer_values(pts, rors, t))


def analyzer_step(delta):
    """Analyzer strip stepper (thin handler target): move the
    selected time by delta seconds, clamped to the recorded
    curve, and republish the readout."""
    points = curve_points()
    if not points:
        return
    sec = read_members(['AnalyzerSec'])['AnalyzerSec']
    base = float(points[-1]['t']) if sec is None or int(sec) < 0 \
        else float(sec)
    new = max(float(points[0]['t']),
              min(float(points[-1]['t']), base + float(delta)))
    write_members([('AnalyzerSec', int(new))])
    update_analyzer()


def analyzer_latest():
    """Analyzer strip Latest button: back to following the
    newest sample."""
    write_members([('AnalyzerSec', -1)])
    update_analyzer()


# ------------------------------------------------------- Tier 3 items 15, 16
# Curve display options (item 15) and phases from background with
# phase band shading (item 16).
#
# Item 15 lives mostly in the chart prop bindings (the Settings
# Display tags bind straight onto the canvas series line width,
# line type, RoR area opacity and reference line endpoint size in
# the view), because series props are view data. The defaults on
# those tags (BT width 3 solid, RoR width 2 solid, ghost width 2
# solid, RoR fill off, marker size 4) reproduce the pre Tier 3
# look exactly. What the library owns for item 15 is the RoR fill
# and band AREA data below: the canvas line component honors a
# series area block (proven live in the 2026-11-17 probe round:
# a line series with an area block fills exactly like the area
# component), and the band series are dataset columns, composed
# here like every other overlay.
#
# Item 16 phase bands: the canvas line chart exposes no markArea
# config in this build (its series schema has visible, value,
# label, dataLabels, referenceLines, line, smooth, points and
# advanced only), so bands use the closest honest mechanism the
# app already uses for overlays: extra LiveCurveDS columns built
# here. Each band column holds the bean axis top (460 F) at every
# row inside its phase range and null outside it; the chart draws
# it as a width 0 series with a low opacity solid area fill, so
# the filled strip IS the band, behind the curves (the band
# series sit first in the series list). No text lives in the
# bands: the phase names are already in the PhasesBar, and band
# labels would collide at 360px.
#
# Band ranges follow the PhasesBar: stamped event times for the
# phases that have happened, and the effective targets for the
# phase still ahead. Effective targets are the saved Settings
# phase duration targets (PhaseDryTargetSec and friends), or,
# when PhaseFromBg is on and a ghost with ordered stamped events
# is staged, the ghost boundaries staged on the BgPhase tags by
# stage_bg_phases. The saved target tags are never written by
# the from background path: staging is session level only, and
# clearing the ghost clears the staged boundaries.

BAND_TOP_F = 460.0
BAND_COLS = ('bandDry', 'bandMai', 'bandDev', 'bandCool')


def stage_bg_phases(dry_sec, fc_sec, drop_sec):
    """Stage the loaded ghost phase boundaries (Tier 3 item 16)
    from its stamped event times, in elapsed seconds since its
    charge. Called by both ghost routes (roastery.batches
    set_background from the saved document events, and
    roastery.artisan stage_background_upload from the imported
    document events). -1 means the ghost has no such event.
    These are staged tags only: the saved SettingsTargets values
    are never touched here."""
    def _i(v):
        return int(float(v)) if v is not None and float(v) >= 0 else -1
    write_members([('BgPhaseDrySec', _i(dry_sec)),
                   ('BgPhaseFcSec', _i(fc_sec)),
                   ('BgPhaseDropSec', _i(drop_sec))])


def phase_band_ranges():
    """The phase band ranges for the live chart, as
    [(column, start_sec, end_sec)] with elapsed seconds since
    charge. Drying runs charge to dry end, Maillard dry end to
    FC start, Development FC start to drop, and Cooling drop to
    the latest sample. A phase that has been stamped ends at
    its stamp; a phase still ahead ends at its effective target
    boundary (the ghost boundaries when phases from background
    is on and staged, else the saved phase duration targets).
    Empty when idle or when no samples exist yet."""
    points = curve_points()
    if not points:
        return []
    vals = read_members([
        'State', 'DryEndElapsedSec', 'FirstCrackStartElapsedSec',
        'DropElapsedSec', 'PhaseDryTargetSec',
        'PhaseMaillardTargetSec', 'PhaseDevTargetSec',
        'PhaseFromBg', 'BgPhaseDrySec', 'BgPhaseFcSec',
        'BgPhaseDropSec'])
    if vals['State'] == 'Idle':
        return []
    last = float(points[-1]['t'])
    dry_s = vals['DryEndElapsedSec']
    dry_s = int(dry_s) if dry_s is not None else -1
    fc_s = vals['FirstCrackStartElapsedSec']
    fc_s = int(fc_s) if fc_s is not None else -1
    drop_s = vals['DropElapsedSec']
    drop_s = int(drop_s) if drop_s is not None else -1
    bg_dry = vals['BgPhaseDrySec'] or -1
    bg_fc = vals['BgPhaseFcSec'] or -1
    bg_drop = vals['BgPhaseDropSec'] or -1
    use_bg = (bool(vals['PhaseFromBg']) and bg_dry > 0
              and bg_fc > bg_dry and bg_drop > bg_fc)
    if use_bg:
        b_dry, b_fc, b_drop = bg_dry, bg_fc, bg_drop
    else:
        b_dry = int(vals['PhaseDryTargetSec'] or 0)
        b_fc = b_dry + int(vals['PhaseMaillardTargetSec'] or 0)
        b_drop = b_fc + int(vals['PhaseDevTargetSec'] or 0)
    dry_end = dry_s if dry_s >= 0 else b_dry
    fc_end = fc_s if fc_s >= 0 else b_fc
    if fc_end < dry_end:
        fc_end = dry_end
    drop_end = drop_s if drop_s >= 0 else b_drop
    if drop_end < fc_end:
        drop_end = fc_end
    out = []
    for col, s, e in (('bandDry', 0, dry_end),
                      ('bandMai', dry_end, fc_end),
                      ('bandDev', fc_end, drop_end)):
        if e > s:
            out.append((col, float(s), float(e)))
    if drop_s >= 0 and last > drop_s:
        out.append(('bandCool', float(drop_s), float(last)))
    return out


def build_live_curve():
    """Rebuild LiveCurveDS, the dataset the Roast page charts
    actually draw, from the recorded CurveSamples (v4.1, Eric's
    live feedback 2026-11-12).

    Why not tag history: the v4 chart bound its bean and RoR
    series to a tag history query with a mostRecent 30 MIN
    window. A roast that finished more than 30 minutes before
    the screenshot fell entirely outside the window, so both
    lines vanished while the tag dataset overlays (target,
    markers) still drew, and the wall clock date axis compressed
    the roast into a sliver labelled with the date. The samples
    are the stored truth instead: one row per temperature change
    with its elapsed seconds, kept for the whole roast however
    long the page stays open.

    X values are elapsed dates (epoch + elapsed seconds) and the
    axis formats them mm:ss. RoR is recomputed from the stored
    temps with compute_ror_series and the current parameters
    (live variant), the same math as RateOfRiseF and the saved
    batches, so the drawn curve can never disagree with them.
    Fan and heat ride along for the levels strip, same axis."""
    from java.util import Date
    points = curve_points()
    pts = [(float(p['t']), p['bt']) for p in points]
    rors = compute_ror_series(pts, ror_params(), offline=False)
    # The canvas line chart reads ONE wide dataset (v4.4
    # migration): the ghost and target overlays merge into the
    # same rows by timestamp union, each column null where its
    # source has no point. The chart series set connectNulls,
    # so the merge nulls never break a line; they are not data
    # gaps. Columns bg, bgRor and plan come from the overlay
    # datasets build_overlays maintains.
    merged = {}

    def put(ms, col, val):
        row = merged.get(ms)
        if row is None:
            row = {}
            merged[ms] = row
        row[col] = val

    # Display smoothing (item 12) shapes ONLY this bean column:
    # the samples and the RoR column above stay raw.
    display = display_smoothed([p['bt'] for p in points])
    for p, (_t, r), disp in zip(points, rors, display):
        ms = long(p['t'] * 1000)
        put(ms, 'bean', disp)
        put(ms, 'ror', r)
        put(ms, 'fan', float(p['fan']) if p['fan'] is not None
            else None)
        put(ms, 'heat', float(p['heat']) if p['heat'] is not None
            else None)
    for t, v in projection_points(pts, rors):
        put(long(t * 1000), 'proj', v)
    for path, col in ((BACKGROUND_DS, 'bg'), (BGROR_DS, 'bgRor'),
                      (TARGET_DS, 'plan')):
        ds = system.tag.readBlocking([path])[0].value
        if ds is None:
            continue
        for i in range(ds.rowCount):
            t = ds.getValueAt(i, 't_stamp')
            v = ds.getValueAt(i, col)
            if t is not None and v is not None:
                put(long(t.getTime()), col, float(v))
    # Phase bands (Tier 3 item 16): crisp boundary rows at each
    # band edge, then the band value at every row inside its
    # range. The chart fills under these width 0 series, which
    # shades the strip behind the curves.
    for col, s, e in phase_band_ranges():
        put(long(s * 1000), col, BAND_TOP_F)
        put(long(e * 1000), col, BAND_TOP_F)
        for ms in list(merged.keys()):
            if long(s * 1000) <= ms <= long(e * 1000):
                put(ms, col, BAND_TOP_F)
    rows = []
    for ms in sorted(merged):
        m = merged[ms]
        rows.append([Date(ms), m.get('bean'), m.get('ror'),
                     m.get('fan'), m.get('heat'), m.get('bg'),
                     m.get('bgRor'), m.get('plan'), m.get('proj'),
                     m.get('bandDry'), m.get('bandMai'),
                     m.get('bandDev'), m.get('bandCool')])
    system.tag.writeBlocking(
        [LIVE_DS], [system.dataset.toDataSet(LIVE_COLS, rows)])


def clear_curve_samples():
    system.tag.writeBlocking([CURVE_SAMPLES], [empty_curve_dataset()])
    system.tag.writeBlocking([LIVE_DS], [empty_live_dataset()])


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
    record_press(label)
    build_marks()
    # A stamp through the normal button is the confirmation an
    # auto suggestion (item 14) waits for: clear its prompt.
    if stem == 'DryEnd':
        _clear_suggestion('DryEnd')
    elif stem == 'FirstCrackStart':
        _clear_suggestion('FCStart')
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
    record_press(vals[name_member])
    build_marks()



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
    # Finalize any open between batch window FIRST (Tier 3
    # item 20): the metrics stage on the Bbp tags and ride into
    # this batch document at Save Batch. With no open window
    # this clears any stale staged metrics instead.
    _bbp_finalize_charge()
    vals = read_members(['BeanTempF', 'FanLevel', 'HeatLevel'])
    now = system.date.now()
    write_members([('State', 'Roasting'), ('StartTime', now),
                   ('ChargeTime', now), ('ChargeTempF', vals['BeanTempF']),
                   ('Mode', 'Roast'), ('WeightOutG', 0.0)])
    _clear_events()
    _reset_live_analytics()
    clear_curve_samples()
    _clear_log()
    append_log('event', 'Charge', vals['BeanTempF'], 0, now,
               float(vals['FanLevel']), float(vals['HeatLevel']))
    record_press('Charge')
    build_overlays()
    build_marks()




# ------------------------------------------------------- cooling seek
# Polish round 2: on DROP the stepped simulator program has
# no seek of its own (the Program Counter meta node is read
# only on this device build; writes are ignored, proven
# live), so drop() fast forwards the program through the
# Base Rate meta node to the cooling row aligned with the
# actual bean temp at drop, before the between batch window
# opens. The deployed library (roastery/core/code.py in the
# project) carries this inside its full simulator glue
# section with the SIM_* constants; this builder copy is
# self contained with literal tag paths because the builder
# core snapshot predates that section. Same rule: the
# declining cooling segment (program seconds 720 to 785)
# declines monotonically, the aligned row is the first row
# at or below the drop temp, clamped to the bottom row.

_SIM_COOL_POINTS = [(720, 417.3), (725, 411.1), (730, 402.8),
                    (735, 395.3), (740, 387.3), (745, 378.5),
                    (750, 370.0), (755, 363.1), (760, 358.3),
                    (765, 355.4), (770, 351.9), (775, 349.2),
                    (780, 344.8), (785, 342.9)]


def _sim_cool_target_sec(drop_temp):
    try:
        dt = float(drop_temp)
    except Exception:
        return 720
    pts = _SIM_COOL_POINTS
    if dt >= pts[0][1]:
        return pts[0][0]
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if v1 <= dt <= v0:
            for s in range(t0, t1 + 1):
                v = v0 + (v1 - v0) * float(s - t0) / float(t1 - t0)
                if v <= dt:
                    return s
            return t1
    return 785


def sim_seek_cooling(drop_temp):
    """Simulated source only, fully guarded; restores the
    Fan and Heat base rate and reseeds the live RoR buffer."""
    try:
        if read_members(['ActiveSource'])['ActiveSource'] \
                != 'Simulated':
            return
    except Exception:
        return
    try:
        counter = '[default]Roastery/SimProgramCounter'
        pause = '[default]Roastery/SimPause'
        rate = '[default]Roastery/SimBaseRate'
        target = _sim_cool_target_sec(drop_temp)
        cur = system.tag.readBlocking([counter])[0].value
        if cur is None or int(cur) >= target:
            return
        vals = read_members(['FanLevel', 'HeatLevel'])
        speed = 1.0 + 0.06 * (int(vals['HeatLevel'] or 5) - 5) \
            - 0.035 * (int(vals['FanLevel'] or 5) - 5)
        speed = max(0.6, min(1.45, speed))
        restore_ms = max(650, min(1700, int(round(
            1000.0 / speed / 10.0) * 10)))
        from java.lang import Thread
        # Two stages (bulk at 25 ms, approach at 150 ms for
        # the last 45 intervals): at the 5 ms device floor the
        # program runs about 150 intervals per second and a
        # polling loop overshoots by hundreds (proven live).
        # A counter wrap aborts the seek.
        system.tag.writeBlocking([pause, rate], [False, 25])
        try:
            waited = 0.0
            approach_at = target - 45
            in_approach = False
            last_pc = int(cur)
            while waited < 60:
                Thread.sleep(50)
                waited += 0.05
                pc = system.tag.readBlocking([counter])[0].value
                if pc is None:
                    continue
                pc = int(pc)
                if pc < last_pc:
                    break
                last_pc = pc
                if pc >= target:
                    break
                if not in_approach and pc >= approach_at:
                    in_approach = True
                    system.tag.writeBlocking([rate], [150])
        finally:
            system.tag.writeBlocking([rate], [restore_ms])
        write_members([('_RoRLiveJson', '')])
    except Exception:
        pass


def drop():
    _stamp('Drop', 'Drop')
    write_members([('State', 'Dropped'), ('Mode', 'Cool')])
    # Align the simulator cooling curve with this actual drop
    # (Simulated source only, no-op otherwise), BEFORE the
    # between batch window opens, so the window captures the
    # aligned cooling and never the seek fast forward.
    sim_seek_cooling(read_members(['BeanTempF'])['BeanTempF'])
    # The between batch window opens at DROP (Tier 3 item 20).
    _bbp_start_window()
    build_overlays()



def cool():
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Cooling')])
    append_log('state', 'Cooling', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())
    record_press('Cool')



def finish():
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Complete')])
    append_log('state', 'Finished', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())
    record_press('Finish')



def reset_batch():
    record_press('Reset')
    write_members([('State', 'Idle'), ('Mode', 'Off'), ('StartTime', None),
                   ('ChargeTime', None), ('ChargeTempF', 0.0),
                   ('WeightOutG', 0.0), ('RateOfRiseF', 0.0),
                   ('_RoRPrevTempF', 0.0), ('_RoRPrevMs', 0),
                   ('_RoRLiveJson', '')])
    _clear_events()
    _reset_live_analytics()
    clear_curve_samples()
    _clear_log()
    # Reset discards an open between batch window and any
    # staged BBP metrics (Tier 3 item 20, documented decision):
    # a reset workspace starts a fresh between batch story.
    _bbp_clear_all()
    write_members([('PlanDeviationText', '--')])
    build_marks()



def stepper(member, delta, label):
    """Fan and Heat steppers (SR800 levels 1 to 9), with trace log.
    A press that actually moves the level is a captured press."""
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
    record_press('%s %+d' % (label, int(delta)))



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
    vals = read_members(['StartTime'])
    start = vals['StartTime']
    if start is None:
        return
    # The plan is the variable length list from
    # target_plan_points (Tier 3 item 17): the JSON list when
    # one is stored, else the legacy four point tags.
    pts = target_plan_points()
    # X values are elapsed dates (epoch + offset seconds), the
    # v4.1 axis shared by every chart dataset; StartTime only
    # gates whether a roast timeline exists at all.
    rows = []
    s = 0.0
    while s < pts[-1][0]:
        rows.append([Date(long(s * 1000)), _plan_at(pts, s)])
        s += 15.0
    rows.append([Date(long(pts[-1][0] * 1000)), pts[-1][1]])
    bg_rows = []
    bg_json = system.tag.readBlocking([BACKGROUND_JSON])[0].value
    if bg_json:
        for pair in system.util.jsonDecode(bg_json):
            bg_rows.append([Date(long(float(pair[0]) * 1000)),
                            float(pair[1])])
    system.tag.writeBlocking(
        [TARGET_DS, BACKGROUND_DS],
        [system.dataset.toDataSet(['t_stamp', 'plan'], rows),
         system.dataset.toDataSet(['t_stamp', 'bg'], bg_rows)])
    bg_ror_rows = []
    if bg_rows:
        pairs = []
        bg_json2 = system.tag.readBlocking([BACKGROUND_JSON])[0].value
        if bg_json2:
            for pair in system.util.jsonDecode(bg_json2):
                pairs.append((float(pair[0]), float(pair[1])))
        for t, r in compute_ror_series(pairs, ror_params(),
                                       offline=True):
            if r is not None:
                bg_ror_rows.append([Date(long(t * 1000)), r])
    system.tag.writeBlocking(
        [BGROR_DS],
        [system.dataset.toDataSet(['t_stamp', 'bgRor'], bg_ror_rows)])
    # The live chart dataset merges the overlays in (v4.4);
    # refresh it so a ghost or target change lands at once.
    build_live_curve()



# ------------------------------------------------------- target plan
# Full profile designer for the target plan (Tier 3 item 17,
# Artisan designer.py point by point editing).
#
# Storage choice: the plan is a JSON list of [sec, tempF] pairs
# on the TargetPlanJson member of CurrentBatch. It survives
# restarts like every other standing tag, has no length limit
# the four fixed tags imposed, and both readers (the plan line
# in build_overlays and the deviation tile through
# update_plan_deviation) go through target_plan_points, so a
# longer list changes nothing else. When the JSON tag is empty
# or invalid, the plan falls back to the legacy four point tags
# (charge, dry end, FC, drop), which are also the migration
# source: the existing four points ARE the default list, with
# no separate migration step. Saving a plan through the
# designer writes the JSON list and syncs two legacy tags for
# the readers that still use them as scalars: the first point
# temp to TargetChargeTempF and the last point to TargetDropSec
# and TargetDropTempF (the drop target the alarms and metadata
# use). The dry end and FC legacy tags are NOT synced: they
# also carry the suggestion thresholds, which are their own
# settings.
#
# Validation (Artisan designer shape, and the BatchEdit ordered
# time pattern): at least 2 and at most 12 points, the first
# point anchored at 0 seconds (charge), times strictly
# increasing, temps between 50 and 500 F. A violation is
# REJECTED with a visible note and nothing is saved; the plan
# is never silently sorted.

TARGET_PLAN_MAX = 12
TARGET_PLAN_COLS = ['idx', 'timeSec', 'timeText', 'tempF']


def target_plan_points():
    """The current target plan as [(sec, tempF)] oldest first:
    the TargetPlanJson list when it parses and validates, else
    the legacy four point tags."""
    raw = read_members(['TargetPlanJson'])['TargetPlanJson']
    pts = []
    if raw:
        try:
            data = system.util.jsonDecode(raw)
        except Exception:
            data = None
        if isinstance(data, list):
            try:
                pts = [(float(p[0]), float(p[1])) for p in data]
            except Exception:
                pts = []
    if pts and validate_target_plan(pts) is None:
        return pts
    vals = read_members(['TargetChargeTempF', 'TargetDryEndSec',
                         'TargetDryEndTempF', 'TargetFCSec',
                         'TargetFCTempF', 'TargetDropSec',
                         'TargetDropTempF'])
    return [(0.0, float(vals['TargetChargeTempF'] or 0.0)),
            (float(vals['TargetDryEndSec'] or 0),
             float(vals['TargetDryEndTempF'] or 0.0)),
            (float(vals['TargetFCSec'] or 0),
             float(vals['TargetFCTempF'] or 0.0)),
            (float(vals['TargetDropSec'] or 0),
             float(vals['TargetDropTempF'] or 0.0))]


def validate_target_plan(points):
    """None when the plan is valid, else the rejection message
    (the caller shows it and saves nothing)."""
    if len(points) < 2:
        return ('The target plan needs at least 2 points. '
                'Nothing was saved.')
    if len(points) > TARGET_PLAN_MAX:
        return ('The target plan holds at most %d points. '
                'Nothing was saved.' % TARGET_PLAN_MAX)
    if float(points[0][0]) != 0.0:
        return ('The first target point must be at 0 seconds '
                '(charge). Nothing was saved.')
    for i in range(len(points)):
        t, v = float(points[i][0]), float(points[i][1])
        if v < 50.0 or v > 500.0:
            return ('Target temps must be between 50 and 500 F. '
                    'Nothing was saved.')
        if i > 0 and t <= float(points[i - 1][0]):
            return ('Target point times must be strictly '
                    'increasing. Nothing was saved.')
    return None


def set_target_plan(points):
    """Validate and store a plan; returns the rejection message
    or None. On success the JSON list is written, the charge
    and drop legacy tags are synced (see the section note), and
    the overlays rebuild so the plan line moves at once."""
    pts = [(float(t), float(v)) for t, v in points]
    err = validate_target_plan(pts)
    if err:
        return err
    write_members([
        ('TargetPlanJson',
         system.util.jsonEncode([[t, v] for t, v in pts])),
        ('TargetChargeTempF', pts[0][1]),
        ('TargetDropSec', int(pts[-1][0])),
        ('TargetDropTempF', pts[-1][1])])
    try:
        build_overlays()
    except Exception:
        pass
    return None


def target_plan_dataset():
    rows = []
    for i, (t, v) in enumerate(target_plan_points()):
        rows.append([i, int(t),
                     '%d:%02d' % (int(t) // 60, int(t) % 60), v])
    return system.dataset.toDataSet(TARGET_PLAN_COLS, rows)


def _target_editor_paths():
    return [TARGET_EDITOR + '/' + f
            for f in ('Idx', 'TimeSec', 'TempF')]


def target_editor_load(self, idx):
    pts = target_plan_points()
    idx = max(0, min(int(idx), len(pts) - 1))
    t, v = pts[idx]
    system.tag.writeBlocking(_target_editor_paths(),
                             [idx, int(t), float(v)])
    self.view.custom.targetPlanDs = target_plan_dataset()
    self.view.custom.targetPlanCount = len(pts)


def target_editor_load_idx(self):
    idx = system.tag.readBlocking(
        [TARGET_EDITOR + '/Idx'])[0].value
    target_editor_load(self, int(idx or 0))


def _target_editor_values():
    vals = system.tag.readBlocking(_target_editor_paths())
    return (int(vals[0].value or 0), int(vals[1].value or 0),
            float(vals[2].value or 0.0))


def _target_note(self, msg):
    self.view.custom.targetPlanNote = msg
    self.view.custom.targetPlanDs = target_plan_dataset()
    self.view.custom.targetPlanCount = len(target_plan_points())


def target_editor_save(self):
    """Save the editor values over the selected plan point."""
    idx, sec, temp = _target_editor_values()
    pts = target_plan_points()
    if idx < 0 or idx >= len(pts):
        _target_note(self, 'Pick a point to edit first.')
        return
    pts[idx] = (float(sec), float(temp))
    err = set_target_plan(pts)
    _target_note(self, err if err else
                 'Saved target point %d: %d sec, %.0f F.'
                 % (idx + 1, sec, temp))


def target_editor_add(self):
    """Append the editor values as a new last plan point. The
    time must be after the current last point (validation in
    set_target_plan rejects it otherwise, with the note)."""
    _idx, sec, temp = _target_editor_values()
    pts = target_plan_points()
    pts.append((float(sec), float(temp)))
    err = set_target_plan(pts)
    if err:
        _target_note(self, err)
    else:
        target_editor_load(self, len(pts) - 1)
        _target_note(self, 'Added target point %d: %d sec, '
                     '%.0f F.' % (len(pts), sec, temp))


def target_editor_delete(self):
    """Delete the selected plan point. The charge point (index
    0) anchors the plan and cannot be deleted."""
    idx, _sec, _temp = _target_editor_values()
    pts = target_plan_points()
    if idx <= 0:
        _target_note(self, 'The charge point (point 1) anchors '
                     'the plan and cannot be deleted.')
        return
    if idx >= len(pts):
        _target_note(self, 'Pick a point to delete first.')
        return
    gone = pts.pop(idx)
    err = set_target_plan(pts)
    if err:
        _target_note(self, err)
    else:
        target_editor_load(self, min(idx, len(pts) - 1))
        _target_note(self, 'Deleted target point %d (%d sec).'
                     % (idx + 1, int(gone[0])))


def target_plan_reset(self):
    """Reset the plan to the legacy four points: clearing the
    JSON tag makes target_plan_points fall back to them."""
    write_members([('TargetPlanJson', '')])
    try:
        build_overlays()
    except Exception:
        pass
    target_editor_load(self, 0)
    _target_note(self, 'Plan reset to the four points from the '
                 'fields above.')


def targets_startup(self):
    self.view.custom.targetPlanDs = target_plan_dataset()
    self.view.custom.targetPlanCount = len(target_plan_points())
    target_editor_load(self, 0)


def update_plan_deviation(temp):
    """Deviation tile text (Tier 3 item 17): live BT minus the
    target plan interpolated at the elapsed seconds, over the
    variable length plan. Published on PlanDeviationText; the
    tile binds that tag. Two dashes outside a roast, the same
    contract the old four point view expression had."""
    vals = read_members(['State', 'StartTime'])
    if vals['State'] != 'Roasting' or vals['StartTime'] is None:
        text = '--'
    else:
        elapsed = elapsed_sec(vals['StartTime'])
        dev = float(temp) - _plan_at(target_plan_points(),
                                     float(elapsed))
        text = '%+.1f F' % dev
    cur = read_members(['PlanDeviationText'])['PlanDeviationText']
    if cur != text:
        write_members([('PlanDeviationText', text)])


# ------------------------------------------------------- between batch
# Between batch protocol, BT only subset (Tier 3 item 20,
# Artisan main.py calcBBPMetrics). The ET half is skipped:
# the SR800 has one bean temp probe.
#
# Window: from the previous roast DROP to the next CHARGE.
# drop() opens the window (first sample is the drop temp at
# t = 0); every BeanTempF change while the state is Dropped,
# Cooling or Complete stages a sample into BbpSamplesDS
# (t_offset_sec is float seconds since DROP, so the window
# keeps sub second resolution). The staging tags live outside
# the batch workspace (the Bbp folder plus the dataset tag),
# so the window survives Save Batch for the roast that just
# dropped. charge() closes the window: it appends the final
# sample at the charge temp and moment, computes the metrics,
# and stages them on the Bbp tags; batches.build_document
# writes them into the next batch document as its bbp
# subdocument at Save Batch. Reset discards the window and
# any staged metrics (documented decision above, in
# reset_batch): a reset workspace starts fresh.
#
# Metrics, all from the staged samples S = [(t, BT)]:
# - time_sec: t of the last sample minus t of the first (the
#   DROP to CHARGE duration).
# - bottom_temp_f: the minimum BT in S; the bottom is the
#   FIRST sample holding that minimum, at time t_b.
# - RoR span: span = the library RoR delta span (the
#   RoRDeltaSpanSec tag through ror_params, default 20 s; a
#   span of 0 falls back to 20 for this math), the same span
#   convention core.compute_ror_series differentiates over.
# - ror_in_f_min: the slope approaching the bottom over the
#   span, (bottom - BT at max(t_first, t_b - span)) times 60
#   divided by (t_b - that start time), with BT interpolated
#   linearly between samples; 0.0 when the bottom is the
#   first sample (no approach exists).
# - ror_out_f_min: the slope leaving the bottom over the
#   span, (BT at min(t_last, t_b + span) - bottom) times 60
#   divided by (that end time - t_b), interpolated the same
#   way; 0.0 when the bottom is the last sample.


def _bbp_read(members):
    qvs = system.tag.readBlocking(
        [BBP_ROOT + '/' + m for m in members])
    return dict((m, qvs[i].value) for i, m in enumerate(members))


def _bbp_write(pairs):
    system.tag.writeBlocking(
        [BBP_ROOT + '/' + m for m, _v in pairs],
        [v for _m, v in pairs])


def empty_bbp_dataset():
    return typed_empty_dataset(BBP_COLS, BBP_SEED)


def bbp_samples():
    """Staged between batch samples as [(t_sec, tempF)] with
    float seconds since DROP, oldest first."""
    ds = system.tag.readBlocking([BBP_DS])[0].value
    out = []
    if ds is None:
        return out
    for r in range(ds.rowCount):
        t = ds.getValueAt(r, 't_offset_sec')
        v = ds.getValueAt(r, 'bean_temp_f')
        if t is not None and v is not None:
            out.append((float(t), float(v)))
    out.sort()
    return out


def _bbp_start_window():
    now = system.date.now()
    temp = read_members(['BeanTempF'])['BeanTempF']
    # Only the window state is (re)started here. The staged
    # metrics are NOT cleared: they belong to the batch that
    # is running now (finalized at its CHARGE) and must
    # survive until its Save Batch, which consumes them
    # (bbp_clear_staged). This window is for the NEXT batch.
    _bbp_write([('SampleCount', 1),
                ('DropMs', float(now.getTime())),
                ('WindowActive', True)])
    ds = empty_bbp_dataset()
    ds = system.dataset.addRow(ds, [0.0, now, float(temp or 0.0)])
    system.tag.writeBlocking([BBP_DS], [ds])


def _bbp_capture(temp, now, now_ms):
    vals = _bbp_read(['WindowActive', 'DropMs'])
    if not vals['WindowActive'] or not vals['DropMs']:
        return
    state = read_members(['State'])['State']
    if state not in ('Dropped', 'Cooling', 'Complete'):
        return
    t = (now_ms - float(vals['DropMs'])) / 1000.0
    if t < 0:
        return
    ds = system.tag.readBlocking([BBP_DS])[0].value
    if ds is None or ds.rowCount == 0:
        ds = empty_bbp_dataset()
    if ds.rowCount > 0:
        last_t = ds.getValueAt(ds.rowCount - 1, 't_offset_sec')
        last_bt = ds.getValueAt(ds.rowCount - 1, 'bean_temp_f')
        if (last_t is not None and int(float(last_t)) == int(t)
                and last_bt is not None
                and abs(float(last_bt) - float(temp)) < 0.05):
            return
    ds = system.dataset.addRow(ds, [float(t), now, float(temp)])
    system.tag.writeBlocking([BBP_DS], [ds])
    _bbp_write([('SampleCount', ds.rowCount)])


def _bbp_interp(points, t):
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t0 <= t <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return points[-1][1]


def bbp_compute(points):
    """The four BBP metrics from staged samples (definitions
    in the section note), or None when the window cannot
    support them (fewer than 2 samples or no duration)."""
    if len(points) < 2:
        return None
    t_first = points[0][0]
    t_last = points[-1][0]
    if t_last <= t_first:
        return None
    bottom = min(v for _t, v in points)
    t_b = [t for t, v in points if v == bottom][0]
    span = float(ror_params()['span'] or 20)
    if span <= 0:
        span = 20.0
    if t_b > t_first:
        ta = max(t_first, t_b - span)
        ror_in = ((bottom - _bbp_interp(points, ta)) * 60.0
                  / (t_b - ta))
    else:
        ror_in = 0.0
    if t_last > t_b:
        te = min(t_last, t_b + span)
        ror_out = ((_bbp_interp(points, te) - bottom) * 60.0
                   / (te - t_b))
    else:
        ror_out = 0.0
    return {'time_sec': t_last - t_first,
            'bottom_temp_f': bottom,
            'bottom_sec': t_b,
            'ror_in_f_min': ror_in,
            'ror_out_f_min': ror_out}


def _bbp_finalize_charge():
    """Close the window at CHARGE: append the final sample,
    compute the metrics and stage them for the batch document.
    With no open window, stale staged metrics are cleared so a
    later save can never inherit an old window."""
    vals = _bbp_read(['WindowActive'])
    if not vals['WindowActive']:
        _bbp_write([('HasMetrics', False), ('TimeSec', 0.0),
                    ('BottomTempF', 0.0), ('BottomSec', 0.0),
                    ('RorInFMin', 0.0), ('RorOutFMin', 0.0),
                    ('SampleCount', 0)])
        return None
    now = system.date.now()
    temp = read_members(['BeanTempF'])['BeanTempF']
    try:
        _bbp_capture(float(temp or 0.0), now, long(now.getTime()))
    except Exception:
        pass
    points = bbp_samples()
    metrics = bbp_compute(points)
    _bbp_write([('WindowActive', False),
                ('SampleCount', len(points))])
    system.tag.writeBlocking([BBP_DS], [empty_bbp_dataset()])
    if metrics is None:
        _bbp_write([('HasMetrics', False)])
        return None
    _bbp_write([('HasMetrics', True),
                ('TimeSec', float(metrics['time_sec'])),
                ('BottomTempF', float(metrics['bottom_temp_f'])),
                ('BottomSec', float(metrics['bottom_sec'])),
                ('RorInFMin', float(metrics['ror_in_f_min'])),
                ('RorOutFMin', float(metrics['ror_out_f_min']))])
    return metrics


def _bbp_clear_all():
    _bbp_write([('WindowActive', False), ('DropMs', 0.0),
                ('HasMetrics', False), ('TimeSec', 0.0),
                ('BottomTempF', 0.0), ('BottomSec', 0.0),
                ('RorInFMin', 0.0), ('RorOutFMin', 0.0),
                ('SampleCount', 0)])
    system.tag.writeBlocking([BBP_DS], [empty_bbp_dataset()])


def bbp_clear_staged():
    """Consume the staged metrics after a successful save:
    they have been written into that batch document, and a
    later save must never inherit them. The open window and
    its samples are untouched (they belong to the next
    batch). Called by roastery.batches.save_current_batch."""
    _bbp_write([('HasMetrics', False), ('TimeSec', 0.0),
                ('BottomTempF', 0.0), ('BottomSec', 0.0),
                ('RorInFMin', 0.0), ('RorOutFMin', 0.0)])


def bbp_staged_metrics():
    """The staged BBP metrics for the batch document, as the
    four value bbp subdocument, or None when no window was
    finalized at this batch charge."""
    vals = _bbp_read(['HasMetrics', 'TimeSec', 'BottomTempF',
                      'RorInFMin', 'RorOutFMin'])
    if not vals['HasMetrics']:
        return None
    return {'time_sec': float(vals['TimeSec'] or 0.0),
            'bottom_temp_f': float(vals['BottomTempF'] or 0.0),
            'ror_in_f_min': float(vals['RorInFMin'] or 0.0),
            'ror_out_f_min': float(vals['RorOutFMin'] or 0.0)}


# ---------------------------------------------------------------- forms

def coerce(member, value):
    """Form payloads carry numbers as strings; coerce per member."""
    if member in FORM_BOOLS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('true', '1', 'yes', 'on')
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
            v = (False if m in FORM_BOOLS else
                 0 if m in FORM_INTS else (0.0 if m in FORM_FLOATS else ''))
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
    self.view.custom.themeText = str(self.session.props.theme).capitalize()


def theme_toggle(self):
    cur = self.session.props.theme
    new = 'light' if cur == 'dark' else 'dark'
    self.session.props.theme = new
    self.view.custom.themeText = new.capitalize()


def toggle_all_cols(self):
    """Phone column sets (polish round 2, HUNT-13): flip the
    calling view's showAllCols custom prop. The wide tables
    (Log, Alarms, Phase Analysis) carry a reduced phone set
    and a full set in a phone only wrapper; its toggle button
    swaps which one shows. The advanced stylesheet never
    renders the wrapper at desktop widths, so this only ever
    fires from a phone width session."""
    try:
        cur = self.view.custom.showAllCols
    except Exception:
        cur = False
    self.view.custom.showAllCols = not bool(cur)
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

import math

import roastery.core as core

NQ_SELECT_ALL = 'Roastery/Batches/SelectAll'
NQ_SELECT_BY_ID = 'Roastery/Batches/SelectById'
NQ_INSERT = 'Roastery/Batches/Insert'
NQ_UPDATE = 'Roastery/Batches/Update'
NQ_DELETE = 'Roastery/Batches/Delete'
NQ_SERIES_INSERT = 'Roastery/Series/InsertBatch'
NQ_SERIES_SELECT = 'Roastery/Series/SelectByBatch'
NQ_EVENTS_SELECT = 'Roastery/Events/SelectByBatch'
NQ_MAX_NUMBER = 'Roastery/Batches/SelectMaxNumber'

SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
EDITOR_CREATE_TAG = '[default]Roastery/EditorCreateMode'
DETAIL_DS = '[default]Roastery/DetailDS'
DETAIL_MARKS = '[default]Roastery/DetailMarksDS'
DETAIL_JSON = '[default]Roastery/DetailDocJson'
DETAIL_REFRESH_MESSAGE = 'roastery-detail-refresh'
# Detail chart minimum x span in seconds (polish round 2
# item 6): the canvas time axis picks its tick label format
# from the axis span, and a very short batch (the seeded
# batch 1042 spans about 20 s) landed in the hour:minute:
# second regime while the live chart reads minute:second.
# detail_startup floors the chart max at this span so short
# batches render in the same regime as the live chart;
# longer batches keep their natural end. Sized empirically
# against the rendered ticks on batch 1042.
DETAIL_MIN_SPAN_SEC = 600

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
    members += ['TurningPointElapsedSec', 'TurningPointTempF',
                'AucLiveFMin', 'AucSinceFcFMin', 'AucBaseTempF',
                'AucBegin', 'AucTargetFMin']
    vals = core.read_members(members)
    total = vals['DropElapsedSec'] or 0
    dry = vals['DryEndElapsedSec']
    dry = dry if dry is not None and dry >= 0 else 0
    fc = vals['FirstCrackStartElapsedSec']
    fc = fc if fc is not None and fc >= 0 else total
    charge_w = vals['ChargeWeightG'] or 0.0
    out_w = vals['WeightOutG'] or 0.0
    lossd = loss_yield_density(vals)
    loss = lossd.get('weightLossPct')
    if loss is None:
        loss = ((charge_w - out_w) * 100.0 / charge_w) if out_w > 0 and charge_w > 0 else 0.0
    doc = {
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
        'aucDetail': {'valueFMin': vals['AucLiveFMin'],
                      'sinceFcFMin': vals['AucSinceFcFMin'],
                      'baseF': vals['AucBaseTempF'],
                      'begin': vals['AucBegin'],
                      'targetFMin': vals['AucTargetFMin']},
        'turningPoint': (
            {'t': vals['TurningPointElapsedSec'],
             'tempF': vals['TurningPointTempF']}
            if vals['TurningPointElapsedSec'] is not None
            and vals['TurningPointElapsedSec'] >= 0 else None),
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
    # Between batch protocol (Tier 3 item 20, BT only): the
    # metrics staged at this batch CHARGE from the previous
    # roast DROP window, when a window was finalized. Batches
    # with no preceding drop carry no bbp key at all.
    _bbp = core.bbp_staged_metrics()
    if _bbp is not None:
        doc['bbp'] = _bbp
    # The saved target document carries the full variable
    # length plan (Tier 3 item 17) beside the legacy fields.
    doc['target']['points'] = [
        [float(t), float(v)] for t, v in core.target_plan_points()]
    doc['loss'] = lossd
    pts = [(float(p['t']), float(p['bt'])) for p in core.curve_points()]
    doc['phaseAnalysis'] = phase_analysis(doc, pts)
    return doc


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
    """Write the curve points to batch_series. The stored
    rate_of_rise_f is DERIVED: recomputed here from the stored
    temps by roastery.core.compute_ror_series (offline path), so
    the saved RoR always matches the one implementation. In
    SeriesCaptureMode 'Group' the transaction group already wrote
    the rows live and this is skipped."""
    mode = core.read_members(['SeriesCaptureMode'])['SeriesCaptureMode']
    if mode == 'Group':
        ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
        return ds.rowCount
    if not points:
        return 0
    temps = [(p['t'], p['bt']) for p in points]
    rors = core.compute_ror_series(temps, core.ror_params(),
                                   offline=True)
    ror_by_t = dict((t, r) for t, r in rors)
    payload = []
    for p in points:
        r = ror_by_t.get(p['t'])
        item = {'t': p['t'], 'bt': p['bt'],
                'ror': r if r is not None else p['ror']}
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
    if get_batch(vals['BatchNumber']) is not None:
        self.view.custom.saveNote = (
            'Batch %d is already in the log. Start a New Roast for '
            'a fresh batch number, or edit the saved batch from '
            'the Log tab.' % vals['BatchNumber'])
        return vals['BatchNumber']
    doc = build_document()
    _run(NQ_INSERT, {
        'batch_number': vals['BatchNumber'],
        'roast_start': vals['ChargeTime'],
        'roast_end': vals['DropTime'],
        'bean_name': vals['BeanName'],
        'drop_temp_f': vals['DropTempF'],
        'data': system.util.jsonEncode(doc)})
    _insert_series(vals['BatchNumber'], core.curve_points())
    # The staged BBP metrics were written into this batch
    # document by build_document; consume them so a later
    # save cannot inherit them (Tier 3 item 20).
    core.bbp_clear_staged()
    core.record_press('Save Batch')
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


EVENT_FORM_KEYS = ('charge', 'dryEnd', 'fcStart', 'fcEnd',
                   'scStart', 'scEnd', 'drop')


def _mmss(t):
    if t is None:
        return ''
    t = int(t)
    return '%02d:%02d' % (t // 60, t % 60)


def edit_form_data_for(self):
    """Slide over editor prefill (called from the editor view
    onStartup). Mode and target come from the EditorCreateMode and
    SelectedBatchNumber tags. In create mode the form starts blank
    except the bean defaults; in edit mode it comes from the stored
    batch document (SelectById), metadata plus event times (mm:ss
    from charge) and event temps."""
    create = system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value
    if create:
        data = {}
        for m in core.FORM_MEMBERS:
            if m in core.FORM_BOOLS:
                data[m] = False
            elif m in core.FORM_INTS:
                data[m] = 0
            elif m in core.FORM_FLOATS:
                data[m] = 0.0
            else:
                data[m] = ''
        data.update({'HarvestYear': 2025, 'ChargeWeightG': 200.0,
                     'TargetDropTempF': 415.0,
                     'RoasterType': 'FreshRoast SR800',
                     'RoasterSizeKg': 0.25, 'BatchNumber': 0})
        return data
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    batch = get_batch(number)
    if batch is None:
        return {}
    doc = batch['document']
    meta = dict(doc.get('metadata') or {})
    data = {}
    for m in core.FORM_MEMBERS:
        v = meta.get(m)
        if v is None:
            v = (False if m in core.FORM_BOOLS else
                 0 if m in core.FORM_INTS else
                 (0.0 if m in core.FORM_FLOATS else ''))
        data[m] = v
    data['BatchNumber'] = batch['batchNumber']
    events = doc.get('events') or {}
    for key in EVENT_FORM_KEYS:
        e = events.get(key)
        data['Ev_%s_t' % key] = _mmss(e.get('t')) if e else ''
        tv = e.get('tempF') if e else None
        data['Ev_%s_tempF' % key] = tv if tv is not None else ''
    return data



def batch_edit_submit(self, event):
    """Slide over editor form submit for both modes."""
    create = system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value
    if create:
        _create_submit(self, event)
    else:
        _update_submit(self, event)



def _update_submit(self, event):
    batch_number = int(system.tag.readBlocking(
        [SELECTED_TAG])[0].value or 0)
    batch = get_batch(batch_number)
    if batch is None:
        self.view.custom.editNote = 'Batch %d no longer exists.' % batch_number
        return
    doc = _apply_form(batch['document'], event)
    err = _apply_events(doc, event)
    if err:
        # Reject nonsense with a visible message; nothing is saved.
        self.view.custom.editNote = err
        return
    _run(NQ_UPDATE, {
        'batch_number': batch_number,
        'bean_name': doc.get('beanName'),
        'drop_temp_f': doc.get('dropTempF'),
        'data': system.util.jsonEncode(doc)})
    self.view.custom.editNote = 'Saved batch %d.' % batch_number
    stage_detail(batch_number)
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')
    system.perspective.sendMessage(DETAIL_REFRESH_MESSAGE, {},
                                   scope='session')



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
    custom props (the action buttons act on it) and in the
    SelectedBatchNumber tag (detail view, slide over editor and
    ghost actions read it from any page)."""
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
    if number is not None:
        system.tag.writeBlocking([SELECTED_TAG], [int(number)])



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
        table = self.view.getChild('BatchesPanelRoot').getChild('BatchTable')
    table.refreshBinding('props.data')


def open_editor(self, create=False):
    """Open the slide over batch editor (right dock 'batchEditor',
    configured on the Log pages). The editor view reads its target
    from the SelectedBatchNumber and EditorCreateMode tags, so any
    page can open it for the staged batch."""
    if create:
        system.tag.writeBlocking([EDITOR_CREATE_TAG], [True])
    else:
        number = int(system.tag.readBlocking(
            [SELECTED_TAG])[0].value or 0)
        if number <= 0:
            return
        system.tag.writeBlocking([EDITOR_CREATE_TAG], [False])
    system.perspective.openDock('batchEditor')
    system.perspective.sendMessage('roastery-editor-open', {},
                                   scope='session')


def editor_refresh(self):
    """Refill the slide over editor for the staged batch. Runs
    from the editor view onStartup and from its
    'roastery-editor-open' message handler: a docked view loads
    once per page, so onStartup alone goes stale after the first
    open. The title is set here in the library because an
    expression binding cannot concatenate the batch number onto
    text in this build (it evaluated to null with bad quality)."""
    create = bool(system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value)
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    self.view.custom.editorTitle = ('New Batch' if create else
                                    'Edit Batch %d' % number)
    self.view.custom.editNote = ''
    root = self.getChild('BatchEditRoot')
    if root is None:
        root = self.view.getChild('BatchEditRoot')
    root.getChild('BatchForm').props.data = edit_form_data_for(self)



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
    """Use as Ghost: read the selected batch's curve from the
    batch_series table (Series/SelectByBatch) and stage it as the
    Roast page background overlay, then navigate to the console.
    roastery.core.build_overlays recomputes the ghost RoR from the
    staged temps with the current RoR parameters."""
    batch_number = int(self.view.custom.selBatchNumber or 0)         if hasattr(self.view.custom, 'selBatchNumber') else 0
    if batch_number <= 0:
        batch_number = int(system.tag.readBlocking(
            [SELECTED_TAG])[0].value or 0)
    if batch_number <= 0:
        return
    ds = _run(NQ_SERIES_SELECT, {'batch_number': batch_number})
    pairs = []
    levels = []
    for r in range(ds.rowCount):
        pairs.append([ds.getValueAt(r, 't_offset_sec'),
                      ds.getValueAt(r, 'bean_temp_f')])
        levels.append((ds.getValueAt(r, 't_offset_sec'),
                       ds.getValueAt(r, 'fan_level'),
                       ds.getValueAt(r, 'heat_level')))
    batch = get_batch(batch_number)
    label = 'Batch %d' % batch_number
    if batch is not None and batch['beanName']:
        label += ' - ' + batch['beanName']
    drop_sec = -1.0
    if batch is not None:
        ev = (batch['document'].get('events') or {}).get('drop')
        if ev and ev.get('t') is not None:
            drop_sec = float(ev['t'])
        elif batch['document'].get('totalSec'):
            drop_sec = float(batch['document']['totalSec'])
    # Playback events for Tier 2 item 11 ride along with the
    # ghost: the Fan and Heat changes in its own series plus
    # its drop time, derived by roastery.core.
    events = core.build_background_events(levels, drop_sec)
    # Phase boundaries for Tier 3 item 16 stage with the ghost
    # too, from its stamped document events (session level
    # staging tags; the saved Settings targets stay untouched).
    if batch is not None:
        _ev = batch['document'].get('events') or {}
        core.stage_bg_phases(
            (_ev.get('dryEnd') or {}).get('t'),
            (_ev.get('fcStart') or {}).get('t'),
            (_ev.get('drop') or {}).get('t'))
    system.tag.writeBlocking(
        [core.BACKGROUND_JSON, BACKGROUND_LABEL,
         core.BACKGROUND_DROP_TAG, core.BACKGROUND_EVENTS_TAG],
        [system.util.jsonEncode(pairs), label, drop_sec,
         system.util.jsonEncode(events)])
    core.build_overlays()
    system.perspective.navigate(page='/')



# ---------------------------------------------------------------- compare
# Multi curve comparison on the Log page (Tier 1 item 2): up to
# three saved batches overlaid on one canvas chart, BT solid and
# RoR dashed per batch. RoR is recomputed from each batch's
# stored temps with the current parameters, the same offline
# path stage_detail uses, so compared curves can never disagree
# with the detail view.

COMPARE_COLS = ['t_stamp', 'btA', 'rorA', 'btB', 'rorB',
                'btC', 'rorC']
COMPARE_SLOTS = ('A', 'B', 'C')


def compare_options():
    """Dropdown options for the compare pickers, from the
    SelectAll named query (the table's own source)."""
    ds = _run(NQ_SELECT_ALL)
    out = [{'value': 0, 'label': 'None'}]
    for r in range(ds.rowCount):
        n = ds.getValueAt(r, 'batch_number')
        bean = ds.getValueAt(r, 'bean_name') or ''
        out.append({'value': int(n),
                    'label': 'Batch %s - %s' % (n, bean)})
    return out


def compare_startup(self):
    """BatchesPanel onStartup: fill the three compare pickers
    and default A and B to the two newest batches."""
    opts = compare_options()
    root = self.getChild('BatchesPanelRoot')
    if root is None:
        root = self.view.getChild('BatchesPanelRoot')
    for slot in COMPARE_SLOTS:
        root.getChild('CompareRow').getChild(
            'Cmp' + slot).props.options = opts
    nums = [o['value'] for o in opts if o['value']]
    c = self.view.custom
    if len(nums) >= 2:
        c.cmpA, c.cmpB = nums[0], nums[1]
    elif nums:
        c.cmpA = nums[0]


def _compare_points(batch_number):
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    points = []
    for r in range(ds.rowCount):
        bt = ds.getValueAt(r, 'bean_temp_f')
        if bt is not None:
            points.append((float(ds.getValueAt(r, 't_offset_sec')),
                           float(bt)))
    points.sort()
    return points


def build_compare(self):
    """Compare button: build the wide compare dataset on the
    elapsed axis (timestamp union, nulls elsewhere, the live
    chart's merge shape) and the caption naming each slot."""
    from java.util import Date
    c = self.view.custom
    chosen = [('A', int(c.cmpA or 0)), ('B', int(c.cmpB or 0)),
              ('C', int(c.cmpC or 0))]
    merged = {}
    captions = []
    for slot, number in chosen:
        if number <= 0:
            continue
        points = _compare_points(number)
        if not points:
            continue
        rors = core.compute_ror_series(points, core.ror_params(),
                                       offline=True)
        ror_by_t = dict((t, r) for t, r in rors)
        for t, bt in points:
            ms = long(t * 1000)
            row = merged.get(ms)
            if row is None:
                row = {}
                merged[ms] = row
            row['bt' + slot] = bt
            row['ror' + slot] = ror_by_t.get(t)
        batch = get_batch(number)
        bean = (batch['beanName'] if batch else '') or ''
        captions.append('%s = Batch %d %s' % (slot, number, bean))
    rows = []
    for ms in sorted(merged):
        m = merged[ms]
        rows.append([Date(ms), m.get('btA'), m.get('rorA'),
                     m.get('btB'), m.get('rorB'),
                     m.get('btC'), m.get('rorC')])
    c.compareDs = system.dataset.toDataSet(COMPARE_COLS, rows)
    c.compareCaption = (' - '.join(captions) if captions
                        else 'Pick at least one batch to compare.')


# ---------------------------------------------------------------- event editing

def parse_mmss(text):
    """'mm:ss' (or plain seconds) -> int seconds; None when blank.
    Raises ValueError on garbage."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if ':' in s:
        parts = s.split(':')
        if len(parts) != 2:
            raise ValueError('bad time')
        return int(parts[0]) * 60 + int(float(parts[1]))
    return int(float(s))


def _apply_events(doc, payload):
    """Apply the slide over event edits to the document and
    RECOMPUTE the derived data so the document stays self
    consistent: phase durations and DTR from the event times,
    total time from drop, roast degree from the (possibly edited)
    drop temp, event timestamps from roast start + offset.
    Returns an error string, or None on success. On error the
    caller saves nothing."""
    events = dict(doc.get('events') or {})
    order = ['charge', 'dryEnd', 'fcStart', 'fcEnd', 'scStart',
             'scEnd', 'drop']
    labels = {'charge': 'Charge', 'dryEnd': 'Dry End',
              'fcStart': 'FC Start', 'fcEnd': 'FC End',
              'scStart': 'SC Start', 'scEnd': 'SC End', 'drop': 'Drop'}
    new_events = {}
    for key in order:
        tkey = 'Ev_%s_t' % key
        fkey = 'Ev_%s_tempF' % key
        if tkey not in payload and fkey not in payload:
            new_events[key] = events.get(key)
            continue
        old = events.get(key) or {}
        try:
            t = parse_mmss(payload.get(tkey)) if tkey in payload                 else old.get('t')
        except Exception:
            return ('Event times must be mm:ss (for example 04:30). '
                    'Nothing was saved.')
        temp = old.get('tempF')
        if fkey in payload and payload.get(fkey) not in (None, ''):
            try:
                temp = float(payload[fkey])
            except Exception:
                return ('Event temps must be numbers. '
                        'Nothing was saved.')
        if key == 'charge':
            t = 0
        if t is None:
            new_events[key] = None
        else:
            new_events[key] = {'t': int(t), 'ts': old.get('ts'),
                               'tempF': temp}
    new_events['custom'] = events.get('custom') or []
    seq = [(k, new_events[k]['t']) for k in order if new_events.get(k)]
    for i in range(len(seq) - 1):
        if seq[i][1] >= seq[i + 1][1]:
            return ('%s must come before %s. Nothing was saved.'
                    % (labels[seq[i][0]], labels[seq[i + 1][0]]))
    doc['events'] = new_events

    def _t(key):
        e = new_events.get(key)
        return e['t'] if e else None

    dry = _t('dryEnd')
    fc = _t('fcStart')
    drop_t = _t('drop')
    if drop_t is not None:
        doc['totalSec'] = drop_t
        dev = (drop_t - fc) if fc is not None else 0
        doc['phases'] = {
            'dryingSec': dry if dry is not None else 0,
            'maillardSec': (fc - dry) if (fc is not None
                                          and dry is not None) else 0,
            'developmentSec': dev,
            'dtrPct': (dev * 100.0 / drop_t) if drop_t > 0 else 0.0}
        drop_ev = new_events.get('drop') or {}
        if drop_ev.get('tempF') is not None:
            doc['dropTempF'] = drop_ev['tempF']
            doc['roastDegree'] = roast_degree(drop_ev['tempF'])
    start_iso = doc.get('roastStart')
    if start_iso:
        try:
            start_dt = system.date.parse(
                start_iso, "yyyy-MM-dd'T'HH:mm:ss")
            for key in order:
                e = new_events.get(key)
                if e:
                    e['ts'] = _iso(system.date.addSeconds(
                        start_dt, int(e['t'])))
            if drop_t is not None:
                doc['roastEnd'] = _iso(system.date.addSeconds(
                    start_dt, int(drop_t)))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- detail + new roast

def stage_detail(batch_number):
    """Stage everything the Log detail view binds for one batch:
    DetailDS (bean temp + RoR recomputed from the stored temps
    with the CURRENT RoR parameters, the way Artisan recalculates
    a loaded profile), DetailMarksDS (event marker lines) and
    DetailDocJson. Returns True when the batch exists."""
    from java.util import Date
    batch = get_batch(int(batch_number))
    if batch is None:
        return False
    doc = batch['document']
    system.tag.writeBlocking(
        [SELECTED_TAG, DETAIL_JSON],
        [int(batch_number), system.util.jsonEncode(doc)])
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    points = []
    for r in range(ds.rowCount):
        bt = ds.getValueAt(r, 'bean_temp_f')
        if bt is not None:
            points.append((float(ds.getValueAt(r, 't_offset_sec')),
                           float(bt)))
    rors = core.compute_ror_series(points, core.ror_params(),
                                   offline=True)
    # X values are elapsed dates (epoch + t_offset seconds), the
    # v4.1 axis: the detail chart reads exactly like the live
    # chart, and no longer depends on the batch having a stored
    # roast_start wall clock (the generated fixture batches have
    # none, and their detail curves used to stage empty).
    rows = []
    for (t, bt), (_t2, ror) in zip(points, rors):
        rows.append([Date(long(t * 1000)), bt, ror])
    evs = []
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'CHARGE'), ('dryEnd', 'DRY END'),
                     ('fcStart', 'FC START'), ('fcEnd', 'FC END'),
                     ('scStart', 'SC START'), ('scEnd', 'SC END'),
                     ('drop', 'DROP')):
        e = events.get(key)
        if e and e.get('t') is not None:
            evs.append((float(e['t']), lbl))
    for c in events.get('custom') or []:
        if c.get('t') is not None:
            evs.append((float(c['t']),
                        (c.get('name') or 'CUSTOM').upper()))
    system.tag.writeBlocking(
        [DETAIL_DS, DETAIL_MARKS],
        [system.dataset.toDataSet(['t_stamp', 'bt', 'ror'], rows),
         core.marks_dataset(evs)])
    # The detail analyzer (Tier 2 item 13) restages with the
    # batch: selection back to Latest, readout recomputed.
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [-1])
    detail_analyzer_refresh()
    return True


# ------------------------------------------------------- detail analyzer
# Tier 2 item 13 on BatchDetail: the same crosshair readout as
# the live chart, computed over the staged DetailDS (stored
# temps with RoR recomputed on read by stage_detail, the one
# implementation) plus the staged ghost for the ghost BT and
# deviation columns. Values publish to the DetailAnalyzer
# tags the detail strip binds; selection moves through the
# strip steppers, never through floating chart text.

def _detail_analyzer_paths():
    names = {'timeText': 'TimeText', 'btText': 'BtText',
             'rorText': 'RorText', 'bgText': 'BgText',
             'devText': 'DevText', 'btF': 'BtF', 'rorF': 'RorF',
             'bgF': 'BgF', 'devF': 'DevF', 'hasBg': 'HasBg'}
    return dict((k, core.DETAIL_ANALYZER + '/' + v)
                for k, v in names.items())


def _detail_points():
    ds = system.tag.readBlocking([DETAIL_DS])[0].value
    points = []
    rors = []
    if ds is None:
        return points, rors
    for r in range(ds.rowCount):
        ts = ds.getValueAt(r, 't_stamp')
        bt = ds.getValueAt(r, 'bt')
        if ts is None or bt is None:
            continue
        t = ts.getTime() / 1000.0
        points.append((t, float(bt)))
        rors.append((t, ds.getValueAt(r, 'ror')))
    return points, rors


def detail_analyzer_refresh():
    """Recompute the BatchDetail analyzer readout at the
    selected time (DetailAnalyzer/Sec, -1 is Latest)."""
    points, rors = _detail_points()
    if not points:
        return
    sec = system.tag.readBlocking(
        [core.DETAIL_ANALYZER + '/Sec'])[0].value
    t = points[-1][0] if sec is None or int(sec) < 0 else float(sec)
    t = max(points[0][0], min(points[-1][0], t))
    core._analyzer_write(
        _detail_analyzer_paths(),
        core.analyzer_values(points, rors, t))


def detail_analyzer_step(delta):
    """Detail analyzer stepper (thin handler target)."""
    points, _rors = _detail_points()
    if not points:
        return
    sec = system.tag.readBlocking(
        [core.DETAIL_ANALYZER + '/Sec'])[0].value
    base = points[-1][0] if sec is None or int(sec) < 0 \
        else float(sec)
    new = max(points[0][0], min(points[-1][0],
                                base + float(delta)))
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [int(new)])
    detail_analyzer_refresh()


def detail_analyzer_latest():
    """Detail analyzer Latest button."""
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [-1])
    detail_analyzer_refresh()


def detail_reference_lines():
    """Reference line items for the staged batch's events, from
    the DetailDocJson document stage_detail wrote (custom event
    names intact). Bound on the detail chart's bean series
    through a script transform triggered by DetailMarksDS."""
    raw = system.tag.readBlocking([DETAIL_JSON])[0].value
    if not raw:
        return []
    doc = system.util.jsonDecode(raw)
    events = doc.get('events') or {}
    evs = []
    for key, lbl in (('charge', 'CHARGE'), ('dryEnd', 'DRY END'),
                     ('fcStart', 'FC START'), ('fcEnd', 'FC END'),
                     ('scStart', 'SC START'), ('scEnd', 'SC END'),
                     ('drop', 'DROP')):
        e = events.get(key)
        if e and e.get('t') is not None:
            evs.append((float(e['t']), lbl))
    for c in events.get('custom') or []:
        if c.get('t') is not None:
            evs.append((float(c['t']),
                        (c.get('name') or 'CUSTOM').upper()))
    return core._ref_items(evs, top_gap=150.0, mid_gap=60.0,
                           mid_top_gap=60.0)


def open_detail(self):
    """Batches panel Details button: stage the selected batch and
    navigate to the detail page."""
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    if stage_detail(number):
        system.perspective.navigate(page='/log/detail')
        # The detail view re-runs detail_startup on this message,
        # which also gives the presses query a second, warm chance
        # on a cold connection.
        system.perspective.sendMessage(DETAIL_REFRESH_MESSAGE, {},
                                       scope='session')


# Tier 2 items 7, 8 and 10b: phase analytics completion, loss /
# yield / density, and the BT similarity score. Definitions are
# Artisan 5.0.0 main.py: RoR(TP_index, dryEndIndex),
# computedProfileInformation() (phase RoRs, delta temps, total
# RoR, fcs_ror, per phase AUC through ts(), cool phase time from
# calcStatistics), weight_loss(), volume_increase(), and
# curveSimilarity() (BT half).


def _weight_loss(green, roasted):
    """Artisan weight_loss: percent, 0 when green is 0 or the
    roasted weight exceeds the green weight."""
    green = float(green or 0.0)
    roasted = float(roasted or 0.0)
    if green == 0.0 or green < roasted:
        return 0.0
    return 100.0 * ((green - roasted) / green)


def _volume_increase(green, roasted):
    """Artisan volume_increase: percent, 0 when green is 0 or
    the roasted volume is smaller than the green volume."""
    green = float(green or 0.0)
    roasted = float(roasted or 0.0)
    if green == 0.0 or green > roasted:
        return 0.0
    return 100.0 * ((roasted - green) / green)


def loss_yield_density(meta):
    """The full Artisan loss, yield and density set from the
    batch metadata (Tier 1 item 3 fields). Every value is
    guarded: when an input is absent or the Artisan formula
    would divide by zero or read a negative yield, the key is
    simply not stored, never a fabricated number. Keys:
    weightLossPct, defectsLossPct, totalLossPct, totalYieldG,
    totalYieldPct, volumeGainPct, moistureLossPct,
    organicLossPct, greenDensityGL, roastedDensityGL.
    Densities are weight over volume in g per L (Artisan
    converts weight to g and volume to L; Roastery stores g
    and ml, so density is weight * 1000 / volume_ml).
    totalYieldG is Artisan's computed total_yield (the yield
    weight in grams, weight out minus defects); totalYieldPct
    is the same yield as a percent of the green weight."""
    meta = meta or {}
    out = {}

    def _f(key):
        v = meta.get(key)
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    win = _f('ChargeWeightG')
    wout = _f('WeightOutG')
    defects = _f('DefectsWeightG')
    vin = _f('VolumeInMl')
    vout = _f('VolumeOutMl')
    gmoist = _f('MoisturePct')
    rmoist = _f('RoastedMoisturePct')
    wl = _weight_loss(win, wout) if win > 0 and wout > 0 else 0.0
    if wl > 0:
        out['weightLossPct'] = wl
    if wout > 0 and defects > 0 and defects < wout:
        dl = _weight_loss(wout, wout - defects)
        if dl > 0:
            out['defectsLossPct'] = dl
    if vin > 0 and vout > 0:
        vg = _volume_increase(vin, vout)
        if vg > 0:
            out['volumeGainPct'] = vg
    if gmoist > 0 and rmoist > 0:
        ml = gmoist - rmoist
        out['moistureLossPct'] = ml
        if wl > 0:
            out['organicLossPct'] = wl - ml
    if win > 0 and (wout > 0 or defects > 0):
        res = (wout - defects) if wout > 0 else (win - defects)
        if res > 0:
            out['totalYieldG'] = res
            out['totalYieldPct'] = res * 100.0 / win
            tl = _weight_loss(win, res)
            if tl > 0:
                out['totalLossPct'] = tl
    if win > 0 and vin > 0:
        out['greenDensityGL'] = win * 1000.0 / vin
    if wout > 0 and vout > 0:
        out['roastedDensityGL'] = wout * 1000.0 / vout
    return out


def _auc_range(points, start, end, base):
    """Trapezoid area between the bean curve and the base temp
    over [start, end] only, in degree F minutes (Artisan ts()
    per phase shape, calcAUC trapezoids). Segments are clipped
    to the range with interpolated endpoint temps."""
    if end is None or start is None or end <= start or not points:
        return None
    auc = 0.0
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t1 <= start or t0 >= end or t1 <= t0:
            continue
        a = max(t0, start)
        b = min(t1, end)
        va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
        vb = v0 + (v1 - v0) * (b - t0) / (t1 - t0)
        avg = (va + vb) / 2.0
        if avg > base:
            auc += (avg - base) * (b - a) / 60.0
    return auc


def _interp_pairs(pairs, t):
    if not pairs or t < pairs[0][0] or t > pairs[-1][0]:
        return None
    for i in range(len(pairs) - 1):
        t0, v0 = pairs[i]
        t1, v1 = pairs[i + 1]
        if t0 <= t <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pairs[-1][1]


def bt_similarity(fg_points, fg_drop_t, bg_points, bg_drop_t,
                  fg_dry_t=None):
    """BT similarity against the background, Artisan main.py
    curveSimilarity() BT half only (the dbt value): the RMSE
    in F between the foreground BT and the background BT
    interpolated at the same times, over the stretch from
    DRY to DROP, with the background time axis shifted so the
    two DROP times align (dropTimeDelta). The ET half is
    skipped (single sensor). Roastery adaptation: Artisan
    locates its dry index by scanning back from DROP for the
    phases dry boundary temperature; Roastery uses its
    recorded Dry End event as the same phase boundary.
    Returns None when either curve lacks a DROP or there is
    no overlap to compare."""
    if (not fg_points or not bg_points or fg_drop_t is None
            or bg_drop_t is None):
        return None
    start = float(fg_dry_t) if fg_dry_t is not None else 0.0
    shift = float(fg_drop_t) - float(bg_drop_t)
    sq = []
    for t, bt in fg_points:
        if t < start or t > float(fg_drop_t):
            continue
        b = _interp_pairs(bg_points, t - shift)
        if b is None:
            continue
        sq.append((float(bt) - b) ** 2)
    if not sq:
        return None
    return math.sqrt(sum(sq) / len(sq))


def phase_analysis(doc, points):
    """Structured phase analytics for the saved document
    (Tier 2 item 7): per phase duration, share, delta temp,
    average RoR and AUC, plus fcsRorFMin, totalRorFMin and
    coolSec. Only values the data actually supports are
    stored. See _phase_analysis for the definitions."""
    rows, _tp_text, extra = _phase_analysis(doc, points)
    out = {'phases': {}}
    for name, vals in extra['phases'].items():
        out['phases'][name] = vals
    if extra.get('fcsRor') is not None:
        out['fcsRorFMin'] = extra['fcsRor']
    if extra.get('totalRor') is not None:
        out['totalRorFMin'] = extra['totalRor']
    if extra.get('coolSec') is not None:
        out['coolSec'] = extra['coolSec']
    return out


def _phase_analysis(doc, points):
    """Analyzer style phase readouts for the detail view,
    aligned to Artisan's computed block (Tier 2 item 7):
    per phase duration and share (dry phase time still runs
    charge to dry end, as in Artisan calcStatistics), the per
    phase delta temp and average RoR from Artisan RoR() (the
    DRY phase RoR and delta are measured from the TURNING
    POINT, or from the greens temp when one is recorded, not
    from charge), per phase AUC (Artisan ts() ranges: charge
    to dry, dry to FC start, FC start to drop, above the AUC
    base), the RoR at FC START (fcs_ror, the RoR series value
    at the FC sample), the total RoR (TP to drop), and a cool
    phase line (drop to the cool end: the imported Artisan
    COOL time when present, else the last stored sample).
    Returns (table rows, turning point text, extra dict)."""
    events = doc.get('events') or {}
    meta = doc.get('metadata') or {}

    def ev(key, field):
        e = events.get(key)
        return e.get(field) if e else None

    total = doc.get('totalSec') or (points[-1][0] if points else 0)
    dry_t = ev('dryEnd', 't')
    fc_t = ev('fcStart', 't')
    drop_t = ev('drop', 't')
    saved_tp = doc.get('turningPoint') or {}
    tp = None
    if (saved_tp.get('t') is not None
            and saved_tp.get('tempF') is not None):
        # The live detected turning point, saved with the batch
        # (roastery.core._track_turning_point); it wins over the
        # offline curve scan below.
        tp = (saved_tp['t'], saved_tp['tempF'])
    else:
        for (t, bt) in points:
            if t <= 0:
                continue
            if dry_t is not None and t >= dry_t:
                break
            if dry_t is None and total and t > total * 0.5:
                break
            if tp is None or bt < tp[1]:
                tp = (t, bt)
    # AUC base: the saved AUC detail base when present, else
    # the charge temp (the base curve_auc uses for the batch).
    auc_detail = doc.get('aucDetail') or {}
    base = auc_detail.get('baseF')
    if base is None:
        base = ev('charge', 'tempF') or 0.0
    greens = 0.0
    try:
        greens = float(meta.get('GreensTempF') or 0.0)
    except Exception:
        greens = 0.0
    dry_temp = ev('dryEnd', 'tempF')
    # Drying delta and RoR, Artisan RoR() first two branches.
    dry_gain = None
    dry_ror = None
    if dry_temp is not None and greens > 0:
        dry_gain = dry_temp - greens
        if dry_t:
            dry_ror = dry_gain / (dry_t / 60.0)
    elif dry_temp is not None and tp is not None and dry_t is not None and dry_t > tp[0]:
        dry_gain = dry_temp - tp[1]
        dry_ror = dry_gain / ((dry_t - tp[0]) / 60.0)
    bounds = (('Drying', 0, dry_t, dry_gain, dry_ror),
              ('Maillard', dry_t, fc_t, None, None),
              ('Development', fc_t, drop_t, None, None))
    phases = {}
    rows = []
    for name, ta, tb, gain, ror in bounds:
        if ta is None or tb is None or tb <= ta:
            continue
        dur = tb - ta
        if gain is None:
            fa = _interp_pairs(points, float(ta))
            fb = _interp_pairs(points, float(tb))
            # Event temps are the recorded truth when present;
            # the curve interpolation is the fallback.
            ea = ev('charge' if name == 'Drying' else
                    'dryEnd' if name == 'Maillard' else 'fcStart',
                    'tempF')
            eb = ev('dryEnd' if name == 'Drying' else
                    'fcStart' if name == 'Maillard' else 'drop',
                    'tempF')
            if ea is not None:
                fa = ea
            if eb is not None:
                fb = eb
            gain = (fb - fa) if (fa is not None
                                 and fb is not None) else None
            ror = (gain / (dur / 60.0)) if gain is not None else None
        auc = _auc_range(points, float(ta), float(tb), float(base))
        phases[name] = {'sec': dur,
                        'sharePct': (dur * 100.0 / total)
                        if total else None,
                        'deltaF': gain, 'rorFMin': ror,
                        'aucFMin': auc}
        rows.append([name, _mmss(dur),
                     ('%.0f%%' % (dur * 100.0 / total))
                     if total else '--',
                     ('%+.0f F' % gain) if gain is not None
                     else '--',
                     ('%.1f F/min' % ror) if ror is not None
                     else '--',
                     ('%.0f' % auc) if auc is not None else '--'])
    # Cool phase: drop to cool end.
    cool_sec = None
    cool_end = None
    sub = (doc.get('artisan') or {}).get('events') or {}
    if sub.get('coolEndSec') is not None:
        cool_end = float(sub['coolEndSec'])
    elif points and drop_t is not None and points[-1][0] > drop_t:
        cool_end = float(points[-1][0])
    if cool_end is not None and drop_t is not None and cool_end > drop_t:
        cool_sec = cool_end - drop_t
        span = total + cool_sec
        rows.append(['Cool', _mmss(cool_sec),
                     ('%.0f%%' % (cool_sec * 100.0 / span))
                     if span else '--', '--', '--', '--'])
    # RoR at FC START from the one RoR implementation.
    fcs_ror = None
    if fc_t is not None and points:
        rors = core.compute_ror_series(points, core.ror_params(),
                                       offline=True)
        best = None
        for t, r in rors:
            if r is None:
                continue
            if best is None or abs(t - fc_t) < abs(best[0] - fc_t):
                best = (t, r)
        if best is not None:
            fcs_ror = best[1]
    total_ror = None
    drop_temp = ev('drop', 'tempF')
    if (tp is not None and drop_t is not None and drop_temp is not None
            and drop_t > tp[0]):
        total_ror = (drop_temp - tp[1]) / ((drop_t - tp[0]) / 60.0)
    extra = {'phases': phases, 'fcsRor': fcs_ror,
             'totalRor': total_ror, 'coolSec': cool_sec}
    tp_text = ('%.0f F at %s' % (tp[1], _mmss(tp[0]))) if tp         else '--'
    return rows, tp_text, extra


def detail_startup(self):
    """BatchDetail view onStartup: fill the view custom props from
    the staged document (DetailDocJson) and the captured presses
    (Events/SelectByBatch, named query)."""
    raw = system.tag.readBlocking([DETAIL_JSON])[0].value
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    self.view.custom.batchNumber = number
    if not raw:
        self.view.custom.titleText = 'No batch staged'
        return
    doc = system.util.jsonDecode(raw)
    meta = doc.get('metadata') or {}
    phases = doc.get('phases') or {}
    calculator_seed(doc)
    self.view.custom.titleText = 'Batch %s - %s' % (
        doc.get('batchNumber'), doc.get('beanName') or '')
    self.view.custom.subText = '%s - %s' % (
        (doc.get('roastStart') or '')[:16].replace('T', ' '),
        doc.get('roastDegree') or '')
    # HUNT-24 (polish round 2 hunt): a seeded stub batch carries
    # a seedNote in its document (HUNT-16); surface it on the
    # detail page so the stub analytics are not read as a real
    # roast. Empty for normal batches, and the label hides.
    self.view.custom.dSeedNote = doc.get('seedNote') or ''
    self.view.custom.dTotal = _mmss(doc.get('totalSec'))
    self.view.custom.dDtr = ('%.1f%%' % phases['dtrPct']
                             if phases.get('dtrPct') is not None
                             else '--')
    dt = doc.get('dropTempF')
    self.view.custom.dDropTemp = ('%.0f F' % dt) if dt else '--'
    loss = doc.get('weightLossPct')
    self.view.custom.dLoss = ('%.1f%%' % loss) if loss else '--'
    auc = doc.get('auc')
    self.view.custom.dAuc = ('%.0f' % auc) if auc else '--'
    self.view.custom.dSource = doc.get('source') or '--'
    self.view.custom.dPhases = (
        'Drying %s - Maillard %s - Development %s' % (
            _mmss(phases.get('dryingSec')),
            _mmss(phases.get('maillardSec')),
            _mmss(phases.get('developmentSec'))))
    # Statistics summary line (Tier 3 item 19): the same phase
    # values in the compact under chart form, percents of the
    # total roast time. No new math: the phase seconds and the
    # DTR percent come straight from the document phases block.
    _tot = float(doc.get('totalSec') or 0)

    def _share(sec):
        if not _tot or sec is None:
            return '--'
        return '%d%%' % int(round(float(sec) * 100.0 / _tot))
    def _ms(sec):
        sec = int(max(0, float(sec or 0)))
        return '%d:%02d' % (sec // 60, sec % 60)
    _sep = ' ' + chr(183) + ' '
    self.view.custom.dStatsLine = _sep.join([
        'Dry %s %s' % (_ms(phases.get('dryingSec')),
                       _share(phases.get('dryingSec'))),
        'Mai %s %s' % (_ms(phases.get('maillardSec')),
                       _share(phases.get('maillardSec'))),
        'Dev %s %s' % (_ms(phases.get('developmentSec')),
                       _share(phases.get('developmentSec'))),
        'DTR %s' % (('%.0f%%' % phases['dtrPct'])
                    if phases.get('dtrPct') is not None
                    else '--')])
    pts = []
    try:
        sds = _run(NQ_SERIES_SELECT, {'batch_number': number})
        for r in range(sds.rowCount):
            bt = sds.getValueAt(r, 'bean_temp_f')
            if bt is not None:
                pts.append((float(sds.getValueAt(r,
                                                 't_offset_sec')),
                            float(bt)))
    except Exception:
        pts = []
    pts.sort()
    # Detail chart max (polish round 2 item 6): floor the
    # axis span at DETAIL_MIN_SPAN_SEC so a very short batch
    # renders minute:second ticks like the live chart; the
    # DetailChart xAxis max binds this custom prop. The min
    # stays at axis base + 1000 in the view.
    _end_sec = float(doc.get('totalSec') or 0)
    if pts:
        _end_sec = max(_end_sec, pts[-1][0])
    _span_sec = max(_end_sec, float(DETAIL_MIN_SPAN_SEC))
    self.view.custom.detailMaxMs = (
        core.AXIS_BASE_MS + long(_span_sec * 1000) + 1000)
    seg_rows, tp_text, extra = _phase_analysis(doc, pts)
    self.view.custom.analysisDs = system.dataset.toDataSet(
        ['phase', 'time', 'share', 'gain', 'avgRor', 'auc'],
        seg_rows)
    self.view.custom.dTp = tp_text
    fcs = extra.get('fcsRor')
    self.view.custom.dFcsRor = ('%.1f F/min' % fcs)         if fcs is not None else '--'
    tror = extra.get('totalRor')
    self.view.custom.dTotalRor = ('%.1f F/min' % tror)         if tror is not None else '--'
    cool = extra.get('coolSec')
    self.view.custom.dCool = _mmss(cool)         if cool is not None else '--'
    lossd = doc.get('loss') or loss_yield_density(meta)
    def _pct(key):
        v = lossd.get(key)
        return ('%.1f%%' % v) if v is not None else '--'
    def _dens(key):
        v = lossd.get(key)
        return ('%.0f g/L' % v) if v is not None else '--'
    self.view.custom.dDefectsLoss = _pct('defectsLossPct')
    self.view.custom.dTotalLoss = _pct('totalLossPct')
    self.view.custom.dVolumeGain = _pct('volumeGainPct')
    self.view.custom.dMoistureLoss = _pct('moistureLossPct')
    self.view.custom.dOrganicLoss = _pct('organicLossPct')
    self.view.custom.dGreenDensity = _dens('greenDensityGL')
    self.view.custom.dRoastedDensity = _dens('roastedDensityGL')
    yld = lossd.get('totalYieldPct')
    self.view.custom.dYield = ('%.1f%%' % yld)         if yld is not None else '--'
    # BT similarity against the currently staged ghost
    # (Tier 2 item 10b), when the ghost carries a drop time.
    sim = None
    try:
        bg_pairs = core.background_points()
        bg_drop = system.tag.readBlocking(
            [core.BACKGROUND_DROP_TAG])[0].value
        evs = doc.get('events') or {}
        drop_ev = evs.get('drop') or {}
        dry_ev = evs.get('dryEnd') or {}
        if bg_pairs and bg_drop is not None and float(bg_drop) >= 0:
            sim = bt_similarity(pts, drop_ev.get('t'), bg_pairs,
                                float(bg_drop), dry_ev.get('t'))
    except Exception:
        sim = None
    self.view.custom.dSimilarity = ('%.1f F RMSE' % sim)         if sim is not None else '--'
    # Between batch line (Tier 3 item 20): one line carrying
    # the four BBP values when the document has them, and an
    # empty string when it does not, so batches with no
    # preceding drop show nothing.
    _bbp_doc = doc.get('bbp') or {}
    if _bbp_doc:
        self.view.custom.dBbp = (
            'Between batch (BBP): %s, bottom %.0f F, '
            'RoR in %.1f F/min, RoR out %.1f F/min' % (
                _mmss(_bbp_doc.get('time_sec')),
                float(_bbp_doc.get('bottom_temp_f') or 0),
                float(_bbp_doc.get('ror_in_f_min') or 0),
                float(_bbp_doc.get('ror_out_f_min') or 0)))
    else:
        self.view.custom.dBbp = ''
    ev_rows = []
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'Charge'), ('dryEnd', 'Dry End'),
                     ('fcStart', 'FC Start'), ('fcEnd', 'FC End'),
                     ('scStart', 'SC Start'), ('scEnd', 'SC End'),
                     ('drop', 'Drop')):
        e = events.get(key)
        if e:
            ev_rows.append([lbl, _mmss(e.get('t')),
                            ('%.0f F' % e['tempF'])
                            if e.get('tempF') is not None else '--'])
    for c in events.get('custom') or []:
        ev_rows.append([c.get('name') or 'Custom', _mmss(c.get('t')),
                        ('%.0f F' % c['tempF'])
                        if c.get('tempF') is not None else '--'])
    self.view.custom.eventsDs = system.dataset.toDataSet(
        ['event', 'time', 'temp'], ev_rows)
    meta_rows = []
    for m in core.FORM_MEMBERS:
        if meta.get(m) not in (None, ''):
            meta_rows.append([m, str(meta[m])])
    self.view.custom.metaDs = system.dataset.toDataSet(
        ['field', 'value'], meta_rows)
    press_rows = []
    try:
        pds = _run(NQ_EVENTS_SELECT, {'batch_number': number})
        for r in range(pds.rowCount):
            press_rows.append([
                pds.getValueAt(r, 'action'),
                _mmss(pds.getValueAt(r, 't_offset_sec')),
                pds.getValueAt(r, 'bean_temp_f'),
                pds.getValueAt(r, 'fan_level'),
                pds.getValueAt(r, 'heat_level')])
    except Exception:
        press_rows = []
    self.view.custom.pressDs = system.dataset.toDataSet(
        ['action', 'time', 'tempF', 'fan', 'heat'], press_rows)
    self.view.custom.hasPresses = len(press_rows) > 0


def new_roast(self):
    """NEW ROAST action: zero the workspace, take the next batch
    number (max of the database and the current tag, plus one),
    and land on the Roast page."""
    try:
        ds = _run(NQ_MAX_NUMBER)
        max_db = int(ds.getValueAt(0, 'max_number') or 0)
    except Exception:
        max_db = 0
    cur = core.read_members(['BatchNumber'])['BatchNumber'] or 0
    nxt = max(max_db, int(cur)) + 1
    core.reset_batch()
    core.write_members([('BatchNumber', nxt)])
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
    in v2 and stay null. Returns the number of batches inserted.

    HUNT-16 (polish round 2): stub rows gain a seedNote. A source
    row is a stub when totalSec is under 60 and drySec is 0: it
    never recorded even the first phase, so it is a short test
    artifact from early development, not a full roast record.
    Rows 4 to 7 of the legacy tag are exactly that (9 s each,
    drySec 0, the same drop temp repeated); rows 1 to 3 are short
    test roasts too (18 to 19 s) but carry complete phase splits
    and distinct curves, so the stub note would be false for them
    and they do not gain one. No fuller source for the stub rows
    survives anywhere: the RoastLog backup file is identical in
    content to the tag, and the original records were lost with
    the pre-rebuild database. Seeded values stay truthful to the
    source; nothing plausible is fabricated."""
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
        if total < 60 and (row['drySec'] or 0) == 0:
            doc['seedNote'] = (
                'Seeded from a RoastLog stub row (totalSec %g s, '
                'drySec 0): a short test artifact from early '
                'development, not a full roast record. No fuller '
                'source survives (the RoastLog backup file holds '
                'the same rows); the original record was lost '
                'with the pre-rebuild database.' % total)
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

# ---------------------------------------------------------------- Tier 3
# Item 18: batch export beyond .alog (CSV, JSON, printable HTML
# summary), and item 21: the yield and conversion calculator
# seeding. The export builders are pure library functions over
# the stored document (SelectById) and the stored series
# (Series/SelectByBatch, named queries only); the download
# handlers are thin one purpose wrappers around
# system.perspective.download, exactly like the .alog export in
# roastery.artisan. Ranking and production reports are skipped,
# per the Tier 3 inventory.

CALC_TAG = '[default]Roastery/Calculator'


def _series_rows(batch_number):
    """Stored series for one batch as plain dicts, in time order.
    RoR, fan and heat are the stored columns (RoR was derived by
    the one implementation at save time)."""
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    rows = []
    for r in range(ds.rowCount):
        rows.append({
            't': ds.getValueAt(r, 't_offset_sec'),
            'bt': ds.getValueAt(r, 'bean_temp_f'),
            'ror': ds.getValueAt(r, 'rate_of_rise_f'),
            'fan': ds.getValueAt(r, 'fan_level'),
            'heat': ds.getValueAt(r, 'heat_level')})
    rows.sort(key=lambda row: (row['t'] is None, row['t']))
    return rows


def _fmt_num(v, places=2):
    if v is None:
        return ''
    try:
        return ('%.' + str(places) + 'f') % float(v)
    except Exception:
        return str(v)


def _csv_cell(v):
    s = '' if v is None else str(v)
    if ',' in s or '"' in s or chr(10) in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _html_escape(v):
    s = '' if v is None else str(v)
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;'))


def build_csv_text(batch_number):
    """CSV export (Tier 3 item 18): a metadata header section
    (comment lines prefixed with # carrying the batch document
    key fields), then the series table with elapsed seconds,
    elapsed mm:ss, bean temp, RoR, fan and heat."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    doc = batch['document']
    meta = doc.get('metadata') or {}
    lines = []
    header = [
        ('Batch', doc.get('batchNumber')),
        ('Bean', doc.get('beanName')),
        ('Origin', meta.get('Origin')),
        ('Roast start', doc.get('roastStart')),
        ('Roast end', doc.get('roastEnd')),
        ('Roast degree', doc.get('roastDegree')),
        ('Drop temp F', _fmt_num(doc.get('dropTempF'), 1)),
        ('Total sec', doc.get('totalSec')),
        ('Charge weight g', _fmt_num(meta.get('ChargeWeightG'), 1)),
        ('Weight out g', _fmt_num(meta.get('WeightOutG'), 1)),
        ('Weight loss pct', _fmt_num(doc.get('weightLossPct'), 1)),
        ('AUC', _fmt_num(doc.get('auc'), 1)),
        ('Source', doc.get('source')),
    ]
    lines.append('# Roastery batch export')
    for k, v in header:
        if v not in (None, ''):
            lines.append('# ' + _csv_cell(k) + ',' + _csv_cell(v))
    lines.append('')
    lines.append('time_sec,time_mmss,bean_temp_f,'
                 'rate_of_rise_f_per_min,fan_level,heat_level')
    for row in _series_rows(batch_number):
        t = row['t']
        fan = row['fan']
        heat = row['heat']
        lines.append(','.join([
            _fmt_num(t, 1),
            _mmss(t) if t is not None else '',
            _fmt_num(row['bt']),
            _fmt_num(row['ror']),
            (('%d' % int(fan)) if fan is not None else ''),
            (('%d' % int(heat)) if heat is not None else '')]))
    return 'roastery-batch-%d.csv' % int(batch_number), chr(10).join(lines) + chr(10)


def build_json_text(batch_number):
    """JSON export (Tier 3 item 18): the full batch document
    plus the full stored series, one object."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    payload = {
        'batchNumber': int(batch_number),
        'beanName': batch['beanName'],
        'roastStart': _iso(batch['roastStart']),
        'roastEnd': _iso(batch['roastEnd']),
        'dropTempF': batch['dropTempF'],
        'document': batch['document'],
        'series': _series_rows(batch_number)}
    return ('roastery-batch-%d.json' % int(batch_number),
            system.util.jsonEncode(payload))


def build_summary_html(batch_number):
    """Printable summary (Tier 3 item 18): a standalone HTML
    file that reads well printed, with the batch metadata, the
    summary and phase analysis, the loss block, the events
    timeline and simple series statistics. Inline CSS lives in
    the generated file only (it is a print document, not a
    Perspective view, so the style class rule does not apply)."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    doc = batch['document']
    meta = doc.get('metadata') or {}
    phases = doc.get('phases') or {}
    rows = _series_rows(batch_number)
    pts = [(float(r['t']), float(r['bt'])) for r in rows
           if r['t'] is not None and r['bt'] is not None]
    seg_rows, tp_text, extra = _phase_analysis(doc, pts)
    lossd = doc.get('loss') or loss_yield_density(meta)
    max_bt = max([bt for _t, bt in pts]) if pts else None
    dur = pts[-1][0] if pts else None
    e = _html_escape
    out = []
    out.append('<!DOCTYPE html>')
    out.append('<html><head><meta charset="utf-8">')
    out.append('<title>Roastery Batch %s Summary</title>' % e(doc.get('batchNumber')))
    out.append('<style>body{font-family:Arial,sans-serif;margin:32px;'
               'color:#111}h1{font-size:22px;margin:0 0 4px}'
               'h2{font-size:15px;margin:24px 0 8px;color:#0c7bb3}'
               'table{border-collapse:collapse;min-width:320px}'
               'td,th{border:1px solid #999;padding:5px 10px;'
               'font-size:13px;text-align:left}'
               '.sub{color:#555;font-size:13px}</style></head><body>')
    out.append('<h1>Batch %s - %s</h1>' % (e(doc.get('batchNumber')), e(doc.get('beanName'))))
    out.append('<p class="sub">%s - %s</p>' % (
        e((doc.get('roastStart') or '')[:16].replace('T', ' ')),
        e(doc.get('roastDegree'))))
    out.append('<h2>Summary</h2><table>')
    summary = [
        ('Total time', _mmss(doc.get('totalSec'))),
        ('Drop temp', ('%.0f F' % doc['dropTempF']) if doc.get('dropTempF') else '--'),
        ('Weight loss', ('%.1f%%' % doc['weightLossPct']) if doc.get('weightLossPct') else '--'),
        ('Dev ratio (DTR)', ('%.1f%%' % phases['dtrPct']) if phases.get('dtrPct') is not None else '--'),
        ('AUC', ('%.0f' % doc['auc']) if doc.get('auc') else '--'),
        ('Turning point', tp_text),
        ('RoR at FC start', ('%.1f F/min' % extra['fcsRor']) if extra.get('fcsRor') is not None else '--'),
        ('Total RoR (TP to drop)', ('%.1f F/min' % extra['totalRor']) if extra.get('totalRor') is not None else '--'),
        ('Source', doc.get('source') or '--'),
    ]
    for k, v in summary:
        out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(k), e(v)))
    out.append('</table>')
    loss_labels = {'weightLossPct': 'Weight loss',
                   'defectsLossPct': 'Defects loss',
                   'totalLossPct': 'Total loss',
                   'totalYieldPct': 'Total yield',
                   'volumeGainPct': 'Volume gain',
                   'moistureLossPct': 'Moisture loss',
                   'organicLossPct': 'Organic loss',
                   'greenDensityGL': 'Green density',
                   'roastedDensityGL': 'Roasted density'}
    if lossd:
        out.append('<h2>Loss, Yield and Density</h2><table>')
        for k in ('weightLossPct', 'defectsLossPct', 'totalLossPct',
                  'totalYieldPct', 'volumeGainPct', 'moistureLossPct',
                  'organicLossPct'):
            if lossd.get(k) is not None:
                out.append('<tr><td>%s</td><td>%.1f%%</td></tr>' % (e(loss_labels.get(k, k)), lossd[k]))
        for k in ('greenDensityGL', 'roastedDensityGL'):
            if lossd.get(k) is not None:
                out.append('<tr><td>%s</td><td>%.0f g/L</td></tr>' % (e(loss_labels.get(k, k)), lossd[k]))
        out.append('</table>')
    out.append('<h2>Phase Analysis</h2><table>')
    out.append('<tr><th>Phase</th><th>Time</th><th>Share</th>'
               '<th>Gain</th><th>Avg RoR</th><th>AUC</th></tr>')
    for r in seg_rows:
        out.append('<tr>' + ''.join('<td>%s</td>' % e(c) for c in r) + '</tr>')
    out.append('</table>')
    out.append('<h2>Events</h2><table>')
    out.append('<tr><th>Event</th><th>Time</th><th>Temp</th></tr>')
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'Charge'), ('dryEnd', 'Dry End'),
                     ('fcStart', 'FC Start'), ('fcEnd', 'FC End'),
                     ('scStart', 'SC Start'), ('scEnd', 'SC End'),
                     ('drop', 'Drop')):
        ev = events.get(key)
        if ev:
            out.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                e(lbl), e(_mmss(ev.get('t'))),
                e(('%.0f F' % ev['tempF']) if ev.get('tempF') is not None else '--')))
    for c in events.get('custom') or []:
        out.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(c.get('name') or 'Custom'), e(_mmss(c.get('t'))),
            e(('%.0f F' % c['tempF']) if c.get('tempF') is not None else '--')))
    out.append('</table>')
    out.append('<h2>Metadata</h2><table>')
    for m in core.FORM_MEMBERS:
        if meta.get(m) not in (None, ''):
            out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(m), e(meta[m])))
    out.append('</table>')
    out.append('<h2>Curve Statistics</h2><table>')
    stats = [
        ('Samples', str(len(pts))),
        ('Duration', _mmss(dur) if dur is not None else '--'),
        ('Max bean temp', ('%.1f F' % max_bt) if max_bt is not None else '--'),
    ]
    for k, v in stats:
        out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(k), e(v)))
    out.append('</table>')
    out.append('</body></html>')
    return ('roastery-batch-%d-summary.html' % int(batch_number),
            chr(10).join(out))


def export_csv_download(self):
    """BatchDetail Export CSV button (thin)."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_csv_text(int(number))
    system.perspective.download(filename, text)


def export_json_download(self):
    """BatchDetail Export JSON button (thin)."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_json_text(int(number))
    system.perspective.download(filename, text)


def export_summary_download(self):
    """BatchDetail Print Summary button (thin): downloads the
    printable HTML summary; open it and print from the browser."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_summary_html(int(number))
    system.perspective.download(filename, text)


def calculator_seed(doc):
    """Tier 3 item 21: seed the calculator tags from the staged
    batch, so the calculator on BatchDetail starts from this
    batch's own weights. The math itself lives on expression
    tags in the Calculator folder (expected out, actual loss,
    and the F/C and g/oz conversions), so the readouts update
    live as the bidirectional tag bound inputs are edited."""
    meta = (doc or {}).get('metadata') or {}
    writes = []
    try:
        charge = float(meta.get('ChargeWeightG') or 0)
    except Exception:
        charge = 0
    try:
        out_w = float(meta.get('WeightOutG') or 0)
    except Exception:
        out_w = 0
    if charge > 0:
        writes.append((CALC_TAG + '/ChargeG', charge))
        writes.append((CALC_TAG + '/ConvG', charge))
    if out_w > 0:
        writes.append((CALC_TAG + '/OutG', out_w))
    if writes:
        system.tag.writeBlocking([p for p, _v in writes],
                                 [v for _p, v in writes])
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
    ('Roastery/Batches/SelectMaxNumber', 'Query',
     "SELECT COALESCE(MAX(batch_number), 0) AS max_number FROM batches",
     []),
    ('Roastery/Events/InsertPress', 'UpdateQuery',
     "INSERT INTO batch_events (batch_number, action, t_offset_sec, bean_temp_f, rate_of_rise_f, fan_level, heat_level)\n"
     "VALUES (:batch_number, :action, :t_offset_sec, :bean_temp_f, :rate_of_rise_f, :fan_level, :heat_level)",
     [('batch_number', NQ_INT4), ('action', NQ_STRING),
      ('t_offset_sec', NQ_INT4), ('bean_temp_f', NQ_FLOAT8),
      ('rate_of_rise_f', NQ_FLOAT8), ('fan_level', NQ_INT4),
      ('heat_level', NQ_INT4)]),
    ('Roastery/Events/SelectByBatch', 'Query',
     "SELECT id, batch_number, action, t_offset_sec, bean_temp_f, rate_of_rise_f, fan_level, heat_level, pressed_at\n"
     "FROM batch_events WHERE batch_number = :batch_number ORDER BY pressed_at, id",
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

ARTISAN_CODE = r'''# Roastery Artisan interoperability: import and export of Artisan
# .alog roast profile files. Artisan is Eric's other roast tool
# (the SR800 Pico feed also talks to it), so the roast log speaks
# its format both ways.
#
# Format (from the Artisan 5.0.0 source study,
# knowledge/notes/artisan-file-format.md): an .alog file is ONE
# Python dict literal, parsed by Artisan with ast.literal_eval.
# `mode` ('C' or 'F') is the unit of every temperature in the file.
# The bean curve is temp2, the environment curve temp1, both over
# timex = seconds since RECORDING start. Main events exist only
# as sample indices in timeindex [CHARGE, DRY, FCs, FCe, SCs, SCe,
# DROP, COOL]. Custom slider events live in specialevents with
# values on Artisan's internal scale. Missing readings are -1.
# RoR is never stored; it is recomputed from the temps, which is
# why batch_series keeps temps as truth and this module runs the
# imported temps through roastery.core.compute_ror_series.
#
# Import maps the profile onto the standard batch document and
# series rows through the existing named queries, and keeps
# everything Roastery has no field for (the ET curve, extra
# devices, alarms, PID, energy, display colors, computed cache)
# verbatim in the document's `artisan` subdocument (schema grouped
# identity / curves / events / display / settings per the format
# note), so export is lossless. Export rebuilds the .alog dict
# from the stored batch, carrying the imported values when
# present, writes the Artisan 5.0.0 identity fields with the
# signature constant published in the Artisan source (that pair is
# what Artisan's official builds verify, so exported files open
# without a "not genuine" prompt), and finishes with the file
# hash: SHA-256 over the canonical JSON of the profile with every
# int converted to float, exactly as Artisan computes it.
#
# Quantization decisions (documented once, here): Artisan slider
# percents map to SR800 levels with level = 1 + round(pct * 8 /
# 100), clamped to 1..9, and back with pct = (level - 1) * 12.5.
# Series rows start at Charge (negative offsets are dropped; the
# full raw arrays stay in the artisan subdocument). The ET curve
# of a native Roastery batch exports as all -1 (no ET probe).

import ast
import java.lang
import java.security
import java.util

import roastery.batches as batches
import roastery.core as core

LOG = system.util.getLogger('roastery.artisan')

SIGNATURE = ('651a113abb93bbd95c324cc534f9cf0f32a9425dfe8bd3f55c788971'
             'd7979342bbed0e0669b62328842850efbb31a8adcad9f74738'
             'f7d8cc475e86bb3ffa5f00')
ARTISAN_VERSION = '5.0.0'

SLOT_DOC = ('charge', 'dryEnd', 'fcStart', 'fcEnd', 'scStart',
            'scEnd', 'drop')
DEFAULT_ETYPES = ['Air', 'Drum', 'Damper', 'Burner', '--']
ALT_ETYPES = ['Fan', 'Drum', 'Cooling', 'Heater', '--']

STRUCT_KEYS = frozenset([
    'mode', 'timex', 'temp1', 'temp2', 'timeindex',
    'specialevents', 'specialeventstype', 'specialeventsvalue',
    'specialeventsStrings', 'beans', 'weight', 'phases',
    'samplinginterval', 'title', 'hash', 'signature', 'version',
    'revision', 'build', 'recording_version', 'recording_revision',
    'recording_build', 'artisan_os', 'artisan_os_version',
    'artisan_os_arch', 'roastUUID', 'roastbatchnr',
    'roastbatchprefix', 'roastbatchpos', 'roastdate',
    'roastisodate', 'roasttime', 'roastepoch', 'roasttzoffset',
    'locale', 'viewerMode', 'computed'])
CURVE_KEYS = frozenset([
    'extradevices', 'extraname1', 'extraname2', 'extratimex',
    'extratemp1', 'extratemp2', 'extramathexpression1',
    'extramathexpression2'])
EVENT_KEYS = frozenset([
    'etypes', 'default_etypes', 'default_etypes_set',
    'eventsliderunits', 'load_etypes'])
DISPLAY_KEYS = frozenset([
    'extradevicecolor1', 'extradevicecolor2',
    'extraCurveVisibility1', 'extraCurveVisibility2',
    'extraDelta1', 'extraDelta2', 'extraFill1', 'extraFill2',
    'extraLCDvisibility1', 'extraLCDvisibility2',
    'extraNoneTempHint1', 'extraNoneTempHint2',
    'extradrawstyles1', 'extradrawstyles2', 'extralinestyles1',
    'extralinestyles2', 'extralinewidths1', 'extralinewidths2',
    'extramarkers1', 'extramarkers2', 'extramarkersizes1',
    'extramarkersizes2', 'whole_color', 'ground_color',
    'color_system', 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax',
    'anno_positions', 'flag_positions'])
IDENTITY_KEYS = (
    'title', 'version', 'revision', 'build', 'recording_version',
    'recording_revision', 'recording_build', 'artisan_os',
    'artisan_os_version', 'artisan_os_arch', 'roastUUID',
    'roastbatchnr', 'roastbatchprefix', 'roastbatchpos',
    'roastdate', 'roastisodate', 'roasttime', 'roastepoch',
    'roasttzoffset', 'locale', 'devices', 'sourcetypes')

GRAMS = {'g': 1.0, 'kg': 1000.0, 'lb': 453.59237,
         'lbs': 453.59237, 'oz': 28.349523125}
VOLUMES = {'ml': 1.0, 'l': 1000.0, 'oz': 29.5735,
           'fl oz': 29.5735, 'floz': 29.5735}
DEFECT_FIELDS = (
    ('DefectHeavyFC', 'heavyFC'), ('DefectLowFC', 'lowFC'),
    ('DefectLightCut', 'lightCut'), ('DefectDarkCut', 'darkCut'),
    ('DefectDrops', 'drops'), ('DefectOily', 'oily'),
    ('DefectUneven', 'uneven'), ('DefectTipping', 'tipping'),
    ('DefectScorching', 'scorching'), ('DefectDivots', 'divots'))


# ---------------------------------------------------------------- parse

def parse_alog(text):
    """Parse .alog text exactly as Artisan's loader does: the
    first character must be '{' and the body must evaluate as a
    Python literal dict (ast.literal_eval)."""
    if text is None:
        raise ValueError('Empty file.')
    stripped = text.strip()
    if not stripped.startswith('{'):
        raise ValueError('Not an Artisan .alog file: the first '
                         'character must be an opening brace.')
    try:
        data = ast.literal_eval(stripped)
    except Exception:
        # Older Jython ast builds lack literal_eval; a builtins
        # free eval of a literal is the same operation.
        data = eval(stripped, {'__builtins__': {},
                               'True': True, 'False': False,
                               'None': None})
    if not isinstance(data, dict):
        raise ValueError('Not an Artisan .alog file: the content '
                         'is not a profile dict.')
    if 'timex' not in data or 'temp2' not in data:
        raise ValueError('Not an Artisan roast profile: it has '
                         'no timex/temp2 curve arrays.')
    return data


def _proper(v):
    """Artisan is_proper_temp: -1, 0 and None are missing."""
    return v is not None and v != -1 and v != 0


def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _to_f(v, mode):
    if not _proper(v):
        return None
    v = float(v)
    return v if mode == 'F' else v * 9.0 / 5.0 + 32.0


def _from_f(v, mode):
    if v is None:
        return None
    v = float(v)
    return v if mode == 'F' else (v - 32.0) * 5.0 / 9.0


def _pct_from_internal(v):
    """Artisan event value scale (util.py): stored v maps to an
    external percent: v == 0 gives 0, v >= 1 gives (v - 1) * 10,
    v <= -1 gives (v + 1) * 10, between 0 and 1 gives v * 10."""
    v = _num(v)
    if v == 0:
        return 0.0
    if v >= 1:
        return (v - 1.0) * 10.0
    if v <= -1:
        return (v + 1.0) * 10.0
    return v * 10.0


def _internal_from_pct(pct):
    pct = float(pct)
    if pct == 0:
        return 0.0
    return pct / 10.0 + 1.0


def _level_from_pct(pct):
    lvl = 1 + int(round(float(pct) * 8.0 / 100.0))
    return max(1, min(9, lvl))


def _pct_from_level(level):
    return (float(level) - 1.0) * 12.5


def _iso(epoch_ms):
    if epoch_ms is None:
        return None
    return system.date.format(java.util.Date(long(epoch_ms)),
                              "yyyy-MM-dd'T'HH:mm:ss")


def _profile_epoch_ms(p):
    """Epoch ms of the charge moment: roastepoch (recording
    start) plus the charge offset, with an isodate fallback."""
    t0 = 0.0
    ti = p.get('timeindex') or []
    timex = p.get('timex') or []
    if ti and isinstance(ti[0], (int, float)) and ti[0] >= 0 \
            and ti[0] < len(timex):
        t0 = float(timex[ti[0]])
    epoch = p.get('roastepoch')
    if epoch:
        return long(float(epoch) * 1000.0 + t0 * 1000.0), t0
    isodate = p.get('roastisodate')
    if isodate:
        try:
            dt = system.date.parse(
                '%s %s' % (isodate, p.get('roasttime') or '00:00:00'),
                'yyyy-MM-dd HH:mm:ss')
            return dt.getTime(), t0
        except Exception:
            pass
    return None, t0


# ---------------------------------------------------------------- import

def _classify(p):
    """Split a parsed profile into the artisan subdocument:
    identity / curves / events / display carried in named groups,
    and every other key verbatim under settings (lossless)."""
    identity = {}
    for k in IDENTITY_KEYS:
        if k in p:
            identity[k] = p[k]
    curves = {'mode': p.get('mode') or 'F',
              'timex': p.get('timex') or [],
              'temp1': p.get('temp1') or [],
              'temp2': p.get('temp2') or [],
              'samplinginterval': p.get('samplinginterval')}
    ti = list(p.get('timeindex') or [])
    while len(ti) < 8:
        ti.append(0)
    curves['chargeIndex'] = ti[0]
    curves['timeindexRaw'] = ti
    for k in CURVE_KEYS:
        if k in p:
            curves[k] = p[k]
    events = {'specialevents': p.get('specialevents') or [],
              'specialeventstype':
                  p.get('specialeventstype') or [],
              'specialeventsvalue':
                  p.get('specialeventsvalue') or [],
              'specialeventsStrings':
                  p.get('specialeventsStrings') or []}
    for k in EVENT_KEYS:
        if k in p:
            events[k] = p[k]
    display = {}
    for k in DISPLAY_KEYS:
        if k in p:
            display[k] = p[k]
    if 'phases' in p:
        display['phasesRaw'] = p['phases']
    settings = {}
    known = STRUCT_KEYS | CURVE_KEYS | EVENT_KEYS | DISPLAY_KEYS
    for k in p:
        if k not in known:
            settings[k] = p[k]
    if 'weight' in p:
        settings['weightRaw'] = p['weight']
    if 'computed' in p:
        settings['computedImported'] = p['computed']
    return {'formatVersion': 1, 'identity': identity,
            'curves': curves, 'events': events,
            'display': display, 'settings': settings}


def _etypes_of(p):
    for key in ('etypes', 'load_etypes', 'default_etypes'):
        v = p.get(key)
        if v:
            return [str(x) for x in v]
    return list(DEFAULT_ETYPES)


def _weight_g(p, idx):
    w = p.get('weight') or []
    if len(w) <= idx:
        return 0.0
    unit = str(w[2]).lower() if len(w) > 2 else 'g'
    return _num(w[idx]) * GRAMS.get(unit, 1.0)


def _density_from_list(d):
    """Grams per litre from an Artisan density list of the
    shape [amount, amountUnit, volume, volumeUnit]."""
    if not d or len(d) < 4:
        return 0.0
    amount = _num(d[0]) * GRAMS.get(str(d[1]).lower(), 1.0)
    vol = _num(d[2])
    vunit = str(d[3]).lower()
    liters = vol if vunit == 'l' else vol / 1000.0
    if amount > 0 and liters > 0:
        return amount / liters
    return 0.0


def _density_gl(p):
    return _density_from_list(p.get('density') or [])


def _fan_heat_series(p, timex, t0, mode):
    """Fan and Heater slider events become per sample step
    levels and the fanHeatTrace entries (SR800 1..9 levels)."""
    etypes = _etypes_of(p)
    fan_t = heat_t = None
    for i, name in enumerate(etypes):
        if name in ('Fan', 'Air') and fan_t is None:
            fan_t = i
        if name in ('Heater', 'Burner') and heat_t is None:
            heat_t = i
    idxs = p.get('specialevents') or []
    tys = p.get('specialeventstype') or []
    vals = p.get('specialeventsvalue') or []
    fan_events = []
    heat_events = []
    for j in range(len(idxs)):
        idx = idxs[j]
        if not isinstance(idx, (int, float)) \
                or idx < 0 or idx >= len(timex):
            continue
        t = int(round(float(timex[int(idx)]) - t0))
        if t < 0:
            continue
        typ = int(tys[j]) if j < len(tys) else -1
        pct = _pct_from_internal(vals[j] if j < len(vals) else 0)
        if typ == fan_t:
            fan_events.append((t, pct))
        elif typ == heat_t:
            heat_events.append((t, pct))
    fan_events.sort()
    heat_events.sort()

    def level_at(events, t, default=5):
        lvl = None
        for et, pct in events:
            if et <= t:
                lvl = _level_from_pct(pct)
            else:
                break
        if lvl is None:
            lvl = _level_from_pct(events[0][1]) if events else default
        return lvl

    merged = sorted(set([t for t, _ in fan_events] +
                        [t for t, _ in heat_events]))
    trace = []
    for t in merged:
        fp = [pct for et, pct in fan_events if et == t]
        hp = [pct for et, pct in heat_events if et == t]
        if fp:
            label = 'Fan %g%%' % fp[0]
        else:
            label = 'Heat %g%%' % hp[0]
        trace.append({'t': float(t), 'label': label,
                      'fan': float(level_at(fan_events, t)),
                      'heat': float(level_at(heat_events, t))})
    return fan_events, heat_events, level_at, trace


def profile_to_batch(p, batch_number):
    """Map a parsed Artisan profile to (document, series points,
    insert params) in the standard Roastery batch shapes."""
    mode = p.get('mode') or 'F'
    timex = [float(v) for v in (p.get('timex') or [])]
    temp2 = p.get('temp2') or []
    temp1 = p.get('temp1') or []
    ti = list(p.get('timeindex') or [])
    while len(ti) < 8:
        ti.append(-1 if len(ti) == 0 else 0)
    ci = ti[0]
    if ci is None or ci < 0 or ci >= len(timex):
        ci = 0
    t0 = float(timex[ci]) if timex else 0.0
    # _profile_epoch_ms returns the charge moment: roastepoch
    # (recording start) plus the charge offset. The isodate
    # fallback names the roast's own start time and is used as
    # the charge moment directly.
    charge_ms, _ = _profile_epoch_ms(p)

    def event_at(slot):
        idx = ti[slot]
        if idx is None:
            return None, None
        if slot == 0:
            if idx < 0:
                return None, None
        elif idx <= 0:
            return None, None
        if idx >= len(timex):
            return None, None
        t = int(round(float(timex[int(idx)]) - t0))
        bt = _to_f(temp2[int(idx)] if int(idx) < len(temp2)
                   else None, mode)
        et = _to_f(temp1[int(idx)] if int(idx) < len(temp1)
                   else None, mode)
        ev = {'t': t,
              'ts': _iso(charge_ms + t * 1000)
              if charge_ms is not None else None,
              'tempF': bt}
        return ev, et

    events = {}
    et_temps = {}
    for slot in range(7):
        ev, et = event_at(slot)
        events[SLOT_DOC[slot]] = ev
        if et is not None:
            et_temps[SLOT_DOC[slot]] = et
    if events['charge'] is None:
        bt = _to_f(temp2[ci] if ci < len(temp2) else None, mode)
        events['charge'] = {
            't': 0,
            'ts': _iso(charge_ms) if charge_ms is not None
            else None,
            'tempF': bt}
    cool_ev, _et = event_at(7)
    cool_sec = cool_ev['t'] if cool_ev else None

    fan_events, heat_events, level_at, trace = _fan_heat_series(
        p, timex, t0, mode)

    by_t = {}
    for i in range(len(timex)):
        raw = temp2[i] if i < len(temp2) else None
        bt = _to_f(raw, mode)
        if bt is None:
            continue
        t = int(round(float(timex[i]) - t0))
        if t < 0:
            continue
        by_t[t] = {'t': t, 'bt': bt, 'ror': None,
                   'ts': java.util.Date(long(charge_ms + t * 1000))
                   if charge_ms is not None else None,
                   'fan': level_at(fan_events, t),
                   'heat': level_at(heat_events, t)}
    points = [by_t[k] for k in sorted(by_t.keys())]

    charge_ev = events['charge']
    dry_ev = events['dryEnd']
    fc_ev = events['fcStart']
    drop_ev = events['drop']
    total = drop_ev['t'] if drop_ev else (
        points[-1]['t'] if points else 0)
    dry = dry_ev['t'] if dry_ev else 0
    fc = fc_ev['t'] if fc_ev else total
    drop_temp = drop_ev['tempF'] if drop_ev else None
    charge_temp = charge_ev['tempF'] if charge_ev else None
    charge_w = _weight_g(p, 0)
    out_w = _weight_g(p, 1)
    loss = ((charge_w - out_w) * 100.0 / charge_w) \
        if out_w > 0 and charge_w > 0 else 0.0

    meta = dict((m, '' if m not in core.FORM_INTS
                 and m not in core.FORM_FLOATS else 0)
                for m in core.FORM_MEMBERS)
    for m in core.FORM_FLOATS:
        meta[m] = 0.0
    beans = p.get('beans') or ''
    meta['BeanName'] = beans
    meta['ChargeWeightG'] = charge_w
    meta['WeightOutG'] = out_w
    meta['MoisturePct'] = _num(p.get('moisture_greens'))
    meta['DensityGL'] = _density_gl(p)
    meta['OperatorName'] = p.get('operator') or ''
    meta['Notes'] = p.get('roastingnotes') or ''
    meta['CuppingNotes'] = p.get('cuppingnotes') or ''
    meta['TargetDropTempF'] = drop_temp or 0.0
    meta['RoastTitle'] = p.get('title') or ''
    meta['RoasterType'] = p.get('roastertype') or ''
    meta['RoasterSizeKg'] = _num(p.get('roastersize'))
    meta['RoasterHeating'] = int(_num(p.get('roasterheating')))
    meta['Organization'] = p.get('organization') or ''
    vol = p.get('volume') or []
    vol_unit = str(vol[2]).lower() if len(vol) > 2 else 'ml'
    vol_factor = VOLUMES.get(vol_unit, 1.0)
    meta['VolumeInMl'] = _num(vol[0]) * vol_factor \
        if len(vol) > 0 else 0.0
    meta['VolumeOutMl'] = _num(vol[1]) * vol_factor \
        if len(vol) > 1 else 0.0
    weight = p.get('weight') or []
    weight_unit = str(weight[2]).lower() \
        if len(weight) > 2 else 'g'
    meta['DefectsWeightG'] = _num(p.get('defects_weight')) * \
        GRAMS.get(weight_unit, 1.0)
    meta['RoastedDensityGL'] = _density_from_list(
        p.get('density_roasted') or [])
    meta['BeanSizeMinMm'] = _num(p.get('beansize_min'))
    if p.get('beansize_max') not in (None, ''):
        meta['BeanSizeMaxMm'] = _num(p.get('beansize_max'))
    else:
        meta['BeanSizeMaxMm'] = _num(p.get('beansize'))
    for member, key in DEFECT_FIELDS:
        meta[member] = bool(p.get(key))
    meta['WholeColor'] = _num(p.get('whole_color'))
    meta['GroundColor'] = _num(p.get('ground_color'))
    meta['ColorSystem'] = p.get('color_system') or ''
    meta['AmbientTempF'] = _to_f(p.get('ambientTemp'), mode) \
        or 0.0
    meta['AmbientHumidityPct'] = _num(p.get('ambient_humidity'))
    meta['AmbientPressureHPa'] = _num(p.get('ambient_pressure'))
    meta['RoastedMoisturePct'] = _num(p.get('moisture_roasted'))
    meta['GreensTempF'] = _to_f(p.get('greens_temp'), mode) \
        or 0.0

    end_ms = None
    if charge_ms is not None:
        end_ms = charge_ms + long(total * 1000)
    doc = {
        'batchNumber': int(batch_number),
        'beanName': beans or (p.get('title') or 'Artisan import'),
        'roastStart': _iso(charge_ms),
        'roastEnd': _iso(end_ms),
        'dropTempF': drop_temp,
        'roastDegree': batches.roast_degree(drop_temp),
        'totalSec': total,
        'phases': {'dryingSec': dry, 'maillardSec': fc - dry,
                   'developmentSec': total - fc,
                   'dtrPct': ((total - fc) * 100.0 / total)
                   if total > 0 else 0.0},
        'auc': batches.curve_auc(points, charge_temp),
        'weightLossPct': loss,
        'source': 'Artisan import',
        'metadata': meta,
        'events': {'charge': charge_ev, 'dryEnd': dry_ev,
                   'fcStart': fc_ev, 'fcEnd': events['fcEnd'],
                   'scStart': events['scStart'],
                   'scEnd': events['scEnd'], 'drop': drop_ev,
                   'custom': []},
        'target': {
            'chargeTempF': charge_temp or 0.0,
            'dryEndSec': dry_ev['t'] if dry_ev else 0,
            'dryEndTempF': dry_ev['tempF'] if dry_ev else 0.0,
            'fcSec': fc_ev['t'] if fc_ev else 0,
            'fcTempF': fc_ev['tempF'] if fc_ev else 0.0,
            'dropSec': total,
            'dropTempF': drop_temp or 0.0},
        'fanHeatTrace': trace}
    doc['loss'] = batches.loss_yield_density(meta)
    sub = _classify(p)
    sub['events']['coolEndSec'] = cool_sec
    sub['events']['etTempsF'] = et_temps
    doc['artisan'] = sub
    # Phase analysis runs after the artisan subdocument is
    # attached: its cool phase reads the imported COOL time
    # from sub['events']['coolEndSec'].
    doc['phaseAnalysis'] = batches.phase_analysis(
        doc, [(pt['t'], pt['bt']) for pt in points])
    params = {
        'batch_number': int(batch_number),
        'roast_start': java.util.Date(long(charge_ms))
        if charge_ms is not None else None,
        'roast_end': java.util.Date(long(end_ms))
        if end_ms is not None else None,
        'bean_name': doc['beanName'],
        'drop_temp_f': drop_temp,
        'data': system.util.jsonEncode(doc)}
    return doc, points, params


def _insert_points(batch_number, points):
    """Series insert for imported batches: temps are truth, the
    stored RoR is recomputed by the one library implementation
    (offline path), through Series/InsertBatch only. Imports do
    not use the live capture mode switch; that switch governs
    roasts recorded on the gateway itself."""
    if not points:
        return 0
    temps = [(pt['t'], pt['bt']) for pt in points]
    rors = core.compute_ror_series(temps, core.ror_params(),
                                   offline=True)
    ror_by_t = dict((t, r) for t, r in rors)
    payload = []
    for pt in points:
        item = {'t': pt['t'], 'bt': pt['bt'],
                'ror': ror_by_t.get(pt['t'])}
        if pt.get('ts') is not None:
            item['ts'] = system.date.format(
                pt['ts'], "yyyy-MM-dd'T'HH:mm:ss.SSSZ")
        if pt.get('fan') is not None:
            item['fan'] = pt['fan']
        if pt.get('heat') is not None:
            item['heat'] = pt['heat']
        payload.append(item)
    return batches._run(batches.NQ_SERIES_INSERT, {
        'batch_number': int(batch_number),
        'points': system.util.jsonEncode(payload)})


def _next_free_number():
    ds = batches._run(batches.NQ_MAX_NUMBER)
    n = 0
    if ds.rowCount > 0:
        v = ds.getValueAt(0, 'max_number')
        n = int(v) if v is not None else 0
    n += 1
    while batches.get_batch(n) is not None:
        n += 1
    return n


def _already_imported(uuid):
    if not uuid:
        return None
    ds = batches._run(batches.NQ_SELECT_ALL)
    for r in range(ds.rowCount):
        number = ds.getValueAt(r, 'batch_number')
        b = batches.get_batch(number)
        if b is None:
            continue
        sub = (b['document'].get('artisan') or {}).get('identity') \
            or {}
        if sub.get('roastUUID') == uuid:
            return number
    return None


def import_profile(p, filename):
    """Insert a parsed profile as a new batch. Returns
    (batch_number, message)."""
    uuid = p.get('roastUUID')
    dupe = _already_imported(uuid)
    if dupe is not None:
        return None, ('This Artisan roast is already in the log '
                      'as batch %d (same roastUUID).' % dupe)
    number = _next_free_number()
    doc, points, params = profile_to_batch(p, number)
    batches._run(batches.NQ_INSERT, params)
    _insert_points(number, points)
    src_nr = p.get('roastbatchnr')
    msg = 'Imported %s as batch %d' % (filename or 'file', number)
    if src_nr:
        msg += ' (Artisan batch %s)' % src_nr
    msg += ': %d samples, %s.' % (
        len(points), doc['beanName'] or 'unnamed bean')
    return number, msg


def import_upload(self, event):
    """Log page FileUpload onFileReceived handler (thin)."""
    note = ''
    try:
        f = event.file
        if f is None:
            raise ValueError('No file arrived with the event.')
        raw = f.getBytes()
        text = str(java.lang.String(raw, 'UTF-8'))
        profile = parse_alog(text)
        number, msg = import_profile(profile, f.name)
        note = msg
        if number is not None:
            system.perspective.sendMessage(
                batches.REFRESH_MESSAGE, {}, scope='page')
    except Exception as e:
        LOG.error('Artisan import failed: %s' % e)
        note = 'Import failed: %s' % e
    try:
        self.view.custom.importNote = note
    except Exception:
        pass
    return note


def stage_background_upload(self, event):
    """Roast page FileUpload onFileReceived handler (thin):
    stage the uploaded profile's bean curve as the Roast page
    background overlay. Nothing is saved to the log."""
    note = ''
    try:
        f = event.file
        if f is None:
            raise ValueError('No file arrived with the event.')
        raw = f.getBytes()
        text = str(java.lang.String(raw, 'UTF-8'))
        profile = parse_alog(text)
        doc, points, params = profile_to_batch(profile, 0)
        pairs = [[pt['t'], pt['bt']] for pt in points]
        if not pairs:
            raise ValueError('The file has no bean curve '
                             'samples at or after charge.')
        # Playback events (Tier 2 item 11) stage with the
        # ghost, derived from the imported per sample levels
        # by the same roastery.core builder the saved batch
        # route uses.
        levels = [(pt['t'], pt.get('fan'), pt.get('heat'))
                  for pt in points]
        events = core.build_background_events(
            levels, float(doc.get('totalSec') or -1))
        # Phase boundaries for Tier 3 item 16 stage with the
        # ghost, from the imported document events.
        _ev = doc.get('events') or {}
        core.stage_bg_phases((_ev.get('dryEnd') or {}).get('t'),
                             (_ev.get('fcStart') or {}).get('t'),
                             (_ev.get('drop') or {}).get('t'))
        system.tag.writeBlocking(
            [core.BACKGROUND_JSON, batches.BACKGROUND_LABEL,
             core.BACKGROUND_DROP_TAG, core.BACKGROUND_EVENTS_TAG],
            [system.util.jsonEncode(pairs),
             'File: ' + (f.name or 'profile.alog'),
             float(doc.get('totalSec') or -1),
             system.util.jsonEncode(events)])
        core.build_overlays()
        note = 'Background staged from %s: %d samples. ' \
            'Nothing was saved to the log.' % (
                f.name or 'file', len(pairs))
    except Exception as e:
        LOG.error('Artisan background staging failed: %s' % e)
        note = 'Background failed: %s' % e
    try:
        self.view.custom.bgNote = note
    except Exception:
        pass
    return note


# ---------------------------------------------------------------- export

def _native(v):
    """Normalize Java values that can ride along in a decoded
    batch document (Double, Integer, Boolean, ArrayList) to the
    Python natives the encoders below branch on."""
    if isinstance(v, (java.lang.Double, java.lang.Float)):
        return float(v)
    if isinstance(v, java.lang.Number):
        return int(v)
    if isinstance(v, java.lang.Boolean):
        return bool(v)
    if isinstance(v, dict):
        return dict((k, _native(x)) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return [_native(x) for x in v]
    if isinstance(v, basestring):
        return unicode(v)
    return v


def _py_float(x):
    """Format a float the way CPython repr does (shortest round
    trip digits, fixed notation for decimal exponents in
    (-4, 16], scientific outside). Java Double.toString supplies
    the shortest digits; only the notation differs."""
    if x == 0.0:
        return '-0.0' if str(x).startswith('-') else '0.0'
    s = java.lang.Double.toString(float(x))
    sign = ''
    if s.startswith('-'):
        sign, s = '-', s[1:]
    if 'E' in s:
        mant, exp = s.split('E')
        exp = int(exp)
    else:
        mant, exp = s, 0
    if '.' in mant:
        ip, fp = mant.split('.')
    else:
        ip, fp = mant, ''
    digits = (ip + fp).lstrip('0')
    k = exp - len(fp)
    while len(digits) > 1 and digits.endswith('0'):
        digits = digits[:-1]
        k += 1
    point = k + len(digits)
    if -4 < point <= 16:
        if point >= len(digits):
            out = digits + '0' * (point - len(digits)) + '.0'
        elif point > 0:
            out = digits[:point] + '.' + digits[point:]
        else:
            out = '0.' + '0' * (-point) + digits
    else:
        e = point - 1
        out = digits[0]
        if len(digits) > 1:
            out += '.' + digits[1:]
        out += 'e' + ('+' if e >= 0 else '-') + '%02d' % abs(e)
    return sign + out


def _json_escape(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif o < 0x20 or o > 0x7E:
            out.append('\\u%04x' % o)
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def _json_for_hash(data):
    """json.dumps with sort_keys, separators (',', ':') and
    ensure_ascii, over the int to float converted structure."""
    if data is None:
        return 'null'
    if isinstance(data, bool):
        return 'true' if data else 'false'
    if isinstance(data, float):
        return _py_float(data)
    if isinstance(data, (int, long)):
        return str(data)
    if isinstance(data, basestring):
        return _json_escape(data)
    if isinstance(data, (list, tuple)):
        return '[' + ','.join(_json_for_hash(v) for v in data) \
            + ']'
    if isinstance(data, dict):
        parts = []
        for k in sorted(data.keys()):
            parts.append(_json_escape(str(k)) + ':' +
                         _json_for_hash(data[k]))
        return '{' + ','.join(parts) + '}'
    return _json_escape(str(data))


def _rec_int_to_float(data):
    """Artisan util.rec_int_to_float: every int (bools included,
    as in CPython) becomes a float, recursively."""
    if isinstance(data, bool):
        return 1.0 if data else 0.0
    if isinstance(data, (int, long)):
        return float(data)
    if isinstance(data, dict):
        return dict((k, _rec_int_to_float(v))
                    for k, v in data.items())
    if isinstance(data, (list, tuple)):
        return [_rec_int_to_float(v) for v in data]
    return data


def _profile_hash(profile):
    canon = _json_for_hash(_rec_int_to_float(_native(profile)))
    md = java.security.MessageDigest.getInstance('SHA-256')
    md.update(java.lang.String(canon).getBytes('UTF-8'))
    return ''.join('%02x' % (b & 0xff) for b in md.digest())


def _literal(data):
    """A Python literal for the .alog file: pure ASCII, single
    quoted strings, the exact structure ast.literal_eval reads
    back on the Artisan side."""
    if data is None:
        return 'None'
    if isinstance(data, bool):
        return 'True' if data else 'False'
    if isinstance(data, float):
        return _py_float(data)
    if isinstance(data, (int, long)):
        return str(data)
    if isinstance(data, basestring):
        return _literal_str(data)
    if isinstance(data, (list, tuple)):
        return '[' + ', '.join(_literal(v) for v in data) + ']'
    if isinstance(data, dict):
        parts = []
        for k in sorted(data.keys(), key=lambda x: str(x)):
            parts.append(_literal_str(str(k)) + ': ' +
                         _literal(data[k]))
        return '{' + ', '.join(parts) + '}'
    return _literal_str(str(data))


def _literal_str(s):
    quote = "'"
    if "'" in s and '"' not in s:
        quote = '"'
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '\\':
            out.append('\\')
        elif ch == quote:
            out.append('\\' + quote)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif o < 0x20 or o > 0x7E:
            out.append('\\u%04x' % o)
        else:
            out.append(ch)
    return quote + ''.join(out) + quote


def _nearest_index(timex, target):
    best, best_d = 0, None
    for i, v in enumerate(timex):
        d = abs(float(v) - target)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _median_delta(timex):
    ds = [float(timex[i + 1]) - float(timex[i])
          for i in range(len(timex) - 1)
          if float(timex[i + 1]) > float(timex[i])]
    if not ds:
        return 3.0
    ds.sort()
    return ds[len(ds) // 2]


def _series_for(batch):
    ds = batches._run(batches.NQ_SERIES_SELECT,
                      {'batch_number': int(batch['batchNumber'])})
    rows = []
    for r in range(ds.rowCount):
        rows.append({'t': ds.getValueAt(r, 't_offset_sec'),
                     'bt': ds.getValueAt(r, 'bean_temp_f'),
                     'fan': ds.getValueAt(r, 'fan_level'),
                     'heat': ds.getValueAt(r, 'heat_level')})
    rows.sort(key=lambda row: row['t'])
    return rows


def _computed_for(profile, timex, temp1, temp2, ti, mode, doc):
    """Rebuild the derived cache in Artisan's own key shape:
    event times (elapsed since charge, except CHARGE_time which
    is the absolute timex), event BT/ET read from the exported
    arrays, phase times, turning point as the curve minimum
    between charge and dry end, and AUC as the trapezoid area
    above AUCbase from the turning point to drop."""
    c = {}
    t0 = float(timex[ti[0]]) if ti[0] is not None and ti[0] >= 0 \
        else 0.0
    names = ('CHARGE', 'DRY', 'FCs', 'FCe', 'SCs', 'SCe', 'DROP',
             'COOL')
    times = {}
    for slot in range(8):
        idx = ti[slot]
        if idx is None or idx < 0 or idx >= len(timex):
            continue
        if slot > 0 and idx == 0:
            continue
        elapsed = float(timex[idx]) - t0
        times[names[slot]] = elapsed
        c[names[slot] + '_time'] = elapsed if slot > 0 \
            else float(timex[idx])
        if idx < len(temp2) and _proper(temp2[idx]):
            c[names[slot] + '_BT'] = float(temp2[idx])
        if idx < len(temp1) and _proper(temp1[idx]):
            c[names[slot] + '_ET'] = float(temp1[idx])
    if 'DRY' in times and 'CHARGE' in times:
        c['dryphasetime'] = times['DRY']
    if 'FCs' in times and 'DRY' in times:
        c['midphasetime'] = times['FCs'] - times['DRY']
    if 'DROP' in times and 'FCs' in times:
        c['finishphasetime'] = times['DROP'] - times['FCs']
    if 'COOL' in times and 'DROP' in times:
        c['coolphasetime'] = times['COOL'] - times['DROP']
    if 'DROP' in times:
        c['totaltime'] = times['DROP']
    tp_idx = None
    if ti[0] is not None and ti[0] >= 0 and len(ti) > 1 \
            and ti[1] and ti[1] > ti[0]:
        lo, hi = int(ti[0]), int(ti[1])
        best = None
        for i in range(lo, min(hi + 1, len(temp2))):
            if _proper(temp2[i]) and (best is None
                                      or temp2[i] < temp2[best]):
                best = i
        tp_idx = best
    if tp_idx is not None:
        c['TP_idx'] = tp_idx
        c['TP_time'] = float(timex[tp_idx]) - t0
        c['TP_BT'] = float(temp2[tp_idx])
        if tp_idx < len(temp1) and _proper(temp1[tp_idx]):
            c['TP_ET'] = float(temp1[tp_idx])
    base = 212.0 if mode == 'F' else 100.0
    c['AUCbase'] = base
    c['AUCbegin'] = 'TP'
    c['AUCfromeventflag'] = 1
    start = tp_idx if tp_idx is not None else (
        int(ti[0]) if ti[0] is not None and ti[0] >= 0 else 0)
    end = int(ti[6]) if len(ti) > 6 and ti[6] else len(temp2) - 1
    auc = 0.0
    for i in range(start, min(end, len(temp2) - 1)):
        if not (_proper(temp2[i]) and _proper(temp2[i + 1])):
            continue
        dt_min = (float(timex[i + 1]) - float(timex[i])) / 60.0
        if dt_min <= 0:
            continue
        avg = (float(temp2[i]) + float(temp2[i + 1])) / 2.0 - base
        if avg > 0:
            auc += avg * dt_min
    c['AUC'] = int(round(auc))
    meta = doc.get('metadata') or {}
    win = _num(meta.get('ChargeWeightG'))
    wout = _num(meta.get('WeightOutG'))
    if win > 0 and wout > 0:
        c['weightin'] = win
        c['weightout'] = wout
        c['weight_loss'] = (win - wout) * 100.0 / win
        c['total_loss'] = c['weight_loss']
        c['total_yield'] = wout * 100.0 / win
    return c


def batch_to_profile(batch):
    """Rebuild the Artisan profile dict for a stored batch. The
    imported artisan subdocument is carried verbatim wherever the
    batch still matches it; structural keys always come from the
    current document, so editor changes are honored."""
    doc = batch['document']
    sub = doc.get('artisan') or {}
    curves = sub.get('curves') or {}
    sevents = sub.get('events') or {}
    display = sub.get('display') or {}
    settings = sub.get('settings') or {}
    events = doc.get('events') or {}
    meta = doc.get('metadata') or {}

    profile = {}
    for k, v in settings.items():
        if k in ('weightRaw', 'computedImported'):
            continue
        profile[k] = v
    for k, v in display.items():
        if k != 'phasesRaw':
            profile[k] = v
    for k in CURVE_KEYS:
        if k in curves:
            profile[k] = curves[k]
    for k in EVENT_KEYS:
        if k in sevents:
            profile[k] = sevents[k]

    mode = curves.get('mode') or 'F'
    raw_timex = curves.get('timex') or []
    if raw_timex and curves.get('temp2'):
        timex = [float(v) for v in raw_timex]
        temp2 = list(curves['temp2'])
        temp1 = list(curves.get('temp1') or
                     [-1.0] * len(timex))
        ci = curves.get('chargeIndex')
        if ci is None or ci < 0 or ci >= len(timex):
            ci = 0
        t0 = float(timex[ci])
    else:
        rows = _series_for(batch)
        timex = [float(r['t']) for r in rows]
        temp2 = [float(r['bt']) for r in rows]
        temp1 = [-1.0] * len(rows)
        ci = 0
        t0 = 0.0
    profile['mode'] = mode
    profile['timex'] = timex
    profile['temp1'] = temp1
    profile['temp2'] = temp2
    profile['samplinginterval'] = curves.get('samplinginterval') \
        or _median_delta(timex)

    ti = [-1, 0, 0, 0, 0, 0, 0, 0]
    ti[0] = int(ci)
    for slot in range(1, 7):
        ev = events.get(SLOT_DOC[slot])
        if ev and ev.get('t') is not None:
            ti[slot] = _nearest_index(timex, t0 + float(ev['t']))
    cool_sec = sevents.get('coolEndSec')
    if cool_sec is not None:
        ti[7] = _nearest_index(timex, t0 + float(cool_sec))
    profile['timeindex'] = ti

    raw_spec = sevents.get('specialevents') or []
    if raw_spec and raw_timex:
        profile['specialevents'] = list(raw_spec)
        profile['specialeventstype'] = list(
            sevents.get('specialeventstype') or [])
        profile['specialeventsvalue'] = list(
            sevents.get('specialeventsvalue') or [])
        profile['specialeventsStrings'] = list(
            sevents.get('specialeventsStrings') or [])
        if 'etypes' not in profile:
            profile['etypes'] = list(ALT_ETYPES)
    else:
        etypes = list(ALT_ETYPES)
        profile['etypes'] = etypes
        if 'default_etypes' not in profile:
            profile['default_etypes'] = list(DEFAULT_ETYPES)
            profile['default_etypes_set'] = 0
        if 'eventsliderunits' not in profile:
            profile['eventsliderunits'] = ['%', '%', '%', '%']
        spec, stys, svals, sstrs = [], [], [], []
        prev = None
        for entry in (doc.get('fanHeatTrace') or []):
            t = entry.get('t')
            if t is None:
                continue
            idx = _nearest_index(timex, t0 + float(t))
            for name, typ in (('fan', 0), ('heat', 3)):
                lvl = entry.get(name)
                if lvl is None:
                    continue
                if prev is not None and prev.get(name) == lvl \
                        and prev is not entry:
                    continue
                pct = _pct_from_level(lvl)
                spec.append(idx)
                stys.append(typ)
                svals.append(_internal_from_pct(pct))
                sstrs.append('%g%%' % pct)
            prev = entry
        order = sorted(range(len(spec)), key=lambda j: spec[j])
        profile['specialevents'] = [spec[j] for j in order]
        profile['specialeventstype'] = [stys[j] for j in order]
        profile['specialeventsvalue'] = [svals[j] for j in order]
        profile['specialeventsStrings'] = [sstrs[j] for j in order]

    if display.get('phasesRaw'):
        profile['phases'] = list(display['phasesRaw'])
    else:
        dry_t = (events.get('dryEnd') or {}).get('tempF')
        fc_t = (events.get('fcStart') or {}).get('tempF')
        if mode == 'F':
            profile['phases'] = [212, int(round(dry_t)) if dry_t
                                 else 300,
                                 int(round(fc_t)) if fc_t else 390,
                                 450]
        else:
            profile['phases'] = [100, int(round(dry_t)) if dry_t
                                 else 150,
                                 int(round(fc_t)) if fc_t else 200,
                                 230]

    if settings.get('weightRaw'):
        profile['weight'] = list(settings['weightRaw'])
    else:
        profile['weight'] = [_num(meta.get('ChargeWeightG')),
                             _num(meta.get('WeightOutG')), 'g']
    if 'RoasterType' in meta:
        profile['roastertype'] = str(meta.get('RoasterType')
                                      or '')
    if 'RoasterSizeKg' in meta:
        profile['roastersize'] = _num(meta.get('RoasterSizeKg'))
    if 'RoasterHeating' in meta:
        profile['roasterheating'] = int(_num(
            meta.get('RoasterHeating')))
    if 'Organization' in meta:
        profile['organization'] = str(meta.get('Organization')
                                      or '')
    for member, key in DEFECT_FIELDS:
        if member in meta:
            profile[key] = bool(meta.get(member))
    volume_in = _num(meta.get('VolumeInMl'))
    volume_out = _num(meta.get('VolumeOutMl'))
    if volume_in > 0 or volume_out > 0:
        profile['volume'] = [volume_in, volume_out, 'ml']
    if _num(meta.get('DefectsWeightG')) > 0:
        profile['defects_weight'] = _num(
            meta.get('DefectsWeightG'))
    if _num(meta.get('RoastedDensityGL')) > 0 \
            and _num(meta.get('WeightOutG')) > 0 \
            and volume_out > 0:
        profile['density_roasted'] = [
            _num(meta.get('WeightOutG')), 'g', volume_out, 'ml']
    if _num(meta.get('BeanSizeMinMm')) > 0:
        profile['beansize_min'] = str(int(round(
            _num(meta.get('BeanSizeMinMm')))))
    if _num(meta.get('BeanSizeMaxMm')) > 0:
        profile['beansize_max'] = str(int(round(
            _num(meta.get('BeanSizeMaxMm')))))
    if _num(meta.get('WholeColor')) > 0:
        profile['whole_color'] = _num(meta.get('WholeColor'))
    if _num(meta.get('GroundColor')) > 0:
        profile['ground_color'] = _num(meta.get('GroundColor'))
    if meta.get('ColorSystem'):
        profile['color_system'] = meta.get('ColorSystem')
    if _num(meta.get('AmbientTempF')) > 0:
        profile['ambientTemp'] = _from_f(
            meta.get('AmbientTempF'), mode)
    if _num(meta.get('AmbientHumidityPct')) > 0:
        profile['ambient_humidity'] = _num(
            meta.get('AmbientHumidityPct'))
    if _num(meta.get('AmbientPressureHPa')) > 0:
        profile['ambient_pressure'] = _num(
            meta.get('AmbientPressureHPa'))
    if _num(meta.get('RoastedMoisturePct')) > 0:
        profile['moisture_roasted'] = _num(
            meta.get('RoastedMoisturePct'))
    if _num(meta.get('GreensTempF')) > 0:
        profile['greens_temp'] = _from_f(
            meta.get('GreensTempF'), mode)
    if meta.get('Notes'):
        profile['roastingnotes'] = meta.get('Notes')
    if meta.get('CuppingNotes'):
        profile['cuppingnotes'] = meta.get('CuppingNotes')
    profile['beans'] = meta.get('BeanName') or doc.get('beanName') \
        or ''
    identity = sub.get('identity') or {}
    profile['title'] = identity.get('title') or (
        doc.get('beanName') or 'Roastery batch %d'
        % batch['batchNumber'])
    if meta.get('RoastTitle'):
        profile['title'] = meta.get('RoastTitle')
    profile['roastbatchnr'] = int(batch['batchNumber'])
    profile['roastbatchprefix'] = identity.get(
        'roastbatchprefix', '')
    profile['roastbatchpos'] = identity.get('roastbatchpos', 1)
    uuid = identity.get('roastUUID')
    if not uuid:
        uuid = str(java.util.UUID.randomUUID()).replace('-', '')
    profile['roastUUID'] = uuid

    start = batch.get('roastStart')
    if start is not None:
        start_ms = start.getTime()
        rec_ms = start_ms - long(t0 * 1000.0)
        profile['roastepoch'] = int(rec_ms // 1000)
        d = java.util.Date(long(start_ms))
        profile['roastisodate'] = system.date.format(
            d, 'yyyy-MM-dd')
        profile['roasttime'] = system.date.format(d, 'HH:mm:ss')
        profile['roastdate'] = system.date.format(
            d, 'EEE MMM d yyyy')
        tz = java.util.TimeZone.getDefault()
        profile['roasttzoffset'] = int(tz.getOffset(long(start_ms))
                                       // 1000)
    profile['computed'] = _computed_for(profile, timex, temp1,
                                        temp2, ti, mode, doc)

    profile['version'] = ARTISAN_VERSION
    profile['revision'] = ''
    profile['build'] = '0'
    profile['recording_version'] = ARTISAN_VERSION
    profile['recording_revision'] = ''
    profile['recording_build'] = '0'
    profile['artisan_os'] = 'Linux'
    profile['artisan_os_version'] = ''
    profile['artisan_os_arch'] = 'x86_64'
    profile['locale'] = 'en_US'
    profile['viewerMode'] = False
    profile['signature'] = SIGNATURE
    profile['hash'] = _profile_hash(profile)
    return profile


def build_alog_text(batch_number):
    batch = batches.get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.'
                         % batch_number)
    profile = batch_to_profile(batch)
    return 'roastery-batch-%d.alog' % int(batch_number), \
        _literal(_native(profile))


def export_download(self):
    """BatchDetail Export button (thin): download the stored
    batch as an Artisan .alog file."""
    number = system.tag.readBlocking([batches.SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_alog_text(int(number))
    system.perspective.download(filename, text)
'''


def write_library():
    base = os.path.join(PROJ, 'ignition', 'script-python', 'roastery')
    for mod, code in (('core', CORE_CODE), ('batches', BATCHES_CODE),
                      ('artisan', ARTISAN_CODE)):
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
    'roast-title-sm': {'fontSize': '20px', 'fontWeight': '700',
                       'color': 'var(--label)'},
    'roast-subtitle': {'fontSize': '12px', 'color': 'var(--neutral-70)'},
    'roast-card': {'backgroundColor': 'var(--container)',
                   'borderRadius': 'var(--roast-radius-card)',
                   'boxShadow': 'var(--boxShadow2)',
                   'padding': '16px'},
    'roast-card-sm': {'backgroundColor': 'var(--container)',
                      'borderRadius': 'var(--roast-radius-card)',
                      'boxShadow': 'var(--boxShadow2)',
                      'padding': '12px 16px',
                      'overflow': 'hidden'},
    'roast-cell': {'backgroundColor': 'var(--containerNested)',
                   'borderRadius': 'var(--roast-radius-small)',
                   'padding': '8px 6px',
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
                       'color': 'var(--label)', 'lineHeight': '1.05',
                       'fontVariantNumeric': 'tabular-nums'},
    'roast-value-md': {'fontSize': '20px', 'fontWeight': '700',
                       'color': 'var(--label)', 'lineHeight': '1.1',
                       'fontVariantNumeric': 'tabular-nums'},
    'roast-clock': {'fontSize': '27px', 'fontWeight': '700',
                    'color': 'var(--label)', 'fontFamily': 'monospace'},
    'roast-chip': {'fontSize': '13px', 'fontWeight': '600',
                   'color': 'var(--label)',
                   'whiteSpace': 'nowrap', 'overflow': 'hidden',
                   'textOverflow': 'ellipsis'},
    'roast-pill': {'fontSize': '12px', 'fontWeight': '700',
                   'color': '#ffffff', 'padding': '4px 14px',
                   'borderRadius': '999px', 'textAlign': 'center'},
    'roast-chart': {'backgroundColor': 'transparent'},
    'roast-hidden': {'display': 'none'},
    'roast-mode-pill': {'fontSize': '11px', 'fontWeight': '700',
                        'color': '#ffffff', 'padding': '3px 12px',
                        'borderRadius': '999px'},
    'roast-note': {'fontSize': '13px', 'color': 'var(--neutral-70)'},
    'roast-note-sm': {'fontSize': '11px', 'color': 'var(--neutral-60)'},
    'roast-note-success': {'fontSize': '13px', 'fontWeight': '700',
                           'color': 'var(--success)',
                           'minHeight': '18px'},
    'roast-banner': {'backgroundColor': '#991b1b',
                     'padding': '8px 16px'},
    'roast-banner-text': {'fontSize': '14px', 'fontWeight': '700',
                          'color': '#ffffff'},
    'roast-btn': {'fontSize': '14px', 'fontWeight': '700',
                  'color': '#ffffff',
                  'borderRadius': 'var(--roast-radius-interactive)',
                  'padding': '10px 18px', 'cursor': 'pointer'},
    'roast-btn-sm': {'fontSize': '12px', 'fontWeight': '700',
                     'borderRadius': 'var(--roast-radius-interactive)',
                     'padding': '6px 12px',
                     'cursor': 'pointer'},
    'roast-btn-ghost': {'backgroundColor': 'transparent',
                        'color': 'var(--label)'},
    'roast-btn-primary': {'backgroundColor': '#0c7bb3'},
    'roast-btn-green': {'backgroundColor': '#16a34a'},
    'roast-btn-purple': {'backgroundColor': '#7c3aed'},
    'roast-btn-event': {'fontSize': '13px', 'padding': '10px 6px'},
    'roast-btn-charge': {'backgroundColor': '#dc2626'},
    'roast-btn-blue': {'backgroundColor': '#0c7bb3'},
    'roast-btn-sc': {'backgroundColor': '#2563eb'},
    'roast-btn-drop': {'backgroundColor': '#334155'},
    'roast-btn-cool': {'backgroundColor': '#0284c7'},
    'roast-btn-reset': {'backgroundColor': '#6b7280'},
    'roast-btn-step': {'fontSize': '16px', 'padding': '6px 14px'},
    'roast-input': {'borderRadius': 'var(--roast-radius-interactive)',
                    'padding': '8px 10px',
                    'fontSize': '14px', 'color': 'var(--label)',
                    'backgroundColor': 'var(--input)'},
    'roast-checkbox': {'color': 'var(--label)'},
    'roast-table': {'fontSize': '13px', 'color': 'var(--label)',
                    'backgroundColor': 'var(--container)'},
    'roast-accent-bar': {
        'borderRadius': 'var(--roast-radius-micro)'},
    'roast-seg': {'borderRadius': 'var(--roast-radius-interactive)',
                  'padding': '8px 4px'},
    'roast-seg-drying': {'backgroundColor': '#0284c7'},
    'roast-seg-maillard': {'backgroundColor': '#2563eb'},
    'roast-seg-development': {'backgroundColor': '#1e40af'},
    'roast-seg-text': {'fontSize': '12px', 'fontWeight': '700',
                       'color': '#ffffff', 'textAlign': 'center',
                       'whiteSpace': 'nowrap', 'overflow': 'hidden'},
    'roast-seg-detail': {'fontSize': '11px', 'fontWeight': '400',
                         'color': 'rgba(255,255,255,0.88)',
                         'textAlign': 'center',
                         'whiteSpace': 'nowrap', 'overflow': 'hidden'},
    'roast-event-name': {'fontSize': '11px', 'fontWeight': '700',
                         'textTransform': 'uppercase',
                         'letterSpacing': '0.08em',
                         'textAlign': 'center'},
    'roast-event-time': {'fontSize': '16px', 'fontWeight': '700',
                         'color': 'var(--label)', 'textAlign': 'center'},
    'roast-event-temp': {'fontSize': '12px', 'fontWeight': '600',
                         'color': 'var(--neutral-70)',
                         'textAlign': 'center'},
    'roast-form-caption': {'fontSize': '11px', 'fontWeight': '700',
                           'color': 'var(--neutral-70)',
                           'textTransform': 'uppercase',
                           'letterSpacing': '0.06em'},
    'roast-section-div': {'paddingTop': '12px', 'gap': '8px'},
    'roast-scroll': {'backgroundColor': 'var(--containerRoot)',
                     'padding': '20px', 'gap': '16px',
                     'height': '100%', 'overflowY': 'auto'},
    'roast-content': {'padding': '16px 20px', 'gap': '12px'},
    'roast-status': {'fontSize': '12px', 'fontWeight': '700'},
    'roast-alarm-cap': {'fontSize': '13px', 'fontWeight': '700',
                        'color': 'var(--label)'},
    'roast-accent-text': {'fontSize': '13px', 'fontWeight': '700',
                          'color': 'var(--callToAction)'},
    'roast-stepper-value': {'fontSize': '26px', 'fontWeight': '700',
                            'color': 'var(--label)',
                            'textAlign': 'center'},
    'roast-unit': {'fontSize': '12px', 'fontWeight': '600',
                   'color': 'var(--neutral-70)'},
    'roast-value-right': {'fontSize': '14px', 'fontWeight': '700',
                          'color': 'var(--label)', 'textAlign': 'right'},
    'roast-full': {'width': '100%'},
    'roast-gap-8': {'gap': '8px'},
    'roast-gap-10': {'gap': '10px'},
    'roast-gap-12': {'gap': '12px'},
    'roast-tabbar': {'backgroundColor': 'var(--container)',
                     'padding': '6px 100px 6px 10px', 'gap': '8px'},
    'roast-tab-btn': {'fontSize': '15px', 'fontWeight': '700',
                      'borderRadius': 'var(--roast-radius-interactive)',
                      'padding': '10px 8px',
                      'cursor': 'pointer', 'color': 'var(--label)',
                      'backgroundColor': 'transparent'},
    'roast-hud': {'backgroundColor': 'var(--container)',
                  'padding': '5px 6px', 'gap': '4px'},
    'roast-hud-field': {'paddingLeft': '8px'},
    'roast-hud-value': {'fontSize': '16px', 'fontWeight': '700',
                        'color': 'var(--label)',
                        'fontFamily': 'monospace',
                        'whiteSpace': 'nowrap', 'overflow': 'hidden',
                        'textOverflow': 'ellipsis'},
    'roast-hud-value-phase': {'fontSize': '12px',
                        'fontWeight': '700',
                        'color': 'var(--label)',
                        'fontFamily': 'monospace',
                        'whiteSpace': 'nowrap', 'overflow': 'hidden',
                        'textOverflow': 'ellipsis'},
    'roast-hud-cap': {'fontSize': '10px', 'fontWeight': '700',
                      'color': 'var(--neutral-60)',
                      'textTransform': 'uppercase',
                      'letterSpacing': '0.08em'},
    'roast-controldock': {'backgroundColor': 'var(--container)',
                               'padding': '8px 10px', 'gap': '8px',
                          'boxShadow': '0 -4px 12px rgba(0,0,0,0.12)'},
    'roast-btn-lg': {'fontSize': '15px', 'padding': '13px 8px',
                     'minHeight': '52px'},
    'roast-btn-step-lg': {'fontSize': '21px', 'padding': '8px 16px',
                          'minWidth': '58px', 'minHeight': '52px'},
    'roast-fillscroll': {'height': '100%', 'overflowY': 'auto'},
    'roast-scrollcol': {'overflowY': 'auto', 'minHeight': '0px'},
    'roast-dock-editor': {'backgroundColor': 'var(--containerRoot)',
                          'padding': '18px 20px', 'gap': '12px',
                          'height': '100%', 'overflowY': 'auto'},
    'roast-section-desc': {'fontSize': '12.5px',
                           'color': 'var(--neutral-70)',
                           'lineHeight': '1.45'},
    'roast-kv-cap': {'fontSize': '11px', 'fontWeight': '700',
                     'color': 'var(--neutral-60)',
                     'textTransform': 'uppercase',
                     'letterSpacing': '0.08em'},
    'roast-table-sm': {'fontSize': '12.5px', 'color': 'var(--label)',
                       'backgroundColor': 'var(--container)'},
    'roast-h100': {'height': '100%'},
    'roast-stats-line': {'fontSize': '11px', 'fontWeight': '600',
                         'color': 'var(--neutral-70)',
                         'whiteSpace': 'nowrap',
                         'overflow': 'hidden',
                         'textOverflow': 'ellipsis'},
}

STYLESHEET_CSS = """/* Roastery advanced stylesheet.
   Perspective prefixes every style class with psc- in the DOM, so
   global rules target .psc-<classname>. Theme colors come from the
   built in session theme CSS variables; nothing here hard codes a
   surface color, so dark and light sessions both hold. */

/* Design tokens (v4.2 style system audit). The radius scale is
   defined ONCE here; style classes reference the variables, so
   a global radius change is a one line edit in this file. */
:root {
  --roast-radius-micro: 2px;
  --roast-radius-interactive: 4px;
  --roast-radius-small: 6px;
  --roast-radius-card: 8px;
}

/* Borders. The style class compiler in this build drops
   border properties from class definitions (proven by the
   compiled rules: every border key vanished and computed
   borders measured 0px), so borders live here, keyed to the
   same class names. One border color everywhere: the theme
   border variable. */
.psc-roast-card, .psc-roast-card-sm, .psc-roast-cell {
  border: 1px solid var(--border); }
.psc-roast-input { border: 1px solid var(--border); }
.psc-roast-btn-ghost { border: 1px solid var(--border); }
.psc-roast-tabbar { border-top: 1px solid var(--border); }
.psc-roast-controldock { border-top: 1px solid var(--border); }
.psc-roast-hud { border-bottom: 1px solid var(--border); }
.psc-roast-hud-field { border-left: 1px solid var(--border); }
.psc-roast-section-div { border-top: 1px solid var(--border); }

/* Display. The compiler drops display from class definitions
   too (proven 2026-11-13: .psc-roast-hidden compiled to an
   empty rule and the delete confirm row it was meant to hide
   rendered unconditionally), so the hidden utility lives
   here, keyed to the same class name. */
.psc-roast-hidden { display: none !important; }

/* Statistics summary line (Tier 3 item 19): single line, never
   wraps, truncates with an ellipsis instead of pushing the
   layout at 360px (the class compiler carries these text
   properties, and the rule here makes the intent explicit). */
.psc-roast-stats-line { white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }

/* Phase bar segments size by percentage widths that must sum
   to the bar. Two sizing traps, both proven at 360px on
   2026-11-13: content-box sizing added the segments' padding
   (24px) on top of the percentages, and a flex item's
   automatic minimum size (its content, here the single word
   DEVELOPMENT at about 88px) refused to shrink to a 67px
   target share, so the Development segment ran off the card
   with its centered name clipped on both sides. Border-box
   plus an explicit min-width of 0 keeps the percentages
   honest; the segment text classes clip inside the segment. */
.psc-roast-seg { box-sizing: border-box; min-width: 0;
  overflow: hidden; }

/* Button feedback that a static style class cannot express. */
.psc-roast-btn:hover { filter: brightness(1.15); }
.psc-roast-btn:active { filter: brightness(0.9); }

/* Keyboard focus stays visible on form inputs. */
.psc-roast-input:focus { outline: 2px solid var(--callToAction); }

/* Slim scrollbar for the popup scroll areas. */
.psc-roast-scroll::-webkit-scrollbar { width: 10px; }
.psc-roast-scroll::-webkit-scrollbar-thumb {
  background: var(--neutral-60);
  border-radius: var(--roast-radius-interactive); }

/* ---- v4 shell rules ------------------------------------------
   The shared top dock is the mobile HUD: hide it on desktop
   widths (the breakpoint container switches layouts at 900px,
   the same threshold). On mobile widths it is a fixed cover
   dock, so page roots carry top padding to clear it. */
@media (min-width: 900px) {
  .docked-view-top { display: none !important; }
}
@media (max-width: 899.98px) {
  .psc-roast-app { padding-top: 70px; }
}

/* Touch targets: every roast button is at least 44px tall. */
.psc-roast-btn { min-height: 44px; }
.psc-roast-tab-btn { min-height: 48px; }
.psc-roast-tab-btn:hover { background: var(--containerNested); }

/* ---- v4.1 declutter (Eric's phone, 360px) ---------------------
   Flex children may shrink below their content width inside a
   roast-flexmin row (the tiles row bled past the right edge of
   a 360px phone because tiles refused to shrink). */
.psc-roast-flexmin > * { min-width: 0; }

/* Tab bar compaction under 560px: at 360px the theme button's
   fixed 88px plus three growing tabs left about 46px per tab,
   clipping 'Settings' to 'Setting'. Smaller type, tighter
   padding, a narrower theme button and less nub clearance. */
@media (max-width: 560px) {
  /* Perspective emits style class props as element styles, so
     these overrides need !important to win the cascade (proven
     live: without it the padding and font size rules silently
     lost to the class definitions). */
  .psc-roast-tabbar { padding: 6px 60px 6px 6px !important;
    gap: 6px !important; }
  .psc-roast-tabbar > * { min-width: 0; }
  .psc-roast-tabbar > *:first-child { flex: 0 0 46px !important; }
  .psc-roast-tab-btn { font-size: 12px !important;
    padding: 8px 1px !important;
    white-space: nowrap; overflow: hidden; }
}

/* ---- polish round 2: phone column sets (HUNT-13) ------------
   The three wide tables (Log, Alarms, Phase Analysis) ship in
   two instances: the full set carries roast-cols-full and a
   phone wrapper carries roast-cols-phone with a reduced set
   plus a toggle that swaps in the full set. The stylesheet
   picks the instance by viewport width, the same breakpoint
   pattern as the HUD dock above: below 900px the phone
   wrapper shows, at 900px and up the full table shows and
   the wrapper is gone, so desktop layouts are unchanged. */
@media (max-width: 899.98px) {
  .psc-roast-cols-full { display: none !important; }
}
@media (min-width: 900px) {
  .psc-roast-cols-phone { display: none !important; }
}

/* ---- polish round 2: phone headers (HUNT-14, HUNT-15) -------
   LogPage: the title column takes the full first row at phone
   widths, so the subtitle stops squeezing into a roughly
   100px column and the header actions wrap onto their own
   row under the title. BatchDetail: the Back button keeps
   one line (fixed 118px basis in the view, nowrap here) and
   the six action buttons share two even rows of three
   instead of wrapping ad hoc into three rows. */
@media (max-width: 560px) {
  .psc-roast-log-headcol { flex: 1 1 100% !important; }
  .psc-roast-back-btn { white-space: nowrap; }
  .psc-roast-detail-actions > * { flex: 1 1 28% !important;
    white-space: nowrap; }
  /* With the Back button at its full one line width the
     detail subtitle wraps to two lines at 360px; the head
     row's fixed 76px basis would clip the second line under
     the action row, so the row sizes to its content here. */
  .psc-roast-detail-head { flex-basis: auto !important; }
}
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
    if wtype == 'checkbox':
        # HUNT-18: the template's checkbox option carries the
        # component default text ('text'), which a checkbox
        # field renders next to the box. Clear it, the same
        # fix the standalone checkboxes got in HUNT-11.
        for _o in w.get('checkbox', {}).get('options', []):
            _o['text'] = ''
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

def extra_meta_rows():
    """Roast Properties rows (Tier 1 item 3): the Artisan
    profile fields beyond the original sixteen, shared by the
    Config metadata form and the slide over batch editor so
    both carry the full property set. Defect flags are form
    checkboxes; their values ride the form payload as booleans
    and roastery.core.coerce keeps them boolean."""
    return [
        f_row([f_widget('PropsHeader', 'none', 'Roast Properties',
                        tpl=HEADER_TPL)]),
        f_row([f_text('RoastTitle', 'Roast title'),
               f_text('RoasterType', 'Roaster type')]),
        f_row([f_number('RoasterSizeKg', 'Roaster size (kg)', 0, 100),
               f_number('RoasterHeating', 'Roaster heating', 0, 99)]),
        f_row([f_text('Organization', 'Organization'),
               f_text('ColorSystem', 'Color system')]),
        f_row([f_number('VolumeInMl', 'Volume in (ml)', 0, 100000),
               f_number('VolumeOutMl', 'Volume out (ml)', 0, 100000)]),
        f_row([f_number('DefectsWeightG', 'Defects weight (g)',
                        0, 5000),
               f_number('RoastedDensityGL', 'Roasted density (g/L)',
                        0, 2000)]),
        f_row([f_number('BeanSizeMinMm', 'Bean size min (mm)', 0, 30),
               f_number('BeanSizeMaxMm', 'Bean size max (mm)', 0, 30)]),
        f_row([f_number('WholeColor', 'Whole bean color', 0, 150),
               f_number('GroundColor', 'Ground color', 0, 150)]),
        f_row([f_number('AmbientTempF', 'Ambient temp (F)', -50, 140),
               f_number('AmbientHumidityPct', 'Ambient humidity (%)',
                        0, 100)]),
        f_row([f_number('AmbientPressureHPa',
                        'Ambient pressure (hPa)', 0, 2000),
               f_number('RoastedMoisturePct', 'Roasted moisture (%)',
                        0, 100)]),
        f_row([f_number('GreensTempF', 'Greens temp (F)', -50, 140)]),
        f_row([f_widget('CuppingNotes', 'text-area', 'Cupping notes')]),
        f_row([f_widget('DefectHeavyFC', 'checkbox', 'Heavy FC'),
               f_widget('DefectLowFC', 'checkbox', 'Low FC'),
               f_widget('DefectLightCut', 'checkbox', 'Light cut')]),
        f_row([f_widget('DefectDarkCut', 'checkbox', 'Dark cut'),
               f_widget('DefectDrops', 'checkbox', 'Drops'),
               f_widget('DefectOily', 'checkbox', 'Oily')]),
        f_row([f_widget('DefectUneven', 'checkbox', 'Uneven'),
               f_widget('DefectTipping', 'checkbox', 'Tipping'),
               f_widget('DefectScorching', 'checkbox', 'Scorching')]),
        f_row([f_widget('DefectDivots', 'checkbox', 'Divots')]),
    ]

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
    rows += extra_meta_rows()
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
                  position={'grow': 1, 'shrink': 1, 'basis': '0px'},
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.params.valueText')},
                      'props.style.classes': {'binding': prop_binding(
                          'view.params.valueClass')}})
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
                   'accent': '#0c7bb3', 'valueClass': 'roast-value-lg'},
        'propConfig': {
            'params.title': {'paramDirection': 'input'},
            'params.valueText': {'paramDirection': 'input'},
            'params.unit': {'paramDirection': 'input'},
            'params.accent': {'paramDirection': 'input'},
            'params.valueClass': {'paramDirection': 'input'}},
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
    """Phase bar. Segment widths are always the Settings phase
    duration targets (PhaseDryTargetSec, PhaseMaillardTargetSec,
    PhaseDevTargetSec) as proportions, so adjusting a target in
    Settings visibly rebalances the bar, and the geometry never
    moves during a roast (stability pass; the widths used to
    recompute to actual shares at Drop). Segment text carries
    the actual durations and shares. The DTR label shows the
    actual DTR after drop, else the DTRTargetPct target."""
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))
    drop_e = ref(T('DropElapsedSec'))
    # Effective targets (Tier 3 item 16): when phases from
    # background is on and a ghost with ordered stamped events
    # is staged (BgPhase tags, staged by the library when the
    # ghost loads), the bar proportions and target labels come
    # from the GHOST phase durations. The saved target tags are
    # never overwritten; turning the option off, or clearing
    # the ghost, returns the bar to the saved targets.
    bg_dry = ref(T('BgPhaseDrySec'))
    bg_fc = ref(T('BgPhaseFcSec'))
    bg_drop = ref(T('BgPhaseDropSec'))
    use_bg = (f"({ref(T('PhaseFromBg'))} && {bg_dry} > 0 && "
              f"{bg_fc} > {bg_dry} && {bg_drop} > {bg_fc})")
    td = f"if({use_bg}, {bg_dry}, {ref(T('PhaseDryTargetSec'))})"
    tm = (f"if({use_bg}, ({bg_fc} - {bg_dry}), "
          f"{ref(T('PhaseMaillardTargetSec'))})")
    tv = (f"if({use_bg}, ({bg_drop} - {bg_fc}), "
          f"{ref(T('PhaseDevTargetSec'))})")
    dtr_t = (f"if({use_bg}, ({bg_drop} - {bg_fc}) * 100.0 / "
             f"{bg_drop}, {ref(T('DTRTargetPct'))})")
    tt = f"({td} + {tm} + {tv})"
    # Stability pass: segment widths are ALWAYS the target
    # proportions. They used to recompute to the actual phase
    # shares at Drop, visibly rebalancing the whole bar at the
    # exact moment Eric is watching it (Maillard collapsed to
    # 8px in a no-FC test drop). The actuals live in the segment
    # text; the geometry is the plan.
    tt_safe = f"if({tt} > 0, {tt}, 1)"
    dry_w = f"{td} * 100.0 / {tt_safe}"
    mai_w = f"{tm} * 100.0 / {tt_safe}"
    dev_w = f"{tv} * 100.0 / {tt_safe}"
    dry_pct = f"if({drop_e} > 0, {dry_e} * 100.0 / {drop_e}, {dry_w})"
    mai_pct = (f"if({drop_e} > 0, ({fc_e} - {dry_e}) * 100.0 / "
               f"{drop_e}, {mai_w})")
    dev_pct = (f"if({drop_e} > 0, ({drop_e} - {fc_e}) * 100.0 / "
               f"{drop_e}, {dev_w})")

    def seg(name, caption, color_class, width_expr, text_expr):
        # Two stacked lines (no overlap pass, 2026-11-13): the
        # name on its own line, the time and share beneath it.
        # The old single line ('DEVELOPMENT 01:05 - 43%') needs
        # about 150px; a target proportion segment at 360px is
        # about 108px, so the name truncated ('DEVELOPI...').
        # Stacked, the widest line is the name at 12px (about
        # 80px) and every segment reads at every width.
        nm = label(name + 'Text', caption, 'roast-seg-text')
        dt = label(name + 'Detail', '', 'roast-seg-detail',
                   prop_config={'props.text': {'binding': expr_binding(
                       text_expr)}})
        inner = flex(name + 'Stack', 'column', [nm, dt],
                     align='center', justify='center')
        # Segment width is a binding driven layout value: the one
        # inline style a class cannot express (documented exception).
        return flex(name, 'row', [inner], justify='center',
                    align='center',
                    classes='roast-seg ' + color_class,
                    prop_config={'props.style.width': {'binding':
                        expr_binding(f"numberFormat({width_expr}, '0.0') + '%'")}})

    dry_t = (f"if({dry_e} >= 0, {mmss_int(dry_e)} + ' · ' + "
             f"numberFormat({dry_pct}, '0') + '%', 'target ' + {mmss_int(td)})")
    mai_t = (f"if({fc_e} >= 0, "
             f"{mmss_int(f'({fc_e} - {dry_e})')} + ' · ' + "
             f"numberFormat({mai_pct}, '0') + '%', 'target ' + "
             f"{mmss_int(tm)})")
    dev_t = (f"if({drop_e} >= 0, "
             f"{mmss_int(f'({drop_e} - {fc_e})')} + ' · ' + "
             f"numberFormat({dev_pct}, '0') + '%', 'target ' + "
             f"{mmss_int(tv)})")
    # No gap between segments (no overlap pass, 2026-11-13):
    # the widths are percentages summing to 100, so the old
    # 8px gaps pushed the bar 16px past its card and the
    # Development segment clipped at the right edge on the
    # phone. The bar is contiguous, Artisan style; the segment
    # colors and corner radius carry the separation.
    bar = flex('Bar', 'row', [
        seg('DrySeg', 'DRYING', 'roast-seg-drying', dry_w, dry_t),
        seg('MaiSeg', 'MAILLARD', 'roast-seg-maillard', mai_w, mai_t),
        # The third caption is DEV, not DEVELOPMENT (no overlap
        # pass): at target proportions the development segment
        # is about 68px wide on a phone and the full word needs
        # about 88px at 12px, so it clipped mid word no matter
        # how the box was sized. DEV is the working abbreviation
        # (same root as DTR beside the bar); the full word
        # lives in the HUD phase field, the summary, and
        # Settings, where it has room.
        seg('DevSeg', 'DEV', 'roast-seg-development', dev_w, dev_t)],
        classes='roast-full')
    heading = label('Heading', 'Phases', 'roast-section-title')
    dtr = label('DtrLabel', 'DTR', 'roast-accent-text',
                prop_config={'props.text': {'binding': expr_binding(
                    f"if({drop_e} >= 0, 'DTR ' + numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', "
                    f"'DTR target ' + numberFormat({dtr_t}, '0.0') + '%')")}})
    head = flex('HeadRow', 'row', [heading, dtr],
                justify='space-between', align='center')
    root = flex('root', 'column', [head, bar],
                classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 108}},
            'root': root}

# ================================================================ Controls

def _st_expr():
    return ref(T('State'))


def _ev_expr(stem):
    return ref(T(stem + 'ElapsedSec'))


def ev_btn(name, text, color_class, enabled_expr, call,
           classes='roast-btn roast-btn-event', basis='104px'):
    return button(name, text, classes + ' ' + color_class,
                  position={'grow': 1, 'shrink': 1, 'basis': basis},
                  prop_config={'props.enabled': {'binding': expr_binding(
                      enabled_expr)}},
                  events=lib_event(call))


def primary_event_buttons(prefix, big=False):
    """The primary roast flow, in sequence: Charge, Dry End,
    FC Start, Drop. Shared by the desktop Controls rail and the
    mobile control dock so the flow reads identically everywhere."""
    st = _st_expr()
    roasting = f"{st} = 'Roasting'"
    cls = 'roast-btn roast-btn-lg' if big else 'roast-btn roast-btn-event'
    basis = '0px' if big else '104px'
    return [
        ev_btn(prefix + 'ChargeButton', 'Charge', 'roast-btn-charge',
               f"{st} = 'Idle' || {st} = 'Complete'",
               'roastery.core.charge()', cls, basis),
        ev_btn(prefix + 'DryEndButton', 'Dry End', 'roast-btn-blue',
               f"{roasting} && {_ev_expr('DryEnd')} < 0",
               "roastery.core.stamp_event('DryEnd', 'Dry End')",
               cls, basis),
        ev_btn(prefix + 'FCStartButton', 'FC Start', 'roast-btn-blue',
               f"{roasting} && {_ev_expr('DryEnd')} >= 0 && {_ev_expr('FirstCrackStart')} < 0",
               "roastery.core.stamp_event('FirstCrackStart', 'First Crack Start')",
               cls, basis),
        ev_btn(prefix + 'DropButton', 'Drop', 'roast-btn-drop',
               f"{roasting} && {_ev_expr('Drop')} < 0",
               'roastery.core.drop()', cls, basis)]


def stepper_big(name, caption, member, color_class):
    """Fan / Heat stepper with 52px touch targets (dock + rail)."""
    val = label(name + 'Value', '5', 'roast-stepper-value',
                position={'grow': 0, 'shrink': 0, 'basis': '44px'},
                prop_config={'props.text': {'binding': fmt_tag(
                    T(member), '0')}})
    minus = button(name + 'Minus', '-',
                   'roast-btn roast-btn-step-lg roast-btn-reset',
                   events=lib_event(
                       f"roastery.core.stepper('{member}', -1, '{caption}')"))
    plus = button(name + 'Plus', '+',
                  'roast-btn roast-btn-step-lg ' + color_class,
                  events=lib_event(
                      f"roastery.core.stepper('{member}', 1, '{caption}')"))
    cap = label(name + 'Caption', caption.upper(), 'roast-caption')
    inner = flex(name + 'Row', 'row', [minus, val, plus],
                 align='center', justify='center', classes='roast-gap-8')
    return flex(name, 'column', [cap, inner], align='center',
                classes='roast-gap-8',
                position={'grow': 1, 'shrink': 1, 'basis': '150px'})


def controls_view():
    """Desktop control rail: primary flow prominent and in
    sequence, secondary events grouped and subordinate, big
    steppers, then session actions."""
    st = _st_expr()
    roasting = f"{st} = 'Roasting'"
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
    primary_cap = label('PrimaryCap', 'Primary flow', 'roast-caption')
    primary = flex('PrimaryRow', 'row', primary_event_buttons(''),
                   wrap='wrap', classes='roast-gap-8')
    for b in primary['children']:
        b['position'] = {'grow': 1, 'shrink': 1, 'basis': '46%'}
    secondary_cap = label('SecondaryCap', 'More events', 'roast-caption')
    secondary = flex('SecondaryRow', 'row', [
        ev_btn('FCEndButton', 'FC End', 'roast-btn-blue',
               f"{roasting} && {_ev_expr('FirstCrackStart')} >= 0 && {_ev_expr('FirstCrackEnd')} < 0",
               "roastery.core.stamp_event('FirstCrackEnd', 'First Crack End')"),
        ev_btn('SCStartButton', 'SC Start', 'roast-btn-sc',
               f"{roasting} && {_ev_expr('FirstCrackStart')} >= 0 && {_ev_expr('SecondCrackStart')} < 0",
               "roastery.core.stamp_event('SecondCrackStart', 'Second Crack Start')"),
        ev_btn('SCEndButton', 'SC End', 'roast-btn-sc',
               f"{roasting} && {_ev_expr('SecondCrackStart')} >= 0 && {_ev_expr('SecondCrackEnd')} < 0",
               "roastery.core.stamp_event('SecondCrackEnd', 'Second Crack End')")],
        wrap='wrap', classes='roast-gap-8')
    customs = flex('CustomRow', 'row', [
        ev_btn(f'CustomButton{i}', f'Custom {i}', 'roast-btn-purple',
               roasting, f'roastery.core.stamp_custom({i})')
        for i in (1, 2, 3, 4)],
        wrap='wrap', classes='roast-gap-8')
    for i, comp in enumerate(customs['children'], start=1):
        comp['propConfig']['props.text'] = {'binding': tag_binding(
            T(f'CustomEvent{i}Name'))}
    steppers = flex('Steppers', 'row', [
        stepper_big('FanStepper', 'Fan', 'FanLevel', 'roast-btn-blue'),
        stepper_big('HeatStepper', 'Heat', 'HeatLevel',
                    'roast-btn-charge')],
        wrap='wrap', classes='roast-gap-12')
    actions = flex('ActionRow', 'row', [
        ev_btn('CoolButton', 'Cool', 'roast-btn-cool',
               f"{st} = 'Dropped'", 'roastery.core.cool()'),
        ev_btn('FinishButton', 'Finish', 'roast-btn-green',
               f"{st} = 'Cooling'", 'roastery.core.finish()'),
        ev_btn('ResetButton', 'Reset', 'roast-btn-reset',
               f"{st} != 'Idle'", 'roastery.core.reset_batch()'),
        ev_btn('NewRoastButton', 'New Roast', 'roast-btn-primary',
               f"{st} != 'Roasting'", 'roastery.batches.new_roast(self)')],
        wrap='wrap', classes='roast-gap-8')
    root = flex('root', 'column',
                [head, primary_cap, primary, secondary_cap, secondary,
                 customs, steppers, actions],
                classes='roast-card roast-gap-10')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 560, 'height': 470}},
            'root': root}

# ================================================================ MetaCard

def meta_card_view():
    heading = label('Heading', 'Batch Metadata', 'roast-section-title')
    edit_btn = button('EditButton', 'Edit',
                      'roast-btn roast-btn-sm roast-btn-primary',
                      events=script_event(
                          "\tsystem.perspective.navigate(page='/settings')\n"))
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
        line('DefLoss', 'Defects loss',
             f"if({ref(T('WeightOutG'))} > 0 && {ref(T('DefectsWeightG'))} > 0 && {ref(T('DefectsWeightG'))} < {ref(T('WeightOutG'))}, numberFormat({ref(T('DefectsWeightG'))} * 100.0 / {ref(T('WeightOutG'))}, '0.0') + '%', '--')"),
        line('TotLoss', 'Total loss',
             f"if({ref(T('ChargeWeightG'))} > 0 && {ref(T('WeightOutG'))} > 0, numberFormat(({ref(T('ChargeWeightG'))} - ({ref(T('WeightOutG'))} - {ref(T('DefectsWeightG'))})) * 100.0 / {ref(T('ChargeWeightG'))}, '0.0') + '%', '--')"),
        line('Yield', 'Total yield',
             f"if({ref(T('ChargeWeightG'))} > 0 && {ref(T('WeightOutG'))} > 0, numberFormat(({ref(T('WeightOutG'))} - {ref(T('DefectsWeightG'))}) * 100.0 / {ref(T('ChargeWeightG'))}, '0.0') + '%', '--')"),
        line('VolGain', 'Volume gain',
             f"if({ref(T('VolumeInMl'))} > 0 && {ref(T('VolumeOutMl'))} >= {ref(T('VolumeInMl'))}, numberFormat(({ref(T('VolumeOutMl'))} - {ref(T('VolumeInMl'))}) * 100.0 / {ref(T('VolumeInMl'))}, '0.0') + '%', '--')"),
        line('MoistLoss', 'Moisture loss',
             f"if({ref(T('MoisturePct'))} > 0 && {ref(T('RoastedMoisturePct'))} > 0, numberFormat({ref(T('MoisturePct'))} - {ref(T('RoastedMoisturePct'))}, '0.0') + '%', '--')"),
        line('OrgLoss', 'Organic loss',
             f"if({ref(T('MoisturePct'))} > 0 && {ref(T('RoastedMoisturePct'))} > 0 && {ref(T('WeightOutG'))} > 0 && {ref(T('ChargeWeightG'))} > 0, numberFormat(({ref(T('ChargeWeightG'))} - {ref(T('WeightOutG'))}) * 100.0 / {ref(T('ChargeWeightG'))} - ({ref(T('MoisturePct'))} - {ref(T('RoastedMoisturePct'))}), '0.0') + '%', '--')"),
        line('GreenDens', 'Green density',
             f"if({ref(T('ChargeWeightG'))} > 0 && {ref(T('VolumeInMl'))} > 0, numberFormat({ref(T('ChargeWeightG'))} * 1000.0 / {ref(T('VolumeInMl'))}, '0') + ' g/L', '--')"),
        line('RoastDens', 'Roasted density',
             f"if({ref(T('WeightOutG'))} > 0 && {ref(T('VolumeOutMl'))} > 0, numberFormat({ref(T('WeightOutG'))} * 1000.0 / {ref(T('VolumeOutMl'))}, '0') + ' g/L', '--')"),
        line('BgDev', 'Deviation vs background',
             f"{ref(T('BgDeviationText'))}"),
        line('Auc', 'AUC (F min)',
             f"if({ref(T('AucLiveFMin'))} > 0, numberFormat({ref(T('AucLiveFMin'))}, '0'), '--')"),
        line('AucFc', 'AUC since FC (F min)',
             f"if({ref(T('AucSinceFcFMin'))} > 0, numberFormat({ref(T('AucSinceFcFMin'))}, '0'), '--')"),
        line('AucGuide', 'AUC target reached at',
             f"if({ref(T('AucGuideElapsedSec'))} >= 0, {mmss_int(ref(T('AucGuideElapsedSec')))}, '--:--')"),
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

# ================================================================ charts (canvas)

# v4.4: every chart in the project is a 2027 canvas line chart
# (ia.canvas-charts.line, ECharts based). Eric, 2026-11-13:
# "All of them must be new echarts", after the classic XY roast
# curve failed to follow dark mode. The base tree below is the
# harness validated minimal prop tree for the component
# (CompLab project on the 2027 gateway; knowledge/notes/
# canvas-charts-2027.md), animation sanitized the way ChartLab
# standardized.
#
# Theming rules, proven in the 2026-11-13 probe round:
# - Colors that must follow the theme stay EMPTY (''). The
#   canvas wrapper resolves empty colors from the session
#   theme: axis labels, titles, gridlines and legend all
#   rendered correctly in dark AND light with '' everywhere.
# - CSS var() strings do NOT resolve: the wrapper passes them
#   to the canvas literally, an invalid fill, so text renders
#   black (invisible on dark). Never put var() in a chart prop.
# - Series colors are literal hex by design: they must read
#   identically in both themes (amber bean, sky RoR).
# - appearance.backgroundColor '' = transparent surface over
#   the card, both themes.
CANVAS_LINE_BASE = {'appearance': {'animation': {'enabled': True,
                              'entry': {'delay': 0,
                                        'duration': 1000,
                                        'easing': 'cubicOut'},
                              'transition': {'delay': 0,
                                             'duration': 300,
                                             'easing': 'cubicOut'}},
                'backgroundColor': '',
                'colorPalette': []},
 'axisPointer': {'enabled': True,
                 'label': {'backgroundColor': '',
                           'color': '',
                           'elementStyle': {},
                           'fontSize': '',
                           'visible': False},
                 'type': 'line'},
 'data': [],
 'legend': {'color': '',
            'elementStyle': {},
            'fontSize': '',
            'interactive': True,
            'orientation': 'horizontal',
            'position': 'bottom',
            'visible': True},
 'liveData': False,
 'series': [{'advanced': {'connectNulls': False,
                          'step': '',
                          'tooltip': {'enabled': True,
                                      'formatter': {'template': '',
                                                    'type': 'value',
                                                    'value': ''}},
                          'yAxis': 0},
             'dataLabels': {'color': '',
                            'elementStyle': {},
                            'fontSize': '',
                            'format': '{value}',
                            'position': 'top',
                            'visible': False},
             'label': 'Power',
             'line': {'type': 'solid', 'width': 2},
             'points': {'fillColor': '',
                        'outlineColor': 'transparent',
                        'outlineWidth': 0,
                        'shape': 'circle',
                        'size': 4,
                        'visible': False},
             'referenceLines': {'animation': {'enabled': True,
                                              'entry': {'delay': 0,
                                                        'duration': 1000,
                                                        'easing': 'cubicOut'},
                                              'transition': {'delay': 0,
                                                             'duration': 300,
                                                             'easing': 'cubicOut'}},
                                'endpoints': {'points': [{'shape': 'circle',
                                                          'size': 4}],
                                              'visible': True},
                                'items': []},
             'smooth': False,
             'value': 'value',
             'visible': True}],
 'stackGroups': [],
 'title': {'color': '',
           'elementStyle': {},
           'fontSize': '',
           'gap': 5,
           'position': 'top-left',
           'subtitle': {'color': '',
                        'elementStyle': {},
                        'fontSize': '',
                        'text': ''},
           'text': '',
           'visible': True},
 'tooltip': {'enabled': True,
             'formatter': {'template': '',
                           'type': 'value',
                           'value': '{value}'},
             'trigger': 'axis'},
 'visualMap': {'dimension': 'y',
               'enabled': False,
               'legend': {'color': '',
                          'elementStyle': {},
                          'fontSize': '',
                          'interactive': True,
                          'orientation': 'horizontal',
                          'position': 'bottom',
                          'visible': True},
               'outOfRange': {},
               'pieces': []},
 'xAxis': {'advanced': {'axisPointer': {'enabled': 'auto',
                                        'label': {'backgroundColor': '',
                                                  'color': '',
                                                  'elementStyle': {},
                                                  'fontSize': '',
                                                  'visible': 'auto'},
                                        'type': 'auto'}},
           'axisLine': {'color': '', 'visible': True, 'width': 1},
           'boundaryGap': True,
           'field': 'timestamp',
           'gridLines': {'color': '', 'visible': False, 'width': 1},
           'labels': {'color': '',
                      'elementStyle': {},
                      'fontSize': '',
                      'overflow': 'none',
                      'position': 'bottom',
                      'rotation': 0,
                      'visible': True},
           'max': 'auto',
           'min': 'auto',
           'position': 'bottom',
           'ticks': {'displayInside': False,
                     'majorSplit': 'auto',
                     'minorSplit': 0,
                     'visible': True},
           'title': {'color': '',
                     'elementStyle': {},
                     'fontSize': '',
                     'gap': 15,
                     'position': 'middle',
                     'rotation': 0,
                     'text': '',
                     'visible': True},
           'type': 'time',
           'visible': True},
 'yAxis': [{'advanced': {'axisPointer': {'enabled': 'auto',
                                         'label': {'backgroundColor': '',
                                                   'color': '',
                                                   'elementStyle': {},
                                                   'fontSize': '',
                                                   'visible': 'auto'},
                                         'type': 'auto'}},
            'axisLine': {'visible': True},
            'boundaryGap': True,
            'gridLines': {'visible': False},
            'labels': {'color': '',
                       'elementStyle': {},
                       'fontSize': '',
                       'overflow': 'none',
                       'rotation': 0,
                       'visible': True,
                       'width': None},
            'max': 'auto',
            'min': 'auto',
            'ticks': {'displayInside': False,
                      'majorSplit': 'auto',
                      'minorSplit': 0,
                      'visible': True},
            'title': {'color': '',
                      'elementStyle': {},
                      'fontSize': '',
                      'gap': 15,
                      'position': 'middle',
                      'rotation': 0,
                      'text': '',
                      'visible': True},
            'visible': True}],
 'zoom': {'axis': 'x',
          'backgroundColor': '',
          'enabled': False,
          'height': 30,
          'type': 'slider',
          'width': 30,
          'xPosition': 'bottom',
          'yPosition': 'right'}}

SANE_ANIM = {'enabled': True,
             'entry': {'duration': 900, 'easing': 'cubicOut',
                       'delay': 0},
             'transition': {'duration': 300,
                            'easing': 'cubicOut', 'delay': 0}}


def _canvas_props():
    p = copy.deepcopy(CANVAS_LINE_BASE)
    p['appearance']['animation'] = copy.deepcopy(SANE_ANIM)
    p['appearance']['backgroundColor'] = ''
    p['title']['visible'] = False
    p['legend'].update({'visible': True, 'position': 'bottom',
                        'color': '', 'fontSize': 12})
    return p


def _canvas_series(value, label, color, axis, width=2, dash=None,
                   step=None, area=None):
    s = copy.deepcopy(CANVAS_LINE_BASE['series'][0])
    s['value'] = value
    s['label'] = label
    s['smooth'] = True
    s['line'].update({'type': dash or 'solid', 'width': width,
                      'color': color})
    if area is not None:
        # The canvas line component honors a series area block
        # exactly like the area component (probe proven live,
        # 2026-11-17): a solid fill under the line at the given
        # opacity. Opacity 0 is no fill, the default look.
        s['area'] = area
    s['points']['visible'] = False
    s['advanced']['yAxis'] = axis
    # The live dataset is a timestamp UNION of samples and
    # overlays (roastery.core.build_live_curve), so a series
    # has nulls at other sources' timestamps; connectNulls
    # keeps those merge artifacts from breaking the line.
    s['advanced']['connectNulls'] = True
    if step:
        s['advanced']['step'] = step
    return s


def _canvas_xaxis(title_text=None, split=22, rotate=0):
    """The elapsed axis (v4.1 semantics on the new component):
    a time axis fed epoch based values (Date(0) + elapsed
    seconds) from the recorded samples, never wall clock, so a
    roast reads the same an hour later as it did live. Min is
    1000 ms: at exactly 0 the first tick is the epoch year
    boundary and ECharts labels it '1970'; 1 s in, the first
    tick reads 00:01 (probe proven, 2026-11-13). Reference
    line values clamp to the same minimum in the library.

    Label discipline (Eric, 2026-11-13, no overlap pass): the
    tick density is set explicitly through ticks.majorSplit
    (the component's splitNumber analog), never left to render
    at sample density. At a typical 660 s span, split 11 lands
    near 60 s steps; 30 s steps (split 22) were tried on the
    desktop main chart and the labels merged into each other,
    so 60 s is the standard everywhere, with the phone labels
    also tilted 35 degrees. Eric's floor: no finer than about
    15 s."""
    xa = copy.deepcopy(CANVAS_LINE_BASE['xAxis'])
    xa['type'] = 'time'
    xa['field'] = 't_stamp'
    xa['min'] = 1000
    xa['ticks']['majorSplit'] = split
    xa['labels']['rotation'] = rotate
    if title_text:
        xa['title'].update({'visible': True, 'text': title_text,
                            'color': '', 'fontSize': 11})
    else:
        xa['title']['visible'] = False
    return xa


def _canvas_yaxis(minv, maxv, title_text, position=None,
                  grid=True, split='auto'):
    ya = copy.deepcopy(CANVAS_LINE_BASE['yAxis'][0])
    ya['min'] = minv
    ya['max'] = maxv
    if position:
        ya['position'] = position
    ya['title'].update({'visible': True, 'text': title_text,
                        'color': '', 'fontSize': 11})
    ya['gridLines'] = {'visible': grid, 'color': '', 'width': 1}
    ya['ticks']['majorSplit'] = split
    return ya


def _refline_binding(trigger_tag, lib_call):
    """Bind a series' referenceLines.items: the trigger is the
    marks dataset tag (rewritten whenever the marker record
    changes) and the script transform asks the library for the
    current items, so custom event names survive (the marks
    dataset itself lumps customs into one column)."""
    b = tag_binding(trigger_tag)
    b['transforms'] = [{'type': 'script',
                        'code': '\treturn %s\n' % lib_call}]
    return {'binding': b}


def main_chart(legend_on=True, mobile=False):
    p = _canvas_props()
    p['legend']['visible'] = legend_on
    p['data'] = []
    p['xAxis'] = _canvas_xaxis('Elapsed (mm:ss)',
                               split=11,
                               rotate=35 if mobile else 0)
    p['yAxis'] = [_canvas_yaxis(150, 460, 'Bean Temp (deg F)',
                                split=6),
                  _canvas_yaxis(0, 40, 'Rate of Rise (deg F/min)',
                                position='right', grid=False,
                                split=4)]
    if mobile:
        # At 360px the two rotated axis titles plus their label
        # columns eat most of the card width and the grid
        # collapses to a sliver (proven live, v4.4). The units
        # already live in the tiles and the HUD, so the mobile
        # instance drops the axis titles and shrinks the labels.
        for ax in p['yAxis']:
            ax['title']['visible'] = False
            ax['labels']['fontSize'] = 11
            ax['labels']['gap'] = 2
        p['xAxis']['labels']['fontSize'] = 11
    # Phase band series (Tier 3 item 16) sit FIRST so the fills
    # draw behind every curve: width 0 lines (invisible strokes)
    # whose dataset columns hold the bean axis top inside their
    # phase range, filled at low opacity by the library composed
    # band columns in LiveCurveDS. The bands carry no text IN
    # the plot (the PhasesBar names the phases, and in plot
    # labels would collide at 360px); their legend labels are
    # the phase names, because an empty label makes the wrapper
    # invent 'Series 1' style names (proven live, 2026-11-17).
    def band_series(col, color, label):
        s = _canvas_series(col, label, color, 0, width=0,
                           area={'fillStyle': 'solid',
                                 'color': color, 'opacity': 0.12,
                                 'gradientMode': 'fade',
                                 'gradientStart': color,
                                 'gradientEnd': ''})
        s['smooth'] = False
        s['advanced']['connectNulls'] = False
        return s
    p['series'] = [
        band_series('bandDry', '#eab308', 'Drying'),
        band_series('bandMai', '#f97316', 'Maillard'),
        band_series('bandDev', '#dc2626', 'Development'),
        band_series('bandCool', '#0284c7', 'Cooling'),
        _canvas_series('bg', 'Background', '#64748b', 0, width=2),
        _canvas_series('bgRor', 'Background RoR', '#64748b', 1,
                       width=2),
        _canvas_series('plan', 'Target', '#94a3b8', 0, width=2,
                       dash='dashed'),
        _canvas_series('bean', 'Bean Temp', AMBER, 0, width=3),
        _canvas_series('ror', 'Rate of Rise', SKY, 1, width=2,
                       area={'fillStyle': 'solid', 'color': SKY,
                             'opacity': 0.0,
                             'gradientMode': 'fade',
                             'gradientStart': SKY,
                             'gradientEnd': ''}),
        _canvas_series('proj', 'Projection', '#f59e0b', 0, width=2,
                       dash='dashed')]
    p['appearance']['colorPalette'] = ['#eab308', '#f97316',
                                       '#dc2626', '#0284c7',
                                       '#64748b', '#64748b',
                                       '#94a3b8', AMBER, SKY,
                                       '#f59e0b']
    p['style'] = {'classes': 'roast-chart'}
    # Curve display options (Tier 3 item 15): the Settings
    # Display tags bind straight onto the series props, the same
    # bracket path mechanism the reference lines use. Defaults
    # on the tags (BT 3 solid, RoR 2 solid, ghost 2 solid, fill
    # off, marker size 4) reproduce the pre Tier 3 look exactly.
    # The event marker size rides the reference line endpoints
    # of the bean series, which carries the event markLines.
    pc = {
        'props.data': {'binding': tag_binding(
            '[default]Roastery/LiveCurveDS')},
        'props.series[7].referenceLines.items':
            _refline_binding(
                '[default]Roastery/EventMarksDS',
                'roastery.core.event_reference_lines_compact()'
                if mobile else
                'roastery.core.event_reference_lines()'),
        'props.series[7].line.width': {'binding': tag_binding(
            T('DispBtWidth'))},
        'props.series[7].line.type': {'binding': tag_binding(
            T('DispBtStyle'))},
        'props.series[8].line.width': {'binding': tag_binding(
            T('DispRorWidth'))},
        'props.series[8].line.type': {'binding': tag_binding(
            T('DispRorStyle'))},
        'props.series[4].line.width': {'binding': tag_binding(
            T('DispGhostWidth'))},
        'props.series[4].line.type': {'binding': tag_binding(
            T('DispGhostStyle'))},
        'props.series[5].line.width': {'binding': tag_binding(
            T('DispGhostWidth'))},
        'props.series[5].line.type': {'binding': tag_binding(
            T('DispGhostStyle'))},
        'props.series[8].area.opacity': {'binding': expr_binding(
            f"if({ref(T('DispRorFill'))}, 0.22, 0.0)")},
        'props.series[7].referenceLines.endpoints.points[0].size':
            {'binding': tag_binding(T('DispMarkerSize'))}}
    return {
        'type': 'ia.canvas-charts.line',
        'meta': {'name': 'RoastChart'},
        'props': p,
        'propConfig': pc,
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}


def trace_chart(mobile=False):
    # Fan / Heat levels on the same elapsed timeline and the
    # same dataset as the main chart (fan and heat ride along
    # per temperature change). Step rendering at the change
    # point: a level holds until the next sample replaces it.
    # Legend at the bottom: at phone widths a right side legend
    # clipped ('H...' for Heat in Eric's v4.1 screenshot).
    p = _canvas_props()
    p['data'] = []
    p['xAxis'] = _canvas_xaxis(split=11,
                               rotate=35 if mobile else 0)
    p['yAxis'] = [_canvas_yaxis(0, 10, 'Level', split=5)]
    p['series'] = [
        _canvas_series('fan', 'Fan', AMBER, 0, width=2,
                       step='start'),
        _canvas_series('heat', 'Heat', RED, 0, width=2,
                       step='start')]
    p['appearance']['colorPalette'] = [AMBER, RED]
    p['style'] = {'classes': 'roast-chart'}
    return {
        'type': 'ia.canvas-charts.line',
        'meta': {'name': 'TraceChart'},
        'props': p,
        'propConfig': {'props.data': {'binding': tag_binding(
            '[default]Roastery/LiveCurveDS')}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}

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
            'props': {'selected': False, 'text': '',
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
    "\tself.getChild('SettingsMetadataRoot').getChild('MetaForm').props.data = roastery.core.config_form_data()\n")
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

# ================================================================ Batches (page /batches)

def phone_cols_wrap(wrap_name, btn_name, table, phone_cols,
                    base_classes):
    """Polish round 2 (HUNT-13): the phone column set wrapper
    for a wide table. Holds a toggle row and two copies of the
    table: a reduced phone set and the full set, exactly one
    of them hidden through the roast-hidden class chosen by
    the view's showAllCols custom prop (the ConfirmRow class
    selection pattern). The advanced stylesheet renders the
    wrapper only below 900px viewport width; the original
    table carries roast-cols-full and renders at 900px and
    up, so desktop is unchanged."""
    phone = copy.deepcopy(table)
    phone['meta']['name'] = table['meta']['name'] + 'Phone'
    phone['props']['columns'] = phone_cols
    phone['props']['style']['classes'] = base_classes
    phone.setdefault('propConfig', {})['props.style.classes'] = {
        'binding': expr_binding(
            "if({view.custom.showAllCols}, '%s roast-hidden', "
            "'%s')" % (base_classes, base_classes))}
    full = copy.deepcopy(table)
    full['meta']['name'] = table['meta']['name'] + 'FullPhone'
    full['props']['style']['classes'] = base_classes
    full.setdefault('propConfig', {})['props.style.classes'] = {
        'binding': expr_binding(
            "if({view.custom.showAllCols}, '%s', "
            "'%s roast-hidden')" % (base_classes, base_classes))}
    toggle = button(btn_name, 'All columns',
                    'roast-btn roast-btn-sm roast-btn-ghost',
                    prop_config={'props.text': {'binding':
                        expr_binding(
                            "if({view.custom.showAllCols}, "
                            "'Fewer columns', 'All columns')")}},
                    events=script_event(
                        "\timport roastery.core\n"
                        "\troastery.core.toggle_all_cols(self)\n"))
    trow = flex('ColsToggleRow', 'row', [toggle],
                justify='flex-end', align='center',
                classes='roast-gap-12')
    return flex(wrap_name, 'column', [trow, phone, full],
                classes='roast-gap-8 roast-cols-phone',
                position={'grow': 0, 'shrink': 0, 'basis': 'auto'})


def batches_panel_view():
    """The reusable batches panel for the Log page: a tidy table
    (columns chosen to survive a phone width), selection driven
    actions (Details, Edit via the slide over dock, Use as Ghost,
    Delete behind a confirm). All logic lives in roastery.batches;
    the table reads through the SelectAll named query only."""
    # Column widths slimmed (no overlap pass, 2026-11-13): the
    # old set totaled 710px and the Bean column ran off the
    # card edge at 360px. The date drops its year in the list
    # (the detail view carries the full date) and every column
    # is sized to its content; the set totals about 580px.
    cols = [
        {'field': 'batch_number', 'header': {'title': 'Batch'},
         'width': 60},
        {'field': 'roast_start', 'header': {'title': 'Date'},
         'width': 132, 'render': 'date',
         'dateFormat': 'MM-DD h:mm a'},
        {'field': 'bean_name', 'header': {'title': 'Bean'},
         'width': 120},
        {'field': 'drop_temp_f', 'header': {'title': 'Drop (F)'},
         'width': 66},
        {'field': 'total_sec', 'header': {'title': 'Total (s)'},
         'width': 62},
        {'field': 'dtr_pct', 'header': {'title': 'DTR %'},
         'width': 56},
        {'field': 'roast_degree', 'header': {'title': 'Degree'},
         'width': 84},
        {'field': 'id', 'header': {'title': 'ID'}, 'width': 50,
         'visible': False},
    ]
    table = {'type': 'ia.display.table', 'meta': {'name': 'BatchTable'},
             'props': {'data': [], 'columns': cols,
                       'pager': {'enabled': False},
                       'rows': {'height': 40},
                       'header': {'height': 36, 'style': {
                           'classes': 'roast-table-header'}},
                       'style': {'classes': 'roast-table roast-cols-full'}},
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
             'position': {'grow': 0, 'shrink': 0, 'basis': '430px'}}
    table_wrap = phone_cols_wrap(
        'BatchTablePhoneWrap', 'ColsToggleButton', table, [
            {'field': 'batch_number',
             'header': {'title': 'Batch'}, 'width': 54},
            {'field': 'roast_start',
             'header': {'title': 'Date'}, 'width': 100,
             'render': 'date', 'dateFormat': 'MM-DD h:mm a'},
            {'field': 'bean_name',
             'header': {'title': 'Bean'}, 'width': 68},
            {'field': 'drop_temp_f',
             'header': {'title': 'Drop (F)'}, 'width': 62}],
        'roast-table')
    sel_enabled = "({view.custom.selBatchNumber} > 0)"
    details_btn = button('DetailsButton', 'Details',
                         'roast-btn roast-btn-sm roast-btn-primary',
                         prop_config={'props.enabled': {'binding':
                             expr_binding(sel_enabled)}},
                         events=lib_event(
                             'roastery.batches.open_detail(self)'))
    edit_btn = button('EditButton', 'Edit',
                      'roast-btn roast-btn-sm roast-btn-ghost',
                      prop_config={'props.enabled': {'binding':
                          expr_binding(sel_enabled)}},
                      events=lib_event(
                          'roastery.batches.open_editor(self)'))
    bg_btn = button('BgButton', 'Use as Ghost',
                    'roast-btn roast-btn-sm roast-btn-purple',
                    prop_config={'props.enabled': {'binding':
                        expr_binding(sel_enabled)}},
                    events=lib_event(
                        'roastery.batches.set_background(self)'))
    del_btn = button('DeleteButton', 'Delete',
                     'roast-btn roast-btn-sm roast-btn-charge',
                     prop_config={'props.enabled': {'binding':
                         expr_binding(sel_enabled)}},
                     events=lib_event('roastery.batches.arm_delete(self)'))
    note = label('SelNote',
                 'Select a batch for its details, the editor, a ghost overlay, or delete.',
                 'roast-note',
                 position={'grow': 1, 'shrink': 1, 'basis': '0px'},
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.custom.selNote')}})
    foot = flex('FootRow', 'row',
                [note, details_btn, edit_btn, bg_btn, del_btn],
                justify='flex-end', align='center', wrap='wrap',
                classes='roast-gap-12')
    confirm_lbl = label('ConfirmLabel', '', 'roast-banner-text',
                        prop_config={'props.text': {'binding': expr_binding(
                            "'Delete batch ' + {view.custom.selBatchNumber} + ', its curve and its press log?'")}})
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
                       prop_config={'props.style.classes': {'binding':
                           expr_binding(
                               "if({view.custom.confirmDelete}, "
                               "'roast-banner roast-gap-12', "
                               "'roast-banner roast-gap-12 roast-hidden')")}})
    import_lbl = label('ImportLabel', 'Artisan import',
                       'roast-note',
                       position={'grow': 0, 'shrink': 0,
                                 'basis': '92px'})
    upload = {'type': 'ia.input.fileupload',
              'meta': {'name': 'ArtisanImport'},
              'props': {'maxUploads': 1,
                        'supportedFileTypes': ['alog'],
                        'fileSizeLimit': 5},
              'events': {'component': {'onFileReceived': {
                  'scope': 'G', 'type': 'script',
                  'config': {'script':
                      "\timport roastery.artisan\n"
                      "\troastery.artisan.import_upload(self, event)\n"}}}},
              'position': {'grow': 0, 'shrink': 1,
                           'basis': '190px'}}
    import_note = label(
        'ImportNote',
        'Choose an Artisan .alog file to add that roast to the log.',
        'roast-note',
        position={'grow': 1, 'shrink': 1, 'basis': '0px'},
        prop_config={'props.text': {'binding': prop_binding(
            'view.custom.importNote')}})
    import_row = flex('ImportRow', 'row',
                      [import_lbl, upload, import_note],
                      align='center', wrap='wrap',
                      classes='roast-gap-12')
    # Compare section (Tier 1 item 2): three batch pickers, an
    # Align picker (polish round 8, HUNT-56: the Artisan
    # alignEvent choice, bound to the CompareAlignEvent tag
    # shared with Settings Display), a Compare button and the
    # overlay chart. Options and the dataset are library built
    # (roastery.batches.compare_*).
    def cmp_drop(name, prop):
        return {'type': 'ia.input.dropdown', 'meta': {'name': name},
                'props': {'options': [], 'value': 0,
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.value': _custom_binding(prop)},
                'position': {'grow': 1, 'shrink': 1, 'basis': '150px'}}
    align_opts = [{'value': 'charge', 'label': 'CHARGE'},
                  {'value': 'dryEnd', 'label': 'DRY'},
                  {'value': 'fcStart', 'label': 'FCs'},
                  {'value': 'fcEnd', 'label': 'FCe'},
                  {'value': 'scStart', 'label': 'SCs'},
                  {'value': 'scEnd', 'label': 'SCe'},
                  {'value': 'drop', 'label': 'DROP'}]
    cmp_btn = button('CompareButton', 'Compare',
                     'roast-btn roast-btn-sm roast-btn-primary',
                     events=lib_event(
                         'roastery.batches.build_compare(self)'))
    compare_row = flex('CompareRow', 'row',
                       [cmp_drop('CmpA', 'cmpA'), cmp_drop('CmpB', 'cmpB'),
                        cmp_drop('CmpC', 'cmpC'),
                        cfg_field('CmpAlignField', 'Align on',
                                  tag_dropdown('CmpAlign',
                                               'CompareAlignEvent',
                                               align_opts),
                                  basis='150px'),
                        cmp_btn],
                       align='center', wrap='wrap',
                       classes='roast-gap-12')
    cmp_cap = label('CompareCaption', '', 'roast-note',
                    prop_config={'props.text': {'binding': prop_binding(
                        'view.custom.compareCaption')}})
    cmp_chart_wrap = flex('CompareChartWrap', 'row',
                          [compare_chart(), compare_chart_phone()],
                          position={'grow': 0, 'shrink': 0,
                                    'basis': '300px'})
    root = flex('root', 'column',
                [table, table_wrap, confirm_row, foot, import_row, compare_row,
                 cmp_cap, cmp_chart_wrap],
                classes='roast-card roast-gap-12',
                scripts={'messageHandlers': [{
                    'messageType': 'roastery-batches-refresh',
                    'script': ("\timport roastery.batches\n"
                               "\troastery.batches.refresh_table(self)\n"),
                    'sessionScope': True, 'pageScope': True,
                    'viewScope': False}]})
    return {'custom': {'showAllCols': False,
                       'selBatchNumber': 0, 'selLabel': '',
                       'selNote': 'Select a batch for its details, the editor, a ghost overlay, or delete.',
                       'confirmDelete': False,
                       'importNote': 'Choose an Artisan .alog file to add that roast to the log.',
                       'cmpA': 0, 'cmpB': 0, 'cmpC': 0,
                       'compareDs': None,
                       'compareCaption': 'Pick up to three batches and press Compare.',
                       'compareRefLines': []},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 940}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.batches\n"
                    "\troastery.batches.compare_startup(self)\n"}}}},
            'root': root}


def compare_chart():
    """Multi curve comparison chart (Tier 1 item 2): up to
    three saved batches on the elapsed axis, BT solid and RoR
    dashed in one hue per batch (A orange, B teal, C violet).
    Axis titles are visible (HUNT-52): the full desktop titles
    live here, and compare_chart_phone() below carries the
    short titles for the 360px phone instance (HUNT-54).
    The HUNT-31 per-theme color bindings are applied
    post-generation, so this builder only emits the data
    binding; do not run it against the live project tree.
    The legend names every series. Polish round 8
    (HUNT-56): the bean series carries one ALIGN reference
    line, bound to view.custom.compareRefLines, which
    build_compare writes at the aligned reference event
    (grid-snapped, Artisan's vertical align line)."""
    p = _canvas_props()
    p['data'] = []
    p['xAxis'] = _canvas_xaxis(split=11, rotate=30)
    p['yAxis'] = [_canvas_yaxis(150, 460, 'Bean Temp (deg F)',
                                split=6),
                  _canvas_yaxis(0, 40, 'Rate of Rise (deg F/min)',
                                position='right', grid=False,
                                split=4)]
    for ax in p['yAxis']:
        ax['labels']['fontSize'] = 11
        ax['labels']['gap'] = 2
    p['xAxis']['labels']['fontSize'] = 11
    p['series'] = [
        _canvas_series('btA', 'A BT', '#f97316', 0, width=2),
        _canvas_series('rorA', 'A RoR', '#f97316', 1, width=1,
                       dash='dashed'),
        _canvas_series('btB', 'B BT', '#14b8a6', 0, width=2),
        _canvas_series('rorB', 'B RoR', '#14b8a6', 1, width=1,
                       dash='dashed'),
        _canvas_series('btC', 'C BT', '#8b5cf6', 0, width=2),
        _canvas_series('rorC', 'C RoR', '#8b5cf6', 1, width=1,
                       dash='dashed')]
    p['appearance']['colorPalette'] = ['#f97316', '#14b8a6',
                                       '#8b5cf6']
    p['style'] = {'classes': 'roast-chart roast-cols-full'}
    return {'type': 'ia.canvas-charts.line',
            'meta': {'name': 'CompareChart'},
            'props': p,
            'propConfig': {'props.data': {'binding': prop_binding(
                'view.custom.compareDs')},
                'props.series[0].referenceLines.items': {
                    'binding': prop_binding(
                        'view.custom.compareRefLines')}},
            'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}


def compare_chart_phone():
    """Phone twin of compare_chart() (HUNT-54): identical
    except the short y-axis titles that fit the 288px chart
    at a 360px viewport, 'Bean Temp (F)' and
    'RoR (deg F/min)'. The stylesheet hides this instance at
    900px and up and hides CompareChart below 900px. The
    HUNT-31 per-theme color bindings are applied
    post-generation, same as the desktop instance."""
    node = copy.deepcopy(compare_chart())
    node['meta']['name'] = 'CompareChartPhone'
    node['props']['yAxis'][0]['title']['text'] = 'Bean Temp (F)'
    node['props']['yAxis'][1]['title']['text'] = 'RoR (deg F/min)'
    node['props']['style'] = {'classes':
                              'roast-chart roast-cols-phone'}
    return node


# ================================================================ BatchEdit (slide over dock)
# The editor is a right docked view (dock id 'batchEditor' on the
# Log pages), NOT a popup: no popup chrome, it slides in from the
# right and covers. Mode and target come from the
# EditorCreateMode / SelectedBatchNumber tags (set by
# roastery.batches.open_editor); the form is ONE ia.input.form
# holding the metadata fields plus the event times (mm:ss from
# charge) and event temps. Saving runs through Batches/Update and
# the library recomputes phases, DTR, total time and roast degree
# from the edited times (roastery.batches._apply_events).

BATCHEDIT_STARTUP_SCRIPT = (
    "\timport roastery.batches\n"
    "\troastery.batches.editor_refresh(self)\n")
BATCHEDIT_SUBMIT_SCRIPT = (
    "\timport roastery.batches\n"
    "\troastery.batches.batch_edit_submit(self, event)\n")
BATCHEDIT_CANCEL_SCRIPT = "\tsystem.perspective.closeDock('batchEditor')\n"

EVENT_FORM_ROWS = (('charge', 'Charge'), ('dryEnd', 'Dry End'),
                   ('fcStart', 'FC Start'), ('fcEnd', 'FC End'),
                   ('scStart', 'SC Start'), ('scEnd', 'SC End'),
                   ('drop', 'Drop'))


def batch_edit_form():
    """One form: batch number, the 17 metadata fields, then the
    seven event rows (time as mm:ss text, temp as a number)."""
    header = f_widget('MetaHeader', 'none', 'Batch Details',
                      tpl=HEADER_TPL)
    rows = [f_row([header]),
            f_row([f_number('BatchNumber', 'Batch number', 1, 99999)]),
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
            f_row([f_number('WeightOutG', 'Weight out (g)', 0, 2000)])]
    rows += extra_meta_rows()
    rows += [
            f_row([f_widget('EventsHeader', 'none',
                            'Roast Events - times are mm:ss from charge; '
                            'clear a time to remove the event. Charge is '
                            'always 00:00.', tpl=HEADER_TPL)])]
    for key, lbl in EVENT_FORM_ROWS:
        rows.append(f_row([
            f_text('Ev_%s_t' % key, lbl + ' time (mm:ss)'),
            f_number('Ev_%s_tempF' % key, lbl + ' temp (F)', 0, 600)]))
    return {
        'type': 'ia.input.form', 'meta': {'name': 'BatchForm'},
        'props': {
            'name': 'batchEdit',
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
                           'text': 'Save Batch',
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
                'config': {'script': BATCHEDIT_SUBMIT_SCRIPT}},
            'onCancelActionPerformed': {
                'scope': 'G', 'type': 'script',
                'config': {'script': BATCHEDIT_CANCEL_SCRIPT}}}}}


def batch_edit_view():
    title = label('Title', 'Edit Batch', 'roast-title-sm',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.editorTitle')}})
    note = label('ModeNote',
                 'Editing the stored batch document. Saving recomputes '
                 'phase times, DTR, total time and roast degree from '
                 'the event times. The batch number is the batch '
                 'identity and does not change.',
                 'roast-note')
    form = batch_edit_form()
    saved = label('EditNoteLabel', '', 'roast-note-success',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.editNote')}})
    close_btn = button('CloseButton', 'Close',
                       'roast-btn roast-btn-primary',
                       events=script_event(BATCHEDIT_CANCEL_SCRIPT))
    footer = flex('Footer', 'row', [close_btn], justify='flex-end')
    root = flex('root', 'column', [title, note, form, saved, footer],
                classes='roast-dock-editor',
                scripts={'messageHandlers': [{
                    'messageType': 'roastery-editor-open',
                    'script': ("\timport roastery.batches\n"
                               "\troastery.batches.editor_refresh(self)\n"),
                    'sessionScope': True, 'pageScope': True,
                    'viewScope': False}]})

    def _no_shrink(node):
        if isinstance(node, dict):
            for child in node.get('children', []) or []:
                pos = child.setdefault('position', {})
                pos['shrink'] = 0
                _no_shrink(child)
    _no_shrink(root)
    return {'custom': {'editNote': '', 'editorTitle': 'Edit Batch'},
            'params': {},
            'propConfig': {},
            'props': {'defaultSize': {'width': 480, 'height': 900}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script': BATCHEDIT_STARTUP_SCRIPT}}}},
            'root': root}

# ================================================================ v4 shell + pages
# App shell (page-config/config.json, written by main):
# - sharedDocks.bottom = Views/TabBar on every page (Roast,
#   Settings, Log tabs + theme toggle), a real docked view.
# - sharedDocks.top = Views/HudBar (bean temp, RoR, clock, state,
#   phase), a fixed cover dock; the advanced stylesheet hides top
#   docks at desktop widths (>= 900px) and pads page roots below
#   it on mobile, so the HUD exists on mobile only.
# - The Roast page's mobile control dock is NOT a page dock (the
#   bottom edge already carries the tab bar, and Perspective
#   stacks one dock per edge): it is Views/ControlDock pinned at
#   the bottom of the small breakpoint layout, directly above the
#   tab bar.
# - Log pages carry a right dock (dock id 'batchEditor') holding
#   Views/BatchEdit: the slide over editor.
#
# Responsive strategy: the Roast page root is a Breakpoint
# Container (breakpoint 900). Its two children are keyed by
# position.size ('small' / 'large'), the mechanism the client
# actually implements (BreakpointContainer reads child
# position.size; children without it default to 'small'). The
# small layout is control first for the phone remote control
# pattern; the large layout is trend first with a control rail.

ELAPSED_MS = f"(now() - {ref(T('StartTime'))})"
ELAPSED_SEC = f"({ELAPSED_MS} / 1000)"
DROP_ELAPSED_MS = f"(now() - {ref(T('DropTime'))})"
AFTER_DROP = (f"({ref(T('DropTime'))} != null && "
              f"({ref(T('State'))} = 'Dropped' || {ref(T('State'))} = 'Cooling' || "
              f"{ref(T('State'))} = 'Complete'))")

# Timer rule (Eric, 2026-11-12): "we only set the 0 timer when we
# drop." The header clock counts elapsed since Charge while
# roasting (that is the working roast clock; it is never re-zeroed
# mid roast). At Drop the displayed clock's zero is set: from Drop
# on it counts up from 00:00 as a post drop timer, captioned
# SINCE DROP. Event stamps, phases and the chart always use
# elapsed since Charge regardless.
CLOCK_EXPR_V4 = (
    f"if({AFTER_DROP}, {mmss_ms(DROP_ELAPSED_MS)}, "
    f"if({ref(T('State'))} = 'Roasting', {mmss_ms(ELAPSED_MS)}, '00:00'))")
CLOCK_CAPTION_EXPR = (
    f"if({AFTER_DROP}, 'SINCE DROP', 'ROAST TIME')")

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

_FC_WATCH = (
    f"({ref(T('AlarmFCWatchEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('FirstCrackStartElapsedSec'))} < 0 && "
    f"{ELAPSED_SEC} >= ({ref(T('TargetFCSec'))} - {ref(T('AlarmFCWindowSec'))}) && "
    f"{ELAPSED_SEC} <= ({ref(T('TargetFCSec'))} + {ref(T('AlarmFCWindowSec'))}))")

ALARM_TEXT = (
    f"if({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}, "
    f"{ref(T('AlarmHighTempMsg'))} + ' -- now ' + numberFormat({ref(T('BeanTempF'))}, '0') + ' F', "
    f"if({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}, "
    f"'Drop approaching -- target ' + numberFormat({ref(T('TargetDropTempF'))}, '0') + ' F', "
    f"if({_FC_WATCH}, 'First crack watch -- listen for cracks', '')))")

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


def stats_line_expr():
    """Statistics summary line (Tier 3 item 19): one compact
    line under the live chart with the phase times and percents
    the PhasesBar already computes (actual phase seconds from
    the stamped events, shares of the drop time once dropped,
    target proportions before that, and the DTR the Summary
    shows). Short labels (Dry, Mai, Dev) at the existing caption
    size (11px, the caption scale) with m:ss times and an
    integer DTR, so the longest form (all phases stamped)
    fits the 286px phone chart card whole, with the class
    ellipsis as the backstop. No new math lives here; every
    number is the
    PhasesBar or Summary expression reused."""
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))
    drop_e = ref(T('DropElapsedSec'))
    bg_dry = ref(T('BgPhaseDrySec'))
    bg_fc = ref(T('BgPhaseFcSec'))
    bg_drop = ref(T('BgPhaseDropSec'))
    use_bg = (f"({ref(T('PhaseFromBg'))} && {bg_dry} > 0 && "
              f"{bg_fc} > {bg_dry} && {bg_drop} > {bg_fc})")
    td = f"if({use_bg}, {bg_dry}, {ref(T('PhaseDryTargetSec'))})"
    tm = (f"if({use_bg}, ({bg_fc} - {bg_dry}), "
          f"{ref(T('PhaseMaillardTargetSec'))})")
    tv = (f"if({use_bg}, ({bg_drop} - {bg_fc}), "
          f"{ref(T('PhaseDevTargetSec'))})")
    tt = f"({td} + {tm} + {tv})"
    tt_safe = f"if({tt} > 0, {tt}, 1)"
    dry_pct = (f"if({drop_e} > 0, {dry_e} * 100.0 / {drop_e}, "
               f"{td} * 100.0 / {tt_safe})")
    mai_pct = (f"if({drop_e} > 0 && {fc_e} >= 0, "
               f"({fc_e} - {dry_e}) * 100.0 / {drop_e}, "
               f"{tm} * 100.0 / {tt_safe})")
    dev_pct = (f"if({drop_e} > 0 && {fc_e} >= 0, "
               f"({drop_e} - {fc_e}) * 100.0 / {drop_e}, "
               f"{tv} * 100.0 / {tt_safe})")
    def ms(e):
        # m:ss, not mm:ss: the saved minute zero pad costs a
        # character per phase and the line must fit 360px whole.
        return (f"numberFormat(floor({e} / 60), '0') + ':' + "
                f"numberFormat({e} % 60, '00')")
    return (
        f"'Dry ' + if({dry_e} >= 0, {ms(dry_e)}, '--:--') + ' ' + "
        f"numberFormat({dry_pct}, '0') + '% \u00b7 ' + "
        f"'Mai ' + if({fc_e} >= 0 && {dry_e} >= 0, "
        f"{ms(f'({fc_e} - {dry_e})')}, '--:--') + ' ' + "
        f"numberFormat({mai_pct}, '0') + '% \u00b7 ' + "
        f"'Dev ' + if({drop_e} >= 0 && {fc_e} >= 0, "
        f"{ms(f'({drop_e} - {fc_e})')}, '--:--') + ' ' + "
        f"numberFormat({dev_pct}, '0') + '% \u00b7 ' + "
        f"'DTR ' + if({drop_e} > 0 && {fc_e} >= 0, "
        f"numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0') + '%', '--')")


def state_pill(name):
    # Fixed 88px box (stability pass): the pill used to size to
    # its text (Idle 52px, Roasting 81px), shoving every element
    # after it sideways at each state change. The size rides
    # the flex position channel: this build's style class
    # compiler strips width/minWidth/maxWidth/flexShrink from
    # class definitions (proven: the compiled rule came back
    # empty), so box sizing is layout, expressed via position,
    # while every visual property stays in the class.
    return label(name, 'Idle', 'roast-pill',
                 position={'grow': 0, 'shrink': 0, 'basis': '88px'},
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
                                 {'input': 'Idle', 'output': '#6b7280'},
                                 {'input': 'Roasting',
                                  'output': '#dc2626'},
                                 {'input': 'Dropped',
                                  'output': '#475569'},
                                 {'input': 'Cooling',
                                  'output': '#0284c7'},
                                 {'input': 'Complete',
                                  'output': '#16a34a'}]}]}}})


def alarm_banner(name='AlarmBanner'):
    # Reserved slot (stability pass): the banner used to mount
    # and unmount via display flex/none, shoving the whole page
    # down when an alarm fired mid roast. It now always occupies
    # its 37px slot; only the background and text change.
    return flex(name, 'row', [
        label(name + 'Text', '', 'roast-banner-text',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.alarmText')}})],
        align='center',
        position={'grow': 0, 'shrink': 0, 'basis': '38px'},
        classes='roast-banner',
        prop_config={'props.style.backgroundColor': {'binding':
            expr_binding(
                f"if({ref(T('AlarmActive'))}, '#991b1b', 'rgba(0,0,0,0)')")}})


def prompt_strip(name='PromptStrip'):
    # Tier 2 items 11 and 14: the background playback prompt and
    # the auto event suggestion share one reserved strip, the
    # same stability pattern as the alarm banner: the slot is
    # always its 38px, only the text and background change, so
    # a prompt appearing mid roast moves nothing. Playback
    # (amber) wins over a suggestion (blue) when both are live.
    # The background is a data driven style binding like the
    # alarm banner's (a class cannot express which prompt is
    # active); it is on the validator's named exception list.
    # The Dismiss button calls the library; stamping the
    # suggested event also clears a suggestion.
    txt = label(name + 'Text', '', 'roast-banner-text',
                position={'grow': 1, 'shrink': 1, 'basis': '0px'},
                prop_config={'props.text': {'binding': prop_binding(
                    'view.custom.promptText')}})
    dismiss = button(name + 'Dismiss', '',
                     'roast-btn roast-btn-sm roast-btn-ghost',
                     prop_config={'props.text': {'binding': expr_binding(
                         f"if({ref(T('PlaybackActive'))} || "
                         f"{ref(T('SuggestionActive'))}, "
                         f"'Dismiss', '')")}},
                     events=lib_event(
                         'roastery.core.dismiss_prompt()'))
    return flex(name, 'row', [txt, dismiss],
                align='center',
                position={'grow': 0, 'shrink': 0, 'basis': '38px'},
                classes='roast-banner',
                prop_config={'props.style.backgroundColor': {'binding':
                    expr_binding(
                        f"if({ref(T('PlaybackActive'))}, '#92400e', "
                        f"if({ref(T('SuggestionActive'))}, '#1e40af', "
                        f"'rgba(0,0,0,0)'))")}})


# ---------------------------------------------------------------- TabBar

def tabbar_view():
    """Shared bottom dock content: the three tabs plus the theme
    toggle. Navigation is a plain framework call per button."""

    def tab(name, text, page):
        return button(name, text, 'roast-tab-btn',
                      position={'grow': 1, 'shrink': 1, 'basis': '0px'},
                      events=script_event(
                          "\tsystem.perspective.navigate(page='%s')\n"
                          % page))

    theme_btn = button('ThemeButton', '', 'roast-tab-btn',
                       position={'grow': 0, 'shrink': 0,
                                 'basis': '88px'},
                       prop_config={'props.text': {'binding': prop_binding(
                           'view.custom.themeText')}},
                       events=lib_event(
                           'roastery.core.theme_toggle(self)'))
    root = flex('root', 'row',
                [theme_btn,
                 tab('RoastTab', 'Roast', '/'),
                 tab('SettingsTab', 'Settings', '/settings'),
                 tab('LogTab', 'Log', '/log')],
                align='center', classes='roast-tabbar')
    return {'custom': {'themeText': 'Light'},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 62}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.core\n"
                    "\troastery.core.main_startup(self)\n"}}}},
            'root': root}


# ---------------------------------------------------------------- HudBar

def hud_view():
    """Shared top dock content (mobile only, hidden on desktop by
    the advanced stylesheet): the heads up roast readout that
    stays visible while the page scrolls under it."""

    def field(name, cap, value_binding, cap_binding=None, grow=0,
              basis='auto', value_class='roast-hud-value'):
        cap_pc = {'props.text': {'binding': cap_binding}} if cap_binding \
            else None
        c = label(name + 'Cap', cap, 'roast-hud-cap',
                  prop_config=cap_pc)
        v = label(name + 'Val', '', value_class,
                  prop_config={'props.text': {'binding': value_binding}})
        return flex(name, 'column', [c, v], classes='roast-hud-field',
                    position={'grow': grow, 'shrink': 0,
                              'basis': basis})

    # Fixed field boxes (stability pass): content sized groups
    # used to breathe as digits changed (the clock value box
    # measured 60px and 62px for the same five characters across
    # a state change). Widths fit the widest realistic reading
    # plus the caption above each value, and every value label
    # is capped at its group width so text can never push the
    # row (a forced 'Development' label measured 26px past the
    # 360px edge before the cap).
    # HUD values are whole numbers (no overlap pass, 2026-11-13):
    # at 16px monospace a one decimal reading ('288.4') needs
    # 48px, but the Bean field box holds 44px after its padding,
    # so the last digit clipped in Eric's hands. The HUD is the
    # glance layer; the tiles on the same screen keep the 0.0
    # precision. Whole numbers fit every field with margin.
    # Tier 1 tried adding an AUC field here and the 360px
    # budget does not close: pill 88 + bean + ror + clock +
    # a phase field wide enough for 'Second Crack' at HUD
    # size already fill the row, and every squeeze clipped a
    # digit or a phase letter in measurement. AUC lives on
    # the tiles and in the summary (both layouts) and in
    # Settings instead; the HUD keeps its four readouts.
    bean = field('Bean', 'BEAN F', fmt_tag(T('BeanTempF'), '0'),
                 basis='46px')
    ror = field('Ror', 'ROR', fmt_tag(T('RateOfRiseF'), '0'),
                basis='42px')
    clock = field('Clock', 'ROAST TIME', prop_binding('view.custom.clockText'),
                  cap_binding=prop_binding('view.custom.clockCaption'),
                  basis='58px')
    phase = field('Phase', 'PHASE', prop_binding('view.custom.phaseText'),
                  grow=1, value_class='roast-hud-value-phase')
    root = flex('root', 'row',
                [state_pill('HudState'), bean, ror, clock, phase],
                align='center', justify='flex-start',
                classes='roast-hud')
    return {'custom': {'clockText': '00:00', 'clockCaption': 'ROAST TIME',
                       'phaseText': 'Pre-charge'},
            'params': {},
            'propConfig': {
                'custom.clockText': {'binding': expr_binding(CLOCK_EXPR_V4)},
                'custom.clockCaption': {'binding': expr_binding(
                    CLOCK_CAPTION_EXPR)},
                'custom.phaseText': {'binding': expr_binding(PHASE_EXPR)}},
            'props': {'defaultSize': {'width': 900, 'height': 54}},
            'root': root}


# ---------------------------------------------------------------- ControlDock

def controldock_view():
    """Mobile primary controls, pinned at the bottom of the small
    Roast layout just above the tab bar: the primary flow in
    sequence plus the Fan and Heat steppers, all with 52px
    targets. Nothing here requires scrolling."""
    primary = flex('PrimaryRow', 'row', primary_event_buttons('M', big=True),
                   classes='roast-gap-8')
    steppers = flex('Steppers', 'row', [
        stepper_big('FanStepper', 'Fan', 'FanLevel', 'roast-btn-blue'),
        stepper_big('HeatStepper', 'Heat', 'HeatLevel',
                    'roast-btn-charge')],
        classes='roast-gap-12')
    root = flex('root', 'column', [primary, steppers],
                classes='roast-controldock')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 390, 'height': 150}},
            'root': root}


# ---------------------------------------------------------------- Roast page

def _chart_card(basis, legend_on=True, trace_basis='250px',
                head_stack=False, include_trace=True, mobile=False):
    chart_title = label('ChartTitle', 'Roast Curve', 'roast-value-strong')
    bg_chip = label('BgChip', '', 'roast-note',
                    prop_config={'props.text': {'binding': expr_binding(
                        f"if({ref('[default]Roastery/BackgroundLabel')} != '', 'Background: ' + {ref('[default]Roastery/BackgroundLabel')}, 'Background: none')")}})
    if head_stack:
        chart_head = flex('ChartHead', 'column',
                          [chart_title, bg_chip], align='flex-start',
                          classes='roast-gap-8',
                          position={'grow': 0, 'shrink': 0,
                                    'basis': '44px'})
    else:
        chart_head = flex('ChartHead', 'row', [chart_title, bg_chip],
                          justify='space-between', align='center',
                          position={'grow': 0, 'shrink': 0,
                                    'basis': '24px'})
    # Background from file (Tier 1 item 1): stage an Artisan
    # .alog as the ghost without saving a batch (the library
    # writes the same BackgroundCurveJson the saved batch ghost
    # uses). The note reports the staging on the page view.
    bg_lbl = label('BgFileLabel', 'Background .alog', 'roast-note',
                   position={'grow': 0, 'shrink': 0, 'basis': '104px'})
    bg_upload = {'type': 'ia.input.fileupload',
                 'meta': {'name': 'BgUpload'},
                 'props': {'maxUploads': 1,
                           'supportedFileTypes': ['alog'],
                           'fileSizeLimit': 5},
                 'events': {'component': {'onFileReceived': {
                     'scope': 'G', 'type': 'script',
                     'config': {'script':
                         "\timport roastery.artisan\n"
                         "\troastery.artisan.stage_background_upload(self, event)\n"}}}},
                 'position': {'grow': 0, 'shrink': 1,
                              'basis': '170px'}}
    bg_clear = button('BgClearButton', 'Clear ghost',
                      'roast-btn roast-btn-sm roast-btn-ghost',
                      events=lib_event(
                          'roastery.core.clear_background()'))
    bg_note = label('BgNote', '', 'roast-note',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'},
                    prop_config={'props.text': {'binding': prop_binding(
                        'view.custom.bgNote')}})
    bg_row = flex('BgRow', 'row',
                  [bg_lbl, bg_upload, bg_clear, bg_note],
                  align='center', wrap='wrap', classes='roast-gap-8')
    # Statistics summary line (Tier 3 item 19): directly under
    # the chart, one line, existing classes only. It is a fixed
    # 20px row so the layout never moves when its text changes.
    stats_line = label('StatsLine', '', 'roast-stats-line',
                       position={'grow': 0, 'shrink': 0,
                                 'basis': '20px'},
                       prop_config={'props.text': {'binding':
                           expr_binding(stats_line_expr())}})
    children = [chart_head, bg_row,
                main_chart(legend_on=legend_on, mobile=mobile),
                stats_line, _analyzer_strip()]
    if include_trace:
        trace_cap = label('TraceCaption', 'Fan / Heat Levels',
                          'roast-caption',
                          position={'grow': 0, 'shrink': 0,
                                    'basis': '16px'})
        children += [trace_cap,
                     flex('TraceWrap', 'row', [trace_chart()],
                          position={'grow': 0, 'shrink': 0,
                                    'basis': trace_basis})]
    return flex('ChartCard', 'column', children,
                classes='roast-card roast-gap-8',
                position={'grow': 0, 'shrink': 0, 'basis': basis})


def _analyzer_strip(detail=False):
    """Analyzer crosshair readout strip (Tier 2 item 13): a
    fixed strip under the chart, never floating chart text, so
    it cannot collide with axis or marker labels. The selected
    time moves with the -10s / +10s steppers or back to Latest;
    the library computes BT, RoR, ghost BT and deviation at
    that time from the one RoR implementation and publishes
    them on tags the four fields bind. Four short fields at
    grow 1 basis 0 fit 360px without squeezing anything."""
    if detail:
        base = '[default]Roastery/DetailAnalyzer/'
        step_m, step_p = ('roastery.batches.detail_analyzer_step(-10)',
                          'roastery.batches.detail_analyzer_step(10)')
        latest = 'roastery.batches.detail_analyzer_latest()'
        nm = 'DetailAnalyzer'
    else:
        base = T('Analyzer')
        step_m, step_p = ('roastery.core.analyzer_step(-10)',
                          'roastery.core.analyzer_step(10)')
        latest = 'roastery.core.analyzer_latest()'
        nm = 'Analyzer'

    def tb(member):
        return base + member if detail else T(member)

    cap = label(nm + 'Cap', 'Analyzer', 'roast-caption',
                position={'grow': 0, 'shrink': 0, 'basis': '64px'})
    minus = button(nm + 'Minus', '-10s',
                   'roast-btn roast-btn-sm roast-btn-ghost',
                   events=lib_event(step_m))
    time_lbl = label(nm + 'Time', '--:--', 'roast-value-strong',
                     position={'grow': 0, 'shrink': 0,
                               'basis': '52px'},
                     prop_config={'props.text': {'binding': tag_binding(
                         tb('TimeText' if detail else 'AnalyzerTimeText'))}})
    plus = button(nm + 'Plus', '+10s',
                  'roast-btn roast-btn-sm roast-btn-ghost',
                  events=lib_event(step_p))
    latest_btn = button(nm + 'Latest', 'Latest',
                        'roast-btn roast-btn-sm roast-btn-ghost',
                        events=lib_event(latest))
    controls = flex(nm + 'Controls', 'row',
                    [cap, minus, time_lbl, plus, latest_btn],
                    align='center', classes='roast-gap-8',
                    position={'grow': 0, 'shrink': 0, 'basis': '36px'})

    def field(fname, caption, member):
        c = label(nm + fname + 'Cap', caption, 'roast-caption')
        v = label(nm + fname + 'Val', '--', 'roast-value',
                  prop_config={'props.text': {'binding': tag_binding(
                      tb(member))}})
        return flex(nm + fname, 'column', [c, v],
                    classes='roast-gap-8',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})

    if detail:
        fields = [('Bt', 'BT (F)', 'BtText'), ('Ror', 'RoR', 'RorText'),
                  ('Bg', 'Ghost BT (F)', 'BgText'),
                  ('Dev', 'Dev (F)', 'DevText')]
    else:
        fields = [('Bt', 'BT (F)', 'AnalyzerBtText'),
                  ('Ror', 'RoR', 'AnalyzerRorText'),
                  ('Bg', 'Ghost BT (F)', 'AnalyzerBgText'),
                  ('Dev', 'Dev (F)', 'AnalyzerDevText')]
    values = flex(nm + 'Values', 'row',
                  [field(*f) for f in fields],
                  classes='roast-gap-8',
                  position={'grow': 0, 'shrink': 0, 'basis': '44px'})
    return flex(nm + 'Strip', 'column', [controls, values],
                classes='roast-gap-8',
                position={'grow': 0, 'shrink': 0, 'basis': '88px'})


def _trace_card(basis='280px'):
    """The Fan / Heat levels strip as its own card (mobile layout,
    v4.1 declutter): inside the chart card it squeezed the main
    chart and its right side legend clipped at phone widths. On
    its own it gets a bottom legend and room to read.

    Height is load bearing, here and in the desktop card's
    trace_basis. The classic XY chart collapsed its value axis
    below roughly 120px. The v4.4 canvas line chart is hungrier:
    its wrapper reserves roughly 150px of fixed layout (title,
    axes, legend) before the grid, so the grid collapses to a
    sliver below about 240px of component height regardless of
    config (proven live: 150px collapsed even with legend,
    labels and titles all off, 200px half collapsed, 250px
    clean, and the main chart config collapses at 150px too).
    250px desktop and 280px here keep a readable grid."""
    cap = label('TraceCardCap', 'Fan / Heat Levels', 'roast-caption',
                position={'grow': 0, 'shrink': 0, 'basis': '16px'})
    return flex('TraceCard', 'column', [
        cap, flex('TraceWrapMobile', 'row',
                  [trace_chart(mobile=True)],
                  position={'grow': 1, 'shrink': 1, 'basis': '0px'})],
        classes='roast-card roast-gap-8',
        position={'grow': 0, 'shrink': 0, 'basis': basis})


def _tiles_row(mobile=False):
    # Mobile (v4.1 declutter): four tiles in a clean 2x2 (Bean,
    # RoR, Fan, Heat, the readouts the remote control pattern
    # needs); Deviation, Phase and Target Drop already live in
    # the HUD, the phase bar and the summary. Seven tiles at a
    # 148px basis overflowed a 360px phone: flex items would not
    # shrink below their content width, so the row bled past the
    # right edge (gray slivers in Eric's screenshot). The row
    # carries roast-flexmin so children may shrink, and the
    # mobile basis is a percentage so two always fit per row.
    tile_pos = {'grow': 1, 'shrink': 1,
                'basis': '38%' if mobile else '148px'}
    tiles = [
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
               'accent': '#16a34a', 'valueClass': 'roast-value-md'},
              dict(tile_pos),
              {'props.params.valueText': {'binding': prop_binding(
                  'view.custom.phaseText')}}),
        embed('TargetTile', 'Views/Tile',
              {'title': 'Target Drop', 'valueText': '415',
               'unit': 'deg F', 'accent': '#64748b'}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('TargetDropTempF'), '0')}}),
        embed('TpTile', 'Views/Tile',
              {'title': 'Turning Point', 'valueText': '--',
               'unit': 'deg F', 'accent': '#f59e0b'}, dict(tile_pos),
              {'props.params.valueText': {'binding': expr_binding(
                  f"if({ref(T('TurningPointElapsedSec'))} >= 0, numberFormat({ref(T('TurningPointTempF'))}, '0') + ' @ ' + {mmss_int(ref(T('TurningPointElapsedSec')))}, '--')")}}),
        embed('AucTile', 'Views/Tile',
              {'title': 'AUC', 'valueText': '--',
               'unit': 'F min', 'accent': '#8b5cf6'}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('AucLiveFMin'), '0')}}),
        embed('BgDevTile', 'Views/Tile',
              {'title': 'Bg Deviation', 'valueText': '--',
               'unit': '', 'accent': '#64748b'}, dict(tile_pos),
              {'props.params.valueText': {'binding': tag_binding(
                  T('BgDeviationText'))}})]
    if mobile:
        tiles = [tiles[0], tiles[1], tiles[3], tiles[4]]
    return flex('TilesRow', 'row', tiles,
                wrap='wrap', classes='roast-gap-12 roast-flexmin',
                position={'grow': 0, 'shrink': 0, 'basis': 'auto'})


def _strip_embed():
    return embed('EventsStripEmbed', 'Views/EventsStrip', {},
                 {'grow': 0, 'shrink': 0, 'basis': 'auto'})


def _phases_embed():
    return embed('PhasesBarEmbed', 'Views/PhasesBar', {},
                 {'grow': 0, 'shrink': 0, 'basis': 'auto'})


def roast_page_view():
    # ---- large (desktop): trend first, control rail on the right
    title = label('TitleLabel', 'Ember & Oak Roastery', 'roast-title')
    sub = label('SubLabel', 'Artisan Roast Console - FreshRoast SR800',
                'roast-subtitle')
    title_block = flex('TitleBlock', 'column', [title, sub],
                       classes='roast-gap-8')
    batch_chip = label('BatchChip', '', 'roast-chip',
                       position={'grow': 0, 'shrink': 1,
                                 'basis': 'auto'},
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' - ' + {ref(T('BeanName'))}")}})
    ws_pill = label('WsPill', 'SR800', 'roast-pill',
                    position={'grow': 0, 'shrink': 0,
                              'basis': '170px'},
                    prop_config={
                        'props.text': {'binding': expr_binding(
                            f"if({ref(T('BeanTempF'))} > 0, {ref(T('ActiveSource'))} + ' CONNECTED', {ref(T('ActiveSource'))} + ' OFFLINE')")},
                        'props.style.backgroundColor': {'binding':
                            expr_binding(
                                f"if({ref(T('BeanTempF'))} > 0, '#166534', '#7f1d1d')")}})
    clock_cap = label('ClockCap', 'ROAST TIME', 'roast-caption',
                      prop_config={'props.text': {'binding': prop_binding(
                          'view.custom.clockCaption')}})
    clock = label('ClockLabel', '00:00', 'roast-clock',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.clockText')}})
    clock_block = flex('ClockBlock', 'column', [clock_cap, clock],
                       align='flex-end', classes='')
    right = flex('HeaderRight', 'row',
                 [batch_chip, ws_pill, state_pill('StatePill'),
                  clock_block],
                 align='center', wrap='wrap', classes='roast-gap-12')
    header = flex('HeaderBar', 'row', [title_block, right],
                  justify='space-between', align='center', wrap='wrap',
                  position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
                  classes='roast-header')
    main_col = flex('MainCol', 'column',
                    [_chart_card('748px', trace_basis='250px'),
                     _strip_embed(),
                     _phases_embed(), _tiles_row()],
                    classes='roast-gap-12',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    rail_col = flex('RailCol', 'column', [
        embed('ControlsEmbed', 'Views/Controls', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('SummaryEmbed', 'Views/Summary', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('MetaCardEmbed', 'Views/MetaCard', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'})],
        classes='roast-gap-12',
        position={'grow': 0, 'shrink': 0, 'basis': '400px'})
    content_row = flex('ContentRow', 'row', [main_col, rail_col],
                       classes='roast-content roast-gap-12',
                       position={'grow': 0, 'shrink': 0, 'basis': 'auto'})
    large = flex('LargeRoot', 'column',
                 [header, alarm_banner(), prompt_strip(), content_row],
                 classes='roast-app roast-fillscroll',
                 position={'size': 'large'})

    # ---- small (phone): control first; chart secondary; the
    # primary controls are pinned in the ControlDock embed at the
    # bottom of the layout (above the shared tab bar dock).
    batch_line = label('BatchLine', '', 'roast-chip',
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' - ' + {ref(T('BeanName'))}")}})
    scroll_col = flex('ScrollCol', 'column', [
        batch_line, _chart_card('518px', legend_on=False,
                                head_stack=True, include_trace=False,
                                mobile=True),
        _tiles_row(mobile=True),
        _trace_card(),
        _strip_embed(),
        _phases_embed(),
        embed('ControlsEmbedMobile', 'Views/Controls', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('SummaryEmbedMobile', 'Views/Summary', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('MetaCardEmbedMobile', 'Views/MetaCard', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'})],
        classes='roast-content roast-gap-12 roast-scrollcol',
        position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    small = flex('SmallRoot', 'column', [
        alarm_banner('AlarmBannerMobile'), prompt_strip('PromptStripMobile'),
        scroll_col,
        embed('ControlDockEmbed', 'Views/ControlDock', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'})],
        classes='roast-app roast-h100',
        position={'size': 'small'})

    root = {'type': 'ia.container.breakpt', 'meta': {'name': 'root'},
            'props': {'breakpoint': 900, 'currentBreakpoint': '',
                      'determinant': 'width', 'style': {}},
            'children': [large, small]}
    return {
        'custom': {'clockText': '00:00', 'clockCaption': 'ROAST TIME',
                   'deviationText': '--', 'phaseText': 'Pre-charge',
                   'alarmText': '', 'bgNote': '', 'promptText': ''},
        'params': {},
        'propConfig': {
            'custom.clockText': {'binding': expr_binding(CLOCK_EXPR_V4)},
            'custom.clockCaption': {'binding': expr_binding(
                CLOCK_CAPTION_EXPR)},
            # Tier 3 item 17: the deviation tile reads the
            # variable length plan through the library published
            # PlanDeviationText tag (a view expression can only
            # interpolate the old four fixed points).
            'custom.deviationText': {'binding': tag_binding(
                T('PlanDeviationText'))},
            'custom.phaseText': {'binding': expr_binding(PHASE_EXPR)},
            'custom.promptText': {'binding': expr_binding(
                f"if({ref(T('PlaybackActive'))}, "
                f"{ref(T('PlaybackText'))}, "
                f"if({ref(T('SuggestionActive'))}, "
                f"{ref(T('SuggestionText'))}, ''))")},
            'custom.alarmText': {'binding': tag_binding(T('AlarmText'))}},
        'props': {'defaultSize': {'width': 1440, 'height': 1240}},
        'root': root}


# ================================================================ Settings
# Settings organization (extend by copying the pattern): every
# section is its own embedded view named Views/Settings<Name>,
# built as a roast-card with a title, a one line description and
# labeled field rows whose inputs bind bidirectionally to the
# standing tags. To add a setting: add a cfg_field row in the
# section it belongs to (plus the tag in setup_roastery_v4_tags.py
# when it is new). To add a section: write one more
# settings_<name>_view() and add one embed line to
# settings_page_view(). Settings write LIVE tags: they take
# effect during a roast and serve as the defaults afterwards.

def settings_section(name, title, desc, children):
    head = label(name + 'Head', title, 'roast-section-title')
    d = label(name + 'Desc', desc, 'roast-section-desc')
    return flex(name, 'column', [head, d] + children,
                classes='roast-card roast-gap-10')


def settings_roaster_view():
    probe = label('ProbeReadout', '', 'roast-value',
                  prop_config={'props.text': {'binding': expr_binding(
                      f"'Probe now: ' + numberFormat({ref(T('BeanTempF'))}, '0.0') + ' F - RoR ' + numberFormat({ref(T('RateOfRiseF'))}, '0.0') + ' F/min'")}})
    src_note = label('SourceNote', '', 'roast-note',
                     prop_config={'props.text': {'binding': expr_binding(
                         f"'Active source: ' + {ref(T('ActiveSource'))} + ' - ' + "
                         f"if({ref(T('ActiveSource'))} = 'WebSocket', {ref(T('Sources/WebSocket/WsUrl'))}, "
                         f"if({ref(T('ActiveSource'))} = 'Mqtt', {ref(T('Sources/Mqtt/Address'))}, "
                         f"{ref(T('Sources/Simulated/Address'))}))")}})
    root = settings_section('SettingsRoasterRoot', 'Roaster',
        'Where the bean temperature comes from. The app always '
        'reads the canonical probe tag; switching the active source '
        'switches the transport underneath it, live.', [
        cfg_row('SourceRow', [
            cfg_field('SourceField', 'Active source', source_dropdown(),
                      basis='300px'),
            cfg_field('ProbeField', 'Live probe', probe, basis='260px')]),
        cfg_row('SrcNoteRow', [src_note]),
        cfg_row('WsRow', [
            cfg_field('WsField', 'WebSocket URL (SR800 feed)',
                      text_in('WsUrlSrcField', 'Sources/WebSocket/WsUrl',
                              'ws://sr800.local:8080'), basis='300px'),
            cfg_field('MqttBrokerField', 'MQTT broker URL',
                      text_in('MqttBrokerField', 'Sources/Mqtt/BrokerUrl',
                              'mqtt://localhost:1883'), basis='300px'),
            cfg_field('MqttTopicField', 'MQTT topic',
                      text_in('MqttTopicField', 'Sources/Mqtt/Topic',
                              'roastery/sr800/temp'), basis='300px')]),
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 260}},
            'root': root}


def settings_targets_view():
    # Tier 3 item 17: below the legacy four point fields and the
    # phase row sits the full profile designer (Artisan
    # designer.py shape): a read only table of the current plan
    # points plus an editor staging one point in the
    # TargetEditor tags (the AlarmEditor precedent: tag bindings
    # are the proven bidirectional path). Save, Add and Delete
    # go through roastery.core, which validates strictly
    # increasing times and rejects with the note text; the plan
    # line and the deviation tile read the stored list.
    TE = '[default]Roastery/TargetEditor/'

    def te_num(name, member, fmt='0'):
        return {'type': 'ia.input.numeric-entry-field',
                'meta': {'name': name},
                'props': {'value': 0, 'format': fmt,
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.value': {'binding': tag_binding(
                    TE + member, bidirectional=True)}}}

    def te_drop(name, member, options):
        return {'type': 'ia.input.dropdown', 'meta': {'name': name},
                'props': {'options': options,
                          'value': options[0]['value'],
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.value': {'binding': tag_binding(
                    TE + member, bidirectional=True)}}}

    plan_cols = [
        {'field': 'idx', 'header': {'title': '#'}, 'width': 36},
        {'field': 'timeSec', 'header': {'title': 'Time (sec)'},
         'width': 92},
        {'field': 'timeText', 'header': {'title': 'Time'},
         'width': 70},
        {'field': 'tempF', 'header': {'title': 'Temp (F)'},
         'width': 92},
    ]
    plan_table = {'type': 'ia.display.table',
                  'meta': {'name': 'TargetPlanTable'},
                  'props': {'data': [], 'columns': plan_cols,
                            'pager': {'enabled': False},
                            'rows': {'height': 32},
                            'header': {'height': 32, 'style': {
                                'classes': 'roast-table-header'}},
                            'style': {'classes': 'roast-table-sm'}},
                  'propConfig': {'props.data': {'binding': prop_binding(
                      'view.custom.targetPlanDs')}},
                  # Fixed basis, not auto: a virtualized table at
                  # auto height renders zero rows in this build
                  # (the Tier 1 alarm table lesson).
                  'position': {'grow': 0, 'shrink': 0,
                               'basis': '190px'}}
    idx_options = [{'value': i, 'label': 'Point %d' % (i + 1)}
                   for i in range(12)]
    load_row = flex('TargetLoadRow', 'row', [
        cfg_field('TpIdxField', 'Edit point',
                  te_drop('TpIdxDrop', 'Idx', idx_options),
                  basis='150px'),
        button('TpLoadButton', 'Load Point',
               'roast-btn roast-btn-sm roast-btn-ghost',
               events=lib_event(
                   'roastery.core.target_editor_load_idx(self)')),
        label('TpCountLabel', '', 'roast-note',
              prop_config={'props.text': {'binding': expr_binding(
                  "'Points in plan: ' + {view.custom.targetPlanCount}")}})],
        align='flex-end', wrap='wrap', classes='roast-gap-12')
    ed_row = cfg_row('TpEdRow', [
        cfg_field('TpTimeField', 'Point time (sec)',
                  te_num('TpTimeNum', 'TimeSec'), basis='160px'),
        cfg_field('TpTempField', 'Point temp (F)',
                  te_num('TpTempNum', 'TempF', '0.0'), basis='160px')])
    btn_row = flex('TpBtnRow', 'row', [
        button('TpSaveButton', 'Save Point',
               'roast-btn roast-btn-sm roast-btn-primary',
               events=lib_event(
                   'roastery.core.target_editor_save(self)')),
        button('TpAddButton', 'Add Point',
               'roast-btn roast-btn-sm roast-btn-green',
               events=lib_event(
                   'roastery.core.target_editor_add(self)')),
        button('TpDeleteButton', 'Delete Point',
               'roast-btn roast-btn-sm roast-btn-charge',
               events=lib_event(
                   'roastery.core.target_editor_delete(self)')),
        button('TpResetButton', 'Reset to Four Points',
               'roast-btn roast-btn-sm roast-btn-ghost',
               events=lib_event(
                   'roastery.core.target_plan_reset(self)')),
        label('TpNoteLabel', '', 'roast-note-success',
              position={'grow': 1, 'shrink': 1, 'basis': '0px'},
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.targetPlanNote')}})],
        align='center', wrap='wrap', classes='roast-gap-12')
    designer_head = label('DesignerHead', 'Target Plan Designer',
                          'roast-section-title')
    designer_desc = label(
        'DesignerDesc',
        'Edit the plan point by point. Times must be strictly '
        'increasing and the first point stays at 0 sec; an out '
        'of order save is rejected and nothing changes. The '
        'four fields above seed the default plan and the Reset '
        'button returns to them.',
        'roast-section-desc')
    root = settings_section('SettingsTargetsRoot', 'Targets',
        'The target profile the deviation tile and target curve '
        'follow, and the phase bar targets. Phase durations drive '
        'the phase bar directly; the DTR target is the development '
        'share of the total roast.', [
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
        cfg_row('PhaseRow', [
            cfg_field('PhaseDryField', 'Drying target (sec)',
                      num_in('PhaseDryNum', 'PhaseDryTargetSec')),
            cfg_field('PhaseMaiField', 'Maillard target (sec)',
                      num_in('PhaseMaiNum', 'PhaseMaillardTargetSec')),
            cfg_field('PhaseDevField', 'Development target (sec)',
                      num_in('PhaseDevNum', 'PhaseDevTargetSec')),
            cfg_field('DtrField', 'DTR target (%)',
                      num_in('DtrNum', 'DTRTargetPct', '0.0'))]),
        designer_head, designer_desc, plan_table, load_row,
        ed_row, btn_row,
    ])
    return {'custom': {'targetPlanDs': None, 'targetPlanCount': 0,
                       'targetPlanNote': ''},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 760}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.core\n"
                    "\troastery.core.targets_startup(self)\n"}}}},
            'root': root}


def settings_ror_view():
    live = label('RorLive', '', 'roast-value',
                 prop_config={'props.text': {'binding': expr_binding(
                     f"'RoR now: ' + numberFormat({ref(T('RateOfRiseF'))}, '0.0') + ' F/min'")}})
    root = settings_section('SettingsRorRoot', 'Rate of Rise',
        'Artisan parameters, applied live by the one library '
        'implementation (roastery.core.compute_ror_series) and '
        're-applied to saved batches when they are loaded as a '
        'detail or a ghost. Defaults are Artisan 5.0.0 defaults: '
        'span 20 s, curve filter 1, delta filter 3, smooth spikes '
        'on, clip -18 to 81 F/min.', [
        cfg_row('RorRow1', [
            cfg_field('SpanField', 'Delta span (sec)',
                      num_in('SpanNum', 'RoRDeltaSpanSec')),
            cfg_field('CurveField', 'Curve filter (0 to 5)',
                      num_in('CurveNum', 'RoRCurveFilter')),
            cfg_field('DeltaField', 'Delta filter (0 to 40)',
                      num_in('DeltaNum', 'RoRDeltaFilter')),
            cfg_field('LiveField', 'Live readout', live, basis='200px')]),
        cfg_row('RorRow2', [
            cfg_field('SpikesField', 'Smooth spikes (median, saved)',
                      check_in('SpikesCheck', 'RoRSmoothSpikes'),
                      basis='220px'),
            cfg_field('PolyField', 'Polyfit RoR (least squares)',
                      check_in('PolyCheck', 'RoRPolyfit'),
                      basis='220px'),
            cfg_field('OptField', 'Optimal smoothing (needs polyfit)',
                      check_in('OptCheck', 'RoROptimalSmoothing'),
                      basis='240px')]),
        cfg_row('RorRow3', [
            cfg_field('ClipLoField', 'Clip low (F/min)',
                      num_in('ClipLoNum', 'RoRClipLowF', '0.0')),
            cfg_field('ClipHiField', 'Clip high (F/min)',
                      num_in('ClipHiNum', 'RoRClipHighF', '0.0'))]),
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 320}},
            'root': root}


def tag_dropdown(name, member, options):
    return {'type': 'ia.input.dropdown', 'meta': {'name': name},
            'props': {'options': options, 'value': options[0]['value'],
                      'style': {'classes': 'roast-input'}},
            'propConfig': {'props.value': {'binding': tag_binding(
                T(member), bidirectional=True)}}}


def settings_auc_view():
    live = label('AucLive', '', 'roast-value',
                 prop_config={'props.text': {'binding': expr_binding(
                     f"'AUC now: ' + numberFormat({ref(T('AucLiveFMin'))}, '0') + ' F min - since FC ' + numberFormat({ref(T('AucSinceFcFMin'))}, '0') + ' F min'")}})
    begin_dd = tag_dropdown('AucBeginDropdown', 'AucBegin', [
        {'value': 'Charge', 'label': 'Charge'},
        {'value': 'TP', 'label': 'Turning point'},
        {'value': 'Dry End', 'label': 'Dry end'},
        {'value': 'FC Start', 'label': 'FC start'}])
    root = settings_section('SettingsAucRoot', 'AUC',
        'Area under the curve, Artisan style: the integral of '
        'bean temp above the base temp from the begin event, in '
        'F min (Artisan works in C min; its 640 C min default '
        'target equals 1152 F min here). The guide projects '
        'when the target is reached at the current rate of '
        'rise and shows in the Roast summary.', [
        cfg_row('AucRow1', [
            cfg_field('AucBeginField', 'Begin event', begin_dd,
                      basis='220px'),
            cfg_field('AucBaseField', 'Base temp (F)',
                      num_in('AucBaseNum', 'AucBaseTempF', '0')),
            cfg_field('AucBaseEvField', 'Base from begin event temp',
                      check_in('AucBaseEvCheck', 'AucBaseFromEvent'),
                      basis='230px')]),
        cfg_row('AucRow2', [
            cfg_field('AucTargetField', 'Target (F min)',
                      num_in('AucTargetNum', 'AucTargetFMin', '0')),
            cfg_field('AucGuideField', 'Guide (projection)',
                      check_in('AucGuideCheck', 'AucGuideEnabled'),
                      basis='200px'),
            cfg_field('AucLiveField', 'Live readout', live,
                      basis='320px')]),
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 300}},
            'root': root}


def _custom_binding(prop):
    """Bidirectional property binding to a view custom prop,
    for editor inputs the library reads back on save. The
    bidirectional flag belongs inside CONFIG: the property
    binding schema (knowledge/raw/binding-schemas/
    binding-property.json) puts it there, and IA's own
    example does the same. HUNT-55 proved the binding level
    copy alone runs one way, so a pick never writes back.
    HUNT-59 (polish round 8): this builder emitted binding
    level only, so running it would have reintroduced
    HUNT-55 on the three compare pickers, the only
    _custom_binding use. Both copies now match the live
    BatchesPanel view and the tag bindings."""
    return {'binding': {'type': 'property',
                        'config': {'path': 'view.custom.' + prop,
                                   'bidirectional': True},
                        'bidirectional': True}}


def settings_projection_view():
    """BT projection settings (Tier 2 item 9): the dashed
    projection series on the live chart is built by
    roastery.core.projection_points from the current BT and
    RoR. Linear extends at the current RoR; Quadratic lets
    the RoR drift linearly and applies only after five
    minutes elapsed, exactly as Artisan updateProjection
    gates it. Display only, never stored."""
    mode_dd = tag_dropdown('ProjModeDropdown', 'ProjectionMode', [
        {'value': 'Linear', 'label': 'Linear (current RoR)'},
        {'value': 'Quadratic', 'label': 'Quadratic (RoR trend)'}])
    root = settings_section('SettingsProjectionRoot', 'Projection',
        'Where the bean curve is heading, Artisan style: a '
        'dashed projection line on the live chart extending '
        'two minutes forward from the current bean temp and '
        'rate of rise. BT only.', [
        cfg_row('ProjRow1', [
            cfg_field('ProjEnabledField', 'Projection on',
                      check_in('ProjEnabledCheck',
                               'ProjectionEnabled'),
                      basis='160px'),
            cfg_field('ProjModeField', 'Mode', mode_dd,
                      basis='260px')]),
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 220}},
            'root': root}


def settings_playback_view():
    """Tier 2 items 11, 12 and 14 settings: background
    playback prompts, auto event suggestions, and display
    smoothing for the BT line. All three are advisory or
    display only: prompts and suggestions never write Fan,
    Heat or an event tag, and smoothing shapes only the
    chart dataset, never a stored temp or the RoR math."""
    pb_note = label('PbSoundNote',
        'Sound is visual only in this build: the Perspective '
        'client has no clean beep API reachable from its '
        'scripting layer, so the banner prompt is the signal '
        'and this switch is stored for when a sound route '
        'exists.', 'roast-note',
        position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    playback = settings_section('PlaybackSection', 'Background Playback',
        'When a background ghost is loaded, its Fan and Heat '
        'changes and its Drop prompt on the Roast page at their '
        'elapsed times, Artisan playback style, each exactly '
        'once. Prompts only: nothing is applied automatically, '
        'Fan and Heat stay manual.', [
        cfg_row('PbRow1', [
            cfg_field('PbEnabledField', 'Playback prompts on',
                      check_in('PbEnabledCheck', 'PlaybackEnabled'),
                      basis='190px'),
            cfg_field('PbSoundField', 'Beep with prompts',
                      check_in('PbSoundCheck', 'PlaybackSound'),
                      basis='170px'),
            cfg_field('PbNoteField', 'Sound note', pb_note,
                      basis='320px')]),
    ])
    suggestions = settings_section('SuggestSection', 'Event Suggestions',
        'When the live bean temp crosses a phase target temp '
        'from the Targets section (Dry End temp, FC temp), the '
        'Roast page suggests the event once. Suggestion only: '
        'the event is stamped only when you press its normal '
        'button, which also clears the suggestion.', [
        cfg_row('SgRow1', [
            cfg_field('SgDryField', 'Suggest Dry End',
                      check_in('SgDryCheck', 'SuggestDryEndEnabled'),
                      basis='170px'),
            cfg_field('SgFcField', 'Suggest FC Start',
                      check_in('SgFcCheck', 'SuggestFcEnabled'),
                      basis='170px')]),
    ])
    smooth_dd = tag_dropdown('DispSmoothDropdown', 'DisplaySmoothing', [
        {'value': 0, 'label': '0 - Off (raw temps)'},
        {'value': 1, 'label': '1 - Light'},
        {'value': 2, 'label': '2'},
        {'value': 3, 'label': '3 - Medium'},
        {'value': 4, 'label': '4'},
        {'value': 5, 'label': '5 - Strongest'}])
    display = settings_section('DisplaySection', 'Display Smoothing',
        'Optional smoothing of the bean temp LINE on the live '
        'chart, Artisan smoothETBT style. Display only: stored '
        'temps stay raw and the rate of rise is computed from '
        'the raw temps exactly as before, at every level.', [
        cfg_row('DsRow1', [
            cfg_field('DsLevelField', 'BT line smoothing level',
                      smooth_dd, basis='260px')]),
    ])
    root = flex('root', 'column', [playback, suggestions, display],
                classes='roast-gap-12')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 560}},
            'root': root}


def settings_alarms_view():
    """Alarm table (Tier 1 item 6): the Artisan style alarm
    definitions live in the AlarmDefsJson tag and are evaluated
    by roastery.core.evaluate_alarms on every temp change and
    press. The table is a read only view of the definitions;
    the editor below it stages one definition in the
    AlarmEditor tags (tag bindings: view.custom property
    bindings do not write user edits back in this build) and
    Save, Add and Delete rewrite the definitions through the
    library. The three lite alarm tags remain in the UDT,
    unused by the views."""
    cols = [
        {'field': 'idx', 'header': {'title': '#'}, 'width': 32},
        {'field': 'name', 'header': {'title': 'Name'}, 'width': 128},
        {'field': 'enabled', 'header': {'title': 'On'}, 'width': 38},
        {'field': 'guard', 'header': {'title': 'Guard'}, 'width': 74},
        {'field': 'offsetSec', 'header': {'title': 'Offset (s)'},
         'width': 72},
        {'field': 'source', 'header': {'title': 'Source'},
         'width': 54},
        {'field': 'cond', 'header': {'title': 'Cond'}, 'width': 46},
        {'field': 'value', 'header': {'title': 'Value'},
         'width': 58},
        {'field': 'message', 'header': {'title': 'Message'},
         'width': 180},
        {'field': 'action', 'header': {'title': 'Action'},
         'width': 68},
    ]
    table = {'type': 'ia.display.table', 'meta': {'name': 'AlarmTable'},
             'props': {'data': [], 'columns': cols,
                       'pager': {'enabled': False},
                       'rows': {'height': 32},
                       'header': {'height': 32, 'style': {
                           'classes': 'roast-table-header'}},
                       'style': {'classes': 'roast-table-sm roast-cols-full'}},
             'propConfig': {'props.data': {'binding': prop_binding(
                 'view.custom.alarmsDs')}},
             # Fixed basis, not auto: a virtualized table at
             # auto height collapses to zero rendered rows in
             # this build (proven in the Tier 1 scratch round);
             # the table scrolls internally past this height.
             'position': {'grow': 0, 'shrink': 0, 'basis': '190px'}}

    ED = '[default]Roastery/AlarmEditor/'

    def ed_text(name, member):
        return {'type': 'ia.input.text-field', 'meta': {'name': name},
                'props': {'text': '',
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.text': {'binding': tag_binding(
                    ED + member, bidirectional=True)}}}

    def ed_num(name, member):
        return {'type': 'ia.input.numeric-entry-field',
                'meta': {'name': name},
                'props': {'value': 0, 'format': '0',
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.value': {'binding': tag_binding(
                    ED + member, bidirectional=True)}}}

    def ed_check(name, member):
        return {'type': 'ia.input.checkbox', 'meta': {'name': name},
                'props': {'selected': False, 'text': '',
                          'style': {'classes': 'roast-checkbox'}},
                'propConfig': {'props.selected': {'binding':
                    tag_binding(ED + member, bidirectional=True)}}}

    def ed_drop(name, member, options):
        return {'type': 'ia.input.dropdown', 'meta': {'name': name},
                'props': {'options': options,
                          'value': options[0]['value'],
                          'style': {'classes': 'roast-input'}},
                'propConfig': {'props.value': {'binding': tag_binding(
                    ED + member, bidirectional=True)}}}

    idx_options = [{'value': i, 'label': 'Alarm %d' % (i + 1)}
                   for i in range(12)]
    load_row = flex('AlarmLoadRow', 'row', [
        cfg_field('AlIdxField', 'Edit alarm',
                  ed_drop('AlIdxDrop', 'Idx', idx_options),
                  basis='150px'),
        button('AlLoadButton', 'Load',
               'roast-btn roast-btn-sm roast-btn-ghost',
               events={'component': {'onActionPerformed': {
                   'scope': 'G', 'type': 'script',
                   'config': {'script':
                       "\timport roastery.core\n"
                       "\troastery.core.alarm_editor_load_idx(self)\n"}}}}),
        label('AlCountLabel', '', 'roast-note',
              prop_config={'props.text': {'binding': expr_binding(
                  "'Alarms defined: ' + {view.custom.alarmCount}")}})],
        align='flex-end', wrap='wrap', classes='roast-gap-12')
    ed_row1 = cfg_row('AlEdRow1', [
        cfg_field('AlNameField', 'Name', ed_text('AlNameIn', 'Name'),
                  basis='200px'),
        cfg_field('AlMsgField', 'Message',
                  ed_text('AlMsgIn', 'Message'), basis='260px'),
        cfg_field('AlEnabledField', 'Enabled',
                  ed_check('AlEnabledCheck', 'Enabled'),
                  basis='90px')])
    ed_row2 = cfg_row('AlEdRow2', [
        cfg_field('AlGuardField', 'Guard event',
                  ed_drop('AlGuardDrop', 'Guard',
                          [{'value': g, 'label': g} for g in
                           ('None', 'Charge', 'TP', 'Dry End',
                            'FC Start', 'FC End', 'SC Start',
                            'SC End', 'Drop')]),
                  basis='150px'),
        cfg_field('AlOffsetField', 'Offset (sec)',
                  ed_num('AlOffsetNum', 'OffsetSec'), basis='110px'),
        cfg_field('AlSourceField', 'Source',
                  ed_drop('AlSourceDrop', 'Source',
                          [{'value': s, 'label': s}
                           for s in ('BT', 'RoR', 'Time')]),
                  basis='110px'),
        cfg_field('AlCondField', 'Condition',
                  ed_drop('AlCondDrop', 'Cond',
                          [{'value': '>=', 'label': '>='},
                           {'value': '<=', 'label': '<='}]),
                  basis='100px'),
        cfg_field('AlValueField', 'Value',
                  ed_num('AlValueNum', 'Value'), basis='110px'),
        cfg_field('AlActionField', 'Action',
                  ed_drop('AlActionDrop', 'Action',
                          [{'value': 'Banner', 'label': 'Banner'},
                           {'value': 'Message', 'label': 'Message'}]),
                  basis='130px')])
    btn_row = flex('AlBtnRow', 'row', [
        button('AlSaveButton', 'Save Alarm',
               'roast-btn roast-btn-sm roast-btn-primary',
               events=lib_event('roastery.core.alarm_editor_save(self)')),
        button('AlAddButton', 'Add as New',
               'roast-btn roast-btn-sm roast-btn-green',
               events=lib_event('roastery.core.alarm_editor_add(self)')),
        button('AlDeleteButton', 'Delete Alarm',
               'roast-btn roast-btn-sm roast-btn-charge',
               events=lib_event(
                   'roastery.core.alarm_editor_delete(self)')),
        label('AlNoteLabel', '', 'roast-note-success',
              position={'grow': 1, 'shrink': 1, 'basis': '0px'},
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.alarmNote')}})],
        align='center', wrap='wrap', classes='roast-gap-12')
    alarm_wrap = phone_cols_wrap(
        'AlarmTablePhoneWrap', 'AlColsToggleButton', table, [
            {'field': 'name', 'header': {'title': 'Name'},
             'width': 90},
            {'field': 'enabled', 'header': {'title': 'On'},
             'width': 34},
            {'field': 'source', 'header': {'title': 'Source'},
             'width': 60},
            {'field': 'value', 'header': {'title': 'Value'},
             'width': 56}],
        'roast-table-sm')
    root = settings_section('SettingsAlarmsRoot', 'Alarms',
        'Alarm definitions, Artisan style: an alarm arms after '
        'its guard event plus the offset, then watches the bean '
        'temp, the rate of rise, or the elapsed time. Banner '
        'alarms show on the Roast page while the condition '
        'holds; Message alarms latch until the next charge. '
        'Definitions live in one tag and are evaluated by the '
        'library on every temp change.', [
        table, alarm_wrap, load_row, ed_row1, ed_row2, btn_row])
    return {'custom': {'showAllCols': False,
                       'alarmsDs': None, 'alarmCount': 0,
                       'alarmIdx': 0, 'alarmNote': ''},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 560}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.core\n"
                    "\troastery.core.alarms_startup(self)\n"}}}},
            'root': root}


def settings_metadata_view():
    form = metadata_form('MetaForm', 'Batch Metadata',
                         'Save Batch Details', CONFIG_SUBMIT_SCRIPT,
                         "\tpass\n")
    saved_lbl = label('FormSavedLabel', '', 'roast-note-success',
                      prop_config={'props.text': {'binding': prop_binding(
                          'view.custom.formSaved')}})
    root = settings_section('MetadataSection', 'Batch Metadata Defaults',
        'These values live on the current batch tags: they are the '
        'defaults a new batch starts with, and editing them during '
        'a roast edits the running batch. A saved batch is edited '
        'from the Log tab instead (slide over editor).',
        [form, saved_lbl])
    root['meta']['name'] = 'root'
    return {'custom': {'formSaved': ''}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 560}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script': CONFIG_STARTUP_SCRIPT}}}},
            'root': root}


def settings_customs_view():
    rows = []
    for i in (1, 2, 3, 4):
        rows.append(cfg_row(f'CustomRow{i}', [
            cfg_field(f'CustomNameField{i}', f'Custom {i} name',
                      text_in(f'CustomNameIn{i}', f'CustomEvent{i}Name')),
            cfg_field(f'CustomKindField{i}', f'Custom {i} kind',
                      text_in(f'CustomKindIn{i}', f'CustomEvent{i}Kind'))]))
    root = settings_section('SettingsCustomsRoot', 'Custom Events',
        'Names and kinds for the four custom event buttons. Kind '
        'is a free label (Airflow, Note, Info, ...).', rows)
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 300}},
            'root': root}


def settings_display_view():
    """Curve display options (Tier 3 item 15) and phases from
    background (Tier 3 item 16). Item 15 follows the Artisan
    CurveStyles group: per curve line width and style for BT,
    RoR and the ghost, a fill toggle under the RoR curve, and
    the event marker size. The tags bind straight onto the
    canvas chart series props in main_chart (line width, line
    type, area opacity, reference line endpoint size), so a
    change here restyles the live chart at once and the
    defaults (BT 3 solid, RoR 2 solid, ghost 2 solid, fill
    off, marker 4) reproduce the earlier fixed look exactly.
    Draw style (step) from Artisan is not offered: the BT and
    RoR curves are smoothed samples, and a step draw would
    misstate them; the Fan and Heat strip already steps.
    Item 16: the toggle stages nothing itself. The ghost phase
    boundaries were staged on the BgPhase tags when the ghost
    loaded (library, both ghost routes); with the toggle on,
    the PhasesBar proportions and the chart phase bands follow
    the ghost instead of the saved targets. Saved values in
    SettingsTargets are never overwritten by this option."""
    width_opts = lambda vals: [{'value': v, 'label': '%d px' % v}
                               for v in vals]
    style_opts = [{'value': 'solid', 'label': 'Solid'},
                  {'value': 'dashed', 'label': 'Dashed'},
                  {'value': 'dotted', 'label': 'Dotted'}]
    align_opts = [{'value': 'charge', 'label': 'CHARGE'},
                  {'value': 'dryEnd', 'label': 'DRY'},
                  {'value': 'fcStart', 'label': 'FCs'},
                  {'value': 'fcEnd', 'label': 'FCe'},
                  {'value': 'scStart', 'label': 'SCs'},
                  {'value': 'scEnd', 'label': 'SCe'},
                  {'value': 'drop', 'label': 'DROP'}]
    display = settings_section('DisplaySection', 'Curve Display',
        'How the live curves are drawn, Artisan CurveStyles '
        'style: line width and style per curve, an optional '
        'fill under the rate of rise curve, and the size of '
        'the event markers on the bean curve. Colors do not '
        'change here; they stay the app palette in both themes. '
        'The compare chart aligns its curves on the event '
        'chosen below (Artisan alignEvent: Charge, Dry End, '
        'First Crack start and end, Second Crack start and '
        'end, Drop); the same choice sits on the Log compare '
        'row, and both write the one CompareAlignEvent tag.', [
        cfg_row('DispRow1', [
            cfg_field('DispBtWField', 'Bean temp width',
                      tag_dropdown('DispBtWDrop', 'DispBtWidth',
                                   width_opts((1, 2, 3, 4, 5))),
                      basis='170px'),
            cfg_field('DispBtSField', 'Bean temp style',
                      tag_dropdown('DispBtSDrop', 'DispBtStyle',
                                   style_opts), basis='170px'),
            cfg_field('DispRorWField', 'Rate of rise width',
                      tag_dropdown('DispRorWDrop', 'DispRorWidth',
                                   width_opts((1, 2, 3, 4, 5))),
                      basis='170px'),
            cfg_field('DispRorSField', 'Rate of rise style',
                      tag_dropdown('DispRorSDrop', 'DispRorStyle',
                                   style_opts), basis='170px')]),
        cfg_row('DispRow2', [
            cfg_field('DispGhostWField', 'Ghost width',
                      tag_dropdown('DispGhostWDrop', 'DispGhostWidth',
                                   width_opts((1, 2, 3, 4, 5))),
                      basis='170px'),
            cfg_field('DispGhostSField', 'Ghost style',
                      tag_dropdown('DispGhostSDrop', 'DispGhostStyle',
                                   style_opts), basis='170px'),
            cfg_field('DispFillField', 'Fill under RoR',
                      check_in('DispFillCheck', 'DispRorFill'),
                      basis='150px'),
            cfg_field('DispMarkerField', 'Event marker size',
                      tag_dropdown('DispMarkerDrop', 'DispMarkerSize',
                                   width_opts((2, 4, 6, 8, 10))),
                      basis='170px')]),
        cfg_row('DispRow3', [
            cfg_field('DispAxisFmtField', 'Time axis format',
                      tag_dropdown('DispAxisFmtDrop', 'DispAxisFormat',
                                   [{'value': 'm:ss',
                                     'label': 'Artisan (m:ss)'},
                                    {'value': 'mm:ss',
                                     'label': 'Padded (mm:ss)'}]),
                      basis='170px'),
            cfg_field('CompareAlignField', 'Compare alignment',
                      tag_dropdown('CompareAlignDrop',
                                   'CompareAlignEvent', align_opts),
                      basis='170px')]),
    ])
    staged = label('BgPhaseReadout', '', 'roast-value',
                   prop_config={'props.text': {'binding': expr_binding(
                       f"if({ref(T('BgPhaseDrySec'))} > 0, "
                       f"'Ghost phases staged: Dry End ' + {mmss_int(ref(T('BgPhaseDrySec')))} + "
                       f"', FC Start ' + {mmss_int(ref(T('BgPhaseFcSec')))} + "
                       f"', Drop ' + {mmss_int(ref(T('BgPhaseDropSec')))}, "
                       f"'No ghost phase boundaries staged (load a background first).')")}})
    phases = settings_section('BgPhaseSection', 'Phases From Background',
        'Phase bands shade the live chart behind the curves '
        '(Drying, Maillard, Development, Cooling), following '
        'the stamped phases and the targets for the phase still '
        'ahead. With this option on, the bands and the phase '
        'bar follow the loaded ghost phase boundaries instead '
        'of the saved targets. The saved target values are '
        'never overwritten; clearing the ghost clears the '
        'staged boundaries.', [
        cfg_row('BgPhaseRow1', [
            cfg_field('BgPhaseToggleField', 'Use ghost phases',
                      check_in('BgPhaseCheck', 'PhaseFromBg'),
                      basis='170px'),
            cfg_field('BgPhaseStagedField', 'Staged ghost phases',
                      staged, basis='380px')]),
    ])
    root = flex('root', 'column', [display, phases],
                classes='roast-gap-12')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 520}},
            'root': root}


def settings_page_view():
    title = label('Title', 'Settings', 'roast-title')
    sub = label('Sub', 'Standing configuration for the roaster. '
                'Changes write live tags and apply immediately.',
                'roast-subtitle')
    head = flex('HeadCol', 'column', [title, sub], classes='roast-gap-8')
    sections = [head]
    for name in ('SettingsRoaster', 'SettingsTargets', 'SettingsRor',
                 'SettingsAuc', 'SettingsProjection',
                 'SettingsPlayback', 'SettingsDisplay',
                 'SettingsAlarms', 'SettingsMetadata',
                 'SettingsCustoms'):
        sections.append(embed(name + 'Embed', 'Views/' + name, {},
                              {'grow': 0, 'shrink': 0, 'basis': 'auto'}))
    content = flex('Content', 'column', sections,
                   classes='roast-content roast-gap-12')
    root = flex('root', 'column', [content], classes='roast-app')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1100, 'height': 1400}},
            'root': root}


# ================================================================ Log pages

def log_page_view():
    title = label('Title', 'Roast Log', 'roast-title')
    sub = label('Sub', 'Previous batches in the database. Select '
                'one for its detail, the editor, or a ghost overlay.',
                'roast-subtitle')
    head_col = flex('HeadCol', 'column', [title, sub],
                    classes='roast-gap-8 roast-log-headcol',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    new_roast_btn = button('NewRoastButton', 'New Roast',
                           'roast-btn roast-btn-sm roast-btn-green',
                           events=lib_event(
                               'roastery.batches.new_roast(self)'))
    new_batch_btn = button('NewBatchButton', 'New Batch',
                           'roast-btn roast-btn-sm roast-btn-primary',
                           events=lib_event(
                               'roastery.batches.open_editor(self, create=True)'))
    # Basis is auto, not a fixed 72px (no overlap pass,
    # 2026-11-13): at 360px the fixed height capped the row
    # while the subtitle needed three lines, so the buttons
    # painted over the text. Auto height plus wrap lets the
    # buttons drop under the text block on narrow screens and
    # sit beside it on wide ones.
    head = flex('HeadRow', 'row', [head_col, new_roast_btn,
                                   new_batch_btn],
                justify='flex-end', align='center', wrap='wrap',
                classes='roast-gap-12 roast-log-head',
                position={'grow': 0, 'shrink': 0, 'basis': 'auto'})
    panel = embed('BatchesPanelEmbed', 'Views/BatchesPanel', {},
                  {'grow': 0, 'shrink': 0, 'basis': 'auto'})
    content = flex('Content', 'column', [head, panel],
                   classes='roast-content roast-gap-12')
    root = flex('root', 'column', [content], classes='roast-app')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 760}},
            'root': root}


def detail_chart():
    p = _canvas_props()
    p['data'] = []
    p['xAxis'] = _canvas_xaxis('Elapsed (mm:ss)', split=11,
                               rotate=30)
    p['yAxis'] = [_canvas_yaxis(150, 460, 'Bean Temp (deg F)',
                                split=6),
                  _canvas_yaxis(0, 40, 'Rate of Rise (deg F/min)',
                                position='right', grid=False,
                                split=4)]
    # The detail page is a single layout at every width, and
    # at phone width the two axis titles plus their label
    # columns crush the plot into a sliver and the titles
    # themselves clip at the card edges (proven at 360px,
    # 2026-11-13). The titles stay off at all widths here:
    # the legend names both series and the events timeline
    # and summary carry the units. Same slimming as the phone
    # main chart.
    for ax in p['yAxis']:
        ax['title']['visible'] = False
        ax['labels']['fontSize'] = 11
        ax['labels']['gap'] = 2
    p['xAxis']['labels']['fontSize'] = 11
    p['series'] = [
        _canvas_series('bt', 'Bean Temp', AMBER, 0, width=3),
        _canvas_series('ror', 'Rate of Rise', SKY, 1, width=2)]
    p['appearance']['colorPalette'] = [AMBER, SKY]
    p['style'] = {'classes': 'roast-chart'}
    return {
        'type': 'ia.canvas-charts.line',
        'meta': {'name': 'DetailChart'},
        'props': p,
        'propConfig': {
            'props.data': {'binding': tag_binding(
                '[default]Roastery/DetailDS')},
            'props.xAxis.max': {'binding': prop_binding(
                'view.custom.detailMaxMs')},
            'props.series[0].referenceLines.items':
                _refline_binding(
                    '[default]Roastery/DetailMarksDS',
                    'roastery.batches.detail_reference_lines()')},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}


def _kv_line(name, caption, custom_key):
    cap = label(name + 'Cap', caption, 'roast-kv-cap',
                position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    v = label(name + 'Val', '--', 'roast-value-right',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.' + custom_key)}})
    return flex(name, 'row', [cap, v], justify='space-between',
                align='baseline', classes='roast-gap-10')


def _ds_table(name, custom_key, cols):
    return {'type': 'ia.display.table', 'meta': {'name': name},
            'props': {'data': [], 'columns': cols,
                      'pager': {'enabled': False},
                      'rows': {'height': 32},
                      'header': {'height': 32},
                      'style': {'classes': 'roast-table-sm'}},
            'propConfig': {'props.data': {'binding': prop_binding(
                'view.custom.' + custom_key)}},
            'position': {'grow': 0, 'shrink': 0, 'basis': '250px'}}



# Tier 3 item 21: calculator inputs and readouts on BatchDetail.
# Inputs bind bidirectionally to the Calculator folder tags (the
# proven tag path; view.custom bindings do not write back in
# this build), and the readouts are expression tags in that
# folder, so the math updates live with no handler code.
CALC_ROOT = '[default]Roastery/Calculator'


def _calc_num(name, member, fmt='0.0'):
    return {'type': 'ia.input.numeric-entry-field',
            'meta': {'name': name},
            'props': {'value': 0, 'format': fmt,
                      'style': {'classes': 'roast-input'}},
            'propConfig': {'props.value': {'binding': tag_binding(
                CALC_ROOT + '/' + member, bidirectional=True)}}}


def _calc_val(name, member, fmt='0.0'):
    return label(name, '--', 'roast-value',
                 prop_config={'props.text': {'binding': fmt_tag(
                     CALC_ROOT + '/' + member, fmt)}})


def _calc_field(name, caption, comp):
    cap = label(name + 'Cap', caption, 'roast-form-caption')
    return flex(name, 'column', [cap, comp], classes='roast-gap-8',
                position={'grow': 1, 'shrink': 1, 'basis': '150px'})


def _calc_row(name, fields):
    return flex(name, 'row', fields, wrap='wrap',
                classes='roast-gap-12')


def _calc_card():
    rows = [
        _calc_row('CalcRow1', [
            _calc_field('CalcChargeField', 'Charge weight (g)',
                        _calc_num('CalcChargeIn', 'ChargeG')),
            _calc_field('CalcLossField', 'Target loss (%)',
                        _calc_num('CalcLossIn', 'LossPct')),
            _calc_field('CalcExpectedField', 'Expected out (g)',
                        _calc_val('CalcExpectedVal', 'ExpectedOutG')),
            _calc_field('CalcExpectedOzField', 'Expected out (oz)',
                        _calc_val('CalcExpectedOzVal',
                                  'ExpectedOutOz', '0.00'))]),
        _calc_row('CalcRow2', [
            _calc_field('CalcOutField', 'Weight out (g)',
                        _calc_num('CalcOutIn', 'OutG')),
            _calc_field('CalcActualLossField', 'Loss from out (%)',
                        _calc_val('CalcActualLossVal',
                                  'ActualLossPct')),
            _calc_field('CalcTempFField', 'Temp (F)',
                        _calc_num('CalcTempFIn', 'TempF')),
            _calc_field('CalcTempCField', 'Temp (C)',
                        _calc_val('CalcTempCVal', 'TempC'))]),
        _calc_row('CalcRow3', [
            _calc_field('CalcTempCInField', 'Temp (C) in',
                        _calc_num('CalcTempCInIn', 'TempCIn')),
            _calc_field('CalcTempFOutField', 'Temp (F) out',
                        _calc_val('CalcTempFOutVal', 'TempFOut')),
            _calc_field('CalcConvGField', 'Weight (g)',
                        _calc_num('CalcConvGIn', 'ConvG')),
            _calc_field('CalcConvOzField', 'Weight (oz)',
                        _calc_val('CalcConvOzVal', 'ConvOz',
                                  '0.00'))]),
        _calc_row('CalcRow4', [
            _calc_field('CalcConvOzInField', 'Weight (oz) in',
                        _calc_num('CalcConvOzInIn', 'ConvOzIn',
                                  '0.00')),
            _calc_field('CalcConvGOutField', 'Weight (g) out',
                        _calc_val('CalcConvGOutVal', 'ConvGOut'))]),
    ]
    return flex('CalcCard', 'column', [
        label('CalcHead', 'Yield and Conversion Calculator',
              'roast-section-title'),
        label('CalcNote',
              'Seeded from this batch weights. Edit any input '
              'and the readouts update live (expression tags in '
              'the Calculator folder).', 'roast-note-sm')] + rows,
        classes='roast-card roast-gap-10',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'})


def batch_detail_view():
    """Log detail: the batch curve (with its event marker lines),
    events timeline, phases and DTR, metadata, and the captured
    button presses audit. Data is staged by
    roastery.batches.stage_detail; this view's custom props are
    filled by detail_startup."""
    back_btn = button('BackButton', 'Back to Log',
                      'roast-btn roast-btn-sm roast-btn-ghost roast-back-btn',
                      position={'grow': 0, 'shrink': 0,
                                'basis': '118px'},
                      events=script_event(
                          "\tsystem.perspective.navigate(page='/log')\n"))
    title = label('Title', 'Batch', 'roast-title-sm',
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.titleText')}})
    sub = label('Sub', '', 'roast-subtitle',
                prop_config={'props.text': {'binding': prop_binding(
                    'view.custom.subText')}})
    title_col = flex('TitleCol', 'column', [title, sub],
                     classes='roast-gap-8')
    ghost_btn = button('GhostButton', 'Use as Ghost',
                       'roast-btn roast-btn-sm roast-btn-purple',
                       events=lib_event(
                           'roastery.batches.set_background(self)'))
    edit_btn = button('EditButton', 'Edit',
                      'roast-btn roast-btn-sm roast-btn-primary',
                      events=lib_event(
                          'roastery.batches.open_editor(self)'))
    export_btn = button('ExportButton', 'Export .alog',
                        'roast-btn roast-btn-sm roast-btn-ghost',
                        events=script_event(
                            "\timport roastery.artisan\n"
                            "\troastery.artisan.export_download(self)\n"))
    csv_btn = button('ExportCsvButton', 'Export CSV',
                     'roast-btn roast-btn-sm roast-btn-ghost',
                     events=lib_event(
                         'roastery.batches.export_csv_download(self)'))
    json_btn = button('ExportJsonButton', 'Export JSON',
                      'roast-btn roast-btn-sm roast-btn-ghost',
                      events=lib_event(
                          'roastery.batches.export_json_download(self)'))
    print_btn = button('PrintSummaryButton', 'Print Summary',
                       'roast-btn roast-btn-sm roast-btn-ghost',
                       events=lib_event(
                           'roastery.batches.export_summary_download(self)'))
    head = flex('HeadRow', 'row', [back_btn, title_col],
                justify='space-between', align='center',
                classes='roast-gap-12 roast-detail-head',
                position={'grow': 0, 'shrink': 0, 'basis': '76px'})
    actions = flex('ActionRow', 'row',
                   [ghost_btn, edit_btn, export_btn, csv_btn,
                    json_btn, print_btn],
                   justify='flex-end', align='center', wrap='wrap',
                   classes='roast-gap-12 roast-detail-actions',
                   position={'grow': 0, 'shrink': 0,
                             'basis': 'auto'})
    # HUNT-24 (polish round 2 hunt): the seed note label sits
    # between the action row and the chart card, bound to
    # view.custom.dSeedNote and hidden by class when empty.
    seed_note = label('SeedNoteLabel', '', 'roast-note',
                      prop_config={
                          'props.text': {'binding': prop_binding(
                              'view.custom.dSeedNote')},
                          'props.style.classes': {'binding':
                              expr_binding(
                                  "if(len({view.custom.dSeedNote}) = 0, "
                                  "'roast-note roast-hidden', "
                                  "'roast-note')")}})
    # Statistics summary line (Tier 3 item 19) on the detail
    # chart card too: the library computes it in detail_startup
    # from the staged document phases (dStatsLine).
    detail_stats = label('DetailStatsLine', '', 'roast-stats-line',
                         position={'grow': 0, 'shrink': 0,
                                   'basis': '20px'},
                         prop_config={'props.text': {'binding':
                             prop_binding('view.custom.dStatsLine')}})
    chart_card = flex('ChartCard', 'column',
                      [detail_chart(), detail_stats,
                       _analyzer_strip(detail=True)],
                      classes='roast-card roast-gap-8',
                      position={'grow': 0, 'shrink': 0,
                                'basis': '538px'})
    events_card = flex('EventsCard', 'column', [
        label('EventsHead', 'Events Timeline', 'roast-section-title'),
        _ds_table('EventsTable', 'eventsDs', [
            {'field': 'event', 'header': {'title': 'Event'}},
            {'field': 'time', 'header': {'title': 'Time'}},
            {'field': 'temp', 'header': {'title': 'Temp'}}])],
        classes='roast-card roast-gap-10',
        position={'grow': 1, 'shrink': 1, 'basis': '320px'})
    analysis_table = _ds_table('AnalysisTable', 'analysisDs', [
        {'field': 'phase', 'header': {'title': 'Phase'}},
        {'field': 'time', 'header': {'title': 'Time'}},
        {'field': 'share', 'header': {'title': 'Share'}},
        {'field': 'gain', 'header': {'title': 'Gain'}},
        {'field': 'avgRor', 'header': {'title': 'Avg RoR'}},
        {'field': 'auc', 'header': {'title': 'AUC'}}])
    analysis_table['props']['style']['classes'] = (
        'roast-table-sm roast-cols-full')
    analysis_wrap = phone_cols_wrap(
        'AnalysisTablePhoneWrap', 'AnColsToggleButton',
        analysis_table, [
            {'field': 'phase', 'header': {'title': 'Phase'},
             'width': 78},
            {'field': 'time', 'header': {'title': 'Time'},
             'width': 58},
            {'field': 'share', 'header': {'title': 'Share'},
             'width': 50},
            {'field': 'avgRor', 'header': {'title': 'Avg RoR'},
             'width': 62}],
        'roast-table-sm')
    summary_card = flex('SummaryCard', 'column', [
        label('SummaryHead', 'Summary', 'roast-section-title'),
        _kv_line('Total', 'Total time', 'dTotal'),
        _kv_line('Dtr', 'Dev ratio (DTR)', 'dDtr'),
        _kv_line('DropT', 'Drop temp', 'dDropTemp'),
        _kv_line('Loss', 'Weight loss', 'dLoss'),
        _kv_line('Auc', 'AUC', 'dAuc'),
        _kv_line('Source', 'Source', 'dSource'),
        label('PhasesVal', '', 'roast-note',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.dPhases')}}),
        label('AnalysisHead', 'Phase Analysis',
              'roast-section-title'),
        analysis_table,
        analysis_wrap,
        _kv_line('Tp', 'Turning point', 'dTp'),
        _kv_line('FcsRor', 'RoR at FC start', 'dFcsRor'),
        _kv_line('TotalRor', 'Total RoR (TP to drop)', 'dTotalRor'),
        _kv_line('Cool', 'Cool phase', 'dCool'),
        _kv_line('Sim', 'BT similarity vs ghost', 'dSimilarity'),
        label('LossHead', 'Loss, Yield and Density',
              'roast-section-title'),
        _kv_line('DefLoss', 'Defects loss', 'dDefectsLoss'),
        _kv_line('TotLoss', 'Total loss', 'dTotalLoss'),
        _kv_line('Yield', 'Total yield', 'dYield'),
        _kv_line('VolGain', 'Volume gain', 'dVolumeGain'),
        _kv_line('MoistLoss', 'Moisture loss', 'dMoistureLoss'),
        _kv_line('OrgLoss', 'Organic loss', 'dOrganicLoss'),
        _kv_line('GreenDens', 'Green density', 'dGreenDensity'),
        _kv_line('RoastDens', 'Roasted density', 'dRoastedDensity'),
        # Between batch line (Tier 3 item 20): the library
        # fills dBbp only when the batch document carries a
        # bbp subdocument; otherwise the line is empty.
        label('BbpLine', '', 'roast-note',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.dBbp')}})],
        classes='roast-card roast-gap-8',
        position={'grow': 1, 'shrink': 1, 'basis': '320px'})
    meta_card = flex('MetaCard', 'column', [
        label('MetaHead', 'Metadata', 'roast-section-title'),
        _ds_table('MetaTable', 'metaDs', [
            {'field': 'field', 'header': {'title': 'Field'}},
            {'field': 'value', 'header': {'title': 'Value'}}])],
        classes='roast-card roast-gap-10',
        position={'grow': 0, 'shrink': 0, 'basis': '300px'})
    mid_row = flex('MidRow', 'row', [events_card, summary_card],
                   wrap='wrap', classes='roast-gap-12',
                   position={'grow': 0, 'shrink': 0,
                             'basis': '820px'})
    press_card = flex('PressCard', 'column', [
        label('PressHead', 'Captured Button Presses',
              'roast-section-title'),
        label('PressNote',
              'One row per control press, captured when it happened '
              '(batch_events). This is the audit trail behind the '
              'events above.', 'roast-note-sm'),
        _ds_table('PressTable', 'pressDs', [
            {'field': 'action', 'header': {'title': 'Action'}},
            {'field': 'time', 'header': {'title': 'Time'}},
            {'field': 'tempF', 'header': {'title': 'Temp (F)'}},
            {'field': 'fan', 'header': {'title': 'Fan'}},
            {'field': 'heat', 'header': {'title': 'Heat'}}])],
        classes='roast-card roast-gap-10',
        position={'grow': 0, 'shrink': 0, 'basis': '316px'},
        prop_config={'props.style.classes': {'binding': expr_binding(
            "if({view.custom.hasPresses}, 'roast-card roast-gap-10', "
            "'roast-card roast-gap-10 roast-hidden')")}})
    calc_card = _calc_card()
    content = flex('Content', 'column',
                   [head, actions, seed_note, chart_card, mid_row,
                    meta_card, calc_card, press_card],
                   classes='roast-content roast-gap-12')
    root = flex('root', 'column', [content], classes='roast-app',
                scripts={'messageHandlers': [{
                    'messageType': 'roastery-detail-refresh',
                    'script': ("\timport roastery.batches\n"
                               "\troastery.batches.detail_startup(self)\n"),
                    'sessionScope': True, 'pageScope': True,
                    'viewScope': False}]})
    return {'custom': {'showAllCols': False,
                       'detailMaxMs': 946710601000,
                       'batchNumber': 0, 'titleText': '',
                       'subText': '', 'dTotal': '--', 'dDtr': '--',
                       'dDropTemp': '--', 'dLoss': '--', 'dAuc': '--',
                       'dSource': '--', 'dPhases': '',
                       'eventsDs': None, 'metaDs': None,
                       'pressDs': None, 'hasPresses': False,
                       'analysisDs': None, 'dTp': '--',
                       'dFcsRor': '--', 'dTotalRor': '--',
                       'dCool': '--', 'dSimilarity': '--',
                       'dDefectsLoss': '--', 'dTotalLoss': '--',
                       'dYield': '--', 'dVolumeGain': '--',
                       'dMoistureLoss': '--', 'dOrganicLoss': '--',
                       'dGreenDensity': '--',
                       'dRoastedDensity': '--',
                       'dBbp': '',
                       'dSeedNote': '',
                       'dStatsLine': ''},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 1500}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.batches\n"
                    "\troastery.batches.detail_startup(self)\n"}}}},
            'root': root}

# ================================================================ write out

def write_view(path_parts, doc):
    # Naming convention (polish phase 4): every view's root
    # container is named <ViewName>Root, whatever name the
    # view builder below gave it.
    if isinstance(doc, dict) and isinstance(doc.get('root'), dict):
        doc['root'].setdefault('meta', {})['name'] = (
            path_parts[-1] + 'Root')
    d = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                     'views', *path_parts)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'view.json'), 'w') as f:
        json.dump(doc, f, indent=2)
    with open(os.path.join(d, 'resource.json'), 'w') as f:
        json.dump(RES, f, indent=2)

OLD_VIEWS = ('Log', 'BatchCard', 'StatTile', 'ControlPanel', 'Settings',
             'Probe', 'Main', 'Config', 'Batches')

def main():
    views_root = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                              'views', 'Views')
    for old in OLD_VIEWS:
        p = os.path.join(views_root, old)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print('removed old view', old)
    # shell + pages
    write_view(['Views', 'RoastPage'], roast_page_view())
    write_view(['Views', 'SettingsPage'], settings_page_view())
    write_view(['Views', 'LogPage'], log_page_view())
    write_view(['Views', 'BatchDetail'], batch_detail_view())
    write_view(['Views', 'TabBar'], tabbar_view())
    write_view(['Views', 'HudBar'], hud_view())
    write_view(['Views', 'ControlDock'], controldock_view())
    # settings sections
    write_view(['Views', 'SettingsRoaster'], settings_roaster_view())
    write_view(['Views', 'SettingsTargets'], settings_targets_view())
    write_view(['Views', 'SettingsRor'], settings_ror_view())
    write_view(['Views', 'SettingsAuc'], settings_auc_view())
    write_view(['Views', 'SettingsProjection'],
               settings_projection_view())
    write_view(['Views', 'SettingsPlayback'],
               settings_playback_view())
    write_view(['Views', 'SettingsDisplay'],
               settings_display_view())
    write_view(['Views', 'SettingsAlarms'], settings_alarms_view())
    write_view(['Views', 'SettingsMetadata'], settings_metadata_view())
    write_view(['Views', 'SettingsCustoms'], settings_customs_view())
    # shared building blocks
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
    editor_dock = {'id': 'batchEditor', 'viewPath': 'Views/BatchEdit',
                   'size': 480, 'show': 'onDemand', 'content': 'cover',
                   'anchor': 'fixed', 'handle': 'hide',
                   'resizable': False}
    tab_dock = {'id': 'tabbar', 'viewPath': 'Views/TabBar', 'size': 62,
                'show': 'visible', 'content': 'push', 'anchor': 'fixed',
                'handle': 'hide', 'resizable': False}
    hud_dock = {'id': 'hud', 'viewPath': 'Views/HudBar', 'size': 54,
                'show': 'visible', 'content': 'cover', 'anchor': 'fixed',
                'handle': 'hide', 'resizable': False}
    pages = {'/': {'viewPath': 'Views/RoastPage'},
             '/settings': {'viewPath': 'Views/SettingsPage'},
             '/log': {'viewPath': 'Views/LogPage',
                      'docks': {'right': [editor_dock]}},
             '/log/detail': {'viewPath': 'Views/BatchDetail',
                             'docks': {'right': [editor_dock]}}}
    config = {'pages': pages,
              'sharedDocks': {'bottom': [tab_dock], 'top': [hud_dock]}}
    with open(os.path.join(pc, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)
    r = dict(RES, files=['config.json'])
    with open(os.path.join(pc, 'resource.json'), 'w') as f:
        json.dump(r, f, indent=2)
    write_library()
    write_named_queries()
    write_styles()
    print('Roastery v4 written to', PROJ)

if __name__ == '__main__':
    main()

if __name__ == '__main__':
    main()
