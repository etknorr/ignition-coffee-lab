#!/usr/bin/env python3
"""Roastery Tier 2 verification (Playwright + REST + psql).

Proves the Tier 2 items 7 to 10 live on the Maker gateway:
7. Phase analytics completion: the Phase Analysis table and
   the saved document carry TP based dry RoR and delta, per
   phase AUC, fcs_ror, total RoR and a cool phase line,
   recomputed independently here from the stored series.
8. Loss, yield and density: an import with known weights,
   volumes, defects and moistures stores the full Artisan
   set in the document and shows it on BatchDetail.
9. BT projection: the LiveCurveDS proj column extends the
   live curve forward at the current RoR (linear), follows
   the Settings toggle and mode, and is never stored.
10. Live deviation from the background (BgDeviationText and
    the tile, recomputed here from the ghost pairs) and the
    BT similarity score on BatchDetail (a batch against
    itself as ghost scores 0.0 RMSE).
11. Background playback prompts: a staged ghost with early
    Fan and Heat changes prompts each change and its Drop
    exactly once with the suggested level, and never writes
    FanLevel or HeatLevel or drops the roast itself.
12. Display smoothing: the LiveCurveDS bean column changes
    with the level (trailing lag on a rising curve) while
    CurveSamples, the RoR column and the saved batch_series
    stay byte identical to smoothing off.
13. Analyzer crosshair readout on the live chart and on
    BatchDetail: BT, RoR, ghost BT and deviation at the
    selected time match an independent recompute.
14. Auto event suggestions: crossing the Settings phase
    target temps suggests Dry End and FC Start once each;
    no event is recorded before Eric presses the normal
    button, and the stamp clears the suggestion.

Screenshots land in showcase/shots/roastery-tier2-*.png.
Test batches are deleted at the end; the lab is left at
7 batches / 101 series rows, CurrentBatch clean Idle.
"""
import ast
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8088/data/perspective/client/Roastery'
SHOTS = '/home/hatch/workspace/ignition-lab/showcase/shots'
B = '[default]Roastery/CurrentBatch'
# Polish round 1 item 2: chart datasets anchor x values to
# roastery.core.AXIS_BASE_MS (a Denver local midnight), not the
# Unix epoch. Dataset reads below normalize by subtracting it.
AXIS_BASE_MS = 946710000000
FIXTURE = '/home/hatch/workspace/ignition-lab/artisan-fixtures/sample-roast.alog'
LOSS_ALOG = '/tmp/tier2-loss.alog'
PLAYBACK_ALOG = '/tmp/tier2-playback.alog'
DA = '[default]Roastery/DetailAnalyzer'
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:220]) if detail else '', flush=True)
    if not cond:
        FAILURES.append(label)


def read_tags(paths):
    st, out = api('GET', '/tags/read', body=json.dumps({'tags': paths}))
    assert st == 200, (st, out)
    return [r['value'] for r in out['results']]


def tag(path):
    return read_tags([path])[0]


def write_tags(pairs):
    st, out = api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': [p for p, _v in pairs],
         'values': [v for _p, v in pairs]}))
    assert st == 200, (st, out)


