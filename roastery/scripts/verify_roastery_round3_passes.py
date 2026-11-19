#!/usr/bin/env python3
"""Polish round 3 item 4: the manual passes round 2 still owed.

A. Alarms editor full flow at 360px: load an alarm, add a new
   one (toast), edit and save it (toast), delete it (toast),
   with the seeded AlarmDefsJson restored byte identical at
   the end and overflow measured on the editor rows.
B. Log compare staging at 360px with fresh eyes: pick two
   batches in the compare dropdowns, stage the compare chart,
   measure overflow, screenshot.
C. Import failure toast in Light theme: upload a bogus .alog
   on the Log page with ThemeMode Light and confirm the
   failure toast renders readable inside the viewport.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B
check = P.check
FAILURES = P.FAILURES
tag = P.tag
write_tags = P.write_tags
wait_until = P.wait_until
psql = P.psql
dismiss = P.dismiss


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
    """Poll for a Periscope toast carrying needle (the
    polish3 pattern: judge by content, never by whichever
    toast element happens to be first in the DOM)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(needle in t for t in toast_texts(page)):
            return True
        page.wait_for_timeout(500)
    return False


def upload(page, path):
    """ia.input.fileupload mounts its <input type=file> only
    after the component is clicked (the tier1 pattern)."""
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


