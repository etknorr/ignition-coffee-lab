#!/usr/bin/env python3
"""Round 10 fresh hunting pass (worker D).

Fresh hunt continuing from HUNT-65. New probes this round:
  1. HUNT-72: the Phase Analysis table Share column summed to
     105 on batch 1042 (26/37/37 plus Cool 5): the Cool row
     carried a share on a different basis (cool seconds over
     the roast plus cool span) while the three phases share
     the drop total. Cool is not a roast phase, so its share
     cell now reads '--' like its gain, RoR and AUC cells.
     Proven statically on the real 1042 document and live in
     the DOM.
  2. HUNT-73: the loss figures could go negative on
     inconsistent metadata. With a 200 g charge, 184 g out
     (8% weight loss) and green moisture 12% against roasted
     2% (10% moisture loss), the organic loss read -2.0%.
     Artisan's dialog clamps it to 0..100 (calc_organic_loss)
     and blanks a moisture loss at or below zero
     (moisture_percent). Proven statically and on the saved
     live roast document.
  3. HUNT-74: the build_document weight loss fallback did
     raw arithmetic, so a roasted weight over the green
     weight (WeightOutG 250 on a 200 g charge) read -25%.
     Artisan weight_loss returns 0 in exactly that case, and
     the fallback now uses _weight_loss. Proven statically
     and through the editor recompute below.
  4. HUNT-75: the slide over editor saved edited weights
     without recomputing doc['weightLossPct'] or doc['loss'],
     so the BatchDetail Weight Loss tile kept the save-time
     value while the Loss section (recomputed live from
     metadata) showed the new one. _update_submit and
     _create_submit now call _recompute_loss. Proven live:
     edit the saved roast's WeightOutG from 184 to 250 and
     the document reads weightLossPct 0.0 with the loss
     block recomputed.
  5. HUNT-76: a Banner alarm fired during the roast stayed
     on the Complete screen after Finish (evaluate_alarms
     only runs while Roasting, Dropped or Cooling, so the
     text never cleared even after the bean cooled). The
     fix clears Banner texts in Complete while keeping
     latched Message alarms per their documented rule.
     Proven live: a temporary Banner def (BT >= 210) fires
     mid-roast and reads clear after Finish.
  6. The four-page walk (Roast, Log, BatchDetail staged
     1042, Settings) at 1360px and 360px, light and dark,
     measuring horizontal overflow and clipped leaf text
     (Perspective footer excluded), the Settings scroll
     sweep at 360px dark, a live roast at 360px dark
     measured at every stage (Charge, Dry End, FC Start,
     ghost, Drop) with the stats line shares and DTR
     checked after Drop, the saved roast's detail at 360px
     light, compare with three batches (A/B/C) at 360px
     dark with the phone All-columns toggle, and static
     Artisan math checks run from the library sources.
  7. Calculator readout adjacency (round 10 candidate 1,
     owned by worker A): measured informationally only,
     the suite records the gaps without failing on them.
  8. The ALIGN ON label gap: measured informationally
     only, as in round 9.

ThemeMode is set only through the App Settings UI flow
(gear, theme button, Close) in this suite, never through
the API, and restored to System the same way at the end.
Does NOT retest the timezone TIME axis passthrough or
HUNT-46 (both beta-gated) and does NOT touch the press
path (HUNT-53 app fix out of scope). Leaves the lab clean.
"""
import ast
import json
import math
import re
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
BG_LABEL = '[default]Roastery/BackgroundLabel'
BG_CURVE = '[default]Roastery/BackgroundCurveJson'
BATCHES = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'batches/code.py')
CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
NEXT_BATCH = [0]
BASE = {'batches': '7', 'series': '101', 'events': '0'}
FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '')
    if not cond:
        FAILS.append(name)


