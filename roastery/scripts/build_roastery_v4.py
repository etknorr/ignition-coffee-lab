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
MARKS_DS = '[default]Roastery/EventMarksDS'
BGROR_DS = '[default]Roastery/BackgroundRorDS'
LIVE_DS = '[default]Roastery/LiveCurveDS'
# fan and heat are Double in the chart dataset, matching the
# EventsLog doubles the v4 strip chart read; the stored
# CurveSamples keep Integer levels.
LIVE_COLS = ['t_stamp', 'bean', 'ror', 'fan', 'heat']
SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
NQ_EVENTS_INSERT = 'Roastery/Events/InsertPress'

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
    return typed_empty_dataset(LIVE_COLS, [None, 0.0, 0.0, 0.0, 0.0])


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


def build_marks():
    """Rebuild EventMarksDS from the stamped event tags, as a
    column-per-event marker dataset (marks_dataset). The chart
    draws one named series per event column, so the legend labels
    the vertical lines."""
    from java.util import Date
    members = ['StartTime', 'State']
    for stem, _lbl in MARK_EVENTS[1:]:
        members.append(stem + 'ElapsedSec')
    for i in (1, 2, 3, 4):
        members += ['CustomEvent%dElapsedSec' % i,
                    'CustomEvent%dName' % i]
    vals = read_members(members)
    rows = []
    start = vals['StartTime']
    evs = []
    if start is not None and vals['State'] != 'Idle':
        evs = [(0, 'CHARGE')]
        for stem, lbl in MARK_EVENTS[1:]:
            e = vals[stem + 'ElapsedSec']
            if e is not None and e >= 0:
                evs.append((int(e), lbl))
        for i in (1, 2, 3, 4):
            e = vals['CustomEvent%dElapsedSec' % i]
            if e is not None and e >= 0:
                nm = vals['CustomEvent%dName' % i] or 'CUSTOM'
                evs.append((int(e), nm.upper()))
    ds = marks_dataset(evs)
    system.tag.writeBlocking([MARKS_DS], [ds])


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
    rows = []
    for p, (_t, r) in zip(points, rors):
        rows.append([Date(long(p['t'] * 1000)), p['bt'], r,
                     float(p['fan']) if p['fan'] is not None else None,
                     float(p['heat']) if p['heat'] is not None
                     else None])
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
    record_press('Charge')
    build_overlays()
    build_marks()



def drop():
    _stamp('Drop', 'Drop')
    write_members([('State', 'Dropped'), ('Mode', 'Cool')])
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
    clear_curve_samples()
    _clear_log()
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
    self.view.custom.themeText = str(self.session.props.theme).capitalize()


def theme_toggle(self):
    cur = self.session.props.theme
    new = 'light' if cur == 'dark' else 'dark'
    self.session.props.theme = new
    self.view.custom.themeText = new.capitalize()
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
NQ_EVENTS_SELECT = 'Roastery/Events/SelectByBatch'
NQ_MAX_NUMBER = 'Roastery/Batches/SelectMaxNumber'

SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
EDITOR_CREATE_TAG = '[default]Roastery/EditorCreateMode'
DETAIL_DS = '[default]Roastery/DetailDS'
DETAIL_MARKS = '[default]Roastery/DetailMarksDS'
DETAIL_JSON = '[default]Roastery/DetailDocJson'
DETAIL_REFRESH_MESSAGE = 'roastery-detail-refresh'

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
        return {'BeanName': '', 'Origin': '', 'Region': '', 'Farm': '',
                'Altitude': '', 'Variety': '', 'Process': '',
                'HarvestYear': 2025, 'MoisturePct': 0.0,
                'DensityGL': 0.0, 'ChargeWeightG': 200.0,
                'TargetDropTempF': 415.0, 'RoastLevel': '',
                'OperatorName': '', 'Notes': '', 'WeightOutG': 0.0,
                'BatchNumber': 0}
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
            v = 0 if m in core.FORM_INTS else (0.0 if m in core.FORM_FLOATS else '')
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
        table = self.view.getChild('root').getChild('BatchTable')
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
    root = self.getChild('root')
    if root is None:
        root = self.view.getChild('root')
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
    batch_number = int(self.view.custom.selBatchNumber or 0) \
        if hasattr(self.view.custom, 'selBatchNumber') else 0
    if batch_number <= 0:
        batch_number = int(system.tag.readBlocking(
            [SELECTED_TAG])[0].value or 0)
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
            t = parse_mmss(payload.get(tkey)) if tkey in payload \
                else old.get('t')
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
    return True


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
    self.view.custom.titleText = 'Batch %s - %s' % (
        doc.get('batchNumber'), doc.get('beanName') or '')
    self.view.custom.subText = '%s - %s' % (
        (doc.get('roastStart') or '')[:16].replace('T', ' '),
        doc.get('roastDegree') or '')
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
                      'padding': '12px 16px', 'minWidth': '0px',
                      'overflow': 'hidden'},
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
    'roast-value-md': {'fontSize': '20px', 'fontWeight': '700',
                       'color': 'var(--label)', 'lineHeight': '1.1'},
    'roast-clock': {'fontSize': '27px', 'fontWeight': '700',
                    'color': 'var(--label)', 'fontFamily': 'monospace'},
    'roast-chip': {'fontSize': '13px', 'fontWeight': '600',
                   'color': 'var(--label)', 'maxWidth': '100%',
                   'whiteSpace': 'nowrap', 'overflow': 'hidden',
                   'textOverflow': 'ellipsis'},
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
    'roast-tabbar': {'backgroundColor': 'var(--container)',
                     'borderTop': '1px solid var(--border)',
                     'padding': '6px 100px 6px 10px', 'gap': '8px'},
    'roast-tab-btn': {'fontSize': '15px', 'fontWeight': '700',
                      'borderRadius': '10px', 'padding': '10px 8px',
                      'cursor': 'pointer', 'color': 'var(--label)',
                      'backgroundColor': 'transparent',
                      'border': '1px solid transparent'},
    'roast-hud': {'backgroundColor': 'var(--container)',
                  'borderBottom': '1px solid var(--border)',
                  'padding': '5px 12px', 'gap': '12px'},
    'roast-hud-value': {'fontSize': '17px', 'fontWeight': '700',
                        'color': 'var(--label)',
                        'fontFamily': 'monospace'},
    'roast-hud-cap': {'fontSize': '9px', 'fontWeight': '700',
                      'color': 'var(--neutral-60)',
                      'textTransform': 'uppercase',
                      'letterSpacing': '0.08em'},
    'roast-controldock': {'backgroundColor': 'var(--container)',
                          'borderTop': '1px solid var(--border)',
                          'padding': '8px 10px', 'gap': '8px',
                          'boxShadow': '0 -6px 18px rgba(0,0,0,0.18)'},
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
  .psc-roast-tabbar { padding: 6px 62px 6px 6px; gap: 6px; }
  .psc-roast-tabbar > * { min-width: 0; }
  .psc-roast-tabbar > *:first-child { flex: 0 0 56px !important; }
  .psc-roast-tab-btn { font-size: 13px; padding: 8px 2px;
    white-space: nowrap; overflow: hidden; }
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
    """Phase bar. Segment widths come from the actual event times
    once the roast is dropped; before that (and as the target
    labels) they come from the Settings phase duration targets
    (PhaseDryTargetSec, PhaseMaillardTargetSec, PhaseDevTargetSec),
    so adjusting a target in Settings visibly rebalances the bar.
    The DTR label shows the actual DTR after drop, else the
    DTRTargetPct target."""
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))
    drop_e = ref(T('DropElapsedSec'))
    td = ref(T('PhaseDryTargetSec'))
    tm = ref(T('PhaseMaillardTargetSec'))
    tv = ref(T('PhaseDevTargetSec'))
    tt = f"({td} + {tm} + {tv})"
    dry_w = (f"if({drop_e} >= 0, {dry_e} * 100.0 / {drop_e}, "
             f"{td} * 100.0 / {tt})")
    mai_w = (f"if({drop_e} >= 0, ({fc_e} - {dry_e}) * 100.0 / {drop_e}, "
             f"{tm} * 100.0 / {tt})")
    dev_w = (f"if({drop_e} >= 0, ({drop_e} - {fc_e}) * 100.0 / {drop_e}, "
             f"{tv} * 100.0 / {tt})")

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

    dry_t = (f"'DRYING  ' + if({dry_e} >= 0, {mmss_int(dry_e)} + ' - ' + "
             f"numberFormat({dry_w}, '0') + '%', 'target ' + {mmss_int(td)})")
    mai_t = (f"'MAILLARD  ' + if({fc_e} >= 0, "
             f"{mmss_int(f'({fc_e} - {dry_e})')} + ' - ' + "
             f"numberFormat({mai_w}, '0') + '%', 'target ' + "
             f"{mmss_int(tm)})")
    dev_t = (f"'DEVELOPMENT  ' + if({drop_e} >= 0, "
             f"{mmss_int(f'({drop_e} - {fc_e})')} + ' - ' + "
             f"numberFormat({dev_w}, '0') + '%', 'target ' + "
             f"{mmss_int(tv)})")
    bar = flex('Bar', 'row', [
        seg('DrySeg', 'DRYING', 'roast-seg-drying', dry_w, dry_t),
        seg('MaiSeg', 'MAILLARD', 'roast-seg-maillard', mai_w, mai_t),
        seg('DevSeg', 'DEVELOPMENT', 'roast-seg-development', dev_w, dev_t)],
        classes='roast-gap-8 roast-full')
    heading = label('Heading', 'Phases', 'roast-section-title')
    dtr = label('DtrLabel', 'DTR', 'roast-accent-text',
                prop_config={'props.text': {'binding': expr_binding(
                    f"if({drop_e} >= 0, 'DTR ' + numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', "
                    f"'DTR target ' + numberFormat({ref(T('DTRTargetPct'))}, '0.0') + '%')")}})
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
        wrap='wrap', classes='roast-gap-14')
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

