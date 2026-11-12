#!/usr/bin/env python3
"""Full verification click test for the Artisan Roastery console (Maker).

Fresh controlled run: baseline normalize via API, desktop roast flow
(Charge, Fan stepper, Dry End, FC Start, Drop), deviation tile read
from the DOM during Roasting, config popup round trip, Save to Roast
Log, alarm banner, /log page in the client route, background select,
Reset, then mobile main + config popup at 390x844.

Evidence shots use a tall desktop viewport (1600x1680) scrolled to
the top, because the Perspective client scrolls internally and
Playwright full_page captures start mid page on this app.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api27m  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(LAB, 'showcase', 'shots')
URL = 'http://localhost:8088/data/perspective/client/Roastery/'
B = '[default]Roastery/CurrentBatch'
R = '[default]Roastery'
FAILURES = []


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


def rows_of(ds_value):
    if isinstance(ds_value, str):
        return json.loads(ds_value).get('rows', [])
    return []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name, detail)
    if not cond:
        FAILURES.append(name)


def dismiss_modal(page):
    page.wait_for_timeout(2500)
    if page.get_by_text('Personal Use Only').count() > 0:
        try:
            page.get_by_text('AGREE & CLOSE').first.click(timeout=8000)
        except Exception:
            box = page.get_by_text('Personal Use Only').first.bounding_box()
            page.mouse.click(box['x'] + box['width'] / 2 + 115,
                             box['y'] + box['height'] - 32)
        page.wait_for_timeout(2500)


def scroll_top(page):
    page.evaluate("""() => {
        window.scrollTo(0, 0);
        document.querySelectorAll('*').forEach(el => {
            if (el.scrollTop) el.scrollTop = 0;
        });
    }""")
    page.wait_for_timeout(700)


def shot(page, name):
    scroll_top(page)
    page.screenshot(path=os.path.join(SHOTS, name))
    print('shot', name)


def click_button(page, name, first=False):
    loc = page.get_by_role('button', name=name)
    if first:
        loc = loc.first
    try:
        loc.click(timeout=10000)
    except Exception:
        page.wait_for_timeout(1500)
        loc.click(force=True, timeout=10000)
    page.wait_for_timeout(600)


def set_field(page, caption, value):
    lab = page.locator('.ia_popup').get_by_text(caption, exact=True).first
    inp = lab.locator('..').locator('..').locator('input').first
    inp.click()
    inp.fill(str(value))
    inp.press('Enter')
    page.wait_for_timeout(1200)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    # ---------- baseline: clean metadata and no background ----------
    write_tags([(B + '/Farm', 'Buku Abel'), (B + '/WeightOutG', 0),
                (B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                (B + '/AlarmHighTempF', 430.0),
                (R + '/BackgroundLabel', '')])
    empty_bg = json.dumps({'columns': [{'name': 't_stamp',
                                         'type': 'java.util.Date'},
                                        {'name': 'bg',
                                         'type': 'java.lang.Double'}],
                           'rows': []})
    write_tags([(R + '/BackgroundDS', empty_bg),
                (R + '/BackgroundCurveJson', '')])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        page.goto(URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(9000)
        dismiss_modal(page)
        if read_tags([B + '/State'])['State'] != 'Idle':
            click_button(page, 'Reset')
            page.wait_for_timeout(2500)
        check('starts idle',
              read_tags([B + '/State'])['State'] == 'Idle')

        # tall viewport for one frame evidence shots
        page.set_viewport_size({'width': 1600, 'height': 1680})
        page.wait_for_timeout(3000)
        shot(page, 'roastery-artisan-desktop.png')

        # ---------- roast flow ----------
        page.get_by_role('button', name='Charge').click()
        page.wait_for_timeout(4000)
        v = read_tags([B + '/State', B + '/ChargeTempF'])
        check('charge sets Roasting', v['State'] == 'Roasting', str(v))
        dev = page.locator('text=DEVIATION').first.locator('..') \
            .locator('..').inner_text().replace('\n', ' ')
        check('deviation tile live', any(c.isdigit() for c in dev)
              and 'F' in dev, dev[:80])
        shot(page, 'roastery-artisan-roasting.png')

        log0 = rows_of(read_tags([R + '/EventsLog'])['EventsLog'])
        fan0 = read_tags([B + '/FanLevel'])['FanLevel']
        page.locator('button', has_text='+').first.click()
        page.wait_for_timeout(2000)
        fan1 = read_tags([B + '/FanLevel'])['FanLevel']
        log1 = rows_of(read_tags([R + '/EventsLog'])['EventsLog'])
        check('fan stepper steps', fan1 == fan0 + 1, f'{fan0} -> {fan1}')
        check('trace logs fan change', len(log1) > len(log0),
              f'{len(log0)} -> {len(log1)} event rows')

        page.get_by_role('button', name='Dry End').click()
        page.wait_for_timeout(6000)
        page.get_by_role('button', name='FC Start').click()
        page.wait_for_timeout(6000)
        page.get_by_role('button', name='Drop').click()
        page.wait_for_timeout(3000)
        v = read_tags([B + '/State', B + '/DropElapsedSec',
                       B + '/DryEndElapsedSec',
                       B + '/FirstCrackStartElapsedSec', B + '/DropTempF'])
        check('drop state', v['State'] == 'Dropped', str(v))
        check('phase elapsed recorded',
              v['DryEndElapsedSec'] >= 0
              and v['FirstCrackStartElapsedSec'] > v['DryEndElapsedSec']
              and v['DropElapsedSec'] > v['FirstCrackStartElapsedSec'],
              str(v))
        shot(page, 'roastery-artisan-summary.png')

        # ---------- config popup round trip ----------
        click_button(page, 'Roast Setup', first=True)
        page.wait_for_timeout(3500)
        shot(page, 'roastery-artisan-config.png')
        set_field(page, 'Farm / station', 'Buku Abel Estate')
        set_field(page, 'Weight out (g)', 172)
        page.get_by_role('button', name='Close').click()
        page.wait_for_timeout(2000)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('farm round trip', v['Farm'] == 'Buku Abel Estate', str(v))
        check('weight out round trip', float(v['WeightOutG']) == 172.0,
              str(v))

        # ---------- save to roast log ----------
        rows0 = rows_of(read_tags([R + '/RoastLog'])['RoastLog'])
        page.get_by_role('button', name='Save to Roast Log').click()
        page.wait_for_timeout(3000)
        rows = rows_of(read_tags([R + '/RoastLog'])['RoastLog'])
        check('roast log gained a row', len(rows) == len(rows0) + 1,
              f'{len(rows0)} -> {len(rows)} rows')
        if rows:
            curve = rows[-1][14]
            check('saved curve present', isinstance(curve, str)
                  and len(curve) > 50, f'curve len {len(str(curve))}')

        # ---------- alarm banner ----------
        write_tags([(B + '/AlarmHighTempF', 150.0)])
        page.wait_for_timeout(3500)
        shot(page, 'roastery-artisan-alarm.png')
        banner = page.locator('text=Bean temperature high').count()
        check('alarm banner visible', banner > 0, f'count {banner}')
        write_tags([(B + '/AlarmHighTempF', 430.0)])
        page.wait_for_timeout(1500)

        # ---------- log page + background ----------
        page.get_by_role('button', name='Roast Log', exact=True).click()
        page.wait_for_timeout(4000)
        check('log page is client route', '/log' in page.url, page.url)
        shot(page, 'roastery-artisan-log.png')
        page.get_by_text('Ethiopia Guji').first.click()
        page.wait_for_timeout(1500)
        page.get_by_role('button', name='View as Background').click()
        page.wait_for_timeout(4500)
        v = read_tags([R + '/BackgroundLabel'])
        check('background label set',
              'Batch' in str(v['BackgroundLabel']), str(v))
        check('back on main page', page.url.rstrip('/').endswith('Roastery')
              or '/log' not in page.url, page.url)
        shot(page, 'roastery-artisan-background.png')

        # ---------- reset ----------
        click_button(page, 'Reset')
        page.wait_for_timeout(2500)
        v = read_tags([B + '/State', B + '/DropElapsedSec'])
        check('reset to idle', v['State'] == 'Idle', str(v))
        page.close()

        # ---------- mobile ----------
        m = browser.new_page(viewport={'width': 390, 'height': 844})
        m.goto(URL, wait_until='networkidle', timeout=60000)
        m.wait_for_timeout(9000)
        dismiss_modal(m)
        widths = m.evaluate("""() => [document.documentElement.scrollWidth,
                                       document.body.scrollWidth]""")
        check('mobile no horizontal overflow',
              all(w <= 391 for w in widths), str(widths))
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-artisan-mobile.png'))
        print('shot roastery-artisan-mobile.png')
        click_button(m, 'Roast Setup', first=True)
        m.wait_for_timeout(3500)
        m.screenshot(path=os.path.join(
            SHOTS, 'roastery-artisan-config-mobile.png'))
        print('shot roastery-artisan-config-mobile.png')
        pop = m.locator('.ia_popup').first.bounding_box()
        check('mobile popup fits width',
              pop is not None and pop['width'] <= 392,
              f"popup width {pop['width'] if pop else None}")
        m.close()
        browser.close()

    # ---------- final normalize ----------
    write_tags([(B + '/Farm', 'Buku Abel'), (B + '/WeightOutG', 0),
                (B + '/FanLevel', 5), (B + '/HeatLevel', 5),
                (R + '/BackgroundLabel', ''),
                (R + '/BackgroundCurveJson', ''),
                (R + '/BackgroundDS', empty_bg)])
    print('FAILURES:', FAILURES if FAILURES else 'none')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
