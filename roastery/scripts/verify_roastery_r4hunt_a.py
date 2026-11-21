#!/usr/bin/env python3
"""Polish round 4 hunt, part A (HUNT-37 onward).

Scope 1: category axis charts mid roast with events close
together. A simulated roast stamps Dry End, Fan Boost,
FC Start, Drum Note and FC End about 2 s apart; the live
chart is inspected at desktop and 360px in Light and Dark,
and the saved batch (fixture 9919) is inspected on
BatchDetail the same way.

Scope 2: the App Settings slide over dock during the live
roast: open at desktop and 360px, switch System to Dark to
Light and back, confirm the chart recolors, the roast is
undisturbed, the dock closes cleanly, and nothing behind
it shifts.

Run with wsvenv python from ~/workspace/ignition-lab.
Leaves the fixture batch 9919 saved for part B; part B
deletes it through the app delete flow.
Round 7: the phone dock close check now accepts a dock
translated fully off the viewport as closed (a closed
Perspective dock stays in the DOM at x=420 on a 360px
screen); the mobile detail open now strips BASE from
dp.url (open_page prepends it, so the absolute URL made
a malformed request and the gateway answered 400).
Round 8 (HUNT-58): part A self-heals its own start (a
stale fixture 9919 or leftover press rows from a partial
A run, or a VM replacement in between, are cleaned with
the HUNT-53 press guard first, so the live roast can
re-create the fixture) and re-writes the lab-dir snapshot
right after the save, so parts B and C never depend on a
stale one-off snapshot file.
"""
import json
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P
import r4hunt_fixture as RF

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B
FIX = 9919
FAILS = []
NOTES = []


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:160] if detail else ''), flush=True)
    if not cond:
        FAILS.append(name)


def note(msg):
    print('NOTE |', msg, flush=True)
    NOTES.append(msg)


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


def dock_click(page, name):
    dock = page.locator('.psc-roast-controldock')
    c0 = int(P.tag(B + '/ActionCounter') or 0)
    dock.get_by_role('button', name=name).click(timeout=25000)
    ok = P.wait_until(
        lambda: int(P.tag(B + '/ActionCounter') or 0) > c0, 12)
    print('press %-10s bump=%s counter=%s state=%s' % (
        name, bool(ok), P.tag(B + '/ActionCounter'),
        P.tag(B + '/State')), flush=True)
    return bool(ok)


def chart_card_rect(page):
    return page.evaluate("""() => {
      const c = document.querySelector(
        '[data-component="ia.display.canvas-charts.line"]');
      if (!c) return null;
      const r = c.getBoundingClientRect();
      return {x: r.x, y: r.y, w: r.width, h: r.height};
    }""")


def dock_rect(page):
    return page.evaluate("""() => {
      const d = document.querySelector('.docked-view-right');
      if (!d) return null;
      const r = d.getBoundingClientRect();
      return {x: r.x, y: r.y, w: r.width, h: r.height,
              vw: window.innerWidth};
    }""")


def overflow(page):
    return page.evaluate("""() => ({
      sw: document.documentElement.scrollWidth,
      cw: document.documentElement.clientWidth,
      sh: document.documentElement.scrollHeight,
      ch: document.documentElement.clientHeight})""")


