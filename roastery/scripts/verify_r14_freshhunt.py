#!/usr/bin/env python3
"""Round 14 fresh hunting pass (worker A, Artisan math).

Fresh hunt continuing from HUNT-96. New defects this round:
  1. HUNT-97: bbp_compute kept the EARLIEST sample holding
     the BBP bottom and let the CHARGE sample itself be the
     bottom. Artisan finds the BBP bottom with findTPint over
     a fake timeindex whose CHARGE index caps the scan, so the
     scan runs over the samples BEFORE charge and scans
     backward, keeping the LATEST tied sample. The compute now
     searches points[:-1] with the latest tie. Proven
     statically on a synthetic window, a flat-bottomed tie,
     a bottom-last edge and a two-point edge, and live in a
     BBP roast whose window bottom is tied at two samples.
  2. HUNT-98: bbp_staged_metrics dropped bottom_sec: the tag
     staged it and bbp_compute returned it, but the saved
     batch document carried only four BBP values, so a saved
     batch lost when its bottom happened. The staged metrics
     now carry bottom_sec, and the BatchDetail BBP line names
     the bottom time. Proven statically by source and live on
     the saved roast 2 document and its detail page.
  3. HUNT-99: _phase_analysis resolved the AUC base from the
     fixed baseF even when AucBaseFromEvent was set, so the
     BatchDetail phase AUCs were computed above the wrong
     base while the live AUC and the .alog export used the
     bean temp at the begin event (Artisan AUCbaseFlag). The
     base now resolves the same way _computed_for does.
     Proven statically for Dry End, TP and fixed-base cases,
     and live on a saved roast whose Dry End begin with
     fromEvent makes the Drying AUC match the recompute
     above the Dry End temp and not the one above 212 F.
  4. HUNT-100: _fan_heat_series level_at backfilled the FIRST
     slider event's level onto every sample before that
     event, so an imported file whose fan only moves at 60 s
     read that level from charge on. Samples before the first
     recorded change now read the SR800 mid default (5).
     Proven statically on a crafted event list and live by
     importing a .alog whose first fan event is late: the
     stored series rows read fan 5 before it and the event
     level after it.
  5. HUNT-101: batch_to_profile wrote the dry and FC temps in
     F into the phases list of a C mode profile, so an
     imported C mode batch without phasesRaw exported phases
     like [100, 300, 390, 230] where Artisan expects about
     [100, 150, 200, 230]. The event temps now convert to
     mode units. Proven statically for C and F mode and live
     by importing a C mode .alog and exporting it back.
  6. The four-page walk (Roast, Log, BatchDetail staged 1042,
     Settings) at 1360px and 360px, light and dark, plus the
     Settings scroll sweep at 360px dark, as the regression
     net for the round.

Harness updates for HUNT-97 and HUNT-98 (same precedent as
HUNT-93 to HUNT-96): verify_r13_freshhunt.py and
verify_roastery_tier3c.py now expect the five-value bbp
subdocument and the latest-tie bottom rule, and the r13
bottom-last static edge now expects the charge sample to
be excluded from the bottom search.

Does NOT retest the timezone TIME axis passthrough or
HUNT-46 (both beta-gated) and does NOT touch the press path
(HUNT-53 app fix out of scope) or the Docker packaging or
the builder files. Leaves the lab clean.
"""
import ast
import hashlib
import json
import math
import re
import sys
import time
import uuid

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright
from api27m import api

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
CALC = '[default]Roastery/Calculator'
WS = B + '/Sources/WebSocket/BeanTempF'
BBP = '[default]Roastery/Bbp'
ARTISAN = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'artisan/code.py')
BATCHES = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'batches/code.py')
CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
FIXTURE = ('/home/hatch/workspace/ignition-lab/artisan-fixtures/'
           'sample-roast.alog')
C_ALOG = '/tmp/r14-import-c-latefan.alog'
EXPORT_C_ALOG = '/tmp/r14-export-c.alog'
FAILS = []
PASSES = [0]
BASE = {}
IMPORTED_BATCH = [0]
AUC_ENTRY = {}


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '')
    if not cond:
        FAILS.append(name)


def approx(a, b, tol):
    return (a is not None and b is not None
            and abs(float(a) - float(b)) <= tol)


OVERFLOW_JS = """
() => {
  const vw = window.innerWidth;
  const de = document.documentElement;
  const clipped = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.closest('.secondary-message')) return;
    if (el.children.length === 0 && el.offsetParent !== null) {
      if (el.scrollWidth > el.clientWidth + 1) {
        const t = (el.textContent || '').trim().slice(0, 40);
        if (t) clipped.push(t + ' (' + el.scrollWidth + '>' +
          el.clientWidth + ')');
      }
    }
  });
  return {vw: vw, docW: de.scrollWidth, bodyW: document.body
    ? document.body.scrollWidth : -1,
    clipped: clipped.slice(0, 10), nClipped: clipped.length};
}"""


def measure(pg, label):
    m = pg.evaluate(OVERFLOW_JS)
    check(label + ' no horizontal overflow',
          m['docW'] <= m['vw'], m)
    check(label + ' no clipped leaf text',
          m['nClipped'] == 0, m['clipped'])
    return m


def scroll_to(pg, frac):
    pg.evaluate("""(f) => {
      const el = document.querySelector('.psc-roast-content');
      if (el) { el.scrollTop = el.scrollHeight * f; return; }
      const cands = [...document.querySelectorAll('*')]
        .filter(e => e.scrollHeight > e.clientHeight + 100)
        .sort((a, b) => b.scrollHeight - a.scrollHeight);
      if (cands.length) cands[0].scrollTop =
        cands[0].scrollHeight * f;
    }""", frac)
    pg.wait_for_timeout(900)


def set_theme_ui(pg, theme):
    """Set ThemeMode through the App Settings UI flow only:
    gear, theme button, Close. Never a direct tag write."""
    pg.locator('.psc-roast-gear-btn:visible').first.click(
        timeout=20000)
    pg.wait_for_timeout(900)
    pg.get_by_role('button', name=theme, exact=True).first.click(
        timeout=20000)
    ok = P.wait_until(lambda: P.tag(TM) == theme, 30)
    check('theme %s set through App Settings UI' % theme,
          bool(ok), P.tag(TM))
    pg.get_by_role('button', name='Close', exact=True).first.click(
        timeout=20000)
    pg.wait_for_timeout(500)


def extract_fns(path, names, extra=None):
    src = open(path).read()
    tree = ast.parse(src)
    ns = {'math': math}
    ns.update(extra or {})
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
    for name in names:
        if name not in ns:
            raise AssertionError('%s not found in %s'
                                 % (name, path))
    return ns

