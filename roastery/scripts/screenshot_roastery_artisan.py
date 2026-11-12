#!/usr/bin/env python3
"""Click test the Artisan Roastery console on the Maker gateway.

Desktop flow: idle shot, Charge, Fan stepper, Dry End, FC Start, Drop,
summary shot, config popup (edit Farm, enter WeightOutG), Save to Roast
Log, forced alarm banner shot, /log page, View as Background, Reset.
Mobile flow: main at 390x844 and the config popup at phone width.
Tag state is verified through GET /tags/read at each stage.
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
    paths = [p for p, _ in pairs]
    values = [v for _, v in pairs]
    st, out = api27m.api('POST', '/tags/write',
                         body=json.dumps({'tagPaths': paths,
                                          'values': values}))
    assert st == 200, (st, out)


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


def field_input(page, caption):
    lab = page.locator('.ia_popup').get_by_text(caption, exact=True).first
    return lab.locator('..').locator('..').locator('input').first


def set_field(page, caption, value):
    inp = field_input(page, caption)
    inp.click()
    inp.fill(str(value))
    inp.press('Enter')
    page.wait_for_timeout(1200)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # ---------------- desktop ----------------
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        page.goto(URL, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(9000)
        dismiss_modal(page)
        # ensure a clean idle state
        st = read_tags([B + '/State'])['State']
        if st != 'Idle':
            page.get_by_role('button', name='Reset').click()
            page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-desktop.png'),
                        full_page=True)
        check('desktop idle shot', True)

        page.get_by_role('button', name='Charge').click()
        page.wait_for_timeout(3500)
        v = read_tags([B + '/State', B + '/ChargeTempF'])
        check('charge sets Roasting', v['State'] == 'Roasting', str(v))
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-roasting.png'),
                        full_page=True)

        # stepper: Fan one step (direction depends on the clamp)
        fan_before = read_tags([B + '/FanLevel'])['FanLevel']
        if fan_before < 9:
            page.locator('button', has_text='+').first.click()
            expect = fan_before + 1
        else:
            page.locator('button', has_text='−').first.click()
            expect = fan_before - 1
        page.wait_for_timeout(1800)
        fan_after = read_tags([B + '/FanLevel'])['FanLevel']
        check('fan stepper steps', fan_after == expect,
              f'{fan_before} -> {fan_after}')
        log = read_tags([R + '/EventsLog'])['EventsLog']
        rows = json.loads(log)['rows'] if isinstance(log, str) else []
        check('events log has seed + fan rows', len(rows) >= 4,
              f'{len(rows)} rows')

        page.get_by_role('button', name='Dry End').click()
        page.wait_for_timeout(7000)
        page.get_by_role('button', name='FC Start').click()
        page.wait_for_timeout(7000)
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
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-summary.png'),
                        full_page=True)

        # config popup: edit Farm, enter WeightOutG
        page.wait_for_timeout(2000)
        click_button(page, 'Roast Setup', first=True)
        page.wait_for_timeout(3500)
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-config.png'))
        set_field(page, 'Farm / station', 'Buku Abel Estate')
        set_field(page, 'Weight out (g)', 172)
        page.get_by_role('button', name='Close').click()
        page.wait_for_timeout(2000)
        v = read_tags([B + '/Farm', B + '/WeightOutG'])
        check('farm round trip', v['Farm'] == 'Buku Abel Estate', str(v))
        check('weight out round trip', float(v['WeightOutG']) == 172.0,
              str(v))

        # save to roast log
        log0 = read_tags([R + '/RoastLog'])['RoastLog']
        rows0 = json.loads(log0)['rows'] if isinstance(log0, str) else []
        page.get_by_role('button', name='Save to Roast Log').click()
        page.wait_for_timeout(3000)
        log = read_tags([R + '/RoastLog'])['RoastLog']
        rows = json.loads(log)['rows'] if isinstance(log, str) else []
        check('roast log gained a row', len(rows) == len(rows0) + 1,
              f'{len(rows0)} -> {len(rows)} rows')
        if rows:
            curve = rows[-1][14]
            check('saved curve present', isinstance(curve, str)
                  and len(curve) > 50, f'curve len {len(str(curve))}')

        # forced alarm banner
        write_tags([(B + '/AlarmHighTempF', 150.0)])
        page.wait_for_timeout(3500)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-alarm.png'))
        write_tags([(B + '/AlarmHighTempF', 430.0)])
        page.wait_for_timeout(1500)

        # roast log page + background selection
        page.get_by_role('button', name='Roast Log', exact=True).click()
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-log.png'),
                        full_page=True)
        page.get_by_text('Ethiopia Guji').first.click()
        page.wait_for_timeout(1500)
        page.get_by_role('button', name='View as Background').click()
        page.wait_for_timeout(4000)
        v = read_tags([R + '/BackgroundLabel'])
        check('background label set',
              'Batch' in str(v['BackgroundLabel']), str(v))
        page.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-background.png'),
                        full_page=True)

        page.get_by_role('button', name='Reset').click()
        page.wait_for_timeout(2500)
        v = read_tags([B + '/State'])
        check('reset to idle', v['State'] == 'Idle', str(v))
        write_tags([(B + '/Farm', 'Buku Abel')])
        page.close()

        # ---------------- mobile ----------------
        m = browser.new_page(viewport={'width': 390, 'height': 844})
        m.goto(URL, wait_until='networkidle', timeout=60000)
        m.wait_for_timeout(9000)
        dismiss_modal(m)
        m.screenshot(path=os.path.join(SHOTS, 'roastery-artisan-mobile.png'),
                     full_page=True)
        m.wait_for_timeout(2000)
        click_button(m, 'Roast Setup', first=True)
        m.wait_for_timeout(3500)
        m.screenshot(path=os.path.join(SHOTS,
                                       'roastery-artisan-config-mobile.png'))
        pop = m.locator('.ia_popup').first.bounding_box()
        check('mobile popup fits width',
              pop is not None and pop['width'] <= 392,
              f"popup width {pop['width'] if pop else None}")
        m.close()
        browser.close()
    print('FAILURES:', FAILURES if FAILURES else 'none')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())
