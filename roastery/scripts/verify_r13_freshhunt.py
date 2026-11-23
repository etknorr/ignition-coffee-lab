#!/usr/bin/env python3
"""Round 13 fresh hunting pass (worker A).

Fresh hunt continuing from HUNT-86. New defects this round:
  1. HUNT-87: the BBP RoR in and out used the RoR delta span
     window (the last 20 s before the bottom and the first 20 s
     after it). Artisan calcBBPMetrics and the profile quality
     BBP report compute both as full-leg averages over the
     whole leg (begin to bottom, bottom to charge), so that is
     what bbp_compute does now. Proven statically on a
     synthetic window (415 F drop, 180 F bottom at 120 s,
     392 F charge at 150 s reads -117.5 in and 424.0 out) and
     live with a curved falling then rising window through the
     WebSocket source, where the staged metrics match an
     independent full-leg recompute from BbpSamplesDS and differ
     from the old span slope by more than 40 F/min on both legs.
  2. HUNT-88: the .alog export computed block ignored the
     saved AUC settings. It always wrote AUCbegin 'TP',
     AUCbase 212.0 (100.0 in C mode) and AUCfromeventflag 1,
     whatever the batch's aucDetail said. The export now reads
     the saved begin, fixed base and fromEvent flag: the begin
     maps to CHARGE, TP, DE or FCs, the base is the bean temp
     at the begin event when fromEvent is set and that temp is
     proper, else the saved fixed base converted to mode units,
     the flag is 1 exactly when fromEvent is set, and the AUC
     integral starts at the begin index (falling back to charge
     when the begin event has not happened, mirroring Artisan
     profileAUC's index 0 fallback). Proven statically for the
     default, Charge, Dry End with fromEvent, FC Start with
     fromEvent, and C mode cases, and live on the batch 1042
     export (flag 0, base 212.0, same AUC value).
  3. HUNT-89: the turning point scan kept the EARLIEST sample
     holding the minimum on ties; Artisan findTPint scans
     backward, so the LATEST tied sample is the turning point.
     The scan is now less-than-or-equal in all three places
     (the export computed block, the live turning point
     tracker, and the phase analysis offline fallback).
     Proven statically on a flat-bottomed curve and live by
     importing a crafted .alog with a tied minimum and
     exporting the new batch (TP_time is the later tied
     sample).
  4. HUNT-90: the BatchDetail calculator could show a negative
     expected out and a loss over 100 percent. ExpectedOutG
     did ChargeG times (1 minus LossPct over 100) with no
     guard, so a LossPct over 100 (typable, the input has no
     min or max) read a negative expected weight, and
     ActualLossPct was clamped at 0 by HUNT-82 but not at 100,
     so a negative OutG read a loss over 100 percent.
     Artisan weight_loss caps at 100 (roasted weight 0).
     ExpectedOutG now clamps the loss percent to 0..100 inside
     the expression and ActualLossPct clamps to 0..100, in the
     setup script and on the live tags (export, patch, import
     back, the HUNT-82 route). Proven live at 200/150 (0.0)
     and 200/-10 (100.0).
  5. HUNT-91: the .alog export computed block omitted keys
     Artisan writes. The phase block is added (dry, mid and
     finish phase RoR and delta temp from Artisan RoR(), with
     the greens temp first and the turning point second,
     gated on the TP and Dry End indices being truthy as in
     Artisan; total_ror as the TP to DROP slope and fcs_ror
     from the stored phase analysis value, both inside the
     same gate; dry, mid and finish phase AUC and total_ts_BT
     as trapezoid areas above the same base), and the volume,
     moisture and density keys are added (volumein and
     volumeout in liters, roast_defects_weight in grams,
     green and roasted density in g/L, volume_gain from the
     guarded increase, moisture_loss as Artisan's raw greens
     minus roasted subtraction when both are recorded,
     organic_loss as weight_loss minus moisture_loss when
     weight_loss is nonzero, set_density from the stored
     DensityGL). A phase AUC is written only when both of its
     bounding events are stamped; Artisan falls back to the
     DROP end when one is missing, which would mislabel a
     charge to drop area as a phase area. Proven statically
     on a crafted batch covering all the new keys and live
     on the batch 1042 export (always-written keys present
     with 0.0, no phase RoRs because the turning point sits
     at the first sample, total_ts_BT matching the
     independent recompute) and on the imported tie batch
     export (phase RoRs and phase AUCs matching the
     independent recompute).
  6. The four-page walk (Roast, Log, BatchDetail staged 1042,
     Settings) at 1360px and 360px, light and dark, measuring
     horizontal overflow and clipped leaf text, plus the
     Settings scroll sweep at 360px dark, as the regression
     net for the round.

Does NOT retest the timezone TIME axis passthrough or
HUNT-46 (both beta-gated) and does NOT touch the press path
(HUNT-53 app fix out of scope) or the Docker packaging or
the builder files. Leaves the lab clean.
"""
import ast
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
SETUP = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
         'scripts/setup_roastery_v4_tags.py')
FIXTURE = ('/home/hatch/workspace/ignition-lab/artisan-fixtures/'
           'sample-roast.alog')
TIE_ALOG = '/tmp/r13-import-tie.alog'
EXPORT_ALOG = '/tmp/r13-export-1042.alog'
EXPORT_TIE_ALOG = '/tmp/r13-export-tie.alog'
FAILS = []
PASSES = [0]
BASE = {}
IMPORTED_BATCH = [0]


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


def static_bbp_full_leg():
    """HUNT-87: bbp_compute must average the whole leg, not
    the RoR span window. A 415 F drop, a 180 F bottom at
    120 s and a 392 F charge at 150 s reads -117.5 F/min in
    and 424.0 out as full-leg averages."""
    ns = extract_fns(CORE, ['bbp_compute'])
    fn = ns['bbp_compute']
    pts = [(0.0, 415.0), (60.0, 300.0), (120.0, 180.0),
           (135.0, 280.0), (150.0, 392.0)]
    got = fn(pts)
    print('HUNT-87 synthetic window:', got, flush=True)
    check('HUNT-87 window time is 150 s',
          got and got['time_sec'] == 150.0, got)
    check('HUNT-87 bottom is 180 F at 120 s',
          got and got['bottom_temp_f'] == 180.0
          and got['bottom_sec'] == 120.0, got)
    check('HUNT-87 RoR in is the full-leg -117.5, not a span',
          got and approx(got['ror_in_f_min'], -117.5, 0.01),
          got and got['ror_in_f_min'])
    check('HUNT-87 RoR out is the full-leg 424.0, not a span',
          got and approx(got['ror_out_f_min'], 424.0, 0.01),
          got and got['ror_out_f_min'])
    first = fn([(0.0, 180.0), (60.0, 280.0), (120.0, 392.0)])
    check('HUNT-87 bottom-first edge reads RoR in 0.0',
          first and first['ror_in_f_min'] == 0.0
          and approx(first['ror_out_f_min'], 106.0, 0.01), first)
    last = fn([(0.0, 415.0), (60.0, 300.0), (120.0, 180.0)])
    check('HUNT-87 bottom-last edge reads RoR out 0.0',
          last and last['ror_out_f_min'] == 0.0
          and approx(last['ror_in_f_min'], -117.5, 0.01), last)
    check('HUNT-87 a single point returns None',
          fn([(0.0, 400.0)]) is None)
    src = open(CORE).read()
    check('HUNT-87 the span helper is gone from core',
          '_bbp_interp' not in src, '')