def wait_tag(path, want, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if tag(path) == want:
            return True
        time.sleep(0.7)
    return False


def wait_until(fn, timeout=60, step=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def psql(sql):
    env = dict(os.environ)
    env['PGPASSWORD'] = open(
        '/home/hatch/workspace/ignition-lab/.roastery-pgpass'
    ).read().strip()
    r = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', sql], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()



def drain_pending():
    """Polish round 3: press capture slots each press's
    context in a 16 slot ring (HUNT-22); the library
    reconcile inserts any press the group missed. Wait
    until every slotted press has its batch_events row, or
    a reconciled press would resurrect a row this suite
    just deleted."""
    def missing():
        paths = ['[default]Roastery/PressSlots/Slot%02d' % i
                 for i in range(16)]
        pairs = []
        for raw in read_tags(paths):
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except Exception:
                continue
            pairs.append((int(e['b']), int(e['c'])))
        if not pairs:
            return False
        cond = ' OR '.join(
            '(batch_number = %d AND press_counter = %d)' % p
            for p in pairs)
        found = int(psql(
            'SELECT COUNT(*) FROM batch_events WHERE ' + cond))
        return found < len(pairs)
    wait_until(lambda: not missing(), timeout=30)
    write_tags([('[default]Roastery/PressSlots/Slot%02d' % i, '')
                for i in range(16)])

def dismiss(page):
    if page.get_by_text('Personal Use Only').count() > 0:
        try:
            page.get_by_text('AGREE & CLOSE').first.click(timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(1500)


def overlays(page):
    return page.evaluate("""() => [...document.querySelectorAll(
      '.ia_qualityOverlay')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0; }).length""")


def overflow_worst(page):
    return page.evaluate("""() => {
      let w = 0;
      document.querySelectorAll('body *').forEach(el => {
        if (el.closest('.modal-body')) return;
        if (el.closest('[data-component="ia.display.table"]')) return;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.left < window.innerWidth - 1)
          w = Math.max(w, r.right);
      });
      return Math.round(w);
    }""")


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


def ds_rows(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return [], []
    if value is None:
        return [], []
    if isinstance(value, dict):
        cols = [c['name'] for c in value.get('columns') or []]
        return cols, value.get('rows') or []
    return [], []


def dock_drop(dock):
    """Phase aware dock (polish phase 2): Drop is offered only
    after FC End, so stamp the prerequisite events through the
    dock first, then Drop. Each click waits for the dock to
    re-render its next phase set."""
    for name in ('Dry End', 'FC Start', 'FC End'):
        btn = dock.get_by_role('button', name=name)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            time.sleep(1.5)
    dock.get_by_role('button', name='Drop').click()


def log_marker():
    shutil.copy('gateway-2027-maker/logs/system_logs.idb',
                '/tmp/logs_t2_start.idb')
    con = sqlite3.connect('/tmp/logs_t2_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    shutil.copy('gateway-2027-maker/logs/system_logs.idb',
                '/tmp/logs_t2_end.idb')
    con = sqlite3.connect('/tmp/logs_t2_end.idb')
    rows = con.execute(
        "SELECT level_string, logger_name, formatted_message FROM "
        "logging_event WHERE event_id > ? AND level_string IN "
        "('WARN', 'ERROR')", (start_id,)).fetchall()
    con.close()
    return [r for r in rows if 'roastery' in (r[1] or '').lower()
            or 'Roastery' in (r[2] or '')]


def make_loss_fixture():
    p = ast.literal_eval(open(FIXTURE).read())
    p.update({
        'roastUUID': 'tier2loss00000000000000000000001',
        'weight': [200.0, 170.0, 'g'],
        'volume': [250.0, 300.0, 'ml'],
        'defects_weight': 10.0,
        'moisture_greens': 10.8,
        'moisture_roasted': 1.8,
    })
    with open(LOSS_ALOG, 'w') as f:
        f.write(repr(p))


def make_playback_fixture():
    """The sample fixture with its slider events moved early:
    Fan falls to level 3 at 30 s, Heat to level 4 at 48 s, and
    DROP sits at 75 s, so a live roast meets all three prompts
    in about ninety seconds. Levels follow the import mapping
    (internal value v is pct (v - 1) * 10, level 1 + round(pct
    * 8 / 100)): Fan starts at 9 (v 11) then v 4 is 30 pct,
    level 3; Heat starts at 8 (v 10) then v 5 is 40 pct,
    level 4."""
    p = ast.literal_eval(open(FIXTURE).read())
    p.update({
        'roastUUID': 'tier2playback00000000000000000001',
        'specialevents': [9, 12, 15, 21],
        'specialeventstype': [0, 3, 0, 3],
        'specialeventsvalue': [11.0, 10.0, 4.0, 5.0],
    })
    ti = list(p['timeindex'])
    ti[6] = 30
    p['timeindex'] = ti
    with open(PLAYBACK_ALOG, 'w') as f:
        f.write(repr(p))


def curve_maps():
    """LiveCurveDS and CurveSamples as {elapsed_ms_or_sec:
    values} maps for the smoothing and analyzer checks."""
    cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
    live = {}
    if cols:
        for r in rows:
            live[int(r[0]) - AXIS_BASE_MS] = dict(
                (c, r[i]) for i, c in enumerate(cols))
    c2, r2 = ds_rows(tag('[default]Roastery/CurveSamples'))
    raw = {}
    if c2:
        ti = c2.index('t_offset_sec')
        bi = c2.index('bean_temp_f')
        for r in r2:
            raw[int(float(r[ti]))] = float(r[bi])
    return live, raw


def mmss(sec):
    sec = int(sec)
    return '%02d:%02d' % (sec // 60, sec % 60)


def series_of(number):
    out = psql("SELECT t_offset_sec, bean_temp_f, rate_of_rise_f "
               "FROM batch_series WHERE batch_number = %d "
               "ORDER BY t_offset_sec" % number)
    pts = []
    for line in out.splitlines():
        t, bt, ror = line.split('|')
        pts.append((float(t), float(bt),
                    float(ror) if ror else None))
    return pts


def interp(pts, t):
    if not pts or t < pts[0][0] or t > pts[-1][0]:
        return None
    for i in range(len(pts) - 1):
        if pts[i][0] <= t <= pts[i + 1][0]:
            t0, v0 = pts[i]
            t1, v1 = pts[i + 1]
            return v1 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def auc_range(pts, a, b, base):
    tot = 0.0
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t1 <= a or t0 >= b or t1 <= t0:
            continue
        lo, hi = max(t0, a), min(t1, b)
        va = v0 + (v1 - v0) * (lo - t0) / (t1 - t0)
        vb = v0 + (v1 - v0) * (hi - t0) / (t1 - t0)
        if (va + vb) / 2.0 > base:
            tot += ((va + vb) / 2.0 - base) * (hi - lo) / 60.0
    return tot


def approx(a, b, tol):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def select_batch_row(page, number):
    # Polish round 3 hardening (same pattern round 2 gave the
    # polish suites): the original read the selection tag back
    # after a fixed 1.2 s, but an aged beta session can take
    # far longer to apply the click, and two battery runs in a
    # row died on exactly that. Poll for the tag instead, and
    # reload once and retry before giving up. The assertion is
    # unchanged: the SelectedBatchNumber tag must end at the
    # requested batch.
    for attempt in range(2):
        # An aged session can also leave the table EMPTY (the
        # query result never applies to the view instance):
        # wait for rows before concluding anything.
        wait_until(lambda: page.locator('.ia_table__row').count()
                   > 0, timeout=20)
        rows = page.locator('.ia_table__row')
        clicked = False
        for i in range(rows.count()):
            tokens = rows.nth(i).inner_text().replace(
                ',', '').split()
            if str(number) in tokens:
                rows.nth(i).click()
                clicked = True
                break
        if clicked and wait_until(
                lambda: int(tag('[default]Roastery/'
                                'SelectedBatchNumber') or 0)
                == number, timeout=25):
            return True
        texts = [rows.nth(i).inner_text().replace('\n', ' | ')
                 [:90] for i in range(rows.count())]
        print('SUITE NOTE: select of %s failed (clicked %s);'
              ' table shows %d rows: %s'
              % (number, clicked, rows.count(), texts))
        if attempt == 0:
            print('SUITE NOTE: reloading once and retrying')
            page.reload(wait_until='networkidle')
            page.wait_for_timeout(4000)
    return int(tag('[default]Roastery/SelectedBatchNumber')
               or 0) == number


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    make_loss_fixture()
    base_batches = int(psql('SELECT COUNT(*) FROM batches'))
    base_series = int(psql('SELECT COUNT(*) FROM batch_series'))
    base_events = int(psql('SELECT COUNT(*) FROM batch_events'))
    check('starting point is the seeded log',
          (base_batches, base_series) == (7, 101),
          (base_batches, base_series))
    imported = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600, 'height': 900})
        mob = browser.new_page(viewport={'width': 360, 'height': 740})
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
            p.wait_for_timeout(8000)
            dismiss(p)
        check('no overlays at start',
              overlays(desk) == 0 and overlays(mob) == 0)

        # ---------- import the two fixtures ----------------------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        before = int(psql('SELECT COUNT(*) FROM batches'))
        upload(desk, FIXTURE)
        got = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches')) == before + 1,
            timeout=40)
        check('phase fixture imported', bool(got))
        phase_no = int(psql('SELECT MAX(batch_number) FROM batches'))
        imported.append(phase_no)
        upload(desk, LOSS_ALOG)
        got = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches')) == before + 2,
            timeout=40)
        check('loss fixture imported', bool(got))
        loss_no = int(psql('SELECT MAX(batch_number) FROM batches'))
        imported.append(loss_no)

        # ---------- item 7: phase analytics ----------------------
        doc = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = %d" % phase_no))
        pts3 = series_of(phase_no)
        pts = [(t, bt) for t, bt, _r in pts3]
        ev = doc['events']
        dry_t, fc_t, drop_t = ev['dryEnd']['t'], ev['fcStart']['t'], ev['drop']['t']
        tp = None
        for t, bt in pts:
            if t <= 0:
                continue
            if t >= dry_t:
                break
            if tp is None or bt < tp[1]:
                tp = (t, bt)
        pa = doc.get('phaseAnalysis') or {}
        ph = pa.get('phases') or {}
        check('document stores phase analysis for all three phases',
              all(k in ph for k in ('Drying', 'Maillard', 'Development')),
              list(ph.keys()))
        greens = float((doc.get('metadata') or {}).get('GreensTempF') or 0)
        if greens > 0:
            # Artisan RoR() first branch: the dry phase is
            # measured from the greens temperature over the
            # charge to dry end span.
            dry_ror = (ev['dryEnd']['tempF'] - greens) / (dry_t / 60.0)
            dry_delta = ev['dryEnd']['tempF'] - greens
            dry_label = 'dry phase RoR follows Artisan RoR() greens branch'
        else:
            dry_ror = (ev['dryEnd']['tempF'] - tp[1]) / ((dry_t - tp[0]) / 60.0)
            dry_delta = ev['dryEnd']['tempF'] - tp[1]
            dry_label = 'dry phase RoR is measured from the turning point'
        check(dry_label,
              approx(ph.get('Drying', {}).get('rorFMin'), dry_ror, 0.6),
              (ph.get('Drying', {}).get('rorFMin'), dry_ror))
        charge_ror = (ev['dryEnd']['tempF'] - ev['charge']['tempF']) / (dry_t / 60.0)
        check('dry phase RoR is not the old charge based value',
              not approx(ph.get('Drying', {}).get('rorFMin'), charge_ror, 0.6)
              or approx(dry_ror, charge_ror, 0.6),
              (ph.get('Drying', {}).get('rorFMin'), charge_ror))
        check('dry phase delta temp matches the same Artisan branch',
              approx(ph.get('Drying', {}).get('deltaF'), dry_delta, 0.6),
              (ph.get('Drying', {}).get('deltaF'), dry_delta))
        mai_ror = (ev['fcStart']['tempF'] - ev['dryEnd']['tempF']) / ((fc_t - dry_t) / 60.0)
        dev_ror = (ev['drop']['tempF'] - ev['fcStart']['tempF']) / ((drop_t - fc_t) / 60.0)
        check('maillard and development RoR and delta match Artisan RoR()',
              approx(ph.get('Maillard', {}).get('rorFMin'), mai_ror, 0.6)
              and approx(ph.get('Development', {}).get('rorFMin'), dev_ror, 0.6)
              and approx(ph.get('Maillard', {}).get('deltaF'),
                         ev['fcStart']['tempF'] - ev['dryEnd']['tempF'], 0.6))
        base = ev['charge']['tempF']
        aucs_ok = True
        for name, a, b in (('Drying', 0, dry_t), ('Maillard', dry_t, fc_t),
                           ('Development', fc_t, drop_t)):
            want = auc_range(pts, a, b, base)
            if not approx(ph.get(name, {}).get('aucFMin'), want, max(2.0, want * 0.05)):
                aucs_ok = False
        check('per phase AUC matches the trapezoid recompute', aucs_ok,
              dict((k, v.get('aucFMin')) for k, v in ph.items()))
        ror_at_fc = min(pts3, key=lambda r: abs(r[0] - fc_t))[2]
        check('fcs_ror matches the stored RoR at FC start',
              approx(pa.get('fcsRorFMin'), ror_at_fc, 1.5),
              (pa.get('fcsRorFMin'), ror_at_fc))
        total_ror = (ev['drop']['tempF'] - tp[1]) / ((drop_t - tp[0]) / 60.0)
        check('total RoR is TP to drop',
              approx(pa.get('totalRorFMin'), total_ror, 0.6),
              (pa.get('totalRorFMin'), total_ror))
        check('cool phase is drop to the Artisan COOL time (60 s)',
              approx(pa.get('coolSec'), 60, 1.5), pa.get('coolSec'))

        # ---------- item 8: loss, yield, density -----------------
        ldoc = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = %d" % loss_no))
        loss = ldoc.get('loss') or {}
        expect = {'weightLossPct': 15.0, 'defectsLossPct': 100.0 * 10 / 170,
                  'totalLossPct': 20.0, 'totalYieldG': 160.0,
                  'totalYieldPct': 80.0, 'volumeGainPct': 20.0,
                  'moistureLossPct': 9.0, 'organicLossPct': 6.0,
                  'greenDensityGL': 800.0,
                  'roastedDensityGL': 170 * 1000.0 / 300}
        missed = dict((k, (loss.get(k), v)) for k, v in expect.items()
                      if not approx(loss.get(k), v, 0.06))
        check('document stores the full loss, yield and density set',
              not missed, missed)
        check('weightLossPct stays consistent with the new math',
              approx(ldoc.get('weightLossPct'), 15.0, 0.06),
              ldoc.get('weightLossPct'))
        sparse = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = 1042"))
        check('a batch without volume or moisture inputs stores no '
              'fabricated density or moisture values',
              'greenDensityGL' not in (sparse.get('loss') or {})
              and 'moistureLossPct' not in (sparse.get('loss') or {}),
              sparse.get('loss'))

        # ---------- BatchDetail display: items 7, 8, 10b ---------
        desk.reload(wait_until='networkidle')
        desk.wait_for_timeout(4000)
        check('phase batch selected', select_batch_row(desk, phase_no))
        # stage the batch as its own ghost first: similarity
        # against itself must be 0.0 RMSE
        desk.get_by_role('button', name='Use as Ghost').first.click()
        desk.wait_for_timeout(3000)
        check('ghost staged from the phase batch',
              str(tag('[default]Roastery/BackgroundLabel') or '')
              .startswith('Batch %d' % phase_no),
              tag('[default]Roastery/BackgroundLabel'))
        check('background drop seconds staged for similarity',
              approx(tag('[default]Roastery/BackgroundDropSec'), drop_t, 0.1),
              tag('[default]Roastery/BackgroundDropSec'))
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        check('phase batch re-selected', select_batch_row(desk, phase_no))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('detail shows the cool phase line in the analysis table',
              'Cool' in body and '01:00' in body)
        check('detail shows fcs RoR, total RoR and similarity readouts',
              'RoR at FC start' in body and 'Total RoR (TP to drop)' in body
              and 'BT similarity vs ghost' in body)
        check('similarity of a batch against itself is 0.0 F RMSE',
              '0.0 F RMSE' in body)
        desk.screenshot(path=SHOTS + '/roastery-tier2-phase-analysis.png')
        mob.goto(BASE + '/log/detail', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        worst = overflow_worst(mob)
        check('detail has no overflow at 360px', worst <= 361, worst)
        mob.screenshot(path=SHOTS + '/roastery-tier2-phase-analysis-360.png')

        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        check('loss batch selected', select_batch_row(desk, loss_no))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('detail shows the loss, yield and density block',
              'Loss, Yield and Density' in body
              and 'Defects loss' in body and '5.9%' in body
              and 'Total yield' in body and '80.0%' in body
              and '800 g/L' in body and '567 g/L' in body
              and '20.0%' in body, body[-300:])
        desk.screenshot(path=SHOTS + '/roastery-tier2-loss-detail.png')

        # ---------- items 9 + 10a: the live roast ----------------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        expected = max(int(psql('SELECT MAX(batch_number) FROM batches')),
                       int(tag(B + '/BatchNumber'))) + 1
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        roast_no = int(tag(B + '/BatchNumber'))
        check('new roast workspace', roast_no == expected
              and tag(B + '/State') == 'Idle', roast_no)
        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('charge starts the roast', wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(20000)

        def proj_rows():
            cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
            if 'proj' not in cols:
                return None
            pi = cols.index('proj')
            bi = cols.index('bean')
            out = [(r[0], r[pi], r[bi]) for r in rows
                   if r[pi] is not None]
            return out

        proj = wait_until(proj_rows, timeout=90)
        check('live dataset carries a projection series', bool(proj),
              len(proj) if proj else 0)
        if proj:
            future = [r for r in proj if r[2] is None]
            anchor = proj[0]
            last = proj[-1]
            span_min = (last[0] - anchor[0]) / 60000.0
            slope = (last[1] - anchor[1]) / span_min if span_min else 0
            ror_now = float(tag(B + '/RateOfRiseF') or 0)
            check('projection extends about two minutes past the last sample',
                  len(future) >= 5 and 1.5 <= span_min <= 2.5,
                  (len(future), span_min))
            check('linear projection slope matches the live RoR',
                  approx(slope, ror_now, max(2.5, abs(ror_now) * 0.35)),
                  (slope, ror_now))
        # deviation against the staged ghost, recomputed here
        def dev_expected():
            raw = tag('[default]Roastery/BackgroundCurveJson')
            pairs = json.loads(raw) if raw else []
            pairs = [(float(a), float(b)) for a, b in pairs]
            cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
            if not pairs or not rows:
                return None
            bi = cols.index('bean')
            bean_rows = [r for r in rows if r[bi] is not None]
            if not bean_rows:
                return None
            last = bean_rows[-1]
            bg = interp(pairs, (last[0] - AXIS_BASE_MS) / 1000.0)
            if bg is None:
                return None
            return float(last[bi]) - bg

        dev_ok = wait_until(lambda: str(
            tag(B + '/BgDeviationText') or '') not in ('', '--'),
            timeout=60)
        check('bg deviation text is live during the roast', bool(dev_ok),
              tag(B + '/BgDeviationText'))
        if dev_ok:
            shown = float(str(tag(B + '/BgDeviationText')).replace(' F', ''))
            want = dev_expected()
            check('bg deviation matches live BT minus ghost BT at the '
                  'same elapsed time', want is not None
                  and approx(shown, want, 6.0), (shown, want))
        desk.wait_for_timeout(1500)
        check('desktop shows the Bg Deviation tile (the projection '
              'series itself is proven from LiveCurveDS above and '
              'its legend is canvas drawn)',
              desk.get_by_text('Bg Deviation').count() >= 1
              and desk.get_by_text('Deviation vs background').count() >= 1)
        desk.screenshot(path=SHOTS + '/roastery-tier2-live-projection.png')
        mob.wait_for_timeout(1200)
        worst = overflow_worst(mob)
        check('no overflow at 360px mid roast', worst <= 361, worst)
        mob.screenshot(path=SHOTS + '/roastery-tier2-live-360.png')

        # Settings: projection section exists; toggle off
        # empties the projection, quadratic mode still projects
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.locator('body').inner_text()
        check('settings page has the Projection section',
              'Where the bean curve is heading' in body)
        desk.screenshot(path=SHOTS + '/roastery-tier2-settings-projection.png')
        write_tags([(B + '/ProjectionEnabled', False)])
        gone = wait_until(lambda: not proj_rows(), timeout=60)
        check('projection toggle off empties the projection series',
              bool(gone))
        write_tags([(B + '/ProjectionEnabled', True),
                    (B + '/ProjectionMode', 'Quadratic')])
        back = wait_until(proj_rows, timeout=60)
        check('quadratic mode still projects (linear fallback before '
              'five minutes, as in Artisan)', bool(back))
        write_tags([(B + '/ProjectionMode', 'Linear')])

        # finish: drop, save, and the stored document must NOT
        # contain any projection data
        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        dock = mob.locator('.psc-roast-controldock')
        dock_drop(dock)
        check('drop lands', wait_tag(B + '/State', 'Dropped'))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Save Batch').first.click()
        saved = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast_no)) == 1,
            timeout=30)
        check('live roast saved', bool(saved))
        if saved:
            raw_doc = psql("SELECT data::text FROM batches WHERE "
                           "batch_number = %d" % roast_no)
            check('saved document carries phase analysis and loss keys',
                  'phaseAnalysis' in raw_doc and '"loss"' in raw_doc)
            check('projection is display only and never stored',
                  '"proj"' not in raw_doc
                  and 'projection' not in raw_doc.lower())
        psql('DELETE FROM batches WHERE batch_number = %d' % roast_no)
        # phase aware dock (polish phase 2): the Reset utility
        # is offered only at Complete, so walk the dropped
        # roast through Cool and Finish first (the old fixed
        # ActionRow had Reset at every state)
        desk.get_by_role('button', name='Cool').first.click()
        wait_tag(B + '/State', 'Cooling')
        desk.get_by_role('button', name='Finish').first.click()
        wait_tag(B + '/State', 'Complete')
        desk.get_by_role('button', name='Reset').first.click()
        check('reset returns the workspace to Idle',
              wait_tag(B + '/State', 'Idle'))
        for n in imported:
            psql('DELETE FROM batches WHERE batch_number = %d' % n)
        drain_pending()
        psql('DELETE FROM batch_events WHERE batch_number IN (%s)'
             % ', '.join(str(n) for n in imported + [roast_no, 1042]))
        write_tags([(B + '/BatchNumber', 1042)])
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        desk.get_by_role('button', name='Clear ghost').first.click()
        cleared = wait_until(
            lambda: tag('[default]Roastery/BackgroundLabel') == '',
            timeout=20)
        check('background cleared at the end', bool(cleared)
              and approx(tag('[default]Roastery/BackgroundDropSec'),
                         -1.0, 0.01))

        # ---------- items 11 to 14 -------------------------------
        make_playback_fixture()
        t2_imported = []
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        before = int(psql('SELECT COUNT(*) FROM batches'))
        upload(desk, PLAYBACK_ALOG)
        got = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches')) == before + 1,
            timeout=40)
        check('playback fixture imported', bool(got))
        pb_no = int(psql('SELECT MAX(batch_number) FROM batches'))
        t2_imported.append(pb_no)

        # stage it as the ghost: playback events ride along
        check('playback batch selected', select_batch_row(desk, pb_no))
        desk.get_by_role('button', name='Use as Ghost').first.click()
        desk.wait_for_timeout(3000)
        evs = json.loads(tag('[default]Roastery/BackgroundEventsJson')
                         or '[]')
        ev_map = dict(((e['kind'], int(e['t'])), e.get('level'))
                      for e in evs)
        check('ghost staging derives the playback events from the '
              'ghost series levels and drop time',
              ev_map.get(('Fan', 30)) == 3
              and ev_map.get(('Heat', 48)) == 4
              and ('Drop', 75) in ev_map,
              evs)
        check('playback ghost drop seconds staged',
              approx(tag('[default]Roastery/BackgroundDropSec'), 75, 0.1),
              tag('[default]Roastery/BackgroundDropSec'))

        # ----- item 13 on BatchDetail: analyzer readout -------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        check('playback batch re-selected', select_batch_row(desk, pb_no))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        # the ghost is this same batch, so ghost BT tracks the
        # detail curve and the deviation reads about zero.
        # Select a mid curve time (the fixture tail is a cooling
        # stretch whose offline RoR is clipped to null, so the
        # readout has no RoR there by design): write the
        # selection tag, then let a +10s step refresh at 310.
        write_tags([(DA + '/Sec', 300)])
        desk.get_by_role('button', name='+10s').first.click()
        desk.wait_for_timeout(2500)
        dsec = int(tag(DA + '/Sec'))
        pts3 = series_of(pb_no)
        want_bt = interp([(t, bt) for t, bt, _r in pts3], dsec)
        # The library interpolates RoR over the non null values
        # (offline RoR is blanked or clipped to null on parts of
        # this fixture, including its cooling tail); mirror that.
        ror_pairs = [(t, r) for t, _bt, r in pts3 if r is not None]
        want_ror = interp(ror_pairs, dsec)
        check('detail analyzer BT matches the stored curve at the '
              'selected time',
              approx(tag(DA + '/BtF'), want_bt, 0.6),
              (tag(DA + '/BtF'), want_bt, dsec))
        check('detail analyzer RoR matches the stored RoR interp '
              'at the selected time',
              approx(tag(DA + '/RorF'), want_ror, 3.0),
              (tag(DA + '/RorF'), want_ror))
        check('detail analyzer ghost BT equals the curve and the '
              'deviation is about zero against itself',
              approx(tag(DA + '/BgF'), want_bt, 0.6)
              and approx(tag(DA + '/DevF'), 0.0, 0.6),
              (tag(DA + '/BgF'), tag(DA + '/DevF')))
        check('detail analyzer time text is the selected mm:ss',
              tag(DA + '/TimeText') == mmss(dsec),
              tag(DA + '/TimeText'))
        desk.screenshot(path=SHOTS + '/roastery-tier2-analyzer-detail.png')
        mob.goto(BASE + '/log/detail', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        worst = overflow_worst(mob)
        check('detail analyzer strip fits 360px', worst <= 361, worst)
        mob.screenshot(path=SHOTS + '/roastery-tier2-analyzer-detail-360.png')

        # ----- the second live roast: items 11, 12, 13, 14 ----
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        expected2 = max(int(psql('SELECT MAX(batch_number) FROM batches')),
                        int(tag(B + '/BatchNumber'))) + 1
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        roast2_no = int(tag(B + '/BatchNumber'))
        check('second roast workspace', roast2_no == expected2
              and tag(B + '/State') == 'Idle', roast2_no)
        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        # Suggestion targets a few degrees above the live temp,
        # so both crossings arrive quickly and deterministically
        # (the Settings targets are live tags by design).
        bt0 = float(tag(B + '/BeanTempF') or 200)
        write_tags([(B + '/TargetDryEndTempF', min(bt0 + 8.0, 320.0))])
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('second roast charges', wait_tag(B + '/State', 'Roasting'))
        # Sim curve adjustment (2026-11-17, same note as the FC
        # target below): suggestions are turning point guarded,
        # and the rising curve is the one that crosses a dry end
        # target, so set the target a few degrees above the
        # rising temp once the turning point exists. The pre
        # charge write above still clears any stale target.
        wait_until(
            lambda: int(tag(B + '/TurningPointElapsedSec')) >= 0,
            timeout=180)
        bt0r = float(tag(B + '/BeanTempF') or 200)
        write_tags([(B + '/TargetDryEndTempF', min(bt0r + 8.0, 320.0))])

        # ----- item 14: Dry End suggestion --------------------
        sug = wait_until(
            lambda: bool(tag(B + '/SuggestionActive'))
            and tag(B + '/SuggestionKind') == 'DryEnd',
            timeout=180)
        check('dry end suggestion appears on the phase temp crossing',
              bool(sug), tag(B + '/SuggestionText'))
        check('suggestion text names the crossed target temp',
              'stamp Dry End?' in str(tag(B + '/SuggestionText') or ''),
              tag(B + '/SuggestionText'))
        check('no dry end is recorded before confirmation',
              int(tag(B + '/DryEndElapsedSec')) == -1
              and int(psql("SELECT COUNT(*) FROM batch_events WHERE "
                           "batch_number = %d AND action = 'Dry End'"
                           % roast2_no)) == 0)
        desk.screenshot(path=SHOTS + '/roastery-tier2-suggestion.png')
        mob.screenshot(path=SHOTS + '/roastery-tier2-suggestion-360.png')
        dock.get_by_role('button', name='Dry End').click()
        check('the normal button stamps dry end and clears the '
              'suggestion',
              wait_until(lambda: int(tag(B + '/DryEndElapsedSec')) >= 0
                         and not tag(B + '/SuggestionActive'),
                         timeout=25))
        pb_seen = []

        # ----- item 14: FC Start suggestion -------------------
        # Sim curve adjustment (2026-11-17): the stepped SR800
        # program dips after charge (392 F down to the turning
        # point near 185 F at about 73 s), so an FC target set
        # from the falling pre-charge temp would not be crossed
        # on the rise for many minutes and this wait would time
        # out on the clock, not on the suggestion logic. Wait
        # for the turning point first, then set the target a few
        # degrees above the rising temp: the same crossing setup
        # this check always intended, on the rising curve.
        wait_until(
            lambda: int(tag(B + '/TurningPointElapsedSec')) >= 0,
            timeout=180)
        bt1 = float(tag(B + '/BeanTempF') or 300)
        write_tags([(B + '/TargetFCTempF', min(bt1 + 12.0, 405.0))])
        sug = wait_until(
            lambda: bool(tag(B + '/SuggestionActive'))
            and tag(B + '/SuggestionKind') == 'FCStart',
            timeout=300)
        check('FC start suggestion appears on its crossing', bool(sug),
              tag(B + '/SuggestionText'))
        check('no FC start is recorded before confirmation',
              int(tag(B + '/FirstCrackStartElapsedSec')) == -1)
        # A playback prompt may be showing at the same moment;
        # the shared Dismiss clears both, so record its text
        # first and let the playback loop count it as seen.
        if tag(B + '/PlaybackActive'):
            pb_seen.append(str(tag(B + '/PlaybackText') or ''))
        desk.get_by_role('button', name='Dismiss').first.click()
        desk.wait_for_timeout(1500)
        check('dismiss clears the suggestion without stamping',
              not tag(B + '/SuggestionActive')
              and int(tag(B + '/FirstCrackStartElapsedSec')) == -1)
        dock.get_by_role('button', name='FC Start').click()
        check('FC start stamps from its normal button',
              wait_until(
                  lambda: int(tag(B + '/FirstCrackStartElapsedSec')) >= 0,
                  timeout=25))

        # ----- item 11: playback prompts ----------------------
        seen = list(pb_seen)
        shot_done = [False]

        def collect_prompt():
            if tag(B + '/PlaybackActive'):
                txt = str(tag(B + '/PlaybackText') or '')
                if txt and (not seen or seen[-1] != txt):
                    seen.append(txt)
                    if not shot_done[0]:
                        shot_done[0] = True
                        desk.screenshot(
                            path=SHOTS + '/roastery-tier2-playback.png')
                        mob.screenshot(
                            path=SHOTS + '/roastery-tier2-playback-360.png')
                try:
                    desk.get_by_role('button', name='Dismiss') \
                        .first.click(timeout=3000)
                except Exception:
                    pass
                desk.wait_for_timeout(600)
                return False
            return 'Background: Drop now' in seen

        done = wait_until(collect_prompt, timeout=240, step=1.5)
        check('playback prompts fire in ghost order (Fan, Heat, Drop)',
              bool(done) and seen[:3] == ['Background: Fan 3',
                                          'Background: Heat 4',
                                          'Background: Drop now'],
              seen)
        check('playback never wrote Fan or Heat and never dropped '
              'the roast',
              int(tag(B + '/FanLevel')) == 5
              and int(tag(B + '/HeatLevel')) == 5
              and tag(B + '/State') == 'Roasting',
              (tag(B + '/FanLevel'), tag(B + '/HeatLevel'),
               tag(B + '/State')))

        # ----- item 12: display smoothing ---------------------
        mob.wait_for_timeout(8000)
        live_off, raw_off = curve_maps()
        overlap = [ms for ms in live_off
                   if ms // 1000 in raw_off
                   and live_off[ms].get('bean') is not None]
        check('smoothing off: chart bean equals the raw samples',
              len(overlap) >= 5 and all(
                  abs(live_off[ms]['bean'] - raw_off[ms // 1000]) < 0.01
                  for ms in overlap),
              len(overlap))
        write_tags([(B + '/DisplaySmoothing', 3)])
        mob.wait_for_timeout(9000)
        live_on, raw_on = curve_maps()
        check('stored samples are unchanged with smoothing on',
              all(raw_on.get(s) == v for s, v in raw_off.items())
              and len(raw_on) >= len(raw_off),
              (len(raw_on), len(raw_off)))
        both = [ms for ms in live_on if ms in live_off
                and live_on[ms].get('bean') is not None
                and live_off[ms].get('bean') is not None]
        diffs = [live_on[ms]['bean'] - live_off[ms]['bean']
                 for ms in both]
        check('smoothing changes the displayed BT values',
              len(both) >= 5 and max(abs(d) for d in diffs) > 0.3,
              (len(both), max(abs(d) for d in diffs) if diffs else 0))
        rising = [live_on[ms]['bean'] - live_off[ms]['bean']
                  for ms in both
                  if (ms // 1000 - 10) in raw_off
                  and raw_off[ms // 1000] - raw_off[ms // 1000 - 10] > 2.0
                  and live_on[ms].get('bean') is not None]
        check('smoothed BT lags the raw line where the curve is '
              'rising (trailing filter direction)',
              len(rising) >= 3
              and sum(rising) / len(rising) < -0.05,
              (len(rising),
               sum(rising) / len(rising) if rising else 0))
        # Polish round 1 item 4: the drawn RoR column follows
        # the Artisan display convention, so before the turning
        # point it is blank in BOTH maps; identity is asserted
        # over every common sample, blank counting as equal,
        # which still proves display smoothing never touches
        # the RoR math.
        def _ror_eq(a, b):
            if a is None or b is None:
                return a is None and b is None
            return abs(a - b) < 0.05
        ror_same = [ms for ms in both
                    if _ror_eq(live_on[ms].get('ror'),
                               live_off[ms].get('ror'))]
        check('RoR column is identical with smoothing on and off',
              len(both) >= 5 and len(ror_same) == len(both),
              (len(both), len(ror_same)))
        desk.screenshot(path=SHOTS + '/roastery-tier2-smoothing-chart.png')
        write_tags([(B + '/DisplaySmoothing', 0)])

        # ----- item 13 on the live chart ----------------------
        desk.get_by_role('button', name='Latest').first.click()
        desk.wait_for_timeout(2500)
        live_now, raw_now = curve_maps()
        last_sec = max(raw_now)
        pairs = json.loads(tag('[default]Roastery/BackgroundCurveJson')
                           or '[]')
        pairs = [(float(a), float(b)) for a, b in pairs]
        want_bg = interp(pairs, last_sec)
        check('live analyzer at Latest reads the last sample BT',
              approx(tag(B + '/AnalyzerBtF'), raw_now[last_sec], 0.6),
              (tag(B + '/AnalyzerBtF'), raw_now[last_sec]))
        check('live analyzer RoR matches the live RoR tag',
              approx(tag(B + '/AnalyzerRorF'),
                     float(tag(B + '/RateOfRiseF') or 0), 4.0),
              (tag(B + '/AnalyzerRorF'), tag(B + '/RateOfRiseF')))
        check('live analyzer ghost BT and deviation match the ghost '
              'interp at the same time',
              want_bg is not None
              and approx(tag(B + '/AnalyzerBgF'), want_bg, 0.6)
              and approx(tag(B + '/AnalyzerDevF'),
                         raw_now[last_sec] - want_bg, 1.2),
              (tag(B + '/AnalyzerBgF'), want_bg))
        desk.get_by_role('button', name='-10s').first.click()
        desk.wait_for_timeout(600)
        desk.get_by_role('button', name='-10s').first.click()
        desk.wait_for_timeout(2500)
        asec = int(tag(B + '/AnalyzerSec'))
        want_bt = interp(sorted(raw_now.items()), asec)
        check('live analyzer stepper moves the selected time and '
              'the BT follows the curve interp',
              asec >= 0 and approx(tag(B + '/AnalyzerBtF'), want_bt, 0.6)
              and tag(B + '/AnalyzerTimeText') == mmss(asec),
              (asec, tag(B + '/AnalyzerBtF'), want_bt))
        desk.screenshot(path=SHOTS + '/roastery-tier2-analyzer-live.png')
        mob.wait_for_timeout(1200)
        worst = overflow_worst(mob)
        check('no overflow at 360px with the analyzer strip',
              worst <= 361, worst)
        mob.screenshot(path=SHOTS + '/roastery-tier2-analyzer-live-360.png')

        # ----- finish roast 2: stored series stay raw ---------
        dock.get_by_role('button', name='Drop').click()
        check('second roast drops', wait_tag(B + '/State', 'Dropped'))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Save Batch').first.click()
        saved2 = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast2_no)) == 1,
            timeout=30)
        check('second roast saved', bool(saved2))
        if saved2:
            stored = dict((int(t), bt) for t, bt, _r in series_of(roast2_no))
            shared = [s for s in stored if s in raw_now]
            check('saved series temps are the raw samples, not the '
                  'smoothed display values',
                  len(shared) >= 5 and all(
                      abs(stored[s] - raw_now[s]) < 0.01 for s in shared),
                  len(shared))
        psql('DELETE FROM batches WHERE batch_number = %d' % roast2_no)
        # phase aware dock (polish phase 2): the Reset utility
        # is offered only at Complete, so walk the dropped
        # roast through Cool and Finish first (the old fixed
        # ActionRow had Reset at every state)
        desk.get_by_role('button', name='Cool').first.click()
        wait_tag(B + '/State', 'Cooling')
        desk.get_by_role('button', name='Finish').first.click()
        wait_tag(B + '/State', 'Complete')
        desk.get_by_role('button', name='Reset').first.click()
        check('reset returns the workspace to Idle after roast 2',
              wait_tag(B + '/State', 'Idle'))
        for n in t2_imported:
            psql('DELETE FROM batches WHERE batch_number = %d' % n)
        # 1042 is in the list because New Roast records its
        # workspace Reset press under the batch number that was
        # current at the click (the standing 1042).
        drain_pending()
        psql('DELETE FROM batch_events WHERE batch_number IN (%s)'
             % ', '.join(str(n) for n in t2_imported + [roast2_no, 1042]))
        write_tags([(B + '/BatchNumber', 1042),
                    (B + '/TargetDryEndTempF', 300.0),
                    (B + '/TargetFCTempF', 385.0),
                    (B + '/DisplaySmoothing', 0),
                    (B + '/AnalyzerSec', -1)])
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        desk.get_by_role('button', name='Clear ghost').first.click()
        cleared2 = wait_until(
            lambda: tag('[default]Roastery/BackgroundLabel') == '',
            timeout=20)
        check('clearing the background clears its playback events '
              'and any pending prompt',
              bool(cleared2)
              and (tag('[default]Roastery/BackgroundEventsJson') or '') == ''
              and not tag(B + '/PlaybackActive'))

        # ----- settings page: the Tier 2 sections -------------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        # The sections sit below the scroll fold; scroll through
        # the page so every embedded section renders, then read
        # the full DOM text (inner_text skips unrendered parts).
        for _ in range(6):
            desk.mouse.wheel(0, 1200)
            desk.wait_for_timeout(700)
        body = desk.evaluate("document.body.textContent")
        check('settings page has the playback, suggestions and '
              'display sections',
              'Background Playback' in body
              and 'Event Suggestions' in body
              and 'Display Smoothing' in body
              and 'visual only' in body)
        desk.evaluate("window.scrollTo(0, 0)")
        desk.screenshot(path=SHOTS + '/roastery-tier2-settings-playback.png')

        check('no overlays at end',
              overlays(desk) == 0 and overlays(mob) == 0)
        browser.close()

    # ---------- final state --------------------------------------
    check('lab back to the seeded log',
          int(psql('SELECT COUNT(*) FROM batches')) == base_batches
          and int(psql('SELECT COUNT(*) FROM batch_series')) == base_series,
          (psql('SELECT COUNT(*) FROM batches'),
           psql('SELECT COUNT(*) FROM batch_series')))
    state = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/BatchNumber', B + '/ActiveSource',
                       B + '/Mode', B + '/ProjectionEnabled',
                       B + '/ProjectionMode', B + '/BgDeviationText',
                       B + '/PlaybackEnabled', B + '/PlaybackSound',
                       B + '/DisplaySmoothing',
                       B + '/SuggestDryEndEnabled',
                       B + '/SuggestFcEnabled', B + '/AnalyzerSec',
                       B + '/TargetDryEndTempF', B + '/TargetFCTempF',
                       B + '/PlaybackActive', B + '/SuggestionActive'])
    check('workspace clean Idle with Tier 2 defaults restored',
          state == ['Idle', 5, 5, 1042, 'Simulated', 'Off', True,
                    'Linear', '--', True, False, 0, True, True, -1,
                    300.0, 385.0, False, False], state)
    check('batch events back to the starting count',
          int(psql('SELECT COUNT(*) FROM batch_events')) == base_events,
          psql('SELECT COUNT(*) FROM batch_events'))
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad, bad[:3])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL TIER 2 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
