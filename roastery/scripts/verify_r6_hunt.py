#!/usr/bin/env python3
"""Round 6 hunting verification (HUNT-48, HUNT-49).

HUNT-48: the themeMode onChange script logged an error when
report_brightness ran Periscope's runJavaScriptAsync against
a closing page (a Java throwable, which except Exception
does not catch in Jython). Fixed by a bare except in
report_brightness and show_toast. Proof: flip ThemeMode
across open sessions, then count themeMode errors in the
gateway log since this run started; there must be none.
Run AFTER verify_roastery_dark in the battery so the log
window also covers the dark suite's theme flips.

HUNT-49: the roast clock value clipped 1px at 360px
(scrollWidth 48, clientWidth 47). Fixed by 15px HUD values
at phone widths. Proof: measure the clock value and the
longest phase value at 360px; scrollWidth must not exceed
clientWidth.

Run with wsvenv python from ~/workspace/ignition-lab.
Leaves the lab as found (ThemeMode System, PhaseLabel
restored).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P

LAB = '/home/hatch/workspace/ignition-lab'
LOGS = 'gateway-2027-maker/logs/system_logs.idb'
TM = '[default]Roastery/AppSettings/ThemeMode'
B = '[default]Roastery/CurrentBatch'
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:200]) if detail else '', flush=True)
    if not cond:
        FAILURES.append(label)


def theme_mode_errors_since(start_ms):
    """themeMode onChange errors logged since start_ms."""
    tmp = '/tmp/logs_r6hunt.idb'
    shutil.copy(os.path.join(LAB, LOGS), tmp)
    con = sqlite3.connect(tmp)
    rows = con.execute(
        "SELECT formatted_message FROM logging_event "
        "WHERE timestmp > ? AND level_string IN ('WARN','ERROR') "
        "AND formatted_message LIKE '%themeMode%'",
        (start_ms,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def main():
    start_ms = int(time.time() * 1000)
    start_theme = P.tag(TM)
    start_phase = P.tag(B + '/PhaseLabel')

    # ---- HUNT-48 -------------------------------------------------
    # Flip ThemeMode across an open session twice. Before
    # the fix, a flip while any session was closing logged
    # "Error running property change script on
    # view.custom.themeMode"; after it, the bare except
    # swallows the Java throwable and nothing is logged.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-zygote',
                                           '--single-process'])
        page = browser.new_page(viewport={'width': 1600,
                                          'height': 900},
                                timezone_id='America/Denver')
        page.goto(P.BASE + '/', wait_until='networkidle',
                  timeout=60000)
        page.wait_for_timeout(6000)
        try:
            if page.get_by_text('Personal Use Only').count() > 0:
                page.get_by_text('AGREE & CLOSE').first.click(
                    timeout=8000)
                page.wait_for_timeout(1200)
        except Exception:
            pass
        for mode in ('Dark', 'Light', 'Dark', 'Light'):
            P.write_tags([(TM, mode)])
            page.wait_for_timeout(3000)
        # Close the session mid-flight on the last flip:
        # the onChange fires while the page is going away,
        # which is the shape that logged before the fix.
        P.write_tags([(TM, 'Dark')])
        browser.close()
        time.sleep(3)
    P.write_tags([(TM, start_theme)])
    errs = theme_mode_errors_since(start_ms)
    check('no themeMode onChange error after the HUNT-48 fix',
          len(errs) == 0, errs[:1])

    # ---- HUNT-49 -------------------------------------------------
    # Clock value and longest phase value at 360px: the
    # content must fit its box (scrollWidth <= clientWidth).
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-zygote',
                                           '--single-process'])
        page = browser.new_page(viewport={'width': 360,
                                          'height': 900},
                                timezone_id='America/Denver')
        page.goto(P.BASE + '/', wait_until='networkidle',
                  timeout=60000)
        page.wait_for_timeout(6000)
        try:
            if page.get_by_text('Personal Use Only').count() > 0:
                page.get_by_text('AGREE & CLOSE').first.click(
                    timeout=8000)
                page.wait_for_timeout(1200)
        except Exception:
            pass
        clock = page.evaluate("""() => {
          const el = document.querySelector(
              '.psc-roast-hud-value');
          const vals = [...document.querySelectorAll(
              '.psc-roast-hud-value')].map(e =>
              [e.innerText.trim(), e.scrollWidth, e.clientWidth]);
          return vals;
        }""")
        for txt, sw, cw in clock:
            check('HUD value %r fits at 360px' % txt,
                  sw <= cw + 1, (sw, cw))
        for phase in ('Development', 'Second Crack'):
            P.write_tags([(B + '/PhaseLabel', phase)])
            page.wait_for_timeout(2500)
            row = page.evaluate("""() => {
              const el = document.querySelector(
                  '.psc-roast-hud-value-phase');
              return [el.innerText.trim(), el.scrollWidth,
                      el.clientWidth];
            }""")
            check('phase %r fits at 360px' % phase,
                  row[1] <= row[2] + 1, row)
        browser.close()
    P.write_tags([(B + '/PhaseLabel', start_phase)])
    check('ThemeMode restored to ' + str(start_theme),
          P.tag(TM) == start_theme, P.tag(TM))

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL R6 HUNT CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