def _elapsed_axis(xaxis_tpl):
    """The v4.1 elapsed axis: a date axis fed epoch based values
    (Date(0) + elapsed seconds), formatted mm:ss. Every chart
    dataset in the project is anchored to the roast's own zero
    (roastery.core.build_live_curve, marks_dataset, build_overlays,
    batches.stage_detail), never to wall clock, so a roast reads
    the same an hour later as it did live, Artisan style. The v4
    axis was wall clock tag history: its mostRecent 30 MIN window
    dropped the bean and RoR lines entirely once a roast was
    older than the window, and the axis labelled itself with the
    date (the date.format default 'M/d')."""
    xaxis = copy.deepcopy(xaxis_tpl)
    xaxis['name'] = 'time'
    xaxis['render'] = 'date'
    xaxis['label'] = {'enabled': True, 'text': 'Elapsed (mm:ss)',
                      'color': ''}
    xaxis['date']['format'] = 'mm:ss'
    return xaxis


def marks_series_list(source='marks'):
    """Event marker lines for an XY chart: one line series per
    event over the library's column-per-event marker dataset
    (roastery.core.marks_dataset). Each series is named for its
    event, so the legend labels the lines (bullet labels do not
    render text on XY line series in this build; proven live).
    Lines are dashed amber, top to bottom of the temp axis, with
    connect off so the gap rows break them."""
    series_tpl, _xa, _ya = _xy_templates()
    out = []
    for col, name in (('charge', 'CHARGE'), ('dryEnd', 'DRY END'),
                      ('fcStart', 'FC START'), ('fcEnd', 'FC END'),
                      ('scStart', 'SC START'), ('scEnd', 'SC END'),
                      ('drop', 'DROP'), ('notes', 'NOTES')):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': source, 'x': 't_stamp', 'y': col}
        s['xAxis'] = 'time'
        s['yAxis'] = 'temp'
        s['render'] = 'line'
        ap = s['line']['appearance']
        ap['stroke']['color'] = '#f59e0b'
        ap['stroke']['width'] = 1.5
        ap['stroke']['opacity'] = 0.9
        ap['stroke']['dashArray'] = '4 3'
        if 'connect' in ap:
            ap['connect'] = False
        ap['bullets'][0]['enabled'] = False
        out.append(s)
    return out