def _computed_inputs():
    """The crafted curve shared by the HUNT-88, HUNT-89 and
    HUNT-91 static checks: a dipping curve with Dry End,
    FC Start and Drop stamped, weights, volumes, moistures
    and a density recorded."""
    timex = [float(t) for t in range(0, 601, 60)]
    temp2 = [392.0, 340.0, 360.0, 380.0, 390.0, 399.0, 405.0,
             410.0, 413.0, 416.0, 419.0]
    temp1 = [-1.0] * len(timex)
    ti = [0, 3, 6, 0, 0, 0, 10, 0]
    meta = {'ChargeWeightG': 200.0, 'WeightOutG': 172.0,
            'DefectsWeightG': 10.0, 'VolumeInMl': 500.0,
            'VolumeOutMl': 650.0, 'MoisturePct': 11.0,
            'RoastedMoisturePct': 1.5, 'DensityGL': 700.0,
            'GreensTempF': 70.0}
    doc = {'metadata': meta,
           'aucDetail': {'begin': 'TP', 'baseF': 212.0,
                         'fromEvent': False},
           'phaseAnalysis': {'fcsRorFMin': 12.0}}
    return timex, temp1, temp2, ti, doc


def static_computed_for():
    """HUNT-88, HUNT-89 and HUNT-91: the export computed
    block on the crafted curve. Hand-computed expectations
    are in the findings file; every value below was worked
    out from the Artisan formulas, not copied from the code
    under test."""
    bns = extract_fns(BATCHES, ['_weight_loss',
                                '_volume_increase'])

    class BatchesStub(object):
        _weight_loss = staticmethod(bns['_weight_loss'])
        _volume_increase = staticmethod(bns['_volume_increase'])

    ns = extract_fns(ARTISAN, ['_computed_for', '_num',
                                '_proper', '_to_f', '_from_f'],
                     extra={'batches': BatchesStub})
    fn = ns['_computed_for']
    timex, temp1, temp2, ti, doc = _computed_inputs()
    c = fn({}, timex, temp1, temp2, ti, 'F', doc)
    print('HUNT-88/91 computed:', {k: c[k] for k in sorted(c)},
          flush=True)
    check('HUNT-88 default AUCbegin TP',
          c.get('AUCbegin') == 'TP', c.get('AUCbegin'))
    check('HUNT-88 default AUCfromeventflag 0',
          c.get('AUCfromeventflag') == 0,
          c.get('AUCfromeventflag'))
    check('HUNT-88 default AUCbase 212.0',
          c.get('AUCbase') == 212.0, c.get('AUCbase'))
    check('HUNT-88 default AUC 914 C-min',
          c.get('AUC') == 914, c.get('AUC'))
    check('HUNT-91 weight_loss 14.0',
          c.get('weight_loss') == 14.0, c.get('weight_loss'))
    check('HUNT-91 total_yield 162.0 g, not a percent',
          c.get('total_yield') == 162.0, c.get('total_yield'))
    check('HUNT-91 total_loss 19.0',
          c.get('total_loss') == 19.0, c.get('total_loss'))
    check('HUNT-91 roast defects loss 5.8',
          c.get('roast_defects_loss') == 5.8,
          c.get('roast_defects_loss'))
    check('HUNT-91 volume_gain 30.0',
          c.get('volume_gain') == 30.0, c.get('volume_gain'))
    check('HUNT-91 volumein 0.5 L',
          c.get('volumein') == 0.5, c.get('volumein'))
    check('HUNT-91 volumeout 0.65 L',
          c.get('volumeout') == 0.65, c.get('volumeout'))
    check('HUNT-91 roast defects weight 10.0',
          c.get('roast_defects_weight') == 10.0,
          c.get('roast_defects_weight'))
    check('HUNT-91 green density 400.0 g/L',
          c.get('green_density') == 400.0,
          c.get('green_density'))
    check('HUNT-91 roasted density 264.6 g/L',
          c.get('roasted_density') == 264.6,
          c.get('roasted_density'))
    check('HUNT-91 moisture loss 9.5',
          c.get('moisture_loss') == 9.5, c.get('moisture_loss'))
    check('HUNT-91 organic loss 4.5',
          c.get('organic_loss') == 4.5, c.get('organic_loss'))
    check('HUNT-91 set density 700.0',
          c.get('set_density') == 700.0, c.get('set_density'))
    check('HUNT-91 dry phase RoR 103.3 (greens branch)',
          c.get('dry_phase_ror') == 103.3,
          c.get('dry_phase_ror'))
    check('HUNT-91 mid phase RoR 8.3',
          c.get('mid_phase_ror') == 8.3, c.get('mid_phase_ror'))
    check('HUNT-91 finish phase RoR 3.5',
          c.get('finish_phase_ror') == 3.5,
          c.get('finish_phase_ror'))
    check('HUNT-91 dry phase delta 310.0',
          c.get('dry_phase_delta_temp') == 310.0,
          c.get('dry_phase_delta_temp'))
    check('HUNT-91 mid phase delta 25.0',
          c.get('mid_phase_delta_temp') == 25.0,
          c.get('mid_phase_delta_temp'))
    check('HUNT-91 finish phase delta 14.0',
          c.get('finish_phase_delta_temp') == 14.0,
          c.get('finish_phase_delta_temp'))
    check('HUNT-91 total RoR 8.8',
          c.get('total_ror') == 8.8, c.get('total_ror'))
    check('HUNT-91 FCs RoR 12.0',
          c.get('fcs_ror') == 12.0, c.get('fcs_ror'))
    check('HUNT-91 dry phase AUC 250',
          c.get('dry_phase_AUC') == 250, c.get('dry_phase_AUC'))
    check('HUNT-91 mid phase AUC 303',
          c.get('mid_phase_AUC') == 303, c.get('mid_phase_AUC'))
    check('HUNT-91 finish phase AUC 446',
          c.get('finish_phase_AUC') == 446,
          c.get('finish_phase_AUC'))
    check('HUNT-91 total_ts_BT 999',
          c.get('total_ts_BT') == 999, c.get('total_ts_BT'))
    check('HUNT-89 TP index 1 on the plain curve',
          c.get('TP_idx') == 1, c.get('TP_idx'))
    check('HUNT-89 TP time 60 s on the plain curve',
          c.get('TP_time') == 60.0, c.get('TP_time'))

    # HUNT-88: Charge begin reads the whole curve.
    timex, temp1, temp2, ti, doc = _computed_inputs()
    doc['aucDetail'] = {'begin': 'Charge', 'baseF': 212.0,
                        'fromEvent': False}
    c2 = fn({}, timex, temp1, temp2, ti, 'F', doc)
    check('HUNT-88 Charge begin spells CHARGE',
          c2.get('AUCbegin') == 'CHARGE', c2.get('AUCbegin'))
    check('HUNT-88 Charge begin AUC 999',
          c2.get('AUC') == 999, c2.get('AUC'))
    check('HUNT-88 Charge begin flag stays 0',
          c2.get('AUCfromeventflag') == 0,
          c2.get('AUCfromeventflag'))

    # HUNT-88: Dry End begin with fromEvent takes the bean
    # temp at Dry End as the base.
    timex, temp1, temp2, ti, doc = _computed_inputs()
    doc['aucDetail'] = {'begin': 'Dry End', 'baseF': 212.0,
                        'fromEvent': True}
    c3 = fn({}, timex, temp1, temp2, ti, 'F', doc)
    check('HUNT-88 Dry End begin spells DE',
          c3.get('AUCbegin') == 'DE', c3.get('AUCbegin'))
    check('HUNT-88 Dry End base is the Dry End temp 380.0',
          c3.get('AUCbase') == 380.0, c3.get('AUCbase'))
    check('HUNT-88 Dry End flag is 1',
          c3.get('AUCfromeventflag') == 1,
          c3.get('AUCfromeventflag'))
    check('HUNT-88 Dry End AUC 96',
          c3.get('AUC') == 96, c3.get('AUC'))

    # HUNT-88: FC Start begin with fromEvent.
    timex, temp1, temp2, ti, doc = _computed_inputs()
    doc['aucDetail'] = {'begin': 'FC Start', 'baseF': 212.0,
                        'fromEvent': True}
    c4 = fn({}, timex, temp1, temp2, ti, 'F', doc)
    check('HUNT-88 FC Start begin spells FCs',
          c4.get('AUCbegin') == 'FCs', c4.get('AUCbegin'))
    check('HUNT-88 FC Start base is the FC temp 405.0',
          c4.get('AUCbase') == 405.0, c4.get('AUCbase'))
    check('HUNT-88 FC Start AUC 17',
          c4.get('AUC') == 17, c4.get('AUC'))

    # HUNT-88: C mode with no aucDetail (an imported batch)
    # defaults to a 100 C base from the turning point.
    temp2c = [200.0, 170.0, 180.0, 190.0, 195.0, 199.0, 202.0,
              205.0, 207.0, 209.0, 210.0]
    timex, temp1, _t, ti, doc = _computed_inputs()
    doc.pop('aucDetail', None)
    c5 = fn({}, timex, temp1, temp2c, ti, 'C', doc)
    check('HUNT-88 C mode AUCbase 100.0',
          c5.get('AUCbase') == 100.0, c5.get('AUCbase'))
    check('HUNT-88 C mode AUC 877',
          c5.get('AUC') == 877, c5.get('AUC'))
    check('HUNT-88 C mode flag 0',
          c5.get('AUCfromeventflag') == 0,
          c5.get('AUCfromeventflag'))
    check('HUNT-91 C mode FCs RoR converts to 6.7',
          c5.get('fcs_ror') == 6.7, c5.get('fcs_ror'))
    check('HUNT-91 C mode dry RoR 56.3',
          c5.get('dry_phase_ror') == 56.3,
          c5.get('dry_phase_ror'))

    # HUNT-89: a flat bottom ties the minimum at two samples;
    # the turning point is the LATER one.
    temp2t = [392.0, 350.0, 340.0, 340.0, 360.0, 380.0, 395.0,
              405.0, 412.0, 416.0, 419.0]
    timex, temp1, _t, ti, doc = _computed_inputs()
    ct = fn({}, timex, temp1, temp2t, ti, 'F', doc)
    check('HUNT-89 tied minimum keeps the later index 3',
          ct.get('TP_idx') == 3, ct.get('TP_idx'))
    check('HUNT-89 tied minimum TP time is 180 s',
          ct.get('TP_time') == 180.0, ct.get('TP_time'))

    # HUNT-91: a monotonic curve puts the turning point at
    # the first sample, so Artisan's TP/DRY gate skips the
    # whole phase RoR block (no dry, mid, finish, total or
    # FCs RoR), while the phase AUCs still land.
    temp2m = [300.0, 310.0, 320.0, 330.0, 340.0, 350.0, 360.0,
              370.0, 380.0, 390.0, 400.0]
    timex, temp1, _t, ti, doc = _computed_inputs()
    cm = fn({}, timex, temp1, temp2m, ti, 'F', doc)
    check('HUNT-91 TP at the first sample skips dry RoR',
          'dry_phase_ror' not in cm, cm.get('dry_phase_ror'))
    check('HUNT-91 TP at the first sample skips mid RoR',
          'mid_phase_ror' not in cm, cm.get('mid_phase_ror'))
    check('HUNT-91 TP at the first sample skips finish RoR',
          'finish_phase_ror' not in cm,
          cm.get('finish_phase_ror'))
    check('HUNT-91 TP at the first sample skips total RoR',
          'total_ror' not in cm, cm.get('total_ror'))
    check('HUNT-91 TP at the first sample skips FCs RoR',
          'fcs_ror' not in cm, cm.get('fcs_ror'))
    check('HUNT-91 monotonic dry phase AUC still 172',
          cm.get('dry_phase_AUC') == 172,
          cm.get('dry_phase_AUC'))
    check('HUNT-91 monotonic mid phase AUC still 222',
          cm.get('mid_phase_AUC') == 222,
          cm.get('mid_phase_AUC'))
    check('HUNT-91 monotonic finish phase AUC still 373',
          cm.get('finish_phase_AUC') == 373,
          cm.get('finish_phase_AUC'))
    check('HUNT-91 monotonic total_ts_BT still 767',
          cm.get('total_ts_BT') == 767, cm.get('total_ts_BT'))
    check('HUNT-91 monotonic AUC 767',
          cm.get('AUC') == 767, cm.get('AUC'))