def main():
    os.makedirs(SHOTS, exist_ok=True)
    # HUNT-58: a rerun after a partial A (or a VM replacement
    # that left a stale fixture plus press rows) must start
    # clean, or the live save refuses the duplicate batch
    # number. The guard drains and clears the press ring
    # before any rows are deleted, so nothing resurrects.
    RF.ensure_clean_baseline()
    base = (int(P.psql('SELECT COUNT(*) FROM batches')),
            int(P.psql('SELECT COUNT(*) FROM batch_series')),
            int(P.psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at seeded baseline', base == (7, 101, 0),
          base)
    P.probe_setup()
    try:
        P.probe('reset')
        P.wait_until(lambda: P.tag(B + '/State') == 'Idle', 30)
        P.write_tags([(B + '/BatchNumber', FIX),
                      (B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                      (B + '/DispAxisFormat', 'm:ss'),
                      # Polish round 6: slot 2 ships unnamed,
                      # so name it explicitly for this close
                      # events roast, then clear it again below.
                      (B + '/CustomEvent2Name', 'Drum Note'),
                      ('[default]Roastery/AppSettings/ThemeMode',
                       'System')])
        P.probe('updatedock')
        time.sleep(3)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            phone = browser.new_context(
                viewport={'width': 360, 'height': 740},
                timezone_id='America/Denver')
            pg = open_page(phone, '/')
            desk = browser.new_context(
                viewport={'width': 1360, 'height': 900},
                timezone_id='America/Denver')
            dp = open_page(desk, '/')

            # ---------- scope 1: close events ----------
            check('charge starts roast',
                  dock_click(pg, 'Charge')
                  and P.wait_until(
                      lambda: P.tag(B + '/State') == 'Roasting',
                      20))
            pg.wait_for_timeout(5000)
            for btn in ('Dry End', 'Fan Boost', 'FC Start',
                        'Drum Note', 'FC End'):
                dock_click(pg, btn)
                pg.wait_for_timeout(600)
            ev = {}
            for m in ('DryEndElapsedSec',
                      'FirstCrackStartElapsedSec',
                      'FirstCrackEndElapsedSec'):
                ev[m] = P.tag(B + '/' + m)
            print('event elapsed shadows:', ev, flush=True)
            span = (ev['FirstCrackEndElapsedSec'] or 0) - \
                (ev['DryEndElapsedSec'] or 0)
            check('events really are close together',
                  0 <= span <= 12, 'dry-to-fcend span %ss' % span)
            try:
                ref = json.loads(P.probe('reflines'))
                vis = [(i.get('value'),
                        (i.get('label') or {}).get('text'),
                        (i.get('label') or {}).get('visible'))
                       for i in ref]
                print('reflines (desktop fn):', vis, flush=True)
                labeled = [v for v in vis if v[2]]
                check('close events: exactly one desktop label '
                      'survives the 55s gap',
                      len(labeled) == 1, labeled)
                check('close events: every event keeps its line',
                      len(vis) >= 6, '%d lines' % len(vis))
            except Exception as e:
                note('reflines probe failed: %s' % str(e)[:100])
            pg.wait_for_timeout(6000)
            dp.wait_for_timeout(1500)
            shot(dp, 'r4hunt-close-live-desktop-light.png')
            shot(pg, 'r4hunt-close-live-360-light.png')
            print('overflow phone mid roast:', overflow(pg),
                  flush=True)
            print('overflow desk mid roast:', overflow(dp),
                  flush=True)

            # ---------- scope 2: App Settings mid roast ----
            rect_before = chart_card_rect(dp)
            cnt_before = int(P.tag(B + '/ActionCounter') or 0)
            dp.locator('.psc-roast-gear-btn:visible').first.click()
            dp.wait_for_timeout(1800)
            dr = dock_rect(dp)
            print('appsettings dock rect desktop:', dr,
                  flush=True)
            check('dock opens at desktop mid roast',
                  dr is not None and dr['w'] > 300, dr)
            shot(dp, 'r4hunt-appsettings-desktop-open.png')
            rect_open = chart_card_rect(dp)
            print('chart rect before/open:', rect_before,
                  rect_open, flush=True)
            check('content behind dock does not shift (cover)',
                  rect_before == rect_open,
                  '%s vs %s' % (rect_before, rect_open))
            # theme walk: Dark, Light, System, Dark
            for mode in ('Dark', 'Light', 'System', 'Dark'):
                dp.get_by_role('button', name=mode,
                               exact=True).click()
                dp.wait_for_timeout(2800)
                tm = P.tag('[default]Roastery/AppSettings/'
                           'ThemeMode')
                cv = P.container_var(dp)
                print('theme ->', mode, 'tag', tm,
                      'container', cv, flush=True)
                check('theme switch lands: ' + mode,
                      tm == mode, tm)
                if mode == 'Dark':
                    shot(dp, 'r4hunt-close-live-desktop-dark.png')
                if mode == 'Light':
                    shot(dp, 'r4hunt-appsettings-desktop-light.png')
            check('roast undisturbed by theme walk',
                  P.tag(B + '/State') == 'Roasting'
                  and int(P.tag(B + '/ActionCounter') or 0)
                  == cnt_before,
                  'state %s counter %s (was %s)' % (
                      P.tag(B + '/State'),
                      P.tag(B + '/ActionCounter'), cnt_before))
            # phone dock at 360 in Dark
            pg.locator('.psc-roast-gear-btn:visible').first.click()
            pg.wait_for_timeout(1800)
            mdr = dock_rect(pg)
            print('appsettings dock rect 360:', mdr, flush=True)
            check('dock at 360 does not exceed viewport',
                  mdr is not None and mdr['w'] <= 361
                  and mdr['x'] >= -1, mdr)
            shot(pg, 'r4hunt-appsettings-360-dark.png')
            shot(pg, 'r4hunt-close-live-360-dark.png')
            pg.get_by_role('button', name='Close',
                           exact=True).click()
            pg.wait_for_timeout(1500)
            # A closed Perspective dock stays in the DOM,
            # translated off the viewport (x=420, w=360 on a
            # 360px screen); closed is None, zero width, or
            # fully outside the viewport.
            _dr = dock_rect(pg)
            check('phone dock closes cleanly',
                  _dr is None or _dr.get('w', 0) == 0
                  or _dr.get('x', 0) >= _dr.get('vw', 360)
                  or _dr.get('x', 0) + _dr.get('w', 0) <= 0,
                  _dr)
            dp.get_by_role('button', name='Close',
                           exact=True).click()
            dp.wait_for_timeout(1500)
            check('roast still running after dock closes',
                  P.tag(B + '/State') == 'Roasting')
            # back to System for the save + detail pass
            P.write_tags([('[default]Roastery/AppSettings/'
                           'ThemeMode', 'System')])
            dp.wait_for_timeout(2000)
            pg.wait_for_timeout(1000)

            # ---------- finish + save fixture --------------
            for btn in ('SC Start', 'SC End', 'Drop'):
                dock_click(pg, btn)
                pg.wait_for_timeout(500)
            check('dropped', P.wait_until(
                lambda: P.tag(B + '/State') == 'Dropped', 20))
            ok = P.wait_until(
                lambda: not P.tag(B + '/SimSeeking'), 90)
            print('seek landed:', bool(ok), flush=True)
            dock_click(pg, 'Cool')
            P.wait_until(lambda: P.tag(B + '/State')
                         in ('Cooling', 'Complete'), 20)
            dock_click(pg, 'Finish')
            check('complete', P.wait_until(
                lambda: P.tag(B + '/State') == 'Complete', 25),
                P.tag(B + '/State'))
            dp.wait_for_timeout(2500)
            dp.get_by_role('button', name='Save Batch').first.click(
                timeout=25000)
            ok = P.wait_until(
                lambda: P.psql('SELECT COUNT(*) FROM batches '
                               'WHERE batch_number = %d' % FIX)
                == '1', 30)
            check('fixture batch 9919 saved', bool(ok))
            doc = P.psql('SELECT data::text FROM batches WHERE '
                         'batch_number = %d' % FIX)
            try:
                d = json.loads(doc)
                evs = d.get('events') or {}
                print('saved events:',
                      {k: v.get('t') for k, v in evs.items()},
                      flush=True)
                print('saved phases:', d.get('phases'),
                      'total', d.get('totalSec'), flush=True)
            except Exception as e:
                note('saved doc parse: %s' % str(e)[:80])
            nser = P.psql('SELECT COUNT(*) FROM batch_series '
                          'WHERE batch_number = %d' % FIX)
            print('fixture series rows:', nser, flush=True)
            # HUNT-58: re-write the lab-dir snapshot from the
            # just-saved fixture, so parts B and C restore the
            # fixture this run actually created, never a stale
            # one-off file.
            snap = RF.snapshot_fixture()
            check('fixture snapshot written for parts B/C',
                  len(snap['series']) == int(nser),
                  '%d snapshot rows vs %s db rows'
                  % (len(snap['series']), nser))

            # ---------- BatchDetail for close events -------
            dp.goto(BASE + '/log', wait_until='domcontentloaded',
                    timeout=60000)
            dp.wait_for_timeout(6000)
            dismiss(dp)
            rows = dp.locator('.ia_table__row')
            clicked = False
            for i in range(rows.count()):
                toks = rows.nth(i).inner_text().replace(
                    ',', '').split()
                if str(FIX) in toks:
                    rows.nth(i).click()
                    clicked = True
                    break
            check('fixture row selectable in Log', clicked)
            dp.wait_for_timeout(1500)
            dp.get_by_role('button', name='Details').first.click(
                timeout=25000)
            dp.wait_for_timeout(5000)
            dismiss(dp)
            shot(dp, 'r4hunt-detail-close-desktop-light.png')
            # detail in Dark via the dock
            dp.locator('.psc-roast-gear-btn:visible').first.click()
            dp.wait_for_timeout(1500)
            dp.get_by_role('button', name='Dark',
                           exact=True).click()
            dp.wait_for_timeout(2800)
            shot(dp, 'r4hunt-detail-close-desktop-dark.png')
            dp.get_by_role('button', name='Close',
                           exact=True).click()
            dp.wait_for_timeout(1000)
            # 360 detail, dark then light
            mob = browser.new_context(
                viewport={'width': 360, 'height': 740},
                timezone_id='America/Denver')
            # open_page prepends BASE, so pass the path part
            # of dp.url, not the absolute URL (which made a
            # malformed request and a gateway 400 page).
            _detail_path = (dp.url[len(P.BASE):]
                            if dp.url.startswith(P.BASE)
                            else dp.url)
            mp = open_page(mob, _detail_path)
            shot(mp, 'r4hunt-detail-close-360-dark.png')
            geo = mp.evaluate("""() => {
              const out = {doc: {
                sw: document.documentElement.scrollWidth,
                cw: document.documentElement.clientWidth}};
              const tbls = [...document.querySelectorAll(
                '[data-component="ia.display.table"]')].map(e => ({
                sw: e.scrollWidth, cw: e.clientWidth}));
              out.tables = tbls;
              return out;
            }""")
            print('detail 360 geometry:', geo, flush=True)
            mp.locator('.psc-roast-gear-btn:visible').first.click()
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='Light',
                           exact=True).click()
            mp.wait_for_timeout(2800)
            shot(mp, 'r4hunt-detail-close-360-light.png')
            mp.get_by_role('button', name='Close',
                           exact=True).click()
            mp.wait_for_timeout(800)
            mob.close()
            phone.close()
            desk.close()
            browser.close()
    finally:
        # Restore theme + workspace defaults; the fixture
        # batch and its press rows stay for part B.
        try:
            P.write_tags([('[default]Roastery/AppSettings/'
                           'ThemeMode', 'System')])
        except Exception:
            pass
        try:
            P.probe('reset')
            P.wait_until(lambda: P.tag(B + '/State') == 'Idle',
                         30)
            P.write_tags([(B + '/BatchNumber', 1042),
                          (B + '/FanLevel', 5),
                          (B + '/HeatLevel', 5),
                          (B + '/CustomEvent2Name', '')])
        except Exception as e:
            print('cleanup issue', str(e)[:100], flush=True)
        P.probe_teardown()
    print('FAILS:', FAILS, flush=True)
    print('PART A DONE', flush=True)


if __name__ == '__main__':
    main()
