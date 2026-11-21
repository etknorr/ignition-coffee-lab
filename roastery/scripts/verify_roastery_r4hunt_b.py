#!/usr/bin/env python3
"""Polish round 4 hunt, part B (HUNT-37 onward).

Scope 3: the press ring under a simulator seek. Charge
with Fan 1 / Heat 9 (sim at about 1.38x), stamp the dock
prerequisites, Drop when the program counter passes 350
(around 6 program minutes, drop temp near 390 F, cooling
target near program 737, so the seek runs for seconds),
then press Cool and Fan +1 DURING the seek. Every press
must land exactly one batch_events row and the state
machine must stay consistent.

Scope 4: fresh eyes on Log (both column sets, stub
marker, compare staging), BatchDetail (seeded batch:
header, exports, phase analysis), Settings sections
(Alarms editor, Custom Events, Targets designer,
Background staging), and toasts in both themes at 360px.

Ends by deleting the part A fixture batch 9919 through
the app delete flow and restoring the seeded baseline:
7 batches / 101 series / 0 events, workspace Idle.

Run with wsvenv python from ~/workspace/ignition-lab.
Round 7: the toast checks now wait for 'Background
failed', the message the Settings background route
actually toasts (artisan.stage_background_upload);
'Import failed' is the Log page import route's
message, so the old needle could never match here.
The desktop all-columns toggle block is removed
(the toggle lives in the phone instance only; on
desktop the single button is not visible). The
FileUpload status modal is dismissed with an outside
tap after each upload, or it blocks the gear and
theme buttons behind its fullViewOverlay. The error
toast itself is waited out before each gear click:
it sits top center for about 5 s over the gear and
intercepts the click.
Round 8 (HUNT-58): part B verifies its precondition
at start (fixture 9919 present with its full series)
and re-creates it from the persistent lab-dir
snapshot when a VM replacement wiped it between
parts A and B, so the delete flow at the end no
longer fails on the missing fixture and no manual
part A rerun is needed.
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


def toast_texts(page):
    loc = page.locator('.Toastify__toast')
    out = []
    for i in range(loc.count()):
        try:
            out.append(loc.nth(i).inner_text())
        except Exception:
            pass
    return out


def wait_toast(page, needle, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(needle in t for t in toast_texts(page)):
            return True
        page.wait_for_timeout(500)
    return False


def wait_toast_gone(page, timeout=10):
    """Clear any Toastify toast. AutoClose is 5 s but the
    timer pauses while the pointer hovers the toast, so a
    toast the mouse rests on never leaves on its own
    (proven in the r4hunt_b reruns: the gear click kept
    hitting the error toast after a 10 s wait). Poll
    briefly for the auto-close, then click the toast
    itself (closeOnClick) and wait for it to go."""
    t0 = time.time()
    clicked = False
    while time.time() - t0 < timeout:
        if page.locator('.Toastify__toast').count() == 0:
            return True
        if time.time() - t0 > 3 and not clicked:
            clicked = True
            try:
                page.locator('.Toastify__toast').first.click(
                    timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(500)
    return page.locator('.Toastify__toast').count() == 0


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


def rows_for(batch_no):
    out = P.psql("SELECT action FROM batch_events WHERE "
                 "batch_number = %d ORDER BY id" % batch_no)
    return [r for r in out.splitlines() if r]


def main():
    os.makedirs(SHOTS, exist_ok=True)
    # HUNT-58: the delete flow at the end needs fixture 9919,
    # which part A created. A VM replacement between A and B
    # restores the database to the reseeded baseline and wipes
    # it (round 7 first-pass failure 2). Verify the
    # precondition now and re-create the fixture from the
    # lab-dir snapshot when it is missing or partial, so B
    # passes without a manual part A rerun.
    RF.ensure_fixture()
    print('counts at B start:',
          P.psql('SELECT COUNT(*) FROM batches'),
          P.psql('SELECT COUNT(*) FROM batch_series'),
          P.psql('SELECT COUNT(*) FROM batch_events'),
          flush=True)
    P.probe_setup()
    try:
        # ================= scope 3: seek presses ==========
        P.probe('reset')
        P.wait_until(lambda: P.tag(B + '/State') == 'Idle', 30)
        P.write_tags([(B + '/FanLevel', 1), (B + '/HeatLevel', 9),
                      (B + '/DispAxisFormat', 'm:ss'),
                      ('[default]Roastery/AppSettings/ThemeMode',
                       'System')])
        P.probe('updatedock')
        time.sleep(3)
        batch_no = int(P.tag(B + '/BatchNumber'))
        print('seek roast batch:', batch_no, flush=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            phone = browser.new_context(
                viewport={'width': 360, 'height': 740},
                timezone_id='America/Denver')
            pg = open_page(phone, '/')
            dock = pg.locator('.psc-roast-controldock')

            def press(name):
                c0 = int(P.tag(B + '/ActionCounter') or 0)
                dock.get_by_role('button', name=name).click(
                    timeout=25000)
                ok = P.wait_until(
                    lambda: int(P.tag(B + '/ActionCounter') or 0)
                    > c0, 12)
                print('press %-10s bump=%s state=%s seeking=%s '
                      'counter(sim)=%s' % (
                          name, bool(ok), P.tag(B + '/State'),
                          P.tag(B + '/SimSeeking'),
                          P.tag('[default]Roastery/'
                                'SimProgramCounter')), flush=True)
                return bool(ok)

            def press_fan_plus():
                c0 = int(P.tag(B + '/ActionCounter') or 0)
                dock.locator('button', has_text='+').first.click(
                    timeout=25000)
                ok = P.wait_until(
                    lambda: int(P.tag(B + '/ActionCounter') or 0)
                    > c0, 12)
                print('press Fan +1   bump=%s state=%s '
                      'seeking=%s fan=%s' % (
                          bool(ok), P.tag(B + '/State'),
                          P.tag(B + '/SimSeeking'),
                          P.tag(B + '/FanLevel')), flush=True)
                return bool(ok)

            counter0 = int(P.tag(B + '/ActionCounter') or 0)
            rows0 = len(rows_for(batch_no))
            press('Charge')
            check('seek roast charging',
                  P.wait_until(
                      lambda: P.tag(B + '/State') == 'Roasting',
                      20))
            for btn in ('Dry End', 'FC Start', 'FC End'):
                press(btn)
                pg.wait_for_timeout(400)
            ok = P.wait_until(
                lambda: int(P.tag(
                    '[default]Roastery/SimProgramCounter') or 0)
                >= 350, 480)
            check('program reached about 6 minutes', bool(ok),
                  'counter %s temp %s' % (
                      P.tag('[default]Roastery/SimProgramCounter'),
                      P.tag(B + '/BeanTempF')))
            press('Drop')
            check('dropped', P.wait_until(
                lambda: P.tag(B + '/State') == 'Dropped', 15))
            seeking = P.wait_until(
                lambda: bool(P.tag(B + '/SimSeeking')), 10)
            check('cooling seek is running after Drop',
                  bool(seeking),
                  'target %s counter %s' % (
                      P.tag(B + '/SimSeekTargetSec'),
                      P.tag('[default]Roastery/SimProgramCounter')))
            # Presses DURING the seek.
            press('Cool')
            check('Cool during seek lands Cooling',
                  P.tag(B + '/State') in ('Cooling', 'Complete'),
                  P.tag(B + '/State'))
            still = bool(P.tag(B + '/SimSeeking'))
            print('seek still running after Cool:', still,
                  flush=True)
            if still:
                press_fan_plus()
            shot(pg, 'r4hunt-seek-during-360.png')
            landed = P.wait_until(
                lambda: not P.tag(B + '/SimSeeking'), 120)
            check('seek lands after mid seek presses',
                  bool(landed),
                  'counter %s state %s' % (
                      P.tag('[default]Roastery/SimProgramCounter'),
                      P.tag(B + '/State')))
            shot(pg, 'r4hunt-seek-landed-360.png')
            if P.tag(B + '/State') == 'Cooling':
                press('Finish')
            check('complete after seek flow', P.wait_until(
                lambda: P.tag(B + '/State') == 'Complete', 25),
                P.tag(B + '/State'))
            press('Reset / New Roast')
            check('reset to Idle', P.wait_until(
                lambda: P.tag(B + '/State') == 'Idle', 25))
            # Quiesce, then the capture invariant.
            last = [-1, -1, -1]
            deadline = time.time() + 90
            while time.time() < deadline:
                n = len(rows_for(batch_no))
                last = last[1:] + [n]
                if last[0] == last[1] == last[2] and last[0] > 0:
                    break
                time.sleep(2)
            counter1 = int(P.tag(B + '/ActionCounter') or 0)
            rows = rows_for(batch_no)[rows0:]
            print('seek roast rows:', rows, flush=True)
            print('bumps:', counter1 - counter0, 'rows:',
                  len(rows), flush=True)
            expected = ['Charge', 'Dry End', 'First Crack Start',
                        'First Crack End', 'Drop', 'Cool']
            if still:
                expected.append('Fan +1')
            expected += ['Finish', 'Reset']
            extras = list(rows)
            missing = []
            for a in expected:
                if a in extras:
                    extras.remove(a)
                else:
                    missing.append(a)
            check('every seek roast press landed exactly once',
                  not missing and len(rows) == counter1 - counter0,
                  'missing %s extras %s' % (missing, extras))
            check('mid seek presses each exactly one row',
                  rows.count('Drop') == 1
                  and rows.count('Cool') == 1
                  and (not still or rows.count('Fan +1') == 1),
                  rows)
            phone.close()

            # ================= scope 4: fresh eyes =========
            desk = browser.new_context(
                viewport={'width': 1360, 'height': 900},
                timezone_id='America/Denver')
            dp = open_page(desk, '/log')
            shot(dp, 'r4hunt-log-desktop-default.png')
            body = dp.locator('body').inner_text()
            check('log stub marker visible on desktop',
                  '(stub)' in body)
            # No all-columns toggle on desktop: a live probe
            # (round 7) counts exactly one 'All columns'
            # button on /log at 1360px and it is not visible
            # (the toggle lives in the phone instance only;
            # desktop already shows every column). The old
            # block clicked it and timed out 15 s per run.
            # compare staging on desktop
            try:
                dp.get_by_role('button', name='Compare').first.click(
                    timeout=20000)
                dp.wait_for_timeout(4500)
                dismiss(dp)
                shot(dp, 'r4hunt-log-compare-desktop.png')
                cbody = dp.locator('body').inner_text()
                print('compare caption present:',
                      'compar' in cbody.lower(), flush=True)
            except Exception as e:
                note('compare issue: %s' % str(e)[:100])
            # BatchDetail of a seeded batch (1044)
            dp.goto(BASE + '/log', wait_until='domcontentloaded',
                    timeout=60000)
            dp.wait_for_timeout(6000)
            dismiss(dp)
            rows_loc = dp.locator('.ia_table__row')
            for i in range(rows_loc.count()):
                toks = rows_loc.nth(i).inner_text().replace(
                    ',', '').split()
                if '1044' in toks:
                    rows_loc.nth(i).click()
                    break
            dp.wait_for_timeout(1500)
            dp.get_by_role('button', name='Details').first.click(
                timeout=25000)
            dp.wait_for_timeout(5000)
            dismiss(dp)
            shot(dp, 'r4hunt-detail-seeded-desktop.png')
            dbody = dp.locator('body').inner_text()
            for needle in ('Export', 'Phase'):
                print('detail body has', needle, ':',
                      needle in dbody, flush=True)
            desk.close()

            mob = browser.new_context(
                viewport={'width': 360, 'height': 740},
                timezone_id='America/Denver')
            mp = open_page(mob, '/log')
            shot(mp, 'r4hunt-log-360-default.png')
            geo = mp.evaluate("""() => {
              const t = document.querySelector(
                '[data-component="ia.display.table"]');
              return t ? {sw: t.scrollWidth, cw: t.clientWidth}
                       : null;
            }""")
            print('log 360 table geometry:', geo, flush=True)
            try:
                mp.get_by_role('button',
                               name='All columns').first.click(
                                   timeout=15000)
                mp.wait_for_timeout(2500)
                shot(mp, 'r4hunt-log-360-allcols.png')
                geo2 = mp.evaluate("""() => {
                  const t = document.querySelector(
                    '[data-component="ia.display.table"]');
                  return t ? {sw: t.scrollWidth,
                              cw: t.clientWidth} : null;
                }""")
                print('log 360 allcols geometry:', geo2,
                      flush=True)
                mp.get_by_role('button',
                               name='Fewer columns').first.click(
                                   timeout=15000)
                mp.wait_for_timeout(1500)
            except Exception as e:
                note('log 360 toggle issue: %s' % str(e)[:100])
            try:
                mp.get_by_role('button', name='Compare').first.click(
                    timeout=20000)
                mp.wait_for_timeout(4500)
                dismiss(mp)
                shot(mp, 'r4hunt-log-compare-360.png')
            except Exception as e:
                note('compare 360 issue: %s' % str(e)[:100])

            # Settings fresh eyes at 360
            mp.goto(BASE + '/settings',
                    wait_until='domcontentloaded', timeout=60000)
            mp.wait_for_timeout(6000)
            dismiss(mp)
            shot(mp, 'r4hunt-settings-360-top.png')
            cards = mp.evaluate("""() => [...document
              .querySelectorAll('.psc-roast-card')].map(e => ({
                sw: e.scrollWidth, cw: e.clientWidth,
                sh: e.scrollHeight, ch: e.clientHeight}))""")
            print('settings 360 cards:', cards, flush=True)
            mp.evaluate('window.scrollTo(0, 1200)')
            mp.wait_for_timeout(1200)
            shot(mp, 'r4hunt-settings-360-mid.png')
            mp.evaluate('window.scrollTo(0, 2600)')
            mp.wait_for_timeout(1200)
            shot(mp, 'r4hunt-settings-360-low.png')
            # toast in Light: bad alog upload in Background
            with open('/tmp/r4hunt-bad1.alog', 'w') as f:
                f.write('this is not an alog file')
            try:
                upload(mp, '/tmp/r4hunt-bad1.alog')
                ok = wait_toast(mp, 'Background failed', 20)
                check('import failure toast fires in Light',
                      bool(ok), toast_texts(mp))
                shot(mp, 'r4hunt-toast-light-360.png')
            except Exception as e:
                note('toast light issue: %s' % str(e)[:100])
            # The FileUpload status stays open as a small
            # viewport modal over the page (round 7 probe:
            # the in-modal arrow does not close it); tap
            # outside it to close it before touching the
            # gear, or the Dark click is blocked by the
            # fullViewOverlay intercepting pointer events.
            if mp.locator('.component-modal-small-viewport'
                           ).count() > 0:
                mp.mouse.click(10, 60)
                mp.wait_for_timeout(1200)
            # Park the pointer off the toast: a hover pauses
            # its auto-close timer, so it would never leave.
            mp.mouse.move(180, 400)
            # The error toast itself sits over the gear for
            # about 5 s; wait it out before clicking.
            wait_toast_gone(mp)
            # toast in Dark
            mp.locator('.psc-roast-gear-btn:visible').first.click()
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='Dark',
                           exact=True).click()
            mp.wait_for_timeout(2800)
            mp.get_by_role('button', name='Close',
                           exact=True).click()
            mp.wait_for_timeout(1000)
            with open('/tmp/r4hunt-bad2.alog', 'w') as f:
                f.write('{"broken": true, "not": "an alog"}')
            try:
                upload(mp, '/tmp/r4hunt-bad2.alog')
                ok = wait_toast(mp, 'Background failed', 20)
                print('dark import toast:', bool(ok),
                      toast_texts(mp), flush=True)
                shot(mp, 'r4hunt-toast-dark-360.png')
            except Exception as e:
                note('toast dark issue: %s' % str(e)[:100])
            # Close the upload modal again before the gear.
            if mp.locator('.component-modal-small-viewport'
                           ).count() > 0:
                mp.mouse.click(10, 60)
                mp.wait_for_timeout(1200)
            # Park the pointer off the toast: a hover pauses
            # its auto-close timer, so it would never leave.
            mp.mouse.move(180, 400)
            wait_toast_gone(mp)
            mp.locator('.psc-roast-gear-btn:visible').first.click()
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='System',
                           exact=True).click()
            mp.wait_for_timeout(2500)
            mp.get_by_role('button', name='Close',
                           exact=True).click()
            mp.wait_for_timeout(800)

            # ---- delete fixture 9919 through the app ------
            mp.goto(BASE + '/log', wait_until='domcontentloaded',
                    timeout=60000)
            mp.wait_for_timeout(6000)
            dismiss(mp)
            rows_loc = mp.locator('.ia_table__row')
            clicked = False
            for i in range(rows_loc.count()):
                toks = rows_loc.nth(i).inner_text().replace(
                    ',', '').split()
                if str(FIX) in toks:
                    rows_loc.nth(i).click()
                    clicked = True
                    break
            check('fixture row selectable for delete', clicked)
            mp.wait_for_timeout(1500)
            mp.get_by_role('button', name='Delete').first.click(
                timeout=25000)
            mp.wait_for_timeout(2000)
            cbody = mp.locator('body').inner_text()
            idx = cbody.lower().find('delete batch')
            print('delete confirm text:',
                  cbody[max(0, idx):idx + 220].replace('\n', ' ')
                  if idx >= 0 else cbody[:300], flush=True)
            shot(mp, 'r4hunt-delete-confirm-360.png')
            mp.get_by_role('button',
                           name='Confirm Delete').first.click(
                               timeout=25000)
            ok = P.wait_until(
                lambda: P.psql('SELECT COUNT(*) FROM batches '
                               'WHERE batch_number = %d' % FIX)
                == '0', 30)
            check('fixture batch deleted through the app',
                  bool(ok))
            check('fixture series cascaded',
                  P.psql('SELECT COUNT(*) FROM batch_series '
                         'WHERE batch_number = %d' % FIX) == '0')
            check('fixture press rows cascaded (HUNT-35)',
                  P.psql('SELECT COUNT(*) FROM batch_events '
                         'WHERE batch_number = %d' % FIX) == '0')
            mob.close()
            browser.close()
    finally:
        for attempt in range(3):
            try:
                P.probe('reset')
            except Exception:
                pass
            try:
                P.drain_pending()
            except Exception:
                pass
            try:
                P.psql('DELETE FROM batch_events')
            except Exception:
                pass
            try:
                P.write_tags(
                    [(B + '/BatchNumber', 1042),
                     (B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                     (B + '/DispAxisFormat', 'm:ss'),
                     ('[default]Roastery/AppSettings/ThemeMode',
                      'System')])
            except Exception:
                pass
            if P.tag(B + '/State') == 'Idle':
                break
            time.sleep(3)
        P.probe_teardown()
    end = (int(P.psql('SELECT COUNT(*) FROM batches')),
           int(P.psql('SELECT COUNT(*) FROM batch_series')),
           int(P.psql('SELECT COUNT(*) FROM batch_events')))
    check('lab restored to seeded baseline',
          end == (7, 101, 0), end)
    print('end state: State=%s Batch=%s Fan=%s Heat=%s '
          'Theme=%s Fmt=%s Periscope=%s Seeking=%s Pause=%s'
          % (P.tag(B + '/State'), P.tag(B + '/BatchNumber'),
             P.tag(B + '/FanLevel'), P.tag(B + '/HeatLevel'),
             P.tag('[default]Roastery/AppSettings/ThemeMode'),
             P.tag(B + '/DispAxisFormat'),
             P.tag('[default]Roastery/AppSettings/'
                   'PeriscopeAvailable'),
             P.tag(B + '/SimSeeking'),
             P.tag('[default]Roastery/SimPause')), flush=True)
    print('FAILS:', FAILS, flush=True)
    print('PART B DONE', flush=True)


if __name__ == '__main__':
    main()