def main_chart(legend_on=True):
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

    xaxis = _elapsed_axis(xaxis_tpl)

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
            'dataSources': {'trend': [], 'plan': [], 'bg': [],
                            'bgRor': [], 'marks': []},
            'xAxes': [xaxis], 'yAxes': [temp_axis, ror_axis],
            'series': [
                series('Background', 'bg', 'bg', 'temp', '#64748b', 2,
                       opacity=0.5),
                series('Background RoR', 'bgRor', 'bgRor', 'ror',
                       '#64748b', 2, opacity=0.4),
                series('Target', 'plan', 'plan', 'temp', '#94a3b8', 2,
                       dash='7 5', opacity=0.85),
                series('Bean Temp', 'trend', 'bean', 'temp', AMBER, 3,
                       fill_opacity=0.13),
                series('Rate of Rise', 'trend', 'ror', 'ror', SKY, 2)] +
                marks_series_list('marks'),
            'legend': {'enabled': legend_on, 'position': 'bottom'},
            # Chart surface transparency is an amCharts prop, not a
            # style class concern (documented exception).
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {
            'props.dataSources.trend': {'binding': tag_binding(
                '[default]Roastery/LiveCurveDS')},
            'props.dataSources.plan': {'binding': tag_binding(
                '[default]Roastery/TargetProfileDS')},
            'props.dataSources.bg': {'binding': tag_binding(
                '[default]Roastery/BackgroundDS')},
            'props.dataSources.bgRor': {'binding': tag_binding(
                '[default]Roastery/BackgroundRorDS')},
            'props.dataSources.marks': {'binding': tag_binding(
                '[default]Roastery/EventMarksDS')}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}