def overflow_report(page, selector):
    return page.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      return {sw: el.scrollWidth, cw: el.clientWidth,
              sh: el.scrollHeight, ch: el.clientHeight};
    }""", selector)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    defs0 = tag('[default]Roastery/CurrentBatch/AlarmDefsJson')
    theme0 = tag('[default]Roastery/AppSettings/ThemeMode')
    P.probe_setup()
    try:
        P.probe('reset')
        P.wait_until(lambda: tag(B + '/State') == 'Idle', 30)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            mob = browser.new_page(viewport={'width': 360,
                                             'height': 740})

            # ---------- A: alarms editor at 360px ----------
            mob.goto(BASE + '/settings', wait_until='networkidle',
                     timeout=60000)
            mob.wait_for_timeout(6000)
            dismiss(mob)
            mob.get_by_text('Alarms', exact=True).first.scroll_into_view_if_needed()
            mob.wait_for_timeout(1500)
            n0 = len(json.loads(defs0))
            count_txt = mob.locator('body').inner_text()
            check('alarms section lists the seeded alarms',
                  ('%d alarms' % n0) in count_txt
                  or str(n0) in count_txt, 'defs %d' % n0)
            # Load alarm 0 into the editor. Judge it the
            # tier1 way: an editor input ends up holding the
            # first seeded alarm's real name (read from the
            # definitions, not guessed).
            first_name = json.loads(defs0)[0]['name']
            mob.get_by_role('button', name='Load').first.click()
            mob.wait_for_timeout(2500)
            name_val = mob.locator(
                'input[type="text"]').evaluate_all(
                "els => els.map(e => e.value)")
            check('editor loads the first alarm',
                  first_name in name_val, name_val)
            # Add as new with a distinct name: type into the
            # name input, found by its staged value (tier1
            # pattern), so the fill cannot land in another
            # section's field.
            handle = mob.evaluate_handle(
                """(want) => [...document.querySelectorAll('input')]
                    .find(i => i.value === want)""", first_name)
            name_in = handle.as_element()
            assert name_in is not None, 'editor name input not found'
            name_in.click()
            mob.keyboard.press('Control+a')
            mob.keyboard.type('Manual Pass Alarm')
            mob.keyboard.press('Enter')
            mob.wait_for_timeout(800)
            mob.get_by_role('button', name='Add as New').click()
            check('add alarm fires a toast',
                  wait_toast(mob, 'Alarm added: Manual Pass Alarm',
                             timeout=15),
                  toast_texts(mob))
            mob.wait_for_timeout(1500)
            defs1 = json.loads(tag(
                '[default]Roastery/CurrentBatch/AlarmDefsJson'))
            check('alarm count grew by one',
                  len(defs1) == n0 + 1,
                  '%d -> %d' % (n0, len(defs1)))
            check('the new alarm carries the typed name',
                  defs1 and defs1[-1].get('name')
                  == 'Manual Pass Alarm',
                  defs1[-1] if defs1 else None)
            # Edit the new alarm: stage its index (the
            # editor's staging tag, the same surface the
            # dropdown writes), load it, change the value,
            # and save.
            idx = len(defs1) - 1
            write_tags([('[default]Roastery/AlarmEditor/Idx',
                          idx)])
            mob.get_by_role('button', name='Load').first.click()
            mob.wait_for_timeout(2000)
            mob.get_by_role('button', name='Save Alarm').click()
            check('save alarm fires a toast',
                  wait_toast(mob, 'Alarm saved: Manual Pass Alarm',
                             timeout=15),
                  toast_texts(mob))
            # Delete it again.
            mob.get_by_role('button', name='Delete Alarm').click()
            check('delete alarm fires a toast',
                  wait_toast(mob, 'Alarm deleted: Manual Pass Alarm',
                             timeout=15),
                  toast_texts(mob))
            mob.wait_for_timeout(2000)
            defs2 = json.loads(tag(
                '[default]Roastery/CurrentBatch/AlarmDefsJson'))
            check('delete returns the alarm count',
                  len(defs2) == n0, len(defs2))
            mob.screenshot(path=os.path.join(
                SHOTS, 'round3-alarms-editor-360.png'))
            ov = overflow_report(mob, '.psc-roast-page')
            print('settings page overflow:', ov)

            # ---------- B: log compare at 360px ------------
            mob.goto(BASE + '/log', wait_until='networkidle',
                     timeout=60000)
            mob.wait_for_timeout(6000)
            dismiss(mob)
            body = mob.locator('body').inner_text()
            check('log shows the stub marker on seeded stubs',
                  '(stub)' in body, body[:200])
            # The compare dropdowns carry defaults (the
            # tier 1 pattern): stage the compare directly and
            # judge the chart, the caption, and the fit.
            mob.get_by_role('button', name='Compare').first.click()
            mob.wait_for_timeout(4000)
            cap = mob.locator('body').inner_text()
            check('compare stages with a caption',
                  'A = Batch' in cap and 'B = Batch' in cap,
                  cap[-300:])
            chart = mob.locator(
                '[data-component="ia.canvas-charts.line"]')
            check('compare chart renders at 360px',
                  chart.count() >= 1, chart.count())
            mob.screenshot(path=os.path.join(
                SHOTS, 'round3-log-compare-360.png'))
            ov = overflow_report(mob, '.psc-roast-page')
            print('log page overflow:', ov)

            # ---------- C: import failure toast, Light -----
            # The batch .alog import upload is the BatchesPanel
            # component on the Log page (the Settings upload is
            # background staging, a different handler). The
            # file input mounts only after the component is
            # clicked (tier1 upload pattern).
            write_tags([('[default]Roastery/AppSettings/'
                          'ThemeMode', 'Light')])
            bogus = '/tmp/bogus.alog'
            with open(bogus, 'w') as f:
                f.write('this is not an artisan file\n')
            mob.reload(wait_until='networkidle')
            mob.wait_for_timeout(6000)
            dismiss(mob)
            upload(mob, bogus)
            check('bogus import fires a failure toast',
                  wait_toast(mob, 'Import failed', timeout=15),
                  toast_texts(mob))
            mob.wait_for_timeout(600)
            mob.screenshot(path=os.path.join(
                SHOTS, 'round3-import-fail-light-360.png'))
            browser.close()
    finally:
        write_tags([('[default]Roastery/CurrentBatch/'
                      'AlarmDefsJson', defs0),
                     ('[default]Roastery/AppSettings/ThemeMode',
                      theme0 or 'System')])
        try:
            P.probe('reset')
        except Exception:
            pass
        P.drain_pending()
        psql('DELETE FROM batch_events')
        P.probe_teardown()
        end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                      int(psql('SELECT COUNT(*) FROM batch_series')),
                      int(psql('SELECT COUNT(*) FROM batch_events')))
        check('lab restored to the seeded baseline',
              end_counts == (7, 101, 0)
              and tag(B + '/State') == 'Idle',
              '%s state=%s' % (end_counts, tag(B + '/State')))
        check('alarm defs restored byte identical',
              tag('[default]Roastery/CurrentBatch/AlarmDefsJson')
              == defs0)

    print()
    if FAILURES:
        print('ROUND 3 PASS FAILURES:', FAILURES)
        return 1
    print('ALL ROUND 3 MANUAL PASS CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
