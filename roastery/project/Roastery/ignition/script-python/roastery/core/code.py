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

LOG = system.util.getLogger('roastery.core')

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
LIVE_COLS = ['t_stamp', 't_label', 't_sec', 'bean', 'ror',
             'fan', 'heat', 'bg', 'bgRor', 'plan', 'proj',
             'bandDry', 'bandMai', 'bandDev', 'bandCool']
SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
NQ_EVENTS_INSERT = 'Roastery/Events/InsertPress'
NQ_EVENTS_SELECT_BY_COUNTER = 'Roastery/Events/SelectByCounter'
APP_SETTINGS = '[default]Roastery/AppSettings'
PERISCOPE_AVAILABLE_TAG = APP_SETTINGS + '/PeriscopeAvailable'
# ------------------------------------------------------- elapsed axis
# Polish round 1, item 2: every chart dataset anchors its x
# values to this fixed instant instead of the Unix epoch. It is
# midnight in America/Denver (Eric's timezone) on 2000-01-01:
# 946710000000 ms (2000-01-01 07:00 UTC). A canvas time axis
# formats its tick labels in the BROWSER's timezone, so epoch
# anchored elapsed values (Date(0) + elapsed) read 17:02, 17:03
# on a Denver phone (epoch midnight UTC is 17:00 in Denver),
# which looks like a wall clock under the Elapsed (mm:ss)
# title. Anchored to a Denver local midnight instead, the same
# ticks read 00:00, 00:15 through the first hour of elapsed
# time, exactly the mm:ss reading the title promises. The
# anchor is a constant, never derived from the gateway clock,
# so every gateway and every dataset agrees on it. Datasets
# carry Date(AXIS_BASE_MS + elapsed); readers that need elapsed
# seconds back subtract AXIS_BASE_MS (roastery.batches
# _detail_points does).
AXIS_BASE_MS = 946710000000


def elapsed_ms(sec):
    """Elapsed seconds since charge as chart x milliseconds."""
    return AXIS_BASE_MS + long(float(sec) * 1000)


def elapsed_date(sec):
    """Elapsed seconds since charge as a chart x Date."""
    from java.util import Date
    return Date(elapsed_ms(sec))


# ------------------------------------------------- elapsed labels
# Polish round 3 (HUNT-23, reopened by Eric 2026-11-18: the
# axis "says 7:01 7:02... isn't it just 1:00 2:00?"). The
# canvas TIME axis formats dates in the browser's timezone
# and no configuration passthrough changes that on this
# build (round 2 probe, knowledge/notes/
# canvas-chart-timezone-axis.md), so the Denver anchor only
# ever read true in Denver. The charts now run on a
# CATEGORY axis whose category names are elapsed strings
# this library formats: the browser never formats a date,
# so the labels read true elapsed in every timezone
# (proven at Denver, Pacific and UTC in the round 3 axis
# probe and the timezone verification shots).
#
# Consequences, all worked through in the probe:
# - Categories are one per grid step (second_grid below),
#   so the axis stays time proportional and the auto label
#   interval thins the text to whatever fits the width,
#   which is the no overlap rule. Fixed tick steps are NOT
#   exposed by the component on this build (axisLabel
#   interval keys in both advanced and labels are silently
#   dropped, proven with a freshness control), so spacing
#   is Auto only, like Artisan's auto grid.
# - Polish round 6 (HUNT-51, Eric 2026-11-19: the axis must
#   read even increments like 15 30 45 1:00 1:15 1:30, and
#   30 s resolution is fine). The auto interval alone cannot
#   promise that: it samples every Nth category for N from
#   label width and plot width, and N lands on 51 s steps
#   on a full roast. The fix is in the category set itself:
#   second_grid now emits one row per AXIS_GRID_STEP_SEC
#   (30 s), so every category name is an even step and any
#   auto interval stride over them stays even (30, 60, 90,
#   120 s). The blanking shortcut was NOT used: the round 3
#   probe proved blank names merge into a single category
#   and scramble the line, so categories must stay unique
#   and non blank. The cost is quantization: samples,
#   overlays, bands and markers land on the nearest 30 s
#   bucket (at most 15 s off their true second), which Eric
#   accepted as 30 s resolution. Reference lines snap to
#   the same grid in _ref_items, because a line can only
#   draw on a category that exists.
# - Category names must be unique per second or ECharts
#   collapses the duplicates into one slot (proven: blank
#   names merged into a single category and scrambled the
#   line). That rules out blanking non tick seconds and
#   rules out a decimal minutes format (several seconds
#   round onto one name). The formats are m:ss (Artisan's
#   own) and mm:ss.
# - Reference lines take the category NAME as their value
#   (a numeric value is looked up as a name and draws
#   nothing, proven), so _ref_items emits label strings
#   from this same formatter and the two can never drift.


def axis_format():
    """The Display setting for the time axis labels:
    'm:ss' (Artisan style, the default) or 'mm:ss'."""
    try:
        fmt = read_members(['DispAxisFormat'])['DispAxisFormat']
    except Exception:
        fmt = None
    return fmt if fmt in ('m:ss', 'mm:ss') else 'm:ss'


def axis_label(sec, fmt=None):
    """Elapsed seconds since charge as a category name."""
    if fmt is None:
        fmt = axis_format()
    s = int(round(float(sec)))
    if s < 0:
        s = 0
    m, ss = divmod(s, 60)
    if fmt == 'mm:ss':
        return '%02d:%02d' % (m, ss)
    return '%d:%02d' % (m, ss)


# Polish round 6 (HUNT-51): the elapsed axis grid step in
# seconds. Every chart category is a multiple of this step,
# so every label the auto interval can show is an even
# increment (30, 60, 90, 120 s) at any width. 30 s is the
# step Eric named as fine; the grid is the same for the
# phone and desktop instances (they share one dataset tag),
# and the auto interval thins it per instance.
AXIS_GRID_STEP_SEC = 30


def grid_bucket(sec, step=AXIS_GRID_STEP_SEC):
    """Nearest grid step multiple for one elapsed second.
    Integer arithmetic (round half up) so the Jython library
    and the CPython suites agree exactly, including at half
    step boundaries where round() differs between the two.
    A value lands at most step / 2 from its true second."""
    s = int(round(float(sec)))
    return (s + step // 2) // step * step


def second_grid(placed, cols, max_sec, fmt=None,
                fill_cols=()):
    """Dataset rows for a category axis chart: one row per
    AXIS_GRID_STEP_SEC seconds, 0..max_sec, [Date, t_label,
    t_sec] plus one value per column in cols. Callers bucket
    their placed seconds to the grid step first (see
    grid_bucket), so a value lands on its nearest grid row
    and is null elsewhere (the series run connectNulls, so a
    gap of a few buckets bridges without warping the time
    scale), except the cols in fill_cols, which forward fill:
    fan and heat levels are constant between changes, so
    their fill is exact, and their step series need a value
    at every grid row to draw the steps. The grid extends
    past max_sec when a bucketed value lands beyond it, so
    no sample is ever dropped. Every t_label is a multiple
    of the grid step (HUNT-51), so the auto interval can
    only ever show even increments.
    """
    from java.util import Date
    if fmt is None:
        fmt = axis_format()
    rows = []
    last = dict((c, None) for c in fill_cols)
    top = int(max_sec)
    for c in cols:
        keys = placed.get(c, {})
        if keys:
            top = max(top, max(keys))
    for s in range(0, top + 1, AXIS_GRID_STEP_SEC):
        row = [Date(elapsed_ms(s)), axis_label(s, fmt), s]
        for c in cols:
            v = placed.get(c, {}).get(s)
            if c in last:
                if v is not None:
                    last[c] = v
                v = last[c]
            row.append(v)
        rows.append(row)
    return rows
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


# ------------------------------------------------------- toasts
# Polish round 1 phase 3: one shot user feedback through the
# Embr Periscope module's native toasts (react-toastify on the
# client). Periscope toasts are NOT a component: Periscope
# injects its own toast container and exposes a client side JS
# global, fired through its scripting function
# system.perspective.runJavaScriptAsync with arguments passed
# as data (never string built, per the maintainer's guidance).
# This wrapper no-ops silently when the PeriscopeAvailable tag
# is False or anything throws, so a gateway without the module
# behaves exactly as before. The JS side guards on the global
# existing, so a missing module can never surface a client
# error either. Toasts fire only in the session that caused
# them (the default runJavaScriptAsync targeting): the phone
# is the remote control and the desktop is a separate session,
# and a toast is feedback for the person who acted.

TOAST_KINDS = ('success', 'info', 'warning', 'error')
TOAST_JS = ("(content, options) => { "
            "if (typeof periscope !== 'undefined' && periscope "
            "&& periscope.toast) { "
            "if (options && options.theme === 'system') { "
            "options.theme = (typeof window !== 'undefined' "
            "&& window.matchMedia && window.matchMedia("
            "'(prefers-color-scheme: dark)').matches) "
            "? 'dark' : 'light' } "
            "periscope.toast(content, options) } }")


def _toast_theme(self):
    """The react-toastify theme for this session (polish
    phase 4, HUNT-17). A session pinned to the built in dark
    or light theme passes that name straight through. Any
    other session theme (the roastsystem theme in System
    mode) resolves on the client: 'system' is handed to the
    JS side, which maps it through the device's
    prefers-color-scheme media query, the same query the
    roastsystem theme itself resolves with."""
    try:
        t = str(self.session.props.theme)
    except Exception:
        return 'system'
    if t in ('dark', 'light'):
        return t
    return 'system'


def show_toast(self, message, kind='info'):
    """Fire one Periscope toast in the caller's session. kind
    is success, info, warning or error. Never raises."""
    try:
        if not message:
            return
        qv = system.tag.readBlocking([PERISCOPE_AVAILABLE_TAG])[0]
        if not qv.value:
            return
        if kind not in TOAST_KINDS:
            kind = 'info'
        system.perspective.runJavaScriptAsync(
            TOAST_JS,
            {'content': str(message),
             'options': {'type': kind, 'autoClose': 5000,
                         'position': 'top-center',
                         'theme': _toast_theme(self),
                         'closeOnClick': True}})
    except:
        # Polish round 6, HUNT-48: runJavaScriptAsync goes
        # through Periscope to a page that may be closing,
        # and a Java throwable is not a Python Exception in
        # Jython (round 4, HUNT-36), so except Exception
        # does not catch it. Bare except keeps the Never
        # raises promise; a toast to a gone page is nothing
        # to log.
        pass


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
        LIVE_COLS, [None, '', 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0])


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
    if _sim_seeking(now_ms):
        # Cooling seek fast forward in progress (Simulated
        # source only): the device is racing through program
        # rows, so this change is a fast forward artifact, not
        # a roast sample. Advance the seek one step (its
        # landing reseeds the RoR buffer and opens the
        # deferred between batch window) and keep the live
        # pipeline muted until then, so sessions are not
        # flooded with chart rebuilds at the seek's tick rate
        # (polish round 3, HUNT-22: that flood, plus the old
        # blocking seek loop inside drop(), is the window in
        # which dock clicks were swallowed whole).
        sim_seek_advance()
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
    try:
        # Press capture tail (polish round 3, HUNT-22): the
        # last presses of a burst leave ring slots no later
        # press will reconcile, and invokeLater does not
        # fire in any scope on this build (proven in the round
        # 3 audit). The temp change path is the one always on
        # gateway rhythm, so it carries the tail; reconcile
        # self limits to slots past the grace age.
        reconcile_press_pending()
    except Exception:
        pass


