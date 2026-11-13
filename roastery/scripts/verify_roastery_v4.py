#!/usr/bin/env python3
"""Roastery v4 end to end verification (Playwright + REST + psql).

Proves the v4 contract in a live Maker session:
- the phone layout is the remote control: a full roast is driven
  from the 390px layout (ControlDock primary flow + steppers)
  while a 1600px desktop session shows the same state live;
- event marker lines land in EventMarksDS at the clicked times;
- Save Batch writes the JSONB document, batch_series rows (temp
  change capture) and batch_events rows (one per button press);
- Log detail stages the batch (curve, events, metadata, presses);
- the slide over editor rejects out of order event times with a
  visible message, and a valid edit recomputes phases, DTR and
  total time in the stored document;
- Use as Ghost stages the background overlay on the Roast page;
- New Roast zeroes the workspace with the next batch number;
- a phase target changed in Settings rebalances the phase bar;
- zero quality overlays and zero Roastery warnings in the window.

Screenshots land in showcase/shots/roastery-v4-*.png. The test
batch is deleted from the database at the end.
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
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:180]) if detail else '')
    if not cond:
        FAILURES.append(label)


def read_tags(paths):
    st, out = api('GET', '/tags/read', body=json.dumps({'tags': paths}))
    assert st == 200, (st, out)
    return [r['value'] for r in out['results']]


def tag(path):
    return read_tags([path])[0]


def wait_tag(path, want, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if tag(path) == want:
            return True
        time.sleep(0.7)
    return False


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


def log_marker():
    shutil.copy('gateway-2027-maker/logs/system_logs.idb',
                '/tmp/logs_v4_start.idb')
    con = sqlite3.connect('/tmp/logs_v4_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    shutil.copy('gateway-2027-maker/logs/system_logs.idb',
                '/tmp/logs_v4_end.idb')
    con = sqlite3.connect('/tmp/logs_v4_end.idb')
    rows = con.execute(
        "SELECT level_string, logger_name, formatted_message FROM "
        "logging_event WHERE level_int >= 30000 AND event_id > ? "
        "AND logger_name NOT LIKE '%multicast%' AND logger_name NOT "
        "LIKE '%ClientSession%' AND logger_name NOT LIKE "
        "'%GatewayTagRoutes%' ORDER BY event_id", (start_id,)).fetchall()
    con.close()
    return rows


def set_numeric(page, label_text, value):
    """Perspective numeric entry fields are read-only inputs:
    click to focus, select all, type, Enter commits and writes
    the bidirectional tag binding."""
    inp = page.locator(
        "xpath=//*[contains(text(),'%s')]/following::input[1]"
        % label_text)
    inp.first.click()
    page.wait_for_timeout(700)
    page.keyboard.press('Control+a')
    page.keyboard.type(str(value))
    page.keyboard.press('Enter')
    page.wait_for_timeout(1200)


def ds_rows(value):
    """Dataset tag values come back as a JSON string of
    {columns, rows}, a dict, or a list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if value is None:
        return []
    if isinstance(value, dict):
        return value.get('rows') or []
    if isinstance(value, list):
        return value
    return []


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    batch_no = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600, 'height': 900})
        mob = browser.new_page(viewport={'width': 390, 'height': 844})
        mob360 = browser.new_page(viewport={'width': 360, 'height': 740})
        for p in (desk, mob, mob360):
            p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
            p.wait_for_timeout(8000)
            dismiss(p)
        check('no overlays at start',
              overlays(desk) == 0 and overlays(mob) == 0)
        expected = max(
            int(psql('SELECT MAX(batch_number) FROM batches')),
            int(tag(B + '/BatchNumber'))) + 1
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        check('new roast opens a fresh workspace',
              tag(B + '/State') == 'Idle'
              and int(tag(B + '/BatchNumber')) == expected,
              (tag(B + '/State'), tag(B + '/BatchNumber'), expected))

        # ---- the roast, driven from the phone layout -------------
        dock = mob.locator('.psc-roast-controldock')
        check('mobile control dock present', dock.count() == 1)
        dock.get_by_role('button', name='Charge').click()
        check('charge from phone starts the roast',
              wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(1500)
        check('desktop session shows Roasting from the phone action',
              'Roasting' in desk.locator('body').inner_text())
        mob.wait_for_timeout(4500)
        fan0, heat0 = read_tags([B + '/FanLevel', B + '/HeatLevel'])
        dock.get_by_role('button', name='Dry End').click()
        mob.wait_for_timeout(800)
        dock.get_by_role('button', name='+').nth(0).click()   # Fan +1
        dock.get_by_role('button', name='+').nth(1).click()   # Heat +1
        mob.wait_for_timeout(500)
        fan, heat = read_tags([B + '/FanLevel', B + '/HeatLevel'])
        check('steppers moved fan and heat',
              (fan, heat) == (fan0 + 1, heat0 + 1), (fan, heat))
        mob.wait_for_timeout(4500)
        dock.get_by_role('button', name='FC Start').click()
        mob.wait_for_timeout(45000)
        marks = ds_rows(tag('[default]Roastery/EventMarksDS'))
        # columns: t_stamp, charge, dryEnd, fcStart, ...
        tops = [i for i, r in enumerate(marks)
                if any(v == 455.0 for v in r[1:])]
        check('event marker rows built', len(marks) >= 9, len(marks))
        check('marker columns carry CHARGE, DRY END and FC START',
              len(tops) == 3 and marks[tops[1]][2] == 455.0
              and marks[tops[2]][3] == 455.0,
              [marks[t][1:] for t in tops])

        # ---- v4.1: elapsed axis + live curve dataset -------------
        # The chart draws LiveCurveDS, built by the library from
        # the recorded samples: elapsed (epoch based) x values,
        # bean temps as stored, RoR from compute_ror_series.
        check('marker x values are elapsed (epoch based)',
              0 <= marks[0][0] < 3600000, marks[0][0])
        live = ds_rows(tag('[default]Roastery/LiveCurveDS'))
        check('live curve dataset has the roast samples',
              len(live) >= 20, len(live))
        check('live curve x values are elapsed (epoch based)',
              0 <= live[0][0] and live[-1][0] < 3600000,
              (live[0][0], live[-1][0]))
        check('live curve carries bean temps and calculated RoR',
              any(r[1] is not None for r in live)
              and sum(1 for r in live if r[2] is not None) >= 5
              and any(r[3] is not None and r[4] is not None
                      for r in live),
              live[-1])
        check('chart axis is labelled Elapsed (mm:ss)',
              desk.get_by_text('Elapsed (mm:ss)').count() >= 1)
        # Visible bleed only: an element counts when it starts
        # inside the viewport and extends past the right edge
        # (the defect Eric screenshotted). The Maker project
        # update modal parks fully off canvas at left == width
        # after a scan; it is session chrome, not app content.
        worst = mob360.evaluate("""() => {
          let w = 0;
          document.querySelectorAll('body *').forEach(el => {
            if (el.closest('.modal-body')) return;
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.left < window.innerWidth - 1)
              w = Math.max(w, r.right);
          });
          return Math.round(w);
        }""")
        check('no app element overflows a 360px phone',
              worst <= 361, worst)
        # HUD readability and tab label fit at 360px (parent
        # review of the first v4.1 shot: values read as one blob
        # and the Settings label clipped). Measure, do not
        # eyeball: value to value gaps and per button text fit.
        hud_gaps = mob360.evaluate("""() => {
          const els = [...document.querySelectorAll(
            '.psc-roast-hud-value, .psc-roast-hud-value-phase')]
            .map(e => e.getBoundingClientRect())
            .filter(r => r.width > 0)
            .sort((a, b) => a.x - b.x);
          const gaps = [];
          for (let i = 1; i < els.length; i++)
            gaps.push(Math.round(els[i].x - els[i - 1].right));
          return gaps;
        }""")
        check('HUD values are separated at 360px',
              len(hud_gaps) >= 3 and min(hud_gaps) >= 8, hud_gaps)
        tab_fit = mob360.evaluate("""() => {
          const bad = [];
          document.querySelectorAll('.psc-roast-tab-btn')
            .forEach(el => {
              if (el.scrollWidth > el.clientWidth + 1)
                bad.push((el.innerText || '').trim() + ':' +
                         el.scrollWidth + '>' + el.clientWidth);
            });
          return bad;
        }""")
        check('tab labels fully fit at 360px', tab_fit == [], tab_fit)
        # ---- v4.2: layout stability ------------------------------
        # Nothing may change position during a roast except the
        # values themselves and the chart drawing. Capture the
        # geometry of the state carrying elements twice, six
        # seconds apart, mid roast, and require zero drift.
        STAB_JS = """() => {
          const all = (sel) => [...document.querySelectorAll(sel)]
            .map(el => { const r = el.getBoundingClientRect();
              return [Math.round(r.x), Math.round(r.y),
                      Math.round(r.width), Math.round(r.height)]; })
            .filter(b => b[2] > 0);
          const one = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return [Math.round(r.x), Math.round(r.y),
                    Math.round(r.width), Math.round(r.height)];
          };
          return {pills: all('.psc-roast-pill'),
                  hudVals: all('.psc-roast-hud-value'),
                  phases: all('.psc-roast-seg'),
                  tiles: all('.psc-roast-cell'),
                  banner: one('.psc-roast-banner'),
                  tabbar: one('.psc-roast-tabbar')};
        }"""
        stab1_d = desk.evaluate(STAB_JS)
        stab1_m = mob360.evaluate(STAB_JS)
        mob360.wait_for_timeout(6000)
        stab2_d = desk.evaluate(STAB_JS)
        stab2_m = mob360.evaluate(STAB_JS)
        check('desktop layout is stable mid roast',
              stab1_d == stab2_d,
              (stab1_d, stab2_d) if stab1_d != stab2_d else 'frozen')
        check('mobile layout is stable mid roast',
              stab1_m == stab2_m,
              (stab1_m, stab2_m) if stab1_m != stab2_m else 'frozen')
        check('state pill has a fixed 88px box',
              any(p[2] == 88 for p in stab1_m['pills']),
              stab1_m['pills'])
        check('alarm banner slot is reserved (38px, empty or not)',
              stab1_d['banner'] is not None
              and stab1_d['banner'][3] == 38,
              stab1_d['banner'])
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-desktop.png'))
        mob.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-mobile.png'))
        mob360.screenshot(path=os.path.join(
            SHOTS, 'roastery-v41-roast-360.png'))
        check('no overlays mid roast',
              overlays(desk) == 0 and overlays(mob) == 0)

        dock.get_by_role('button', name='Drop').click()
        check('drop lands', wait_tag(B + '/State', 'Dropped'))
        mob.wait_for_timeout(1500)
        body = desk.locator('body').inner_text()
        check('desktop clock zero is set at Drop (SINCE DROP caption)',
              'SINCE DROP' in body)
        # Cool + Finish live in the full Controls embed (scroll col)
        mob.get_by_role('button', name='Cool').first.click()
        check('cooling', wait_tag(B + '/State', 'Cooling'))
        mob.wait_for_timeout(2500)
        mob.get_by_role('button', name='Finish').first.click()
        check('complete', wait_tag(B + '/State', 'Complete'))
        batch_no = int(tag(B + '/BatchNumber'))
        mob.get_by_role('button', name='Save Batch').first.click()
        mob.wait_for_timeout(3500)
        note = mob.locator('body').inner_text()
        check('saved batch is the fresh workspace number',
              batch_no == expected, (batch_no, expected))
        check('save note confirms the batch',
              ('Saved batch %d' % batch_no) in note, batch_no)

        # ---- database evidence -----------------------------------
        doc = psql("SELECT data FROM batches WHERE batch_number "
                   "= %d" % batch_no)
        check('batch document stored', bool(doc))
        doc = json.loads(doc)
        ev = doc['events']
        check('document events stamped',
              all(ev[k] for k in ('charge', 'dryEnd', 'fcStart', 'drop')),
              list(ev.keys()))
        series_n = int(psql("SELECT COUNT(*) FROM batch_series WHERE "
                            "batch_number = %d" % batch_no))
        check('temp change series captured', series_n >= 8, series_n)
        presses = psql("SELECT action FROM batch_events WHERE "
                       "batch_number = %d ORDER BY id" % batch_no)
        actions = [a for a in presses.split('\n') if a]
        check('one batch_events row per press',
              all(a in actions for a in
                  ('Charge', 'Dry End', 'First Crack Start', 'Drop',
                   'Cool', 'Finish', 'Fan +1', 'Heat +1', 'Save Batch')),
              actions)
        fc_t = ev['fcStart']['t']
        dry_t = ev['dryEnd']['t']

        # ---- log detail ------------------------------------------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.locator('.ia_table__row').nth(0).click()
        desk.wait_for_timeout(1000)
        desk.get_by_role('button', name='Details').click()
        desk.wait_for_timeout(5000)
        body = desk.locator('body').inner_text()
        check('detail page shows the batch',
              ('Batch %d' % batch_no) in body)
        check('detail shows captured presses',
              'CAPTURED BUTTON PRESSES' in body and 'Charge' in body)
        check('no overlays on detail', overlays(desk) == 0)
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-detail-desktop.png'))

        # ---- slide over editor: rejection, then a real edit ------
        desk.get_by_role('button', name='Edit', exact=True).click()
        desk.wait_for_timeout(3500)
        dockv = desk.locator('.docked-view-right')
        check('slide over opens', dockv.count() == 1)
        check('editor title names the batch',
              ('Edit Batch %d' % batch_no) in dockv.inner_text())

        def set_event_time(label_text, value):
            inp = dockv.locator(
                "xpath=//*[contains(text(),'%s')]/following::input[1]"
                % label_text)
            inp.first.fill(value)

        def submit_editor():
            dockv.get_by_role('button', name='Save Batch').click()
            desk.wait_for_timeout(3000)

        set_event_time('FC Start time', '00:03')
        submit_editor()
        note = dockv.inner_text()
        doc_now = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = %d"
            % batch_no))
        check('out of order edit rejected with a visible message',
              'Saved batch' not in note and len(note) > 0
              and doc_now['events']['fcStart']['t'] == fc_t,
              note[-140:])
        set_event_time('Dry End time', '00:15')
        set_event_time('FC Start time', '00:25')
        set_event_time('Drop time', '00:45')
        submit_editor()
        note = dockv.inner_text()
        check('valid edit saves', ('Saved batch %d' % batch_no) in note,
              note[-140:])
        doc2 = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = %d"
            % batch_no))
        ph = doc2['phases']
        exp_dtr = round((45 - 25) * 100.0 / 45, 2)
        check('phases recomputed from edited times',
              ph['dryingSec'] == 15 and doc2['totalSec'] == 45,
              ph)
        check('DTR recomputed from edited times',
              abs(ph['dtrPct'] - exp_dtr) < 0.6, (ph['dtrPct'], exp_dtr))
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-editor-desktop.png'))
        close_btn = dockv.get_by_role('button', name='Close')
        close_btn.evaluate('el => el.click()')
        desk.wait_for_timeout(1500)

        # ---- ghost ------------------------------------------------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.locator('.ia_table__row').nth(0).click()
        desk.wait_for_timeout(1000)
        desk.get_by_role('button', name='Use as Ghost').click()
        desk.wait_for_timeout(2500)
        bg_label = tag('[default]Roastery/BackgroundLabel')
        bg_rows = ds_rows(tag('[default]Roastery/BackgroundDS'))
        bg_ror = ds_rows(tag('[default]Roastery/BackgroundRorDS'))
        check('ghost staged with label and curve',
              str(batch_no) in str(bg_label) and len(bg_rows) >= 5,
              (bg_label, len(bg_rows)))
        bg_json = tag('[default]Roastery/BackgroundCurveJson')
        check('ghost RoR recomputed on read', len(bg_ror) >= 5,
              (len(bg_ror), str(bg_json)[:120]))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-ghost-desktop.png'))

        # ---- duplicate save is refused with guidance --------------
        desk.get_by_role('button', name='Reset').first.click()
        desk.wait_for_timeout(2000)
        desk.get_by_role('button', name='Charge').first.click()
        check('recharge for the duplicate save check',
              wait_tag(B + '/State', 'Roasting'))
        desk.wait_for_timeout(3000)
        desk.get_by_role('button', name='Drop').first.click()
        check('re-drop', wait_tag(B + '/State', 'Dropped'))
        desk.get_by_role('button', name='Cool').first.click()
        check('re-cool', wait_tag(B + '/State', 'Cooling'))
        desk.wait_for_timeout(1500)
        desk.get_by_role('button', name='Finish').first.click()
        check('re-finish', wait_tag(B + '/State', 'Complete'))
        desk.get_by_role('button', name='Save Batch').first.click()
        desk.wait_for_timeout(3000)
        body = desk.locator('body').inner_text()
        check('duplicate save refused with a visible explanation',
              'already in the log' in body)
        check('stored document untouched by the duplicate save',
              json.loads(psql(
                  "SELECT data FROM batches WHERE batch_number = %d"
                  % batch_no))['totalSec'] == 45)

        # ---- new roast --------------------------------------------
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        check('new roast takes the next batch number',
              int(tag(B + '/BatchNumber')) == batch_no + 1,
              tag(B + '/BatchNumber'))
        check('new roast workspace is clean Idle',
              tag(B + '/State') == 'Idle'
              and len(ds_rows(tag('[default]Roastery/EventMarksDS'))) == 0)

        # ---- settings phase target drives the phase bar -----------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        set_numeric(desk, 'Drying target (sec)', 300)
        check('phase target tag written',
              int(tag(B + '/PhaseDryTargetSec')) == 300,
              tag(B + '/PhaseDryTargetSec'))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.locator('body').inner_text()
        check('phase bar shows the new drying target',
              'target 05:00' in body)
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-settings-phasebar.png'))
        # restore
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        set_numeric(desk, 'Drying target (sec)', 270)

        # ---- dark theme pass --------------------------------------
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Light').click()
        desk.wait_for_timeout(3000)
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-dark-desktop.png'))
        mob.reload(wait_until='networkidle')
        mob.wait_for_timeout(6000)
        dismiss(mob)
        mob.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-dark-mobile.png'))
        check('no overlays in dark theme',
              overlays(desk) == 0 and overlays(mob) == 0)
        desk.get_by_role('button', name='Dark').click()
        desk.wait_for_timeout(2000)

        browser.close()

    # ---- cleanup + log window ------------------------------------
    if batch_no:
        psql("DELETE FROM batch_events WHERE batch_number = %d"
             % batch_no)
        psql("DELETE FROM batch_series WHERE batch_number = %d"
             % batch_no)
        psql("DELETE FROM batches WHERE batch_number = %d" % batch_no)
        check('test batch cleaned from the database',
              psql("SELECT COUNT(*) FROM batches WHERE batch_number "
                   "= %d" % batch_no) == '0')
    rows = log_check(start_event)
    bad = [r for r in rows if 'Error running action' in (r[2] or '')
           or 'roastery' in (r[1] or '').lower()]
    check('zero Roastery warnings in the validation window',
          len(bad) == 0, bad[:3])
    for r in rows:
        print('  log:', r[0], r[1], (r[2] or '')[:120])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