def static_bbp_tie():
    """HUNT-97: bbp_compute must keep the LATEST tied bottom
    and must not let the CHARGE sample be the bottom. The
    expectations below are Artisan findTPint over the fake
    BBP timeindex: the scan caps at the charge index and
    walks backward, so the last sample before charge wins
    a tie and the charge sample itself never wins."""
    ns = extract_fns(CORE, ['bbp_compute'])
    fn = ns['bbp_compute']
    pts = [(0.0, 415.0), (60.0, 300.0), (120.0, 180.0),
           (135.0, 280.0), (150.0, 392.0)]
    got = fn(pts)
    print('HUNT-97 synthetic window:', got, flush=True)
    check('HUNT-97 window time is 150 s',
          got and got['time_sec'] == 150.0, got)
    check('HUNT-97 bottom is 180 F at 120 s',
          got and got['bottom_temp_f'] == 180.0
          and got['bottom_sec'] == 120.0, got)
    check('HUNT-97 RoR in is the full-leg -117.5',
          got and approx(got['ror_in_f_min'], -117.5, 0.01),
          got and got['ror_in_f_min'])
    check('HUNT-97 RoR out is the full-leg 424.0',
          got and approx(got['ror_out_f_min'], 424.0, 0.01),
          got and got['ror_out_f_min'])
    tie = [(0.0, 415.0), (30.0, 350.0), (60.0, 328.0),
           (90.0, 328.0), (120.0, 360.0), (150.0, 392.0)]
    gt = fn(tie)
    print('HUNT-97 tied window:', gt, flush=True)
    check('HUNT-97 tied bottom is the LATER sample at 90 s',
          gt and gt['bottom_temp_f'] == 328.0
          and gt['bottom_sec'] == 90.0, gt)
    check('HUNT-97 tied RoR in is -58.0 from the later bottom',
          gt and approx(gt['ror_in_f_min'], -58.0, 0.01),
          gt and gt['ror_in_f_min'])
    check('HUNT-97 tied RoR out is 64.0 from the later bottom',
          gt and approx(gt['ror_out_f_min'], 64.0, 0.01),
          gt and gt['ror_out_f_min'])
    last = fn([(0.0, 415.0), (60.0, 300.0), (120.0, 180.0)])
    check('HUNT-97 charge sample is not the bottom (300 F '
          'at 60 s)',
          last and last['bottom_temp_f'] == 300.0
          and last['bottom_sec'] == 60.0, last)
    check('HUNT-97 bottom-last RoR in is -115.0',
          last and approx(last['ror_in_f_min'], -115.0, 0.01),
          last and last['ror_in_f_min'])
    check('HUNT-97 bottom-last RoR out is -120.0',
          last and approx(last['ror_out_f_min'], -120.0, 0.01),
          last and last['ror_out_f_min'])
    two = fn([(0.0, 400.0), (60.0, 350.0)])
    check('HUNT-97 two-point window bottoms at the first '
          'sample',
          two and two['bottom_temp_f'] == 400.0
          and two['bottom_sec'] == 0.0
          and approx(two['ror_out_f_min'], -50.0, 0.01), two)
    flat = fn([(0.0, 200.0), (30.0, 200.0), (60.0, 200.0)])
    check('HUNT-97 flat window bottoms at the last sample '
          'before charge',
          flat and flat['bottom_temp_f'] == 200.0
          and flat['bottom_sec'] == 30.0
          and flat['ror_in_f_min'] == 0.0
          and flat['ror_out_f_min'] == 0.0, flat)
    check('HUNT-97 a single point returns None',
          fn([(0.0, 400.0)]) is None)
    src = open(CORE).read()
    seg = src.split('def bbp_compute')[1].split(
        'def _bbp_finalize_charge')[0]
    check('HUNT-97 the bottom search excludes the last sample',
          'points[:-1]' in seg, '')
    check('HUNT-97 the bottom keeps the latest tied sample',
          '[-1]' in seg, '')


def static_bbp_bottom_sec_source():
    """HUNT-98: the staged metrics must carry bottom_sec
    (the tag stages it, the document used to drop it) and
    the BatchDetail BBP line must name the bottom time."""
    src = open(CORE).read()
    seg = src.split('def bbp_staged_metrics')[1].split(
        'def ')[0] if 'def bbp_staged_metrics' in src else ''
    check('HUNT-98 staged metrics read the BottomSec tag',
          "'BottomSec'" in seg, '')
    check('HUNT-98 staged metrics return bottom_sec',
          "'bottom_sec'" in seg, '')
    bsrc = open(BATCHES).read()
    check('HUNT-98 the detail BBP line names the bottom time',
          'bottom %.0f F at %s' in bsrc, '')


def _phase_doc(begin, from_event, base_f=212.0):
    """The crafted curve shared by the HUNT-99 static checks:
    a dipping curve with Dry End, FC Start and Drop stamped
    and a turning point at 60 s, 340 F."""
    points = [(0, 392.0), (60, 340.0), (120, 360.0),
              (180, 380.0), (240, 390.0), (300, 399.0),
              (360, 405.0), (420, 410.0), (480, 413.0),
              (540, 416.0), (600, 419.0)]
    doc = {'batchNumber': 1099, 'totalSec': 600,
           'events': {'charge': {'t': 0, 'tempF': 392.0},
                      'dryEnd': {'t': 180, 'tempF': 380.0},
                      'fcStart': {'t': 360, 'tempF': 405.0},
                      'drop': {'t': 600, 'tempF': 419.0}},
           'turningPoint': {'t': 60, 'tempF': 340.0},
           'aucDetail': {'begin': begin, 'baseF': base_f,
                         'fromEvent': from_event},
           'metadata': {}}
    return doc, points


def _phase_ns():
    cns = extract_fns(CORE, ['shares_100'])

    class CoreStub(object):
        shares_100 = staticmethod(cns['shares_100'])

        @staticmethod
        def compute_ror_series(points, params, offline=False):
            return []

        @staticmethod
        def ror_params():
            return {}

    return extract_fns(BATCHES, ['_phase_analysis',
                                 '_interp_pairs', '_auc_range',
                                 '_mmss'],
                       extra={'core': CoreStub})