def trace_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, y, color):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': 'live', 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = 'level'
        s['render'] = 'step line'
        s['stepLine']['appearance']['stroke']['color'] = color
        s['stepLine']['appearance']['stroke']['width'] = 2
        s['stepLine']['appearance']['connect'] = True
        s['stepLine']['appearance']['bullets'][0]['enabled'] = False
        return s

    # Same elapsed axis as the main chart (v4.1): the strip used
    # to read the wall clock EventsLog, so its axis showed dates
    # and its steps bunched at the left of a day scale axis. The
    # samples in LiveCurveDS carry fan and heat per temperature
    # change on the elapsed timeline. Legend sits at the bottom:
    # at phone widths a right side legend clipped ('H...' for
    # Heat in Eric's screenshot).
    xaxis = _elapsed_axis(xaxis_tpl)
    xaxis['label'] = {'enabled': False, 'text': '', 'color': ''}
    lvl = copy.deepcopy(yaxis_tpl)
    lvl['name'] = 'level'
    lvl['render'] = 'value'
    lvl['label'] = {'enabled': True, 'text': 'Level', 'color': ''}
    lvl['value']['range'] = {'min': 0, 'max': 10, 'useStrict': True}
    return {
        'type': 'ia.chart.xy', 'meta': {'name': 'TraceChart'},
        'props': {
            'dataSources': {'live': []},
            'xAxes': [xaxis], 'yAxes': [lvl],
            'series': [series('Fan', 'fan', AMBER),
                       series('Heat', 'heat', RED)],
            'legend': {'enabled': True, 'position': 'bottom'},
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {'props.dataSources.live': {'binding':
                       tag_binding('[default]Roastery/LiveCurveDS')}},
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

# ================================================================ Batches (page /batches)

def batches_panel_view():
    """The reusable batches panel for the Log page: a tidy table
    (columns chosen to survive a phone width), selection driven
    actions (Details, Edit via the slide over dock, Use as Ghost,
    Delete behind a confirm). All logic lives in roastery.batches;
    the table reads through the SelectAll named query only."""
    cols = [
        {'field': 'batch_number', 'header': {'title': 'Batch'},
         'width': 70},
        {'field': 'roast_start', 'header': {'title': 'Date'},
         'width': 150, 'render': 'date',
         'dateFormat': 'YYYY-MM-DD h:mm a'},
        {'field': 'bean_name', 'header': {'title': 'Bean'}, 'width': 150},
        {'field': 'drop_temp_f', 'header': {'title': 'Drop (F)'},
         'width': 80},
        {'field': 'total_sec', 'header': {'title': 'Total (s)'},
         'width': 80},
        {'field': 'dtr_pct', 'header': {'title': 'DTR %'}, 'width': 70},
        {'field': 'roast_degree', 'header': {'title': 'Degree'},
         'width': 110},
        {'field': 'id', 'header': {'title': 'ID'}, 'width': 50,
         'visible': False},
    ]
    table = {'type': 'ia.display.table', 'meta': {'name': 'BatchTable'},
             'props': {'data': [], 'columns': cols,
                       'pager': {'enabled': False},
                       'rows': {'height': 40},
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
             'position': {'grow': 0, 'shrink': 0, 'basis': '430px'}}
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
                       'selNote': 'Select a batch for its details, the editor, a ghost overlay, or delete.',
                       'confirmDelete': False},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 560}},
            'root': root}


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
            f_row([f_number('WeightOutG', 'Weight out (g)', 0, 2000)]),
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

ALARM_TEXT = (
    f"if({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}, "
    f"{ref(T('AlarmHighTempMsg'))} + ' -- now ' + numberFormat({ref(T('BeanTempF'))}, '0') + ' F', "
    f"if({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}, "
    f"'Drop approaching -- target ' + numberFormat({ref(T('TargetDropTempF'))}, '0') + ' F', "
    f"'First crack watch -- listen for cracks'))")

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


