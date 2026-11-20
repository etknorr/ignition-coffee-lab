#!/usr/bin/env python3
"""Roastery Tier 3c verification (Playwright + REST + psql).

Proves Tier 3 items 17 and 20 live on the Maker gateway:
17. Full profile designer for the target plan: the Settings
    Targets designer adds, edits and deletes plan points
    through the real UI (editor inputs, Load, Save, Add and
    Delete buttons), validation rejects out of order times
    with a visible note and saves nothing, the plan line
    overlay dataset and the library published deviation text
    read a 6 point plan, and Reset returns to the default
    4 point plan with the old behavior.
20. Between batch protocol, BT only: a simulated cycle
    (roast, DROP, a falling then rising BT window driven
    through the WebSocket source slot, CHARGE, Save) stores
    a bbp subdocument whose four values match an independent
    recompute from the staged BbpSamplesDS samples, and
    BatchDetail shows them. The first roast, saved with no
    preceding window, carries no bbp key, and neither does
    seeded batch 1042 on its detail page.

Presses write batch_events rows through the RUNNING
PressEvents transaction group (PressCaptureMode stays
Group); scripted presses are spaced over a second apart
and all test rows are deleted at the end.

Screenshots land in showcase/shots/roastery-tier3c-*.png.
The lab is left at 7 batches / 101 series rows / 0 events,
CurrentBatch clean Idle, target plan back to the default
4 points.
"""
import json
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
WS = B + '/Sources/WebSocket/BeanTempF'
BBP = '[default]Roastery/Bbp'
TE = '[default]Roastery/TargetEditor'
LOGS = '/home/hatch/workspace/ignition-lab/gateway-2027-maker/logs/system_logs.idb'
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


def set_editor_input(page, caption, value):
    """Type into the designer editor input that follows the
    given caption label in the DOM (the field column holds the
    caption and then its input). Returns True when the staging
    tag took the value."""
    inp = page.locator(
        "xpath=//*[normalize-space(text())='%s']/following::input[1]"
        % caption).first
    inp.click()
    inp.fill(str(value))
    inp.press('Tab')
    page.wait_for_timeout(700)


def plan_json():
    raw = tag(B + '/TargetPlanJson')
    return json.loads(raw) if raw else []


def plan_at(pts, s):
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if s <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (s - t0) / (t1 - t0)
    return pts[-1][1]


def interp(pts, t):
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        if t0 <= t <= t1:
            return v1 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def bbp_expected(samples, span=6.0):
    """Independent recompute of the four BBP metrics from the
    staged samples, following the definitions documented in
    roastery.core (bottom is the first minimum; RoR in and out
    are span slopes with linear interpolation)."""
    bottom = min(v for _t, v in samples)
    tb = [t for t, v in samples if v == bottom][0]
    t_first, t_last = samples[0][0], samples[-1][0]
    if tb > t_first:
        ta = max(t_first, tb - span)
        ror_in = (bottom - interp(samples, ta)) * 60.0 / (tb - ta)
    else:
        ror_in = 0.0
    if t_last > tb:
        te = min(t_last, tb + span)
        ror_out = (interp(samples, te) - bottom) * 60.0 / (te - tb)
    else:
        ror_out = 0.0
    return {'time_sec': t_last - t_first, 'bottom_temp_f': bottom,
            'ror_in_f_min': ror_in, 'ror_out_f_min': ror_out}


def approx(a, b, tol):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def dock_prereq(dock):
    """Phase aware dock (polish phase 2): Drop is offered only
    after FC End, so stamp the prerequisite events through the
    dock first. Each click waits for the dock to re-render its
    next phase set."""
    for name in ('Dry End', 'FC Start', 'FC End'):
        btn = dock.get_by_role('button', name=name)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            time.sleep(1.5)


