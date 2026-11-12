#!/usr/bin/env python3
"""Roastery v3 verification: database CRUD via named queries, the
scripting library, style classes, SQL historian, RoasterSource.

Desktop pass (1600x1000):
  light shot -> toggle dark -> dark shot -> set BatchNumber 2001 ->
  short roast (Charge, Dry End, FC Start, stepper) -> Config form
  round trip (Farm, WeightOut) -> Drop, Cool, Finish -> Save Batch ->
  verify the batches row and batch_series rows in Postgres ->
  Batches page shot -> Edit popup (prefill check, shot) -> edit Farm
  and WeightOut -> save -> reopen popup to verify persistence ->
  New Batch 2002 via the create form -> delete it via the confirm
  flow -> verify gone -> View as Background from batch 2001 ->
  Main with overlay -> reset to clean Idle.
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
LAB = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(LAB, 'showcase', 'shots')
B = '[default]Roastery/CurrentBatch'
R = '[default]Roastery'
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
    pw = open(os.path.join(LAB, 'pg-lab-password.txt')).read().strip()
    env = dict(os.environ, PGPASSWORD=pw)
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', query], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def click_row(page, label):
    """Select a table row by its batch number cell text. Playwright
    hit testing fights the Perspective table (ancestors report as
    intercepting), so click the row element in the DOM instead."""
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
    loc = page.get_by_role('button', name=name, exact=exact)
    try:
        loc.first.click(timeout=10000)
    except Exception:
        page.wait_for_timeout(1500)
        loc.first.click(force=True, timeout=10000)
    page.wait_for_timeout(700)


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
    popup = page.locator('.ia_popup')
    return popup.locator('input.ia_form__field, textarea.ia_form__field')


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
            click_button(page, 'Reset')
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
        click_button(page, 'Theme: light', exact=True)
        page.wait_for_timeout(6000)
        dismiss_modal(page)
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
        check('charging after Charge',
              read_tags([B + '/State'])['State'] == 'Roasting')
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
        page.get_by_role('button', name='+').nth(0).click()
        page.wait_for_timeout(600)
        check('fan stepper stepped',
              read_tags([B + '/FanLevel'])['FanLevel'] == fan0 + 1)
        samples = read_tags([R + '/CurveSamples'])['CurveSamples']
        n_samples = len(json.loads(samples)['rows']) \
            if isinstance(samples, str) else -1
        check('curve samples being recorded', n_samples >= 1, n_samples)

        # ---------- Config form round trip (tags) ----------
        click_button(page, 'Roast Setup')
        page.wait_for_timeout(3500)
        fields = form_fields(page)
        n = fields.count()
        check('config form has 16 fields', n == 16, n)
        check('config form prefilled farm',
              fields.nth(3).input_value() == 'Buku Abel',
              fields.nth(3).input_value())
        fields.nth(3).fill('Wete Konga')
        fields.nth(15).fill('171.5')
        fields.nth(3).press('Tab')
        page.wait_for_timeout(600)
        click_button(page, 'Save Batch Details')
        try:
            page.get_by_text('Batch details saved.').wait_for(
                state='visible', timeout=6000)
        except Exception:
            click_button(page, 'Save Batch Details')
            page.get_by_text('Batch details saved.').wait_for(
                state='visible', timeout=6000)
        page.wait_for_timeout(800)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('config form wrote farm tag', v['Farm'] == 'Wete Konga', v)
        check('config form wrote weight out tag',
              float(v['WeightOutG']) == 171.5, v)
        click_button(page, 'Close')
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

        # ---------- Batches page ----------
        test_label = '{:,}'.format(TEST_BATCH)
        scratch_label = '{:,}'.format(SCRATCH_BATCH)
        click_button(page, 'Batches', exact=True)
        check('batches page open', page.url.endswith('/batches'), page.url)
        page.locator('.ia_table').wait_for(timeout=30000)
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

        # ---------- edit via popup ----------
        click_row(page, test_label)
        click_button(page, 'Edit')
        page.wait_for_timeout(3500)
        fields = form_fields(page)
        check('edit form has 17 fields', fields.count() == 17,
              fields.count())
        check('edit form prefilled farm',
              fields.nth(4).input_value() == 'Wete Konga',
              fields.nth(4).input_value())
        check('edit form prefilled weight out',
              fields.nth(16).input_value() in ('171.5', '171.50'),
              fields.nth(16).input_value())
        popup = page.locator('.ia_popup')
        popup.first.screenshot(path=os.path.join(
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
        click_button(page, 'Delete')
        page.wait_for_timeout(1000)
        click_button(page, 'Confirm Delete')
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
        click_row(page, test_label)
        click_button(page, 'View as Background')
        # Poll: click delivery on this beta can lag the waits, and
        # the overlay build follows the handler, not the click call.
        bg_rows = 0
        v = {}
        for _ in range(24):
            page.wait_for_timeout(500)
            v = read_tags([R + '/BackgroundLabel', R + '/BackgroundDS'])
            ds = json.loads(v['BackgroundDS']) \
                if isinstance(v['BackgroundDS'], str) else {'rows': []}
            bg_rows = len(ds['rows'])
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
        click_button(page, 'Reset')
        page.wait_for_timeout(2500)
        write_tags([(B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                    (B + '/Farm', 'Buku Abel'), (B + '/WeightOutG', 0.0),
                    (B + '/BatchNumber', 1042),
                    (R + '/BackgroundLabel', ''),
                    (R + '/BackgroundCurveJson', '')])
        click_button(page, 'Charge')
        page.wait_for_timeout(3500)
        click_button(page, 'Reset')
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
        click_button(m, 'Theme: light', exact=True)
        m.wait_for_timeout(6000)
        dismiss_modal(m)
        check('mobile dark after toggle', theme_var(m) == '#161616',
              theme_var(m))
        scroll_top(m)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v3-dark-mobile.png'))
        print('shot roastery-v3-dark-mobile.png')
        check('mobile no quality overlays', overlay_count(m) == 0,
              overlay_count(m))
        m.close()
        browser.close()

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        sys.exit(1)
    print('ALL CHECKS PASS')


if __name__ == '__main__':
    main()
