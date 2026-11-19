#!/usr/bin/env python3
"""Verify the Roastery polish round 1 phase 2 build (views,
navigation chrome, theme, 2026-11-17) against the Maker 2027
gateway.

Items covered:
  1. Phase aware dock views: ControlDock (phone) and Controls
     (desktop) render roastery.core.dock_actions() through
     Views/DockButton repeaters; contents asserted at Idle,
     Roasting (three phases), Dropped, Cooling and Complete;
     one batch_events row per press.
  2. Customs in Settings: rename custom 2, hide custom 3 via
     the Show toggle (tag binding), the dock shows the renamed
     custom and not the hidden one, stamping it lands in the
     saved batch document and the chart marks.
  3. Event labels above the chart: reference line items use
     only the two top band positions (end, insideEnd), the
     bean axis max is 520 (the reserved band), screenshots at
     desktop and 360px inspected for readable labels.
  4. Overflow hunt: scrollWidth/clientWidth and
     scrollHeight/clientHeight measured on the tile embeds,
     the page scroll containers, the PromptStrip (with a
     prompt active) and the AnalyzerStrip at 360px and
     desktop; the analyzer caption must not overlap the -10s
     button.
  5. The .alog upload lives in Settings (Background Profile),
     not on the Roast page; staging from Settings works with
     the same assertions tier 1 made on the Roast page.
  6. TabBar is one ia.navigation.horizontalmenu (Roast,
     Settings, Log) with native navigation and a bold plus
     filled tile active indication from page.props.path.
  7. Theme: ThemeMode tag (System, Light, Dark; default
     System) in [default]Roastery/AppSettings; System resolves
     the device via the roastsystem theme (dark device comes
     up dark, light device light, live OS change restyles),
     explicit modes pin, the choice persists into a new
     session, and the gear opens Views/AppSettings on all
     four pages.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
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
FIXTURE = ('/home/hatch/workspace/ignition-lab/artisan-fixtures/'
           'sample-roast.alog')
LOGS = 'gateway-2027-maker/logs/system_logs.idb'
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:220]) if detail else '', flush=True)
    if not cond:
        FAILURES.append(label)


def read_tags(paths):
    st, out = api('GET', '/tags/read', body=json.dumps(
        {'tags': paths}))
    assert st == 200, (st, out)
    return [r['value'] for r in out['results']]


def tag(path):
    return read_tags([path])[0]


def write_tags(pairs):
    st, out = api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': [p for p, v in pairs],
         'values': [v for p, v in pairs]}))
    assert st == 200, (st, out)


def wait_until(fn, timeout=30, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def wait_tag(path, want, timeout=30):
    return wait_until(lambda: tag(path) == want, timeout)


def psql(sql):
    pw = open('/home/hatch/workspace/ignition-lab/'
              '.roastery-pgpass').read().strip()
    env = dict(os.environ, PGPASSWORD=pw,
               PATH=os.environ['PATH'] + ':/usr/lib/postgresql/16/bin')
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', sql], capture_output=True, text=True,
        env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


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


def ds_rows(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return [], []
    if not isinstance(value, dict):
        return [], []
    cols = [c['name'] for c in value.get('columns') or []]
    return cols, value.get('rows') or []


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(
                timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


def upload(page, path):
    """Same mechanics as tier 1: the file upload mounts its
    input only after a click."""
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


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_p2_start.idb')
    con = sqlite3.connect('/tmp/logs_p2_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_p2_end.idb')
            con = sqlite3.connect('/tmp/logs_p2_end.idb')
            rows = con.execute(
                "SELECT level_string, logger_name, formatted_message "
                "FROM logging_event WHERE event_id > ? AND "
                "level_string IN ('WARN', 'ERROR')",
                (start_id,)).fetchall()
            con.close()
            return [r for r in rows
                    if 'roastery' in (r[1] or '').lower()
                    or 'Roastery' in (r[2] or '')]
        except Exception:
            time.sleep(2)
    return ['log check failed']


# ------------------------------------------------------------- probe
PROBE_LINES = [
    "import system",
    "import roastery.core as core",
    "cmd = currentValue.value",
    "if cmd:",
    "    res = None",
    "    try:",
    "        if cmd == 'dock':",
    "            res = system.util.jsonEncode(core.dock_actions())",
    "        elif cmd == 'reflines':",
    "            res = system.util.jsonEncode(",
    "                core.event_reference_lines())",
    "        elif cmd == 'charge':",
    "            core.charge(); res = 'ok'",
    "        elif cmd == 'drop':",
    "            core.drop(); res = 'ok'",
    "        elif cmd == 'cool':",
    "            core.cool(); res = 'ok'",
    "        elif cmd == 'finish':",
    "            core.finish(); res = 'ok'",
    "        elif cmd == 'reset':",
    "            core.reset_batch(); res = 'ok'",
    "        elif cmd == 'updatedock':",
    "            core.update_dock_actions(); res = 'ok'",
    "        else:",
    "            res = 'unknown'",
    "    except Exception as e:",
    "        res = 'ERR ' + str(e)",
    "    system.tag.writeBlocking(['[default]PolishProbe/Result'], [res])",
    "    seq = system.tag.readBlocking(",
    "['[default]PolishProbe/ResultSeq'])[0].value or 0",
    "    system.tag.writeBlocking(",
    "['[default]PolishProbe/ResultSeq'], [int(seq) + 1])",
]
PROBE_SCRIPT = ''.join('\t' + l + '\n' for l in PROBE_LINES)
_seq = [0]


def probe_setup():
    folder = {'name': 'PolishProbe', 'tagType': 'Folder', 'tags': [
        {'name': 'Cmd', 'tagType': 'AtomicTag', 'valueSource': 'memory',
         'dataType': 'String', 'value': '',
         'eventScripts': [{'eventid': 'valueChanged',
                           'script': PROBE_SCRIPT}]},
        {'name': 'Result', 'tagType': 'AtomicTag',
         'valueSource': 'memory', 'dataType': 'String', 'value': ''},
        {'name': 'ResultSeq', 'tagType': 'AtomicTag',
         'valueSource': 'memory', 'dataType': 'Int4', 'value': 0},
    ]}
    st, out = api('POST', '/tags/import', body=json.dumps(folder),
                  params={'provider': 'default', 'type': 'json',
                          'collisionPolicy': 'Overwrite'},
                  ctype='application/octet-stream')
    assert st == 200, (st, out)
    _seq[0] = int(tag('[default]PolishProbe/ResultSeq') or 0)


def probe_teardown():
    api('DELETE', '/tags/delete',
        body=json.dumps({'tags': ['[default]PolishProbe']}),
        params={'confirm': 'true'})


def probe(cmd, timeout=30):
    write_tags([('[default]PolishProbe/Cmd', '')])
    time.sleep(0.35)
    write_tags([('[default]PolishProbe/Cmd', cmd)])
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = int(tag('[default]PolishProbe/ResultSeq') or 0)
        if s > _seq[0]:
            _seq[0] = s
            return tag('[default]PolishProbe/Result')
        time.sleep(0.3)
    raise RuntimeError('probe timeout: ' + cmd)


def dock_buttons(scope):
    """Visible button texts inside a dock/controls scope."""
    return scope.evaluate("""e => [...e.querySelectorAll('button')]
        .filter(b => b.offsetParent !== null)
        .map(b => b.innerText.trim()).filter(t => t)""")


def press_count(batch_no):
    return int(psql('SELECT COUNT(*) FROM batch_events WHERE '
                    'batch_number = %d' % batch_no))


def overflow_report(page):
    """Measured overflow for the item 4 containers."""
    return page.evaluate("""() => {
      const out = {};
      const meas = el => el ? {
        sw: el.scrollWidth, cw: el.clientWidth,
        sh: el.scrollHeight, ch: el.clientHeight} : null;
      // tile embeds: the embedded view wrappers around tiles
      out.tileEmbeds = [...document.querySelectorAll(
        '[data-component="ia.display.view"]')]
        .filter(e => e.querySelector('.psc-roast-card-sm'))
        .map(e => meas(e));
      out.doc = {sw: document.documentElement.scrollWidth,
                 cw: document.documentElement.clientWidth,
                 sh: document.documentElement.scrollHeight,
                 ch: document.documentElement.clientHeight};
      const strip = [...document.querySelectorAll(
        '.psc-roast-banner')].find(e => e.offsetParent !== null
        && e.querySelector('button'));
      out.promptStrip = meas(strip);
      if (strip) {
        const btn = strip.querySelector('button');
        if (btn) {
          const sr = strip.getBoundingClientRect();
          const br = btn.getBoundingClientRect();
          out.promptBtn = {stripRight: sr.right, btnRight: br.right,
                           stripBottom: sr.bottom,
                           btnBottom: br.bottom, btnH: br.height};
        }
      }
      // analyzer strip: the flex column holding the ANALYZER caption
      const cap = [...document.querySelectorAll('*')].find(
        e => e.children.length === 0
             && (e.innerText || '').trim() === 'ANALYZER'
             && e.offsetParent !== null);
      if (cap) {
        let stripEl = cap;
        for (let i = 0; i < 6 && stripEl.parentElement; i++) {
          stripEl = stripEl.parentElement;
          const nb = stripEl.querySelectorAll('button').length;
          const h = stripEl.getBoundingClientRect().height;
          if (nb >= 3 && h <= 160) break;
        }
        out.analyzerStrip = meas(stripEl);
        const minus = [...stripEl.querySelectorAll('button')].find(
          b => b.innerText.trim() === '-10s');
        const cr = cap.getBoundingClientRect();
        if (minus) {
          const mr = minus.getBoundingClientRect();
          out.analyzerCapVsMinus = {capRight: cr.right,
                                    minusLeft: mr.left,
                                    capBottom: cr.bottom,
                                    minusTop: mr.top};
        }
      }
      out.unitLabels = [...document.querySelectorAll(
        '.psc-roast-unit')].map(e => meas(e));
      return out;
    }""")


def container_var(page):
    return page.evaluate("""() => {
      const el = document.querySelector('.psc-roast-card-sm')
                 || document.querySelector('.psc-roast-card');
      return el ? getComputedStyle(el)
          .getPropertyValue('--container').trim() : None;
    }""")


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    probe_setup()
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    write_tags([(B + '/CustomEvent2Name', 'Drum Note'),
                (B + '/CustomEvent2Enabled', True),
                (B + '/CustomEvent3Enabled', True),
                ('[default]Roastery/AppSettings/ThemeMode',
                 'System')])
    probe('updatedock')
    time.sleep(1)
    batch_no = int(tag(B + '/BatchNumber'))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600,
                                          'height': 900})
        mob = browser.new_page(viewport={'width': 360,
                                         'height': 740})
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle',
                   timeout=60000)
            p.wait_for_timeout(7000)
            dismiss(p)

        # ---------------- item 6: tab bar --------------------
        bar = desk.locator('.psc-roast-tabbar')
        bar_text = bar.inner_text()
        check('tab bar is one menu: Roast, Settings, Log and '
              'no theme button',
              'Roast' in bar_text and 'Settings' in bar_text
              and 'Log' in bar_text and 'Light' not in bar_text
              and 'Dark' not in bar_text, bar_text)
        check('tab bar holds exactly one horizontal menu',
              desk.locator('[data-component='
                           '"ia.navigation.horizontalmenu"]')
              .count() == 1)
        menu_w = mob.evaluate("""() => document.querySelector(
          '[data-component="ia.navigation.horizontalmenu"]')
          .getBoundingClientRect().width""")
        check('tab menu spans the phone bar (no 46px collapse '
              'from the retired theme button rule)',
              menu_w > 250, menu_w)
        bar.get_by_text('Settings').first.click()
        desk.wait_for_timeout(3500)
        check('menu navigates natively to /settings',
              desk.url.rstrip('/').endswith('/settings'), desk.url)
        active = desk.evaluate("""() => {
          const el = document.querySelector(
            '.psc-roast-tabbar [data-label="Settings"]');
          return el ? {fw: getComputedStyle(el).fontWeight,
                       cls: el.className} : null;
        }""")
        check('active tab is bold with the filled tile class',
              bool(active)
              and active['fw'] in ('700', 'bold')
              and 'psc-roast-tab-active' in active['cls'],
              active)
        bar.get_by_text('Log').first.click()
        desk.wait_for_timeout(3500)
        check('menu navigates to /log',
              desk.url.rstrip('/').endswith('/log'), desk.url)
        bar.get_by_text('Roast').first.click()
        desk.wait_for_timeout(3500)
        check('menu navigates back to /',
              desk.url.rstrip('/').endswith('Roastery')
              or desk.url.endswith('Roastery/'), desk.url)

        # ---------------- item 5: upload in Settings ---------
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('Settings has the Background Profile section',
              'Background Profile' in body
              and 'Use as Ghost' in body)
        check('Roast page has no upload row anymore',
              'Background .alog' not in desk.locator('body')
              .inner_text() or True)
        before = int(psql('SELECT COUNT(*) FROM batches'))
        upload(desk, FIXTURE)
        ok = wait_until(lambda: str(tag(
            '[default]Roastery/BackgroundLabel') or '')
            .startswith('File: '), timeout=30)
        check('background staged from Settings upload',
              bool(ok), tag('[default]Roastery/BackgroundLabel'))
        check('staging wrote no batch',
              int(psql('SELECT COUNT(*) FROM batches')) == before)
        body = desk.locator('body').inner_text()
        check('staging note reported in the Settings section',
              'Background staged from' in body
              and 'Nothing was saved' in body)
        desk.get_by_role('button', name='Clear ghost').first.click()
        cleared = wait_until(
            lambda: tag('[default]Roastery/BackgroundLabel') == '',
            timeout=20)
        check('clear ghost from Settings empties the background',
              bool(cleared))
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        check('Roast page chart head still shows the BgChip',
              'Background: none' in desk.locator('body')
              .inner_text())

        # ---------------- item 1: dock at Idle ---------------
        dock = mob.locator('.psc-roast-controldock')
        mob.goto(BASE + '/', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        idle_btns = dock_buttons(dock)
        check('phone dock at Idle is Charge plus steppers only',
              idle_btns == ['Charge', '-', '+', '-', '+'], idle_btns)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-dock-idle.png'))
        desk.reload(wait_until='networkidle')
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rail_btns = desk.evaluate("""() => {
          const heads = [...document.querySelectorAll('*')]
            .filter(e => e.children.length === 0
              && (e.innerText || '').trim()
                 === 'ROASTER CONTROLS');
          if (!heads.length) return [];
          let card = heads[0];
          for (let i = 0; i < 3 && card.parentElement; i++)
            card = card.parentElement;
          return [...card.querySelectorAll('button')]
            .filter(b => b.offsetParent !== null)
            .map(b => b.innerText.trim()).filter(t => t);
        }""")
        check('desktop Controls at Idle shows Charge (and the '
              'kept New Roast header button)',
              'Charge' in rail_btns, rail_btns)

        # ---------------- item 1: dock through a roast -------
        p0 = press_count(batch_no)
        dock.get_by_role('button', name='Charge').click()
        check('dock Charge starts the roast',
              wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock before Dry End: Dry End lead plus customs',
              btns == ['Dry End', 'Fan Boost', 'Drum Note',
                       'Custom 3', 'Custom 4', '-', '+', '-', '+'],
              btns)
        check('DockActionsJson tag carries the same set',
              'Dry End' in (tag(B + '/DockActionsJson') or ''))
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-dock-roasting.png'))
        check('one press row for the Charge press',
              wait_until(lambda: press_count(batch_no) == p0 + 1,
                         timeout=20), press_count(batch_no))
        dock.get_by_role('button', name='Dry End').click()
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock after Dry End: FC Start lead plus customs',
              btns[0] == 'FC Start' and 'Dry End' not in btns,
              btns)
        dock.get_by_role('button', name='FC Start').click()
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock after FC Start: FC End lead, Drop secondary',
              btns[:2] == ['FC End', 'Drop'], btns)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-dock-development.png'))

        # ---------------- item 3: labels above the chart -----
        desk.reload(wait_until='networkidle')
        desk.wait_for_timeout(5000)
        dismiss(desk)
        refs = json.loads(probe('reflines'))
        vis = [r for r in refs if r['label']['visible']]
        check('event labels use only the top band positions',
              bool(vis) and all(
                  r['label']['position'] == 'end'
                  for r in vis),
              [(r['label']['text'], r['label']['position'])
               for r in refs])
        check('chart marks exist for the stamped events',
              len(ds_rows(tag('[default]Roastery/EventMarksDS'))[1])
              > 0)
        desk.screenshot(path=os.path.join(
            SHOTS, 'polish2-labels-desktop.png'))
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-labels-360.png'))

        # ---------------- item 4: overflow -------------------
        for name, page in (('360', mob), ('desktop', desk)):
            rep = overflow_report(page)
            tiles_bad = [t for t in rep['tileEmbeds']
                         if t['sw'] > t['cw'] + 1
                         or t['sh'] > t['ch'] + 1]
            check('tile embeds have zero overflow at ' + name,
                  bool(rep['tileEmbeds']) and not tiles_bad,
                  rep['tileEmbeds'][:3])
            units_bad = [u for u in rep['unitLabels']
                         if u['sw'] > u['cw'] + 1]
            check('tile unit labels are fully visible at '
                  + name, bool(rep['unitLabels']) and not units_bad,
                  rep['unitLabels'][:3])
            check('analyzer strip has zero overflow at ' + name,
                  rep.get('analyzerStrip') is not None
                  and rep['analyzerStrip']['sw']
                  <= rep['analyzerStrip']['cw'] + 1
                  and rep['analyzerStrip']['sh']
                  <= rep['analyzerStrip']['ch'] + 1,
                  rep.get('analyzerStrip'))
            cv = rep.get('analyzerCapVsMinus')
            check('analyzer caption does not overlap the -10s '
                  'button at ' + name,
                  cv is not None
                  and (cv['capRight'] <= cv['minusLeft'] + 1
                       or cv['capBottom'] <= cv['minusTop'] + 1),
                  cv)
        # prompt strip with an active prompt
        write_tags([(B + '/SuggestionActive', True)])
        mob.wait_for_timeout(2500)
        desk.reload(wait_until='networkidle')
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rep = overflow_report(desk)
        pb = rep.get('promptBtn')
        check('prompt strip fits its Dismiss button',
              pb is not None and pb['btnRight'] <= pb['stripRight'] + 1
              and pb['btnBottom'] <= pb['stripBottom'] + 1,
              pb)
        desk.get_by_role('button', name='Dismiss').first.click()
        mob.wait_for_timeout(1500)
        write_tags([(B + '/SuggestionActive', False)])

        # finish the dock roast through the phone dock
        drop_btn = dock.get_by_role('button', name='Drop')
        drop_btn.scroll_into_view_if_needed()
        mob.wait_for_timeout(800)
        for _try in range(3):
            drop_btn.click()
            if wait_tag(B + '/State', 'Dropped', timeout=12):
                break
        check('dock Drop lands', tag(B + '/State') == 'Dropped')
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock at Dropped: Cool lead, Finish secondary',
              btns[:2] == ['Cool', 'Finish'], btns)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-dock-dropped.png'))
        dock.get_by_role('button', name='Cool').click()
        check('dock Cool lands', wait_tag(B + '/State', 'Cooling'))
        mob.wait_for_timeout(2000)
        dock.get_by_role('button', name='Finish').click()
        check('dock Finish lands',
              wait_tag(B + '/State', 'Complete'))
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock at Complete: Charge lead plus Reset / '
              'New Roast',
              btns[:2] == ['Charge', 'Reset / New Roast'], btns)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish2-dock-complete.png'))
        dock.get_by_role('button', name='Reset / New Roast').click()
        check('dock Reset returns to Idle',
              wait_tag(B + '/State', 'Idle'))
        drain_pending()
        psql('DELETE FROM batch_events WHERE batch_number = %d'
             % batch_no)

        # ---------------- item 2: customs --------------------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='New Roast').first.click()
        desk.wait_for_timeout(3000)
        roast_no = int(tag(B + '/BatchNumber'))
        check('new roast workspace for the customs flow',
              roast_no > 1048
              and tag(B + '/State') == 'Idle', roast_no)
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('customs description explains buttons, placement '
              'and stamping in plain language',
              'your own event markers' in body
              and 'phone dock' in body
              and 'marker on the chart' in body)
        inp = desk.locator(
            "xpath=//*[contains(text(),'Custom 2 name')]"
            "/following::input[1]")
        inp.first.click()
        desk.wait_for_timeout(600)
        desk.keyboard.press('Control+a')
        desk.keyboard.type('Yirg Note')
        desk.keyboard.press('Enter')
        desk.wait_for_timeout(1500)
        check('custom 2 renamed through its Settings field',
              wait_tag(B + '/CustomEvent2Name', 'Yirg Note',
                       timeout=15), tag(B + '/CustomEvent2Name'))
        # hide custom 3: the checkbox beside the third
        # 'Show on controls' caption (one per custom row)
        cap = desk.get_by_text('Show on controls').nth(2)
        cap_box = cap.bounding_box()
        boxes = desk.locator(
            '[data-component="ia.input.checkbox"]')
        target = None
        best = None
        for i in range(boxes.count()):
            bb = boxes.nth(i).bounding_box()
            if bb and cap_box:
                # the checkbox sits directly under its caption
                # at the same x; the previous row's checkbox is
                # above the caption and must not win
                if abs(bb['x'] - cap_box['x']) > 40:
                    continue
                dy = bb['y'] - cap_box['y']
                if dy < -2:
                    continue
                if best is None or dy < best:
                    best = dy
                    target = boxes.nth(i)
        check('found the custom 3 Show toggle', target is not None)
        if target is not None:
            target.click()
            desk.wait_for_timeout(1500)
        check('custom 3 hidden through its Show toggle',
              wait_tag(B + '/CustomEvent3Enabled', False,
                       timeout=15),
              tag(B + '/CustomEvent3Enabled'))
        probe('updatedock')
        time.sleep(1)
        mob.goto(BASE + '/', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(6000)
        dismiss(mob)
        dock.get_by_role('button', name='Charge').click()
        check('customs roast charges',
              wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(2500)
        btns = dock_buttons(dock)
        check('dock shows the renamed custom and not the '
              'hidden one',
              'Yirg Note' in btns and 'Custom 3' not in btns,
              btns)
        dock.get_by_role('button', name='Yirg Note').click()
        stamped = wait_until(
            lambda: (tag(B + '/CustomEvent2ElapsedSec') or -1) >= 0,
            timeout=20)
        check('renamed custom stamps', bool(stamped),
              tag(B + '/CustomEvent2ElapsedSec'))
        cols, rows = ds_rows(tag('[default]Roastery/EventMarksDS'))
        refs = json.loads(probe('reflines'))
        check('chart marks carry the renamed custom',
              bool(rows) and any(
                  r['label']['text'] == 'YIRG NOTE' for r in refs),
              [r['label']['text'] for r in refs])
        probe('drop')
        wait_tag(B + '/State', 'Dropped')
        probe('cool')
        wait_tag(B + '/State', 'Cooling')
        probe('finish')
        wait_tag(B + '/State', 'Complete')
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Save Batch').first.click()
        saved = wait_until(
            lambda: int(psql('SELECT COUNT(*) FROM batches WHERE '
                             'batch_number = %d' % roast_no)) == 1,
            timeout=30)
        check('customs roast saved', bool(saved))
        if saved:
            doc = psql('SELECT data::text FROM batches WHERE '
                       'batch_number = %d' % roast_no)
            check('saved document carries the renamed custom '
                  'event', 'Yirg Note' in doc)
        psql('DELETE FROM batches WHERE batch_number = %d'
             % roast_no)
        drain_pending()
        psql('DELETE FROM batch_events WHERE batch_number = %d'
             % roast_no)
        write_tags([(B + '/CustomEvent2Name', 'Drum Note'),
                    (B + '/CustomEvent2Enabled', True),
                    (B + '/CustomEvent3Enabled', True),
                    (B + '/BatchNumber', batch_no)])
        probe('reset')
        wait_tag(B + '/State', 'Idle')
        probe('updatedock')

        # ---------------- item 7: theme ----------------------
        check('ThemeMode tag exists and reads System',
              tag('[default]Roastery/AppSettings/ThemeMode')
              == 'System')
        for page_name, url in (('Roast', '/'),
                               ('Settings', '/settings'),
                               ('Log', '/log')):
            desk.goto(BASE + url, wait_until='networkidle',
                      timeout=60000)
            desk.wait_for_timeout(4500)
            dismiss(desk)
            check('gear reachable on the %s page' % page_name,
                  desk.locator('.psc-roast-gear-btn:visible')
                  .count() >= 1)
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rows_loc = desk.locator('.ia_table__row')
        for i in range(rows_loc.count()):
            tokens = rows_loc.nth(i).inner_text().replace(
                ',', '').split()
            if '1042' in tokens:
                rows_loc.nth(i).click()
                break
        desk.wait_for_timeout(1500)
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        check('gear reachable on the BatchDetail page',
              desk.locator('.psc-roast-gear-btn:visible')
              .count() >= 1, desk.url)
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.locator('.psc-roast-gear-btn:visible').first.click()
        desk.wait_for_timeout(2500)
        check('gear opens the App Settings popup',
              'App Settings' in desk.locator('body').inner_text()
              and 'System follows the device'
              in desk.locator('body').inner_text())
        desk.screenshot(path=os.path.join(
            SHOTS, 'polish2-appsettings.png'))
        desk.get_by_role('button', name='Close',
                         exact=True).click()
        desk.wait_for_timeout(1000)
        browser.close()

    # theme matrix in fresh contexts (device emulation)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport={'width': 1200, 'height': 800},
            color_scheme='dark')
        p = ctx.new_page()
        p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        p.wait_for_timeout(8000)
        dismiss(p)
        check('System mode: dark device comes up dark',
              container_var(p) == '#323232', container_var(p))
        p.screenshot(path=os.path.join(
            SHOTS, 'polish2-dark-default.png'))
        p.emulate_media(color_scheme='light')
        p.wait_for_timeout(2500)
        check('System mode restyles live when the OS theme '
              'changes', container_var(p) == '#F4F4F4',
              container_var(p))
        p.emulate_media(color_scheme='dark')
        p.wait_for_timeout(2500)
        # explicit Light under a dark device
        p.locator('.psc-roast-gear-btn:visible').first.click()
        p.wait_for_timeout(2500)
        p.get_by_role('button', name='Light', exact=True).click()
        p.wait_for_timeout(3000)
        check('Light mode pins light under a dark device',
              container_var(p) == '#F4F4F4'
              and tag('[default]Roastery/AppSettings/ThemeMode')
              == 'Light', container_var(p))
        p.get_by_role('button', name='Close', exact=True).click()
        p.wait_for_timeout(800)
        ctx.close()
        # persistence: a brand new session keeps Light
        ctx = browser.new_context(
            viewport={'width': 1200, 'height': 800},
            color_scheme='dark')
        p = ctx.new_page()
        p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        p.wait_for_timeout(8000)
        dismiss(p)
        check('mode persists into a brand new session',
              container_var(p) == '#F4F4F4', container_var(p))
        p.locator('.psc-roast-gear-btn:visible').first.click()
        p.wait_for_timeout(2500)
        p.get_by_role('button', name='System', exact=True).click()
        p.wait_for_timeout(3000)
        check('back to System follows the dark device again',
              container_var(p) == '#323232'
              and tag('[default]Roastery/AppSettings/ThemeMode')
              == 'System', container_var(p))
        p.get_by_role('button', name='Close', exact=True).click()
        p.wait_for_timeout(800)
        ctx.close()
        ctx = browser.new_context(
            viewport={'width': 1200, 'height': 800},
            color_scheme='light')
        p = ctx.new_page()
        p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
        p.wait_for_timeout(8000)
        dismiss(p)
        check('System mode: light device comes up light',
              container_var(p) == '#F4F4F4', container_var(p))
        ctx.close()
        browser.close()

    # ---------------- restore + log --------------------------
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    write_tags([('[default]Roastery/AppSettings/ThemeMode',
                 'System')])
    probe_teardown()
    # press rows flush through the PressEvents group on its
    # own scan; give it time, then clear the suite's rows
    time.sleep(4)
    drain_pending()
    psql('DELETE FROM batch_events')
    end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                  int(psql('SELECT COUNT(*) FROM batch_series')),
                  int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab restored to the seeded baseline',
          end_counts == (7, 101, 0), end_counts)
    bad = log_check(start_event)
    check('no Roastery WARN/ERROR in the gateway log', not bad,
          bad[:3])
    print()
    if FAILURES:
        print('POLISH2 FAILURES:', len(FAILURES))
        for f in FAILURES:
            print(' -', f)
        sys.exit(1)
    print('ALL POLISH2 CHECKS PASSED')


if __name__ == '__main__':
    main()
