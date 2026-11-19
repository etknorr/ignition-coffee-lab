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
import re
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
# Polish round 1 item 2: chart datasets anchor their x values
# to roastery.core.AXIS_BASE_MS (a Denver local midnight), not
# the Unix epoch, so Denver browsers label the ticks as
# elapsed mm:ss. Dataset assertions subtract the base.
AXIS_BASE_MS = 946710000000
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


def wait_until(fn, timeout=30, step=0.5):
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
    _paths = ['[default]Roastery/PressSlots/Slot%02d' % i
              for i in range(16)]
    api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': _paths, 'values': [''] * 16}))

def page_drop(page):
    """Phase aware dock (polish phase 2): Drop is offered only
    after FC End, so stamp the prerequisite events through the
    dock first, then Drop. Each click waits for the dock to
    re-render its next phase set."""
    for name in ('Dry End', 'FC Start', 'FC End'):
        btn = page.get_by_role('button', name=name)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            time.sleep(1.5)
    page.get_by_role('button', name='Drop').first.click()


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
        # The PressEvents transaction group scans at 250 ms;
        # two presses inside one scan coalesce into a single
        # batch_events row (the group sees only the latest
        # LastAction). Pace the clicks like a human would.
        mob.wait_for_timeout(800)
        dock.get_by_role('button', name='+').nth(1).click()   # Heat +1
        mob.wait_for_timeout(500)
        fan, heat = read_tags([B + '/FanLevel', B + '/HeatLevel'])
        check('steppers moved fan and heat',
              (fan, heat) == (fan0 + 1, heat0 + 1), (fan, heat))
        mob.wait_for_timeout(4500)
        # Polish round 1 item 4: live turning point tracking
        # runs only until First Crack Start is stamped (the
        # Artisan charge to first crack window), so the TP
        # confirmation must be awaited BEFORE the FC stamp.
        # The stepped sim dips to about 185 F at 37 s elapsed
        # and confirms the TP on the rise at about 45 s.
        check('turning point confirms before first crack',
              wait_until(
                  lambda: int(tag(B + '/TurningPointElapsedSec')
                              or -1) >= 0, timeout=150))
        dock.get_by_role('button', name='FC Start').click()
        mob.wait_for_timeout(45000)
        marks = ds_rows(tag('[default]Roastery/EventMarksDS'))
        # columns: t_stamp, charge, dryEnd, fcStart, ...
        tops = [i for i, r in enumerate(marks)
                if any(v == 455.0 for v in r[1:])]
        check('event marker rows built', len(marks) >= 9, len(marks))
        # Column based, not row count based (Tier 1 hardening):
        # the live turning point marker (notes column) is a
        # legitimate extra row since v5; the contract is that
        # each stamped event tops its OWN column.
        def _top_in(col):
            return any(marks[t][col] == 455.0 for t in tops)
        check('marker columns carry CHARGE, DRY END and FC START',
              len(tops) >= 3 and _top_in(1) and _top_in(2)
              and _top_in(3),
              [marks[t][1:] for t in tops])

        # ---- v4.1: elapsed axis + live curve dataset -------------
        # The chart draws LiveCurveDS, built by the library from
        # the recorded samples: elapsed (axis based) x values,
        # bean temps as stored, RoR from compute_ror_series.
        check('marker x values are elapsed (axis based)',
              0 <= marks[0][0] - AXIS_BASE_MS < 3600000,
              marks[0][0])
        live = ds_rows(tag('[default]Roastery/LiveCurveDS'))
        check('live curve dataset has the roast samples',
              len(live) >= 20, len(live))
        check('live curve x values are elapsed (axis based)',
              0 <= live[0][0] - AXIS_BASE_MS
              and live[-1][0] - AXIS_BASE_MS < 3600000,
              (live[0][0], live[-1][0]))
        # Polish round 1 item 4: the DRAWN RoR column follows
        # the Artisan display convention (blank before the
        # turning point confirms and outside the RoR clip
        # limits); the stored samples keep the true values.
        # This read lands mid dip, so the assertion is the
        # convention itself; RoR presence after TP is asserted
        # on the detail page below.
        _clip = read_tags([B + '/RoRClipLowF', B + '/RoRClipHighF'])
        # Polish round 3: LIVE_COLS gained t_label and t_sec
        # after t_stamp for the category axis, so bean is
        # index 3, ror 4, fan 5, heat 6.
        check('live curve carries bean temps and display gated '
              'RoR',
              any(r[3] is not None for r in live)
              and all(r[4] is None or _clip[0] <= r[4] <= _clip[1]
                      for r in live)
              and any(r[5] is not None and r[6] is not None
                      for r in live),
              live[-1])
        # v4.4: the charts are canvas components now; their
        # axis titles are canvas text, not DOM text, so the
        # label is asserted on the served view config (the
        # mm:ss tick format itself is screenshot verified).
        def _find(node, want_type, want_name):
            if isinstance(node, dict):
                if (node.get('type') == want_type
                        and node.get('meta', {}).get('name')
                        == want_name):
                    return node
                for v in node.values():
                    hit = _find(v, want_type, want_name)
                    if hit is not None:
                        return hit
            elif isinstance(node, list):
                for v in node:
                    hit = _find(v, want_type, want_name)
                    if hit is not None:
                        return hit
            return None

        _rp = json.load(open(
            'gateway-2027-maker/data/projects/Roastery/com'
            '.inductiveautomation.perspective/views/Views/'
            'RoastPage/view.json'))
        _chart = _find(_rp.get('root', {}),
                       'ia.canvas-charts.line', 'RoastChart')
        check('main chart is a canvas line chart on a '
              'category elapsed axis (round 3)',
              _chart is not None
              and _chart['props']['xAxis']['type'] == 'category'
              and _chart['props']['xAxis']['field'] == 't_label'
              and _chart['props']['xAxis']['title']['text']
              == '')
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

        # The turning point was confirmed before the FC Start
        # stamp above, and the roast has minutes of rising
        # curve by now, so the saved curve and its ghost RoR
        # carry the rise (a dip only drop would leave the
        # ghost RoR legitimately empty under the display
        # convention).
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
        # Hardened phase analysis check. The old form was a raw
        # body text substring conjunction and it failed even though
        # the data was right: the Turning point caption carries
        # the roast-kv-cap style class (textTransform uppercase),
        # so extracted body text reads TURNING POINT and the mixed
        # case literal could never match, and any card layout
        # change reshuffles extracted text across cards. This form
        # verifies content against database truth instead: the
        # stored document phases must equal the durations derived
        # from the stored event times, and the detail page Summary
        # phase line and DTR readout must show those same values.
        # Only the summary line itself is parsed, never the global
        # ordering of text across unrelated cards.
        _ev = doc['events']
        _dry = int(round(_ev['dryEnd']['t'] - _ev['charge']['t']))
        _mai = int(round(_ev['fcStart']['t'] - _ev['dryEnd']['t']))
        _dev = int(round(_ev['drop']['t'] - _ev['fcStart']['t']))
        _tot = int(round(_ev['drop']['t'] - _ev['charge']['t']))
        _ph = doc['phases']
        _doc_ok = (int(round(_ph['dryingSec'])) == _dry
                   and int(round(_ph['maillardSec'])) == _mai
                   and int(round(_ph['developmentSec'])) == _dev
                   and abs(_ph['dtrPct'] - _dev * 100.0 / _tot) < 0.6)

        def _mmss(s):
            return '%02d:%02d' % (s // 60, s % 60)

        _line = re.search(
            r'Drying (\d+:\d+) - Maillard (\d+:\d+) - '
            r'Development (\d+:\d+)', body)
        _line_ok = (_line is not None
                    and _line.groups() == (_mmss(_dry), _mmss(_mai),
                                           _mmss(_dev)))
        _dtr = re.search(r'DEV RATIO \(DTR\)\s*\n\s*([\d.]+)%', body)
        _dtr_ok = (_dtr is not None
                   and abs(float(_dtr.group(1))
                           - _dev * 100.0 / _tot) < 0.6)
        _tp_ok = re.search(
            r'TURNING POINT\s*\n\s*\d+ F at \d+:\d+', body) is not None
        check('detail shows phase analysis',
              'PHASE ANALYSIS' in body and _doc_ok and _line_ok
              and _dtr_ok and _tp_ok,
              'doc phases %s | line %s | dtr %s | expected %s/%s/%s '
              'dtr %.1f' % (_ph,
                            _line.groups() if _line else None,
                            _dtr.group(1) if _dtr else None,
                            _mmss(_dry), _mmss(_mai), _mmss(_dev),
                            _dev * 100.0 / _tot))
        check('no overlays on detail', overlays(desk) == 0)
        # Polish round 1 item 4, second half: after the turning
        # point the live curve RoR column carries the true
        # computed values (the dip read above asserted the
        # blank side of the convention).
        _live2 = ds_rows(tag('[default]Roastery/LiveCurveDS'))
        check('live curve RoR appears after the turning point',
              sum(1 for r in _live2 if r[4] is not None) >= 5,
              sum(1 for r in _live2 if r[2] is not None))
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-detail-desktop.png'))

        # ---- slide over editor: rejection, then a real edit ------
        desk.get_by_role('button', name='Edit', exact=True).click()
        desk.wait_for_timeout(3500)
        dockv = desk.locator('.docked-view-right')
        check('slide over opens', dockv.count() == 1)
        check('editor title names the batch',
              ('Edit Batch %d' % batch_no) in dockv.inner_text())
        # Polish round 2 item 2: wait on the real readiness
        # condition, the fully mounted form (59 inputs in the
        # dock DOM; a stalled long lived session shows the
        # title with only a partial mount, 11 inputs in the
        # phase 4 dump), instead of proceeding on the title
        # alone. Generous timeout: the stall observed in the
        # chained battery outlasted the old 30 s waits.
        # Polish round 2 part A: reload recovery. A fresh page
        # instance always renders the editor (item 2 finding),
        # so if the readiness poll times out on this aged
        # session, reload the page once, reopen the editor,
        # and poll again; only a second stall records the
        # named failure below.
        _mounted = wait_until(
            lambda: dockv.locator('input').count() >= 59,
            timeout=120)
        if not _mounted:
            print('SUITE NOTE: reload recovery fired in v4 '
                  'editor readiness (mount poll timed out); '
                  'reloading the page and reopening the editor '
                  'once')
            desk.reload(wait_until='networkidle', timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            desk.get_by_role('button', name='Edit',
                             exact=True).click()
            desk.wait_for_timeout(3500)
            dockv = desk.locator('.docked-view-right')
            _mounted = wait_until(
                lambda: dockv.locator('input').count() >= 59,
                timeout=120)
        check('editor form fully rendered (59 dock inputs)',
              bool(_mounted),
              dockv.locator('input').count())

        def set_event_time(label_text, value):
            # Type like a user. Playwright fill() sets the DOM
            # value without the key events the form's change
            # tracking listens for, and on a pristine form the
            # edit then never registers, so Save Batch
            # (autoDisable) stays disabled; that was the
            # intermittent editor stall behind the polish
            # round 1 item 0 regression report. The read back
            # also guards against a late prefill refresh
            # stomping the typed value.
            inp = dockv.locator(
                "xpath=//*[contains(text(),'%s')]/following::input[1]"
                % label_text)
            for _try in range(2):
                inp.first.click()
                inp.first.press('Control+a')
                inp.first.press_sequentially(value, delay=60)
                inp.first.press('Tab')
                desk.wait_for_timeout(1200)
                if inp.first.input_value() == value:
                    return

        def submit_editor():
            # The form prefill lands asynchronously; under load
            # a fill made before it lands is overwritten by the
            # prefill and the form reads pristine, so Save
            # Batch (autoDisable) stays disabled. Wait for the
            # button to actually enable before clicking.
            # Polish round 2 item 2: never click a button that
            # stayed disabled (the blind click burned a 30 s
            # Playwright timeout and crashed the suite as
            # INCOMPLETE in the phase 4 battery); record the
            # failure as a check instead so the suite completes
            # and names the stall.
            btn = dockv.get_by_role('button', name='Save Batch')
            enabled = wait_until(lambda: not btn.is_disabled(),
                                 timeout=60)
            if not enabled:
                # Polish round 2 part A: reload recovery, the
                # submit_editor site. Reload the page once and
                # reopen the editor on the fresh instance (the
                # item 2 recovery); the typed edit is lost with
                # the stalled instance, so the named failure is
                # recorded either way, with the remount result
                # as its detail.
                print('SUITE NOTE: reload recovery fired in v4 '
                      'submit_editor (Save never enabled); '
                      'reloading the page and reopening the '
                      'editor once')
                desk.reload(wait_until='networkidle',
                            timeout=60000)
                desk.wait_for_timeout(5000)
                dismiss(desk)
                desk.get_by_role('button', name='Edit',
                                 exact=True).click()
                desk.wait_for_timeout(3500)
                remounted = wait_until(
                    lambda: dockv.locator('input').count() >= 59,
                    timeout=120)
                check('editor Save Batch enabled after edit', False,
                      'still disabled after 60 s; reload recovery '
                      'remounted the form: %s' % bool(remounted))
                return
            btn.click()
            desk.wait_for_timeout(3000)

        # Wait until the prefill has landed (FC Start shows
        # the stamped time) before editing anything.
        _fc_inp = dockv.locator(
            "xpath=//*[contains(text(),'FC Start time')]"
            "/following::input[1]")
        wait_until(lambda: _fc_inp.first.input_value()
                   == _mmss(fc_t), timeout=30)

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
        page_drop(desk)
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
        # Polish phase 2 item 7: theme lives in App Settings
        # (gear), as an explicit mode choice.
        # Polish round 3: App Settings is a slide over dock
        # now (HUNT-32), and this session is aged by the time
        # the dark pass runs; if the Dark button is not
        # actionable shortly after the gear click, reload
        # once and reopen (the suites' reload recovery).
        desk.locator('.psc-roast-gear-btn:visible').first.click()
        desk.wait_for_timeout(2500)
        try:
            desk.get_by_role('button', name='Dark',
                             exact=True).click(timeout=15000)
        except Exception:
            print('SUITE NOTE: reload recovery fired in v4 '
                  'dark pass (App Settings dock did not '
                  'present Dark); reloading and reopening')
            desk.reload(wait_until='networkidle', timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            desk.locator(
                '.psc-roast-gear-btn:visible').first.click()
            desk.wait_for_timeout(2500)
            desk.get_by_role('button', name='Dark',
                             exact=True).click()
        desk.wait_for_timeout(3000)
        desk.get_by_role('button', name='Close', exact=True).click()
        desk.wait_for_timeout(1000)
        desk.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-dark-desktop.png'))
        mob.reload(wait_until='networkidle')
        mob.wait_for_timeout(6000)
        dismiss(mob)
        mob.screenshot(path=os.path.join(
            SHOTS, 'roastery-v4-roast-dark-mobile.png'))
        check('no overlays in dark theme',
              overlays(desk) == 0 and overlays(mob) == 0)
        desk.locator('.psc-roast-gear-btn:visible').first.click()
        desk.wait_for_timeout(2500)
        desk.get_by_role('button', name='Light', exact=True).click()
        desk.wait_for_timeout(2000)
        desk.get_by_role('button', name='Close', exact=True).click()
        desk.wait_for_timeout(1000)

        browser.close()

    # ---- cleanup + log window ------------------------------------
    if batch_no:
        drain_pending()
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
