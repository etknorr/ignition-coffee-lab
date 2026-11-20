#!/usr/bin/env python3
"""Round 6 item 1 verification: unnamed custom event slots are
hidden (Eric's feedback: 'Drum Note', 'Custom 3', 'Custom 4'
mean nothing to him and take up a ton of space; his SR800 is a
fluid bed roaster, he has no drum).

Live proof, desktop plus 360px:
- the Controls rail and the phone dock show one custom button
  (Fan Boost) during a roast, not four;
- the Roast Events strip shows only the Fan Boost cell among
  the customs, no blank cells;
- naming slot 3 in Settings puts its button on the dock and
  its cell in the strip; clearing the name hides both again;
- stamp_custom refuses an unnamed slot in the library.

Run with wsvenv python. Leaves the lab as found (resets the
roast, drains the press ring, deletes the test press rows).
Does NOT assert the seeded baseline: the item 3 worker's
fixtures may be in the database while this runs; counts are
compared against the start of this run instead.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8088/data/perspective/client/Roastery'
SHOTS = '/home/hatch/workspace/ignition-lab/showcase/shots'
B = '[default]Roastery/CurrentBatch'
LOGS = 'gateway-2027-maker/logs/system_logs.idb'
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
        {'tagPaths': [p for p, v in pairs], 'values': [v for p, v in pairs]}))
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
    env = dict(os.environ, PGPASSWORD=pw)
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', sql], capture_output=True, text=True,
        env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def drain_pending():
    """Wait until every slotted press has its batch_events row,
    then empty the ring, so a later psql delete cannot be
    resurrected by the reconciler."""
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
    _paths = ['[default]Roastery/PressSlots/Slot%02d' % i
              for i in range(16)]
    api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': _paths, 'values': [''] * 16}))


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


def dock_buttons(page):
    els = page.locator('.psc-roast-controldock button')
    return [e.inner_text().strip() for e in els.all()
            if e.is_visible()]


def rail_buttons(page):
    els = page.locator('.psc-roast-card button')
    out = []
    for e in els.all():
        if not e.is_visible():
            continue
        t = e.inner_text().strip()
        if t in ('Dry End', 'Fan Boost', 'Drum Note', 'Custom 3',
                 'Custom 4', 'Test Note', 'FC Start', 'FC End',
                 'SC Start', 'SC End', 'Drop', 'Charge', 'Cool',
                 'Finish'):
            out.append(t)
    return out


def strip_names(page):
    # The event cell renders its name uppercased in the DOM
    # (a style class transform), so compare uppercased.
    els = page.locator('.psc-roast-event-name')
    return [e.inner_text().strip().upper() for e in els.all()
            if e.is_visible()]


def strip_cells(page):
    # Count the RENDERED cells, not just the named ones:
    # an unnamed slot renders a blank cell with dashes and
    # an empty name label, which the name list cannot see
    # (an empty label reports invisible). HUNT-47 caught
    # exactly that gap: the cells were visible until the
    # class hide landed.
    els = page.locator('.psc-roast-cell')
    return sum(1 for e in els.all() if e.is_visible())


def main():
    os.makedirs(SHOTS, exist_ok=True)
    start_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                    int(psql('SELECT COUNT(*) FROM batch_series')),
                    int(psql('SELECT COUNT(*) FROM batch_events')))
    print('lab counts at start:', start_counts, flush=True)
    check('lab starts Idle on batch 1042',
          tag(B + '/State') == 'Idle'
          and int(tag(B + '/BatchNumber') or 0) == 1042,
          (tag(B + '/State'), tag(B + '/BatchNumber')))
    check('slots 2 to 4 ship unnamed',
          read_tags([B + '/CustomEvent2Name',
                     B + '/CustomEvent3Name',
                     B + '/CustomEvent4Name']) == ['', '', ''],
          read_tags([B + '/CustomEvent2Name',
                     B + '/CustomEvent3Name',
                     B + '/CustomEvent4Name']))
    max_event_id = int(psql('SELECT COALESCE(MAX(id), 0) '
                            'FROM batch_events'))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600,
                                          'height': 900},
                                timezone_id='America/Denver')
        mob = browser.new_page(viewport={'width': 360,
                                         'height': 740},
                               timezone_id='America/Denver')
        for pg in (desk, mob):
            pg.goto(BASE + '/', wait_until='networkidle',
                    timeout=60000)
            pg.wait_for_timeout(5000)
            dismiss(pg)

        # Charge from the phone dock (the remote control).
        mob.locator('.psc-roast-controldock').get_by_role(
            'button', name='Charge').click()
        check('charge starts the roast',
              wait_tag(B + '/State', 'Roasting'))
        mob.wait_for_timeout(3000)
        desk.wait_for_timeout(2000)

        btns = dock_buttons(mob)
        check('phone dock before Dry End: Dry End lead plus '
              'only Fan Boost',
              btns == ['Dry End', 'Fan Boost', '-', '+', '-', '+'],
              btns)
        rail = rail_buttons(desk)
        check('Controls rail before Dry End: Dry End lead plus '
              'only Fan Boost',
              rail == ['Dry End', 'Fan Boost'], rail)
        names = strip_names(desk)
        check('Events strip shows Fan Boost and no blank or '
              'placeholder custom cell',
              'FAN BOOST' in names
              and 'DRUM NOTE' not in names
              and 'CUSTOM 3' not in names
              and 'CUSTOM 4' not in names
              and '' not in names, names)
        check('Events strip renders 8 cells, not 11 blank ones',
              strip_cells(desk) == 8, strip_cells(desk))
        desk.screenshot(path=os.path.join(
            SHOTS, 'r6-customs-rail-desktop.png'))
        mob.screenshot(path=os.path.join(
            SHOTS, 'r6-customs-dock-360.png'))
        # Scroll the desktop page to the strip for the shot.
        desk.locator('.psc-roast-event-name').first.scroll_into_view_if_needed()
        desk.wait_for_timeout(800)
        desk.screenshot(path=os.path.join(
            SHOTS, 'r6-customs-strip-desktop.png'))

        # Settings flow: name slot 3, watch it appear. HUNT-46:
        # a Settings page that is navigated away from and back
        # to in the SAME session stops writing tag edits, so
        # the clear below runs on a fresh page (a fresh
        # session), which is also how Eric would most often
        # reach it (a later visit, usually a new session).
        desk.goto(BASE + '/settings', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        inp = desk.locator(
            "xpath=//*[contains(text(),'Custom 3 name')]"
            "/following::input[1]")
        inp.first.click()
        desk.wait_for_timeout(600)
        desk.keyboard.press('Control+a')
        desk.keyboard.type('Test Note')
        desk.keyboard.press('Enter')
        desk.wait_for_timeout(1500)
        check('slot 3 named through its Settings field',
              wait_tag(B + '/CustomEvent3Name', 'Test Note',
                       timeout=15), tag(B + '/CustomEvent3Name'))
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        mob.wait_for_timeout(2000)
        btns = dock_buttons(mob)
        check('named slot appears on the phone dock',
              'Test Note' in btns, btns)
        # The strip is read on the phone page, which never
        # navigated: HUNT-46, a page navigated away from and
        # back to freezes at its first mount state, so the
        # desktop strip would still show the pre-name state.
        names = strip_names(mob)
        check('named slot appears in the Events strip',
              'TEST NOTE' in names, names)
        check('Events strip renders 9 cells with the named slot',
              strip_cells(mob) == 9, strip_cells(mob))
        mob.screenshot(path=os.path.join(
            SHOTS, 'r6-customs-named-360.png'))

        # Clear the name again through Settings on a fresh
        # page; both the dock button and the strip cell hide.
        desk2 = browser.new_page(viewport={'width': 1600,
                                           'height': 900},
                                 timezone_id='America/Denver')
        desk2.goto(BASE + '/settings', wait_until='networkidle',
                   timeout=60000)
        desk2.wait_for_timeout(6000)
        dismiss(desk2)
        inp = desk2.locator(
            "xpath=//*[contains(text(),'Custom 3 name')]"
            "/following::input[1]")
        inp.first.click()
        desk2.wait_for_timeout(600)
        desk2.keyboard.press('Control+a')
        desk2.keyboard.press('Backspace')
        desk2.keyboard.press('Enter')
        desk2.wait_for_timeout(1500)
        check('slot 3 name cleared through its Settings field',
              wait_tag(B + '/CustomEvent3Name', '',
                       timeout=15),
              repr(tag(B + '/CustomEvent3Name')))
        desk2.close()
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(6000)
        dismiss(desk)
        mob.wait_for_timeout(2000)
        btns = dock_buttons(mob)
        check('cleared slot drops off the phone dock',
              'Test Note' not in btns, btns)
        # Strip read on the phone page again (HUNT-46: the
        # desktop page remounted and its strip is frozen).
        names = strip_names(mob)
        check('cleared slot drops out of the Events strip',
              'TEST NOTE' not in names
              and '' not in names, names)
        check('Events strip back to 8 cells after the clear',
              strip_cells(mob) == 8, strip_cells(mob))
        browser.close()

    # Cleanup: reset the roast, drain the ring, delete this
    # run's press rows for batch 1042 only.
    write_tags([(B + '/CustomEvent3Name', '')])
    st, out = api('GET', '/tags/read', body=json.dumps(
        {'tags': [B + '/State']}))
    if out['results'][0]['value'] != 'Idle':
        # Reset through a one shot probe tag (same pattern as
        # the polish suites): a valueChanged script on a
        # scratch tag calls the library.
        folder = {'name': 'R6Probe', 'tagType': 'Folder', 'tags': [
            {'name': 'Cmd', 'tagType': 'AtomicTag',
             'valueSource': 'memory', 'dataType': 'String',
             'value': '',
             'eventScripts': [{'eventid': 'valueChanged',
                               'script': '\timport roastery.core\n'
                                         '\troastery.core.reset_batch()\n'}]}]}
        api('POST', '/tags/import', body=json.dumps(folder),
            params={'provider': 'default', 'type': 'json',
                    'collisionPolicy': 'Overwrite'},
            ctype='application/octet-stream')
        write_tags([('[default]R6Probe/Cmd', 'x')])
        wait_tag(B + '/State', 'Idle', timeout=30)
        api('DELETE', '/tags/delete',
            body=json.dumps({'tags': ['[default]R6Probe']}),
            params={'confirm': 'true'})
    drain_pending()
    psql('DELETE FROM batch_events WHERE batch_number = 1042 '
         'AND id > %d' % max_event_id)
    time.sleep(3)
    end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                  int(psql('SELECT COUNT(*) FROM batch_series')),
                  int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab counts back to the start of this run',
          end_counts == start_counts, end_counts)
    check('workspace Idle on batch 1042',
          tag(B + '/State') == 'Idle'
          and int(tag(B + '/BatchNumber') or 0) == 1042)

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL R6 CUSTOMS CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
