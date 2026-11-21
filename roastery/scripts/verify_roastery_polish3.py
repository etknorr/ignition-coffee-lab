#!/usr/bin/env python3
"""Verify the Roastery polish round 1 phase 3 build (Embr
Periscope native toasts for one shot feedback, 2026-11-18)
against the Maker 2027 gateway.

Items covered:
  1. The Embr Periscope module (2027 build) is installed,
     ACTIVE and not quarantined (gateway modules API), and
     the AppSettings PeriscopeAvailable tag is True.
  2. Wiring is in the gateway project library: roastery.core
     show_toast wraps the args based runJavaScriptAsync call,
     and the batches / artisan call sites call it.
  3. Live toasts in a real session: Settings background stage
     and Clear ghost, BatchEdit save (toast text asserted in
     the DOM, desktop screenshot), and a latched alarm Message
     (warning toast on the Roast page, desktop plus 360px,
     with geometry checks against the phone viewport, the
     top offset and the control dock).
  4. PressEvents still writes after the gateway restart the
     module install required (one batch_events row set from a
     real dock Charge press, cleaned up after).
  5. Kill switch: with PeriscopeAvailable False the same
     BatchEdit save still succeeds, no toast appears and no
     client console errors surface; the tag is set back True.

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
GW_CORE = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker/'
           'data/projects/Roastery/ignition/script-python/'
           'roastery/core/code.py')
GW_BATCHES = GW_CORE.replace('core/code.py', 'batches/code.py')
GW_ARTISAN = GW_CORE.replace('core/code.py', 'artisan/code.py')
B = '[default]Roastery/CurrentBatch'
PERI = '[default]Roastery/AppSettings/PeriscopeAvailable'
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


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(
                timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


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
    return wait_until(
        lambda: any(needle in t for t in toast_texts(page)),
        timeout=timeout, step=0.25)


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_p3_start.idb')
    con = sqlite3.connect('/tmp/logs_p3_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_p3_end.idb')
            con = sqlite3.connect('/tmp/logs_p3_end.idb')
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
    "import roastery.core as core",
    "cmd = currentValue.value",
    "if cmd:",
    "    res = None",
    "    try:",
    "        if cmd == 'reset':",
    "            core.reset_batch(); res = 'ok'",
    "        elif cmd == 'clearbg':",
    "            core.clear_background(); res = 'ok'",
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


def sweep_events(max_event_id, timeout=60):
    """Delete batch_events rows above the watermark until the
    PressEvents group has no late write left in flight. The
    group writes asynchronously (250ms scan, longer under
    load), and reset_batch itself records a press, so a single
    delete can be followed by a late landing row."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        drain_pending()
        psql('DELETE FROM batch_events WHERE id > %d'
             % max_event_id)
        time.sleep(3)
        n = int(psql('SELECT COUNT(*) FROM batch_events '
                     'WHERE id > %d' % max_event_id))
        if n == 0:
            return True
    return False


