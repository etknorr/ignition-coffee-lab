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
    base = float(points[-1]['t']) if sec is None or int(sec) < 0         else float(sec)
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



def drop():
    _stamp('Drop', 'Drop')
    write_members([('State', 'Dropped'), ('Mode', 'Cool')])
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