def static_phase_analysis_tp_tie():
    """HUNT-89: the phase analysis offline fallback scan
    keeps the LATEST tied minimum. A flat bottom at 60 s and
    90 s reads the turning point at 01:30, and the Drying
    RoR is measured from that later point."""
    cns = extract_fns(CORE, ['shares_100'])

    class CoreStub(object):
        shares_100 = staticmethod(cns['shares_100'])

        @staticmethod
        def compute_ror_series(points, params, offline=False):
            return []

        @staticmethod
        def ror_params():
            return {}

    ns = extract_fns(BATCHES, ['_phase_analysis',
                               '_interp_pairs', '_auc_range',
                               '_mmss'],
                     extra={'core': CoreStub})
    fn = ns['_phase_analysis']
    doc = {'batchNumber': 1099, 'totalSec': 180,
           'events': {'charge': {'t': 0, 'tempF': 392.0},
                      'dryEnd': {'t': 180, 'tempF': 390.0},
                      'fcStart': None, 'drop': None},
           'metadata': {}}
    points = [(0, 392.0), (30, 350.0), (60, 340.0), (90, 340.0),
              (120, 360.0), (150, 380.0), (180, 390.0)]
    rows, tp_text, extra = fn(doc, points)
    print('HUNT-89 phase analysis TP:', tp_text, 'rows:', rows,
          flush=True)
    check('HUNT-89 phase analysis TP is the later tie 01:30',
          tp_text == '340 F at 01:30', tp_text)
    check('HUNT-89 Drying gain is 50 F from the later TP',
          rows and rows[0][3] == '+50 F', rows)
    check('HUNT-89 Drying RoR is 33.3 from the later TP',
          rows and rows[0][4] == '33.3 F/min', rows)


