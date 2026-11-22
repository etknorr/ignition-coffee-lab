#!/usr/bin/env python3
"""Round 11 fresh hunting pass (worker D).

Fresh hunt continuing from HUNT-77. New defects this round:
  1. HUNT-78: the Artisan import path computed the batch weight
     loss with raw arithmetic ((green - roasted) / green), so
     an .alog whose roasted weight exceeds the green weight
     (250 g out on a 200 g charge) imported with
     weightLossPct -25.0. Artisan weight_loss returns 0 in
     exactly that case, and batches._weight_loss is that
     function (the HUNT-74 fix in build_document); the import
     path used the raw form, so the imported batch showed a
     negative Weight Loss tile while its Loss section
     (loss_yield_density, guarded) showed none. Proven
     statically and live through the Log page upload of a
     crafted .alog (sample fixture with the out weight raised
     to 250 g and a fresh roastUUID).
  2. HUNT-79: the .alog export computed block
     (artisan._computed_for) wrote Artisan's keys with the
     wrong math. weight_loss did the raw arithmetic, so it
     went negative when the roasted weight exceeded the green
     weight; total_yield was a percent (wout * 100 / win)
     where Artisan writes grams (weight out minus defects,
     computedProfileInformation, main.py:16889); total_loss
     just copied weight_loss, ignoring the defects loss
     Artisan adds in; and AUC was integrated in F-min where
     Artisan's AUC is always in C-min (calcAUC converts the
     temps to C first, ts() is documented "always in C", and
     the comparator reads this cached value and labels it
     C*min). All four now use the guarded Artisan shapes.
     Proven statically through _computed_for and live on the
     exported batch 1042 .alog (total_yield 172.0, not 86.0;
     AUC in C-min).
  3. HUNT-80: the slide over editor's create path never
     applied the event fields the form invites the user to
     type, so a manually created batch with typed event times
     saved with no events, no total time, no phases and
     drop_temp_f 0.0. The update path applies them through
     _apply_events; create does the same now, and the insert
     carries the edited drop temp. Proven statically and live
     through the Log New Batch flow.
  4. HUNT-81: the turning point scan in the export computed
     block needed a Dry End stamp (it scanned charge to the
     dry index), so a batch with a real dip but no Dry End
     event exported no TP at all and its AUC started at
     charge. Artisan findTPint needs no Dry End: it scans
     charge to DROP, capped at FC Start when one is stamped.
     The export mirrors that now. Found when the suite's
     export proof hit a missing TP_idx on batch 1042; for
     1042 itself the TP sits at the first sample, so the old
     code and the new code agree there. Proven statically on
     a dipping curve with no Dry End stamped.
  5. HUNT-82: the BatchDetail calculator's Loss from out
     readout showed -25.0% for an over-green batch: the
     Calculator/ActualLossPct expression tag did the raw
     loss arithmetic. The tag expression now clamps at 0,
     matching _weight_loss, and the setup script that
     defines the tag carries the same fix. Proven live by
     writing the calculator inputs and by the detail page
     of the imported over-green batch.
  6. The four-page walk (Roast, Log, BatchDetail staged 1042,
     Settings) at 1360px and 360px, light and dark, measuring
     horizontal overflow and clipped leaf text (Perspective
     footer excluded), plus the Settings scroll sweep at 360px
     dark, as the regression net for the round.

ThemeMode is set only through the App Settings UI flow
(gear, theme button, Close) in this suite, never through
the API, and restored to System the same way at the end.
Does NOT retest the timezone TIME axis passthrough or
HUNT-46 (both beta-gated) and does NOT touch the press
path (HUNT-53 app fix out of scope) or the HUNT-58 r4hunt
chain or the builder files (other workers own them).
Leaves the lab clean.
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

B = '[default]Roastery/CurrentBatch'
CALC = '[default]Roastery/Calculator'
TM = '[default]Roastery/AppSettings/ThemeMode'
BG_LABEL = '[default]Roastery/BackgroundLabel'
BG_CURVE = '[default]Roastery/BackgroundCurveJson'
BATCHES = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'batches/code.py')
ARTISAN = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'artisan/code.py')
FIXTURE = ('/home/hatch/workspace/ignition-lab/artisan-fixtures/'
           'sample-roast.alog')
OVERGREEN_ALOG = '/tmp/r11-import-overgreen.alog'
EXPORT_ALOG = '/tmp/r11-export-1042.alog'
NEXT_BATCH = [0]
IMPORTED_BATCH = [0]
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

def static_weight_loss_guard():
    """HUNT-78: the guarded _weight_loss the import path now
    uses, plus the source shape of the fix."""
    ns = extract_fns(BATCHES, ['_weight_loss'])
    wl = ns['_weight_loss']
    check('HUNT-78 guarded loss reads 0 over green weight',
          wl(200.0, 250.0) == 0.0, wl(200.0, 250.0))
    check('HUNT-78 guarded loss still reads 8.0 for 200/184',
          wl(200.0, 184.0) == 8.0, wl(200.0, 184.0))
    check('HUNT-78 guarded loss reads 14.3 for 200/171.4',
          abs(wl(200.0, 171.4) - 14.3) < 0.01, wl(200.0, 171.4))
    src = open(ARTISAN).read()
    check('HUNT-78 import uses _weight_loss, not raw arithmetic',
          'batches._weight_loss(charge_w, out_w)' in src
          and '((charge_w - out_w) * 100.0 / charge_w)' not in src,
          '')
    check('HUNT-78 import keeps the no roasted weight guard',
          'if out_w > 0 and charge_w > 0 else 0.0' in src, '')


def static_computed_for():
    """HUNT-79: _computed_for on crafted inputs, run from the
    real library source with a stub batches module carrying
    the real _weight_loss."""
    bns = extract_fns(BATCHES, ['_weight_loss'])

    class BatchesStub(object):
        _weight_loss = staticmethod(bns['_weight_loss'])

    ns = extract_fns(ARTISAN, ['_computed_for', '_num', '_proper'],
                     extra={'batches': BatchesStub})
    fn = ns['_computed_for']
    timex = [float(t) for t in range(0, 601, 60)]
    temp2 = [300.0] * len(timex)
    temp1 = [-1.0] * len(timex)
    ti = [0, 1, 2, 3, 4, 5, 10, 10]

    def run(win, wout, defects, mode='F', temps=None):
        doc = {'metadata': {'ChargeWeightG': win,
                            'WeightOutG': wout,
                            'DefectsWeightG': defects}}
        return fn({}, timex, temp1,
                  temps if temps is not None else temp2,
                  ti, mode, doc)

    c = run(200.0, 250.0, 10.0)
    print('HUNT-79 over green computed:', c, flush=True)
    check('HUNT-79 over green weight_loss is absent, not -25.0',
          'weight_loss' not in c, c)
    check('HUNT-79 over green defects loss reads 4.0',
          c.get('roast_defects_loss') == 4.0, c)
    check('HUNT-79 over green total_yield is 240.0 g, not a pct',
          c.get('total_yield') == 240.0, c)
    check('HUNT-79 over green total_loss is absent, not -25.0',
          'total_loss' not in c, c)
    check('HUNT-79 F-mode AUC converts to C-min (489, not 880)',
          c.get('AUC') == 489, c.get('AUC'))
    check('HUNT-79 AUC base stays 212.0 in F mode',
          c.get('AUCbase') == 212.0, c.get('AUCbase'))
    c2 = run(200.0, 184.0, 10.0)
    print('HUNT-79 defects computed:', c2, flush=True)
    check('HUNT-79 weight_loss reads 8.0 for 200/184',
          c2.get('weight_loss') == 8.0, c2)
    check('HUNT-79 defects loss reads 5.4 for 184/174',
          c2.get('roast_defects_loss') == 5.4, c2)
    check('HUNT-79 total_yield reads 174.0 g for 184-10',
          c2.get('total_yield') == 174.0, c2)
    check('HUNT-79 total_loss reads 13.0, not 8.0',
          c2.get('total_loss') == 13.0, c2)
    c3 = run(200.0, 172.0, 0.0)
    check('HUNT-79 no defects loss key when defects are 0',
          'roast_defects_loss' not in c3, c3)
    check('HUNT-79 total_yield reads 172.0 g for 200/172',
          c3.get('total_yield') == 172.0, c3)
    check('HUNT-79 total_loss reads 14.0 for 200/172',
          c3.get('total_loss') == 14.0, c3)
    c4 = run(200.0, 172.0, 0.0, mode='C',
             temps=[150.0] * len(timex))
    check('HUNT-79 C-mode AUC needs no conversion (500)',
          c4.get('AUC') == 500, c4.get('AUC'))
    check('HUNT-79 C-mode AUC base is 100.0',
          c4.get('AUCbase') == 100.0, c4.get('AUCbase'))

    # HUNT-81: the turning point in the export used to need a
    # Dry End stamp. A dipping curve with no Dry End (and no
    # FC Start) must still find its TP, Artisan findTPint
    # style, and the AUC must start there, not at charge.
    dip = [390.0, 340.0, 350.0, 365.0, 380.0, 390.0, 400.0,
           408.0, 412.0, 415.0, 415.0]
    doc5 = {'metadata': {'ChargeWeightG': 200.0,
                         'WeightOutG': 172.0,
                         'DefectsWeightG': 0.0}}
    ti_nodry = [0, 0, 0, 0, 0, 0, 10, 0]
    c5 = fn({}, timex, temp1, dip, ti_nodry, 'F', doc5)
    print('HUNT-81 no dry end computed TP:', c5.get('TP_idx'),
          c5.get('TP_time'), c5.get('TP_BT'), 'AUC:', c5.get('AUC'),
          flush=True)
    check('HUNT-81 TP found without a Dry End stamp (idx 1)',
          c5.get('TP_idx') == 1, c5.get('TP_idx'))
    check('HUNT-81 TP time reads 60.0 s',
          c5.get('TP_time') == 60.0, c5.get('TP_time'))
    check('HUNT-81 TP temp reads 340.0 F',
          c5.get('TP_BT') == 340.0, c5.get('TP_BT'))
    # AUC from the TP (segments 1..9 above 212 F, in C-min):
    # 133 + 145.5 + 160.5 + 173 + 183 + 192 + 198 + 201.5 + 203
    # = 1589.5 F-min, x5/9 = 883.06, int 883.
    check('HUNT-81 AUC starts at the TP (883 C-min, not 968)',
          c5.get('AUC') == 883, c5.get('AUC'))
    ti_dry = [0, 2, 0, 0, 0, 0, 10, 0]
    c6 = fn({}, timex, temp1, dip, ti_dry, 'F', doc5)
    check('HUNT-81 TP is the same dip with a Dry End stamped',
          c6.get('TP_idx') == 1 and c6.get('AUC') == 883,
          (c6.get('TP_idx'), c6.get('AUC')))


def static_calc_loss_guard():
    """HUNT-82: the Calculator ActualLossPct expression tag
    must clamp at 0, like _weight_loss does. The repo source
    of truth for the tag is setup_roastery_v4_tags.py."""
    src = open('/home/hatch/workspace/ignition-coffee-lab/'
               'roastery/scripts/setup_roastery_v4_tags.py').read()
    m = re.search(r"'ActualLossPct'.*?'expression':\s*'([^']+)'",
                  src, re.S)
    check('HUNT-82 setup script defines ActualLossPct',
          m is not None, '')
    expr = m.group(1) if m else ''
    print('HUNT-82 setup expression:', expr, flush=True)
    check('HUNT-82 ActualLossPct clamps at 0',
          'max(0,' in expr, expr)
    check('HUNT-82 raw unclamped loss form is gone',
          '({[.]ChargeG} - {[.]OutG}) * 100.0 / {[.]ChargeG}, 0)'
          not in expr, expr)


def calc_loss_live():
    """HUNT-82 live: the ActualLossPct expression tag reads
    0.0 when the out weight exceeds the charge weight, and
    still reads the plain percent for a normal loss. The
    calculator inputs are restored to their entry values."""
    from api27m import api
    st, out = api('GET', '/tags/export',
                  params={'provider': 'default', 'type': 'json',
                          'path': 'Roastery/Calculator',
                          'recursive': 'true'})
    check('HUNT-82 Calculator folder exports', st == 200, st)
    expr = None
    def find(node):
        if isinstance(node, dict):
            if node.get('name') == 'ActualLossPct':
                return node.get('expression')
            for v in node.values():
                r = find(v)
                if r is not None:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = find(v)
                if r is not None:
                    return r
        return None
    if st == 200:
        expr = find(out)
    check('HUNT-82 live ActualLossPct expression is clamped',
          expr is not None and 'max(0,' in expr, expr)
    charge0 = P.tag(CALC + '/ChargeG')
    out0 = P.tag(CALC + '/OutG')
    P.write_tags([(CALC + '/ChargeG', 200.0),
                  (CALC + '/OutG', 250.0)])
    time.sleep(2)
    check('HUNT-82 live loss reads 0.0 over green weight',
          P.tag(CALC + '/ActualLossPct') == 0.0,
          P.tag(CALC + '/ActualLossPct'))
    P.write_tags([(CALC + '/OutG', 184.0)])
    time.sleep(2)
    check('HUNT-82 live loss still reads 8.0 for 200/184',
          P.tag(CALC + '/ActualLossPct') == 8.0,
          P.tag(CALC + '/ActualLossPct'))
    P.write_tags([(CALC + '/ChargeG', charge0),
                  (CALC + '/OutG', out0)])
    time.sleep(1)


def static_create_events():
    """HUNT-80: _apply_events on a create-shape document."""
    ns = extract_fns(BATCHES, ['_apply_events', 'parse_mmss',
                                'roast_degree'])
    apply_events = ns['_apply_events']

    def create_doc():
        return {'batchNumber': 1099, 'beanName': '', 'roastDegree': '',
                'totalSec': 0, 'phases': {}, 'events': {},
                'metadata': {}, 'manualEntry': True}

    payload = {'Ev_dryEnd_t': '04:30', 'Ev_dryEnd_tempF': '300',
               'Ev_fcStart_t': '08:00', 'Ev_fcStart_tempF': '385',
               'Ev_drop_t': '10:00', 'Ev_drop_tempF': '415'}
    doc = create_doc()
    err = apply_events(doc, payload)
    print('HUNT-80 created doc events:', doc.get('events'),
          'phases:', doc.get('phases'), flush=True)
    check('HUNT-80 typed events apply with no error',
          err is None, err)
    evs = doc.get('events') or {}
    check('HUNT-80 dry end lands at 270 s, 300 F',
          (evs.get('dryEnd') or {}).get('t') == 270
          and (evs.get('dryEnd') or {}).get('tempF') == 300.0,
          evs.get('dryEnd'))
    check('HUNT-80 FC start lands at 480 s, 385 F',
          (evs.get('fcStart') or {}).get('t') == 480
          and (evs.get('fcStart') or {}).get('tempF') == 385.0,
          evs.get('fcStart'))
    check('HUNT-80 drop lands at 600 s, 415 F',
          (evs.get('drop') or {}).get('t') == 600
          and (evs.get('drop') or {}).get('tempF') == 415.0,
          evs.get('drop'))
    check('HUNT-80 total time recomputes to 600 s',
          doc.get('totalSec') == 600, doc.get('totalSec'))
    check('HUNT-80 phases recompute to 270/210/120, DTR 20.0',
          doc.get('phases') == {'dryingSec': 270,
                                'maillardSec': 210,
                                'developmentSec': 120,
                                'dtrPct': 20.0}, doc.get('phases'))
    check('HUNT-80 drop temp and degree follow the typed drop',
          doc.get('dropTempF') == 415.0
          and doc.get('roastDegree') == 'Full City',
          (doc.get('dropTempF'), doc.get('roastDegree')))
    doc2 = create_doc()
    err2 = apply_events(doc2, {'Ev_dryEnd_t': '08:00',
                               'Ev_fcStart_t': '04:30'})
    check('HUNT-80 out of order events are rejected',
          err2 is not None and 'must come before' in err2, err2)
    check('HUNT-80 rejected edit leaves the doc untouched',
          doc2.get('totalSec') == 0 and doc2.get('phases') == {},
          doc2)
    doc3 = create_doc()
    err3 = apply_events(doc3, {})
    check('HUNT-80 no events typed leaves the doc untouched',
          err3 is None and doc3.get('totalSec') == 0
          and doc3.get('phases') == {} and doc3.get('events') == {
              'charge': None, 'dryEnd': None, 'fcStart': None,
              'fcEnd': None, 'scStart': None, 'scEnd': None,
              'drop': None, 'custom': []}, doc3.get('events'))
    doc4 = create_doc()
    err4 = apply_events(doc4, {'Ev_drop_t': 'xx'})
    check('HUNT-80 garbage event time is rejected',
          err4 is not None and 'mm:ss' in err4, err4)
    src = open(BATCHES).read()
    check('HUNT-80 _create_submit calls _apply_events',
          '_apply_events(doc, event)' in src.split(
              'def _create_submit')[1].split(
                  'def select_row')[0], '')

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
    R5.shot(pg, 'r11-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r11-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r11-fresh-detail-%s.png' % tag)
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
    R5.shot(pg4, 'r11-fresh-settings-%s.png' % tag)
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
        R5.shot(pg, 'r11-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def doc_of(number):
    return json.loads(P.psql(
        'SELECT data FROM batches WHERE batch_number = %d'
        % number))


def delete_batch_ui(pg, number):
    """Delete one batch through the Log UI, as r10 does."""
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


def export_1042(pw):
    """HUNT-79 live: export batch 1042 as .alog and read the
    computed block back. The AUC expectation is computed
    independently from the exported arrays themselves (the
    export's own TP index to its drop index), so it does not
    depend on how the export rebuilds its timeindex."""
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
    print('HUNT-79 exported 1042 computed:', comp, flush=True)
    check('HUNT-79 export weight_loss reads 14.0 for 200/172',
          comp.get('weight_loss') == 14.0, comp)
    check('HUNT-79 export total_yield is 172.0 g, not 86.0',
          comp.get('total_yield') == 172.0, comp)
    check('HUNT-79 export total_loss reads 14.0',
          comp.get('total_loss') == 14.0, comp)
    check('HUNT-79 export carries no defects loss for 1042',
          'roast_defects_loss' not in comp, comp)
    timex = [float(v) for v in prof['timex']]
    temp2 = [float(v) for v in prof['temp2']]
    ti = prof['timeindex']
    # The export writes TP_idx when it finds a turning point;
    # without one the AUC starts at charge (the export's own
    # fallback), so the expectation follows the same rule.
    start = int(comp['TP_idx']) if 'TP_idx' in comp else int(ti[0])
    end = int(ti[6])
    f_min = 0.0
    for i in range(start, min(end, len(temp2) - 1)):
        dt = (timex[i + 1] - timex[i]) / 60.0
        if dt <= 0:
            continue
        avg = (temp2[i] + temp2[i + 1]) / 2.0 - 212.0
        if avg > 0:
            f_min += avg * dt
    want = int(round(f_min * 5.0 / 9.0))
    print('HUNT-79 exported AUC=%s F-min=%.2f C-min want=%s'
          % (comp.get('AUC'), f_min, want), flush=True)
    check('HUNT-79 export AUC is C-min, not F-min',
          comp.get('AUC') == want, (comp.get('AUC'), want))
    check('HUNT-79 export AUC base stays 212.0 in F mode',
          comp.get('AUCbase') == 212.0, comp.get('AUCbase'))
    b.close()


def field_index_by_label(pg, label):
    """Index of the form input whose nearest label text matches,
    so the create flow does not depend on a fixed field order.
    The create editor carries 51 fields with the event times at
    37-50, not the 61-field order the first probe saw, so label
    lookup is the robust route."""
    return pg.evaluate("""(label) => {
      const inputs = document.querySelectorAll(
        "[data-component='ia.input.form'] "
        + "input.ia_form__field, "
        + "[data-component='ia.input.form'] "
        + "textarea.ia_form__field");
      for (let i = 0; i < inputs.length; i++) {
        let node = inputs[i], text = '';
        for (let d = 0; d < 5 && node; d++) {
          node = node.parentElement;
          if (!node) break;
          text = (node.innerText || '').split('\\n')[0].trim();
          if (text) break;
        }
        if (text === label) return i;
      }
      return -1;
    }""", label)


def fill_labeled(pg, fields, label, value):
    idx = field_index_by_label(pg, label)
    check('create form has a %s field' % label, idx >= 0, idx)
    if idx >= 0:
        fields.nth(idx).fill(value)


def create_batch_live(pw):
    """HUNT-80 live: create a batch through the Log New Batch
    flow with typed event times, then read the stored
    document back."""
    nxt = int(P.psql('SELECT MAX(batch_number) FROM batches')) + 1
    NEXT_BATCH[0] = nxt
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='New Batch').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    form = pg.locator('[data-component="ia.input.form"]')
    check('HUNT-80 create editor form opens', form.count() >= 1,
          form.count())
    fields = form.locator('input.ia_form__field, '
                          'textarea.ia_form__field')
    # Fill by label, not by index: the create editor carries
    # 51 fields with the event times at 37-50, and the first
    # probe's 61-field order does not hold in create mode.
    fill_labeled(pg, fields, 'Batch number', str(nxt))
    fill_labeled(pg, fields, 'Bean name', 'R11 create test')
    fill_labeled(pg, fields, 'Dry End time (mm:ss)', '04:30')
    fill_labeled(pg, fields, 'Dry End temp (F)', '300')
    fill_labeled(pg, fields, 'FC Start time (mm:ss)', '08:00')
    fill_labeled(pg, fields, 'FC Start temp (F)', '385')
    fill_labeled(pg, fields, 'Drop time (mm:ss)', '10:00')
    fill_labeled(pg, fields, 'Drop temp (F)', '415')
    pg.get_by_role('button', name='Save Batch').first.click(
        timeout=25000)
    pg.wait_for_timeout(2500)
    check('HUNT-80 create saved note',
          pg.get_by_text('Created batch %d.' % nxt).count() >= 1)
    doc = doc_of(nxt)
    print('HUNT-80 created doc:', json.dumps(doc)[:600], flush=True)
    evs = doc.get('events') or {}
    check('HUNT-80 created doc carries the typed dry end',
          (evs.get('dryEnd') or {}).get('t') == 270
          and (evs.get('dryEnd') or {}).get('tempF') == 300.0,
          evs.get('dryEnd'))
    check('HUNT-80 created doc carries the typed FC start',
          (evs.get('fcStart') or {}).get('t') == 480
          and (evs.get('fcStart') or {}).get('tempF') == 385.0,
          evs.get('fcStart'))
    check('HUNT-80 created doc carries the typed drop',
          (evs.get('drop') or {}).get('t') == 600
          and (evs.get('drop') or {}).get('tempF') == 415.0,
          evs.get('drop'))
    check('HUNT-80 created doc total is 600 s',
          doc.get('totalSec') == 600, doc.get('totalSec'))
    check('HUNT-80 created doc phases are 270/210/120',
          doc.get('phases') == {'dryingSec': 270,
                                'maillardSec': 210,
                                'developmentSec': 120,
                                'dtrPct': 20.0}, doc.get('phases'))
    check('HUNT-80 created doc drop temp is 415, degree Full City',
          doc.get('dropTempF') == 415.0
          and doc.get('roastDegree') == 'Full City',
          (doc.get('dropTempF'), doc.get('roastDegree')))
    pg.goto(P.BASE + '/log', wait_until='networkidle',
            timeout=60000)
    pg.wait_for_timeout(2000)
    body = pg.locator('body').inner_text()
    check('HUNT-80 created batch shows in the Log table',
          'R11 create test' in body, body[:200])
    delete_batch_ui(pg, nxt)
    b.close()


def craft_overgreen_alog():
    """Sample fixture with the roasted weight raised over the
    green weight (250 g out on a 200 g charge) and a fresh
    roastUUID so the duplicate guard does not fire."""
    data = ast.literal_eval(open(FIXTURE).read())
    data['weight'] = [200.0, 250.0, 'g']
    data['roastUUID'] = uuid.uuid4().hex
    with open(OVERGREEN_ALOG, 'w') as f:
        f.write(repr(data) + '\n')
    return OVERGREEN_ALOG


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


def import_overgreen_live(pw):
    """HUNT-78 live: import the over-green .alog through the
    Log page upload and read the stored document back."""
    path = craft_overgreen_alog()
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
    check('HUNT-78 over-green .alog imports as a new batch',
          bool(ok), P.psql('SELECT COUNT(*) FROM batches'))
    nxt = int(P.psql('SELECT MAX(batch_number) FROM batches'))
    IMPORTED_BATCH[0] = nxt
    note = pg.locator('body').inner_text()
    check('HUNT-78 import note names the new batch',
          ('Imported' in note and str(nxt) in note), note[:200])
    doc = doc_of(nxt)
    print('HUNT-78 imported doc loss:', doc.get('weightLossPct'),
          doc.get('loss'), flush=True)
    check('HUNT-78 imported weight loss reads 0.0, not -25.0',
          doc.get('weightLossPct') == 0.0,
          doc.get('weightLossPct'))
    # The doc JSON holds one '-25' substring, and it is not a
    # loss: the Artisan timezone offset -25200 s (UTC-7) in
    # the artisan identity subdocument. A negative loss would
    # serialize as -25.0, so that is the value to exclude.
    check('HUNT-78 imported doc carries no -25.0 loss value',
          '-25.0' not in json.dumps(doc), '')
    tzo = ((doc.get('artisan') or {}).get('identity') or {}).get(
        'roasttzoffset')
    check('HUNT-78 the only -25 in the doc is the tz offset',
          tzo == -25200 and json.dumps(doc).count('-25') == 1,
          tzo)
    check('HUNT-78 imported loss block carries no weight loss',
          'weightLossPct' not in (doc.get('loss') or {}),
          doc.get('loss'))
    check('HUNT-78 imported weights read 200 in, 250 out',
          (doc.get('metadata') or {}).get('ChargeWeightG') == 200.0
          and (doc.get('metadata') or {}).get('WeightOutG')
          == 250.0, doc.get('metadata'))
    R5.stage_one(nxt)
    pg2 = R5.open_page(ctx, '/log/detail')
    pg2.wait_for_timeout(2500)
    body2 = pg2.locator('body').inner_text()
    # The page also renders the Artisan timezone offset
    # (-25200 s), so the check excludes the loss renderings
    # (-25.0 and -25%) rather than the bare substring.
    check('HUNT-78 detail page shows no -25 loss value',
          '-25.0' not in body2 and '-25%' not in body2,
          body2[:300])
    delete_batch_ui(pg, nxt)
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
    static_weight_loss_guard()
    static_computed_for()
    static_calc_loss_guard()
    static_create_events()
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
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            export_1042(pw)
            create_batch_live(pw)
            import_overgreen_live(pw)
            calc_loss_live()
    finally:
        try:
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
                # Calculator scratch inputs: reseed to the
                # staged batch 1042 weights (200 g in, 172 g
                # out), as calculator_seed would on staging.
                (CALC + '/ChargeG', 200.0),
                (CALC + '/OutG', 172.0),
            ]
            if P.tag(B + '/State') == 'Idle':
                pairs.append((B + '/BatchNumber', 1042))
            P.write_tags(pairs)
            P.drain_pending()
            P.psql('DELETE FROM batch_events')
            for n in (NEXT_BATCH[0], IMPORTED_BATCH[0]):
                if n:
                    P.psql('DELETE FROM batches WHERE '
                           'batch_number = %d' % n)
                    P.psql('DELETE FROM batch_series WHERE '
                           'batch_number = %d' % n)
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