def editor_save(desk, dry_end):
    """Open the BatchEdit slide over for batch 1042 from the
    Log page, set the Dry End time, save. Returns the dock
    locator. Mirrors the polish1 editor walk."""
    def open_once():
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rows_el = desk.locator('.ia_table__row')
        picked = False
        for i in range(rows_el.count()):
            rows_el.nth(i).click()
            desk.wait_for_timeout(900)
            if int(tag('[default]Roastery/SelectedBatchNumber')
                   or 0) == 1042:
                picked = True
                break
        assert picked, 'batch 1042 row not selectable'
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Edit',
                         exact=True).click()
        desk.wait_for_timeout(4500)
        dockv = desk.locator('.docked-view-right')
        assert 'Edit Batch 1042' in dockv.inner_text()
        # Polish round 2 item 2: wait for the fully mounted
        # form (59 inputs in the dock DOM) before typing; in
        # a stalled long lived session the title renders with
        # only a partial mount and fills land nowhere.
        mounted = wait_until(
            lambda: dockv.locator('input').count() >= 59,
            timeout=120, step=0.5)
        if not mounted:
            # Polish round 2 part A: reload recovery. Reload
            # the page once and reopen the editor on the fresh
            # page instance (the item 2 recovery: a fresh
            # instance always renders the form), then poll
            # again; only a second stall fails the assert below.
            print('SUITE NOTE: reload recovery fired in polish3 '
                  'editor_save (mount poll timed out); reloading '
                  'the page and reopening the editor once')
            desk.reload(wait_until='networkidle', timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            desk.get_by_role('button', name='Edit',
                             exact=True).click()
            desk.wait_for_timeout(4500)
            dockv = desk.locator('.docked-view-right')
            assert 'Edit Batch 1042' in dockv.inner_text()
            mounted = wait_until(
                lambda: dockv.locator('input').count() >= 59,
                timeout=120, step=0.5)
        assert mounted, ('editor form never fully rendered '
                         '(dock inputs)')
        return dockv

    def try_type(dockv):
        inp = dockv.locator(
            "xpath=//*[contains(text(),'Dry End time')]"
            "/following::input[1]")
        save_btn = dockv.get_by_role('button',
                                     name='Save Batch')
        # Polish round 2 closing fix: port the v4 suite's
        # proven editor typing technique (its prefill wait and
        # its set_event_time). The old fill() loop raced the
        # editor's asynchronous prefill in an aged session:
        # fill() sets the DOM value without the key events the
        # form's change tracking listens for, and a prefill
        # landing after the fill stomps the typed value, so the
        # form reads pristine and Save Batch (autoDisable)
        # never enables; that crash ended both closing battery
        # runs at the kill switch save, and the reload recovery
        # above covers only the mount poll, not this post
        # typing assert.
        # Step 1, confirm the prefill has settled before
        # typing: wait until the Dry End field holds the value
        # the saved batch document says it prefills with (the
        # v4 suite waits for its FC Start field to show the
        # stamped time the same way before editing anything).
        _doc = json.loads(psql(
            'SELECT data FROM batches WHERE batch_number = 1042'))
        _dry_t = ((_doc.get('events') or {}).get('dryEnd')
                  or {}).get('t')
        _prefill = ('%02d:%02d' % (int(_dry_t) // 60,
                                   int(_dry_t) % 60)
                    if _dry_t is not None else '')
        wait_until(lambda: inp.first.input_value() == _prefill,
                   timeout=30, step=0.5)
        # Step 2, type like a user and confirm the typed value
        # stuck (the v4 set_event_time body): click, select all,
        # press_sequentially so real key events register the
        # edit, Tab, wait, then read the field back; if a late
        # prefill refresh stomped it, retype. The Save enable
        # wait also rechecks the field value, so a stomp during
        # that wait loops back to retyping instead of asserting
        # on a pristine form.
        for _try in range(3):
            for _type_try in range(2):
                inp.first.click()
                inp.first.press('Control+a')
                inp.first.press_sequentially(dry_end, delay=60)
                inp.first.press('Tab')
                desk.wait_for_timeout(1200)
                if inp.first.input_value() == dry_end:
                    break
            enabled = wait_until(
                lambda: (not save_btn.first.is_disabled()
                         and inp.first.input_value() == dry_end),
                timeout=20, step=0.5)
            if enabled:
                return dockv, save_btn, True
        return dockv, save_btn, False

    dockv = open_once()
    dockv, save_btn, enabled = try_type(dockv)
    if not enabled:
        # Round 10: the same kill switch save that the round 2
        # comment names died twice in a row here (resumed
        # battery and standalone rerun) with Save Batch never
        # enabling, while fresh-page probes with the same
        # prefill and both PeriscopeAvailable values, plain
        # remounts, and the full roast plus latch plus reset
        # sequence all pass. The form mounts (59 inputs) but
        # the aged page instance stops applying the edit, the
        # HUNT-46 class. One reload recovery on the fresh page
        # instance, the same remedy the mount poll already
        # uses; only a second failure asserts.
        print('SUITE NOTE: reload recovery fired in polish3 '
              'editor_save (Save never enabled after typing); '
              'reloading the page and reopening the editor once')
        dockv = open_once()
        dockv, save_btn, enabled = try_type(dockv)
    assert enabled, 'editor Save Batch never enabled'
    save_btn.first.click()
    saved = wait_until(
        lambda: 'Saved batch 1042' in dockv.inner_text(),
        timeout=20, step=0.5)
    assert saved, 'editor save did not land'
    return dockv


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    max_event_id = int(psql(
        'SELECT COALESCE(MAX(id), 0) FROM batch_events'))
    doc_1042 = psql(
        'SELECT data FROM batches WHERE batch_number = 1042')
    seeded_alarms = tag(B + '/AlarmDefsJson')
    probe_setup()
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    probe('clearbg')
    # reset_batch records a Reset press and the PressEvents
    # group writes it asynchronously; sweep any late row from
    # the setup reset (and from a previous suite's final reset)
    # before trusting the counts.
    sweep_events(max_event_id)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('counts settle at the seeded baseline after the '
          'setup reset sweep', base_counts == (7, 101, 0),
          base_counts)

    # ---------------- item 1: module and tag ------------------
    st, out = api('GET', '/modules/healthy',
                  params={'search': 'Periscope'})
    items = (out or {}).get('items') or []
    peri = items[0] if items else {}
    check('Periscope module is installed and ACTIVE',
          peri.get('id') == 'com.mussonindustrial.embr.periscope'
          and peri.get('state') == 'ACTIVE', peri)
    check('Periscope is the 2027 build at 0.16.0',
          str(peri.get('version', '')).startswith('0.16.0'),
          peri.get('version'))
    st, out = api('GET', '/modules/quarantined')
    check('no module is quarantined',
          ((out or {}).get('items') or []) == [], out)
    check('PeriscopeAvailable tag is True', tag(PERI) is True)

    # ---------------- item 2: wiring in the library -----------
    core_src = open(GW_CORE).read()
    check('core library has the show_toast wrapper on the '
          'args based runJavaScriptAsync call',
          'def show_toast(self, message' in core_src
          and 'runJavaScriptAsync' in core_src
          and 'PERISCOPE_AVAILABLE_TAG' in core_src)
    check('JS side guards on the periscope global',
          "typeof periscope !== 'undefined'" in core_src,
          [ln for ln in core_src.splitlines()
           if 'typeof periscope' in ln][:1])
    batches_src = open(GW_BATCHES).read()
    artisan_src = open(GW_ARTISAN).read()
    check('batches call sites toast (editor save, roast save, '
          'CSV, JSON, summary)',
          batches_src.count('show_toast') >= 5,
          batches_src.count('show_toast'))
    check('artisan call sites toast (import, staging, .alog)',
          artisan_src.count('show_toast') >= 3,
          artisan_src.count('show_toast'))
    check('core call sites toast (alarm editor, metadata form, '
          'clear ghost, alarm latch publish)',
          core_src.count('show_toast') >= 3
          and 'AlarmMessageText' in core_src
          and 'AlarmMessageSeq' in core_src,
          core_src.count('show_toast'))

    errors = {'desk': [], 'mob': []}

    def watch(page, key):
        page.on('pageerror',
                lambda e: errors[key].append(str(e)))
        page.on('console',
                lambda m: errors[key].append(m.text)
                if m.type == 'error' else None)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600,
                                          'height': 900})
        mob = browser.new_page(viewport={'width': 360,
                                         'height': 740})
        watch(desk, 'desk')
        watch(mob, 'mob')
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle',
                   timeout=60000)
            p.wait_for_timeout(6000)
            dismiss(p)

        # ---------------- item 3a: staging and clear toasts ---
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        upload(desk, FIXTURE)
        staged = wait_until(
            lambda: str(tag('[default]Roastery/BackgroundLabel')
                        or '').startswith('File: '), timeout=30)
        check('background staged from Settings upload',
              bool(staged), tag('[default]Roastery/BackgroundLabel'))
        check('stage success toast fires with the file name',
              bool(wait_toast(
                  desk, 'Background staged from sample-roast.alog',
                  timeout=10)), toast_texts(desk))
        desk.get_by_role('button', name='Clear ghost').first.click()
        cleared = wait_until(
            lambda: tag('[default]Roastery/BackgroundLabel') == '',
            timeout=20)
        check('clear ghost empties the background', bool(cleared))
        check('clear ghost toast fires',
              bool(wait_toast(desk, 'Background cleared',
                              timeout=10)), toast_texts(desk))

        # ---------------- item 3b: BatchEdit save toast -------
        editor_save(desk, '00:10')
        got = wait_toast(desk, 'Batch 1042 saved', timeout=10)
        check('BatchEdit save toast appears in the DOM with '
              'the expected text', bool(got), toast_texts(desk))
        if got:
            desk.screenshot(path=os.path.join(
                SHOTS, 'polish3-toast-desktop.png'))
        check('desktop toast screenshot taken', bool(got))

        # ---------------- item 3c: alarm Message toast --------
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle',
                   timeout=60000)
            p.wait_for_timeout(6000)
            dismiss(p)
        dock = mob.locator('.psc-roast-controldock')
        dock.get_by_role('button', name='Charge').click()
        check('charge starts the roast',
              bool(wait_tag(B + '/State', 'Roasting')))
        press_rows = wait_until(
            lambda: int(psql(
                'SELECT COUNT(*) FROM batch_events WHERE id > %d'
                % max_event_id)) > 0, timeout=30)
        check('PressEvents wrote the Charge press after the '
              'module install restart', bool(press_rows))
        test_alarms = json.dumps([
            {'name': 'Polish3 latch', 'enabled': True,
             'guard': 'None', 'offsetSec': 0, 'source': 'Time',
             'cond': '>=', 'value': 3,
             'message': 'POLISH3 LATCH FIRED', 'action': 'Message'},
            {'name': 'Polish3 banner', 'enabled': True,
             'guard': 'None', 'offsetSec': 0, 'source': 'BT',
             'cond': '>=', 'value': 100,
             'message': 'POLISH3 BANNER', 'action': 'Banner'}])
        write_tags([(B + '/AlarmDefsJson', test_alarms)])
        # Alarm evaluation rides the bean temp change path on
        # a small shared CPU gateway with two sessions open;
        # tier1 waits 150s for its turning point for the same
        # reason, so this window is generous too.
        latched = wait_until(
            lambda: tag(B + '/AlarmMessageText')
            == 'POLISH3 LATCH FIRED', timeout=90)
        check('Message alarm latches the toast value tag',
              bool(latched), tag(B + '/AlarmMessageText'))
        check('banner text still carries banner and latched '
              'message (banner path unchanged)',
              'POLISH3 BANNER' in str(tag(B + '/AlarmText'))
              and 'POLISH3 LATCH FIRED' in str(tag(B + '/AlarmText')),
              tag(B + '/AlarmText'))
        got_d = wait_toast(desk, 'POLISH3 LATCH FIRED', timeout=15)
        check('alarm Message toast fires on the desktop Roast '
              'page', bool(got_d), toast_texts(desk))
        got_m = wait_toast(mob, 'POLISH3 LATCH FIRED', timeout=15)
        check('alarm Message toast fires on the phone Roast '
              'page', bool(got_m), toast_texts(mob))
        if got_m:
            # Polish round 2 closing fix: measure the VISIBLE
            # latch toast, settled, not whatever the first
            # .Toastify__toast in the DOM happens to be doing.
            # Two failure shapes pointed the same way: the
            # closing battery's run 2 measured a toast element
            # at top about -2333 while run 1 with the same
            # code passed, and this fix's first run measured
            # exactly one toast element in the DOM (counts and
            # allTops below) at a fractional top in the entry
            # bounce overshoot, 4.3 px over the banner line.
            # Toastify's bounce in starts the toast at
            # translateY(-3000px) and overshoots before it
            # settles, so a rect read while the animation is
            # in flight is a transient frame, not the rendered
            # position (and a stale or exiting element from an
            # earlier step is the same trap). The measurement
            # now selects among the toasts carrying the latch
            # text the ones actually rendered (displayed,
            # visible, sized, not in a Toastify exit state),
            # takes the last (the live one Toastify appended),
            # and waits for its animations to finish before
            # reading the rect. The assertion below is
            # unchanged: that visible, settled toast must sit
            # on the viewport, clear of the banner and the
            # dock, with no clipped text. The returned counts
            # and allTops keep the other elements in evidence.
            geo = mob.evaluate("""async () => {
              const pick = () => {
                const all = [...document.querySelectorAll(
                  '.Toastify__toast')];
                const latch = all.filter(
                  e => (e.innerText || '')
                         .includes('POLISH3 LATCH FIRED'));
                const vis = latch.filter(e => {
                  const cs = getComputedStyle(e);
                  const r = e.getBoundingClientRect();
                  return cs.display !== 'none'
                    && cs.visibility !== 'hidden'
                    && r.width > 0 && r.height > 0
                    && !e.className.includes('exit');
                });
                const t = vis.length ? vis[vis.length - 1]
                  : (latch.length ? latch[latch.length - 1]
                                  : all[0]);
                return {all, latch, vis, t};
              };
              let sel = pick();
              if (sel.t && sel.t.getAnimations) {
                await Promise.race([
                  Promise.all(sel.t.getAnimations().map(
                    a => a.finished.catch(() => {}))),
                  new Promise(r => setTimeout(r, 5000))]);
                sel = pick();
              }
              const all = sel.all, latch = sel.latch,
                    vis = sel.vis, t = sel.t;
              const d = document.querySelector(
                '.psc-roast-controldock');
              const b = [...document.querySelectorAll('*')].find(
                e => e.children.length === 0
                     && (e.innerText || '')
                        .includes('POLISH3 BANNER'));
              const tr = t.getBoundingClientRect();
              const dr = d ? d.getBoundingClientRect() : null;
              const br = b ? b.getBoundingClientRect() : null;
              return {left: tr.left, right: tr.right,
                      top: tr.top, bottom: tr.bottom,
                      sw: t.scrollWidth, cw: t.clientWidth,
                      dockTop: dr ? dr.top : null,
                      bannerTop: br ? br.top : null,
                      toastCount: all.length,
                      latchCount: latch.length,
                      visibleCount: vis.length,
                      allTops: all.map(e => Math.round(
                        e.getBoundingClientRect().top))};
            }""")
            # Periscope on mobile spans the full width at the
            # very top by design (its container drops the dock
            # padding on small screens). The no overlap contract
            # is against the app's own persistent surfaces: the
            # toast must not cover the alarm banner text or the
            # control dock, and its own text must not clip.
            check('360px toast is fully inside the viewport, '
                  'does not overlap the alarm banner or the '
                  'control dock, and has no clipped text',
                  geo['left'] >= 0 and geo['right'] <= 361
                  and geo['top'] >= 0
                  and (geo['bannerTop'] is None
                       or geo['bottom'] <= geo['bannerTop'] + 1)
                  and (geo['dockTop'] is None
                       or geo['bottom'] <= geo['dockTop'] + 1)
                  and geo['sw'] <= geo['cw'] + 1, geo)
            mob.screenshot(path=os.path.join(
                SHOTS, 'polish3-toast-360.png'))
        check('360px toast screenshot taken', bool(got_m))

        # ---------------- item 3d: identical text latches twice
        # Polish phase 4 (HUNT-19): two Message alarms carrying
        # the SAME message text latch at different times. The
        # AlarmMessageText value does not change for the second
        # latch, so a text keyed trigger would miss it; the
        # AlarmMessageSeq counter must increment for both, and
        # the Roast page (watching the sequence) must toast
        # twice. A page side scanner counts distinct toast
        # elements, so the 5 second autoClose cannot hide the
        # first toast before the second lands.
        seq0 = int(tag(B + '/AlarmMessageSeq') or 0)
        start_ms = tag(B + '/StartTime')
        if isinstance(start_ms, str):
            import datetime as _dt
            start_ms = int(_dt.datetime.strptime(
                start_ms.replace('T', ' ').rstrip('Z')[:19],
                '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        elapsed_now = int(time.time() - float(start_ms) / 1000.0)
        desk.evaluate("""() => {
          window.__p4seen = new Set();
          window.__p4n = 0;
          window.__p4scan = setInterval(() => {
            document.querySelectorAll('.Toastify__toast')
              .forEach(el => {
                if ((el.innerText || '').includes(
                      'POLISH3 SAME TEXT')) {
                  if (!el.dataset.p4id) {
                    el.dataset.p4id = String(++window.__p4n);
                  }
                  window.__p4seen.add(el.dataset.p4id);
                }
              });
          }, 200);
        }""")
        same_text_alarms = json.dumps([
            {'name': 'Polish4 same A', 'enabled': True,
             'guard': 'None', 'offsetSec': 0, 'source': 'Time',
             'cond': '>=', 'value': max(1, elapsed_now - 5),
             'message': 'POLISH3 SAME TEXT', 'action': 'Message'},
            {'name': 'Polish4 same B', 'enabled': True,
             'guard': 'None', 'offsetSec': 0, 'source': 'Time',
             'cond': '>=', 'value': elapsed_now + 6,
             'message': 'POLISH3 SAME TEXT', 'action': 'Message'}])
        write_tags([(B + '/AlarmDefsJson', same_text_alarms),
                    (B + '/_AlarmFiredJson', '')])
        seq2 = wait_until(
            lambda: int(tag(B + '/AlarmMessageSeq') or 0)
            >= seq0 + 2, timeout=90)
        check('identical Message text latching twice increments '
              'AlarmMessageSeq twice (HUNT-19)',
              bool(seq2),
              'seq %s -> %s' % (seq0, tag(B + '/AlarmMessageSeq')))
        check('AlarmMessageText holds the shared text after '
              'both latches', tag(B + '/AlarmMessageText')
              == 'POLISH3 SAME TEXT', tag(B + '/AlarmMessageText'))
        two_toasts = wait_until(
            lambda: desk.evaluate(
                'window.__p4seen ? window.__p4seen.size : 0')
            >= 2, timeout=30)
        check('both identical text latches toast on the '
              'desktop Roast page (HUNT-19)', bool(two_toasts),
              desk.evaluate(
                  'window.__p4seen ? window.__p4seen.size : 0'))
        desk.evaluate('clearInterval(window.__p4scan)')
        write_tags([(B + '/AlarmDefsJson', seeded_alarms)])
        probe('reset')
        wait_tag(B + '/State', 'Idle')

        # ---------------- item 5: kill switch -----------------
        write_tags([(PERI, False)])
        check('PeriscopeAvailable set False for the kill '
              'switch pass', tag(PERI) is False)
        desk.wait_for_timeout(1500)
        editor_save(desk, '00:12')
        desk.wait_for_timeout(3500)
        check('save still succeeds with toasts disabled and '
              'no toast appears',
              desk.locator('.Toastify__toast').count() == 0,
              toast_texts(desk))
        peri_errors = [e for k in errors for e in errors[k]
                       if 'periscope' in e.lower()
                       or 'runjavascript' in e.lower()]
        check('no periscope client errors with the module '
              'gated off', peri_errors == [], peri_errors[:3])
        write_tags([(PERI, True)])
        check('PeriscopeAvailable restored True',
              tag(PERI) is True)
        browser.close()

    all_errors = errors['desk'] + errors['mob']
    check('no page errors during the whole suite',
          all_errors == [], all_errors[:3])

    # ---------------- restore ---------------------------------
    psql("UPDATE batches SET data = '%s'::jsonb "
         'WHERE batch_number = 1042' % doc_1042.replace(
             "'", "''"))
    drain_pending()
    psql('DELETE FROM batch_events WHERE id > %d' % max_event_id)
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    # The final reset's own press row lands asynchronously
    # through the group; sweep until no late row remains.
    sweep_events(max_event_id)
    probe_teardown()
    end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                  int(psql('SELECT COUNT(*) FROM batch_series')),
                  int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab back to the seeded baseline',
          end_counts == base_counts, end_counts)
    state = read_tags([B + '/State', B + '/FanLevel',
                       B + '/HeatLevel', B + '/BatchNumber',
                       B + '/ActiveSource',
                       '[default]Roastery/BackgroundLabel',
                       '[default]Roastery/AppSettings/ThemeMode',
                       PERI])
    check('workspace clean: Idle, defaults, background '
          'cleared, theme System, PeriscopeAvailable True',
          state == ['Idle', 5, 5, 1042, 'Simulated', '',
                    'System', True], state)
    check('alarm table restored to the seeded definitions',
          tag(B + '/AlarmDefsJson') == seeded_alarms)
    bad = log_check(start_event)
    check('no roastery WARN or ERROR in the gateway log',
          bad == [], bad[:3])

    print()
    if FAILURES:
        print('POLISH3 RESULT: %d FAILURES: %s'
              % (len(FAILURES), FAILURES))
        sys.exit(1)
    print('POLISH3 RESULT: ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