def state_pill(name):
    return label(name, 'Idle', 'roast-pill',
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
    return flex(name, 'row', [
        label(name + 'Text', '', 'roast-banner-text',
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.alarmText')}})],
        align='center',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
        classes='roast-banner',
        prop_config={'props.style.display': {'binding': expr_binding(
            f"if({ALARM_ACTIVE}, 'flex', 'none')")}})


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

    def field(name, cap, value_binding, cap_binding=None):
        cap_pc = {'props.text': {'binding': cap_binding}} if cap_binding \
            else None
        c = label(name + 'Cap', cap, 'roast-hud-cap',
                  prop_config=cap_pc)
        v = label(name + 'Val', '', 'roast-hud-value',
                  prop_config={'props.text': {'binding': value_binding}})
        return flex(name, 'column', [c, v], classes='',
                    position={'grow': 0, 'shrink': 0, 'basis': 'auto'})

    bean = field('Bean', 'BEAN F', fmt_tag(T('BeanTempF'), '0.0'))
    ror = field('Ror', 'ROR', fmt_tag(T('RateOfRiseF'), '0.0'))
    clock = field('Clock', 'ROAST TIME', prop_binding('view.custom.clockText'),
                  cap_binding=prop_binding('view.custom.clockCaption'))
    phase = field('Phase', 'PHASE', prop_binding('view.custom.phaseText'))
    root = flex('root', 'row',
                [state_pill('HudState'), bean, ror, clock, phase],
                align='center', justify='space-between',
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

def _chart_card(basis, legend_on=True, trace_basis='150px',
                head_stack=False, include_trace=True):
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
    children = [chart_head, main_chart(legend_on=legend_on)]
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


def _trace_card(basis='205px'):
    """The Fan / Heat levels strip as its own card (mobile layout,
    v4.1 declutter): inside the chart card it squeezed the main
    chart and its right side legend clipped at phone widths. On
    its own it gets a bottom legend and room to read.

    Height is load bearing, here and in the desktop card's
    trace_basis: below roughly 120px of chart height the XY
    chart collapses its value axis entirely (series clamp to
    the top edge, only the maximum tick label survives). Proven
    live with an isolated probe at 108px (broken) vs 198px
    (correct) on identical config and data."""
    cap = label('TraceCardCap', 'Fan / Heat Levels', 'roast-caption',
                position={'grow': 0, 'shrink': 0, 'basis': '16px'})
    return flex('TraceCard', 'column', [
        cap, flex('TraceWrapM', 'row', [trace_chart()],
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
                  T('TargetDropTempF'), '0')}})]
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
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' - ' + {ref(T('BeanName'))}")}})
    ws_pill = label('WsPill', 'SR800', 'roast-pill',
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
                    [_chart_card('560px'), _strip_embed(),
                     _phases_embed(), _tiles_row()],
                    classes='roast-gap-14',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    rail_col = flex('RailCol', 'column', [
        embed('ControlsEmbed', 'Views/Controls', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('SummaryEmbed', 'Views/Summary', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('MetaCardEmbed', 'Views/MetaCard', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'})],
        classes='roast-gap-14',
        position={'grow': 0, 'shrink': 0, 'basis': '400px'})
    content_row = flex('ContentRow', 'row', [main_col, rail_col],
                       classes='roast-content roast-gap-14',
                       position={'grow': 0, 'shrink': 0, 'basis': 'auto'})
    large = flex('LargeRoot', 'column',
                 [header, alarm_banner(), content_row],
                 classes='roast-app roast-fillscroll',
                 position={'size': 'large'})

    # ---- small (phone): control first; chart secondary; the
    # primary controls are pinned in the ControlDock embed at the
    # bottom of the layout (above the shared tab bar dock).
    batch_line = label('BatchLine', '', 'roast-chip',
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' - ' + {ref(T('BeanName'))}")}})
    scroll_col = flex('ScrollCol', 'column', [
        batch_line, _chart_card('430px', legend_on=False,
                                head_stack=True, include_trace=False),
        _tiles_row(mobile=True),
        _trace_card(),
        _strip_embed(),
        _phases_embed(),
        embed('ControlsEmbedM', 'Views/Controls', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('SummaryEmbedM', 'Views/Summary', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'}),
        embed('MetaCardEmbedM', 'Views/MetaCard', {},
              {'grow': 0, 'shrink': 0, 'basis': 'auto'})],
        classes='roast-content roast-gap-14 roast-scrollcol',
        position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    small = flex('SmallRoot', 'column', [
        alarm_banner('AlarmBannerM'), scroll_col,
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
                   'alarmText': ''},
        'params': {},
        'propConfig': {
            'custom.clockText': {'binding': expr_binding(CLOCK_EXPR_V4)},
            'custom.clockCaption': {'binding': expr_binding(
                CLOCK_CAPTION_EXPR)},
            'custom.deviationText': {'binding': expr_binding(
                DEVIATION_EXPR)},
            'custom.phaseText': {'binding': expr_binding(PHASE_EXPR)},
            'custom.alarmText': {'binding': expr_binding(ALARM_TEXT)}},
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
    root = settings_section('RoasterSection', 'Roaster',
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
    root = settings_section('TargetSection', 'Targets',
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
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 300}},
            'root': root}


def settings_ror_view():
    live = label('RorLive', '', 'roast-value',
                 prop_config={'props.text': {'binding': expr_binding(
                     f"'RoR now: ' + numberFormat({ref(T('RateOfRiseF'))}, '0.0') + ' F/min'")}})
    root = settings_section('RorSection', 'Rate of Rise',
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


def settings_alarms_view():
    def alarm_row(name, caption, check_member, fields):
        chk = check_in(name + 'Check', check_member)
        chk['position'] = {'grow': 0, 'shrink': 0, 'basis': '30px'}
        cap = label(name + 'Cap', caption, 'roast-alarm-cap',
                    position={'grow': 0, 'shrink': 0, 'basis': '168px'})
        fields[0]['position'] = {'grow': 0, 'shrink': 0, 'basis': '110px'}
        if len(fields) > 1:
            fields[1]['position'] = {'grow': 1, 'shrink': 1,
                                     'basis': '220px'}
        return flex(name, 'row', [chk, cap] + fields, align='center',
                    wrap='wrap', classes='roast-gap-10',
                    position={'grow': 0, 'shrink': 0, 'basis': '48px'})
    root = settings_section('AlarmSection', 'Alarms',
        'Lite alarms shown as the banner on the Roast page.', [
        alarm_row('AlarmHigh', 'High bean temp', 'AlarmHighTempEnabled', [
            num_in('AlarmHighNum', 'AlarmHighTempF'),
            text_in('AlarmHighMsgIn', 'AlarmHighTempMsg')]),
        alarm_row('AlarmDrop', 'Drop approaching', 'AlarmDropEnabled', [
            num_in('AlarmDropNum', 'AlarmDropDeltaF')]),
        alarm_row('AlarmFC', 'First crack watch', 'AlarmFCWatchEnabled', [
            num_in('AlarmFCNum', 'AlarmFCWindowSec')]),
    ])
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 240}},
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
    root = settings_section('CustomSection', 'Custom Events',
        'Names and kinds for the four custom event buttons. Kind '
        'is a free label (Airflow, Note, Info, ...).', rows)
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 900, 'height': 300}},
            'root': root}


def settings_page_view():
    title = label('Title', 'Settings', 'roast-title')
    sub = label('Sub', 'Standing configuration for the roaster. '
                'Changes write live tags and apply immediately.',
                'roast-subtitle')
    head = flex('HeadCol', 'column', [title, sub], classes='roast-gap-8')
    sections = [head]
    for name in ('SettingsRoaster', 'SettingsTargets', 'SettingsRor',
                 'SettingsAlarms', 'SettingsMetadata', 'SettingsCustoms'):
        sections.append(embed(name + 'Embed', 'Views/' + name, {},
                              {'grow': 0, 'shrink': 0, 'basis': 'auto'}))
    content = flex('Content', 'column', sections,
                   classes='roast-content roast-gap-14')
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
                    classes='roast-gap-8',
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
    new_roast_btn = button('NewRoastButton', 'New Roast',
                           'roast-btn roast-btn-sm roast-btn-green',
                           events=lib_event(
                               'roastery.batches.new_roast(self)'))
    new_batch_btn = button('NewBatchButton', 'New Batch',
                           'roast-btn roast-btn-sm roast-btn-primary',
                           events=lib_event(
                               'roastery.batches.open_editor(self, create=True)'))
    head = flex('HeadRow', 'row', [head_col, new_roast_btn,
                                   new_batch_btn],
                justify='flex-end', align='center', wrap='wrap',
                classes='roast-gap-12',
                position={'grow': 0, 'shrink': 0, 'basis': '72px'})
    panel = embed('BatchesPanelEmbed', 'Views/BatchesPanel', {},
                  {'grow': 0, 'shrink': 0, 'basis': 'auto'})
    content = flex('Content', 'column', [head, panel],
                   classes='roast-content roast-gap-14')
    root = flex('root', 'column', [content], classes='roast-app')
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 760}},
            'root': root}


def detail_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, y, axis, color, width, fill_opacity=0.0):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': 'detail', 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = axis
        s['render'] = 'line'
        s['line']['appearance']['stroke']['color'] = color
        s['line']['appearance']['stroke']['width'] = width
        if fill_opacity:
            s['line']['appearance']['fill']['color'] = color
            s['line']['appearance']['fill']['opacity'] = fill_opacity
        s['line']['appearance']['bullets'][0]['enabled'] = False
        return s

    xaxis = _elapsed_axis(xaxis_tpl)
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
        'type': 'ia.chart.xy', 'meta': {'name': 'DetailChart'},
        'props': {
            'dataSources': {'detail': [], 'marks': []},
            'xAxes': [xaxis], 'yAxes': [temp_axis, ror_axis],
            'series': [series('Bean Temp', 'bt', 'temp', AMBER, 3,
                              fill_opacity=0.13),
                       series('Rate of Rise', 'ror', 'ror', SKY, 2)] +
                       marks_series_list('marks'),
            'legend': {'enabled': True, 'position': 'bottom'},
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {
            'props.dataSources.detail': {'binding': tag_binding(
                '[default]Roastery/DetailDS')},
            'props.dataSources.marks': {'binding': tag_binding(
                '[default]Roastery/DetailMarksDS')}},
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


def batch_detail_view():
    """Log detail: the batch curve (with its event marker lines),
    events timeline, phases and DTR, metadata, and the captured
    button presses audit. Data is staged by
    roastery.batches.stage_detail; this view's custom props are
    filled by detail_startup."""
    back_btn = button('BackButton', 'Back to Log',
                      'roast-btn roast-btn-sm roast-btn-ghost',
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
    head = flex('HeadRow', 'row',
                [back_btn, title_col, ghost_btn, edit_btn],
                justify='space-between', align='center', wrap='wrap',
                classes='roast-gap-12',
                position={'grow': 0, 'shrink': 0, 'basis': '76px'})
    chart_card = flex('ChartCard', 'column', [detail_chart()],
                      classes='roast-card roast-gap-8',
                      position={'grow': 0, 'shrink': 0,
                                'basis': '430px'})
    events_card = flex('EventsCard', 'column', [
        label('EventsHead', 'Events Timeline', 'roast-section-title'),
        _ds_table('EventsTable', 'eventsDs', [
            {'field': 'event', 'header': {'title': 'Event'}},
            {'field': 'time', 'header': {'title': 'Time'}},
            {'field': 'temp', 'header': {'title': 'Temp'}}])],
        classes='roast-card roast-gap-10',
        position={'grow': 1, 'shrink': 1, 'basis': '320px'})
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
                  'view.custom.dPhases')}})],
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
                   wrap='wrap', classes='roast-gap-14',
                   position={'grow': 0, 'shrink': 0,
                             'basis': '314px'})
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
        prop_config={'props.style.display': {'binding': expr_binding(
            "if({view.custom.hasPresses}, 'flex', 'none')")}})
    content = flex('Content', 'column',
                   [head, chart_card, mid_row, meta_card, press_card],
                   classes='roast-content roast-gap-14')
    root = flex('root', 'column', [content], classes='roast-app',
                scripts={'messageHandlers': [{
                    'messageType': 'roastery-detail-refresh',
                    'script': ("\timport roastery.batches\n"
                               "\troastery.batches.detail_startup(self)\n"),
                    'sessionScope': True, 'pageScope': True,
                    'viewScope': False}]})
    return {'custom': {'batchNumber': 0, 'titleText': '',
                       'subText': '', 'dTotal': '--', 'dDtr': '--',
                       'dDropTemp': '--', 'dLoss': '--', 'dAuc': '--',
                       'dSource': '--', 'dPhases': '',
                       'eventsDs': None, 'metaDs': None,
                       'pressDs': None, 'hasPresses': False},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 1100}},
            'events': {'system': {'onStartup': {
                'scope': 'G', 'type': 'script',
                'config': {'script':
                    "\timport roastery.batches\n"
                    "\troastery.batches.detail_startup(self)\n"}}}},
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
