#!/usr/bin/env python3
"""Roastery Tier 3b verification (Playwright + REST + psql).

Proves Tier 3 items 15, 16 and 19 live on the Maker gateway:
15. Curve display options: the Settings Display section and
    its tags (BT, RoR and ghost width and style, RoR fill,
    event marker size) bind onto the live canvas chart series
    props. Defaults reproduce the pre Tier 3 look exactly
    (checked on the authored view and on the tags), and changed
    values take effect in the live session with no quality
    overlays (the changed look is screenshot proven).
16. Phases from background, and phase bands on the chart: the
    ghost staged from an .alog file stages its phase
    boundaries on the BgPhase tags (saved Settings targets
    untouched), the LiveCurveDS band columns shade Drying,
    Maillard, Development and Cooling ranges that follow the
    stamped phases and the effective targets, and with the
    option on, the bands and the phase bar follow the ghost
    boundaries instead of the saved targets.
19. Statistics summary line: one compact line under the live
    chart (and on BatchDetail's chart card) carrying the phase
    times, percents and DTR from the values the PhasesBar,
    Summary and the staged document already compute. It fits
    360px as a single line with no overflow.

Presses during the test roast write batch_events rows through
the RUNNING PressEvents transaction group (PressCaptureMode
stays Group); those rows are deleted at the end.

Screenshots land in showcase/shots/roastery-tier3b-*.png.
The lab is left at 7 batches / 101 series rows / 0 events,
CurrentBatch clean Idle, display and target tags restored.
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
# Polish round 1 item 2: chart datasets anchor x values to
# roastery.core.AXIS_BASE_MS (a Denver local midnight), not the
# Unix epoch. Dataset reads below normalize by subtracting it.
AXIS_BASE_MS = 946710000000
FIXTURE = '/home/hatch/workspace/ignition-lab/artisan-fixtures/sample-roast.alog'
LOGS = '/home/hatch/workspace/ignition-lab/gateway-2027-maker/logs/system_logs.idb'
ROASTPAGE_JSON = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker/'
                  'data/projects/Roastery/com.inductiveautomation.'
                  'perspective/views/Views/RoastPage/view.json')
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:220]) if detail else '', flush=True)
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
    write_tags([('[default]Roastery/PressSlots/Slot%02d' % i, '')
                for i in range(16)])

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
        if (el.closest('[data-component="ia.display.table"]')) return;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.left < window.innerWidth - 1)
          w = Math.max(w, r.right);
      });
      return Math.round(w);
    }""")


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


def ds_rows(value):
    if isinstance(value, str):
        value = json.loads(value)
    cols = [c['name'] for c in value['columns']]
    return cols, value['rows']


def band_range(col):
    """(min_ms, max_ms) of one LiveCurveDS band column, in
    elapsed milliseconds (axis base subtracted), or None.
    Polish round 1 item 1: a band column now holds exactly its
    two boundary rows, so min and max ARE the band edges."""
    cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
    if col not in cols:
        return None
    i = cols.index(col)
    ts = [r[0] - AXIS_BASE_MS for r in rows if r[i] is not None]
    if not ts:
        return None
    return (min(ts), max(ts))


def stats_lines(page):
    return page.evaluate("""() => [...document.querySelectorAll(
      '.psc-roast-stats-line')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0; })
      .map(e => ({text: e.textContent.trim(),
                  right: Math.round(e.getBoundingClientRect().right),
                  scrollW: e.scrollWidth,
                  clientW: e.clientWidth}))""")


