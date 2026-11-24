#!/usr/bin/env python3
"""Roastery v3 verification: database CRUD via named queries, the
scripting library, style classes, SQL historian, RoasterSource.

Desktop pass (1600x1000):
  light shot -> toggle dark -> dark shot -> set BatchNumber 2001 ->
  short roast (Charge, Dry End, FC Start, stepper) -> Settings
  MetaForm round trip (Farm, WeightOut) -> Drop, Cool, Finish ->
  Save Batch -> verify the batches row and batch_series rows in
  Postgres -> Log page shot -> Edit slide-over (prefill check,
  shot) -> edit Farm and WeightOut -> save -> reopen editor to
  verify persistence -> New Batch 2002 via the create form ->
  delete it via the confirm flow -> verify gone -> Use as Ghost
  from batch 2001 -> Main with overlay -> reset to clean Idle.
Mobile pass (390x844): dark mobile shot, no overlays, no overflow.

Run with wsvenv python.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api27m
from playwright.sync_api import sync_playwright

URL = 'http://localhost:8088/data/perspective/client/Roastery/'
# HUNT-107: LAB used to resolve from __file__, so running the
# repo copy looked for pg-lab-password.txt next to the script
# and crashed with FileNotFoundError, and wrote screenshots
# into the repo tree. Every other suite points at the lab dir.
LAB = '/home/hatch/workspace/ignition-lab'
SHOTS = os.path.join(LAB, 'showcase', 'shots')
B = '[default]Roastery/CurrentBatch'
R = '[default]Roastery'
TM = '[default]Roastery/AppSettings/ThemeMode'
FAILURES = []
TEST_BATCH = 2001
SCRATCH_BATCH = 2002


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name +
          ((' :: ' + str(detail)) if detail else ''))
    if not ok:
        FAILURES.append(name)


def read_tags(paths):
    st, out = api27m.api('GET', '/tags/read',
                         body=json.dumps({'tags': paths}))
    assert st == 200, (st, out)
    return {p.split('/')[-1]: r.get('value')
            for p, r in zip(paths, out['results'])}


def write_tags(pairs):
    st, out = api27m.api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': [p for p, _ in pairs],
         'values': [v for _, v in pairs]}))
    assert st == 200, (st, out)


def sql(query):
    # HUNT-107, part 2: pg-lab-password.txt is a stale
    # duplicate whose content differs from .roastery-pgpass,
    # and the role password comes from .roastery-pgpass (the
    # recovery path creates it from that file), so the old
    # read failed auth after the VM replacement recovery.
    # Every other suite reads .roastery-pgpass; this one
    # does now too.
    pw = open(os.path.join(LAB, '.roastery-pgpass')).read().strip()
    env = dict(os.environ, PGPASSWORD=pw)
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', query], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def click_row(page, label):
    """Select a table row by its batch number cell text. Playwright
    hit testing fights the Perspective table (ancestors report as
    intercepting), so click the row element in the DOM instead.
    Verify the selection took: the Delete button enables only
    when a batch is selected. HUNT-110 drive-by: the table can
    re-render under the click while it settles from a refresh
    (the create flow sends one), and a click on a detached cell
    node is silently lost, so retry the cell click until the
    selection shows."""
    for _ in range(5):
        ok = page.evaluate("""(label) => {
          const cells = [...document.querySelectorAll('.ia_table .content')];
          const cell = cells.find(e => e.textContent.trim() === label);
          if (!cell) return false;
          // The virtualized table takes its row click from the cell
          // content div itself; clicking the row container does nothing.
          cell.click();
          return true;
        }""", label)
        if not ok:
            raise RuntimeError(f'row not found: {label}')
        page.wait_for_timeout(1200)
        try:
            if page.get_by_role('button', name='Delete',
                                exact=True).first.is_enabled():
                return
        except Exception:
            pass
        page.wait_for_timeout(1000)
    raise RuntimeError(f'row not selected: {label}')


def dismiss_modal(page):
    if page.get_by_text('Personal Use Only').count() > 0:
        try:
            page.get_by_text('AGREE & CLOSE').first.click(timeout=8000)
        except Exception:
            box = page.locator('body').bounding_box()
            page.mouse.click(box['width'] / 2, box['height'] * 0.62)
        page.wait_for_timeout(2500)


def scroll_top(page):
    page.evaluate("""() => {
        window.scrollTo(0, 0);
        document.querySelectorAll('*').forEach(el => {
            if (el.scrollTop) el.scrollTop = 0;
        });
    }""")
    page.wait_for_timeout(700)


def click_button(page, name, exact=False):
    """exact=True when the name is a substring of another button
    on the same page: the ConfirmRow sits above the buttons row
    in the BatchesPanel, so a plain 'Delete' click matches the
    hidden 'Confirm Delete' button first and arms nothing
    (HUNT-110 drive-by)."""
    loc = page.get_by_role('button', name=name, exact=exact)
    try:
        loc.first.click(timeout=10000)
    except Exception:
        page.wait_for_timeout(1500)
        loc.first.click(force=True, timeout=10000)
    page.wait_for_timeout(700)


def js_click_button(page, name):
    """Click a button by its exact text through the DOM, bypassing
    hit testing. HUNT-110 drive-by: in a long session the
    BatchesPanel layout can shift under a Playwright click (the
    Delete button was observed to move 79px between the click
    and the check), so a coordinate click can miss the button
    even though it is enabled and visible. A DOM click still
    exercises the app's own handler end to end; it only skips
    the browser's hit test."""
    page.evaluate("""(name) => {
      const b = [...document.querySelectorAll('button')].find(
        e => e.textContent.trim() === name);
      if (!b) throw new Error('no button: ' + name);
      b.click();
    }""", name)
    page.wait_for_timeout(700)