# ------------------------------------------------------- display texts
# Polish round 1, items 4, 5 and 6: the HUD and the Roast page
# read three library published texts instead of computing
# their own values in view expression bindings (the pattern
# AnalyzerRorText and BgDeviationText already established).
# Each publisher writes only on change, so a steady roast does
# not churn the tags.

_SEP = ' ' + chr(183) + ' '
STATS_IDLE_TEXT = _SEP.join(['Dry --:-- --', 'Mai --:-- --',
                             'Dev --:-- --', 'DTR --'])


def _publish(member, text):
    cur = read_members([member])[member]
    if cur != text:
        write_members([(member, text)])


def ror_display_text(ror):
    """The HUD RoR reading under Artisan's live display
    convention (polish round 1 item 4; the Artisan source
    evidence is written up in docs/coffee-roaster-app.md).
    Artisan's delta LCD shows its '--' placeholder whenever
    the delta value is None or outside the RoR limits, and
    its plotted RoR holds no values before the roast's
    turning point region. So: before the turning point
    confirms, and whenever the true value falls outside
    [RoRClipLowF, RoRClipHighF], the HUD reads '--'. After
    the turning point it reads the true computed value. The
    RateOfRiseF tag and the stored samples always keep the
    true value; only this display text is gated."""
    vals = read_members(['State', 'TurningPointElapsedSec',
                         'RoRClipLowF', 'RoRClipHighF'])
    if vals['State'] not in ('Roasting', 'Dropped', 'Cooling',
                             'Complete'):
        return '--'
    tp = vals['TurningPointElapsedSec']
    if tp is None or tp < 0 or ror is None:
        return '--'
    lo = vals['RoRClipLowF']
    lo = float(lo) if lo is not None else -18.0
    hi = vals['RoRClipHighF']
    hi = float(hi) if hi is not None else 81.0
    if ror < lo or ror > hi:
        return '--'
    return '%d' % int(round(float(ror)))


def update_ror_display(ror):
    try:
        _publish('RateOfRiseDisplayText', ror_display_text(ror))
    except Exception:
        pass


def phase_label():
    """The roast phase for the HUD (polish round 1 item 6),
    computed in roast order from State plus the stamped event
    elapsed tags. Second Crack is a sub state of Development:
    it shows only once FC Start is stamped too, so an early
    or stray SC stamp can never relabel a young roast. The
    old view expression checked the SC tag first and showed
    'Second Crack' at 03:08 of a roast with no first crack."""
    vals = read_members(['State', 'DryEndElapsedSec',
                         'FirstCrackStartElapsedSec',
                         'SecondCrackStartElapsedSec'])
    state = vals['State']
    if state == 'Idle':
        return 'Pre-charge'
    if state == 'Complete':
        return 'Complete'
    if state == 'Cooling':
        return 'Cooling'
    if state == 'Dropped':
        return 'Dropped'
    fc = vals['FirstCrackStartElapsedSec']
    fc = fc if fc is not None else -1
    sc = vals['SecondCrackStartElapsedSec']
    sc = sc if sc is not None else -1
    if sc >= 0 and fc >= 0:
        return 'Second Crack'
    if fc >= 0:
        return 'Development'
    dry = vals['DryEndElapsedSec']
    if dry is not None and dry >= 0:
        return 'Maillard'
    return 'Drying'


def update_phase_label():
    try:
        _publish('PhaseLabel', phase_label())
    except Exception:
        pass


def shares_100(durations, total):
    """Whole percent shares of durations that always sum to
    100 (HUNT-63). Largest remainder: floor every exact share,
    then hand the leftover points to the largest fractional
    parts (ties go to the longer duration). Independent
    rounding can sum to 99 or 101: a live roast read Dry 44,
    Mai 22, Dev 33. Returns ints aligned with durations, or
    Nones when the total is not positive. When the durations
    do not cover the total (a partial roast with phases still
    missing), the shares cannot sum to 100 by construction,
    so plain rounding is used instead."""
    if total is None or float(total) <= 0:
        return [None] * len(durations)
    total = float(total)
    if abs(sum(durations) - total) > 1.0:
        return [int(round(float(d) * 100.0 / total))
                for d in durations]
    exact = [float(d) * 100.0 / total for d in durations]
    floors = [int(math.floor(e)) for e in exact]
    left = 100 - sum(floors)
    order = sorted(range(len(exact)),
                   key=lambda i: (exact[i] - floors[i], exact[i]),
                   reverse=True)
    for i in order[:max(0, left)]:
        floors[i] += 1
    return floors


