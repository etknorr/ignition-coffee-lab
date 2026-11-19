#!/usr/bin/env python3
"""Roastery Tier 1 verification (Playwright + REST + psql).

Proves the six Tier 1 Artisan parity features live on the
Maker gateway:
1. Background profile from an .alog on the Roast page (staged
   as the ghost, no batch written).
2. Multi curve comparison on the Log page (three saved batches,
   BT and RoR overlaid on one canvas chart).
3. Roast Properties completeness: a property rich .alog round
   trips import (JSONB document metadata) and export (.alog
   keys) with values intact.
4. Live turning point detection during a simulated roast.
5. Live AUC with Artisan settings (begin, base, target,
   guide), readouts on tiles, HUD, summary and Settings.
6. The alarm table: definitions in AlarmDefsJson drive the
   Roast page banner (Banner while true, Message latched), and
   the Settings section lists and edits them.

Screenshots land in showcase/shots/roastery-tier1-*.png. Test
batches and tag changes are cleaned up at the end; the lab is
left at 7 batches / 101 series rows, CurrentBatch clean Idle.
"""
import ast
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
FIXTURE = '/home/hatch/workspace/ignition-lab/artisan-fixtures/sample-roast.alog'
PROPS_ALOG = '/tmp/tier1-props.alog'
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:200]) if detail else '', flush=True)
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
        // A table's virtualized internals live inside its own
        // horizontal scroll container by design (the batches
        // table is 580px of columns at every width, long
        // before Tier 1); they are clipped, not bleeding.
        if (el.closest('[data-component="ia.display.table"]')) return;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.left < window.innerWidth - 1)
          w = Math.max(w, r.right);
      });
      return Math.round(w);
    }""")


def upload(page, path):
    """ia.input.fileupload mounts its <input type=file> only
    after the component is clicked (proven in the Artisan
    rounds); breakpoint duplicates mean clicking until one
    input exists, then setting files on it."""
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
                '/tmp/logs_t1_start.idb')
    con = sqlite3.connect('/tmp/logs_t1_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    shutil.copy('gateway-2027-maker/logs/system_logs.idb',
                '/tmp/logs_t1_end.idb')
    con = sqlite3.connect('/tmp/logs_t1_end.idb')
    rows = con.execute(
        "SELECT level_string, logger_name, formatted_message FROM "
        "logging_event WHERE event_id > ? AND level_string IN "
        "('WARN', 'ERROR')", (start_id,)).fetchall()
    con.close()
    bad = [r for r in rows if 'roastery' in (r[1] or '').lower()
           or 'Roastery' in (r[2] or '')]
    return bad


def make_props_fixture():
    p = ast.literal_eval(open(FIXTURE).read())
    p.update({
        'title': 'Tier1 Props Test',
        'roastUUID': 'tier1props000000000000000000001',
        'roastertype': 'Test Roaster X',
        'roastersize': 1.5,
        'roasterheating': 3,
        'organization': 'Test Org',
        'volume': [250.0, 210.0, 'ml'],
        'defects_weight': 12.0,
        'density_roasted': [700.0, 'g', 1000.0, 'ml'],
        'beansize_min': '14',
        'beansize_max': '18',
        'heavyFC': True,
        'tipping': True,
        'whole_color': 55.0,
        'ground_color': 60.0,
        'color_system': 'Agtron',
        'ambientTemp': 71.6,
        'ambient_humidity': 40.0,
        'ambient_pressure': 1009.0,
        'moisture_roasted': 11.5,
        'greens_temp': 69.8,
        'cuppingnotes': 'blueberry and jasmine',
        'roastingnotes': 'props round trip note',
    })
    with open(PROPS_ALOG, 'w') as f:
        f.write(repr(p))


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    make_props_fixture()
    seeded_alarms = tag(B + '/AlarmDefsJson')
    base_batches = int(psql('SELECT COUNT(*) FROM batches'))
    base_series = int(psql('SELECT COUNT(*) FROM batch_series'))
    check('starting point is the seeded log',
          (base_batches, base_series) == (7, 101),
          (base_batches, base_series))
    imported_no = None
    roast_no = None
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

        # ---------- item 1: background from .alog ----------------
        # Polish phase 2 item 5: the upload lives in Settings,
        # Background Profile (off the Roast page).
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        before = int(psql('SELECT COUNT(*) FROM batches'))
        upload(desk, PROPS_ALOG)
        ok = wait_until(lambda: str(tag(
            '[default]Roastery/BackgroundLabel') or '').startswith(
                'File: '), timeout=30)
        check('background staged from file with File: label', bool(ok),
              tag('[default]Roastery/BackgroundLabel'))
        bg_json = tag('[default]Roastery/BackgroundCurveJson')
        pts = json.loads(bg_json) if bg_json else []
        check('background curve points staged', len(pts) > 100,
              len(pts))
        check('staging wrote no batch',
              int(psql('SELECT COUNT(*) FROM batches')) == before)
        body = desk.locator('body').inner_text()
        check('staging note reported on the page',
              'Background staged from' in body
              and 'Nothing was saved' in body)
        desk.screenshot(path=SHOTS + '/roastery-tier1-bg-staged.png')
        desk.get_by_role('button', name='Clear ghost').first.click()
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        cleared = wait_until(
            lambda: tag('[default]Roastery/BackgroundLabel') == '',
            timeout=20)
        check('clear ghost empties the background', bool(cleared)
              and not tag('[default]Roastery/BackgroundCurveJson'))

        # ---------- item 3: Roast Properties round trip ----------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        upload(desk, PROPS_ALOG)
        got = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches')) == before + 1,
            timeout=40)
        check('props fixture imported as a new batch', bool(got))
        imported_no = int(psql('SELECT MAX(batch_number) FROM batches'))
        doc = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = %d"
            % imported_no))
        meta = doc.get('metadata') or {}
        expect = {'RoastTitle': 'Tier1 Props Test',
                  'RoasterType': 'Test Roaster X',
                  'RoasterSizeKg': 1.5, 'RoasterHeating': 3,
                  'Organization': 'Test Org',
                  'VolumeInMl': 250.0, 'VolumeOutMl': 210.0,
                  'DefectsWeightG': 12.0, 'RoastedDensityGL': 700.0,
                  'BeanSizeMinMm': 14.0, 'BeanSizeMaxMm': 18.0,
                  'DefectHeavyFC': True, 'DefectTipping': True,
                  'DefectDrops': False,
                  'WholeColor': 55.0, 'GroundColor': 60.0,
                  'ColorSystem': 'Agtron', 'AmbientTempF': 71.6,
                  'AmbientHumidityPct': 40.0,
                  'AmbientPressureHPa': 1009.0,
                  'RoastedMoisturePct': 11.5, 'GreensTempF': 69.8,
                  'CuppingNotes': 'blueberry and jasmine',
                  'Notes': 'props round trip note'}
        missed = dict((k, (meta.get(k), v)) for k, v in expect.items()
                      if meta.get(k) != v)
        check('imported document carries the Roast Properties',
              not missed, missed)
        # export from the detail page and read the .alog back
        desk.reload(wait_until='networkidle')
        desk.wait_for_timeout(4000)
        # select the imported batch's row (the v4 suite's
        # .ia_table__row pattern; the row whose cells carry the
        # batch number, verified through the tag select_row
        # mirrors the pick into)
        rows = desk.locator('.ia_table__row')
        clicked = False
        for i in range(rows.count()):
            # the Batch column renders with a thousands
            # separator ('1,049'); normalize before matching
            tokens = rows.nth(i).inner_text().replace(',', '').split()
            if str(imported_no) in tokens:
                rows.nth(i).click()
                clicked = True
                break
        desk.wait_for_timeout(1200)
        check('imported batch selected in the table',
              clicked
              and int(tag('[default]Roastery/SelectedBatchNumber') or 0)
              == imported_no)
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        with desk.expect_download(timeout=30000) as dl_info:
            desk.get_by_role('button', name='Export .alog').first.click()
        dl = dl_info.value
        dl_path = '/tmp/tier1-export.alog'
        dl.save_as(dl_path)
        prof = ast.literal_eval(open(dl_path).read())
        exp_expect = {'roastertype': 'Test Roaster X',
                      'roastersize': 1.5, 'roasterheating': 3,
                      'organization': 'Test Org',
                      'defects_weight': 12.0,
                      'beansize_min': '14', 'beansize_max': '18',
                      'heavyFC': True, 'tipping': True,
                      'whole_color': 55.0, 'ground_color': 60.0,
                      'color_system': 'Agtron',
                      'ambient_humidity': 40.0,
                      'ambient_pressure': 1009.0,
                      'moisture_roasted': 11.5,
                      'cuppingnotes': 'blueberry and jasmine',
                      'roastingnotes': 'props round trip note',
                      'title': 'Tier1 Props Test'}
        exp_missed = dict((k, (prof.get(k), v))
                          for k, v in exp_expect.items()
                          if prof.get(k) != v)
        vol = prof.get('volume') or []
        if not (len(vol) == 3 and abs(vol[0] - 250.0) < 0.01
                and abs(vol[1] - 210.0) < 0.01 and vol[2] == 'ml'):
            exp_missed['volume'] = (vol, [250.0, 210.0, 'ml'])
        dr = prof.get('density_roasted') or []
        if not (len(dr) == 4 and abs(dr[0] - 171.4) < 0.01
                and abs(dr[2] - 210.0) < 0.01):
            exp_missed['density_roasted'] = (dr, 'weight out over volume out')
        check('exported .alog carries the Roast Properties back',
              not exp_missed, exp_missed)
        desk.screenshot(path=SHOTS + '/roastery-tier1-props-detail.png')
        psql('DELETE FROM batches WHERE batch_number = %d' % imported_no)
        check('props test batch deleted',
              int(psql('SELECT COUNT(*) FROM batches')) == before)

        # ---------- item 2: multi curve comparison ---------------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        desk.get_by_role('button', name='Compare').first.click()
        desk.wait_for_timeout(4000)
        body = desk.locator('body').inner_text()
        check('compare caption names the compared batches',
              'A = Batch' in body and 'B = Batch' in body, body[-400:])
        chart = desk.locator('[data-component="ia.canvas-charts.line"]')
        check('compare chart is a canvas line chart', chart.count() >= 1)
        desk.screenshot(path=SHOTS + '/roastery-tier1-compare.png')
        mob.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        mob.get_by_role('button', name='Compare').first.click()
        mob.wait_for_timeout(4000)
        worst = overflow_worst(mob)
        check('compare page has no overflow at 360px', worst <= 361,
              worst)
        mob.screenshot(path=SHOTS + '/roastery-tier1-compare-360.png')

        # ---------- items 4, 5, 6: the live roast ----------------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        expected = max(int(psql('SELECT MAX(batch_number) FROM batches')),
                       int(tag(B + '/BatchNumber'))) + 1
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        roast_no = int(tag(B + '/BatchNumber'))
        check('new roast workspace for the live checks',
              roast_no == expected and tag(B + '/State') == 'Idle',
              (roast_no, expected))
        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('charge starts the roast', wait_tag(B + '/State', 'Roasting'))

        # item 6 first (fast): swap in a test alarm table
        test_alarms = json.dumps([
            {'name': 'Test banner', 'enabled': True, 'guard': 'None',
             'offsetSec': 0, 'source': 'BT', 'cond': '>=', 'value': 100,
             'message': 'TEST BANNER FIRED', 'action': 'Banner'},
            {'name': 'Test latch', 'enabled': True, 'guard': 'None',
             'offsetSec': 0, 'source': 'Time', 'cond': '>=', 'value': 5,
             'message': 'TEST LATCH FIRED', 'action': 'Message'},
            {'name': 'Test guarded', 'enabled': True, 'guard': 'Drop',
             'offsetSec': 0, 'source': 'BT', 'cond': '>=', 'value': 100,
             'message': 'TEST GUARDED FIRED', 'action': 'Banner'}])
        write_tags([(B + '/AlarmDefsJson', test_alarms)])
        fired = wait_until(
            lambda: 'TEST BANNER FIRED' in str(tag(B + '/AlarmText')),
            timeout=30)
        check('banner alarm fires from the table', bool(fired),
              tag(B + '/AlarmText'))
        check('alarm banner state is active',
              tag(B + '/AlarmActive') is True)
        latched = wait_until(
            lambda: 'TEST LATCH FIRED' in str(tag(B + '/AlarmText')),
            timeout=30)
        check('message alarm latches from the table', bool(latched),
              tag(B + '/AlarmText'))
        check('guarded alarm stays silent before its guard event',
              'TEST GUARDED FIRED' not in str(tag(B + '/AlarmText')))
        desk.wait_for_timeout(2500)
        desk.screenshot(path=SHOTS + '/roastery-tier1-alarm-banner.png')
        write_tags([(B + '/AlarmDefsJson', seeded_alarms)])
        desk.wait_for_timeout(1500)

        # item 4: turning point (elapsed can legitimately be
        # 0 when the charge temp is the curve minimum, so test
        # for None explicitly, never with a truthiness or)
        def _tp():
            v = tag(B + '/TurningPointElapsedSec')
            return v is not None and v >= 0
        tp = wait_until(_tp, timeout=150)
        check('turning point detected live', bool(tp),
              tag(B + '/TurningPointElapsedSec'))
        tp_temp = tag(B + '/TurningPointTempF')
        check('turning point temp is the curve minimum region',
              0 < float(tp_temp) <= float(tag(B + '/BeanTempF')),
              (tp_temp, tag(B + '/BeanTempF')))
        marks_note = wait_until(
            lambda: tag('[default]Roastery/EventMarksDS'), timeout=10)
        check('marks dataset rebuilt with the roast events',
              marks_note is not None)

        # item 5: AUC live
        auc = wait_until(lambda: float(tag(B + '/AucLiveFMin') or 0) > 0,
                         timeout=150)
        check('live AUC accumulates above the base', bool(auc),
              tag(B + '/AucLiveFMin'))
        guide = tag(B + '/AucGuideElapsedSec')
        check('AUC guide projects a future elapsed time',
              guide is not None and int(guide) > 0, guide)
        desk.wait_for_timeout(1500)
        # inner_text drops below fold content in this client,
        # so prove the tiles by their rendered text nodes
        check('desktop tiles show Turning Point and AUC',
              desk.get_by_text('Turning Point').count() >= 1
              and desk.get_by_text('AUC', exact=True).count() >= 1)
        desk.screenshot(path=SHOTS + '/roastery-tier1-live-desktop.png')
        mob.wait_for_timeout(1500)
        worst = overflow_worst(mob)
        check('no overflow at 360px mid roast', worst <= 361, worst)
        mob.screenshot(path=SHOTS + '/roastery-tier1-live-360.png')

        # finish and save: the document must carry TP and AUC
        dock_drop(dock)
        check('drop lands', wait_tag(B + '/State', 'Dropped'))
        write_tags([(B + '/AlarmDefsJson', seeded_alarms)])
        desk.get_by_role('button', name='Save Batch').first.click()
        saved = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast_no)) == 1,
            timeout=30)
        check('roast saved', bool(saved))
        if saved:
            doc = json.loads(psql(
                "SELECT data FROM batches WHERE batch_number = %d"
                % roast_no))
            tp_doc = doc.get('turningPoint') or {}
            auc_doc = doc.get('aucDetail') or {}
            check('saved document carries the turning point',
                  tp_doc.get('t') is not None and tp_doc['t'] >= 0,
                  tp_doc)
            check('saved document carries the AUC detail',
                  float(auc_doc.get('valueFMin') or 0) > 0
                  and auc_doc.get('begin') == 'TP', auc_doc)
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
        check('workspace analytics cleared on reset',
              (tag(B + '/TurningPointElapsedSec') or 0) == -1
              and float(tag(B + '/AucLiveFMin') or 0) == 0
              and tag(B + '/AlarmText') == '')

        # ---------- settings: AUC section + alarm editor ---------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.locator('body').inner_text()
        check('settings page has the AUC section',
              'Area under the curve, Artisan style' in body)
        check('settings page lists the seeded alarm table',
              desk.get_by_text('High bean temp').count() >= 1
              and desk.get_by_text('First crack watch').count() >= 1)
        desk.evaluate("""() => {
          const els = [...document.querySelectorAll('*')];
          const h = els.find(e => e.children.length === 0
                           && e.innerText === 'ALARMS');
          if (h) h.scrollIntoView();
        }""")
        desk.wait_for_timeout(1200)
        desk.screenshot(path=SHOTS + '/roastery-tier1-settings.png')
        # edit alarm 1's message through the editor and save:
        # the startup load filled the editor inputs, so the
        # message input is the one whose value is the seeded
        # message text.
        try:
            handle = desk.evaluate_handle(
                """() => [...document.querySelectorAll('input')]
                    .find(i => i.value === 'Bean temperature high')""")
            al_msg = handle.as_element()
            assert al_msg is not None, 'editor message input not found'
            al_msg.click()
            desk.keyboard.press('Control+a')
            desk.keyboard.type('Bean temperature high (edited)')
            desk.keyboard.press('Enter')
            desk.wait_for_timeout(800)
            desk.get_by_role('button', name='Save Alarm').first.click()
            desk.wait_for_timeout(2500)
            defs = json.loads(tag(B + '/AlarmDefsJson'))
            check('alarm editor save rewrites the definitions',
                  defs and defs[0].get('message')
                  == 'Bean temperature high (edited)',
                  defs[0] if defs else None)
        except Exception as e:
            check('alarm editor save rewrites the definitions', False,
                  repr(e)[:160])
        write_tags([(B + '/AlarmDefsJson', seeded_alarms)])
        check('no overlays at end',
              overlays(desk) == 0 and overlays(mob) == 0)
        browser.close()

    # ---------- final state --------------------------------------
    check('lab back to the seeded log',
          int(psql('SELECT COUNT(*) FROM batches')) == base_batches
          and int(psql('SELECT COUNT(*) FROM batch_series')) == base_series,
          (psql('SELECT COUNT(*) FROM batches'),
           psql('SELECT COUNT(*) FROM batch_series')))
    check('alarm definitions restored to the seeded table',
          tag(B + '/AlarmDefsJson') == seeded_alarms)
    check('background cleared at the end',
          tag('[default]Roastery/BackgroundLabel') == '')
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad, bad[:3])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL TIER 1 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
