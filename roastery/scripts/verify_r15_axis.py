#!/usr/bin/env python3
"""Round 15 verification: vertical y axis titles and tick
labels on every Roastery canvas chart, and the 14 view builder
resync.

Eric's order (2026-11-23): the y axis labels must be vertical
because the chart in its old format was worthless; it needs to
be bigger and fill more of the available mobile width. The fix
(ECharts nameRotate / axisLabel rotate, carried in the
Perspective canvas chart props as title.rotation and
labels.rotation):

- _canvas_yaxis() in the builder sets title rotation -90 with
  gap 6 and labels rotation -90 with gap 2 for every chart it
  builds.
- The RoastPage, BatchDetail and BatchesPanel view literals
  carry the same values on all 14 of their y axes.

Checks:
1. Repo view files: every ia.canvas chart in RoastPage,
   BatchDetail and BatchesPanel has all y axes at title
   rotation -90 gap 6, labels rotation -90 gap 2.
2. The gateway project files carry the same values (the
   running build).
3. Builder byte identity: the builder's emitted views match
   the repo view.json files byte for byte for all 25 views,
   which is the round 15 resync proof for the 14 stale views
   (Tile, EventsStrip, Controls, BatchesPanel, LogPage,
   TabBar, ControlDock, SettingsRoaster, SettingsRor,
   SettingsAuc, SettingsProjection, SettingsPlayback,
   SettingsAlarms, SettingsDisplay) plus the 11 already in
   sync.
4. Live: the Roast page at 360 px in Dark renders, and the
   chart's colored plot region spans at least 150 px of the
   360 px width (measured on the screenshot; the pre-fix
   layout measured about 73 px, the fixed layout about
   206 px). Screenshot saved under
   ~/workspace/ignition-lab/r15-screenshots/.

Run with wsvenv python from ~/workspace/ignition-lab. Leaves
ThemeMode back at System and writes no tags.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
os.chdir('/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P

TM = '[default]Roastery/AppSettings/ThemeMode'


def read_tag(path):
    return P.tag(path)


def write_tag(path, value):
    P.write_tags([(path, value)])

REPO_VIEWS = os.path.expanduser(
    '~/workspace/ignition-coffee-lab/roastery/project/Roastery/'
    'com.inductiveautomation.perspective/views/Views')
GW_VIEWS = os.path.expanduser(
    '~/workspace/ignition-lab/gateway-2027-maker/data/projects/'
    'Roastery/com.inductiveautomation.perspective/views/Views')
CHART_VIEWS = ('RoastPage', 'BatchDetail', 'BatchesPanel')
SHOT = ('/home/hatch/workspace/ignition-lab/r15-screenshots/'
        'verify-roast-dark-360.png')

FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)) if (detail and not cond) else '')
    if not cond:
        FAILS.append(name)


def canvas_charts(node, out):
    if isinstance(node, dict):
        if str(node.get('type', '')).startswith('ia.canvas'):
            out.append(node)
        for v in node.values():
            canvas_charts(v, out)
    elif isinstance(node, list):
        for v in node:
            canvas_charts(v, out)


def axis_failures(base):
    bad = []
    total = 0
    for view in CHART_VIEWS:
        doc = json.load(open(os.path.join(base, view,
                                          'view.json')))
        charts = []
        canvas_charts(doc, charts)
        for ch in charts:
            for ax in ch.get('props', {}).get('yAxis', []):
                total += 1
                t = ax.get('title', {})
                lab = ax.get('labels', {})
                if not (t.get('rotation') == -90
                        and t.get('gap') == 6
                        and lab.get('rotation') == -90
                        and lab.get('gap') == 2):
                    bad.append('%s/%s' % (
                        view, ch.get('meta', {}).get('name')))
    return total, bad


def main():
    total, bad = axis_failures(REPO_VIEWS)
    check('repo chart views carry 14 y axes', total == 14, total)
    check('repo y axes all vertical (title -90 gap 6, labels '
          '-90 gap 2)', not bad, bad)
    total, bad = axis_failures(GW_VIEWS)
    check('gateway chart views carry 14 y axes', total == 14,
          total)
    check('gateway y axes all vertical', not bad, bad)

    out = subprocess.run(
        ['./wsvenv/bin/python', 'r15-scratch/diffprobe.py'],
        capture_output=True, text=True).stdout
    ident = out.count('IDENTICAL')
    stale = [ln for ln in out.splitlines()
             if ln.startswith('STALE')]
    check('builder emits all 23 probed views byte identical',
          ident == 23 and not stale,
          'identical=%d stale=%s' % (ident, stale))
    out = subprocess.run(
        ['./wsvenv/bin/python', 'r15-scratch/probe_literals.py'],
        capture_output=True, text=True).stdout
    check('builder literals RoastPage and BatchDetail byte '
          'identical', out.count('IDENTICAL') == 2, out.strip())

    prev_theme = read_tag(TM)
    try:
        write_tag(TM, 'Dark')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=[
                '--no-zygote', '--single-process'])
            ctx = b.new_context(viewport={'width': 360,
                                          'height': 740},
                                timezone_id='America/Denver')
            pg = ctx.new_page()
            pg.goto('http://localhost:8088/data/perspective/'
                    'client/Roastery/',
                    wait_until='domcontentloaded', timeout=60000)
            pg.wait_for_timeout(6000)
            # The Maker Personal Use Only modal has a single
            # AGREE & CLOSE button; poll and click it.
            for _ in range(40):
                try:
                    if pg.get_by_text('AGREE & CLOSE').count() > 0:
                        pg.get_by_text('AGREE & CLOSE').first.click(
                            timeout=5000)
                        pg.wait_for_timeout(1200)
                        if pg.get_by_text(
                                'AGREE & CLOSE').count() == 0:
                            break
                except Exception:
                    pass
                pg.wait_for_timeout(500)
            pg.get_by_text('Roast Curve').first.wait_for(
                timeout=30000)
            time.sleep(3)
            pg.screenshot(path=SHOT)
            b.close()
        check('live Roast page rendered at 360 dark',
              os.path.getsize(SHOT) > 10000)
        measure = subprocess.run(
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
''', SHOT], capture_output=True, text=True)
        width = int(measure.stdout.strip() or 0)
        check('live plot region spans >= 150 px at 360 wide '
              '(was about 73 px before the fix)', width >= 150,
              width)
    finally:
        write_tag(TM, prev_theme if prev_theme in
                  ('System', 'Light', 'Dark') else 'System')

    print('TOTAL %d PASS, %d FAIL' % (PASSES[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
