#!/usr/bin/env python3
"""Roastery v2 regression: retheme + Form component + mojibake fix.

Desktop pass (1600x1000):
  light shot -> theme toggle to dark -> dark shot -> roast flow ->
  Form round trip in dark (dark config shot) -> theme back to light ->
  light config shot -> log page background flow (label encoding) ->
  reset to clean Idle.
Mobile pass (390x844, fresh session = light):
  light mobile shot -> toggle -> dark mobile shot -> config popup fit.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api27m
from playwright.sync_api import sync_playwright

URL = 'http://localhost:8088/data/perspective/client/Roastery/'
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'showcase', 'shots')
B = '[default]Roastery/CurrentBatch'
R = '[default]Roastery'
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
            click_button(page, 'Reset')
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
        click_button(page, 'Theme: light', exact=True)
        page.wait_for_timeout(6000)
        dismiss_modal(page)
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
        log0 = read_tags([R + '/EventsLog'])
        click_button(page, 'Charge')
        check('charging after Charge',
              read_tags([B + '/State'])['State'] == 'Roasting')
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
        plus = page.get_by_role('button', name='+')
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
        click_button(page, 'Roast Setup')
        page.wait_for_timeout(3500)
        popup = page.locator('.ia_popup')
        check('config popup open', popup.count() >= 1)
        fields = popup.locator('input.ia_form__field, '
                               'textarea.ia_form__field')
        n = fields.count()
        check('form has 16 fields', n == 16, n)
        vals = [fields.nth(i).input_value() for i in range(n)]
        print('form values:', vals)
        check('form prefilled bean', vals[0] == 'Ethiopia Guji', vals[0])
        check('form prefilled farm', vals[3] == 'Buku Abel', vals[3])
        scroll_top(page)
        popup.first.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-dark-config.png'))
        print('shot roastery-v2-dark-config.png')
        fields.nth(3).fill('Wete Konga')
        fields.nth(15).fill('171.5')
        click_button(page, 'Save Batch Details')
        page.wait_for_timeout(1500)
        check('saved note shown',
              page.get_by_text('Batch details saved.').count() >= 1)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('farm written by form', v['Farm'] == 'Wete Konga', v)
        check('weight out written by form',
              float(v['WeightOutG']) == 171.5, v)
        click_button(page, 'Close')
        page.wait_for_timeout(2000)
        check('metacard shows new farm',
              page.get_by_text('Wete Konga').count() >= 1)

        # ---------- light config ----------
        click_button(page, 'Theme: dark', exact=True)
        page.wait_for_timeout(6000)
        dismiss_modal(page)
        check('light after toggle back', theme_var(page) == '#FAFAFA',
              theme_var(page))
        click_button(page, 'Roast Setup')
        page.wait_for_timeout(3500)
        popup = page.locator('.ia_popup')
        popup.first.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-light-config.png'))
        print('shot roastery-v2-light-config.png')
        fvals = [popup.locator('input.ia_form__field, '
                               'textarea.ia_form__field').nth(i)
                 .input_value() for i in range(4)]
        check('form prefilled in light too', fvals[3] == 'Wete Konga',
              fvals)
        click_button(page, 'Close')
        page.wait_for_timeout(1500)

        # ---------- log page + background label encoding ----------
        click_button(page, 'Roast Log', exact=True)
        page.wait_for_timeout(4500)
        check('log page open', page.url.endswith('/log'), page.url)
        page.get_by_text('Ethiopia Guji').first.click()
        page.wait_for_timeout(1500)
        click_button(page, 'View as Background')
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
        click_button(page, 'Reset')
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
        click_button(page, 'Reset')
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
        click_button(m, 'Theme: light', exact=True)
        m.wait_for_timeout(6000)
        dismiss_modal(m)
        check('mobile dark after toggle', theme_var(m) == '#161616',
              theme_var(m))
        scroll_top(m)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-v2-dark-mobile.png'))
        print('shot roastery-v2-dark-mobile.png')
        check('mobile no quality overlays', overlay_count(m) == 0,
              overlay_count(m))
        click_button(m, 'Roast Setup')
        m.wait_for_timeout(3500)
        pw_ = m.locator('.ia_popup').first.bounding_box()
        check('mobile popup fits', pw_ is not None and pw_['width'] <= 392,
              pw_)
        m.close()
        browser.close()

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        sys.exit(1)
    print('ALL CHECKS PASS')


if __name__ == '__main__':
    main()