def set_theme_ui(page, theme):
    """HUNT-110: the header 'Theme: light' / 'Theme: dark'
    button this suite used to click no longer exists; theme
    lives in App Settings now (System, Light, Dark buttons
    behind the gear). Drive that flow, the same pattern
    verify_r13_ui.py uses: gear, theme button, Close, and
    wait for the ThemeMode tag to follow. Never a direct
    tag write. If the gear click times out, reload once for
    a fresh session and retry, as r13_ui does."""
    try:
        page.locator('.psc-roast-gear-btn:visible').first.click(
            timeout=20000)
    except Exception:
        print('set_theme_ui: gear click timed out, reloading '
              'the page once for a fresh session', flush=True)
        page.reload()
        page.wait_for_timeout(4000)
        page.locator('.psc-roast-gear-btn:visible').first.click(
            timeout=20000)
    page.wait_for_timeout(900)
    page.get_by_role('button', name=theme, exact=True).first.click(
        timeout=20000)
    ok = False
    for _ in range(30):
        if read_tags([TM])['ThemeMode'] == theme:
            ok = True
            break
        page.wait_for_timeout(1000)
    check('theme %s set through App Settings UI' % theme,
          ok, read_tags([TM])['ThemeMode'])
    click_button(page, 'Close')


def click_tab(page, label):
    """HUNT-110: the bottom tab bar is a horizontalmenu, not
    buttons; its items are Roast, Settings, Log. Click the
    item by its label inside the tab bar."""
    page.locator('.psc-roast-tabbar').get_by_text(label, exact=True) \
        .first.click(timeout=10000)
    page.wait_for_timeout(1500)


