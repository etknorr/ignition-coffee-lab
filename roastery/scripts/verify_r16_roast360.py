#!/usr/bin/env python3
"""Round 16 live axis verification: one full simulated roast
driven through the phone UI at 360px, Charge through Finish.

The round 15 axis change is checked where Eric uses it:
- Every gateway y axis still carries title rotation -90 gap 6
  and labels rotation -90 gap 2.
- At Idle, Charge, Dry End, FC Start, FC End, SC Start, SC End,
  Drop and Complete, the 360px page has no horizontal overflow
  and no clipped leaf text, and the chart's colored plot region
  still spans at least 150px of the 360px width.
- Event stamps land in order, the phase line reaches all three
  phases, and a screenshot is saved at every stage under
  ~/workspace/ignition-lab/r16-screenshots/ for visual proof
  that the titles and tick labels stay vertical and readable
  while values, markers and phase bands change.

The roast is saved, then removed slot-safely (PressSlots drained
first, the HUNT-53 rule), and cleanup_workspace.py restores the
clean lab. Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
SHOTS = '/home/hatch/workspace/ignition-lab/r16-screenshots'
GW_VIEWS = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker/'
            'data/projects/Roastery/com.inductiveautomation.'
            'perspective/views/Views')
CHART_VIEWS = ('RoastPage', 'BatchDetail', 'BatchesPanel')
FAILS = []
PASSES = [0]
NEXT_BATCH = [0]

OVERFLOW_JS = """
() => {
  const vw = window.innerWidth;
  const de = document.documentElement;
  const clipped = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.closest('.secondary-message')) return;
    if (el.children.length === 0 && el.offsetParent !== null) {
      if (el.scrollWidth > el.clientWidth + 1) {
        const t = (el.textContent || '').trim().slice(0, 40);
        if (t) clipped.push(t + ' (' + el.scrollWidth + '>' +
          el.clientWidth + ')');
      }
    }
  });
  return {vw: vw, docW: de.scrollWidth,
          clipped: clipped.slice(0, 10), nClipped: clipped.length};
}
"""


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:240]) if (detail != '' and not cond)
          else '', flush=True)
    if not cond:
        FAILS.append(name)


def canvas_charts(node, out):
    if isinstance(node, dict):
        if str(node.get('type', '')).startswith('ia.canvas'):
            out.append(node)
        for value in node.values():
            canvas_charts(value, out)
    elif isinstance(node, list):
        for value in node:
            canvas_charts(value, out)


def axis_props():
    total = 0
    bad = []
    for view in CHART_VIEWS:
        doc = json.load(open(os.path.join(GW_VIEWS, view,
                                          'view.json')))
        charts = []
        canvas_charts(doc, charts)
        for chart in charts:
            for axis in chart.get('props', {}).get('yAxis', []):
                total += 1
                title = axis.get('title', {})
                labels = axis.get('labels', {})
                if not (title.get('rotation') == -90
                        and title.get('gap') == 6
                        and labels.get('rotation') == -90
                        and labels.get('gap') == 2):
                    bad.append(view)
    check('gateway still carries 14 y axes', total == 14, total)
    check('gateway y axes all vertical', not bad, bad)


def plot_width(path):
    out = subprocess.run(
        ['python3', '-c', '''
from PIL import Image
import sys
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
bg = im.getpixel((6, 6))
best = 0
for y in range(int(h * 0.30), int(h * 0.62)):
    run = 0
    wid = 0
    for x in range(w):
        p = im.getpixel((x, y))
        d = max(abs(p[0] - bg[0]), abs(p[1] - bg[1]),
                abs(p[2] - bg[2]))
        if d > 10:
            run += 1
            wid = max(wid, run)
        else:
            run = 0
    best = max(best, wid)
print(best)
''', path], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def measure(page, stage):
    m = page.evaluate(OVERFLOW_JS)
    check('%s no horizontal overflow' % stage, m['docW'] <= m['vw'], m)
    check('%s no clipped leaf text' % stage, m['nClipped'] == 0,
          m['clipped'])
    path = os.path.join(SHOTS, 'r16-roast360-%s.png' % stage)
    page.screenshot(path=path, timeout=60000)
    check('%s screenshot saved' % stage, os.path.getsize(path) > 10000,
          path)
    width = plot_width(path)
    check('%s plot spans >= 150px' % stage, width >= 150, width)
    return path


def click(page, name):
    button = page.locator('button').filter(has_text=name).first
    button.scroll_into_view_if_needed(timeout=10000)
    button.click(timeout=20000)


def stamp(page, label, member, stage, wait_ms):
    click(page, label)
    ok = P.wait_until(
        lambda: (P.tag(B + '/' + member) or -1) >= 0, 30)
    check('%s stamps' % label, bool(ok), P.tag(B + '/' + member))
    page.wait_for_timeout(wait_ms)
    page.evaluate('window.scrollTo(0, 0)')
    page.wait_for_timeout(700)
    measure(page, stage)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    axis_props()
    check('starting database is the clean seed',
          (P.psql('SELECT COUNT(*) FROM batches'),
           P.psql('SELECT COUNT(*) FROM batch_series'),
           P.psql('SELECT COUNT(*) FROM batch_events'))
          == ('7', '101', '0'),
          (P.psql('SELECT COUNT(*) FROM batches'),
           P.psql('SELECT COUNT(*) FROM batch_series'),
           P.psql('SELECT COUNT(*) FROM batch_events')))
    P.write_tags([(TM, 'Dark')])
    with sync_playwright() as pw:
        browser = R5.launch(pw)
        ctx = browser.new_context(
            viewport={'width': 360, 'height': 800},
            timezone_id='America/Denver')
        page = R5.open_page(ctx, '/')
        try:
            max_db = int(P.psql(
                'SELECT MAX(batch_number) FROM batches'))
            current = int(P.tag(B + '/BatchNumber'))
            NEXT_BATCH[0] = (current if current > max_db
                             else max_db + 1)
            measure(page, 'idle')
            click(page, 'New Roast')
            check('new roast takes the next batch number',
                  P.wait_until(
                      lambda: P.tag(B + '/BatchNumber')
                      == NEXT_BATCH[0], 30),
                  P.tag(B + '/BatchNumber'))
            click(page, 'Charge')
            check('charge starts the roast', P.wait_until(
                lambda: P.tag(B + '/State') == 'Roasting', 30))
            page.wait_for_timeout(20000)
            measure(page, 'charge')
            stamp(page, 'Dry End', 'DryEndElapsedSec', 'dry-end',
                  8000)
            stamp(page, 'FC Start', 'FirstCrackStartElapsedSec',
                  'fc-start', 8000)
            stamp(page, 'FC End', 'FirstCrackEndElapsedSec',
                  'fc-end', 8000)
            stamp(page, 'SC Start', 'SecondCrackStartElapsedSec',
                  'sc-start', 8000)
            stamp(page, 'SC End', 'SecondCrackEndElapsedSec',
                  'sc-end', 8000)
            click(page, 'Drop')
            check('drop lands', P.wait_until(
                lambda: P.tag(B + '/State') == 'Dropped', 30))
            page.wait_for_timeout(2500)
            measure(page, 'drop')
            try:
                click(page, 'Cool')
                check('cool starts', P.wait_until(
                    lambda: P.tag(B + '/State') == 'Cooling', 30))
                page.wait_for_timeout(2500)
            except Exception as exc:
                check('cool starts', False, str(exc)[:160])
            click(page, 'Finish')
            check('finish reaches Complete', P.wait_until(
                lambda: P.tag(B + '/State') == 'Complete', 30))
            page.wait_for_timeout(1500)
            measure(page, 'complete')
            body = page.locator('body').inner_text()
            # The live phase line abbreviates (verified live in
            # round 16 run 1: 'Dry 0:20 30% - Mai 0:10 15% - Dev
            # 0:37 55% - DTR 55%'), so parse that shape instead
            # of looking for the full phase names.
            import re as _re
            m = _re.search(
                r'Dry\s+\d+:\d+\s+\d+%.*Mai\s+\d+:\d+\s+\d+%.*'
                r'Dev\s+\d+:\d+\s+\d+%.*DTR\s+\d+%', body)
            check('phase line shows all three phases and DTR',
                  m is not None, body[:300])
            stamps = [P.tag(B + '/' + member) or -1 for member in
                      ('DryEndElapsedSec', 'FirstCrackStartElapsedSec',
                       'FirstCrackEndElapsedSec',
                       'SecondCrackStartElapsedSec',
                       'SecondCrackEndElapsedSec', 'DropElapsedSec')]
            check('event stamps are in order',
                  all(stamps[i] >= 0 and stamps[i] <= stamps[i + 1]
                      for i in range(len(stamps) - 1)), stamps)
            click(page, 'Save Batch')
            check('roast saves under the next batch number',
                  P.wait_until(
                      lambda: P.psql(
                          'SELECT COUNT(*) FROM batches WHERE '
                          'batch_number = %d' % NEXT_BATCH[0]) == '1',
                      30))
            click(page, 'Reset')
            check('reset returns to Idle', P.wait_until(
                lambda: P.tag(B + '/State') == 'Idle', 30))
        finally:
            browser.close()
    P.drain_pending()
    if NEXT_BATCH[0]:
        P.psql('DELETE FROM batch_events WHERE batch_number = %d'
               % NEXT_BATCH[0])
        P.psql('DELETE FROM batches WHERE batch_number = %d'
               % NEXT_BATCH[0])
    subprocess.run(['./wsvenv/bin/python', 'cleanup_workspace.py'],
                   cwd='/home/hatch/workspace/ignition-lab',
                   capture_output=True, text=True)
    check('lab restored to 7 batches, 101 series, 0 events',
          (P.psql('SELECT COUNT(*) FROM batches'),
           P.psql('SELECT COUNT(*) FROM batch_series'),
           P.psql('SELECT COUNT(*) FROM batch_events'))
          == ('7', '101', '0'))
    check('theme restored to System', P.tag(TM) == 'System',
          P.tag(TM))
    print('TOTAL %d PASS, %d FAIL' % (PASSES[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
