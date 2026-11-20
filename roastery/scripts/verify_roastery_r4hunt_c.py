#!/usr/bin/env python3
"""Polish round 4 hunt, part C: follow ups to part A.

- Restores the close events fixture batch 9919 from the
  snapshot taken during part B (part B deleted the
  original through the app), then inspects BatchDetail
  at 360px by in session navigation (part A's direct URL
  open hit a 400 error page, a harness artifact).
- Checks whether the gear is reachable on BatchDetail at
  360px, the header geometry, and the phase analysis and
  events timeline geometry.
- Cross session theme: does an already open session
  follow a ThemeMode change made elsewhere?
- App Settings dock geometry done properly: a real
  content element's rect before, during (slide frames),
  and after open and close at desktop.

Ends with the fixture deleted through the app delete
flow and the lab at the seeded baseline.
Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B
FIX = 9919
FAILS = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:170] if detail else ''), flush=True)
    if not cond:
        FAILS.append(name)


def note(msg):
    print('NOTE |', msg, flush=True)


def dismiss(page):
    """Dismiss the Maker 'Personal Use Only' agreement modal.

    Round 7 hunting: the modal is gone when its AGREE & CLOSE
    button is gone, so that is the check. The old form watched
    the 'Personal Use Only' text count, which never drops below
    1: the page footer carries a permanent
    <div class="secondary-message">Personal Use Only</div>, so
    after the modal closed every iteration found count 1 and
    spent 5 s waiting on a button that no longer exists, 30
    iterations, about 165 s per open_page (proven in the round
    7 delete repro, 2026-11-20). The modal itself closes on
    the first click in under a second; the page is live
    immediately after.
    """
    for _ in range(30):
        try:
            if page.get_by_text('AGREE & CLOSE').count() > 0:
                page.get_by_text('AGREE & CLOSE').first.click(
                    timeout=5000)
                page.wait_for_timeout(1200)
                if page.get_by_text('AGREE & CLOSE').count() == 0:
                    return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return page.get_by_text('AGREE & CLOSE').count() == 0


def open_page(ctx, path):
    pg = ctx.new_page()
    pg.goto(BASE + path, wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    dismiss(pg)
    pg.wait_for_timeout(1500)
    return pg


def shot(pg, name):
    try:
        pg.screenshot(path=os.path.join(SHOTS, name),
                      timeout=30000)
        print('shot', name, flush=True)
        return True
    except Exception as e:
        print('shot issue', name, str(e)[:90], flush=True)
        return False


def restore_fixture():
    if P.psql('SELECT COUNT(*) FROM batches WHERE '
              'batch_number = %d' % FIX) == '1':
        print('fixture already present', flush=True)
        return
    # Round 7: the snapshot used to live only in /tmp and a
    # VM replacement wiped it, failing C at startup. It now
    # lives in the lab dir (persistent); /tmp stays as a
    # fallback for older snapshots.
    snap_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'r4hunt_fixture_9919.json')
    if not os.path.exists(snap_path):
        snap_path = '/tmp/r4hunt_fixture_9919.json'
    snap = json.loads(open(snap_path).read())
    b = snap['batch']
    import subprocess
    pw = open('/home/hatch/workspace/ignition-lab/'
              '.roastery-pgpass').read().strip()
    env = dict(os.environ, PGPASSWORD=pw,
               PATH=os.environ['PATH']
               + ':/usr/lib/postgresql/16/bin')

    def run(sql):
        out = subprocess.run(
            ['psql', '-h', 'localhost', '-U', 'ignition',
             '-d', 'db', '-v', 'ON_ERROR_STOP=1', '-c', sql],
            capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr

    run("INSERT INTO batches (batch_number, roast_start, "
        "roast_end, bean_name, drop_temp_f, data) VALUES "
        "(%d, '%s', '%s', '%s', %s, '%s'::jsonb)" % (
            b['batch_number'], b['roast_start'], b['roast_end'],
            b['bean_name'].replace("'", "''"),
            b['drop_temp_f'],
            json.dumps(b['data']).replace("'", "''")))
    for s in snap['series']:
        def num(v):
            return 'NULL' if v is None else str(v)
        run("INSERT INTO batch_series (batch_number, "
            "t_offset_sec, bean_temp_f, rate_of_rise_f, "
            "fan_level, heat_level) VALUES (%d, %s, %s, %s, "
            "%s, %s)" % (FIX, num(s['t']), num(s['bt']),
                         num(s['ror']), num(s['fan']),
                         num(s['heat'])))
    print('fixture restored, series',
          P.psql('SELECT COUNT(*) FROM batch_series WHERE '
                 'batch_number = %d' % FIX), flush=True)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    restore_fixture()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------- 360 BatchDetail via navigation --------
        mob = browser.new_context(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver')
        mp = open_page(mob, '/log')
        rows = mp.locator('.ia_table__row')
        clicked = False
        for i in range(rows.count()):
            toks = rows.nth(i).inner_text().replace(
                ',', '').split()
            if str(FIX) in toks:
                rows.nth(i).click()
                clicked = True
                break
        check('fixture selectable at 360', clicked)
        mp.wait_for_timeout(1500)
        mp.get_by_role('button', name='Details').first.click(
            timeout=25000)
        mp.wait_for_timeout(5000)
        dismiss(mp)
        gear = mp.locator('.psc-roast-gear-btn:visible').count()
        print('gear buttons visible on detail at 360:', gear,
              flush=True)
        check('gear reachable on BatchDetail at 360',
              gear >= 1)
        shot(mp, 'r4hunt-detail-close-360-light.png')
        geo = mp.evaluate("""() => {
          const out = {doc: {
            sw: document.documentElement.scrollWidth,
            cw: document.documentElement.clientWidth}};
          out.tables = [...document.querySelectorAll(
            '[data-component="ia.display.table"]')].map(e => {
              const r = e.getBoundingClientRect();
              return {sw: e.scrollWidth, cw: e.clientWidth,
                      x: r.x, w: r.width};});
          const btns = [...document.querySelectorAll('button')]
            .filter(b => b.offsetParent !== null)
            .map(b => { const r = b.getBoundingClientRect();
              return {t: b.innerText.trim().slice(0, 18),
                      x: r.x, y: r.y, w: r.width, h: r.height};});
          out.buttons = btns.slice(0, 10);
          return out;
        }""")
        print('detail 360 geometry:', json.dumps(geo)[:800],
              flush=True)
        # dark via its own gear
        if gear >= 1:
            mp.locator('.psc-roast-gear-btn:visible').first.click()
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='Dark',
                           exact=True).click()
            mp.wait_for_timeout(2800)
            shot(mp, 'r4hunt-detail-close-360-dark.png')
            print('detail 360 container in dark:',
                  P.container_var(mp), flush=True)
            mp.get_by_role('button', name='Close',
                           exact=True).click()
            mp.wait_for_timeout(1000)
            mp.locator('.psc-roast-gear-btn:visible').first.click()
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='System',
                           exact=True).click()
            mp.wait_for_timeout(2500)
            mp.get_by_role('button', name='Close',
                           exact=True).click()
            mp.wait_for_timeout(800)
        # scroll the detail page for timeline + phase table
        mp.evaluate('window.scrollTo(0, 900)')
        mp.wait_for_timeout(1200)
        shot(mp, 'r4hunt-detail-close-360-scrolled.png')
        mob.close()

        # ---------- cross session theme -------------------
        P.write_tags([('[default]Roastery/AppSettings/ThemeMode',
                       'System')])
        ctx1 = browser.new_context(
            viewport={'width': 1000, 'height': 750},
            color_scheme='light')
        s1 = open_page(ctx1, '/')
        print('session1 container at System/light:',
              P.container_var(s1), flush=True)
        P.write_tags([('[default]Roastery/AppSettings/ThemeMode',
                       'Dark')])
        s1.wait_for_timeout(4500)
        cv_after = P.container_var(s1)
        print('session1 container after tag write to Dark:',
              cv_after, flush=True)
        note('cross session theme follow: container %s '
             '(#F4F4F4 light, #323232 dark)' % cv_after)
        shot(s1, 'r4hunt-xsession-after-dark-write.png')
        P.write_tags([('[default]Roastery/AppSettings/ThemeMode',
                       'System')])
        s1.wait_for_timeout(2000)
        ctx1.close()

        # ---------- dock geometry, desktop ----------------
        desk = browser.new_context(
            viewport={'width': 1360, 'height': 900},
            timezone_id='America/Denver')
        dp = open_page(desk, '/')

        def card_rect(page):
            return page.evaluate("""() => {
              const c = document.querySelector('.psc-roast-card');
              if (!c) return null;
              const r = c.getBoundingClientRect();
              return {x: r.x, y: r.y, w: r.width, h: r.height};
            }""")

        def dock_rect(page):
            return page.evaluate("""() => {
              const d = document.querySelector(
                '.docked-view-right');
              if (!d) return null;
              const r = d.getBoundingClientRect();
              return {x: r.x, y: r.y, w: r.width,
                      h: r.height, vw: window.innerWidth};
            }""")

        before = card_rect(dp)
        dp.locator('.psc-roast-gear-btn:visible').first.click()
        dp.wait_for_timeout(250)
        shot(dp, 'r4hunt-slide-frame1.png')
        dp.wait_for_timeout(350)
        shot(dp, 'r4hunt-slide-frame2.png')
        dp.wait_for_timeout(1600)
        shot(dp, 'r4hunt-slide-frame3-settled.png')
        during = card_rect(dp)
        dr = dock_rect(dp)
        print('card before/open:', before, during,
              'dock:', dr, flush=True)
        check('content does not shift when dock opens',
              before == during, '%s vs %s' % (before, during))
        dp.get_by_role('button', name='Close',
                       exact=True).click()
        dp.wait_for_timeout(400)
        shot(dp, 'r4hunt-slide-out-frame.png')
        dp.wait_for_timeout(1600)
        dr2 = dock_rect(dp)
        print('dock rect after close:', dr2, flush=True)
        check('dock fully off viewport after close',
              dr2 is None or dr2['x'] >= dr2['vw'], dr2)
        shot(dp, 'r4hunt-slide-closed.png')
        after = card_rect(dp)
        check('content back in place after close',
              before == after, '%s vs %s' % (before, after))
        desk.close()
        browser.close()

    # ---------- delete fixture + baseline -----------------
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport={'width': 1000, 'height': 750})
        pg = open_page(ctx, '/log')
        rows = pg.locator('.ia_table__row')
        for i in range(rows.count()):
            toks = rows.nth(i).inner_text().replace(
                ',', '').split()
            if str(FIX) in toks:
                rows.nth(i).click()
                break
        pg.wait_for_timeout(1500)
        pg.get_by_role('button', name='Delete').first.click(
            timeout=25000)
        pg.wait_for_timeout(1800)
        pg.get_by_role('button', name='Confirm Delete').first.click(
            timeout=25000)
        ok = P.wait_until(
            lambda: P.psql('SELECT COUNT(*) FROM batches WHERE '
                           'batch_number = %d' % FIX) == '0', 30)
        check('fixture deleted through the app again', bool(ok))
        browser.close()
    end = (int(P.psql('SELECT COUNT(*) FROM batches')),
           int(P.psql('SELECT COUNT(*) FROM batch_series')),
           int(P.psql('SELECT COUNT(*) FROM batch_events')))
    print('end counts:', end, flush=True)
    check('lab at seeded baseline after part C',
          end == (7, 101, 0), end)
    print('FAILS:', FAILS, flush=True)
    print('PART C DONE', flush=True)


if __name__ == '__main__':
    main()