def static_phase_auc_base():
    """HUNT-99: with AucBaseFromEvent set, the phase AUCs
    must integrate above the bean temp at the begin event,
    not above the fixed baseF. Hand-computed trapezoid
    areas over the crafted curve (60 s samples, so each
    segment is one minute): Dry End begin takes base 380 F,
    so the Drying AUC is 0.0 (the curve never clears 380 F
    before Dry End), Maillard 41.5 and Development 131.0;
    the fixed-base control reads 450.0 / 545.5 / 803.0 above
    212 F, and a TP begin with fromEvent takes base 340 F
    for a Drying AUC of 66.0."""
    ns = _phase_ns()
    fn = ns['_phase_analysis']
    doc, points = _phase_doc('Dry End', True)
    _rows, _tp, extra = fn(doc, points)
    ph = extra['phases']
    print('HUNT-99 Dry End fromEvent phases:', ph, flush=True)
    check('HUNT-99 Dry End fromEvent Drying AUC is 0.0 above '
          'the Dry End temp',
          ph.get('Drying', {}).get('aucFMin') == 0.0, ph)
    check('HUNT-99 Dry End fromEvent Maillard AUC is 41.5',
          ph.get('Maillard', {}).get('aucFMin') == 41.5, ph)
    check('HUNT-99 Dry End fromEvent Development AUC is 131.0',
          ph.get('Development', {}).get('aucFMin') == 131.0, ph)
    doc, points = _phase_doc('Dry End', False)
    _rows, _tp, extra = fn(doc, points)
    ph = extra['phases']
    check('HUNT-99 fixed-base control Drying AUC is 450.0',
          ph.get('Drying', {}).get('aucFMin') == 450.0, ph)
    check('HUNT-99 fixed-base control Maillard AUC is 545.5',
          ph.get('Maillard', {}).get('aucFMin') == 545.5, ph)
    check('HUNT-99 fixed-base control Development AUC is 803.0',
          ph.get('Development', {}).get('aucFMin') == 803.0, ph)
    doc, points = _phase_doc('TP', True)
    _rows, _tp, extra = fn(doc, points)
    ph = extra['phases']
    check('HUNT-99 TP fromEvent Drying AUC is 66.0 above the '
          'turning point temp',
          ph.get('Drying', {}).get('aucFMin') == 66.0, ph)


def static_fan_heat_backfill():
    """HUNT-100: level_at must return the mid default before
    the first slider event, not that event's level. One fan
    event at 60 s to 100 percent (level 9) and one heat event
    at 90 s to 100 percent: every sample before 60 s reads
    fan 5, the fan steps to 9 at 60 s, the heat steps to 9
    at 90 s."""
    ns = extract_fns(ARTISAN, ['_fan_heat_series', '_etypes_of',
                               '_pct_from_internal', '_num',
                               '_level_from_pct',
                               '_pct_from_level'],
                     extra={'DEFAULT_ETYPES': ['Air', 'Drum',
                                               'Damper', 'Burner',
                                               '--']})
    fn = ns['_fan_heat_series']
    timex = [float(t) for t in range(0, 121, 10)]
    temp2 = [300.0 + t for t in range(0, 121, 10)]
    p = {'timex': timex, 'temp2': temp2,
         'specialevents': [6, 9], 'specialeventstype': [0, 3],
         'specialeventsvalue': [11.0, 11.0]}
    fan_ev, heat_ev, level_at, trace = fn(p, timex, 0.0, 'F')
    print('HUNT-100 fan events:', fan_ev, 'heat events:',
          heat_ev, 'trace:', trace, flush=True)
    check('HUNT-100 fan before the first event reads the '
          'default 5, not the event level',
          level_at(fan_ev, 0) == 5
          and level_at(fan_ev, 30) == 5
          and level_at(fan_ev, 59) == 5,
          (level_at(fan_ev, 0), level_at(fan_ev, 30)))
    check('HUNT-100 fan steps to 9 at the event',
          level_at(fan_ev, 60) == 9
          and level_at(fan_ev, 120) == 9, level_at(fan_ev, 60))
    check('HUNT-100 heat before the first event reads the '
          'default 5',
          level_at(heat_ev, 0) == 5
          and level_at(heat_ev, 89) == 5, level_at(heat_ev, 0))
    check('HUNT-100 heat steps to 9 at the event',
          level_at(heat_ev, 90) == 9
          and level_at(heat_ev, 120) == 9, level_at(heat_ev, 90))
    check('HUNT-100 the trace carries one event per change',
          trace == [{'t': 60.0, 'label': 'Fan 100%',
                     'fan': 9.0, 'heat': 5.0},
                    {'t': 90.0, 'label': 'Heat 100%',
                     'fan': 9.0, 'heat': 9.0}], trace)

def _load_artisan_module():
    """Exec the whole artisan module under CPython with the
    Jython and gateway names stubbed, so batch_to_profile
    (which carries module-level constants and the hash
    helpers) can run statically. The stubs only cover the
    names this path touches: java.lang number/string/date,
    the SHA-256 digest, system.util.getLogger, and the two
    batches helpers _computed_for needs."""
    src = open(ARTISAN).read()
    keep = [ln for ln in src.split('\n')
            if not ln.startswith('import java')
            and not ln.startswith('import roastery')]
    src = '\n'.join(keep)

    class _JString(object):
        def __init__(self, s='', enc=None):
            self._s = str(s)

        def __str__(self):
            return self._s

        def getBytes(self, enc):
            return self._s.encode(enc)

    class _JDouble(object):
        @staticmethod
        def toString(x):
            return repr(float(x))

    class _JDate(object):
        def __init__(self, ms):
            self._ms = ms

        def getTime(self):
            return self._ms

    class _JUUID(object):
        @staticmethod
        def randomUUID():
            return uuid.uuid4()

    class _MD(object):
        def __init__(self, h):
            self._h = h

        def update(self, b):
            self._h.update(b)

        def digest(self):
            return self._h.digest()

    class _JMessageDigest(object):
        @staticmethod
        def getInstance(name):
            return _MD(hashlib.sha256())

    class _JSecurity(object):
        MessageDigest = _JMessageDigest

    class _JTimeZone(object):
        @staticmethod
        def getDefault():
            class _TZ(object):
                @staticmethod
                def getOffset(ms):
                    return 0
            return _TZ()

    class _JUtil(object):
        Date = _JDate
        UUID = _JUUID
        TimeZone = _JTimeZone

    class _JLang(object):
        Double = _JDouble
        Float = _JDouble
        Number = (int, float)
        Boolean = bool
        String = _JString

    class _Java(object):
        lang = _JLang
        util = _JUtil
        security = _JSecurity

    class _SysUtil(object):
        @staticmethod
        def getLogger(name):
            return None

        @staticmethod
        def jsonEncode(v):
            return json.dumps(v)

    class _SysDate(object):
        @staticmethod
        def format(d, fmt):
            return ''

        @staticmethod
        def parse(s, fmt):
            raise ValueError('no parse in the static shim')

    class _System(object):
        util = _SysUtil
        date = _SysDate

    bns = extract_fns(BATCHES, ['_weight_loss',
                                '_volume_increase'])

    class BatchesStub(object):
        _weight_loss = staticmethod(bns['_weight_loss'])
        _volume_increase = staticmethod(bns['_volume_increase'])
        NQ_SERIES_SELECT = 'Roastery/Series/SelectByBatch'

        @staticmethod
        def _run(path, params=None):
            raise AssertionError('_run must not be called here')

    class CoreStub(object):
        pass

    ns = {'__name__': 'artisan_static', 'ast': ast,
          'math': math, 'long': int, 'basestring': str,
          'unicode': str, 'system': _System, 'java': _Java,
          'batches': BatchesStub, 'core': CoreStub}
    exec(compile(src, ARTISAN, 'exec'), ns)
    return ns