def reset_via_dock(page):
    """HUNT-110: the old persistent Reset button is gone; the
    dock offers Reset only at Complete, as 'Reset / New
    Roast'. Drive the roast to Complete through the dock
    (Drop, Cool, Finish as the state requires), then Reset.
    From a fresh roast the phase-aware dock only offers Drop
    once the event chain reaches it, so stamp Dry End, FC
    Start, FC End in order until Drop is on offer. Works
    from Roasting, Dropped, Cooling, Complete, or Idle."""
    # HUNT-110 drive-by: the dock lives on the Roast page only;
    # if a flaky navigation left us on /log, go home first.
    if not page.url.rstrip('/').endswith('Roastery'):
        click_tab(page, 'Roast')
        page.wait_for_timeout(1500)
    state = read_tags([B + '/State'])['State']
    if state == 'Roasting':
        for name in ('Dry End', 'FC Start', 'FC End'):
            if page.get_by_role('button', name='Drop',
                                exact=True).count() > 0:
                break
            if page.get_by_role('button', name=name,
                                exact=True).count() > 0:
                click_button(page, name)
                page.wait_for_timeout(1000)
        click_button(page, 'Drop')
        page.wait_for_timeout(2000)
        state = 'Dropped'
    if state == 'Dropped':
        click_button(page, 'Cool')
        page.wait_for_timeout(1500)
        state = 'Cooling'
    if state == 'Cooling':
        click_button(page, 'Finish')
        page.wait_for_timeout(2000)
        state = 'Complete'
    if state == 'Complete':
        click_button(page, 'Reset / New Roast', exact=True)
        page.wait_for_timeout(2500)


def meta_form_fields(page):
    """HUNT-110: the live batch metadata form moved from the
    old Roast Setup popup to the Settings page MetaForm (the
    same 16 FORM_MEMBERS first, 36 inputs total). Open
    Settings, wait for the submit to be enabled and the Farm
    value to settle across two reads (the form data loads
    async after the view mounts), and return the form
    fields. Farm is index 3, WeightOutG index 15, as in the
    old popup."""
    click_tab(page, 'Settings')
    page.wait_for_timeout(3000)
    submit = page.get_by_role('button', name='Save Batch Details',
                              exact=True).first
    for _ in range(20):
        try:
            if submit.is_enabled():
                break
        except Exception:
            pass
        page.wait_for_timeout(1000)
    submit.scroll_into_view_if_needed()
    fields = page.locator('input.ia_form__field, '
                          'textarea.ia_form__field')
    # HUNT-110 drive-by: the form data loads async, and a
    # fill raced against a late load is silently overwritten,
    # so the submit then writes the old values. Do not hand
    # the fields back until the Farm value is stable.
    last = None
    for _ in range(20):
        cur = fields.nth(3).input_value()
        if cur and cur == last:
            break
        last = cur
        page.wait_for_timeout(1000)
    return fields


def save_meta_form(page, fields, farm, weight):
    """HUNT-110 drive-by: fill the MetaForm, confirm the
    fills stuck, submit, and confirm the tags moved. The
    submit was observed to silently do nothing once on a
    freshly restarted gateway (rerun4 v2 and v3: no note, no
    tag change, while the same flow passed warm), so retry
    the fill and the submit once before giving up."""
    for attempt in range(4):
        # HUNT-110 drive-by: the submit click is lost
        # intermittently in a long session (probe9 proves the
        # form, the fill, and the submit all work when the
        # interaction lands). On the last attempt, re-mount the
        # form first: leave the Settings page and come back so
        # the startup script re-runs and a fresh form loads.
        if attempt == 3:
            click_tab(page, 'Roast')
            page.wait_for_timeout(1500)
            fields = meta_form_fields(page)
        fields.nth(3).fill(farm)
        fields.nth(15).fill(weight)
        # HUNT-110 drive-by: Tab out of the weight field after
        # filling. The number field only commits its value to
        # the form on blur, and a submit raced ahead of that
        # blur writes the old 0.0 (rerun10 v3 wrote the farm
        # but not the weight).
        fields.nth(15).press('Tab')
        page.wait_for_timeout(600)
        try:
            stuck = (fields.nth(3).input_value() == farm
                     and float(fields.nth(15).input_value())
                     == float(weight))
        except Exception:
            stuck = False
        if not stuck:
            continue
        # Alternate a DOM click: the submit click is lost
        # intermittently in a long session, the same class of
        # flake as the Delete arm.
        if attempt in (1, 3):
            js_click_button(page, 'Save Batch Details')
        else:
            click_button(page, 'Save Batch Details')
        page.wait_for_timeout(1500)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        if v['Farm'] == farm and float(v['WeightOutG']) == float(weight):
            return True
    return False


