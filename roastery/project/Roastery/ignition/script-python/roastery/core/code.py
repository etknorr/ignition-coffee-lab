# Roastery core library: roast flow control, RoR derivation, curve
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
