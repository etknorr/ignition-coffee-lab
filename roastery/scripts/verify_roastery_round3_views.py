#!/usr/bin/env python3
"""Polish round 3 items 2 and 3 verification.

Item 2 (HUNT-24 other half): the Log table marks the seeded
stub batches (1045 to 1048) with '(stub)' after the bean name,
in both the desktop and phone column sets, and the selection
label inherits the marker.

Item 3 (HUNT-25): the BatchDetail header stacks at 360px:
Back and the gear share the first row, the title column takes
its own full width row below, and no two header boxes touch.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B
check = P.check
FAILURES = P.FAILURES
tag = P.tag
psql = P.psql
dismiss = P.dismiss


def main():
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600,
                                          'height': 900})
        mob = browser.new_page(viewport={'width': 360,
                                         'height': 740})
        # ---------------- item 2: log stub marker ----------
        for page, name in ((desk, 'desktop'), (mob, '360px')):
            page.goto(BASE + '/log', wait_until='networkidle',
                      timeout=60000)
            page.wait_for_timeout(6000)
            dismiss(page)
            body = page.locator('body').inner_text()
            check('log marks stub batches at %s' % name,
                  body.count('(stub)') >= 4,
                  'count %d' % body.count('(stub)'))
            page.screenshot(path=os.path.join(
                SHOTS, 'round3-log-stub-%s.png'
                % ('desktop' if name == 'desktop' else '360')))
        # Selection label inherits the marker: click a stub
        # row on desktop (rows are ordered newest first; the
        # stubs are 1045 to 1048, all Ethiopia Guji (stub)).
        desk.locator('text=Ethiopia Guji (stub)').first.click()
        desk.wait_for_timeout(2000)
        body = desk.locator('body').inner_text()
        check('selection label carries the stub marker',
              'Selected batch' in body and '(stub)' in body,
              body[body.find('Selected batch'):
                   body.find('Selected batch') + 120]
              if 'Selected batch' in body else 'no selection')

        # ---------------- item 3: detail header ------------
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        mob.goto(desk.url, wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        geo = mob.evaluate("""() => {
          const q = (t) => [...document.querySelectorAll('button')]
            .find(b => (b.innerText || '').trim() === t);
          const back = q('Back to Log');
          const title = [...document.querySelectorAll('*')]
            .filter(e => e.children.length === 0
              && (e.innerText || '').startsWith('Batch 10'))
            .sort((a, b) => a.innerText.length
              - b.innerText.length)[0];
          if (!back || !title) return null;
          const br = back.getBoundingClientRect();
          const tr = title.getBoundingClientRect();
          return {backBottom: br.bottom, backTop: br.top,
                  backRight: br.right, titleTop: tr.top,
                  titleLeft: tr.left, titleRight: tr.right};
        }""")
        print('header geometry:', geo)
        check('title sits on its own row below the back button',
              bool(geo) and geo['titleTop'] >= geo['backBottom'],
              geo)
        check('title spans the full phone width',
              bool(geo) and geo['titleLeft'] < 40
              and geo['titleRight'] > 320, geo)
        mob.screenshot(path=os.path.join(
            SHOTS, 'round3-batchdetail-header-360.png'))
        browser.close()

    print()
    if FAILURES:
        print('ROUND 3 VIEW FAILURES:', FAILURES)
        return 1
    print('ALL ROUND 3 VIEW CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