def _c_mode_batch():
    """A C mode imported batch without phasesRaw: the curve
    is in C, the document events are in F, Dry End 380 F and
    FC Start 405 F."""
    timex = [float(t) for t in range(0, 601, 60)]
    temp2 = [200.0, 170.0, 180.0, 190.0, 195.0, 199.0, 202.0,
             205.0, 207.0, 209.0, 210.0]
    doc = {'batchNumber': 1097, 'beanName': 'C mode test',
           'totalSec': 600,
           'events': {'charge': {'t': 0, 'tempF': 392.0},
                      'dryEnd': {'t': 180, 'tempF': 380.0},
                      'fcStart': {'t': 360, 'tempF': 405.0},
                      'fcEnd': None, 'scStart': None,
                      'scEnd': None,
                      'drop': {'t': 600, 'tempF': 419.0},
                      'custom': []},
           'metadata': {'ChargeWeightG': 200.0,
                        'WeightOutG': 172.0},
           'aucDetail': {'begin': 'TP', 'baseF': 212.0,
                         'fromEvent': False},
           'phaseAnalysis': {'fcsRorFMin': 12.0},
           'fanHeatTrace': []}
    sub = {'curves': {'mode': 'C', 'timex': timex,
                      'temp2': temp2,
                      'temp1': [-1.0] * len(timex),
                      'samplinginterval': 60.0},
           'events': {}, 'display': {}, 'settings': {},
           'identity': {}}
    doc['artisan'] = sub
    return {'batchNumber': 1097, 'document': doc,
            'roastStart': None}


def static_phases_c_mode():
    """HUNT-101: a C mode export must write its phases in C.
    Dry End 380 F is 193 C and FC Start 405 F is 207 C, so
    the phases list reads [100, 193, 207, 230]; the F mode
    control on the same document reads [212, 380, 405, 450]."""
    ns = _load_artisan_module()
    fn = ns['batch_to_profile']
    batch = _c_mode_batch()
    prof = fn(batch)
    print('HUNT-101 C mode phases:', prof.get('phases'),
          'mode:', prof.get('mode'), flush=True)
    check('HUNT-101 C mode profile keeps mode C',
          prof.get('mode') == 'C', prof.get('mode'))
    check('HUNT-101 C mode phases are in C, not F',
          prof.get('phases') == [100, 193, 207, 230],
          prof.get('phases'))
    batch['document']['artisan']['curves']['mode'] = 'F'
    batch['document']['artisan']['curves']['temp2'] = [
        392.0, 340.0, 360.0, 380.0, 390.0, 399.0, 405.0, 410.0,
        413.0, 416.0, 419.0]
    prof_f = fn(batch)
    check('HUNT-101 F mode control phases stay in F',
          prof_f.get('phases') == [212, 380, 405, 450],
          prof_f.get('phases'))


def ds_rows(value):
    if isinstance(value, str):
        value = json.loads(value)
    cols = [c['name'] for c in value['columns']]
    return cols, value['rows']


def click_visible(page, name):
    return page.evaluate("""(name) => {
      const els = [...document.querySelectorAll('button')]
        .filter(e => e.textContent.trim() === name &&
          e.getBoundingClientRect().width > 0 &&
          e.getBoundingClientRect().height > 0 && !e.disabled);
      if (!els.length) return false;
      els[0].click(); return true;
    }""", name)