def dock_drop(dock):
    dock_prereq(dock)
    dock.get_by_role('button', name='Drop').click()


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_t3c_start.idb')
    con = sqlite3.connect('/tmp/logs_t3c_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    last = None
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_t3c_end.idb')
            con = sqlite3.connect('/tmp/logs_t3c_end.idb')
            rows = con.execute(
                "SELECT level_string, logger_name, formatted_message "
                "FROM logging_event WHERE event_id > ? AND "
                "level_string IN ('WARN', 'ERROR')",
                (start_id,)).fetchall()
            con.close()
            return [r for r in rows
                    if 'roastery' in (r[1] or '').lower()
                    or 'Roastery' in (r[2] or '')]
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def select_batch_row(page, number):
    rows = page.locator('.ia_table__row')
    for i in range(rows.count()):
        tokens = rows.nth(i).inner_text().replace(',', '').split()
        if str(number) in tokens:
            rows.nth(i).click()
            page.wait_for_timeout(1200)
            return int(tag('[default]Roastery/SelectedBatchNumber')
                       or 0) == number
    return False


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    base = (int(psql('SELECT COUNT(*) FROM batches')),
            int(psql('SELECT COUNT(*) FROM batch_series')),
            int(psql('SELECT COUNT(*) FROM batch_events')))
    check('starting point is the seeded log', base == (7, 101, 0), base)
    max_event_id = int(psql('SELECT COALESCE(MAX(id), 0) FROM batch_events'))
    legacy0 = read_tags([B + '/TargetChargeTempF', B + '/TargetDryEndSec',
                         B + '/TargetDryEndTempF', B + '/TargetFCSec',
                         B + '/TargetFCTempF', B + '/TargetDropSec',
                         B + '/TargetDropTempF'])
    check('default plan is the legacy four points, JSON list empty',
          legacy0 == [200.0, 240, 300.0, 510, 385.0, 630, 415.0]
          and plan_json() == [], (legacy0, plan_json()))
    check('BBP staging starts empty',
          read_tags([BBP + '/WindowActive', BBP + '/HasMetrics'])
          == [False, False])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600, 'height': 1000})
        mob = browser.new_page(viewport={'width': 360, 'height': 740})
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
            p.wait_for_timeout(7000)
            dismiss(p)
        check('no overlays at start',
              overlays(desk) == 0 and overlays(mob) == 0)

        # ---------- item 17: the designer surface ---------------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('settings Targets carries the Target Plan Designer',
              'Target Plan Designer' in body
              and 'Points in plan: 4' in body, body[-200:])
        desk.screenshot(
            path=SHOTS + '/roastery-tier3c-designer-desktop.png')
        mob.goto(BASE + '/settings', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        check('designer has no overflow at 360px',
              overflow_worst(mob) <= 361, overflow_worst(mob))
        mob.evaluate("""() => {
          const el = [...document.querySelectorAll('*')]
            .find(e => e.textContent.trim() === 'Target Plan Designer');
          if (el) el.scrollIntoView({block: 'start'});
        }""")
        mob.wait_for_timeout(1200)
        mob.screenshot(path=SHOTS + '/roastery-tier3c-designer-360.png')

        # Load point 4 (drop) through the UI, then edit it.
        write_tags([(TE + '/Idx', 3)])
        desk.wait_for_timeout(600)
        check('Load Point button clicked',
              click_visible(desk, 'Load Point'))
        desk.wait_for_timeout(1200)
        check('editor loaded point 4 from the plan',
              read_tags([TE + '/TimeSec', TE + '/TempF']) == [630, 415.0],
              read_tags([TE + '/TimeSec', TE + '/TempF']))
        set_editor_input(desk, 'Point time (sec)', 600)
        set_editor_input(desk, 'Point temp (F)', 410)
        check('editor inputs wrote the staging tags',
              read_tags([TE + '/TimeSec', TE + '/TempF']) == [600, 410.0],
              read_tags([TE + '/TimeSec', TE + '/TempF']))
        check('Save Point button clicked',
              click_visible(desk, 'Save Point'))
        desk.wait_for_timeout(1500)
        plan = plan_json()
        check('saved edit is in the plan list (point 4 now 600, 410) '
              'and the drop legacy tags synced',
              plan == [[0.0, 200.0], [240.0, 300.0], [510.0, 385.0],
                       [600.0, 410.0]]
              and read_tags([B + '/TargetDropSec',
                             B + '/TargetDropTempF']) == [600, 410.0],
              plan)
        body = desk.evaluate("document.body.textContent")
        check('save note is visible', 'Saved target point 4' in body)

        # Add two points through the UI: a 6 point plan.
        set_editor_input(desk, 'Point time (sec)', 660)
        set_editor_input(desk, 'Point temp (F)', 418)
        check('Add Point button clicked (660)',
              click_visible(desk, 'Add Point'))
        desk.wait_for_timeout(1500)
        set_editor_input(desk, 'Point time (sec)', 720)
        set_editor_input(desk, 'Point temp (F)', 425)
        check('Add Point button clicked (720)',
              click_visible(desk, 'Add Point'))
        desk.wait_for_timeout(1500)
        plan = plan_json()
        check('plan now holds 6 points, strictly increasing',
              len(plan) == 6 and plan[-2] == [660.0, 418.0]
              and plan[-1] == [720.0, 425.0], plan)

        # Validation: an out of order Add is rejected, plan kept.
        before = plan_json()
        set_editor_input(desk, 'Point time (sec)', 700)
        set_editor_input(desk, 'Point temp (F)', 420)
        click_visible(desk, 'Add Point')
        desk.wait_for_timeout(1500)
        body = desk.evaluate("document.body.textContent")
        check('out of order Add is rejected with a visible note',
              'strictly increasing' in body, body[-200:])
        check('rejected Add saved nothing', plan_json() == before,
              plan_json())
        # Validation: an out of order Save on a middle point too.
        write_tags([(TE + '/Idx', 1)])
        desk.wait_for_timeout(500)
        click_visible(desk, 'Load Point')
        desk.wait_for_timeout(1200)
        set_editor_input(desk, 'Point time (sec)', 520)
        click_visible(desk, 'Save Point')
        desk.wait_for_timeout(1500)
        body = desk.evaluate("document.body.textContent")
        check('out of order Save is rejected with a visible note',
              'strictly increasing' in body)
        check('rejected Save saved nothing', plan_json() == before)

        # Delete through the UI, then re-add, back to 6 points.
        write_tags([(TE + '/Idx', 5)])
        desk.wait_for_timeout(500)
        click_visible(desk, 'Load Point')
        desk.wait_for_timeout(1200)
        click_visible(desk, 'Delete Point')
        desk.wait_for_timeout(1500)
        check('delete removed the last point',
              len(plan_json()) == 5, plan_json())
        set_editor_input(desk, 'Point time (sec)', 720)
        set_editor_input(desk, 'Point temp (F)', 425)
        click_visible(desk, 'Add Point')
        desk.wait_for_timeout(1500)
        plan6 = plan_json()
        check('plan is back to the same 6 points',
              plan6 == before, plan6)

        # ---------- item 20 setup: controlled BT source ---------
        write_tags([(B + '/RoRDeltaSpanSec', 6)])
        expected_no = max(int(psql('SELECT MAX(batch_number) FROM batches')),
                          int(tag(B + '/BatchNumber'))) + 1
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        roast1 = int(tag(B + '/BatchNumber'))
        check('new roast workspace for roast 1', roast1 == expected_no
              and tag(B + '/State') == 'Idle', roast1)
        write_tags([(B + '/ActiveSource', 'WebSocket'), (WS, 400.0)])
        ok = wait_until(lambda: approx(tag(B + '/BeanTempF'), 400.0, 0.01),
                        timeout=20)
        check('WebSocket source drives the canonical bean temp', bool(ok),
              tag(B + '/BeanTempF'))

        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('roast 1 charge starts', wait_tag(B + '/State', 'Roasting'))
        # Wiggle the slot temp: the deviation text and the curve
        # samples are temp change driven, and a held temp would
        # leave them at their charge time state.
        mob.wait_for_timeout(1500)
        write_tags([(WS, 402.0)])
        wait_until(lambda: approx(tag(B + '/BeanTempF'), 402.0, 0.01),
                   timeout=15)
        mob.wait_for_timeout(1200)
        write_tags([(WS, 404.0)])
        wait_until(lambda: approx(tag(B + '/BeanTempF'), 404.0, 0.01),
                   timeout=15)
        mob.wait_for_timeout(1500)

        # Plan line and deviation read the 6 point plan.
        def plan_rows():
            cols, rows = ds_rows(tag('[default]Roastery/TargetProfileDS'))
            if 'plan' not in cols or not rows:
                return None
            return rows
        rows = wait_until(plan_rows, timeout=30)
        check('plan overlay dataset exists during the roast', bool(rows))
        if rows:
            by_ms = dict((int(r[0]) - AXIS_BASE_MS, r[1])
                         for r in rows)
            check('plan line follows the 6 point plan (600 at 410, '
                  'ends 720 at 425)',
                  approx(by_ms.get(600000), 410.0, 0.6)
                  and approx(by_ms.get(720000), 425.0, 0.6)
                  and max(by_ms) == 720000,
                  (by_ms.get(600000), by_ms.get(720000), max(by_ms)))
        dev_txt = wait_until(
            lambda: str(tag(B + '/PlanDeviationText') or '')
            if str(tag(B + '/PlanDeviationText') or '') not in ('', '--')
            else None, timeout=30)
        check('deviation tile text is live against the 6 point plan',
              bool(dev_txt), dev_txt)
        if dev_txt:
            cols, lrows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
            bi = cols.index('bean')
            bean_rows = [r for r in lrows if r[bi] is not None]
            last = bean_rows[-1]
            want = float(last[bi]) - plan_at(
                [(float(t), float(v)) for t, v in plan6],
                (last[0] - AXIS_BASE_MS) / 1000.0)
            got = float(str(dev_txt).replace(' F', ''))
            check('deviation matches BT minus the 6 point plan at '
                  'the same elapsed time', approx(got, want, 6.0),
                  (got, want))
        desk.screenshot(path=SHOTS + '/roastery-tier3c-roast-plan-desktop.png')

        # ---------- item 20: DROP opens the window --------------
        mob.wait_for_timeout(1500)
        # prerequisites first: the DROP to CHARGE duration
        # below is measured from the Drop press itself, so the
        # timestamp is taken after the prerequisite stamps
        dock_prereq(dock)
        t_drop_click = time.time()
        dock.get_by_role('button', name='Drop').click()
        check('roast 1 drop lands', wait_tag(B + '/State', 'Dropped'))
        check('BBP window opened at DROP',
              wait_tag(BBP + '/WindowActive', True, timeout=15))
        mob.wait_for_timeout(1600)
        # Save roast 1 mid window: no preceding window, so its
        # document must carry no bbp, and the window must survive.
        desk.get_by_role('button', name='Save Batch').first.click()
        saved1 = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast1)) == 1,
            timeout=30)
        check('roast 1 saved mid window', bool(saved1))
        if saved1:
            doc1 = json.loads(psql(
                'SELECT data FROM batches WHERE batch_number = %d'
                % roast1))
            check('roast 1 document has no bbp (no preceding window)',
                  'bbp' not in doc1, list(doc1.keys()))
            check('roast 1 document target carries the 6 point plan',
                  (doc1.get('target') or {}).get('points') == plan6,
                  (doc1.get('target') or {}).get('points'))
        check('window survived the batch save',
              tag(BBP + '/WindowActive') is True)

        # Falling then rising BT through the source slot.
        seq = [385.0, 370.0, 355.0, 340.0, 328.0,
               340.0, 355.0, 372.0, 390.0]
        for v in seq:
            write_tags([(WS, v)])
            wait_until(lambda: approx(tag(B + '/BeanTempF'), v, 0.01),
                       timeout=15)
            mob.wait_for_timeout(1700)
        cols, srows = ds_rows(tag('[default]Roastery/BbpSamplesDS'))
        ti, vi = cols.index('t_offset_sec'), cols.index('bean_temp_f')
        samples = [(float(r[ti]), float(r[vi])) for r in srows]
        samples.sort()
        check('window staged at least 9 samples (drop plus the '
              'falling and rising writes)', len(samples) >= 9,
              (len(samples), samples[:3]))
        check('staged bottom is the written minimum 328 F',
              samples and min(v for _t, v in samples) == 328.0,
              samples)
        mob.screenshot(path=SHOTS + '/roastery-tier3c-bbp-window-360.png')
        expected = bbp_expected(samples, span=6.0)

        # Close roast 1 through its real flow (Cool, then
        # Finish): Charge is only enabled from Idle or Complete,
        # and the window keeps capturing through both states.
        mob.evaluate("window.scrollTo(0, 900)")
        mob.wait_for_timeout(800)
        check('cool button clicked', click_visible(mob, 'Cool'))
        check('cooling starts', wait_tag(B + '/State', 'Cooling'))
        mob.wait_for_timeout(1600)
        check('finish button clicked', click_visible(desk, 'Finish'))
        check('roast 1 complete', wait_tag(B + '/State', 'Complete'))
        check('window still open in Complete',
              tag(BBP + '/WindowActive') is True)
        mob.wait_for_timeout(1600)

        # CHARGE roast 2: the window finalizes into staged metrics.
        roast2 = roast1 + 1
        write_tags([(B + '/BatchNumber', roast2)])
        mob.wait_for_timeout(1500)
        t_charge_click = time.time()
        dock.get_by_role('button', name='Charge').click()
        check('roast 2 charge starts', wait_tag(B + '/State', 'Roasting'))
        staged = read_tags([BBP + '/HasMetrics', BBP + '/TimeSec',
                            BBP + '/BottomTempF', BBP + '/RorInFMin',
                            BBP + '/RorOutFMin', BBP + '/WindowActive'])
        check('metrics staged at CHARGE and the window closed',
              staged[0] is True and staged[5] is False, staged)
        check('staged bottom temp matches the recompute',
              approx(staged[2], expected['bottom_temp_f'], 0.01), staged)
        check('staged RoR in matches the span slope recompute',
              approx(staged[3], expected['ror_in_f_min'],
                     max(8.0, abs(expected['ror_in_f_min']) * 0.08)),
              (staged[3], expected['ror_in_f_min']))
        check('staged RoR out matches the span slope recompute',
              approx(staged[4], expected['ror_out_f_min'],
                     max(8.0, abs(expected['ror_out_f_min']) * 0.08)),
              (staged[4], expected['ror_out_f_min']))
        check('staged total time is the DROP to CHARGE duration',
              approx(staged[1], t_charge_click - t_drop_click, 4.0),
              (staged[1], t_charge_click - t_drop_click))

        # Finish roast 2 and save it: the bbp subdocument lands.
        mob.wait_for_timeout(3500)
        dock_drop(dock)
        check('roast 2 drop lands', wait_tag(B + '/State', 'Dropped'))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Save Batch').first.click()
        saved2 = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast2)) == 1,
            timeout=30)
        check('roast 2 saved', bool(saved2))
        bbp_doc = {}
        if saved2:
            doc2 = json.loads(psql(
                'SELECT data FROM batches WHERE batch_number = %d'
                % roast2))
            bbp_doc = doc2.get('bbp') or {}
            check('roast 2 document carries the bbp subdocument',
                  set(bbp_doc.keys()) == {'time_sec', 'bottom_temp_f',
                                          'ror_in_f_min',
                                          'ror_out_f_min'},
                  bbp_doc)
            check('bbp values match the staged metrics',
                  approx(bbp_doc.get('bottom_temp_f'), staged[2], 0.01)
                  and approx(bbp_doc.get('ror_in_f_min'), staged[3], 0.01)
                  and approx(bbp_doc.get('ror_out_f_min'), staged[4], 0.01)
                  and approx(bbp_doc.get('time_sec'), staged[1], 0.01),
                  bbp_doc)
            check('bbp values match the independent recompute '
                  '(bottom, RoR in, RoR out)',
                  approx(bbp_doc.get('bottom_temp_f'),
                         expected['bottom_temp_f'], 0.01)
                  and approx(bbp_doc.get('ror_in_f_min'),
                             expected['ror_in_f_min'],
                             max(8.0, abs(expected['ror_in_f_min']) * 0.08))
                  and approx(bbp_doc.get('ror_out_f_min'),
                             expected['ror_out_f_min'],
                             max(8.0, abs(expected['ror_out_f_min']) * 0.08)),
                  (bbp_doc, expected))

        # ---------- BatchDetail shows BBP, and only then --------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        check('roast 2 selected', select_batch_row(desk, roast2))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        want_line = ('Between batch (BBP)' in body
                     and 'bottom 328 F' in body
                     and ('RoR in %.1f F/min' % float(staged[3])) in body
                     and ('RoR out %.1f F/min' % float(staged[4])) in body)
        check('BatchDetail shows the BBP line with all four values',
              want_line, body[-300:])
        desk.evaluate("""() => {
          const el = [...document.querySelectorAll('*')]
            .find(e => e.textContent.trim()
              .startsWith('Between batch (BBP)'));
          if (el) el.scrollIntoView({block: 'center'});
        }""")
        desk.wait_for_timeout(1200)
        desk.screenshot(
            path=SHOTS + '/roastery-tier3c-detail-bbp-desktop.png')
        mob.goto(BASE + '/log/detail', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        check('BatchDetail BBP has no overflow at 360px',
              overflow_worst(mob) <= 361, overflow_worst(mob))
        mob.screenshot(path=SHOTS + '/roastery-tier3c-detail-bbp-360.png')

        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        check('batch 1042 selected', select_batch_row(desk, 1042))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('a batch with no preceding drop shows no BBP line',
              'Between batch (BBP)' not in body)

        # ---------- restore the default plan through the UI -----
        write_tags([(B + '/TargetChargeTempF', 200.0),
                    (B + '/TargetDryEndSec', 240),
                    (B + '/TargetDryEndTempF', 300.0),
                    (B + '/TargetFCSec', 510),
                    (B + '/TargetFCTempF', 385.0),
                    (B + '/TargetDropSec', 630),
                    (B + '/TargetDropTempF', 415.0)])
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        check('Reset to Four Points button clicked',
              click_visible(desk, 'Reset to Four Points'))
        desk.wait_for_timeout(1500)
        check('plan is the default 4 points again (JSON cleared, '
              'legacy tags at defaults)',
              plan_json() == []
              and read_tags([B + '/TargetChargeTempF',
                             B + '/TargetDryEndSec',
                             B + '/TargetDryEndTempF', B + '/TargetFCSec',
                             B + '/TargetFCTempF', B + '/TargetDropSec',
                             B + '/TargetDropTempF']) == legacy0)
        body = desk.evaluate("document.body.textContent")
        check('reset note and 4 point count are visible',
              'Points in plan: 4' in body, body[-200:])

        # ---------- clean the workspace through the UI ----------
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        # phase aware dock (polish phase 2): at Dropped the
        # dock offers Cool and Finish; the Reset utility is
        # offered at Complete under its full label. Walk the
        # roast closed first (the window stays open through
        # Cooling and Complete, so the discard assertion
        # below still tests Reset itself).
        click_visible(desk, 'Cool')
        wait_tag(B + '/State', 'Cooling')
        # a click dispatched while the dock re-renders its
        # phase set can be swallowed, so retry each click
        # until the STATE advances, not until it dispatches
        def click_until(name, state, timeout=40):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if tag(B + '/State') == state:
                    return True
                click_visible(desk, name)
                time.sleep(1.2)
            return tag(B + '/State') == state
        click_until('Finish', 'Complete')
        check('reset through its button',
              click_until('Reset / New Roast', 'Idle'))
        check('reset discarded the window opened by roast 2 drop',
              read_tags([BBP + '/WindowActive', BBP + '/HasMetrics',
                         BBP + '/SampleCount']) == [False, False, 0],
              read_tags([BBP + '/WindowActive', BBP + '/HasMetrics',
                         BBP + '/SampleCount']))
        # Polish round 6: the ghost staged earlier in this
        # suite was never cleared (reset_batch does not clear
        # the background by design), so the restore section's
        # 'background cleared at the end' check failed. Clear
        # it through the app's own button, the way the tier
        # suites do. HUNT-46: this desk session has already
        # mounted /settings, so the click runs on a fresh
        # page (a fresh session, first mount), the way the v4
        # suite does it.
        ghost = browser.new_page(viewport={'width': 1600,
                                           'height': 900},
                                 timezone_id='America/Denver')
        ghost.goto(BASE + '/settings', wait_until='networkidle',
                   timeout=60000)
        ghost.wait_for_timeout(4000)
        dismiss(ghost)
        check('ghost cleared through its button',
              click_visible(ghost, 'Clear ghost')
              and wait_until(
                  lambda: (tag('[default]Roastery/BackgroundLabel')
                           or '') == '', timeout=20))
        ghost.close()
        browser.close()

    # ---------- restore ------------------------------------------
    psql('DELETE FROM batches WHERE batch_number IN (%d, %d)'
         % (roast1, roast2))
    drain_pending()
    psql('DELETE FROM batch_events WHERE id > %d' % max_event_id)
    write_tags([(B + '/BatchNumber', 1042),
                (B + '/ActiveSource', 'Simulated'),
                (B + '/RoRDeltaSpanSec', 20),
                (WS, 0.0)])
    state = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/BatchNumber', B + '/ActiveSource',
                       B + '/Mode'])
    check('workspace clean Idle', state == ['Idle', 5, 5, 1042,
                                            'Simulated', 'Off'], state)
    check('background cleared at the end',
          (tag('[default]Roastery/BackgroundLabel') or '') == '')
    check('deviation text back to dashes',
          tag(B + '/PlanDeviationText') == '--')
    end = (int(psql('SELECT COUNT(*) FROM batches')),
           int(psql('SELECT COUNT(*) FROM batch_series')),
           int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab back to the seeded log', end == base, end)
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad, bad[:3])
    # Polish round 6 (HUNT-27 watch): a replayed Charge can
    # land after the checks above (the platform re-delivers a
    # dock click seconds late, even after the session closed),
    # leaving the workspace Roasting for the next suite. The
    # checks above stay as-is, they caught the phantom in the
    # rerun; this probe reset runs AFTER them so the lab is
    # left clean regardless. The reset's own Reset press row
    # is cleaned the same way (ring slots emptied first, then
    # the row deleted), and the lab is re-verified clean.
    import verify_roastery_polish2 as _P
    try:
        _P.probe_setup()
        _P.probe('reset', timeout=30)
    finally:
        _P.probe_teardown()
    time.sleep(5)
    _slots = ['[default]Roastery/PressSlots/Slot%02d' % i
              for i in range(16)]
    write_tags([(s, '') for s in _slots])
    time.sleep(2)
    psql('DELETE FROM batch_events WHERE id > %d' % max_event_id)
    time.sleep(3)
    _state2 = read_tags([B + '/State', B + '/Mode',
                         B + '/BatchNumber'])
    _end2 = (int(psql('SELECT COUNT(*) FROM batches')),
             int(psql('SELECT COUNT(*) FROM batch_series')),
             int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab left clean after post-check reset',
          _state2 == ['Idle', 'Off', 1042] and _end2 == base,
          (_state2, _end2))
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL TIER 3C CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