def static_tp_tracker_source():
    """HUNT-89: the live turning point tracker uses
    less-than-or-equal, matching the offline read."""
    src = open(CORE).read()
    seg = src.split('def _track_turning_point')[1].split(
        'def _reset_live_analytics')[0]
    check('HUNT-89 live tracker uses temp <= min_t',
          'temp <= min_t' in seg, '')
    check('HUNT-89 live tracker no longer uses strict less-than',
          'temp < min_t' not in seg, '')


def static_calc_clamps():
    """HUNT-90: the calculator expressions clamp both ends
    in the setup script (the source of truth for the tags)."""
    src = open(SETUP).read()
    m = re.search(r"'ExpectedOutG'.*?'expression':\s*'([^']+)'",
                  src, re.S)
    check('HUNT-90 setup script defines ExpectedOutG',
          m is not None, '')
    expr = m.group(1) if m else ''
    print('HUNT-90 ExpectedOutG expression:', expr, flush=True)
    check('HUNT-90 ExpectedOutG clamps the loss to 0..100',
          'max(0, min(100,' in expr, expr)
    check('HUNT-90 ExpectedOutG no longer uses the raw loss',
          '{[.]ChargeG} * (1 - {[.]LossPct} / 100.0)' not in expr,
          expr)
    m2 = re.search(r"'ActualLossPct'.*?'expression':\s*'([^']+)'",
                   src, re.S)
    check('HUNT-90 setup script defines ActualLossPct',
          m2 is not None, '')
    expr2 = m2.group(1) if m2 else ''
    print('HUNT-90 ActualLossPct expression:', expr2, flush=True)
    check('HUNT-90 ActualLossPct clamps to 0..100',
          'min(100, max(0,' in expr2, expr2)


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
    """Click a dock button until the workspace state advances
    (a click dispatched while the dock re-renders its phase
    set can be swallowed, proven in tier3c)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if P.tag(B + '/State') == state:
            return True
        click_visible(page, name)
        time.sleep(1.2)
    return P.tag(B + '/State') == state


def dock_prereq(dock):
    """Phase aware dock: Drop is offered only after FC End, so
    stamp the prerequisite events through the dock first.
    Each click waits for the dock to re-render its next phase
    set (tier3c's helper, copied verbatim)."""
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


def calc_live():
    """HUNT-90 live: the Calculator expression tags read the
    clamped values, and the live expressions carry the
    clamps. The calculator inputs are restored to their
    entry values (200/15/172)."""
    st, out = api('GET', '/tags/export',
                  params={'provider': 'default', 'type': 'json',
                          'path': 'Roastery/Calculator',
                          'recursive': 'true'})
    check('HUNT-90 Calculator folder exports', st == 200, st)

    def find(node, name):
        if isinstance(node, dict):
            if node.get('name') == name:
                return node.get('expression')
            for v in node.values():
                r = find(v, name)
                if r is not None:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = find(v, name)
                if r is not None:
                    return r
        return None

    expr_e = find(out, 'ExpectedOutG') if st == 200 else None
    expr_a = find(out, 'ActualLossPct') if st == 200 else None
    print('HUNT-90 live ExpectedOutG:', expr_e, flush=True)
    print('HUNT-90 live ActualLossPct:', expr_a, flush=True)
    check('HUNT-90 live ExpectedOutG clamps the loss to 0..100',
          expr_e is not None and 'max(0, min(100,' in expr_e,
          expr_e)
    check('HUNT-90 live ActualLossPct clamps to 0..100',
          expr_a is not None and 'min(100, max(0,' in expr_a,
          expr_a)
    charge0 = P.tag(CALC + '/ChargeG')
    loss0 = P.tag(CALC + '/LossPct')
    out0 = P.tag(CALC + '/OutG')
    P.write_tags([(CALC + '/ChargeG', 200.0),
                  (CALC + '/LossPct', 150.0),
                  (CALC + '/OutG', 172.0)])
    time.sleep(2)
    check('HUNT-90 live expected out reads 0.0 at a 150% loss',
          P.tag(CALC + '/ExpectedOutG') == 0.0,
          P.tag(CALC + '/ExpectedOutG'))
    P.write_tags([(CALC + '/LossPct', -10.0)])
    time.sleep(2)
    check('HUNT-90 live expected out reads 200.0 at a -10% loss',
          P.tag(CALC + '/ExpectedOutG') == 200.0,
          P.tag(CALC + '/ExpectedOutG'))
    P.write_tags([(CALC + '/LossPct', 15.0),
                  (CALC + '/OutG', -10.0)])
    time.sleep(2)
    check('HUNT-90 live loss reads 100.0 at a -10 g out weight',
          P.tag(CALC + '/ActualLossPct') == 100.0,
          P.tag(CALC + '/ActualLossPct'))
    P.write_tags([(CALC + '/ChargeG', charge0),
                  (CALC + '/LossPct', loss0),
                  (CALC + '/OutG', out0)])
    time.sleep(2)
    check('HUNT-90 calculator inputs restored to their entry '
          'values',
          P.tag(CALC + '/ChargeG') == charge0
          and P.tag(CALC + '/LossPct') == loss0
          and P.tag(CALC + '/OutG') == out0,
          (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/LossPct'),
           P.tag(CALC + '/OutG')))


def auc_int(timex, temp2, a, b, base_f, mode='F'):
    """Independent trapezoid area above base over sample
    indices [a, b], in C-min, the shape _computed_for uses
    (the HUNT-62 exact integral, not Artisan's off-by-one)."""
    total = 0.0
    for i in range(a, min(b, len(temp2) - 1)):
        dt = (float(timex[i + 1]) - float(timex[i])) / 60.0
        if dt <= 0:
            continue
        avg = (float(temp2[i]) + float(temp2[i + 1])) / 2.0
        avg -= base_f
        if avg > 0:
            total += avg * dt
    if mode == 'F':
        total *= 5.0 / 9.0
    return int(round(total))


def export_1042(pw):
    """HUNT-88 and HUNT-91 live: export batch 1042 as .alog
    and read the computed block back. 1042 has no aucDetail
    and no dry or FC events, so the flag defaults to 0, the
    phase RoRs are skipped by the TP gate, and only the
    always-written keys and total_ts_BT land."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    R5.stage_one(1042)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(2500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    with pg.expect_download(timeout=30000) as dl_info:
        pg.get_by_role('button', name='Export .alog').first.click()
    dl = dl_info.value
    dl.save_as(EXPORT_ALOG)
    prof = ast.literal_eval(open(EXPORT_ALOG).read())
    comp = prof.get('computed') or {}
    print('HUNT-88/91 exported 1042 computed:', comp, flush=True)
    check('HUNT-88 export AUCfromeventflag is 0 by default',
          comp.get('AUCfromeventflag') == 0,
          comp.get('AUCfromeventflag'))
    check('HUNT-88 export AUCbase stays 212.0 in F mode',
          comp.get('AUCbase') == 212.0, comp.get('AUCbase'))
    check('HUNT-88 export AUCbegin stays TP by default',
          comp.get('AUCbegin') == 'TP', comp.get('AUCbegin'))
    check('HUNT-91 export weight_loss reads 14.0 for 200/172',
          comp.get('weight_loss') == 14.0, comp)
    check('HUNT-91 export total_yield is 172.0 g',
          comp.get('total_yield') == 172.0, comp)
    check('HUNT-91 export total_loss reads 14.0',
          comp.get('total_loss') == 14.0, comp)
    check('HUNT-91 export carries no defects loss for 1042',
          'roast_defects_loss' not in comp, comp)
    check('HUNT-91 export volumein is written as 0.0',
          comp.get('volumein') == 0.0, comp.get('volumein'))
    check('HUNT-91 export volumeout is written as 0.0',
          comp.get('volumeout') == 0.0, comp.get('volumeout'))
    check('HUNT-91 export defects weight is written as 0.0',
          comp.get('roast_defects_weight') == 0.0,
          comp.get('roast_defects_weight'))
    check('HUNT-91 export carries no volume gain for 1042',
          'volume_gain' not in comp, comp)
    check('HUNT-91 export carries no moisture loss for 1042',
          'moisture_loss' not in comp, comp)
    check('HUNT-91 export carries no organic loss for 1042',
          'organic_loss' not in comp, comp)
    check('HUNT-91 export carries no green density for 1042',
          'green_density' not in comp, comp)
    check('HUNT-91 export carries no roasted density for 1042',
          'roasted_density' not in comp, comp)
    check('HUNT-91 export carries no set density for 1042',
          'set_density' not in comp, comp)
    check('HUNT-91 export carries no dry RoR (TP at sample 0)',
          'dry_phase_ror' not in comp, comp)
    check('HUNT-91 export carries no mid RoR (TP at sample 0)',
          'mid_phase_ror' not in comp, comp)
    check('HUNT-91 export carries no finish RoR (TP at sample 0)',
          'finish_phase_ror' not in comp, comp)
    check('HUNT-91 export carries no total RoR (TP at sample 0)',
          'total_ror' not in comp, comp)
    check('HUNT-91 export carries no FCs RoR (TP at sample 0)',
          'fcs_ror' not in comp, comp)
    check('HUNT-91 export carries no dry phase AUC (no Dry End)',
          'dry_phase_AUC' not in comp, comp)
    check('HUNT-91 export carries no mid phase AUC (no Dry End)',
          'mid_phase_AUC' not in comp, comp)
    check('HUNT-91 export carries no finish AUC (no FC Start)',
          'finish_phase_AUC' not in comp, comp)
    timex = [float(v) for v in prof['timex']]
    temp2 = [float(v) for v in prof['temp2']]
    ti = prof['timeindex']
    start = int(comp['TP_idx']) if 'TP_idx' in comp else int(ti[0])
    end = int(ti[6])
    want = auc_int(timex, temp2, start, end, 212.0, 'F')
    print('HUNT-88 exported AUC=%s want=%s' % (comp.get('AUC'),
                                                want), flush=True)
    check('HUNT-88 export AUC matches the recompute',
          comp.get('AUC') == want, (comp.get('AUC'), want))
    want_ts = auc_int(timex, temp2, int(ti[0]), end, 212.0, 'F')
    check('HUNT-91 export total_ts_BT matches the recompute',
          comp.get('total_ts_BT') == want_ts,
          (comp.get('total_ts_BT'), want_ts))
    R5.shot(pg, 'r13-fresh-detail-1042-export.png')
    b.close()


def craft_tie_alog():
    """The sample fixture with its curve minimum tied at two
    adjacent samples (the minimum 171.08615569 F at fixture
    index 36, copied to index 37) and a fresh roastUUID so
    the duplicate guard does not fire."""
    data = ast.literal_eval(open(FIXTURE).read())
    mn = min(data['temp2'][:data['timeindex'][2]])
    idx = data['temp2'].index(mn)
    data['temp2'][idx + 1] = mn
    data['roastUUID'] = uuid.uuid4().hex
    with open(TIE_ALOG, 'w') as f:
        f.write(repr(data) + '\n')
    return TIE_ALOG, idx, idx + 1


def upload(page, path):
    """ia.input.fileupload mounts its <input type=file> only
    after the component is clicked (proven in the Artisan
    rounds); click until one input exists, then set files."""
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


def import_tie_live(pw):
    """HUNT-89 and HUNT-91 live: import the tied-minimum
    .alog through the Log page upload, then export the new
    batch and read the turning point and the phase keys back.
    The expectation is computed from the exported arrays
    themselves, so it does not depend on the export's index
    convention."""
    path, first_idx, second_idx = craft_tie_alog()
    print('HUNT-89 tied minimum at fixture indices %d and %d'
          % (first_idx, second_idx), flush=True)
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
    check('HUNT-89 tied-minimum .alog imports as a new batch',
          bool(ok), P.psql('SELECT COUNT(*) FROM batches'))
    nxt = int(P.psql('SELECT MAX(batch_number) FROM batches'))
    IMPORTED_BATCH[0] = nxt
    note = pg.locator('body').inner_text()
    check('HUNT-89 import note names the new batch',
          ('Imported' in note and str(nxt) in note), note[:200])
    R5.stage_one(nxt)
    pg2 = R5.open_page(ctx, '/log/detail')
    pg2.wait_for_timeout(2500)
    with pg2.expect_download(timeout=30000) as dl_info:
        pg2.get_by_role('button',
                        name='Export .alog').first.click()
    dl = dl_info.value
    dl.save_as(EXPORT_TIE_ALOG)
    prof = ast.literal_eval(open(EXPORT_TIE_ALOG).read())
    comp = prof.get('computed') or {}
    timex = [float(v) for v in prof['timex']]
    temp2 = [float(v) for v in prof['temp2']]
    ti = prof['timeindex']
    print('HUNT-89 exported tie computed:', comp, flush=True)
    lo = int(ti[0])
    hi = int(ti[2]) if ti[2] else int(ti[6])
    scan = temp2[lo:hi]
    mn = min(scan)
    tied = [lo + i for i, v in enumerate(scan) if v == mn]
    print('HUNT-89 tied indices in the export:', tied,
          'TP_idx:', comp.get('TP_idx'), flush=True)
    check('HUNT-89 the export has two tied minima',
          len(tied) == 2, tied)
    check('HUNT-89 exported TP is the LATER tied sample',
          comp.get('TP_idx') == tied[-1],
          (comp.get('TP_idx'), tied))
    want_time = timex[comp.get('TP_idx')] - timex[lo]
    check('HUNT-89 exported TP time is the later sample time',
          comp.get('TP_time') == want_time,
          (comp.get('TP_time'), want_time))
    # HUNT-91 phase keys on a batch that stamps Dry End and
    # FC Start: recompute each from the exported event temps
    # and times, independently of the export's own numbers.
    dry_t = comp.get('DRY_time')
    fc_t = comp.get('FCs_time')
    drop_t = comp.get('DROP_time')
    dry_bt = comp.get('DRY_BT')
    fc_bt = comp.get('FCs_BT')
    drop_bt = comp.get('DROP_BT')
    tp_bt = comp.get('TP_BT')
    tp_t = comp.get('TP_time')
    greens = prof.get('greens_temp')
    if greens and float(greens) > 0:
        want_dry = round((dry_bt - float(greens)) / dry_t * 60.0,
                         1)
    else:
        want_dry = round((dry_bt - tp_bt) / (dry_t - tp_t)
                         * 60.0, 1)
    want_mid = round((fc_bt - dry_bt) / (fc_t - dry_t) * 60.0, 1)
    want_fin = round((drop_bt - fc_bt) / (drop_t - fc_t)
                     * 60.0, 1)
    want_tot = round((drop_bt - tp_bt) / (drop_t - tp_t)
                     * 60.0, 1)
    print('HUNT-91 tie phase RoRs want dry/mid/fin/tot:',
          want_dry, want_mid, want_fin, want_tot, flush=True)
    check('HUNT-91 tie export dry RoR matches the recompute',
          approx(comp.get('dry_phase_ror'), want_dry, 0.15),
          (comp.get('dry_phase_ror'), want_dry))
    check('HUNT-91 tie export mid RoR matches the recompute',
          approx(comp.get('mid_phase_ror'), want_mid, 0.15),
          (comp.get('mid_phase_ror'), want_mid))
    check('HUNT-91 tie export finish RoR matches the recompute',
          approx(comp.get('finish_phase_ror'), want_fin, 0.15),
          (comp.get('finish_phase_ror'), want_fin))
    check('HUNT-91 tie export total RoR matches the recompute',
          approx(comp.get('total_ror'), want_tot, 0.15),
          (comp.get('total_ror'), want_tot))
    check('HUNT-91 tie export dry delta matches',
          approx(comp.get('dry_phase_delta_temp'),
                 round(dry_bt - float(greens), 1)
                 if greens and float(greens) > 0
                 else round(dry_bt - tp_bt, 1), 0.15),
          comp.get('dry_phase_delta_temp'))
    check('HUNT-91 tie export mid delta matches',
          approx(comp.get('mid_phase_delta_temp'),
                 round(fc_bt - dry_bt, 1), 0.15),
          comp.get('mid_phase_delta_temp'))
    check('HUNT-91 tie export finish delta matches',
          approx(comp.get('finish_phase_delta_temp'),
                 round(drop_bt - fc_bt, 1), 0.15),
          comp.get('finish_phase_delta_temp'))
    want_dauc = auc_int(timex, temp2, int(ti[0]), int(ti[1]),
                        212.0, 'F')
    want_mauc = auc_int(timex, temp2, int(ti[1]), int(ti[2]),
                        212.0, 'F')
    want_fauc = auc_int(timex, temp2, int(ti[2]), int(ti[6]),
                        212.0, 'F')
    want_ts = auc_int(timex, temp2, int(ti[0]), int(ti[6]),
                      212.0, 'F')
    check('HUNT-91 tie export dry AUC matches the recompute',
          comp.get('dry_phase_AUC') == want_dauc,
          (comp.get('dry_phase_AUC'), want_dauc))
    check('HUNT-91 tie export mid AUC matches the recompute',
          comp.get('mid_phase_AUC') == want_mauc,
          (comp.get('mid_phase_AUC'), want_mauc))
    check('HUNT-91 tie export finish AUC matches the recompute',
          comp.get('finish_phase_AUC') == want_fauc,
          (comp.get('finish_phase_AUC'), want_fauc))
    check('HUNT-91 tie export total_ts_BT matches the recompute',
          comp.get('total_ts_BT') == want_ts,
          (comp.get('total_ts_BT'), want_ts))
    check('HUNT-91 tie export AUCfromeventflag is 0 by default',
          comp.get('AUCfromeventflag') == 0,
          comp.get('AUCfromeventflag'))
    R5.shot(pg2, 'r13-fresh-detail-tie-export.png')
    delete_batch_ui(pg, nxt)
    b.close()
    # Opening the detail page seeded the Calculator from the
    # imported batch (detail_startup calculator_seed), so put
    # the lab calculator back to its entry values.
    P.write_tags([(CALC + '/ChargeG', 200.0),
                  (CALC + '/LossPct', 15.0),
                  (CALC + '/OutG', 172.0)])
    time.sleep(1)
    check('HUNT-89 calculator restored to 200/15/172 after the '
          'import',
          P.tag(CALC + '/ChargeG') == 200.0
          and P.tag(CALC + '/LossPct') == 15.0
          and P.tag(CALC + '/OutG') == 172.0,
          (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/LossPct'),
           P.tag(CALC + '/OutG')))


def bbp_full_leg(samples):
    """Independent full-leg recompute of the BBP metrics from
    staged samples (Artisan calcBBPMetrics shape). None when
    the window cannot support them."""
    if len(samples) < 2 or samples[-1][0] <= samples[0][0]:
        return None
    bottom = min(v for _t, v in samples)
    tb = [t for t, v in samples if v == bottom][0]
    t_first, t_last = samples[0][0], samples[-1][0]
    ror_in = ((bottom - samples[0][1]) * 60.0 / (tb - t_first)
              if tb > t_first else 0.0)
    ror_out = ((samples[-1][1] - bottom) * 60.0 / (t_last - tb)
               if t_last > tb else 0.0)
    return {'time_sec': t_last - t_first,
            'bottom_temp_f': bottom, 'ror_in_f_min': ror_in,
            'ror_out_f_min': ror_out}


def _interp(pts, t):
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t0 <= t <= t1:
            return v1 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) \
                / (t1 - t0)
    return pts[-1][1]


def bbp_span_slope(samples, span):
    """The OLD definition (tier3c's bbp_expected): span slopes
    with linear interpolation. Used only to show the staged
    values are not the old ones. None when the window cannot
    support them."""
    if len(samples) < 2 or samples[-1][0] <= samples[0][0]:
        return None
    bottom = min(v for _t, v in samples)
    tb = [t for t, v in samples if v == bottom][0]
    t_first, t_last = samples[0][0], samples[-1][0]
    ror_in = ((bottom - _interp(samples, max(t_first, tb - span)))
              * 60.0 / (tb - max(t_first, tb - span))
              if tb > t_first else 0.0)
    ror_out = ((_interp(samples, min(t_last, tb + span)) - bottom)
               * 60.0 / (min(t_last, tb + span) - tb)
               if t_last > tb else 0.0)
    return {'ror_in_f_min': ror_in, 'ror_out_f_min': ror_out}


def bbp_live(pw):
    """HUNT-87 live: roast 1, DROP, then a curved falling
    and rising window through the WebSocket source (fast
    fall flattening into the bottom, slow rise steepening
    away from it), CHARGE roast 2 and read the staged
    metrics. The curve shape makes the full-leg averages
    differ from the old span slopes by more than 40 F/min
    on both legs, so the comparison proves which definition
    the gateway used. Roast 1 is never saved; roast 2 is
    saved and deleted, and the workspace is reset."""
    base = (int(P.psql('SELECT COUNT(*) FROM batches')),
            int(P.psql('SELECT COUNT(*) FROM batch_series')),
            int(P.psql('SELECT COUNT(*) FROM batch_events')))
    max_event_id = int(P.psql(
        'SELECT COALESCE(MAX(id), 0) FROM batch_events'))
    span0 = P.tag(B + '/RoRDeltaSpanSec')
    P.write_tags([(B + '/RoRDeltaSpanSec', 6)])
    # Two separate browsers, one context each: R5.launch is a
    # single-process headless shell, and opening a second
    # context in the same browser closed it twice in a row
    # (TargetClosedError on the mobile new_page, runs 1 and
    # 2). Tier3c uses a plain multi-process launch for its
    # two pages; the single-process shell only holds one
    # context reliably, so desk and mob get their own.
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
    check('HUNT-87 new roast workspace for roast 1',
          roast1 > 1048 and P.tag(B + '/State') == 'Idle',
          roast1)
    P.write_tags([(B + '/ActiveSource', 'WebSocket'),
                  (WS, 400.0)])
    ok = P.wait_until(
        lambda: approx(P.tag(B + '/BeanTempF'), 400.0, 0.01), 20)
    check('HUNT-87 WebSocket source drives the bean temp',
          bool(ok), P.tag(B + '/BeanTempF'))
    # Re-navigate both pages to the Roast page before the
    # dock clicks (tier3c's pattern): run 3 showed a dock
    # mounted before the New Roast press never offered Drop
    # after Charge, while a freshly navigated dock does.
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
    check('HUNT-87 roast 1 charge starts',
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
    # Drop is offered only after FC End, so stamp the
    # prerequisite events first; the DROP to CHARGE duration
    # is measured from the Drop press itself, so the timestamp
    # is taken after the prerequisite stamps.
    dock_prereq(dock)
    t_drop_click = time.time()
    dock.get_by_role('button', name='Drop').click()
    check('HUNT-87 roast 1 drop lands',
          P.wait_tag(B + '/State', 'Dropped'))
    check('HUNT-87 BBP window opened at DROP',
          P.wait_tag(BBP + '/WindowActive', True, timeout=15))
    mob.wait_for_timeout(1600)
    seq = [380.0, 360.0, 345.0, 335.0, 330.0, 328.0, 329.0,
           331.0, 335.0, 342.0, 355.0, 372.0, 390.0]
    for v in seq:
        P.write_tags([(WS, v)])
        P.wait_until(lambda: approx(P.tag(B + '/BeanTempF'), v,
                                    0.01), 15)
        mob.wait_for_timeout(1700)
    cols, srows = ds_rows(P.tag('[default]Roastery/BbpSamplesDS'))
    ti, vi = (cols.index('t_offset_sec'),
              cols.index('bean_temp_f'))
    samples = sorted((float(r[ti]), float(r[vi])) for r in srows)
    print('HUNT-87 window samples:', samples, flush=True)
    check('HUNT-87 window staged at least 12 samples',
          len(samples) >= 12, len(samples))
    check('HUNT-87 staged bottom is the written minimum 328 F',
          samples and min(v for _t, v in samples) == 328.0,
          samples)
    check('HUNT-87 window starts at the drop temp 404 F',
          samples and approx(samples[0][1], 404.0, 0.5),
          samples and samples[0])
    check('HUNT-87 cool clicked',
          click_until_state(mob, 'Cool', 'Cooling'))
    mob.wait_for_timeout(1600)
    check('HUNT-87 finish clicked',
          click_until_state(desk, 'Finish', 'Complete'))
    check('HUNT-87 window still open in Complete',
          P.tag(BBP + '/WindowActive') is True)
    mob.wait_for_timeout(1600)
    roast2 = roast1 + 1
    P.write_tags([(B + '/BatchNumber', roast2)])
    mob.wait_for_timeout(1500)
    t_charge_click = time.time()
    dock.get_by_role('button', name='Charge').click()
    check('HUNT-87 roast 2 charge starts',
          P.wait_tag(B + '/State', 'Roasting'))
    staged = P.read_tags([BBP + '/HasMetrics', BBP + '/TimeSec',
                          BBP + '/BottomTempF', BBP + '/RorInFMin',
                          BBP + '/RorOutFMin', BBP + '/WindowActive'])
    check('HUNT-87 metrics staged at CHARGE, window closed',
          staged[0] is True and staged[5] is False, staged)
    # The window finalizes at CHARGE by appending a final
    # sample (the bean temp at CHARGE, at the staged TimeSec)
    # and then clears the samples dataset, so the post-CHARGE
    # read is empty. Recompute from the pre-CHARGE samples
    # plus that final sample, the set the gateway used.
    samples_final = list(samples)
    if samples:
        samples_final.append((float(staged[1]),
                              samples[-1][1]))
    expected = bbp_full_leg(samples_final)
    old = bbp_span_slope(samples_final, 6.0)
    print('HUNT-87 staged:', staged, flush=True)
    print('HUNT-87 full-leg recompute:', expected, flush=True)
    print('HUNT-87 old span-6 recompute:', old, flush=True)
    check('HUNT-87 staged bottom matches the recompute',
          expected is not None
          and approx(staged[2], expected['bottom_temp_f'], 0.01),
          staged)
    check('HUNT-87 staged RoR in matches the full-leg recompute',
          expected is not None
          and approx(staged[3], expected['ror_in_f_min'],
                     max(5.0, abs(expected['ror_in_f_min'])
                         * 0.05)),
          (staged[3], expected and expected['ror_in_f_min']))
    check('HUNT-87 staged RoR out matches the full-leg recompute',
          expected is not None
          and approx(staged[4], expected['ror_out_f_min'],
                     max(5.0, abs(expected['ror_out_f_min'])
                         * 0.05)),
          (staged[4], expected and expected['ror_out_f_min']))
    check('HUNT-87 staged RoR in is not the old span slope',
          old is not None
          and abs(staged[3] - old['ror_in_f_min']) > 40,
          (staged[3], old and old['ror_in_f_min']))
    check('HUNT-87 staged RoR out is not the old span slope',
          old is not None
          and abs(staged[4] - old['ror_out_f_min']) > 40,
          (staged[4], old and old['ror_out_f_min']))
    check('HUNT-87 staged time is the DROP to CHARGE duration',
          approx(staged[1], t_charge_click - t_drop_click, 4.0),
          (staged[1], t_charge_click - t_drop_click))
    mob.wait_for_timeout(3500)
    dock_drop(dock)
    check('HUNT-87 roast 2 drop lands',
          P.wait_tag(B + '/State', 'Dropped'))
    desk.goto(P.BASE + '/', wait_until='networkidle',
              timeout=60000)
    desk.wait_for_timeout(5000)
    R5.dismiss(desk)
    desk.get_by_role('button', name='Save Batch').first.click()
    saved2 = P.wait_until(
        lambda: int(P.psql('SELECT COUNT(*) FROM batches WHERE '
                          'batch_number = %d' % roast2)) == 1, 30)
    check('HUNT-87 roast 2 saved', bool(saved2))
    if saved2:
        doc2 = doc_of(roast2)
        bbp_doc = doc2.get('bbp') or {}
        check('HUNT-87 roast 2 doc carries the bbp subdocument',
              set(bbp_doc.keys()) == {'time_sec', 'bottom_temp_f',
                                      'ror_in_f_min',
                                      'ror_out_f_min'}, bbp_doc)
        check('HUNT-87 bbp values match the staged metrics',
              approx(bbp_doc.get('bottom_temp_f'), staged[2], 0.01)
              and approx(bbp_doc.get('ror_in_f_min'), staged[3],
                         0.01)
              and approx(bbp_doc.get('ror_out_f_min'), staged[4],
                         0.01)
              and approx(bbp_doc.get('time_sec'), staged[1], 0.01),
              bbp_doc)
    R5.shot(desk, 'r13-fresh-bbp-roast2-saved.png')
    # Close roast 2 and reset through the app, then clean the
    # two batches and the press rows (tier3c's pattern).
    desk.goto(P.BASE + '/', wait_until='networkidle',
              timeout=60000)
    desk.wait_for_timeout(5000)
    R5.dismiss(desk)
    check('HUNT-87 roast 2 cool clicked',
          click_until_state(mob, 'Cool', 'Cooling'))
    check('HUNT-87 roast 2 finish clicked',
          click_until_state(desk, 'Finish', 'Complete'))
    check('HUNT-87 reset through its button',
          click_until_state(desk, 'Reset / New Roast', 'Idle'))
    check('HUNT-87 reset discarded the window',
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
                  (WS, 0.0)])
    state = P.read_tags([B + '/State', B + '/FanLevel',
                         B + '/HeatLevel', B + '/BatchNumber',
                         B + '/ActiveSource', B + '/Mode'])
    check('HUNT-87 workspace clean Idle after the BBP flow',
          state == ['Idle', 5, 5, 1042, 'Simulated', 'Off'],
          state)
    end = (int(P.psql('SELECT COUNT(*) FROM batches')),
           int(P.psql('SELECT COUNT(*) FROM batch_series')),
           int(P.psql('SELECT COUNT(*) FROM batch_events')))
    check('HUNT-87 lab back to the seeded log after the flow',
          end == base, (end, base))
    # A replayed Charge can land after the checks above (the
    # platform re-delivers a dock click seconds late, proven
    # in tier3c); this probe reset runs after them so the lab
    # is left clean regardless.
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
    check('HUNT-87 lab left clean after the post-check reset',
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
    R5.shot(pg, 'r13-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r13-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r13-fresh-detail-%s.png' % tag)
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
    R5.shot(pg4, 'r13-fresh-settings-%s.png' % tag)
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
        R5.shot(pg, 'r13-settings-sweep-%d-360-dark.png'
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
               P.tag(TM), P.tag(B + '/CompareAlignEvent'),
               P.psql('SELECT COUNT(*) FROM batches')))


def main():
    static_bbp_full_leg()
    static_computed_for()
    static_phase_analysis_tp_tie()
    static_tp_tracker_source()
    static_calc_clamps()
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
            calc_live()
            export_1042(pw)
            import_tie_live(pw)
            bbp_live(pw)
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            # Restore System theme through the UI (the last
            # walk and the sweep both end in Dark).
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
