#!/usr/bin/env python3
"""Roastery Tier 3a verification (Playwright + REST + psql).

Proves Tier 3 items 18 and 21 live on the Maker gateway:
18. Batch export beyond .alog from BatchDetail: the CSV, JSON
    and printable HTML summary downloads fire, and their
    contents match the stored series and document for the
    seeded batch 1042, recomputed independently here from
    Postgres.
21. Yield and conversion calculator on BatchDetail: driven
    through the real UI (numeric inputs), the forward yield
    (charge and loss percent to expected out, in g and oz),
    the reverse (weight out to loss percent) and the F/C and
    g/oz conversions all match hand computed values, both in
    the Calculator expression tags and in the rendered labels.

Screenshots land in showcase/shots/roastery-tier3-*.png.
No batches are created; the lab is left at 7 batches / 101
series rows / 0 events, CurrentBatch clean Idle, and the
Calculator tags back at their defaults.
"""
import csv
import io
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
CALC = '[default]Roastery/Calculator'
LOGS = '/home/hatch/workspace/ignition-lab/gateway-2027-maker/logs/system_logs.idb'
FAILURES = []
DOWNLOADS = '/tmp/tier3-downloads'


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


def wait_until(fn, timeout=40, step=1.0):
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


def approx(a, b, tol):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def select_batch_row(page, number):
    rows = page.locator('.ia_table__row')
    for i in range(rows.count()):
        tokens = rows.nth(i).inner_text().replace(',', '').split()
        if str(number) in tokens:
            rows.nth(i).click()
            page.wait_for_timeout(1200)
            return int(tag('[default]Roastery/SelectedBatchNumber')
                       or 0) == number
    return False


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_t3_start.idb')
    con = sqlite3.connect('/tmp/logs_t3_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    # Copying the live log DB can catch it mid write (a malformed
    # image); retry the copy a few times before giving up.
    last = None
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_t3_end.idb')
            con = sqlite3.connect('/tmp/logs_t3_end.idb')
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


def download(page, button_name):
    with page.expect_download(timeout=20000) as info:
        page.get_by_role('button', name=button_name).first.click()
    dl = info.value
    path = os.path.join(DOWNLOADS, dl.suggested_filename)
    dl.save_as(path)
    return dl.suggested_filename, open(path).read()


def fill_input(page, idx, value):
    inp = page.locator(
        '[data-component="ia.input.numeric-entry-field"] input').nth(idx)
    inp.scroll_into_view_if_needed()
    inp.click()
    page.wait_for_timeout(300)
    inp.press('Control+a')
    inp.type(str(value))
    inp.press('Enter')
    page.wait_for_timeout(1200)


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    base = (int(psql('SELECT COUNT(*) FROM batches')),
            int(psql('SELECT COUNT(*) FROM batch_series')),
            int(psql('SELECT COUNT(*) FROM batch_events')))
    check('starting point is the seeded log', base == (7, 101, 0), base)
    doc = json.loads(psql(
        "SELECT data FROM batches WHERE batch_number = 1042"))
    series = []
    for line in psql(
            "SELECT t_offset_sec, bean_temp_f, rate_of_rise_f, "
            "COALESCE(fan_level, -99), COALESCE(heat_level, -99) "
            "FROM batch_series WHERE batch_number = 1042 "
            "ORDER BY t_offset_sec").splitlines():
        t, bt, ror, fan, heat = line.split('|')
        series.append((float(t), float(bt), float(ror),
                       int(fan), int(heat)))
    check('seeded batch 1042 has a stored series', len(series) == 21,
          len(series))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(viewport={'width': 1600, 'height': 1000},
                                accept_downloads=True)
        mob = browser.new_page(viewport={'width': 360, 'height': 740},
                               accept_downloads=True)
        for p in (desk, mob):
            p.goto(BASE + '/', wait_until='networkidle', timeout=60000)
            p.wait_for_timeout(7000)
            dismiss(p)
        check('no overlays at start',
              overlays(desk) == 0 and overlays(mob) == 0)

        # ---------- stage batch 1042 on BatchDetail ----------
        desk.goto(BASE + '/log', wait_until='networkidle', timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        check('batch 1042 selected', select_batch_row(desk, 1042))
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        body = desk.evaluate("document.body.textContent")
        check('BatchDetail still shows its existing content',
              'Batch 1042' in body and 'Phase Analysis' in body
              and 'Loss, Yield and Density' in body
              and 'Analyzer' in body)
        for name in ('Export .alog', 'Export CSV', 'Export JSON',
                     'Print Summary'):
            check('export button present: ' + name,
                  desk.get_by_role('button', name=name).count() >= 1)
        check('calculator card present',
              'Yield and Conversion Calculator' in body)

        # ---------- item 18: CSV ------------------------------
        fname, csv_text = download(desk, 'Export CSV')
        check('CSV filename', fname == 'roastery-batch-1042.csv', fname)
        check('CSV header carries the batch metadata',
              '# Batch,1042' in csv_text
              and '# Bean,Ethiopia Guji' in csv_text
              and '# Charge weight g,200' in csv_text
              and '# Weight loss pct,14' in csv_text)
        data_lines = [ln for ln in csv_text.splitlines()
                      if ln and not ln.startswith('#')]
        check('CSV column header',
              data_lines[0] == 'time_sec,time_mmss,bean_temp_f,'
              'rate_of_rise_f_per_min,fan_level,heat_level',
              data_lines[0])
        rows = list(csv.reader(io.StringIO('\n'.join(data_lines[1:]))))
        ok = len(rows) == len(series)
        for got, want in zip(rows, series):
            if not (approx(got[0], want[0], 0.06)
                    and approx(got[2], want[1], 0.011)
                    and approx(got[3], want[2], 0.011)):
                ok = False
        check('CSV series rows match the stored series '
              '(t, BT, RoR recomputed from Postgres)', ok,
              (len(rows), len(series)))

        # ---------- item 18: JSON -----------------------------
        fname, json_text = download(desk, 'Export JSON')
        check('JSON filename', fname == 'roastery-batch-1042.json', fname)
        payload = json.loads(json_text)
        jdoc = payload.get('document') or {}
        jseries = payload.get('series') or []
        ok = (payload.get('batchNumber') == 1042
              and jdoc.get('beanName') == doc.get('beanName')
              and approx(jdoc.get('weightLossPct'),
                         doc.get('weightLossPct'), 1e-9)
              and jdoc.get('metadata', {}).get('ChargeWeightG')
              == doc.get('metadata', {}).get('ChargeWeightG'))
        check('JSON carries the full batch document', ok)
        ok = len(jseries) == len(series) and all(
            approx(r['t'], w[0], 1e-6) and approx(r['bt'], w[1], 1e-6)
            and approx(r['ror'], w[2], 1e-6)
            for r, w in zip(jseries, series))
        check('JSON series matches the stored series', ok,
              len(jseries))

        # ---------- item 18: printable summary -----------------
        fname, html = download(desk, 'Print Summary')
        check('summary filename',
              fname == 'roastery-batch-1042-summary.html', fname)
        max_bt = max(bt for _t, bt, _r, _f, _h in series)
        check('summary carries the right values',
              'Batch 1042 - Ethiopia Guji' in html
              and 'Phase Analysis' in html
              and 'Samples' in html and '>21<' in html
              and ('%.1f F' % max_bt) in html
              and '14.0%' in html, html[:200])
        with open('/tmp/tier3-summary.html', 'w') as f:
            f.write(html)
        desk.goto('file:///tmp/tier3-summary.html')
        desk.wait_for_timeout(1200)
        desk.screenshot(path=SHOTS + '/roastery-tier3-summary-print.png')
        check('summary renders as a standalone page',
              'Phase Analysis' in desk.evaluate(
                  "document.body.textContent"))
        desk.goto(BASE + '/log/detail', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)

        # ---------- item 21: calculator ------------------------
        # detail_startup seeded the calculator from batch 1042:
        # charge 200 g, out 172 g, so actual loss reads 14.0%.
        seeded = wait_until(
            lambda: approx(tag(CALC + '/ChargeG'), 200.0, 0.01)
            and approx(tag(CALC + '/OutG'), 172.0, 0.01),
            timeout=20)
        check('calculator is seeded from the staged batch weights',
              bool(seeded), (tag(CALC + '/ChargeG'), tag(CALC + '/OutG')))
        check('seeded reverse loss is the batch loss (14.0 pct)',
              approx(tag(CALC + '/ActualLossPct'), 14.0, 0.05),
              tag(CALC + '/ActualLossPct'))
        n_inputs = desk.locator(
            '[data-component="ia.input.numeric-entry-field"] '
            'input').count()
        check('calculator has seven numeric inputs', n_inputs == 7,
              n_inputs)
        # DOM order: Charge, Loss, Out, TempF, TempCIn, ConvG, ConvOzIn
        fill_input(desk, 0, 250)
        check('UI charge edit writes the Calculator tag',
              approx(tag(CALC + '/ChargeG'), 250.0, 0.01),
              tag(CALC + '/ChargeG'))
        check('forward yield at 15 pct loss: 212.5 g and 7.50 oz',
              approx(tag(CALC + '/ExpectedOutG'), 212.5, 0.05)
              and approx(tag(CALC + '/ExpectedOutOz'),
                         212.5 / 28.349523125, 0.02),
              (tag(CALC + '/ExpectedOutG'), tag(CALC + '/ExpectedOutOz')))
        fill_input(desk, 1, 12)
        check('forward yield at 12 pct loss: 220.0 g',
              approx(tag(CALC + '/ExpectedOutG'), 220.0, 0.05),
              tag(CALC + '/ExpectedOutG'))
        body = desk.evaluate("document.body.textContent")
        check('expected out readout renders in the card',
              '220.0' in body)
        fill_input(desk, 2, 220)
        check('reverse: out 220 g from 250 g is 12.0 pct loss',
              approx(tag(CALC + '/ActualLossPct'), 12.0, 0.05),
              tag(CALC + '/ActualLossPct'))
        fill_input(desk, 3, 212)
        check('conversion: 212 F is 100.0 C',
              approx(tag(CALC + '/TempC'), 100.0, 0.05),
              tag(CALC + '/TempC'))
        fill_input(desk, 4, 100)
        check('conversion: 100 C is 212.0 F',
              approx(tag(CALC + '/TempFOut'), 212.0, 0.05),
              tag(CALC + '/TempFOut'))
        fill_input(desk, 5, 100)
        check('conversion: 100 g is 3.53 oz',
              approx(tag(CALC + '/ConvOz'), 100 / 28.349523125, 0.02),
              tag(CALC + '/ConvOz'))
        fill_input(desk, 6, 10)
        check('conversion: 10 oz is 283.5 g',
              approx(tag(CALC + '/ConvGOut'), 10 * 28.349523125, 0.05),
              tag(CALC + '/ConvGOut'))
        desk.locator('text=Yield and Conversion Calculator') \
            .first.scroll_into_view_if_needed()
        desk.wait_for_timeout(800)
        desk.screenshot(path=SHOTS + '/roastery-tier3-calculator.png')
        desk.screenshot(path=SHOTS + '/roastery-tier3-detail-desktop.png')
        check('no overlays on BatchDetail',
              overlays(desk) == 0)

        # ---------- mobile --------------------------------------
        mob.goto(BASE + '/log/detail', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        worst = overflow_worst(mob)
        check('BatchDetail has no overflow at 360px', worst <= 361,
              worst)
        mob.locator('text=Yield and Conversion Calculator') \
            .first.scroll_into_view_if_needed()
        mob.wait_for_timeout(800)
        mob.screenshot(path=SHOTS + '/roastery-tier3-detail-360.png')
        check('no overlays at 360px', overlays(mob) == 0)
        browser.close()

    # ---------- restore and final state -------------------------
    write_tags([(CALC + '/ChargeG', 200.0), (CALC + '/LossPct', 15.0),
                (CALC + '/OutG', 170.0), (CALC + '/TempF', 415.0),
                (CALC + '/TempCIn', 200.0), (CALC + '/ConvG', 200.0),
                (CALC + '/ConvOzIn', 7.0)])
    check('calculator tags back at their defaults',
          approx(tag(CALC + '/ExpectedOutG'), 170.0, 0.05)
          and approx(tag(CALC + '/ActualLossPct'), 15.0, 0.05)
          and approx(tag(CALC + '/TempC'), 212.7778, 0.01))
    # Another agent is building transaction groups in this lab
    # concurrently; its test rows can be briefly visible. Wait
    # for the counts to settle back to the seeded log.
    def _counts():
        return (int(psql('SELECT COUNT(*) FROM batches')),
                int(psql('SELECT COUNT(*) FROM batch_series')),
                int(psql('SELECT COUNT(*) FROM batch_events')))
    end = wait_until(lambda: _counts() == base or None, timeout=60) \
        or _counts()
    if not isinstance(end, tuple):
        end = _counts()
    check('lab back to the seeded log', end == base, end)
    state = read_tags([B + '/State', B + '/FanLevel', B + '/HeatLevel',
                       B + '/BatchNumber', B + '/ActiveSource',
                       B + '/Mode'])
    check('workspace clean Idle', state == ['Idle', 5, 5, 1042,
                                            'Simulated', 'Off'], state)
    check('background cleared',
          (tag('[default]Roastery/BackgroundLabel') or '') == '')
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad, bad[:3])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL TIER 3A CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