OVERFLOW_JS = """() => {
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


def caption_texts(pg):
    return pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")


def click_btn(pg, name, timeout=20000):
    pg.locator('button').filter(has_text=name).first.click(
        timeout=timeout)


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


def static_auc():
    """HUNT-62 regression: auc_between vs the exact
    from-begin integral (same shapes as round 9)."""
    ns = extract_fns(CORE, ['auc_between'])
    auc_between = ns['auc_between']

    def exact_integral(points, begin_sec, base):
        total = 0.0
        for i in range(len(points) - 1):
            t0, v0 = points[i]
            t1, v1 = points[i + 1]
            if t1 <= begin_sec or t1 <= t0:
                continue
            a = max(t0, begin_sec)
            va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
            avg = (va + v1) / 2.0
            if avg > base:
                total += (avg - base) * (t1 - a) / 60.0
        return total

    pts = [(float(t), 200.0 + 0.4 * t) for t in range(0, 301)]
    got = auc_between(pts, 70.5, 200.0)
    want = exact_integral(pts, 70.5, 200.0)
    print('HUNT-62 auc_between=%.4f exact=%.4f'
          % (got, want), flush=True)
    check('HUNT-62 live AUC integrates from the begin second',
          abs(got - want) < 0.001,
          'got %.4f want %.4f' % (got, want))


def static_shares():
    """HUNT-63 regression: largest remainder shares."""
    ns = extract_fns(CORE, ['shares_100'])
    shares_100 = ns['shares_100']
    got = shares_100([8.0, 4.0, 6.0], 18.0)
    check('HUNT-63 shares 8/4/6 sum to 100 as 45/22/33',
          got == [45, 22, 33], got)
    got2 = shares_100([5.0, 7.0, 7.0], 19.0)
    check('HUNT-63 seeded 1042 shares sum to 100 as 26/37/37',
          got2 == [26, 37, 37] and sum(got2) == 100, got2)


def static_loss():
    """HUNT-73: loss_yield_density on inconsistent metadata.
    Artisan's dialog clamps the organic loss to 0..100
    (calc_organic_loss) and blanks a moisture loss at or
    below zero (moisture_percent); the stored computed
    block keeps the raw subtraction, the detail page is
    the dialog side."""
    ns = extract_fns(BATCHES, ['loss_yield_density',
                                '_weight_loss', '_volume_increase'])
    fn = ns['loss_yield_density']
    meta = {'ChargeWeightG': 200.0, 'WeightOutG': 184.0,
            'MoisturePct': 12.0, 'RoastedMoisturePct': 2.0}
    out = fn(meta)
    print('HUNT-73 loss block:', out, flush=True)
    check('HUNT-73 moisture loss reads 10.0',
          out.get('moistureLossPct') == 10.0, out)
    check('HUNT-73 organic loss clamps to 0.0, not -2.0',
          out.get('organicLossPct') == 0.0, out)
    meta2 = {'ChargeWeightG': 200.0, 'WeightOutG': 184.0,
             'MoisturePct': 8.0, 'RoastedMoisturePct': 11.0}
    out2 = fn(meta2)
    check('HUNT-73 negative moisture loss is omitted, not stored',
          'moistureLossPct' not in out2
          and 'organicLossPct' not in out2, out2)
    meta3 = {'ChargeWeightG': 200.0, 'WeightOutG': 184.0,
             'MoisturePct': 10.0, 'RoastedMoisturePct': 7.0}
    out3 = fn(meta3)
    check('HUNT-73 ordinary organic loss still reads 5.0',
          out3.get('organicLossPct') == 5.0
          and out3.get('moistureLossPct') == 3.0, out3)
    wl = ns['_weight_loss']
    check('HUNT-74 weight loss guard reads 0 over green weight',
          wl(200.0, 250.0) == 0.0, wl(200.0, 250.0))
    check('HUNT-74 weight loss still reads 8.0 for 200/184',
          wl(200.0, 184.0) == 8.0, wl(200.0, 184.0))


def static_cool_share():
    """HUNT-72: _phase_analysis on the real seeded batch
    1042 document and series from the database. The three
    phase shares must be 26/37/37 and the Cool row share
    must read '--' (it used to read 5%, so the column
    summed to 105)."""
    core_ns = extract_fns(CORE, ['shares_100'])

    class CoreStub(object):
        shares_100 = staticmethod(core_ns['shares_100'])

        @staticmethod
        def compute_ror_series(points, params, offline=False):
            return [(t, None) for t, _v in points]

        @staticmethod
        def ror_params():
            return {}

    ns = extract_fns(BATCHES, ['_phase_analysis', '_auc_range',
                                '_interp_pairs', '_mmss'],
                     extra={'core': CoreStub})
    doc = json.loads(P.psql(
        'SELECT data FROM batches WHERE batch_number = 1042'))
    rows_txt = P.psql(
        'SELECT t_offset_sec, bean_temp_f FROM batch_series '
        'WHERE batch_number = 1042 ORDER BY t_offset_sec')
    points = []
    for line in rows_txt.splitlines():
        if not line.strip():
            continue
        t, bt = line.split('|')
        points.append((float(t), float(bt)))
    rows, _tp, _extra = ns['_phase_analysis'](doc, points)
    print('HUNT-72 analysis rows:', rows, flush=True)
    by_name = dict((r[0], r) for r in rows)
    check('HUNT-72 table shows Drying, Maillard, Development',
          all(k in by_name for k in
              ('Drying', 'Maillard', 'Development')), rows)
    shares = [int(by_name[k][2].rstrip('%'))
              for k in ('Drying', 'Maillard', 'Development')]
    check('HUNT-72 phase shares sum to 100 as 26/37/37',
          shares == [26, 37, 37] and sum(shares) == 100, shares)
    check('HUNT-72 Cool row share reads --, not 5%',
          'Cool' in by_name and by_name['Cool'][2] == '--',
          by_name.get('Cool'))


def static_edit_recompute():
    """HUNT-75: _recompute_loss runs the guarded math on a
    document, and both submit paths call it."""
    ns = extract_fns(BATCHES, ['_recompute_loss',
                                'loss_yield_density',
                                '_weight_loss', '_volume_increase'])
    fn = ns['_recompute_loss']
    doc = {'metadata': {'ChargeWeightG': 200.0,
                        'WeightOutG': 184.0, 'MoisturePct': 12.0,
                        'RoastedMoisturePct': 2.0}}
    fn(doc)
    check('HUNT-75 recompute stores weight loss 8.0',
          doc.get('weightLossPct') == 8.0, doc)
    check('HUNT-75 recompute stores organic loss 0.0',
          (doc.get('loss') or {}).get('organicLossPct') == 0.0,
          doc.get('loss'))
    doc['metadata']['WeightOutG'] = 250.0
    fn(doc)
    check('HUNT-75 recompute over green weight reads 0.0',
          doc.get('weightLossPct') == 0.0, doc)
    check('HUNT-75 recompute drops the loss weight key',
          'weightLossPct' not in (doc.get('loss') or {}),
          doc.get('loss'))
    src = open(BATCHES).read()
    check('HUNT-75 _update_submit calls _recompute_loss',
          '_recompute_loss(doc)' in src.split(
              'def _update_submit')[1].split('def _create_submit')[0],
          '')
    check('HUNT-75 _create_submit calls _recompute_loss',
          '_recompute_loss(doc)' in src.split(
              'def _create_submit')[1].split(
                  'def select_row')[0], '')


def calculator_gaps(pg):
    """Round 10 candidate 1 (worker A owns the fix): record
    the Yield and Conversion Calculator readout to input
    adjacency without failing on it. Round 9 measured the
    TEMP (F) input ending at x 1002 with the TEMP (C)
    readout starting at x 1002 (0px gap)."""
    pg4 = pg
    m = pg4.evaluate("""() => {
      const labels = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          /TEMP/i.test(e.textContent || ''));
      return labels.slice(0, 8).map(e => {
        const r = e.getBoundingClientRect();
        return e.textContent.trim().slice(0, 20) + ' @' +
          Math.round(r.left) + '-' + Math.round(r.right);
      });
    }""")
    print('calculator labels (informational):', m, flush=True)
    check('calculator labels measured', len(m) > 0, m)


def align_label_gap(pw):
    """Round 8 candidate 8, informational only (worker A
    owns the compare row): measure the ALIGN ON label gap
    above the C picker on the desktop Log page."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    gap = pg.evaluate("""() => {
      const labels = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          e.textContent.trim().toLowerCase() === 'align on');
      if (!labels.length) return {found: false};
      const lab = labels[0].getBoundingClientRect();
      const dds = [...document.querySelectorAll(
        '[data-component="ia.input.dropdown"]')];
      if (dds.length < 3) return {found: true, dds: dds.length};
      const pick = dds[2].getBoundingClientRect();
      return {found: true, labelTop: lab.top,
              labelBottom: lab.bottom,
              pickerTop: pick.top, pickerBottom: pick.bottom,
              pickerRight: pick.right, labelLeft: lab.left,
              horizGap: lab.left - pick.right,
              vertOverlap: pick.top - lab.bottom,
              labelH: lab.height};
    }""")
    print('ALIGN ON gap (informational):', gap, flush=True)
    check('align label measured', gap.get('found') is True, gap)
    R5.shot(pg, 'r10-align-gap-1360-light.png')
    b.close()


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
    R5.shot(pg, 'r10-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r10-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r10-fresh-detail-%s.png' % tag)
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
    if P.tag('[default]Roastery/SelectedBatchNumber') != 1042:
        print('detail stage stolen mid-walk, retaking', tag,
              flush=True)
        R5.stage_one(1042)
        pg3 = R5.open_page(ctx, '/log/detail')
        pg3.wait_for_timeout(2500)
        measure(pg3, 'detail %s retry' % tag)
        R5.shot(pg3, 'r10-fresh-detail-%s.png' % tag)
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r10-fresh-settings-%s.png' % tag)
    if tag == '1360-light':
        calculator_gaps(pg4)
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
        R5.shot(pg, 'r10-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def doc_of(number):
    return json.loads(P.psql(
        'SELECT data FROM batches WHERE batch_number = %d'
        % number))


def live_roast_360_dark(pw):
    """Full roast at 360px dark, ghost mid-roast, stats line
    and DTR checked after Drop. The save carries crafted
    weights and moistures so the saved document proves
    HUNT-73 live (organic loss 0.0, not -2.0). A temporary
    Banner alarm def proves HUNT-76 live: it fires
    mid-roast and must read clear after Finish."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    orig_alarms = P.tag(B + '/AlarmDefsJson')
    temp_alarms = json.dumps([{
        'name': 'R10 probe', 'enabled': True, 'guard': 'None',
        'offsetSec': 0, 'source': 'BT', 'cond': '>=',
        'value': 210, 'message': 'R10 probe alarm',
        'action': 'Banner'}])
    try:
        set_theme_ui(pg, 'Dark')
        NEXT_BATCH[0] = int(P.psql(
            'SELECT MAX(batch_number) FROM batches')) + 1
        nxt = NEXT_BATCH[0]
        click_btn(pg, 'New Roast')
        check('new roast takes next batch number',
              P.wait_until(
                  lambda: P.tag(B + '/BatchNumber') == nxt, 30),
              P.tag(B + '/BatchNumber'))
        P.write_tags([(B + '/AlarmDefsJson', temp_alarms)])
        click_btn(pg, 'Charge')
        check('charge starts the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Roasting', 30))
        check('HUNT-76 banner alarm fires mid-roast',
              P.wait_until(
                  lambda: P.tag(B + '/AlarmActive') is True, 60),
              repr(P.tag(B + '/AlarmText')))
        pg.wait_for_timeout(8000)
        measure(pg, 'roast live 360-dark')
        R5.shot(pg, 'r10-fresh-roast-live-360-dark.png')
        click_btn(pg, 'Dry End')
        check('dry end stamps', P.wait_until(
            lambda: (P.tag(B + '/DryEndElapsedSec') or -1) >= 0,
            30))
        pg.wait_for_timeout(3000)
        measure(pg, 'roast dry-end 360-dark')
        click_btn(pg, 'FC Start')
        check('fc start stamps', P.wait_until(
            lambda: (P.tag(B + '/FirstCrackStartElapsedSec')
                     or -1) >= 0, 30))
        pg.wait_for_timeout(3000)
        P.write_tags([
            (BG_LABEL, 'Ethiopia Guji (test)'),
            (BG_CURVE, '[[0, 200], [60, 250], [120, 300], '
             '[180, 350], [240, 380]]')])
        pg.wait_for_timeout(3000)
        body = pg.locator('body').inner_text()
        check('background label shows mid-roast dark',
              'Ethiopia Guji (test)' in body, body[:120])
        measure(pg, 'roast ghost live 360-dark')
        R5.shot(pg, 'r10-fresh-roast-ghost-live-360-dark.png')
        P.write_tags([(BG_LABEL, ''), (BG_CURVE, '')])
        click_btn(pg, 'Drop')
        check('drop ends the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Dropped', 30))
        pg.wait_for_timeout(4000)
        body = pg.locator('body').inner_text()
        m = re.search(
            r'Dry\s+(\S+)\s+(\d+)%.*?Mai\w*\s+(\S+)\s+(\d+)%.*?'
            r'Dev\s+(\S+)\s+(\d+)%.*?DTR\s+(\d+)%', body,
            re.S)
        print('stats line after drop:', m.groups() if m else
              body[:400], flush=True)
        if m:
            shares = [int(m.group(2)), int(m.group(4)),
                      int(m.group(6))]
            check('stats phase shares sum to 100',
                  sum(shares) == 100, shares)
            dry = P.tag(B + '/DryEndElapsedSec')
            fc = P.tag(B + '/FirstCrackStartElapsedSec')
            drop = P.tag(B + '/DropElapsedSec')
            want_dtr = round((drop - fc) * 100.0 / drop)
            check('stats DTR equals (drop-FCs)/drop',
                  int(m.group(7)) == want_dtr,
                  'shown %s want %s (dry %s fc %s drop %s)'
                  % (m.group(7), want_dtr, dry, fc, drop))
        else:
            check('stats line parses after drop', False,
                  body[:200])
        measure(pg, 'roast dropped 360-dark')
        R5.shot(pg, 'r10-fresh-roast-dropped-360-dark.png')
        P.write_tags([(B + '/WeightOutG', 184.0),
                      (B + '/MoisturePct', 12.0),
                      (B + '/RoastedMoisturePct', 2.0)])
        click_btn(pg, 'Finish')
        check('finish reaches Complete', P.wait_until(
            lambda: P.tag(B + '/State') == 'Complete', 30))
        check('HUNT-76 banner alarm clears after Finish',
              P.wait_until(
                  lambda: P.tag(B + '/AlarmActive') is False, 30),
              repr(P.tag(B + '/AlarmText')))
        check('HUNT-76 alarm text empty after Finish',
              P.tag(B + '/AlarmText') == '',
              repr(P.tag(B + '/AlarmText')))
        click_btn(pg, 'Save Batch')
        check('roast saves as next batch number', P.wait_until(
            lambda: P.psql('SELECT COUNT(*) FROM batches '
                           'WHERE batch_number = %d' % nxt) == '1',
            30))
        doc = doc_of(nxt)
        print('saved doc loss:', doc.get('weightLossPct'),
              doc.get('loss'), flush=True)
        check('HUNT-73 saved weight loss reads 8.0',
              doc.get('weightLossPct') == 8.0,
              doc.get('weightLossPct'))
        check('HUNT-73 saved organic loss reads 0.0, not -2.0',
              (doc.get('loss') or {}).get('organicLossPct') == 0.0,
              doc.get('loss'))
        check('HUNT-73 saved moisture loss reads 10.0',
              (doc.get('loss') or {}).get('moistureLossPct')
              == 10.0, doc.get('loss'))
        click_btn(pg, 'Reset')
        check('reset returns to Idle', P.wait_until(
            lambda: P.tag(B + '/State') == 'Idle', 30))
    finally:
        P.write_tags([(B + '/AlarmDefsJson', orig_alarms)])
        b.close()
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('live roast leaves no press rows',
          P.psql('SELECT COUNT(*) FROM batch_events') == '0')