def mmss(sec):
    sec = int(max(0, float(sec or 0)))
    return '%d:%02d' % (sec // 60, sec % 60)


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_t3b_start.idb')
    con = sqlite3.connect('/tmp/logs_t3b_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    last = None
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_t3b_end.idb')
            con = sqlite3.connect('/tmp/logs_t3b_end.idb')
            rows = con.execute(
                "SELECT level_string, logger_name, formatted_message "
                "FROM logging_event WHERE event_id > ? AND "
                "level_string IN ('WARN', 'ERROR')",
                (start_id,)).fetchall()
            con.close()
            return [r for r in rows
                    if 'roastery' in (r[1] or '').lower()
                    or 'Roastery' in (r[2] or '')]
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def click_visible(page, name):
    """Click the first visible, enabled button with this exact
    text (breakpoint layouts duplicate buttons in the DOM; the
    hidden copies have no box)."""
    return page.evaluate("""(name) => {
      const els = [...document.querySelectorAll('button')]
        .filter(e => e.textContent.trim() === name &&
          e.getBoundingClientRect().width > 0 &&
          e.getBoundingClientRect().height > 0 && !e.disabled);
      if (!els.length) return false;
      els[0].click(); return true;
    }""", name)


def find_chart(node):
    if isinstance(node, dict):
        if (node.get('type') == 'ia.canvas-charts.line'
                and node.get('meta', {}).get('name') == 'RoastChart'):
            return node
        for v in node.values():
            hit = find_chart(v)
            if hit is not None:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = find_chart(v)
            if hit is not None:
                return hit
    return None


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    base = (int(psql('SELECT COUNT(*) FROM batches')),
            int(psql('SELECT COUNT(*) FROM batch_series')),
            int(psql('SELECT COUNT(*) FROM batch_events')))
    check('starting point is the seeded log', base == (7, 101, 0), base)
    max_event_id = int(psql('SELECT COALESCE(MAX(id), 0) FROM batch_events'))

    # ---------- item 15: defaults reproduce the old look -------
    disp = read_tags([B + '/DispBtWidth', B + '/DispBtStyle',
                      B + '/DispRorWidth', B + '/DispRorStyle',
                      B + '/DispGhostWidth', B + '/DispGhostStyle',
                      B + '/DispRorFill', B + '/DispMarkerSize',
                      B + '/PhaseFromBg'])
    check('display option tags carry the pre Tier 3 defaults',
          disp == [3, 'solid', 2, 'solid', 2, 'solid', False, 4, False],
          disp)
    rp = json.load(open(ROASTPAGE_JSON))
    chart = find_chart(rp.get('root', {}))
    check('main chart is still a canvas line chart', chart is not None)
    series = chart['props']['series']
    labels = [s['value'] for s in series]
    check('band series lead the series list (bands behind curves)',
          labels[:4] == ['bandDry', 'bandMai', 'bandDev', 'bandCool']
          and labels[4:] == ['bg', 'bgRor', 'plan', 'bean', 'ror',
                             'proj'], labels)
    check('band series carry phase name legend labels (an empty '
          'label makes the wrapper invent Series N names)',
          [s['label'] for s in series[:4]] == [
              'Drying', 'Maillard', 'Development', 'Cooling'],
          [s['label'] for s in series[:4]])
    bean, ror, ghost = series[7], series[8], series[4]
    check('authored series defaults match the old fixed look',
          bean['line'] == {'type': 'solid', 'width': 3,
                           'color': '#3b82f6'}
          and ror['line']['width'] == 2
          and ror['line']['type'] == 'solid'
          and ror['area']['opacity'] == 0.0
          and ghost['line']['width'] == 2
          and series[0]['line']['width'] == 0
          and series[0]['area']['opacity'] == 0.12
          and series[7]['referenceLines']['endpoints']['points'][0]['size'] == 4,
          (bean['line'], ror['area']))
    pc = chart['propConfig']
    want_bindings = {
        'props.series[7].line.width': 'DispBtWidth',
        'props.series[7].line.type': 'DispBtStyle',
        'props.series[8].line.width': 'DispRorWidth',
        'props.series[8].line.type': 'DispRorStyle',
        'props.series[4].line.width': 'DispGhostWidth',
        'props.series[4].line.type': 'DispGhostStyle',
        'props.series[5].line.width': 'DispGhostWidth',
        'props.series[5].line.type': 'DispGhostStyle',
        'props.series[7].referenceLines.endpoints.points[0].size':
            'DispMarkerSize'}
    bad = [k for k, m in want_bindings.items()
           if (pc.get(k, {}).get('binding', {})
               .get('config', {}).get('tagPath') != B + '/' + m)]
    check('display tags bind onto the series props (width, style, '
          'marker size)', not bad, bad)
    check('RoR fill binds the RoR area opacity to DispRorFill',
          'DispRorFill' in json.dumps(
              pc.get('props.series[8].area.opacity', {})))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600, 'height': 1000})
        mob = browser.new_page(viewport={'width': 360, 'height': 740})
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
            p.wait_for_timeout(7000)
            dismiss(p)
        check('no overlays at start',
              overlays(desk) == 0 and overlays(mob) == 0)

        # ---------- item 19 at idle ----------------------------
        lines = stats_lines(desk)
        check('stats line sits under the live chart at idle',
              len(lines) >= 1 and lines[0]['text'].startswith('Dry --:--'),
              lines)
        if lines:
            # Polish round 1 item 5 superseded the old idle
            # line (durations --:-- next to target plan
            # shares, which Eric's screenshots showed reading
            # as broken): at idle every phase is a future
            # phase, so durations and shares are both --.
            check('idle stats line shows the polish contract '
                  'and no DTR yet',
                  'Dry --:-- --' in lines[0]['text']
                  and 'Mai --:-- --' in lines[0]['text']
                  and 'Dev --:-- --' in lines[0]['text']
                  and 'DTR --' in lines[0]['text'],
                  lines[0]['text'])

        # ---------- settings: the Display section --------------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('settings page has the Curve Display and Phases From '
              'Background sections',
              'Curve Display' in body and 'Phases From Background' in body
              and 'Fill under RoR' in body and 'Use ghost phases' in body)
        desk.screenshot(path=SHOTS + '/roastery-tier3b-settings-display.png')

        # Distinctive saved targets, so ghost boundaries (270,
        # 195, 120) can never be confused with saved ones (200s).
        write_tags([(B + '/PhaseDryTargetSec', 200),
                    (B + '/PhaseMaillardTargetSec', 200),
                    (B + '/PhaseDevTargetSec', 200),
                    (B + '/DTRTargetPct', 25.0)])

        # ---------- item 16: stage the ghost from a file -------
        # polish phase 2 item 5: the upload lives in the
        # Settings Background Profile section now (the desk
        # page is already on /settings from the block above);
        # stage there, then return to the Roast page.
        upload(desk, FIXTURE)
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        ok = wait_until(lambda: str(tag(
            '[default]Roastery/BackgroundLabel') or '').startswith('File: '),
            timeout=30)
        check('ghost staged from the .alog file', bool(ok),
              tag('[default]Roastery/BackgroundLabel'))
        staged = read_tags([B + '/BgPhaseDrySec', B + '/BgPhaseFcSec',
                            B + '/BgPhaseDropSec'])
        check('ghost phase boundaries staged from its stamped events '
              '(dry 270, FC 465, drop 585)', staged == [270, 465, 585],
              staged)
        saved = read_tags([B + '/PhaseDryTargetSec',
                           B + '/PhaseMaillardTargetSec',
                           B + '/PhaseDevTargetSec', B + '/DTRTargetPct'])
        check('saved Settings targets untouched by staging',
              saved == [200, 200, 200, 25.0], saved)

        # ---------- the test roast ------------------------------
        mob.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('charge starts the roast', wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(6000)
        dock.get_by_role('button', name='Dry End').click()
        check('dry end stamps', wait_until(
            lambda: int(tag(B + '/DryEndElapsedSec') or -1) >= 0,
            timeout=20))
        mob.wait_for_timeout(4000)
        dock.get_by_role('button', name='FC Start').click()
        check('FC start stamps', wait_until(
            lambda: int(tag(B + '/FirstCrackStartElapsedSec') or -1) >= 0,
            timeout=20))
        mob.wait_for_timeout(6000)
        dry_s = int(tag(B + '/DryEndElapsedSec'))
        fc_s = int(tag(B + '/FirstCrackStartElapsedSec'))
        check('press rows came through the transaction group',
              int(psql("SELECT COUNT(*) FROM batch_events WHERE id > %d"
                       % max_event_id)) >= 3,
              psql("SELECT action FROM batch_events WHERE id > %d "
                   "ORDER BY id" % max_event_id))

        # Bands with the option OFF follow stamps + saved targets.
        dev = wait_until(lambda: band_range('bandDev'), timeout=40)
        check('phase bands present in LiveCurveDS', bool(dev))
        if dev:
            check('dry band runs charge to the dry end stamp',
                  band_range('bandDry') == (0, dry_s * 1000),
                  band_range('bandDry'))
            check('maillard band runs dry end to FC start',
                  band_range('bandMai') == (dry_s * 1000, fc_s * 1000),
                  band_range('bandMai'))
            check('development band runs FC start to the saved target '
                  'drop boundary (600 s)', dev == (fc_s * 1000, 600000),
                  dev)
            check('no cooling band before drop',
                  band_range('bandCool') is None)

        # Stats line mid roast (desktop and 360px). Polish
        # round 1 item 5: Development is the CURRENT phase
        # here (FC Start stamped, Drop not), so it shows its
        # live duration and live share, not --:--; the three
        # shares describe the same elapsed total and sum to
        # about 100.
        want_dry = mmss(dry_s)
        want_mai = mmss(fc_s - dry_s)
        lines = stats_lines(desk)
        _sm = None
        if lines:
            _sm = re.search(
                r'Dry (\d+):(\d+) (\d+)% \u00b7 Mai (\d+):(\d+) '
                r'(\d+)% \u00b7 Dev (\d+):(\d+) (\d+)% \u00b7 '
                r'DTR --$', lines[0]['text'])
        check('stats line shows the stamped phase times mid roast',
              bool(lines) and want_dry in lines[0]['text']
              and want_mai in lines[0]['text']
              and _sm is not None
              and int(_sm.group(7)) * 60 + int(_sm.group(8)) >= 3
              and abs(int(_sm.group(3)) + int(_sm.group(6))
                      + int(_sm.group(9)) - 100) <= 3,
              lines[0]['text'] if lines else None)
        mlines = stats_lines(mob)
        check('stats line fits 360px as one line mid roast',
              bool(mlines) and mlines[0]['right'] <= 361
              and mlines[0]['scrollW'] <= mlines[0]['clientW'] + 1,
              mlines)
        mob.screenshot(path=SHOTS + '/roastery-tier3b-roast-360.png')

        # ---------- item 16: phases from background ON ----------
        write_tags([(B + '/PhaseFromBg', True)])
        dev_bg = wait_until(
            lambda: band_range('bandDev')
            if (band_range('bandDev') or (0, 0))[1] == 585000 else None,
            timeout=60)
        check('with the option on, the development band follows the '
              'ghost drop boundary (585 s)', bool(dev_bg), dev_bg)
        saved = read_tags([B + '/PhaseDryTargetSec',
                           B + '/PhaseMaillardTargetSec',
                           B + '/PhaseDevTargetSec', B + '/DTRTargetPct'])
        check('saved targets still untouched with the option on',
              saved == [200, 200, 200, 25.0], saved)
        seg = desk.evaluate("""() => {
          const els = [...document.querySelectorAll('.psc-roast-seg')]
            .filter(e => { const r = e.getBoundingClientRect();
                           return r.width > 0; });
          if (!els.length) return null;
          const bar = els.reduce((a, e) => a + e.getBoundingClientRect().width, 0);
          const dry = els[0].getBoundingClientRect().width;
          return {share: dry / bar, text: els[0].textContent};
        }""")
        check('phase bar dry segment follows the ghost share '
              '(270 of 585, about 46 pct)',
              seg is not None and abs(seg['share'] - 270.0 / 585.0) < 0.04,
              seg)
        desk.screenshot(path=SHOTS + '/roastery-tier3b-bands-desktop.png')

        # ---------- item 15: change the display options ---------
        write_tags([(B + '/DispBtWidth', 5), (B + '/DispBtStyle', 'dashed'),
                    (B + '/DispRorWidth', 4), (B + '/DispRorStyle', 'dotted'),
                    (B + '/DispGhostWidth', 3),
                    (B + '/DispGhostStyle', 'dashed'),
                    (B + '/DispRorFill', True),
                    (B + '/DispMarkerSize', 9)])
        desk.wait_for_timeout(4000)
        mob.wait_for_timeout(2500)
        check('no overlays with the display options changed',
              overlays(desk) == 0 and overlays(mob) == 0)
        desk.screenshot(path=SHOTS + '/roastery-tier3b-display-changed.png')
        mob.screenshot(path=SHOTS + '/roastery-tier3b-display-changed-360.png')
        check('no overflow at 360px with options changed',
              overflow_worst(mob) <= 361, overflow_worst(mob))

        # ---------- drop, cooling band, final stats line --------
        dock.get_by_role('button', name='Drop').click()
        check('drop lands', wait_tag(B + '/State', 'Dropped'))
        drop_s = int(tag(B + '/DropElapsedSec'))
        mob.evaluate("window.scrollTo(0, 600)")
        mob.wait_for_timeout(800)
        check('cool button clicked', click_visible(mob, 'Cool'))
        check('cooling starts', wait_tag(B + '/State', 'Cooling'))
        cool = wait_until(lambda: band_range('bandCool'), timeout=60)
        check('cooling band runs from the drop stamp',
              bool(cool) and cool[0] == drop_s * 1000 and cool[1] > cool[0],
              cool)
        lines = stats_lines(desk)
        total = drop_s
        want = ('Dry %s %d%%' % (mmss(dry_s),
                                 round(dry_s * 100.0 / total)),
                'Dev %s' % mmss(drop_s - fc_s),
                'DTR %d%%' % round((drop_s - fc_s) * 100.0 / total))
        check('stats line after drop shows Dev time and the DTR',
              bool(lines) and all(w in lines[0]['text'] for w in want),
              lines[0]['text'] if lines else None)
        desk.screenshot(path=SHOTS + '/roastery-tier3b-cooling-desktop.png')
        mob.wait_for_timeout(1500)
        mlines = stats_lines(mob)
        check('stats line still fits 360px after drop (all phases '
              'populated)', bool(mlines) and mlines[0]['right'] <= 361
              and mlines[0]['scrollW'] <= mlines[0]['clientW'] + 1,
              mlines)
        mob.screenshot(path=SHOTS + '/roastery-tier3b-cooling-360.png')

        # ---------- BatchDetail stats line -----------------------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rows = desk.locator('.ia_table__row')
        picked = False
        for i in range(rows.count()):
            tokens = rows.nth(i).inner_text().replace(',', '').split()
            if '1042' in tokens:
                rows.nth(i).click()
                desk.wait_for_timeout(1200)
                picked = int(tag('[default]Roastery/SelectedBatchNumber')
                             or 0) == 1042
                break
        check('batch 1042 selected', picked)
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        doc = json.loads(psql(
            "SELECT data FROM batches WHERE batch_number = 1042"))
        ph = doc.get('phases') or {}
        tot = float(doc.get('totalSec') or 0)
        def share(sec):
            return '%d%%' % int(round(float(sec) * 100.0 / tot)) if tot else '--'
        want_line = ('Dry %s %s' % (mmss(ph.get('dryingSec')),
                                    share(ph.get('dryingSec')))
                     + ' \u00b7 Mai %s %s' % (mmss(ph.get('maillardSec')),
                                              share(ph.get('maillardSec')))
                     + ' \u00b7 Dev %s %s' % (mmss(ph.get('developmentSec')),
                                              share(ph.get('developmentSec')))
                     + ' \u00b7 DTR %.0f%%' % float(ph.get('dtrPct') or 0))
        lines = stats_lines(desk)
        got = [l['text'] for l in lines]
        check('BatchDetail chart card carries the same stats line, '
              'matching the stored document phases',
              want_line in got, (want_line, got))
        desk.screenshot(path=SHOTS + '/roastery-tier3b-detail-desktop.png')
        mob.goto(BASE + '/log/detail', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        check('BatchDetail has no overflow at 360px',
              overflow_worst(mob) <= 361, overflow_worst(mob))
        mob.screenshot(path=SHOTS + '/roastery-tier3b-detail-360.png')

        # ---------- clean the workspace through the UI ----------
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        check('ghost cleared through its button',
              click_visible(desk, 'Clear ghost')
              and wait_until(
                  lambda: (tag('[default]Roastery/BackgroundLabel')
                           or '') == '', timeout=20))
        desk.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(4000)
        dismiss(desk)
        check('staged ghost phases cleared with the ghost',
              read_tags([B + '/BgPhaseDrySec', B + '/BgPhaseFcSec',
                         B + '/BgPhaseDropSec']) == [-1, -1, -1])
        # phase aware dock (polish phase 2): the Reset utility
        # is offered only at Complete, under its full label;
        # walk the cooling roast through Finish first, with
        # retries while the dock re-renders its phase set
        # a click dispatched while the dock re-renders its
        # phase set can be swallowed, so retry each click
        # until the STATE advances, not until it dispatches
        def click_until(name, state, timeout=150):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if tag(B + '/State') == state:
                    return True
                click_visible(desk, name)
                time.sleep(1.2)
            return tag(B + '/State') == state
        # Polish round 2 part A: reload recovery. If a final
        # walk step exhausts its click_until budget (the aged
        # session stall from item 2), reload the Roast page
        # once and retry that step once before failing; a
        # fresh page instance always works. At most one
        # reload per step.
        _recovered = set()

        def click_until_recover(name, state):
            if click_until(name, state):
                return True
            if name in _recovered:
                return False
            _recovered.add(name)
            print('SUITE NOTE: reload recovery fired in tier3b '
                  'final walk (%s step exhausted its budget); '
                  'reloading the Roast page and retrying the '
                  'step once' % name)
            desk.goto(BASE + '/', wait_until='networkidle',
                      timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            return click_until(name, state)

        if tag(B + '/State') == 'Cooling':
            click_until_recover('Finish', 'Complete')
        check('reset through its button',
              click_until_recover('Reset / New Roast', 'Idle'))
        browser.close()

    # ---------- restore ------------------------------------------
    write_tags([(B + '/DispBtWidth', 3), (B + '/DispBtStyle', 'solid'),
                (B + '/DispRorWidth', 2), (B + '/DispRorStyle', 'solid'),
                (B + '/DispGhostWidth', 2), (B + '/DispGhostStyle', 'solid'),
                (B + '/DispRorFill', False), (B + '/DispMarkerSize', 4),
                (B + '/PhaseFromBg', False),
                (B + '/PhaseDryTargetSec', 270),
                (B + '/PhaseMaillardTargetSec', 210),
                (B + '/PhaseDevTargetSec', 150),
                (B + '/DTRTargetPct', 20.0)])
    drain_pending()
    psql('DELETE FROM batch_events WHERE id > %d' % max_event_id)
    state = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/BatchNumber', B + '/ActiveSource',
                       B + '/Mode'])
    check('workspace clean Idle', state == ['Idle', 5, 5, 1042,
                                            'Simulated', 'Off'], state)
    check('background cleared at the end',
          (tag('[default]Roastery/BackgroundLabel') or '') == '')
    end = (int(psql('SELECT COUNT(*) FROM batches')),
           int(psql('SELECT COUNT(*) FROM batch_series')),
           int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab back to the seeded log', end == base, end)
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad, bad[:3])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL TIER 3B CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