def _stats_mmss(sec):
    sec = int(max(0, round(float(sec))))
    return '%d:%02d' % (sec // 60, sec % 60)


def stats_line_text():
    """The Roast page stats line (polish round 1 item 5),
    computed in the library so the durations and the
    percentages always describe the same phases. The old
    view expression took durations from the stamped events
    but percentages from the target plan splits, so an
    unstamped phase read '--:-- 43%'. Now: a completed phase
    shows its actual duration and its actual share of the
    total (the drop total once dropped, elapsed so far
    before that); the current phase shows its live duration
    and live share; future phases show -- for both; DTR
    shows -- until Drop, then the actual value."""
    vals = read_members(['State', 'StartTime', 'DryEndElapsedSec',
                         'FirstCrackStartElapsedSec',
                         'DropElapsedSec'])
    state = vals['State']
    if state == 'Idle' or vals['StartTime'] is None:
        return STATS_IDLE_TEXT
    elapsed = float(elapsed_sec(vals['StartTime']))
    dry = vals['DryEndElapsedSec']
    dry = float(dry) if dry is not None else -1.0
    fc = vals['FirstCrackStartElapsedSec']
    fc = float(fc) if fc is not None else -1.0
    drop = vals['DropElapsedSec']
    drop = float(drop) if drop is not None else -1.0
    total = drop if drop >= 0 else elapsed
    starts = [0.0, dry, fc]
    ends = [dry, fc, drop]
    durs = []
    for i in range(3):
        if ends[i] >= 0 and starts[i] >= 0:
            durs.append(ends[i] - starts[i])
        elif (state == 'Roasting' and starts[i] >= 0
                and (i == 0 or ends[i - 1] >= 0)):
            durs.append(max(0.0, elapsed - starts[i]))
        else:
            durs.append(None)
    shown = [d for d in durs if d is not None]
    shares = shares_100(shown, total)
    share_by_idx = {}
    k = 0
    for i, d in enumerate(durs):
        if d is not None:
            share_by_idx[i] = shares[k]
            k += 1
    segs = []
    for i in range(3):
        if durs[i] is not None:
            segs.append((_stats_mmss(durs[i]),
                         ('%d%%' % share_by_idx[i])
                         if share_by_idx[i] is not None else '--'))
        else:
            segs.append(('--:--', '--'))
    if drop >= 0:
        dev_dur = drop - fc if fc >= 0 else 0.0
        dtr = ('%.0f%%' % (dev_dur * 100.0 / drop)) if drop > 0 \
            else '--'
    else:
        dtr = '--'
    return _SEP.join(['Dry %s %s' % segs[0], 'Mai %s %s' % segs[1],
                      'Dev %s %s' % segs[2], 'DTR %s' % dtr])


def update_stats_line():
    try:
        _publish('StatsLineText', stats_line_text())
    except Exception:
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
    # HUNT-89: the old strict less-than kept the EARLIEST
    # sample holding the minimum; Artisan findTPint scans
    # backward, so the LATEST tied sample is the turning
    # point. Less-than-or-equal keeps the latest, matching
    # the offline read in _computed_for and _phase_analysis.
    if min_e is None or min_e < 0 or temp <= min_t:
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
    from begin_sec on, in degree minutes. Segments are clipped
    to the range with an interpolated temp at begin_sec (the
    same shape as batches._auc_range): a segment straddling
    the begin event contributes only its part after the
    event, instead of being dropped whole. HUNT-62: the old
    form kept only points at or after begin_sec, so with the
    default fixed base of 212 F it undercounted the live AUC
    by the straddling segment (about 0.5 F-min on 1 s samples
    with a Dry End begin, about 8 F-min on a 30 s grid; the
    Artisan profileAUC shape counts the segment ending at
    the begin sample, the live updateAUC counts the newest
    segment each tick, and this clipped form is the exact
    integral from the begin second). Segments at or below
    the base contribute nothing. points: [(t_sec, temp)]
    oldest first."""
    if begin_sec is None:
        return 0.0
    pts = [(float(t), float(v)) for t, v in points]
    auc = 0.0
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t1 <= begin_sec or t1 <= t0:
            continue
        a = max(t0, float(begin_sec))
        va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
        avg = (va + v1) / 2.0
        if avg > base:
            auc += (avg - base) * (t1 - a) / 60.0
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
               '_AlarmFiredJson', 'TurningPointElapsedSec',
               'AlarmMessageSeq']
    members += list(ALARM_GUARD_MEMBERS.values())
    vals = read_members(members)
    if (vals['State'] not in ('Roasting', 'Dropped', 'Cooling')
            or vals['StartTime'] is None):
        if vals['State'] == 'Idle':
            write_members([('AlarmText', ''), ('AlarmActive', False)])
        elif vals['State'] == 'Complete':
            # HUNT-76: a Banner alarm fired during the roast
            # used to stay on the Complete screen forever (the
            # roast is over but nothing re-evaluates alarms in
            # Complete, so the text never cleared even after
            # the bean cooled below the threshold). The roast
            # is over, so Banner texts clear at Finish; a
            # latched Message alarm keeps showing, per its
            # documented rule (latched until the next charge
            # or reset). This branch runs on the Finish press
            # itself (finish records the press after writing
            # Complete) and on any later press or alarm edit
            # while Complete.
            fired = []
            if vals['_AlarmFiredJson']:
                try:
                    fired = system.util.jsonDecode(
                        vals['_AlarmFiredJson'])
                except Exception:
                    fired = []
            texts = []
            for i, a in enumerate(alarm_definitions()):
                if (a.get('action') == 'Message'
                        and i in fired):
                    texts.append(a.get('message')
                                 or a.get('name') or 'Alarm')
            write_members([('AlarmText', ' | '.join(texts)),
                           ('AlarmActive', bool(texts))])
        return
    elapsed = elapsed_sec(vals['StartTime'])
    fired = []
    if vals['_AlarmFiredJson']:
        try:
            fired = system.util.jsonDecode(vals['_AlarmFiredJson'])
        except Exception:
            fired = []
    texts = []
    new_msgs = []
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
                new_msgs.append(msg)
            if i in fired:
                texts.append(msg)
        elif hit:
            texts.append(msg)
    pairs = [('AlarmText', ' | '.join(texts)),
             ('AlarmActive', bool(texts))]
    if fired_changed:
        pairs.append(('_AlarmFiredJson',
                      system.util.jsonEncode(fired)))
    if new_msgs:
        # Polish phase 3: the latched Message value the Roast
        # page watches to fire a one shot Periscope toast. Only
        # NEW latches write it, so the page's property change
        # script toasts once per latch, not per evaluation.
        # Polish phase 4 (HUNT-19): AlarmMessageSeq increments
        # on every new latch batch, and the page's toast
        # trigger watches the SEQUENCE, not the text: two
        # latches carrying identical message text write the
        # same AlarmMessageText twice (no value change, no
        # property change, a missed toast), while the
        # sequence always changes.
        pairs.append(('AlarmMessageText', ' | '.join(new_msgs)))
        pairs.append(('AlarmMessageSeq',
                      int(vals['AlarmMessageSeq'] or 0) + 1))
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
    # Polish round 1 display texts ride the same path, after
    # the turning point tracking above so a TP confirmed by
    # this very sample is already visible to the RoR gate.
    update_ror_display(ror)
    update_phase_label()
    update_dock_actions()
    update_stats_line()


def _reset_live_analytics():
    write_members([('TurningPointElapsedSec', -1),
                   ('TurningPointTempF', 0.0),
                   ('_TpMinTempF', 0.0), ('_TpMinElapsedSec', -1),
                   ('AucLiveFMin', 0.0), ('AucSinceFcFMin', 0.0),
                   ('AucGuideElapsedSec', -1),
                   ('AlarmText', ''), ('AlarmActive', False),
                   ('AlarmMessageText', ''),
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
                   ('AnalyzerHasBg', False),
                   ('RateOfRiseDisplayText', '--'),
                   ('PhaseLabel', 'Pre-charge'),
                   ('StatsLineText', STATS_IDLE_TEXT)])


def clear_background(self=None):
    """Clear the staged background ghost (Settings Background
    Clear button): drop the staged points and label and
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
    if self is not None:
        show_toast(self, 'Background cleared', 'success')


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
                     # The value column must be one type:
                     # seeded definitions carry JSON ints
                     # (430) while the editor always writes
                     # floats (430.0), and toDataSet refuses
                     # the mix, throwing inside
                     # _save_alarm_defs AFTER the definitions
                     # were written, which silently ate the
                     # table refresh, the note and the toast
                     # on every Add and on any Save past the
                     # first row (polish round 3, HUNT-30).
                     # Uniform Double here; the definitions
                     # themselves keep their stored shape.
                     float(a.get('value'))
                     if a.get('value') is not None else None,
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
    show_toast(self, 'Alarm saved: %s' % entry['name'], 'success')


def alarm_editor_add(self):
    defs = alarm_definitions()
    entry = _alarm_from_editor(self)
    defs.append(entry)
    _save_alarm_defs(self, defs)
    alarm_editor_load(self, len(defs) - 1)
    self.view.custom.alarmNote = ('Added alarm %d: %s'
                                  % (len(defs), entry['name']))
    # Polish round 3 (HUNT-28): Save toasted but Add and
    # Delete only wrote the note line; the editor's feedback
    # now goes through the toast choke point on all three.
    show_toast(self, 'Alarm added: %s' % entry['name'],
               'success')


def alarm_editor_delete(self):
    defs = alarm_definitions()
    idx = _alarm_editor_idx(self)
    if 0 <= idx < len(defs):
        gone = defs.pop(idx)
        _save_alarm_defs(self, defs)
        self.view.custom.alarmNote = ('Deleted alarm: %s'
                                      % (gone.get('name') or ''))
        show_toast(self, 'Alarm deleted: %s'
                   % (gone.get('name') or ''), 'success')
        if defs:
            alarm_editor_load(self, min(idx, len(defs) - 1))


# ---------------------------------------------------------------- press capture

# Polish round 3 (HUNT-22): exactly one batch_events row per
# press, guaranteed. The PressEvents group stays the writer in
# Group mode, but the group's design has a structural loss
# window: it reads the LastAction context tags at execution
# time, so when its execution lags behind a press (proven in
# the Tier 3 era at a 1 s scan, and again under the Drop
# cooling seek's render load), two counter edges collapse into
# one execution carrying only the latest action, and the
# earlier press's row is never written. The counter keyed
# reconcile below closes that window.
#
# Every press writes its own context into its own slot of a
# 16 slot ring (the PressSlots tags, slot = counter mod 16):
# one tag write, no read, so concurrent press handlers cannot
# overwrite each other's context. (The audit's first design
# kept the contexts in one shared JSON list, and a four click
# cluster landing inside 0.5 s lost exactly one entry to the
# list's read modify write race, the same press the group
# then collapsed. The ring removes the shared write.) The
# group now stores press_counter on every row it writes, and
# reconcile checks each slotted press against the row key
# (batch_number, press_counter): a press the group missed is
# inserted from its slot with its original context; a press
# the group wrote needs nothing. The unique index on
# (batch_number, press_counter) plus the named query's ON
# CONFLICT DO NOTHING make a double write impossible, whoever
# gets there first. Slots are never cleared; a slot is simply
# overwritten 16 presses later, long after the reconcile
# passes (the next press, the BeanTempF change tail, Charge,
# and Save Batch all run it) have verified it. The horizon
# below bounds the net: a press still missing ten minutes
# later belongs to a workspace the gateway lost anyway.
PRESS_RECONCILE_GRACE_SEC = 3.0
PRESS_RECONCILE_HORIZON_SEC = 600.0
PRESS_SLOT_COUNT = 16
PRESS_SLOTS = '[default]Roastery/PressSlots'
# Polish round 4 (HUNT-36): failure isolation. A named query
# call against a faulted database connection can block for a
# long timeout before it throws, so a reconcile pass that kept
# trying slot after slot could stall a press handler for many
# timeouts in a row, and a fault escaping record_press could
# abort the caller's state transition entirely (the round 3
# wedge: a Reset pressed into a faulted connection left
# LastAction 'Reset' with State still Roasting). Two bounds:
# a pass stops at its first database exception, and that
# exception arms a module level backoff deadline; passes that
# start before the deadline return at once with no database
# calls at all. Together they bound the cost of a faulted
# database to roughly one blocking call per backoff window
# across every caller (record_press, the BeanTempF tick tail,
# charge, and Save Batch), while the press ring keeps every
# press's context in tags, so healing is just the next
# successful pass inserting whatever the group missed.
PRESS_DB_BACKOFF_SEC = 15.0
_PRESS_DB_BACKOFF = {'until_ms': 0}


def _press_db_backoff_active(now_ms):
    return now_ms < _PRESS_DB_BACKOFF['until_ms']


def _press_db_backoff_arm():
    try:
        now_ms = system.date.toMillis(system.date.now())
    except Exception:
        return
    _PRESS_DB_BACKOFF['until_ms'] = (
        now_ms + long(PRESS_DB_BACKOFF_SEC * 1000))


def _press_slot_path(counter):
    return '%s/Slot%02d' % (PRESS_SLOTS,
                            int(counter) % PRESS_SLOT_COUNT)


def _press_slot_write(counter, entry):
    try:
        system.tag.writeBlocking(
            [_press_slot_path(counter)],
            [system.util.jsonEncode(entry)])
    except:
        # A missing tag tree (an older install) must not break
        # the press; the group path still applies there.
        pass


def _press_slot_contexts():
    """All ring contexts currently held, as entry dicts."""
    try:
        paths = ['%s/Slot%02d' % (PRESS_SLOTS, i)
                 for i in range(PRESS_SLOT_COUNT)]
        qvs = system.tag.readBlocking(paths)
    except Exception:
        return []
    out = []
    for qv in qvs:
        raw = qv.value
        if not raw:
            continue
        try:
            e = system.util.jsonDecode(raw)
        except Exception:
            continue
        if isinstance(e, dict) and 'c' in e and 'a' in e:
            out.append(e)
    return out


def reconcile_press_pending(min_age_sec=None):
    """Verify every slotted press landed in batch_events and
    insert any the transaction group missed (see the section
    note). Entries younger than the grace age are skipped,
    because the group normally writes within a scan or two;
    entries older than the horizon are out of the net.
    Returns the number of rows inserted. Never raises:
    capture bookkeeping must not break a control.

    Failure isolation (polish round 4, HUNT-36): the pass
    fails fast. The first named query exception ends the
    pass (no further database calls in it) and arms the
    module level backoff; a pass that starts inside the
    backoff window returns 0 at once with no database calls.
    A pass that completes with no database exception clears
    the backoff."""
    if min_age_sec is None:
        min_age_sec = PRESS_RECONCILE_GRACE_SEC
    try:
        now_ms = system.date.toMillis(system.date.now())
        if _press_db_backoff_active(now_ms):
            return 0
        inserted = 0
        db_failed = False
        for e in _press_slot_contexts():
            age = (now_ms - long(e.get('at') or 0)) / 1000.0
            if age < min_age_sec or age > PRESS_RECONCILE_HORIZON_SEC:
                continue
            try:
                rows = system.db.runNamedQuery(
                    NQ_EVENTS_SELECT_BY_COUNTER, {
                        'batch_number': int(e['b']),
                        'press_counter': long(e['c'])})
                if rows is not None and rows.getRowCount() > 0:
                    continue
            except:
                _press_db_backoff_arm()
                db_failed = True
                break
            try:
                system.db.runNamedQuery(NQ_EVENTS_INSERT, {
                    'batch_number': int(e['b']),
                    'action': e['a'],
                    't_offset_sec': e['t'],
                    'bean_temp_f': e['bt'],
                    'rate_of_rise_f': e['ror'],
                    'fan_level': int(e['f'] or 0),
                    'heat_level': int(e['h'] or 0),
                    'press_counter': long(e['c'])})
                inserted += 1
            except:
                _press_db_backoff_arm()
                db_failed = True
                break
        if not db_failed:
            _PRESS_DB_BACKOFF['until_ms'] = 0
        return inserted
    except:
        return 0


def record_press(action):
    """Capture one control button press. Never raises (polish
    round 4, HUNT-36): the state functions (charge, drop,
    cool, finish, reset_batch, the steppers, the stamps) call
    this in the middle of their transitions, and no capture
    failure may abort or skip a state write again. A failure
    is logged and the counter is returned when it is already
    known (the bump landed), else 0.

    The catch is a BARE except on purpose, here and in the
    other press path catches below: runNamedQuery throws a
    Java exception (FaultedDatabaseConnectionException) when
    the connection is faulted, and a Java throwable is not a
    Python Exception in Jython, so except Exception does not
    catch it. That is exactly how the round 3 wedge escaped
    the old code, proven by the gateway log tracebacks in
    the round 4 fault drill: the fault tore through every
    except Exception on the path and aborted the callers."""
    known = [0]
    try:
        return _record_press_impl(action, known)
    except:
        try:
            import sys as _sys
            LOG.error('record_press failed for action %s: %s'
                      % (action, _sys.exc_info()[1]))
        except:
            pass
        return known[0]


def _record_press_impl(action, known):
    """The record_press body (Eric, 2026-11-12: the button
    presses are the trigger). Every press bumps the
    ActionCounter trigger surface and stamps LastAction tags; in
    PressCaptureMode 'Library' the press row is also written to
    batch_events through the Events/InsertPress named query. In
    'Group' mode a SQLBridge transaction group bound to
    ActionCounter writes the row instead; the press also slots
    its context into the press ring for the reconcile net, so
    a group execution that lagged past the press cannot lose
    its row (polish round 3, HUNT-22; see the section note).
    Returns the counter. known is a one element holder the
    wrapper reads on failure: it is set the moment the counter
    is computed, before any write that could throw."""
    vals = read_members(['ActionCounter', 'BatchNumber', 'StartTime',
                         'BeanTempF', 'RateOfRiseF', 'FanLevel',
                         'HeatLevel', 'PressCaptureMode'])
    elapsed = elapsed_sec(vals['StartTime'])
    counter = int(vals['ActionCounter'] or 0) + 1
    known[0] = counter
    write_members([('ActionCounter', counter), ('LastAction', action),
                   ('LastActionElapsedSec', elapsed),
                   ('LastActionBatchNumber',
                    int(vals['BatchNumber'] or 0)),
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
                'heat_level': int(vals['HeatLevel'] or 0),
                'press_counter': counter})
        except:
            # Capture must never break the control it rides on.
            pass
    else:
        # Slot this press's own context into its ring slot
        # BEFORE any database touch (polish round 4, HUNT-36):
        # the slot write is a tag write and cannot block on
        # the database, so the press's context is safe in the
        # ring even if the reconcile below stalls or fails on
        # a faulted connection. Then reconcile older slotted
        # presses (the BeanTempF tail, Charge and Save Batch
        # run it too); this press is inside the grace age, so
        # the pass leaves it for the group as usual.
        _press_slot_write(counter, {
            'c': counter,
            'b': int(vals['BatchNumber'] or 0),
            'a': action,
            't': elapsed,
            'bt': vals['BeanTempF'],
            'ror': vals['RateOfRiseF'],
            'f': int(vals['FanLevel'] or 0),
            'h': int(vals['HeatLevel'] or 0),
            'at': system.date.toMillis(system.date.now())})
        reconcile_press_pending()
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

    X values are ELAPSED dates (axis base + elapsed seconds,
    polish round 1 item 2), the v4.1 axis: every chart dataset
    is anchored to the roast's own zero, never to wall clock,
    and the axis formats them mm:ss."""
    idx = dict((c, i + 1) for i, c in enumerate(MARK_COLS[1:]))
    rows = []
    for e, lbl in sorted(evs):
        col = _MARK_COL_FOR.get(lbl, 'notes')
        ts = elapsed_date(e)
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


def _ref_items(evs, top_gap=55.0, mid_gap=45.0, mid_top_gap=45.0,
               line_gap=None, grid_step=AXIS_GRID_STEP_SEC):
    """Canvas chart reference line items for (elapsed sec,
    label) events: native ECharts markLines through the
    component's series referenceLines. Polish phase 2 item 3:
    labels live in the reserved band at the top of the plot,
    above the curves. The charts' bean axis tops out at 520 F
    while no curve exceeds about 460 F, so the top band of the
    plot is empty by construction, and every label sits at the
    line end ('end', the top of the line) in that band,
    horizontal and readable.

    A two row stagger was tried first and the component
    cannot do it: 'insideEnd' labels render rotated vertical
    along the line inside the plot, and the label 'offset',
    'distance' and 'rotate' fields are not passed through by
    the component (all three proven live in the 360px spaced
    label screenshots). So there is ONE row, and top_gap is
    sized per chart so any two visible labels are guaranteed
    horizontal clearance: an event closer than top_gap to the
    previous labeled event keeps its line and drops its
    label rather than print touching text; the event strip
    under the chart always carries the name. (mid_gap and
    mid_top_gap remain in the signature for the existing
    callers and are ignored.) Values are category names on
    the elapsed category axis (polish round 3, HUNT-23):
    the axis_label string of the event's second, from the
    same formatter that names the categories.

    Polish round 6 (HUNT-51): the value snaps to the grid
    step first (grid_bucket), because a markLine can only
    draw on a category that exists, and the categories are
    now the 30 s grid steps. An event at 273 s draws its
    line at 270 s, at most 15 s from its true second; the
    exact time still lives in the events strip and the batch
    document. The gap and line thinning below run on the
    snapped seconds, since that is where the lines draw.

    line_gap (round 6, detail chart only) thins the LINES
    themselves: an unlabeled line closer than line_gap to
    the last kept line is dropped, so lines a second or two
    apart do not merge into a solid band at the left edge
    of a short batch. It is deliberately far smaller than
    top_gap (labels need tens of seconds of clearance,
    lines only need a few pixels): a labeled line is never
    dropped, and when a labeled line lands within line_gap
    of a kept unlabeled line the unlabeled one goes instead,
    so every visible label keeps its line. None keeps every
    line, which is the live chart's settled behavior.
    """
    items = []
    secs = []
    last_top = None
    for sec, lbl in sorted(evs, key=lambda e: float(e[0])):
        sec = float(grid_bucket(sec, grid_step))
        if last_top is None or sec - last_top >= top_gap:
            vis = True
            last_top = sec
        else:
            vis = False
        secs.append(sec)
        items.append({
            'value': axis_label(sec),
            'orientation': 'vertical',
            'label': {'visible': vis, 'position': 'end',
                      'text': lbl, 'color': '#f59e0b',
                      'fontSize': 11, 'elementStyle': {}},
            'line': {'color': '#f59e0b', 'width': 1.5,
                     'type': 'dashed', 'opacity': 0.9}})
    if line_gap is not None:
        kept = []
        for sec, item in zip(secs, items):
            labeled = item['label']['visible']
            if kept and sec - kept[-1][0] < line_gap:
                if not labeled:
                    continue
                if not kept[-1][1]['label']['visible']:
                    kept.pop()
            kept.append([sec, item])
        items = [item for _sec, item in kept]
    return items


def event_reference_lines():
    """Reference line items for the live chart's bean series,
    bound through a script transform triggered by the
    EventMarksDS tag (rewritten on every press)."""
    return _ref_items(_live_events(), top_gap=55.0)


def event_reference_lines_compact():
    """Phone variant of the marker labels: the phone chart
    squeezes a whole roast into about 215px, about 0.3 px
    per second, so two labels in the top band need roughly
    175 s of separation not to touch. An event closer than
    that to the previous labeled event keeps its line and
    drops its label; the events strip directly under the
    phone chart names every event, so nothing is lost."""
    return _ref_items(_live_events(), top_gap=175.0)


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
                         'SuggestionActive',
                         'TurningPointElapsedSec'])
    if vals['State'] != 'Roasting' or vals['SuggestionActive']:
        return
    # Turning point guard (the Artisan shape in the docstring
    # above, enforced 2026-11-17): no suggestion before the
    # turning point exists. Without it, a realistic charge
    # temp (the 392 F simulator plateau, above both phase
    # targets) suggested Dry End and FC Start in the first
    # seconds of the roast, and an early FC stamp also stops
    # turning point tracking. On a monotonic curve the guard
    # costs nothing: the TP confirms at the first clear rise
    # off the charge minimum.
    if (vals['TurningPointElapsedSec'] is None
            or vals['TurningPointElapsedSec'] < 0):
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
    a fixed horizon. A phase that has been stamped ends at
    its stamp; a phase still ahead ends at its effective target
    boundary (the ghost boundaries when phases from background
    is on and staged, else the saved phase duration targets).
    Polish round 1 item 1: no range here may depend on the
    latest sample or on now, so the ranges change only when a
    phase boundary changes (an event stamp, a target edit, a
    ghost staged or cleared), never on an ordinary tick. The
    cooling band used to run to the latest sample and grew
    every second; it now runs to the effective drop boundary,
    or two minutes past a drop stamped later than that.
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
    if drop_s >= 0:
        cool_end = max(b_drop, drop_s + 120)
        if cool_end > drop_s:
            out.append(('bandCool', float(drop_s),
                        float(cool_end)))
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

    X values are elapsed seconds on the category axis
    (polish round 3, HUNT-23): every row carries its
    t_label category name from axis_label, one row per
    second, so the labels are true elapsed in any browser
    timezone. The t_stamp Date column stays for the
    readers that subtract the axis base.
    RoR is recomputed from the stored temps with
    compute_ror_series and the current parameters (live
    variant), the same math as RateOfRiseF and the saved
    batches, so the drawn curve can never disagree with them.
    Fan and heat ride along for the levels strip, same axis."""
    points = curve_points()
    pts = [(float(p['t']), p['bt']) for p in points]
    rors = compute_ror_series(pts, ror_params(), offline=False)
    # Polish round 1 item 4 (Artisan display convention; the
    # evidence is written up in docs/coffee-roaster-app.md):
    # the DRAWN RoR column follows Artisan's live display
    # rules, not the raw series. Artisan holds no delta values
    # outside CHARGE..DROP, starts its RoR line a short span
    # after CHARGE, and (RoRlimitFlag, on by default) blanks
    # any displayed value outside the RoR limits. Roastery's
    # gate: samples before the confirmed turning point draw
    # nothing (the dip's steep negative slope is the charge
    # transient, not a roast signal), and any value outside
    # [RoRClipLowF, RoRClipHighF] draws nothing. The stored
    # samples, the RateOfRiseF tag and the offline
    # recomputation in saved batches keep the true values.
    _disp = read_members(['TurningPointElapsedSec', 'RoRClipLowF',
                          'RoRClipHighF'])
    _tp = _disp['TurningPointElapsedSec']
    _tp = float(_tp) if _tp is not None else -1.0
    _lo = _disp['RoRClipLowF']
    _lo = float(_lo) if _lo is not None else -18.0
    _hi = _disp['RoRClipHighF']
    _hi = float(_hi) if _hi is not None else 81.0
    # The projection is a forecast, not a display of the past:
    # it extends from the TRUE current RoR, so it is computed
    # from the ungated series before the gate is applied.
    proj_pts = projection_points(pts, rors)
    rors = [(t, r if (r is not None and _tp >= 0 and t >= _tp
                      and _lo <= r <= _hi) else None)
            for t, r in rors]
    # The canvas line chart reads ONE wide dataset (v4.4
    # migration): the ghost and target overlays merge into
    # the same grid, each column null where its source has
    # no point at that grid row. The chart series set
    # connectNulls, so the merge nulls never break a line;
    # they are not data gaps. Columns bg, bgRor and plan
    # come from the overlay datasets build_overlays
    # maintains. (Before polish round 3 the merge keyed rows
    # by union timestamp on the time axis; the category axis
    # needs the regular grid second_grid builds, and a point
    # at a fractional second lands on its nearest grid
    # step, polish round 6 HUNT-51.)
    placed = {}
    max_sec = [-1]

    def put(sec, col, val):
        # Polish round 6 (HUNT-51): values land on the
        # nearest 30 s grid bucket, so the drawn position is
        # at most 15 s from the true second. The stored
        # samples keep the true seconds; only this drawn
        # grid quantizes.
        s = grid_bucket(sec)
        if s < 0:
            s = 0
        colmap = placed.get(col)
        if colmap is None:
            colmap = {}
            placed[col] = colmap
        colmap[s] = val
        if s > max_sec[0]:
            max_sec[0] = s

    # Display smoothing (item 12) shapes ONLY this bean column:
    # the samples and the RoR column above stay raw.
    display = display_smoothed([p['bt'] for p in points])
    for p, (_t, r), disp in zip(points, rors, display):
        put(p['t'], 'bean', disp)
        put(p['t'], 'ror', r)
        put(p['t'], 'fan', float(p['fan']) if p['fan'] is not None
            else None)
        put(p['t'], 'heat', float(p['heat'])
            if p['heat'] is not None else None)
    for t, v in proj_pts:
        put(t, 'proj', v)
    for path, col in ((BACKGROUND_DS, 'bg'), (BGROR_DS, 'bgRor'),
                      (TARGET_DS, 'plan')):
        ds = system.tag.readBlocking([path])[0].value
        if ds is None:
            continue
        for i in range(ds.rowCount):
            t = ds.getValueAt(i, 't_stamp')
            v = ds.getValueAt(i, col)
            if t is not None and v is not None:
                put((long(t.getTime()) - AXIS_BASE_MS) / 1000.0,
                    col, float(v))
    # Phase bands (Tier 3 item 16, polish round 1 item 1):
    # each band contributes ONLY its two boundary seconds.
    # The band series run connectNulls, so the two points
    # draw the full strip and the chart fills under these
    # width 0 series, shading the strip behind the curves.
    # The band columns change only when a phase boundary
    # changes, never on an ordinary tick.
    for col, s, e in phase_band_ranges():
        put(s, col, BAND_TOP_F)
        put(e, col, BAND_TOP_F)
    if max_sec[0] < 0:
        rows = []
    else:
        rows = second_grid(
            placed,
            ['bean', 'ror', 'fan', 'heat', 'bg', 'bgRor',
             'plan', 'proj', 'bandDry', 'bandMai', 'bandDev',
             'bandCool'],
            max_sec[0], fill_cols=('fan', 'heat'))
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
    update_phase_label()
    update_dock_actions()
    update_stats_line()
    return elapsed


def stamp_event(stem, label):
    """Record one standard roast event (Controls event buttons)."""
    _stamp(stem, label)


def stamp_custom(index):
    """Record one of the four customizable events. A custom
    whose CustomEventNEnabled member is off cannot be stamped
    at all (polish round 1 item 7): the guard lives here in
    the library, not only in the view, so no caller can
    bypass it. A missing Enabled member (an older tag tree)
    reads as enabled. A slot with a blank name cannot be
    stamped either (polish round 6): an unnamed slot has no
    button, so no caller should reach it, and stamping it
    would record an event with no label. Returns True when
    the stamp landed."""
    name_member = 'CustomEvent%dName' % index
    enabled_member = 'CustomEvent%dEnabled' % index
    vals = read_members(['BeanTempF', 'StartTime', name_member,
                         enabled_member])
    enabled = vals[enabled_member]
    if enabled is not None and not enabled:
        return False
    # Polish round 6: a slot with no name is hidden, so it
    # cannot be stamped either. A name that is blank (or
    # only whitespace) means Eric has not given this slot
    # a name yet; stamping it would record an event with
    # no label and a press row with no key.
    name = vals[name_member]
    if name is None or not str(name).strip():
        return False
    now = system.date.now()
    elapsed = elapsed_sec(vals['StartTime'], now)
    stem = 'CustomEvent%d' % index
    write_members([(stem + 'Time', now), (stem + 'TempF', vals['BeanTempF']),
                   (stem + 'ElapsedSec', elapsed)])
    append_log('event', vals[name_member], vals['BeanTempF'], elapsed, now)
    record_press(vals[name_member])
    build_marks()
    update_dock_actions()
    return True


def dock_actions():
    """The phase aware dock contract (polish round 1 item 7):
    an ordered list of action descriptors computed from State
    and the stamped events, which the dock view renders in
    the next chunk. Each descriptor carries:
      key:   the action key record_press and the stamp
             functions use ('Charge', 'Dry End',
             'First Crack Start', ..., or a custom's name),
      label: the button text (customs use CustomEventNName;
             a slot whose name is blank is left out entirely,
             polish round 6),
      kind:  'primary', 'secondary', 'custom' or 'utility',
      lead:  True for the one action the phase leads with,
      customIndex: the custom slot (1 to 4) on customs, 0 on
      every other action. It is carried on ALL descriptors on
      purpose: a flex repeater reuses instance views when the
      set changes, and a param missing from the new instance
      keeps its previous value in the reused view, so a Drop
      instance recycled from a custom slot would otherwise
      inherit that slot's customIndex.
    Every key routes through the same library handler the
    current buttons call (charge, stamp_event with the same
    stem and label pairs, drop, cool, finish, reset_batch,
    stamp_custom), so press capture is unchanged: one
    batch_events row per press. Fan and Heat steppers are
    NOT part of the list; the dock keeps them as fixed
    elements."""
    members = ['State', 'DryEndElapsedSec',
               'FirstCrackStartElapsedSec',
               'FirstCrackEndElapsedSec',
               'SecondCrackStartElapsedSec',
               'SecondCrackEndElapsedSec']
    for i in (1, 2, 3, 4):
        members += ['CustomEvent%dName' % i,
                    'CustomEvent%dEnabled' % i]
    vals = read_members(members)

    def act(key, label, kind, lead=False):
        return {'key': key, 'label': label, 'kind': kind,
                'lead': bool(lead), 'customIndex': 0}

    def customs():
        out = []
        for i in (1, 2, 3, 4):
            enabled = vals['CustomEvent%dEnabled' % i]
            if enabled is not None and not enabled:
                continue
            # Polish round 6: a slot with no name is hidden.
            # Eric names his own customs in Settings; the
            # shipped defaults name only slot 1 (Fan Boost),
            # so the dock shows one custom button instead of
            # four, and a slot he clears in Settings drops
            # off the controls until he names it again.
            name = vals['CustomEvent%dName' % i]
            if name is None or not str(name).strip():
                continue
            d = act(name, name, 'custom')
            d['customIndex'] = i
            out.append(d)
        return out

    def stamped(member):
        v = vals[member]
        return v is not None and v >= 0

    state = vals['State']
    if state == 'Complete':
        # Charge stays on offer at Complete (polish phase 2
        # amendment): charging the next batch is what
        # finalizes an open between batch window into staged
        # metrics, while Reset discards it. With Reset as the
        # only action the between batch protocol could never
        # complete in the real button flow (found by the
        # tier 3c suite, whose roast 2 charges from Complete).
        return [act('Charge', 'Charge', 'primary', True),
                act('Reset', 'Reset / New Roast', 'utility')]
    if state == 'Dropped':
        return [act('Cool', 'Cool', 'primary', True),
                act('Finish', 'Finish', 'secondary')]
    if state == 'Cooling':
        return [act('Finish', 'Finish', 'primary', True)]
    if state != 'Roasting':
        return [act('Charge', 'Charge', 'primary', True)]
    if not stamped('DryEndElapsedSec'):
        return [act('Dry End', 'Dry End', 'primary', True)] \
            + customs()
    if not stamped('FirstCrackStartElapsedSec'):
        return [act('First Crack Start', 'FC Start', 'primary',
                    True)] + customs()
    if not stamped('FirstCrackEndElapsedSec'):
        return [act('First Crack End', 'FC End', 'primary', True),
                act('Drop', 'Drop', 'secondary')] + customs()
    if not stamped('SecondCrackStartElapsedSec'):
        return [act('Second Crack Start', 'SC Start', 'primary',
                    True),
                act('Drop', 'Drop', 'secondary')] + customs()
    if not stamped('SecondCrackEndElapsedSec'):
        return [act('Second Crack End', 'SC End', 'primary',
                    True),
                act('Drop', 'Drop', 'secondary')] + customs()
    return [act('Drop', 'Drop', 'primary', True)] + customs()


def update_dock_actions():
    """Publish the current dock set to the DockActionsJson
    member (polish phase 2 item 1), following the PhaseLabel
    publish pattern: the dock views bind the JSON instead of
    calling scripts per render. Recomputed at the same points
    PhaseLabel is recomputed (the temp change path, event
    stamps, charge, drop, cool, finish, reset), and from the
    dock views' own startup so a customs rename or enable
    change made in Settings (a direct tag write, no library
    call) is picked up when the roast views load."""
    try:
        _publish('DockActionsJson',
                 system.util.jsonEncode(dock_actions()))
    except Exception:
        pass


# Key to library handler routing for the dock views. Every
# entry is the same handler the pre phase 2 fixed buttons
# called, so press capture is unchanged: one batch_events
# row per press.
DOCK_EVENT_STEMS = {
    'Dry End': ('DryEnd', 'Dry End'),
    'First Crack Start': ('FirstCrackStart', 'First Crack Start'),
    'First Crack End': ('FirstCrackEnd', 'First Crack End'),
    'Second Crack Start': ('SecondCrackStart',
                           'Second Crack Start'),
    'Second Crack End': ('SecondCrackEnd', 'Second Crack End'),
}


def _dock_route_key(key):
    """Route one standard dock key to its handler. Returns True
    when the key routed, False for an empty or unknown key."""
    if key == 'Charge':
        charge()
    elif key in DOCK_EVENT_STEMS:
        stem, label = DOCK_EVENT_STEMS[key]
        stamp_event(stem, label)
    elif key == 'Drop':
        drop()
    elif key == 'Cool':
        cool()
    elif key == 'Finish':
        finish()
    elif key == 'Reset':
        reset_batch()
    else:
        return False
    return True


# Button label to descriptor key, for the dock_press fallback
# below: the label is the text painted on the button.
DOCK_LABEL_KEYS = {
    'Charge': 'Charge',
    'Dry End': 'Dry End',
    'FC Start': 'First Crack Start',
    'FC End': 'First Crack End',
    'SC Start': 'Second Crack Start',
    'SC End': 'Second Crack End',
    'Drop': 'Drop',
    'Cool': 'Cool',
    'Finish': 'Finish',
    'Reset / New Roast': 'Reset'}


def _dock_press_by_label(params):
    """Fallback routing for a dock click whose descriptor key
    did not route (polish round 3, HUNT-22). The rapid press
    audit caught a press reaching the session during the Drop
    cooling seek's render load with its key param not yet
    applied; the old dispatch then fell through and the press
    vanished without a trace. The painted label is what the
    user saw and tapped, so route by it: standard labels map
    through DOCK_LABEL_KEYS, and a custom's label is its name,
    matched back to its slot. Anything else is ignored, exactly
    as an unknown key was before."""
    label = str(params.get('label') or '')
    if not label:
        return
    key = DOCK_LABEL_KEYS.get(label)
    if key is not None:
        _dock_route_key(key)
        return
    members = ['CustomEvent%dName' % i for i in (1, 2, 3, 4)]
    vals = read_members(members)
    for i in (1, 2, 3, 4):
        if vals['CustomEvent%dName' % i] == label:
            stamp_custom(i)
            return


def dock_press(self):
    """One thin dispatch for every dock button (Views/DockButton
    carries the descriptor as view params). Customs route by
    customIndex; standard keys route by key. A click whose key
    did not route falls back to routing by its painted label
    (polish round 3, HUNT-22)."""
    params = self.view.params
    try:
        idx = int(params.get('customIndex') or 0)
    except Exception:
        idx = 0
    # Customs route by slot, but only when the descriptor kind
    # says custom: standard keys always win, so a recycled
    # repeater instance carrying a stale customIndex can never
    # stamp the wrong event.
    if params.get('kind') == 'custom' and idx:
        stamp_custom(idx)
        return
    key = str(params.get('key') or '')
    if not _dock_route_key(key):
        _dock_press_by_label(params)


# ---------------------------------------------------------------- theme
# Polish phase 2 item 7. The ThemeMode memory tag lives in
# [default]Roastery/AppSettings (setup_roastery_v4_tags.py).
# Light and Dark set the built in session themes directly.
# System sets the session theme to 'roastsystem', a gateway
# theme resource that layers the built in dark variables and
# palette over the built in light theme under a
# prefers-color-scheme: dark media query, so the BROWSER
# resolves the device preference (and restyles live when the
# OS theme changes mid session). Stock Perspective has no
# session property for the browser color scheme and
# system.perspective.runJavaScriptAsync is an Embr Periscope
# module function that is not installed on this gateway, so
# the theme resource is the route that works; see the docs
# section for the full investigation.

THEME_MODE_TAG = '[default]Roastery/AppSettings/ThemeMode'
SYSTEM_THEME = 'roastsystem'
THEME_MODES = ('System', 'Light', 'Dark')


def theme_mode():
    try:
        v = system.tag.readBlocking([THEME_MODE_TAG])[0].value
    except Exception:
        v = None
    return v if v in THEME_MODES else 'System'


def apply_theme(self):
    """Set this session's theme from the ThemeMode tag."""
    mode = theme_mode()
    target = {'Light': 'light', 'Dark': 'dark'}.get(mode,
                                                    SYSTEM_THEME)
    try:
        if str(self.session.props.theme) != target:
            self.session.props.theme = target
    except Exception:
        pass
    return target


def set_theme_mode(self, mode):
    """App Settings mode buttons: write the tag (the choice is
    remembered across sessions) and apply to this session at
    once."""
    if mode not in THEME_MODES:
        return
    system.tag.writeBlocking([THEME_MODE_TAG], [mode])
    apply_theme(self)


def on_theme_mode_change(self):
    """HudBar watcher (round 5, HUNT-38): the HudBar view
    carries a themeMode custom prop bound to the ThemeMode
    tag with this onChange script, and the HudBar top dock
    is mounted on every page, so a ThemeMode write from
    anywhere (another session's App Settings buttons, a
    direct tag write) re-applies the theme in this already
    open session without a reload. apply_theme stays the
    single apply path; the brightness re-report refreshes
    the chart probe for the System case. Idempotent: the
    session's own button writes fire it too, after
    set_theme_mode already applied."""
    apply_theme(self)
    report_brightness(self)


def page_startup(self):
    """Every page view's startup: come up in the right theme."""
    apply_theme(self)
    init_chart_dark(self)
    report_brightness(self)


# ------------------------------------------------ app settings dock
# Polish round 3, HUNT-32 (Eric, 2026-11-19: "the popups
# need to be very smooth, instead of real popups this
# should use css to slide in from the side and slide
# out"). App Settings was the app's only real popup; it
# is now a right dock on every page, the BatchEdit
# slide over pattern: the platform animates the dock in
# and out, the gear toggles it, and the panel's own Close
# button slides it away. Every control inside the view is
# unchanged.

APP_SETTINGS_DOCK = 'appSettings'


def toggle_app_settings(self):
    """Gear buttons: slide the App Settings panel in or
    out."""
    system.perspective.toggleDock(APP_SETTINGS_DOCK)


def close_app_settings(self):
    """App Settings Close button: slide the panel out."""
    system.perspective.closeDock(APP_SETTINGS_DOCK)


# ------------------------------------------------ chart dark mode
# Polish round 3, HUNT-31 (Eric, 2026-11-18: in dark mode
# "the shading is dark and hard to see and the numbers in
# the axes are dark so you can't use it in dark"). Root
# cause, proven in the lab: the canvas chart's axis label
# and title colors default (empty string) to a dark gray
# that does NOT follow the session theme, in pinned Dark
# exactly as in System on a dark device, while the legend
# and grid lines do follow the theme. A CSS var() string
# in a chart text color is dropped by the component (the
# round 3 probe: labels stayed dark under the dark theme
# layer), so the colors are explicit literals switched by
# the session's effective brightness:
# - pinned Light or Dark: session.props.theme is exact;
# - System (the roastsystem theme): the browser resolves
#   prefers-color-scheme and the gateway cannot see it, so
#   a small script run at startup (the same Periscope
#   runJavaScriptAsync channel the toasts use) reads
#   matchMedia on the client and clicks one of two hidden
#   probe buttons in the shared HudBar dock; the buttons
#   set the session custom prop chartDark, and a media
#   change listener re-reports when the OS theme flips
#   mid session. Every chart axis color and the band
#   opacity bind to that prop through the script
#   transforms below (the app's established dynamic prop
#   pattern, null safe where a bare expression binding
#   died on the unset prop in the probe).
# If the script never runs (Periscope unavailable), pinned
# modes still work and System keeps today's rendering.

CHART_TEXT_ON_DARK = '#e2e8f0'
CHART_TEXT_ON_LIGHT = '#475569'
CHART_POINTER_BG_DARK = '#111827'
CHART_POINTER_BG_LIGHT = '#f8fafc'
# The probe buttons carry no text (a text label spills
# past the 1px button box and trips the phone layout's
# overflow checks); the script finds them by their style
# class in DOM order: index 0 is BrightDarkBtn, index 1
# is BrightLightBtn (HudBar child order).
BRIGHTNESS_JS = (
    "() => { const mq = window.matchMedia("
    "'(prefers-color-scheme: dark)'); const report = () => {"
    " const bs = document.querySelectorAll("
    "'.psc-roast-brightness-probe'); const btn = "
    "bs[mq.matches ? 0 : 1]; if (btn) btn.click(); }; "
    "report(); setTimeout(report, 600); "
    "setTimeout(report, 1800); if (mq.addEventListener) "
    "mq.addEventListener('change', report); }")


def init_chart_dark(self):
    """Default the session's chartDark prop to False so the
    chart color bindings have a value from the first paint;
    the brightness report overwrites it a moment later in
    System mode. Never raises."""
    try:
        if self.session.custom.chartDark is None:
            self.session.custom.chartDark = False
    except Exception:
        pass


def set_chart_dark(self, dark):
    """HudBar probe buttons: record this session's resolved
    brightness for the chart bindings."""
    try:
        self.session.custom.chartDark = bool(dark)
    except Exception:
        pass


def report_brightness(self):
    """Ask the client to report its color scheme (System
    mode) through the probe buttons. Harmless in pinned
    modes: the bindings key off the pinned theme first.
    Never raises."""
    try:
        qv = system.tag.readBlocking(
            [PERISCOPE_AVAILABLE_TAG])[0]
        if not qv.value:
            return
        system.perspective.runJavaScriptAsync(
            BRIGHTNESS_JS, {})
    except:
        # Polish round 6, HUNT-48: the brightness probe goes
        # through Periscope to a page that may be closing
        # (the themeMode onChange fires in every open
        # session on a ThemeMode write), and a Java
        # throwable is not a Python Exception in Jython
        # (round 4, HUNT-36), so except Exception does not
        # catch it and the onChange logs an error. Bare
        # except keeps the Never raises promise; the theme
        # itself was already applied by apply_theme, so a
        # missed re-probe costs nothing.
        pass


def chart_dark(self):
    """This session's effective chart brightness: True when
    the charts sit on a dark background."""
    try:
        theme = str(self.session.props.theme)
    except Exception:
        theme = ''
    if theme == 'dark':
        return True
    if theme == 'light':
        return False
    try:
        return bool(self.session.custom.chartDark)
    except Exception:
        return False


def chart_text_color(self, _value=None):
    """Binding transform: axis label and title color for
    the session's brightness (literal hex; chart props
    never take CSS var() strings)."""
    return (CHART_TEXT_ON_DARK if chart_dark(self)
            else CHART_TEXT_ON_LIGHT)


def chart_pointer_bg(self, _value=None):
    """Binding transform: axis pointer label background."""
    return (CHART_POINTER_BG_DARK if chart_dark(self)
            else CHART_POINTER_BG_LIGHT)


def chart_band_opacity(self, _value=None):
    """Binding transform: phase band fill opacity. 0.12
    reads clearly on the light panel; on the dark panel
    the same hues need 0.30 to separate (HUNT-31)."""
    return 0.30 if chart_dark(self) else 0.12


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



def _clear_events():
    """Clear every event stamp member (polish round 1 item 6
    audit): all six EVENT_STEMS events (DryEnd, FirstCrackStart,
    FirstCrackEnd, SecondCrackStart, SecondCrackEnd, Drop)
    times, temps and elapsed seconds, plus the four customs.
    Charge is deliberately NOT cleared here because charge()
    stamps ChargeTime and ChargeTempF immediately before
    calling this; reset_batch clears ChargeTime and
    ChargeTempF in its own write. There are no Cool event
    members on the UDT (cool() is a state change plus a press
    row only), so nothing Cool related can go stale."""
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


# ------------------------------------------------------- simulator sync
# RoasterSim is a stepped simulator program (one static BeanTemp
# row per program second; see scripts/setup_roastery_v4_tags.py
# for the curve model and the capability evidence). The device
# exposes meta nodes under [Controls] that the app reaches
# through the Roastery level Sim* OPC tags:
# - Reset: writing True restarts the program at interval 0
#   (the 392 F charge plateau) and the node clears itself.
# - Pause: True freezes the program at its current interval.
# - BaseRate: milliseconds per program interval. For a STEPPED
#   program this is a clean speed control (500 ms plays the
#   curve at twice wall speed, 2000 ms at half), which is how
#   Fan and Heat levels move the curve: more heat plays it
#   faster, more fan slower. (For the old ramp() program this
#   did not work: ramp progress is wall clock anchored while
#   segment boundaries follow the counter, so the segments
#   jumped. Proven on a scratch device, 2026-11-17.)
# - Program Counter: read only on this device build. Writes
#   while running and while paused are both ignored (proven
#   live, polish round 2), so the Drop cooling seek below
#   cannot jump the counter; it fast forwards through the
#   Base Rate instead.
# All of this is Simulated source only and fully guarded: on a
# real transport (WebSocket, MQTT) or if the Sim tags are
# missing, every call is a no-op and the roast flow is untouched.

SIM_RESET = '[default]Roastery/SimReset'
SIM_PAUSE = '[default]Roastery/SimPause'
SIM_BASE_RATE = '[default]Roastery/SimBaseRate'
SIM_COUNTER = '[default]Roastery/SimProgramCounter'
SIM_CHARGE_TEMP_F = 392.0


def _sim_is_simulated():
    try:
        return read_members(['ActiveSource'])['ActiveSource'] \
            == 'Simulated'
    except Exception:
        return False


def _sim_rate_ms(fan, heat):
    """Base rate for the current Fan and Heat levels: the speed
    factor is 1.0 at the 5/5 defaults, plus 6 percent per heat
    level above 5 (minus below), minus 3.5 percent per fan level
    above 5 (plus below), clamped so a roast can run at most
    about 1.45x or 0.6x real time."""
    speed = 1.0 + 0.06 * (int(heat or 5) - 5) \
        - 0.035 * (int(fan or 5) - 5)
    speed = max(0.6, min(1.45, speed))
    ms = int(round(1000.0 / speed / 10.0) * 10)
    return max(650, min(1700, ms))


def sim_apply_rate():
    """Publish the Fan/Heat driven Base Rate to the simulator.
    Called at Charge and on every Fan or Heat step."""
    if not _sim_is_simulated():
        return
    try:
        vals = read_members(['FanLevel', 'HeatLevel'])
        ms = _sim_rate_ms(vals['FanLevel'], vals['HeatLevel'])
        cur = system.tag.readBlocking([SIM_BASE_RATE])[0].value
        if cur is None or int(cur) != ms:
            system.tag.writeBlocking([SIM_BASE_RATE], [ms])
    except Exception:
        pass


def sim_align_charge():
    """Restart the simulator program so its interval 0 (the
    charge plateau and the start of the dip) lands on the app
    Charge press, then wait briefly for the probe tag to show
    the plateau, so ChargeTempF and the first curve samples are
    the program start and not whatever the free running cycle
    was showing. The wait is bounded (about 3 s worst case) and
    any failure leaves the normal charge flow to proceed."""
    if not _sim_is_simulated():
        return
    try:
        # A fresh program starts here, so any seek flag left
        # over from an interrupted seek clears with it.
        write_members([('SimSeeking', False),
                       ('SimSeekTargetSec', -1)])
        vals = read_members(['FanLevel', 'HeatLevel'])
        system.tag.writeBlocking(
            [SIM_BASE_RATE, SIM_PAUSE, SIM_RESET],
            [_sim_rate_ms(vals['FanLevel'], vals['HeatLevel']),
             False, True])
    except Exception:
        return
    try:
        from java.lang import Thread
        for _i in range(20):
            qvs = system.tag.readBlocking(
                [SIM_COUNTER, path('BeanTempF')])
            pc, bt = qvs[0].value, qvs[1].value
            if (pc is not None and int(pc) <= 2) or (
                    bt is not None
                    and abs(float(bt) - SIM_CHARGE_TEMP_F) <= 10.0):
                break
            Thread.sleep(150)
    except Exception:
        pass


# ------------------------------------------------------- cooling seek
# Polish round 2: on DROP the stepped program has no seek of
# its own, so a Drop pressed far from the program drop anchor
# (720 s) used to leave the probe following the roast schedule,
# rising to the anchor peak before it cooled. The seek aligns
# the program with the actual drop: it fast forwards (two
# stage, 25 ms per interval then a 250 ms approach)
# from the current counter to the cooling row aligned with the
# actual bean temp at drop, then restores the Fan and Heat
# rate. The declining cooling segment (program seconds 720 to
# 785, temps below from the generator in
# scripts/setup_roastery_v4_tags.py at 5 s steps) declines
# monotonically, so the aligned row is the first row at or
# below the drop temp; a drop temp below the segment bottom
# (342.9 F) clamps to the bottom row. The fast forward is
# two stage (bulk, then a slow approach) because the counter
# can only be polled; see sim_seek_cooling. The seek is a
# state machine, not a blocking loop: drop() arms it and
# returns at once, sim_seek_advance steps it on each
# BeanTempF change, and the between batch window opens when
# the seek lands (drop() defers it), so the capture opens on
# the aligned cooling curve and never sees the fast forward.
# It is a tag write sequence, not a press, so the PressEvents
# group still writes exactly one batch_events row for the
# Drop press. Simulated source only, fully guarded like the
# rest of the simulator glue.

SIM_DROP_ANCHOR_SEC = 720
SIM_COOL_BOTTOM_SEC = 785
SIM_COOL_POINTS = [(720, 417.3), (725, 411.1), (730, 402.8),
                   (735, 395.3), (740, 387.3), (745, 378.5),
                   (750, 370.0), (755, 363.1), (760, 358.3),
                   (765, 355.4), (770, 351.9), (775, 349.2),
                   (780, 344.8), (785, 342.9)]
SIM_SEEK_FAST_RATE_MS = 5
SIM_SEEK_FAST_WINDOW = 200
SIM_SEEK_RATE_MS = 25
SIM_SEEK_APPROACH_RATE_MS = 150
SIM_SEEK_APPROACH_STEPS = 45
SIM_SEEK_TIMEOUT_SEC = 60


def _sim_cool_target_sec(drop_temp):
    """Program second in the declining cooling segment aligned
    with drop_temp: the first second whose program temp is at
    or below it (linear between the 5 s table rows), clamped
    to the segment ends."""
    try:
        dt = float(drop_temp)
    except Exception:
        return SIM_DROP_ANCHOR_SEC
    pts = SIM_COOL_POINTS
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
    return SIM_COOL_BOTTOM_SEC


def _sim_seeking(now_ms):
    """True while sim_seek_cooling is fast forwarding the
    simulator program (polish round 3, HUNT-22). The flag
    carries a staleness expiry (the seek timeout plus a
    margin) so a seek interrupted mid flight, by a gateway
    restart for instance, can never mute the BeanTempF
    pipeline for good."""
    try:
        qv = system.tag.readBlocking([path('SimSeeking')])[0]
        if not qv.value:
            return False
        age = now_ms - long(qv.timestamp.getTime())
        return age < (SIM_SEEK_TIMEOUT_SEC + 15) * 1000
    except Exception:
        return False


def sim_seek_cooling(drop_temp):
    """Arm the cooling seek (see the section note): fast
    forward the simulator program to the cooling row aligned
    with drop_temp WITHOUT blocking the caller, and return
    True when a seek started. No-op (False) on real
    transports, when the program is already at or past the
    aligned row, or on any failure.

    Polish round 3 (HUNT-22): this used to run as a blocking
    poll loop inside drop(), holding the pressing session's
    handler for the seek's whole 10 to 25 s. The rapid press
    audit proved the cost: dock clicks landing during the
    block were delivered late or dropped outright by the
    client, one press in the post Drop cluster in most runs.
    The state machine form keeps every press handler at
    milliseconds; sim_seek_advance does the stepping on the
    BeanTempF change rhythm the gateway already runs."""
    if not _sim_is_simulated():
        return False
    try:
        target = _sim_cool_target_sec(drop_temp)
        cur = system.tag.readBlocking([SIM_COUNTER])[0].value
        if cur is None or int(cur) >= target:
            return False
        # Mute the BeanTempF pipeline for the fast forward
        # (the ticks are artifacts; on_bean_temp advances the
        # seek instead of processing them) and start at the
        # device floor, 5 ms per interval (about 150 per
        # second): the old blocking poller could not track
        # that rate and overshot by hundreds of intervals
        # (polish round 2), but the state machine advances on
        # the ticks themselves and stages the rate down as
        # the target nears, so the fast stage is safe here
        # and keeps the seek, and its session render load,
        # as short as possible.
        write_members([('SimSeekTargetSec', int(target)),
                       ('SimSeeking', True)])
        system.tag.writeBlocking(
            [SIM_PAUSE, SIM_BASE_RATE],
            [False, SIM_SEEK_FAST_RATE_MS])
        return True
    except Exception:
        return False


def sim_seek_advance():
    """Advance the cooling seek one step: called on every
    BeanTempF change while SimSeeking. The base rate stages
    down as the target nears (5 ms bulk, 25 ms inside the
    fast window, then the 150 ms approach crawl at about 6
    intervals per second, so tick latency costs only an
    interval or two of overshoot). At the target, or when
    the seek has run past its timeout, finish: restore the
    Fan and Heat base rate, reseed the live RoR buffer (the
    fast forward filled it with compressed time samples;
    the same reseed charge() performs), and open the
    between batch window drop() deferred, so the window
    still opens on the aligned cooling curve."""
    try:
        vals = read_members(['SimSeekTargetSec', 'FanLevel',
                             'HeatLevel'])
        target = vals['SimSeekTargetSec']
        pc = system.tag.readBlocking([SIM_COUNTER])[0].value
        qv = system.tag.readBlocking([path('SimSeeking')])[0]
        age_ms = (system.date.toMillis(system.date.now())
                  - long(qv.timestamp.getTime()))
        done = (target is not None and int(target) >= 0
                and pc is not None and int(pc) >= int(target))
        if not done and age_ms < SIM_SEEK_TIMEOUT_SEC * 1000:
            if (target is not None and int(target) >= 0
                    and pc is not None):
                remaining = int(target) - int(pc)
                if remaining <= SIM_SEEK_APPROACH_STEPS:
                    want = SIM_SEEK_APPROACH_RATE_MS
                elif remaining <= SIM_SEEK_FAST_WINDOW:
                    want = SIM_SEEK_RATE_MS
                else:
                    want = SIM_SEEK_FAST_RATE_MS
                cur_rate = system.tag.readBlocking(
                    [SIM_BASE_RATE])[0].value
                if cur_rate != want:
                    system.tag.writeBlocking(
                        [SIM_BASE_RATE], [want])
            return
        restore_ms = _sim_rate_ms(vals['FanLevel'],
                                  vals['HeatLevel'])
        system.tag.writeBlocking([SIM_BASE_RATE], [restore_ms])
        write_members([('SimSeeking', False),
                       ('SimSeekTargetSec', -1),
                       ('_RoRLiveJson', '')])
        state = read_members(['State'])['State']
        if state in ('Dropped', 'Cooling', 'Complete'):
            if not _bbp_read(['WindowActive'])['WindowActive']:
                _bbp_start_window()
    except Exception:
        pass


def sim_hold_idle():
    """Park the simulator on its charge plateau while the
    workspace is Idle: restart the program and pause it at
    interval 0 in the same write (proven on a scratch device:
    the counter holds at 0 and the probe reads the plateau), so
    the idle console shows a steady preheat reading instead of
    a free running roast cycle, and the next Charge starts
    from a known state."""
    if not _sim_is_simulated():
        return
    try:
        system.tag.writeBlocking(
            [SIM_BASE_RATE, SIM_RESET, SIM_PAUSE],
            [1000, True, True])
    except Exception:
        pass


# ---------------------------------------------------------------- flow

def charge():
    # State guard (polish round 3, HUNT-27): Charge is only
    # offered at Idle and Complete, and a second charge while
    # Roasting is never meaningful. The rapid press audit
    # caught the platform re-delivering the sequence's first
    # Charge event seconds late, after the workspace had been
    # reset to Idle and even after the test session closed;
    # without this guard that replay re-charged the workspace
    # and stamped a phantom press. With it, a replayed Charge
    # is a no-op, and it never reaches record_press.
    if read_members(['State'])['State'] == 'Roasting':
        return
    # Settle any press rows the transaction group missed in
    # the previous workspace before this batch's presses start
    # (polish round 3, HUNT-22): charging is the natural close
    # of the between batch story.
    reconcile_press_pending()
    # Align the simulator first (Simulated source only): its
    # program restarts at the charge plateau, so the temp the
    # BBP finalize and the Charge stamp read below is the
    # program's charge moment, and the RoR buffer reseeds so
    # the live RoR is derived from this roast's samples only.
    sim_align_charge()
    write_members([('_RoRLiveJson', '')])
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
    update_phase_label()
    update_dock_actions()
    update_stats_line()



def drop():
    # State guard (HUNT-27, see charge): a replayed or stale
    # Drop outside Roasting would restamp the drop and re-run
    # the cooling seek over a finished workspace.
    if read_members(['State'])['State'] != 'Roasting':
        return
    _stamp('Drop', 'Drop')
    write_members([('State', 'Dropped'), ('Mode', 'Cool')])
    # Align the simulator cooling curve with this actual drop
    # (Simulated source only, no-op otherwise). When a seek
    # starts, the between batch window opens when the seek
    # lands (sim_seek_advance), so the window captures the
    # aligned cooling and never the seek fast forward;
    # otherwise it opens here, at DROP (Tier 3 item 20).
    if not sim_seek_cooling(read_members(['BeanTempF'])['BeanTempF']):
        _bbp_start_window()
    build_overlays()
    update_phase_label()
    update_dock_actions()
    update_stats_line()



def cool():
    # State guard (HUNT-27, see charge).
    if read_members(['State'])['State'] != 'Dropped':
        return
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Cooling')])
    append_log('state', 'Cooling', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())
    record_press('Cool')
    update_phase_label()
    update_dock_actions()
    update_stats_line()



def finish():
    # State guard (HUNT-27, see charge).
    if read_members(['State'])['State'] not in ('Dropped',
                                                'Cooling'):
        return
    vals = read_members(['BeanTempF', 'StartTime'])
    write_members([('State', 'Complete')])
    append_log('state', 'Finished', vals['BeanTempF'],
               elapsed_sec(vals['StartTime']), system.date.now())
    record_press('Finish')
    update_phase_label()
    update_dock_actions()
    update_stats_line()



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
    # Park the simulator on its charge plateau (Simulated only).
    sim_hold_idle()
    # Reset discards an open between batch window and any
    # staged BBP metrics (Tier 3 item 20, documented decision):
    # a reset workspace starts a fresh between batch story.
    _bbp_clear_all()
    write_members([('PlanDeviationText', '--')])
    build_marks()
    update_dock_actions()



def stepper(member, delta, label):
    """Fan and Heat steppers (SR800 levels 1 to 9), with trace log.
    A press that actually moves the level is a captured press."""
    vals = read_members([member, 'BeanTempF', 'StartTime', 'FanLevel',
                         'HeatLevel'])
    new = max(1, min(9, int(vals[member]) + int(delta)))
    if new == vals[member]:
        return
    write_members([(member, new)])
    # A level change retimes the simulator program (Simulated
    # only): more heat plays the curve faster, more fan slower.
    sim_apply_rate()
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
    vals = read_members(['StartTime'])
    start = vals['StartTime']
    if start is None:
        return
    # The plan is the variable length list from
    # target_plan_points (Tier 3 item 17): the JSON list when
    # one is stored, else the legacy four point tags.
    pts = target_plan_points()
    # X values are elapsed dates (axis base + offset seconds,
    # polish round 1 item 2), the v4.1 axis shared by every
    # chart dataset; StartTime only gates whether a roast
    # timeline exists at all.
    rows = []
    s = 0.0
    while s < pts[-1][0]:
        rows.append([elapsed_date(s), _plan_at(pts, s)])
        s += 15.0
    rows.append([elapsed_date(pts[-1][0]), pts[-1][1]])
    bg_rows = []
    bg_json = system.tag.readBlocking([BACKGROUND_JSON])[0].value
    if bg_json:
        for pair in system.util.jsonDecode(bg_json):
            bg_rows.append([elapsed_date(float(pair[0])),
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
                bg_ror_rows.append([elapsed_date(t), r])
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
# - ror_in_f_min: the average slope from the first sample
#   (DROP) to the bottom, (bottom - BT at t_first) times 60
#   divided by (t_b - t_first); 0.0 when the bottom is the
#   first sample (no approach exists). HUNT-87: this used to
#   be the slope over the RoR delta span before the bottom;
#   Artisan calcBBPMetrics averages the whole leg, so it does
#   now too.
# - ror_out_f_min: the average slope from the bottom to the
#   last sample (CHARGE), (BT at t_last - bottom) times 60
#   divided by (t_last - t_b); 0.0 when the bottom is the
#   last sample.


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


def bbp_compute(points):
    """The four BBP metrics from staged samples (definitions
    in the section note), or None when the window cannot
    support them (fewer than 2 samples or no duration).
    HUNT-87: the RoRs used to be span slopes (the last 20 s
    before the bottom and the first 20 s after it). Artisan
    calcBBPMetrics and the profile quality BBP report compute
    both as full-leg averages over the whole leg, so that is
    what these are now: ror_in is the average slope from the
    first sample (DROP) to the bottom, ror_out from the bottom
    to the last sample (CHARGE). On a realistic cool-down the
    two definitions differ by an order of magnitude (a 415 F
    drop to a 180 F bottom at 120 s reads -117.5 F/min as a
    full-leg average, about -30 as a 20 s span slope)."""
    if len(points) < 2:
        return None
    t_first = points[0][0]
    t_last = points[-1][0]
    if t_last <= t_first:
        return None
    bottom = min(v for _t, v in points)
    t_b = [t for t, v in points if v == bottom][0]
    if t_b > t_first:
        ror_in = ((bottom - points[0][1]) * 60.0
                  / (t_b - t_first))
    else:
        ror_in = 0.0
    if t_last > t_b:
        ror_out = ((points[-1][1] - bottom) * 60.0
                   / (t_last - t_b))
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
    show_toast(self, 'Batch details saved', 'success')


# ---------------------------------------------------------------- session

def main_startup(self):
    # Kept as the Roast page startup entry: theme from the
    # ThemeMode tag (polish phase 2 item 7). The old
    # theme_toggle is gone with the TabBar theme button.
    apply_theme(self)
