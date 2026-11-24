#!/usr/bin/env python3
"""Roastery v2 regression: retheme + Form component + mojibake fix.

Desktop pass (1600x1000):
  light shot -> theme toggle to dark -> dark shot -> roast flow ->
  Settings MetaForm round trip in dark (dark config shot) -> theme
  back to light -> light config shot -> log page ghost flow (label
  encoding) -> reset to clean Idle.
Mobile pass (390x844, fresh session = light):
  light mobile shot -> toggle -> dark mobile shot -> Settings form fit.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api27m
from playwright.sync_api import sync_playwright

URL = 'http://localhost:8088/data/perspective/client/Roastery/'
# HUNT-107: SHOTS used to resolve from __file__, so running the
# repo copy wrote screenshots into the repo tree (config only,
# no PNGs). Every other suite points at the lab shots dir.
SHOTS = '/home/hatch/workspace/ignition-lab/showcase/shots'
B = '[default]Roastery/CurrentBatch'
R = '[default]Roastery'
TM = '[default]Roastery/AppSettings/ThemeMode'
FAILURES = []


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


def js_click_button(page, name):
    """Click a button by its exact text through the DOM, bypassing
    hit testing. HUNT-110 drive-by: in a long session the
    BatchesPanel layout can shift under a Playwright click, so a
    coordinate click can miss the button even though it is
    enabled and visible. A DOM click still exercises the app's
    own handler end to end; it only skips the browser's hit
    test."""
    page.evaluate("""(name) => {
      const b = [...document.querySelectorAll('button')].find(
        e => e.textContent.trim() === name);
      if (!b) throw new Error('no button: ' + name);
      b.click();
    }""", name)
    page.wait_for_timeout(700)


def save_meta_form(page, fields, farm, weight):
    """HUNT-110 drive-by: fill the MetaForm, confirm the
    fills stuck, submit, and confirm the tags moved. The
    submit was observed to silently do nothing once on a
    freshly restarted gateway (rerun4 v2 and v3: no note, no
    tag change, while the same flow passed warm), so retry
    the fill and the submit before giving up. Tab out of the
    weight field after filling: the number field only
    commits its value to the form on blur, and a submit
    raced ahead of that blur writes the old 0.0 (rerun10
    v3 wrote the farm but not the weight). On the last
    attempt, re-mount the form first."""
    for attempt in range(4):
        if attempt == 3:
            click_tab(page, 'Roast')
            page.wait_for_timeout(1500)
            fields = meta_form_fields(page)
        fields.nth(3).fill(farm)
        fields.nth(15).fill(weight)
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
    """Visible Perspective quality overlays (error badges/bars)."""
    return page.evaluate("""() => [...document.querySelectorAll(
      '.ia_qualityOverlay')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0; }).length""")


def cell_name_color(page):
    """Computed color of the Charge EventCell's name label. The cell
    is identified structurally: a 'Charge' leaf whose cell container
    also holds a time string (--:-- or mm:ss). Returns [color,
    cellText] or null. (A plain text search is not enough: the
    MetaCard also has a static 'Charge' caption.)"""
    return page.evaluate("""() => {
      const leaves = [...document.querySelectorAll('*')].filter(
        e => e.children.length === 0 && !e.closest('button')
             && e.textContent.trim() === 'Charge');
      for (const leaf of leaves) {
        let box = leaf;
        for (let i = 0; i < 4 && box; i++) {
          box = box.parentElement;
          if (box && /(--:--)|\\d{2}:\\d{2}/.test(box.textContent)
              && box.textContent.includes('Charge')) {
            return [getComputedStyle(leaf).color,
                    box.textContent.replace(/\\s+/g, ' ').slice(0, 40)];
          }
        }
      }
      return null;
    }""")


def open_session(page):
    page.goto(URL, wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(9000)
    dismiss_modal(page)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        open_session(page)
        if read_tags([B + '/State'])['State'] != 'Idle':
            # HUNT-110: Reset is a dock action at Complete
            # only, as 'Reset / New Roast'.
            reset_via_dock(page)
            page.wait_for_timeout(2500)

        # ---------- light desktop ----------
        check('session starts light', theme_var(page) == '#FAFAFA',
              theme_var(page))
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-light-desktop.png'))
        print('shot roastery-v2-light-desktop.png')
        check('no quality overlays on idle main (light)',
              overlay_count(page) == 0, overlay_count(page))

        # ---------- toggle to dark ----------
        set_theme_ui(page, 'Dark')
        check('dark after toggle', theme_var(page) == '#161616',
              theme_var(page))
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-dark-desktop.png'))
        print('shot roastery-v2-dark-desktop.png')
        check('no quality overlays on idle main (dark)',
              overlay_count(page) == 0, overlay_count(page))
        wait_col = cell_name_color(page)
        print('charge cell (waiting):', wait_col)

        # ---------- roast flow ----------
        click_button(page, 'Charge')
        # HUNT-110 drive-by: the State read right after the
        # click raced the gateway handler (v3 read Idle once
        # while the roast then started fine), so poll instead
        # of asserting on a single immediate read.
        charging = False
        for _ in range(20):
            if read_tags([B + '/State'])['State'] == 'Roasting':
                charging = True
                break
            page.wait_for_timeout(500)
        check('charging after Charge', charging)
        # HUNT-110 drive-by: the trace log baseline must be
        # read AFTER Charge, because Charge clears the log.
        # Reading it before Charge compares the fresh 4-row
        # log against a leftover log from an earlier run,
        # which can be longer (588 chars in one rerun) and
        # fails even though the stepper appended its row.
        log0 = read_tags([R + '/EventsLog'])
        page.wait_for_timeout(4000)
        check('no quality overlays while roasting',
              overlay_count(page) == 0, overlay_count(page))
        done_col = cell_name_color(page)
        print('charge cell (done):', done_col)
        check('charge cell name turns accent when done',
              bool(wait_col) and bool(done_col)
              and done_col[0] != wait_col[0],
              f'{wait_col} -> {done_col}')
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
        # the fan (6 -> 6 while the fan never moved). Exact
        # match keeps only the two steppers, fan first.
        plus = page.get_by_role('button', name='+', exact=True)
        plus.nth(0).click()
        page.wait_for_timeout(600)
        v = read_tags([B + '/FanLevel', R + '/EventsLog'])
        check('fan stepper stepped', v['FanLevel'] == fan0 + 1,
              f"{fan0} -> {v['FanLevel']}")
        check('stepper logged a trace row',
              len(str(v['EventsLog'])) > len(str(log0['EventsLog'])),
              f"{len(str(log0['EventsLog']))} -> "
              f"{len(str(v['EventsLog']))}")
        click_button(page, 'Drop')
        v = read_tags([B + '/State', B + '/DropElapsedSec'])
        check('dropped', v['State'] == 'Dropped')
        check('drop stamped', (v['DropElapsedSec'] or -1) >= 0)

        # ---------- Form round trip (dark config) ----------
        # HUNT-110: the Roast Setup popup is gone; the same
        # form lives on the Settings page as the MetaForm.
        fields = meta_form_fields(page)
        n = fields.count()
        check('config form has 36 fields', n == 36, n)
        vals = [fields.nth(i).input_value() for i in range(n)]
        print('form values:', vals)
        check('form prefilled bean', vals[0] == 'Ethiopia Guji', vals[0])
        check('form prefilled farm', vals[3] == 'Buku Abel', vals[3])
        scroll_top(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-dark-config.png'))
        print('shot roastery-v2-dark-config.png')
        save_meta_form(page, fields, 'Wete Konga', '171.5')
        check('saved note shown',
              page.get_by_text('Batch details saved.').count() >= 1)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('farm written by form', v['Farm'] == 'Wete Konga', v)
        check('weight out written by form',
              float(v['WeightOutG']) == 171.5, v)
        click_tab(page, 'Roast')
        page.wait_for_timeout(2000)
        check('metacard shows new farm',
              page.get_by_text('Wete Konga').count() >= 1)

        # ---------- light config ----------
        set_theme_ui(page, 'Light')
        check('light after toggle back', theme_var(page) == '#FAFAFA',
              theme_var(page))
        fields = meta_form_fields(page)
        page.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-light-config.png'))
        print('shot roastery-v2-light-config.png')
        fvals = [fields.nth(i).input_value() for i in range(4)]
        check('form prefilled in light too', fvals[3] == 'Wete Konga',
              fvals)
        click_tab(page, 'Roast')
        page.wait_for_timeout(1500)

        # ---------- log page + background label encoding ----------
        # HUNT-110: the tab is 'Log', not a 'Roast Log' button,
        # and the ghost button is 'Use as Ghost' now.
        click_tab(page, 'Log')
        page.wait_for_timeout(4500)
        check('log page open', page.url.endswith('/log'), page.url)
        page.get_by_text('Ethiopia Guji').first.click()
        page.wait_for_timeout(1500)
        click_button(page, 'Use as Ghost')
        page.wait_for_timeout(4500)
        v = read_tags([R + '/BackgroundLabel'])
        lbl = str(v['BackgroundLabel'])
        check('background label set', 'Batch' in lbl, lbl)
        check('background label clean ascii separator',
              'Â' not in lbl and ' - ' in lbl, repr(lbl))
        check('back on main',
              page.url.rstrip('/').endswith('Roastery'), page.url)

        # ---------- reset to clean idle ----------
        # The app's own Reset restores State/Mode/times/log; the fan
        # and heat levels are normalized here the same way the v1
        # finish pass did (Reset never wrote them, by design).
        # HUNT-110: Reset is a dock action at Complete only.
        reset_via_dock(page)
        page.wait_for_timeout(2500)
        write_tags([(B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                    (B + '/Farm', 'Buku Abel'),
                    (R + '/BackgroundLabel', ''),
                    (R + '/BackgroundCurveJson', '')])
        v = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/WeightOutG', B + '/Farm'])
        check('reset to idle', v['State'] == 'Idle', v)
        check('clean idle state restored',
              v['FanLevel'] == 5 and v['HeatLevel'] == 5
              and v['Farm'] == 'Buku Abel', v)
        # BackgroundDS is cleared the safe way: Charge rebuilds the
        # overlay datasets from the (now empty) BackgroundCurveJson
        # through its gateway script, and Reset empties them again.
        # Do NOT write a dataset through /tags/write with a JSON
        # object value: on this beta that stores a Document object
        # in the tag ("Invalid DataType for Dataset"), which is what
        # put the ERROR bar on the chart in the first v2 run.
        click_button(page, 'Charge')
        page.wait_for_timeout(3500)
        reset_via_dock(page)
        page.wait_for_timeout(2500)
        v = read_tags([B + '/State', R + '/BackgroundDS'])
        check('final state idle after background clear',
              v['State'] == 'Idle', v['State'])
        check('background ds empty and readable',
              isinstance(v['BackgroundDS'], str)
              and '"rows":[]' in v['BackgroundDS'].replace(' ', ''),
              str(v['BackgroundDS'])[:120])
        page.close()

        # ---------- mobile pass ----------
        m = browser.new_page(viewport={'width': 390, 'height': 844})
        open_session(m)
        check('mobile session light', theme_var(m) == '#FAFAFA',
              theme_var(m))
        overflow = m.evaluate('document.documentElement.scrollWidth')
        check('mobile no horizontal overflow', overflow <= 391, overflow)
        scroll_top(m)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-light-mobile.png'))
        print('shot roastery-v2-light-mobile.png')
        set_theme_ui(m, 'Dark')
        check('mobile dark after toggle', theme_var(m) == '#161616',
              theme_var(m))
        scroll_top(m)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-dark-mobile.png'))
        print('shot roastery-v2-dark-mobile.png')
        check('mobile no quality overlays', overlay_count(m) == 0,
              overlay_count(m))
        # HUNT-110: the Roast Setup popup is gone; the form
        # lives on the Settings page, so check the Settings
        # form fits the phone width instead.
        click_tab(m, 'Settings')
        m.wait_for_timeout(3500)
        overflow2 = m.evaluate('document.documentElement.scrollWidth')
        check('mobile settings form fits', overflow2 <= 391, overflow2)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-mobile-settings.png'))
        print('shot roastery-v2-mobile-settings.png')
        click_tab(m, 'Roast')
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