def click_until_state(page, name, state, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if P.tag(B + '/State') == state:
            return True
        click_visible(page, name)
        time.sleep(1.2)
    return P.tag(B + '/State') == state


def dock_prereq(dock):
    for name in ('Dry End', 'FC Start', 'FC End'):
        btn = dock.get_by_role('button', name=name)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            time.sleep(1.5)


def dock_drop(dock):
    dock_prereq(dock)
    dock.get_by_role('button', name='Drop').click()


def doc_of(number):
    return json.loads(P.psql(
        'SELECT data FROM batches WHERE batch_number = %d'
        % number))


def delete_batch_ui(pg, number):
    label = format(number, ',')
    pg.goto(P.BASE + '/log', wait_until='networkidle',
            timeout=60000)
    pg.wait_for_timeout(1500)
    pg.locator('text=%s' % label).first.click(timeout=25000)
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='Delete').first.click(
        timeout=25000)
    pg.wait_for_timeout(1000)
    pg.get_by_role('button',
                   name='Confirm Delete').first.click(
                       timeout=25000)
    pg.wait_for_timeout(2500)
    check('batch %d deletes through the Log UI' % number,
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = %d' % number) == '0')


def upload(page, path):
    comps = page.locator('[data-component="ia.input.fileupload"]')
    for i in range(comps.count()):
        if page.locator('input[type="file"]').count() > 0:
            break
        try:
            comps.nth(i).click(timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(900)
    page.locator('input[type="file"]').last.set_input_files(path)
    page.wait_for_timeout(3000)


def _to_c(v):
    if v is None or v == -1:
        return v
    return (float(v) - 32.0) * 5.0 / 9.0


def craft_c_latefan_alog():
    """The sample fixture converted to C mode with its phases
    removed (so the export must rebuild them) and its first
    fan event removed (so the first recorded fan change lands
    at 270 s, not at charge)."""
    data = ast.literal_eval(open(FIXTURE).read())
    data['mode'] = 'C'
    data['temp2'] = [_to_c(v) for v in data['temp2']]
    data['temp1'] = [_to_c(v) for v in data['temp1']]
    data.pop('phases', None)
    data['greens_temp'] = _to_c(data.get('greens_temp'))
    data['ambientTemp'] = _to_c(data.get('ambientTemp'))
    for key in ('specialevents', 'specialeventstype',
                'specialeventsvalue', 'specialeventsStrings'):
        del data[key][0]
    data['roastUUID'] = uuid.uuid4().hex
    with open(C_ALOG, 'w') as f:
        f.write(repr(data) + '\n')
    return C_ALOG

def import_c_latefan_live(pw):
    """HUNT-100 and HUNT-101 live: import the C mode .alog
    with a late first fan event, then check the stored series
    fan levels and the exported phases. The fan must read 5
    before 270 s and 7 from 270 s to 465 s (the 80 percent
    event at index 95); the export must carry mode C and
    phases in C from the imported event temps."""
    path = craft_c_latefan_alog()
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    upload(pg, path)
    ok = P.wait_until(
        lambda: int(P.psql('SELECT COUNT(*) FROM batches')) >
        int(BASE['batches']), 60)
    check('HUNT-100/101 C mode late-fan .alog imports',
          bool(ok), P.psql('SELECT COUNT(*) FROM batches'))
    nxt = int(P.psql('SELECT MAX(batch_number) FROM batches'))
    IMPORTED_BATCH[0] = nxt
    note = pg.locator('body').inner_text()
    check('HUNT-100/101 import note names the new batch',
          ('Imported' in note and str(nxt) in note), note[:200])
    early = P.psql(
        'SELECT MIN(fan_level), MAX(fan_level) FROM '
        'batch_series WHERE batch_number = %d AND '
        't_offset_sec < 270' % nxt)
    print('HUNT-100 series fan before 270 s:', early, flush=True)
    check('HUNT-100 stored fan reads 5 before the first fan '
          'event',
          early.strip() == '5|5', early)
    mid = P.psql(
        'SELECT MIN(fan_level), MAX(fan_level) FROM '
        'batch_series WHERE batch_number = %d AND '
        't_offset_sec >= 270 AND t_offset_sec < 465' % nxt)
    print('HUNT-100 series fan 270 to 465 s:', mid, flush=True)
    check('HUNT-100 stored fan reads 7 after the first fan '
          'event',
          mid.strip() == '7|7', mid)
    doc = doc_of(nxt)
    dry_f = (doc.get('events') or {}).get('dryEnd', {}).get('tempF')
    fc_f = (doc.get('events') or {}).get('fcStart', {}).get('tempF')
    R5.stage_one(nxt)
    pg2 = R5.open_page(ctx, '/log/detail')
    pg2.wait_for_timeout(2500)
    with pg2.expect_download(timeout=30000) as dl_info:
        pg2.get_by_role('button',
                        name='Export .alog').first.click()
    dl = dl_info.value
    dl.save_as(EXPORT_C_ALOG)
    prof = ast.literal_eval(open(EXPORT_C_ALOG).read())
    print('HUNT-101 exported mode/phases:',
          prof.get('mode'), prof.get('phases'),
          'dryF', dry_f, 'fcF', fc_f, flush=True)
    check('HUNT-101 exported profile stays in C mode',
          prof.get('mode') == 'C', prof.get('mode'))
    want_phases = [100,
                   int(round((dry_f - 32.0) * 5.0 / 9.0))
                   if dry_f else 150,
                   int(round((fc_f - 32.0) * 5.0 / 9.0))
                   if fc_f else 200, 230]
    check('HUNT-101 exported phases are in C from the event '
          'temps',
          prof.get('phases') == want_phases,
          (prof.get('phases'), want_phases))
    check('HUNT-101 exported phases are not the F temps',
          prof.get('phases') != [100, 300, 390, 230]
          and (prof.get('phases') or [0])[1] < 250,
          prof.get('phases'))
    R5.shot(pg2, 'r14-fresh-detail-c-export.png')
    delete_batch_ui(pg, nxt)
    IMPORTED_BATCH[0] = 0
    b.close()
    P.write_tags([(CALC + '/ChargeG', 200.0),
                  (CALC + '/LossPct', 15.0),
                  (CALC + '/OutG', 172.0)])
    time.sleep(1)
    check('HUNT-100/101 calculator restored to 200/15/172 '
          'after the import',
          P.tag(CALC + '/ChargeG') == 200.0
          and P.tag(CALC + '/LossPct') == 15.0
          and P.tag(CALC + '/OutG') == 172.0,
          (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/LossPct'),
           P.tag(CALC + '/OutG')))


def bbp_full_leg(samples):
    """Independent full-leg recompute with the HUNT-97 bottom
    rule: the latest tied sample before the charge sample."""
    if len(samples) < 2 or samples[-1][0] <= samples[0][0]:
        return None
    search = samples[:-1]
    bottom = min(v for _t, v in search)
    tb = [t for t, v in search if v == bottom][-1]
    t_first, t_last = samples[0][0], samples[-1][0]
    ror_in = ((bottom - samples[0][1]) * 60.0 / (tb - t_first)
              if tb > t_first else 0.0)
    ror_out = ((samples[-1][1] - bottom) * 60.0 / (t_last - tb)
               if t_last > tb else 0.0)
    return {'time_sec': t_last - t_first,
            'bottom_temp_f': bottom, 'bottom_sec': tb,
            'ror_in_f_min': ror_in,
            'ror_out_f_min': ror_out}


def _auc_range(points, start, end, base):
    """Independent trapezoid area above base over [start, end],
    the shape batches._auc_range uses."""
    if end is None or start is None or end <= start \
            or not points:
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


def bbp_live(pw):
    """HUNT-97, HUNT-98 and HUNT-99 live, one roast pair.
    Roast 1 drops, then a falling and rising window whose
    bottom is tied at 328 F on two samples; roast 2 charges
    with AucBegin Dry End and AucBaseFromEvent set, stamps
    Dry End on a rising curve, drops and saves. The staged
    BBP bottom must be the LATER tied sample with its time,
    the saved document must carry bottom_sec, and the saved
    phase analysis Drying AUC must match the recompute above
    the Dry End temp, not the one above 212 F."""
    base = (int(P.psql('SELECT COUNT(*) FROM batches')),
            int(P.psql('SELECT COUNT(*) FROM batch_series')),
            int(P.psql('SELECT COUNT(*) FROM batch_events')))
    max_event_id = int(P.psql(
        'SELECT COALESCE(MAX(id), 0) FROM batch_events'))
    span0 = P.tag(B + '/RoRDeltaSpanSec')
    AUC_ENTRY['begin'] = P.tag(B + '/AucBegin')
    AUC_ENTRY['base'] = P.tag(B + '/AucBaseTempF')
    AUC_ENTRY['fromEvent'] = P.tag(B + '/AucBaseFromEvent')
    P.write_tags([(B + '/RoRDeltaSpanSec', 6)])
    b_desk = R5.launch(pw)
    b_mob = R5.launch(pw)
    desk_ctx = b_desk.new_context(viewport={'width': 1360,
                                            'height': 900},
                                  timezone_id='America/Denver')
    mob_ctx = b_mob.new_context(viewport={'width': 360,
                                          'height': 800},
                                timezone_id='America/Denver')
    desk = R5.open_page(desk_ctx, '/log')
    mob = R5.open_page(mob_ctx, '/')
    desk.get_by_role('button', name='New Roast').first.click(
        timeout=20000)
    desk.wait_for_timeout(3000)
    roast1 = int(P.tag(B + '/BatchNumber'))
    check('HUNT-97 new roast workspace for roast 1',
          roast1 > 1048 and P.tag(B + '/State') == 'Idle',
          roast1)
    P.write_tags([(B + '/ActiveSource', 'WebSocket'),
                  (WS, 400.0)])
    ok = P.wait_until(
        lambda: approx(P.tag(B + '/BeanTempF'), 400.0, 0.01), 20)
    check('HUNT-97 WebSocket source drives the bean temp',
          bool(ok), P.tag(B + '/BeanTempF'))
    mob.goto(P.BASE + '/', wait_until='networkidle',
             timeout=60000)
    mob.wait_for_timeout(5000)
    R5.dismiss(mob)
    desk.goto(P.BASE + '/', wait_until='networkidle',
              timeout=60000)
    desk.wait_for_timeout(5000)
    R5.dismiss(desk)
    dock = mob.locator('.psc-roast-controldock')
    dock.get_by_role('button', name='Charge').click()
    check('HUNT-97 roast 1 charge starts',
          P.wait_tag(B + '/State', 'Roasting'))
    mob.wait_for_timeout(1500)
    P.write_tags([(WS, 402.0)])
    P.wait_until(lambda: approx(P.tag(B + '/BeanTempF'), 402.0,
                                0.01), 15)
    mob.wait_for_timeout(1200)
    P.write_tags([(WS, 404.0)])
    P.wait_until(lambda: approx(P.tag(B + '/BeanTempF'), 404.0,
                                0.01), 15)
    mob.wait_for_timeout(1500)
    dock_prereq(dock)
    t_drop_click = time.time()
    dock.get_by_role('button', name='Drop').click()
    check('HUNT-97 roast 1 drop lands',
          P.wait_tag(B + '/State', 'Dropped'))
    check('HUNT-97 BBP window opened at DROP',
          P.wait_tag(BBP + '/WindowActive', True, timeout=15))
    mob.wait_for_timeout(1600)
    # HUNT-109: the two 328 F writes used to sit side by side,
    # but the BBP capture is change driven, so writing the
    # same temp twice fires no second valueChanged event and
    # the window held only one 328 sample (run 1: tied
    # [10.707]). The minimum now repeats after an intervening
    # 329 F write, so the capture sees a change each time and
    # the window genuinely ties at 328 F on two samples.
    seq = [380.0, 360.0, 345.0, 335.0, 330.0, 328.0, 329.0,
           328.0, 331.0, 335.0, 342.0, 355.0, 372.0, 390.0]
    for j, v in enumerate(seq):
        P.write_tags([(WS, v)])
        P.wait_until(lambda: approx(P.tag(B + '/BeanTempF'), v,
                                    0.01), 15)
        mob.wait_for_timeout(1700)
    cols, srows = ds_rows(P.tag('[default]Roastery/BbpSamplesDS'))
    ti, vi = (cols.index('t_offset_sec'),
              cols.index('bean_temp_f'))
    samples = sorted((float(r[ti]), float(r[vi])) for r in srows)
    print('HUNT-97 window samples:', samples, flush=True)
    check('HUNT-97 window staged at least 12 samples',
          len(samples) >= 12, len(samples))
    tied = [t for t, v in samples
            if v == min(x for _t, x in samples)]
    print('HUNT-97 tied bottom samples:', tied, flush=True)
    check('HUNT-97 the window bottom is tied at two samples',
          len(tied) == 2, tied)
    check('HUNT-97 window starts at the drop temp 404 F',
          samples and approx(samples[0][1], 404.0, 0.5),
          samples and samples[0])
    check('HUNT-97 cool clicked',
          click_until_state(mob, 'Cool', 'Cooling'))
    mob.wait_for_timeout(1600)
    check('HUNT-97 finish clicked',
          click_until_state(desk, 'Finish', 'Complete'))
    check('HUNT-97 window still open in Complete',
          P.tag(BBP + '/WindowActive') is True)
    mob.wait_for_timeout(1600)
    roast2 = roast1 + 1
    P.write_tags([(B + '/BatchNumber', roast2),
                  (B + '/AucBegin', 'Dry End'),
                  (B + '/AucBaseFromEvent', True),
                  (B + '/AucBaseTempF', 212.0)])
    mob.wait_for_timeout(1500)
    t_charge_click = time.time()
    dock.get_by_role('button', name='Charge').click()
    check('HUNT-97 roast 2 charge starts',
          P.wait_tag(B + '/State', 'Roasting'))
    staged = P.read_tags([BBP + '/HasMetrics', BBP + '/TimeSec',
                          BBP + '/BottomTempF', BBP + '/BottomSec',
                          BBP + '/RorInFMin', BBP + '/RorOutFMin',
                          BBP + '/WindowActive'])
    check('HUNT-97 metrics staged at CHARGE, window closed',
          staged[0] is True and staged[6] is False, staged)
    samples_final = list(samples)
    if samples:
        samples_final.append((float(staged[1]),
                              samples[-1][1]))
    expected = bbp_full_leg(samples_final)
    print('HUNT-97 staged:', staged, flush=True)
    print('HUNT-97 full-leg recompute:', expected, flush=True)
    check('HUNT-97 staged bottom matches the recompute',
          expected is not None
          and approx(staged[2], expected['bottom_temp_f'], 0.01),
          staged)
    check('HUNT-97 staged bottom time is the LATER tied '
          'sample',
          expected is not None
          and approx(staged[3], expected['bottom_sec'], 1.0),
          (staged[3], expected and expected['bottom_sec']))
    check('HUNT-97 staged bottom time is not the earlier tie',
          len(tied) == 2
          and abs(float(staged[3]) - tied[0]) > 1.0,
          (staged[3], tied))
    check('HUNT-97 staged RoR in matches the full-leg '
          'recompute',
          expected is not None
          and approx(staged[4], expected['ror_in_f_min'],
                     max(5.0, abs(expected['ror_in_f_min'])
                         * 0.05)),
          (staged[4], expected and expected['ror_in_f_min']))
    check('HUNT-97 staged RoR out matches the full-leg '
          'recompute',
          expected is not None
          and approx(staged[5], expected['ror_out_f_min'],
                     max(5.0, abs(expected['ror_out_f_min'])
                         * 0.05)),
          (staged[5], expected and expected['ror_out_f_min']))
    check('HUNT-97 staged time is the DROP to CHARGE duration',
          approx(staged[1], t_charge_click - t_drop_click, 4.0),
          (staged[1], t_charge_click - t_drop_click))
    # Roast 2 climbs on the WebSocket source so the Dry End
    # stamp lands on a rising curve with real samples.
    mob.wait_for_timeout(1500)
    for v in (392.0, 396.0, 399.0):
        P.write_tags([(WS, v)])
        P.wait_until(lambda: approx(P.tag(B + '/BeanTempF'), v,
                                    0.01), 15)
        mob.wait_for_timeout(1500)
    dock_prereq(dock)
    check('HUNT-99 roast 2 Dry End stamped',
          (P.tag(B + '/DryEndElapsedSec') or -1) >= 0,
          P.tag(B + '/DryEndElapsedSec'))
    dock_drop(dock)
    check('HUNT-97 roast 2 drop lands',
          P.wait_tag(B + '/State', 'Dropped'))
    desk.goto(P.BASE + '/', wait_until='networkidle',
              timeout=60000)
    desk.wait_for_timeout(5000)
    R5.dismiss(desk)
    desk.get_by_role('button', name='Save Batch').first.click()
    saved2 = P.wait_until(
        lambda: int(P.psql('SELECT COUNT(*) FROM batches WHERE '
                          'batch_number = %d' % roast2)) == 1, 30)
    check('HUNT-97 roast 2 saved', bool(saved2))
    if saved2:
        doc2 = doc_of(roast2)
        bbp_doc = doc2.get('bbp') or {}
        check('HUNT-98 roast 2 doc carries bottom_sec',
              'bottom_sec' in bbp_doc, bbp_doc)
        check('HUNT-98 doc bottom_sec matches the staged tag',
              approx(bbp_doc.get('bottom_sec'), staged[3], 0.01),
              (bbp_doc.get('bottom_sec'), staged[3]))
        check('HUNT-98 doc bbp values match the staged metrics',
              approx(bbp_doc.get('bottom_temp_f'), staged[2], 0.01)
              and approx(bbp_doc.get('ror_in_f_min'), staged[4],
                         0.01)
              and approx(bbp_doc.get('ror_out_f_min'), staged[5],
                         0.01)
              and approx(bbp_doc.get('time_sec'), staged[1], 0.01),
              bbp_doc)
        # HUNT-99: the saved phase analysis Drying AUC above
        # the Dry End temp, recomputed from the stored series
        # rows, and the same area above the fixed 212 F base
        # for contrast (the two must differ by a wide margin
        # on this curve, so the check proves which base the
        # app used).
        evs = doc2.get('events') or {}
        dry_ev = evs.get('dryEnd') or {}
        dry_t = dry_ev.get('t')
        dry_temp = dry_ev.get('tempF')
        rows = P.psql(
            'SELECT t_offset_sec, bean_temp_f FROM batch_series'
            ' WHERE batch_number = %d ORDER BY t_offset_sec'
            % roast2)
        pts = [(float(a), float(b))
               for a, b in (r.split('|') for r in
                            rows.strip().split('\n') if r)]
        pa = doc2.get('phaseAnalysis') or {}
        dry_auc = (pa.get('phases') or {}).get(
            'Drying', {}).get('aucFMin')
        want = _auc_range(pts, 0.0, float(dry_t), float(dry_temp)) \
            if dry_t is not None and dry_temp is not None else None
        want212 = _auc_range(pts, 0.0, float(dry_t), 212.0) \
            if dry_t is not None else None
        print('HUNT-99 dry AUC saved:', dry_auc, 'want above '
              'Dry End temp:', want, 'above 212 F:', want212,
              'dry temp:', dry_temp, 'dry t:', dry_t, flush=True)
        check('HUNT-99 saved Drying AUC matches the recompute '
              'above the Dry End temp',
              dry_auc is not None and want is not None
              and approx(dry_auc, want, 0.5), (dry_auc, want))
        check('HUNT-99 the two bases differ by more than 5 '
              'F-min on this curve',
              want is not None and want212 is not None
              and abs(want212 - want) > 5.0, (want, want212))
        check('HUNT-99 saved Drying AUC is not the 212 F '
              'base value',
              dry_auc is not None and want212 is not None
              and abs(dry_auc - want212) > 5.0,
              (dry_auc, want212))
    R5.stage_one(roast2)
    pgd = R5.open_page(desk_ctx, '/log/detail')
    pgd.wait_for_timeout(2500)
    body = pgd.locator('body').inner_text()
    mmss = '%02d:%02d' % (int(float(staged[3])) // 60,
                          int(float(staged[3])) % 60)
    check('HUNT-98 detail page names the bottom time',
          ('bottom 328 F at ' + mmss) in body, body[:400])
    R5.shot(pgd, 'r14-fresh-bbp-roast2-saved.png')
    desk.goto(P.BASE + '/', wait_until='networkidle',
              timeout=60000)
    desk.wait_for_timeout(5000)
    R5.dismiss(desk)
    check('HUNT-97 roast 2 cool clicked',
          click_until_state(mob, 'Cool', 'Cooling'))
    check('HUNT-97 roast 2 finish clicked',
          click_until_state(desk, 'Finish', 'Complete'))
    check('HUNT-97 reset through its button',
          click_until_state(desk, 'Reset / New Roast', 'Idle'))
    check('HUNT-97 reset discarded the window',
          P.read_tags([BBP + '/WindowActive', BBP + '/HasMetrics',
                       BBP + '/SampleCount'])
          == [False, False, 0],
          P.read_tags([BBP + '/WindowActive', BBP + '/HasMetrics',
                       BBP + '/SampleCount']))
    b_desk.close()
    b_mob.close()
    P.psql('DELETE FROM batches WHERE batch_number = %d'
           % roast2)
    P.drain_pending()
    P.psql('DELETE FROM batch_events WHERE id > %d'
           % max_event_id)
    P.write_tags([(B + '/BatchNumber', 1042),
                  (B + '/ActiveSource', 'Simulated'),
                  (B + '/RoRDeltaSpanSec', span0),
                  (B + '/AucBegin', AUC_ENTRY['begin']),
                  (B + '/AucBaseTempF', AUC_ENTRY['base']),
                  (B + '/AucBaseFromEvent', AUC_ENTRY['fromEvent']),
                  (WS, 0.0)])
    state = P.read_tags([B + '/State', B + '/FanLevel',
                         B + '/HeatLevel', B + '/BatchNumber',
                         B + '/ActiveSource', B + '/Mode'])
    check('HUNT-97 workspace clean Idle after the BBP flow',
          state == ['Idle', 5, 5, 1042, 'Simulated', 'Off'],
          state)
    check('HUNT-99 AUC settings restored to their entry '
          'values',
          P.read_tags([B + '/AucBegin', B + '/AucBaseTempF',
                       B + '/AucBaseFromEvent'])
          == [AUC_ENTRY['begin'], AUC_ENTRY['base'],
              AUC_ENTRY['fromEvent']],
          (P.tag(B + '/AucBegin'), P.tag(B + '/AucBaseTempF'),
           P.tag(B + '/AucBaseFromEvent')))
    end = (int(P.psql('SELECT COUNT(*) FROM batches')),
           int(P.psql('SELECT COUNT(*) FROM batch_series')),
           int(P.psql('SELECT COUNT(*) FROM batch_events')))
    check('HUNT-97 lab back to the seeded log after the flow',
          end == base, (end, base))
    try:
        P.probe_setup()
        P.probe('reset', timeout=30)
    finally:
        P.probe_teardown()
    time.sleep(5)
    slots = ['[default]Roastery/PressSlots/Slot%02d' % i
             for i in range(16)]
    P.write_tags([(s, '') for s in slots])
    time.sleep(2)
    P.psql('DELETE FROM batch_events WHERE id > %d'
           % max_event_id)
    time.sleep(3)
    state2 = P.read_tags([B + '/State', B + '/Mode',
                          B + '/BatchNumber'])
    end2 = (int(P.psql('SELECT COUNT(*) FROM batches')),
            int(P.psql('SELECT COUNT(*) FROM batch_series')),
            int(P.psql('SELECT COUNT(*) FROM batch_events')))
    check('HUNT-97 lab left clean after the post-check reset',
          state2 == ['Idle', 'Off', 1042] and end2 == base,
          (state2, end2))

def walk(pw, width, height, theme, tag):
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width,
                                  'height': height},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, theme)
    pg.wait_for_timeout(1200)
    measure(pg, 'roast %s' % tag)
    R5.shot(pg, 'r14-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r14-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r14-fresh-detail-%s.png' % tag)
    if tag == '1360-dark':
        body = pg3.locator('body').inner_text()
        m = re.search(
            r'Dry\s+(\S+)\s+(\d+)%.*?Mai\w*\s+(\S+)\s+(\d+)%.*?'
            r'Dev\s+(\S+)\s+(\d+)%', body, re.S)
        if m:
            shares = [int(m.group(2)), int(m.group(4)),
                      int(m.group(6))]
            check('detail 1042 stats shares sum to 100',
                  sum(shares) == 100, shares)
        else:
            check('detail stats line parses', False, body[:200])
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r14-fresh-settings-%s.png' % tag)
    b.close()


