# Roastery Artisan interoperability: import and export of Artisan
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


def _density_gl(p):
    d = p.get('density') or []
    if len(d) < 4:
        return 0.0
    amount = _num(d[0]) * GRAMS.get(str(d[1]).lower(), 1.0)
    vol = _num(d[2])
    vunit = str(d[3]).lower()
    liters = vol if vunit == 'l' else vol / 1000.0
    if amount > 0 and liters > 0:
        return amount / liters
    return 0.0


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
    notes = p.get('roastingnotes') or ''
    if p.get('cuppingnotes'):
        notes = (notes + '\n' if notes else '') + \
            'Cupping: ' + p['cuppingnotes']
    meta['Notes'] = notes
    meta['TargetDropTempF'] = drop_temp or 0.0

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
    sub = _classify(p)
    sub['events']['coolEndSec'] = cool_sec
    sub['events']['etTempsF'] = et_temps
    doc['artisan'] = sub
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
    profile['beans'] = meta.get('BeanName') or doc.get('beanName') \
        or ''
    identity = sub.get('identity') or {}
    profile['title'] = identity.get('title') or (
        doc.get('beanName') or 'Roastery batch %d'
        % batch['batchNumber'])
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