def theme_var(page):
    return page.evaluate(
        "getComputedStyle(document.documentElement)"
        ".getPropertyValue('--containerRoot')").strip()


def overlay_count(page):
    return page.evaluate("""() => [...document.querySelectorAll(
      '.ia_qualityOverlay')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0; }).length""")


def open_session(page):
    page.goto(URL, wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(9000)
    dismiss_modal(page)


def form_fields(page):
    # HUNT-110: the batch editor is a slide-over dock now, not
    # a popup; its root class scopes the form fields. The form
    # grew from 17 fields to 51, but the first 17 keep their
    # order: batch number, then the 16 metadata members, so
    # Farm is still index 4 and WeightOutG index 16.
    editor = page.locator('.psc-roast-dock-editor')
    return editor.locator('input.ia_form__field, '
                          'textarea.ia_form__field')


def main():
    sql(f'DELETE FROM batches WHERE batch_number IN ({TEST_BATCH}, {SCRATCH_BATCH})')
    # Normalize the live batch tags so a rerun starts from the same
    # place (the app's Reset handles roast state in the session).
    write_tags([(B + '/Farm', 'Buku Abel'), (B + '/WeightOutG', 0.0),
                (B + '/BatchNumber', 1042), (B + '/FanLevel', 5),
                (B + '/HeatLevel', 5)])
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        open_session(page)
        if read_tags([B + '/State'])['State'] != 'Idle':
            # HUNT-110: Reset is a dock action at Complete
            # only, as 'Reset / New Roast'.
            reset_via_dock(page)
            page.wait_for_timeout(2500)

        # ---------- light + dark desktop shots ----------
        check('session starts light', theme_var(page) == '#FAFAFA',
              theme_var(page))
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-light-desktop.png'))
        print('shot roastery-v3-light-desktop.png')
        check('no quality overlays on idle main (light)',
              overlay_count(page) == 0, overlay_count(page))
        set_theme_ui(page, 'Dark')
        check('dark after toggle', theme_var(page) == '#161616',
              theme_var(page))
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-dark-desktop.png'))
        print('shot roastery-v3-dark-desktop.png')
        check('no quality overlays on idle main (dark)',
              overlay_count(page) == 0, overlay_count(page))

        # style classes reach the rendered DOM (psc- prefixed)
        n_psc = page.evaluate("""() => document.querySelectorAll(
            '.psc-roast-card').length""")
        check('style classes applied in DOM', n_psc >= 3, n_psc)

        # SQL historian is receiving BeanTempF history
        n_hist = sql("SELECT count(*) FROM sqlth_te WHERE tagpath LIKE "
                     "'%currentbatch/beantempf%'")
        check('sql historian knows the bean temp tag', n_hist != '0',
              n_hist)

        # ---------- short roast ----------
        write_tags([(B + '/BatchNumber', TEST_BATCH)])
        click_button(page, 'Charge')
        # HUNT-110 drive-by: the State read right after the
        # click raced the gateway handler (one rerun read Idle
        # while the roast then started fine), so poll instead
        # of asserting on a single immediate read.
        charging = False
        for _ in range(20):
            if read_tags([B + '/State'])['State'] == 'Roasting':
                charging = True
                break
            page.wait_for_timeout(500)
        check('charging after Charge', charging)
        page.wait_for_timeout(4000)
        check('no quality overlays while roasting',
              overlay_count(page) == 0, overlay_count(page))
        click_button(page, 'Dry End')
        check('dry end stamped',
              (read_tags([B + '/DryEndElapsedSec'])['DryEndElapsedSec']
               or -1) >= 0)
        click_button(page, 'FC Start')
        fc = -1
        for _ in range(6):
            fc = read_tags([B + '/FirstCrackStartElapsedSec'])[
                'FirstCrackStartElapsedSec']
            if fc is not None and fc >= 0:
                break
            page.wait_for_timeout(600)
        check('fc start stamped', fc is not None and fc >= 0, fc)
        fan0 = read_tags([B + '/FanLevel'])['FanLevel']
        # HUNT-110: name='+' without exact=True also matches
        # the analyzer '+10s' button, which sorts first, so
        # nth(0) used to seek the analyzer instead of stepping
        # the fan. Exact match keeps only the two steppers,
        # fan first.
        page.get_by_role('button', name='+', exact=True).nth(0).click()
        page.wait_for_timeout(600)
        check('fan stepper stepped',
              read_tags([B + '/FanLevel'])['FanLevel'] == fan0 + 1)
        samples = read_tags([R + '/CurveSamples'])['CurveSamples']
        n_samples = len(json.loads(samples)['rows']) \
            if isinstance(samples, str) else -1
        check('curve samples being recorded', n_samples >= 1, n_samples)

        # ---------- Config form round trip (tags) ----------
        # HUNT-110: the Roast Setup popup is gone; the same
        # form lives on the Settings page as the MetaForm.
        fields = meta_form_fields(page)
        n = fields.count()
        check('config form has 36 fields', n == 36, n)
        check('config form prefilled farm',
              fields.nth(3).input_value() == 'Buku Abel',
              fields.nth(3).input_value())
        save_meta_form(page, fields, 'Wete Konga', '171.5')
        check('saved note shown',
              page.get_by_text('Batch details saved.').count() >= 1)
        page.wait_for_timeout(800)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('config form wrote farm tag', v['Farm'] == 'Wete Konga', v)
        check('config form wrote weight out tag',
              float(v['WeightOutG']) == 171.5, v)
        click_tab(page, 'Roast')
        page.wait_for_timeout(1500)

        # ---------- finish and save to the database ----------
        click_button(page, 'Drop')
        v = read_tags([B + '/State', B + '/DropElapsedSec'])
        check('dropped', v['State'] == 'Dropped')
        check('drop stamped', (v['DropElapsedSec'] or -1) >= 0)
        click_button(page, 'Cool')
        click_button(page, 'Finish')
        click_button(page, 'Save Batch')
        page.wait_for_timeout(2500)
        check('save note shown',
              page.get_by_text(
                  f'Saved batch {TEST_BATCH} to the database.').count() >= 1)
        row = sql(f"SELECT bean_name || '|' || round(drop_temp_f::numeric, 1) "
                  f"|| '|' || (data->'metadata'->>'Farm') || '|' || "
                  f"(data->>'roastDegree') FROM batches "
                  f"WHERE batch_number = {TEST_BATCH}")
        check('batch row in database', row.startswith('Ethiopia Guji|'),
              row)
        check('document farm in database', '|Wete Konga|' in row, row)
        n_series = sql(f'SELECT count(*) FROM batch_series '
                       f'WHERE batch_number = {TEST_BATCH}')
        check('series rows in database', int(n_series) >= 1, n_series)

        # ---------- Log page (batches table) ----------
        # HUNT-110: there is no Batches tab or /batches route;
        # the batches table lives on the Log page (/log).
        test_label = '{:,}'.format(TEST_BATCH)
        scratch_label = '{:,}'.format(SCRATCH_BATCH)
        click_tab(page, 'Log')
        check('log page open', page.url.endswith('/log'), page.url)
        # HUNT-110: the Log page renders three .ia_table
        # elements now (breakpoint variants), so the bare
        # locator trips strict mode; the first holds the
        # batches table.
        page.locator('.ia_table').first.wait_for(timeout=30000)
        try:
            page.get_by_text(test_label, exact=True).first.wait_for(
                state='visible', timeout=20000)
            listed = True
        except Exception:
            listed = False
        check('test batch listed', listed)
        check('no quality overlays on batches page',
              overlay_count(page) == 0, overlay_count(page))
        scroll_top(page)
        page.screenshot(path=os.path.join(SHOTS, 'roastery-v3-batches.png'))
        print('shot roastery-v3-batches.png')

        # ---------- edit via slide-over ----------
        click_row(page, test_label)
        click_button(page, 'Edit')
        page.wait_for_timeout(3500)
        fields = form_fields(page)
        check('edit form has 51 fields', fields.count() == 51,
              fields.count())
        check('edit form prefilled farm',
              fields.nth(4).input_value() == 'Wete Konga',
              fields.nth(4).input_value())
        check('edit form prefilled weight out',
              fields.nth(16).input_value() in ('171.5', '171.50'),
              fields.nth(16).input_value())
        editor = page.locator('.psc-roast-dock-editor')
        editor.first.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-batch-edit.png'))
        print('shot roastery-v3-batch-edit.png')
        fields.nth(4).fill('Guji Highlands')
        fields.nth(16).fill('172.0')
        fields.nth(4).press('Tab')
        page.wait_for_timeout(600)
        click_button(page, 'Save Batch')
        page.wait_for_timeout(2000)
        check('edit saved note',
              page.get_by_text(f'Saved batch {TEST_BATCH}.').count() >= 1)
        farm = sql(f"SELECT data->'metadata'->>'Farm' FROM batches "
                   f"WHERE batch_number = {TEST_BATCH}")
        check('edit persisted via SelectById data', farm == 'Guji Highlands',
              farm)
        wout = sql(f"SELECT data->'metadata'->>'WeightOutG' FROM batches "
                   f"WHERE batch_number = {TEST_BATCH}")
        check('weight out persisted', float(wout) == 172.0, wout)
        click_button(page, 'Close')
        page.wait_for_timeout(1500)
        # reopen: prefill must show the edited values (SelectById path)
        click_row(page, test_label)
        click_button(page, 'Edit')
        page.wait_for_timeout(3500)
        fields = form_fields(page)
        check('edit form reprefilled with edited farm',
              fields.nth(4).input_value() == 'Guji Highlands',
              fields.nth(4).input_value())
        click_button(page, 'Close')
        page.wait_for_timeout(1500)

        # ---------- create + delete a scratch batch ----------
        click_button(page, 'New Batch')
        page.wait_for_timeout(3500)
        fields = form_fields(page)
        fields.nth(0).fill(str(SCRATCH_BATCH))
        fields.nth(1).fill('Scratch Bean')
        fields.nth(4).fill('Scratch Farm')
        fields.nth(0).press('Tab')
        page.wait_for_timeout(600)
        click_button(page, 'Save Batch')
        page.wait_for_timeout(2000)
        check('create note',
              page.get_by_text(f'Created batch {SCRATCH_BATCH}.').count() >= 1)
        check('scratch batch in database',
              sql(f'SELECT count(*) FROM batches '
                  f'WHERE batch_number = {SCRATCH_BATCH}') == '1')
        click_button(page, 'Close')
        page.wait_for_timeout(2500)
        check('scratch batch listed after refresh message',
              page.get_by_text(scratch_label, exact=True).count() >= 1)
        click_row(page, scratch_label)
        # HUNT-110 drive-by: the Delete click is lost
        # intermittently in a long session (probe8: the button
        # moved 79px under the click and the arm never fired,
        # while the same flow arms in 1s from a fresh session).
        # Poll the outcome and retry, alternating a DOM click
        # and re-selecting the row, up to four attempts.
        armed = False
        for attempt in range(4):
            if attempt == 1:
                js_click_button(page, 'Delete')
            elif attempt == 2:
                click_row(page, scratch_label)
                click_button(page, 'Delete', exact=True)
            elif attempt == 3:
                click_row(page, scratch_label)
                js_click_button(page, 'Delete')
            else:
                click_button(page, 'Delete', exact=True)
            for _ in range(5):
                if page.get_by_text(
                        'Press Confirm Delete to proceed.').count() >= 1:
                    armed = True
                    break
                page.wait_for_timeout(1000)
            if armed:
                break
        check('delete armed', armed)
        click_button(page, 'Confirm Delete', exact=True)
        page.wait_for_timeout(2500)
        check('scratch batch deleted from database',
              sql(f'SELECT count(*) FROM batches '
                  f'WHERE batch_number = {SCRATCH_BATCH}') == '0')
        gone = False
        for _ in range(20):
            if page.get_by_text(scratch_label, exact=True).count() == 0:
                gone = True
                break
            page.wait_for_timeout(500)
        check('scratch batch gone from table', gone)

        # ---------- background from a database batch ----------
        # HUNT-110: the ghost button is 'Use as Ghost' now.
        # HUNT-110 drive-by: the ghost click is lost
        # intermittently in a long session, the same class of
        # flake as the Delete arm, so poll the outcome and
        # retry, alternating a DOM click and re-selecting.
        click_row(page, test_label)
        bg_rows = 0
        v = {}
        for attempt in range(4):
            if attempt == 1:
                js_click_button(page, 'Use as Ghost')
            elif attempt == 2:
                click_row(page, test_label)
                click_button(page, 'Use as Ghost')
            elif attempt == 3:
                click_row(page, test_label)
                js_click_button(page, 'Use as Ghost')
            else:
                click_button(page, 'Use as Ghost')
            # Poll: click delivery on this beta can lag the waits,
            # and the overlay build follows the handler, not the
            # click call.
            for _ in range(10):
                page.wait_for_timeout(500)
                v = read_tags([R + '/BackgroundLabel',
                               R + '/BackgroundDS'])
                ds = json.loads(v['BackgroundDS']) \
                    if isinstance(v['BackgroundDS'], str) \
                    else {'rows': []}
                bg_rows = len(ds['rows'])
                if bg_rows >= 1:
                    break
            if bg_rows >= 1:
                break
        check('background label set from db batch',
              str(v['BackgroundLabel']).startswith(
                  f'Batch {TEST_BATCH}'), v['BackgroundLabel'])
        check('background overlay has rows', bg_rows >= 1, bg_rows)
        check('back on main', page.url.rstrip('/').endswith('Roastery'),
              page.url)
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-background.png'))
        print('shot roastery-v3-background.png')
        check('no quality overlays with background',
              overlay_count(page) == 0, overlay_count(page))

        # ---------- reset to clean idle ----------
        # HUNT-110: Reset is a dock action at Complete only.
        reset_via_dock(page)
        page.wait_for_timeout(2500)
        write_tags([(B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                    (B + '/Farm', 'Buku Abel'), (B + '/WeightOutG', 0.0),
                    (B + '/BatchNumber', 1042),
                    (R + '/BackgroundLabel', ''),
                    (R + '/BackgroundCurveJson', '')])
        click_button(page, 'Charge')
        page.wait_for_timeout(3500)
        reset_via_dock(page)
        page.wait_for_timeout(2500)
        v = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/WeightOutG', B + '/Farm', B + '/BatchNumber'])
        check('final state clean idle',
              v['State'] == 'Idle' and v['FanLevel'] == 5
              and v['HeatLevel'] == 5 and v['Farm'] == 'Buku Abel'
              and v['BatchNumber'] == 1042, v)
        page.close()

        # ---------- mobile pass ----------
        m = browser.new_page(viewport={'width': 390, 'height': 844})
        open_session(m)
        overflow = m.evaluate('document.documentElement.scrollWidth')
        check('mobile no horizontal overflow', overflow <= 391, overflow)
        set_theme_ui(m, 'Dark')
        check('mobile dark after toggle', theme_var(m) == '#161616',
              theme_var(m))
        scroll_top(m)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-dark-mobile.png'))
        print('shot roastery-v3-dark-mobile.png')
        check('mobile no quality overlays', overlay_count(m) == 0,
              overlay_count(m))
        # HUNT-110: leave ThemeMode System, as the other
        # suites expect; the mobile pass ends dark otherwise.
        set_theme_ui(m, 'System')
        m.close()
        browser.close()

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        sys.exit(1)
    print('ALL CHECKS PASS')


if __name__ == '__main__':
    main()