def settings_sweep(pw):
    """Settings scroll sweep at 360px dark."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        scroll_to(pg, frac)
        measure(pg, 'settings sweep %d%% 360-dark'
                % int(frac * 100))
        R5.shot(pg, 'r14-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def clean_state():
    ok = (P.tag(B + '/State') == 'Idle'
          and P.tag(B + '/BatchNumber') == 1042
          and P.tag(TM) == 'System'
          and P.tag(B + '/CompareAlignEvent') == 'charge'
          and P.tag(B + '/DispAxisFormat') == 'm:ss'
          and P.psql('SELECT COUNT(*) FROM batches') == '7'
          and P.psql('SELECT COUNT(*) FROM batch_series') == '101'
          and P.psql('SELECT COUNT(*) FROM batch_events') == '0')
    check('lab left clean (Idle, 1042, System, 7/101/0)',
          ok, (P.tag(B + '/State'), P.tag(B + '/BatchNumber'),
               P.tag(TM), P.psql('SELECT COUNT(*) FROM batches'),
               P.psql('SELECT COUNT(*) FROM batch_series'),
               P.psql('SELECT COUNT(*) FROM batch_events')))
    check('calculator left at 200/15/172',
          P.tag(CALC + '/ChargeG') == 200.0
          and P.tag(CALC + '/LossPct') == 15.0
          and P.tag(CALC + '/OutG') == 172.0,
          (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/LossPct'),
           P.tag(CALC + '/OutG')))


def main():
    static_bbp_tie()
    static_bbp_bottom_sec_source()
    static_phase_auc_base()
    static_fan_heat_backfill()
    static_phases_c_mode()
    state = P.tag(B + '/State')
    check('lab starts clean', state == 'Idle', state)
    if state != 'Idle':
        print('LAB BUSY: state=%s, not running live probes'
              % state, flush=True)
        print()
        print('PASSES:', PASSES[0])
        print('FAILURES:', FAILS if FAILS else 'none')
        sys.exit(2)
    BASE['batches'] = P.psql('SELECT COUNT(*) FROM batches')
    BASE['series'] = P.psql('SELECT COUNT(*) FROM batch_series')
    BASE['events'] = P.psql('SELECT COUNT(*) FROM batch_events')
    print('lab baseline:', BASE, flush=True)
    try:
        with sync_playwright() as pw:
            import_c_latefan_live(pw)
            bbp_live(pw)
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            b = R5.launch(pw)
            ctx = b.new_context(viewport={'width': 1360,
                                          'height': 900},
                                timezone_id='America/Denver')
            pg = R5.open_page(ctx, '/')
            pg.wait_for_timeout(2000)
            set_theme_ui(pg, 'System')
            pg.wait_for_timeout(800)
            b.close()
    finally:
        try:
            if IMPORTED_BATCH[0]:
                P.psql('DELETE FROM batches WHERE batch_number'
                       ' = %d' % IMPORTED_BATCH[0])
        except Exception:
            pass
    clean_state()
    print('TOTAL %d PASS, %d FAIL'
          % (PASSES[0], len(FAILS)))
    if FAILS:
        print('FAILURES:', FAILS)
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