def detail_and_edit(pw):
    """Saved roast detail at 360px light, then edit the
    weights through the slide over editor (HUNT-74 and
    HUNT-75 live proof), then delete through the Log UI."""
    nxt = NEXT_BATCH[0]
    label = format(nxt, ',')
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    R5.stage_one(nxt)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(2500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    measure(pg, 'detail %d 360-light' % nxt)
    R5.shot(pg, 'r10-fresh-detail-%d-360-light.png' % nxt)
    body = pg.locator('body').inner_text()
    low = body.lower()
    for token in ('phase analysis', 'turning point', 'auc',
                  'dtr'):
        check('detail shows %s' % token, token in low,
              body[:150])
    check('detail Weight Loss tile reads 8.0%',
          '8.0%' in body, body[:400])
    check('detail shows no negative organic loss',
          '-2.0%' not in body, body[:400])
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    pg2.locator('text=%s' % label).first.click(timeout=25000)
    pg2.wait_for_timeout(1200)
    pg2.get_by_role('button', name='Edit').first.click(
        timeout=25000)
    pg2.wait_for_timeout(3500)
    form = pg2.locator('[data-component="ia.input.form"]')
    check('editor form opens', form.count() >= 1,
          form.count())
    fields = form.locator('input.ia_form__field, '
                          'textarea.ia_form__field')
    print('editor field count:', fields.count(), flush=True)
    check('editor WeightOutG prefill reads 184',
          fields.nth(16).input_value() in ('184', '184.0',
                                            '184.00'),
          fields.nth(16).input_value())
    fields.nth(16).fill('250')
    fields.nth(16).press('Tab')
    pg2.wait_for_timeout(600)
    pg2.get_by_role('button', name='Save Batch').first.click(
        timeout=25000)
    pg2.wait_for_timeout(2500)
    check('edit saved note',
          pg2.get_by_text('Saved batch %d.' % nxt).count() >= 1)
    doc = doc_of(nxt)
    print('edited doc loss:', doc.get('weightLossPct'),
          doc.get('loss'), flush=True)
    check('HUNT-75 edit recomputes weight loss (was 8.0)',
          doc.get('weightLossPct') == 0.0,
          doc.get('weightLossPct'))
    check('HUNT-74 edited loss reads 0.0, not -25.0',
          doc.get('weightLossPct') == 0.0,
          doc.get('weightLossPct'))
    check('HUNT-75 edit recomputes the loss block',
          'weightLossPct' not in (doc.get('loss') or {})
          and (doc.get('loss') or {}).get('moistureLossPct')
          == 10.0, doc.get('loss'))
    check('edited doc shows no negative loss anywhere',
          '-25.0%' not in json.dumps(doc), '')
    dock = pg2.locator('.docked-view-right')
    dock.get_by_role('button', name='Close').first.click(
        timeout=25000)
    # The dock container itself stays in the DOM when closed
    # (empty, off screen), so the close is proven by the
    # editor content leaving it, not by the container count.
    check('editor dock closes via its Close button',
          P.wait_until(
              lambda: dock.first.inner_text().strip() == '', 15),
          repr(dock.first.inner_text()[:80]))
    pg2.goto(P.BASE + '/log', wait_until='networkidle',
             timeout=60000)
    pg2.wait_for_timeout(1500)
    pg2.locator('text=%s' % label).first.click(timeout=25000)
    pg2.wait_for_timeout(1200)
    pg2.get_by_role('button', name='Delete').first.click(
        timeout=25000)
    pg2.wait_for_timeout(1000)
    pg2.get_by_role('button',
                    name='Confirm Delete').first.click(
                        timeout=25000)
    pg2.wait_for_timeout(2500)
    check('saved roast deletes through the Log UI',
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = %d' % nxt) == '0')
    b.close()


def compare_three(pw):
    """Compare A/B/C at 360px dark."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    dds = pg.locator('[data-component="ia.input.dropdown"]')
    dds.nth(2).click(timeout=20000)
    pg.wait_for_timeout(900)
    pg.locator('a.iaDropdownCommon_option',
               has_text='Batch 1046').first.click(timeout=20000)
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = caption_texts(pg)
    check('compare caption names A, B and C at 360 dark',
          any('A = Batch' in c and 'B = Batch' in c
              and 'C = Batch' in c for c in caps), caps)
    measure(pg, 'compare ABC 360-dark')
    R5.shot(pg, 'r10-fresh-compare-abc-360-dark.png')
    pg.get_by_role('button', name='All columns').first.click(
        timeout=10000)
    pg.wait_for_timeout(1500)
    measure(pg, 'log all-columns 360-dark')
    R5.shot(pg, 'r10-fresh-log-allcols-360-dark.png')
    b.close()


def phase_table_1042(pw):
    """HUNT-65 regression plus HUNT-72: seeded batch 1042
    Phase Analysis table must show Drying, Maillard and
    Development rows, and the Cool row share must read '--'
    so the Share column sums to 100, not 105."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    R5.stage_one(1042)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(6000)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1500)
    tbl = pg.evaluate("""() => {
      const tabs = [...document.querySelectorAll(
        '[data-component="ia.display.table"]')];
      const t = tabs.find(e =>
        (e.textContent || '').includes('Phase'));
      return t ? t.textContent : '';
    }""")
    print('HUNT-72 analysis table:', tbl[:200], flush=True)
    for phase in ('Drying', 'Maillard', 'Development', 'Cool'):
        check('HUNT-65 table shows %s row' % phase,
              phase in tbl, tbl[:200])
    m = re.findall(r'(\d\d)%', tbl)
    shares = [int(x) for x in m[:3]]
    check('HUNT-65 phase shares sum to 100',
          len(shares) == 3 and sum(shares) == 100, shares)
    check('HUNT-72 Cool row share reads -- in the live table',
          'Cool' in tbl and '--' in tbl.split('Cool')[1][:40],
          tbl[:200])
    R5.shot(pg, 'r10-fresh-detail-1042-analysis-1360-light.png')
    b.close()


def restore_defaults_via_ui(pw):
    """Restore ThemeMode System through the App Settings UI
    flow, the same way the suite set it."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, 'System')
    b.close()


def main():
    static_auc()
    static_shares()
    static_loss()
    static_cool_share()
    static_edit_recompute()
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
            align_label_gap(pw)
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            live_roast_360_dark(pw)
            detail_and_edit(pw)
            compare_three(pw)
            phase_table_1042(pw)
    finally:
        try:
            # BatchNumber is only restored when the workspace
            # is Idle: writing it mid-roast would retangle the
            # running batch number (probe lesson, round 10).
            pairs = [
                (B + '/FanLevel', 5),
                (B + '/HeatLevel', 5),
                (B + '/ActiveSource', 'Simulated'),
                (B + '/Mode', 'Off'),
                (B + '/DispAxisFormat', 'm:ss'),
                (B + '/CompareAlignEvent', 'charge'),
                (B + '/PressCaptureMode', 'Group'),
                (B + '/PhaseFromBg', False),
                (B + '/MoisturePct', 10.5),
                (B + '/RoastedMoisturePct', 0.0),
                ('[default]Roastery/AppSettings/PeriscopeAvailable',
                 True),
                (BG_LABEL, ''),
                (BG_CURVE, ''),
            ]
            if P.tag(B + '/State') == 'Idle':
                pairs.append((B + '/BatchNumber', 1042))
            P.write_tags(pairs)
            P.drain_pending()
            P.psql('DELETE FROM batch_events')
            if NEXT_BATCH[0]:
                P.psql('DELETE FROM batches WHERE '
                       'batch_number = %d' % NEXT_BATCH[0])
        except Exception as e:
            print('emergency cleanup failed:', str(e)[:150],
                  flush=True)
    try:
        with sync_playwright() as pw:
            restore_defaults_via_ui(pw)
    except Exception as e:
        print('theme restore via UI failed:', str(e)[:150],
              flush=True)
    check('lab back to Idle', P.tag(B + '/State') == 'Idle')
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('lab clean', P.psql('SELECT COUNT(*) FROM batches')
          == BASE['batches'] and P.psql(
              'SELECT COUNT(*) FROM batch_series')
          == BASE['series'] and P.psql(
              'SELECT COUNT(*) FROM batch_events') == '0',
          'batches=%s series=%s (baseline %s)'
          % (P.psql('SELECT COUNT(*) FROM batches'),
             P.psql('SELECT COUNT(*) FROM batch_series'), BASE))
    check('theme restored', P.tag(TM) == 'System')
    check('batch number restored',
          P.tag(B + '/BatchNumber') == 1042)
    check('moisture tags restored',
          P.tag(B + '/MoisturePct') == 10.5
          and P.tag(B + '/RoastedMoisturePct') == 0.0)
    print()
    print('PASSES:', PASSES[0])
    print('FAILURES:', FAILS if FAILS else 'none')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
