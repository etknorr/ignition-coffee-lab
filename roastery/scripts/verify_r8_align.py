#!/usr/bin/env python3
"""HUNT-56 (polish round 8): event-based compare alignment.

Artisan 5.0.0's alignEvent (comparator.py realign, canvas.py
timealign) aligns every compared profile after the first to
the top profile's chosen event (CHARGE, DRY, FCs, FCe, SCs,
SCe, DROP), shifting each curve by its event offset and
drawing a vertical align line at the reference time; a
profile missing the event falls back to its charge. This
build implements that in roastery.batches (compare_dataset
/ align_compare_slots, shifts snapped to the 30 s library
grid per HUNT-51), with the choice on one tag-backed
setting (CompareAlignEvent, default CHARGE) exposed both
in Settings Display and on the Log compare row.

Live proof, in two phases:
  Phase 1, gateway math through the same library functions
  build_compare calls: two full-length fixtures, 9920
  (720 s, FCs 540, DROP 720) and 9921 (660 s, FCs 420,
  DROP 660, added here), aligned on FCs, DROP and CHARGE.
  The curves must shift by the event offset (FCs: B -120 s,
  DROP: B -60 s), the reference second must be the
  reference batch's event, every label must be an even
  30 s step, and the single ALIGN reference line item
  must name the aligned event at the snapped reference
  second. A synthetic two-slot case proves the
  missing-event fallback (B with no SCs aligns its charge
  to the reference SCs), and the seeded stub 1048 is
  checked the same way when it lacks the event.
  Phase 1 also covers HUNT-61: a no-curve batch (1050,
  batch row, 0 series rows) staged as C keeps the FCs
  grid and rows and appends ' | Batch 1050 has no curve
  data.' to the caption; with only C=1050 the caption
  keeps the pick-at-least-one line plus the note.
  Phase 2, live UI: the CmpAlign dropdown and the
  Settings Display dropdown both write the one tag;
  Compare stages A=9920 B=9921 with the caption naming
  the alignment at desktop Light (FCs, then DROP) and at
  360px Light (DROP), with no horizontal overflow at
  360px and element screenshots of both charts.
  Phase 3 (HUNT-61, live UI): batch 1050 is created
  through the New Batch form (no series rows), staged as
  C with A=1048 B=1047, Compare pressed at desktop and
  360px Light with Align CHARGE, and the caption must
  name the batch with the no-curve note at both widths.
Fixtures are deleted through the Log UI afterwards
(PressSlots cleared first, HUNT-53); the lab is left at
(7, 101, 0) Idle, theme System, CompareAlignEvent CHARGE.
Harness note: each UI phase launches its own browser;
the single-process Chromium died across context switches
in run 1 (TargetClosedError opening the Settings page),
while the suite finally still cleaned the lab. Phase 4
relaunches the browser inside the same playwright
session instead: a second sync_playwright() in this
process died on new_page the same way.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B
check = P.check
FAILURES = P.FAILURES
tag = P.tag
write_tags = P.write_tags
wait_until = P.wait_until
psql = P.psql

TM = '[default]Roastery/AppSettings/ThemeMode'
ALIGN_TAG = B + '/CompareAlignEvent'
ALIGN_LABELS = {'CHARGE', 'DRY', 'FCs', 'FCe', 'SCs', 'SCe', 'DROP'}

INK_JS = """() => {
  const charts = [...document.querySelectorAll(
    '[data-component="ia.canvas-charts.line"]')];
  let ink = 0, canvases = 0;
  for (const el of charts) {
    if (getComputedStyle(el).display === 'none') continue;
    for (const cv of el.querySelectorAll('canvas')) {
      canvases++;
      const ctx = cv.getContext('2d');
      if (!ctx) continue;
      const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
      for (let i = 0; i < d.length; i += 4) {
        const mx = Math.max(d[i], d[i+1], d[i+2]);
        const mn = Math.min(d[i], d[i+1], d[i+2]);
        if (mx - mn > 40) ink++;
      }
    }
  }
  return {ink, canvases};
}"""

OVERFLOW_JS = """() => ({
  doc: document.documentElement.scrollWidth,
  body: document.body.scrollWidth,
  inner: window.innerWidth})"""


def dismiss_modal(page):
    """Fixed dismiss: judge by the AGREE & CLOSE button count,
    never by the 'Personal Use Only' text count (the footer
    carries a permanent copy)."""
    for _ in range(40):
        try:
            if page.get_by_text('AGREE & CLOSE').count() > 0:
                page.get_by_text('AGREE & CLOSE').first.click(
                    timeout=5000)
                page.wait_for_timeout(1200)
                if page.get_by_text('AGREE & CLOSE').count() == 0:
                    return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return page.get_by_text('AGREE & CLOSE').count() == 0


def caption(page):
    return page.evaluate(
        "() => [...document.querySelectorAll("
        "'[data-component=\"ia.display.label\"]')].map("
        "e => e.textContent.trim()).filter("
        "t => t.includes('A = Batch'))")


def dropdown_texts(page):
    dds = page.locator('[data-component="ia.input.dropdown"]')
    return [dds.nth(i).inner_text().replace('\n', ' | ')
            for i in range(dds.count())]


def pick(page, slot_idx, option_label):
    """slot_idx 0=A, 1=B, 2=C. Click the dropdown, then the
    option anchor in its popup list."""
    dds = page.locator('[data-component="ia.input.dropdown"]')
    dds.nth(slot_idx).click(timeout=20000)
    page.wait_for_timeout(900)
    page.locator('a.iaDropdownCommon_option',
                 has_text=option_label).first.click(timeout=20000)
    page.wait_for_timeout(1500)
    texts = dropdown_texts(page)
    assert option_label in texts[slot_idx], texts
    return texts


def pick_align(page, option_label):
    """Pick the compare alignment by its current label: the
    CmpAlign dropdown is the dropdown whose text is an align
    label (CHARGE, DRY, FCs, ...)."""
    dds = page.locator('[data-component="ia.input.dropdown"]')
    idx = None
    for i in range(dds.count()):
        if dds.nth(i).inner_text().strip() in ALIGN_LABELS:
            idx = i
            break
    assert idx is not None, dropdown_texts(page)
    dds.nth(idx).click(timeout=20000)
    page.wait_for_timeout(900)
    page.locator('a.iaDropdownCommon_option',
                 has_text=option_label).first.click(timeout=20000)
    page.wait_for_timeout(1500)
    texts = dropdown_texts(page)
    assert texts[idx] == option_label, texts
    return texts


def align_dropdown_text(page):
    for t in dropdown_texts(page):
        if t.strip() in ALIGN_LABELS:
            return t.strip()
    return None


def compare(page):
    page.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    page.wait_for_timeout(4000)
    return caption(page)


def shoot_chart(pg, name):
    charts = pg.locator('[data-component="ia.canvas-charts.line"]')
    for i in range(charts.count()):
        if pg.evaluate(
                "(i) => getComputedStyle(document"
                ".querySelectorAll('[data-component=\""
                "ia.canvas-charts.line\"]')[i]).display",
                i) != 'none':
            charts.nth(i).scroll_into_view_if_needed()
            pg.wait_for_timeout(1200)
            charts.nth(i).screenshot(
                path=os.path.join(SHOTS, name), timeout=30000)
            return True
    return False


def open_log(browser, width, height):
    ctx = browser.new_context(
        viewport={'width': width, 'height': height},
        timezone_id='America/Denver')
    pg = ctx.new_page()
    pg.goto(BASE + '/log', wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    assert dismiss_modal(pg), 'modal still up'
    pg.wait_for_timeout(1500)
    return ctx, pg


# ---- Fixture 9921: second full-length batch, event times
# deliberately offset from 9920 (FCs 420 vs 540, DROP 660
# vs 720), so alignment on either event must shift B.
DOC_9921 = {
    'batchNumber': 9921, 'beanName': 'R8 Second Fixture',
    'roastStart': '2026-11-20T08:00:00',
    'roastEnd': '2026-11-20T08:11:00',
    'dropTempF': 418.0, 'roastDegree': 'Full City',
    'totalSec': 660,
    'phases': {'dryingSec': 210, 'maillardSec': 210,
               'developmentSec': 240, 'dtrPct': 36.36},
    'auc': 512.0, 'weightLossPct': 14.0, 'source': 'Simulated',
    'metadata': {'BeanName': 'R8 Second Fixture'},
    'events': {
        'charge': {'t': 0, 'ts': '2026-11-20T08:00:00',
                   'tempF': 392.0},
        'dryEnd': {'t': 210, 'ts': '2026-11-20T08:03:30',
                   'tempF': 320.0},
        'fcStart': {'t': 420, 'ts': '2026-11-20T08:07:00',
                    'tempF': 385.0},
        'fcEnd': {'t': 450, 'ts': '2026-11-20T08:07:30',
                  'tempF': 390.0},
        'scStart': {'t': 570, 'ts': '2026-11-20T08:09:30',
                    'tempF': 405.0},
        'scEnd': {'t': 600, 'ts': '2026-11-20T08:10:00',
                  'tempF': 410.0},
        'drop': {'t': 660, 'ts': '2026-11-20T08:11:00',
                 'tempF': 418.0},
        'custom': []},
    'target': {}, 'fanHeatTrace': []}


def series_9921():
    pts = []
    for t in range(0, 661, 15):
        if t <= 60:
            bt = round(392.0 - 22.0 * (t / 60.0), 1)
            if t == 60:
                bt = 370.0
        else:
            frac = (t - 60) / 600.0
            bt = round(370.0 + 45.0 * (frac ** 1.12), 1)
        pts.append((t, bt))
    pts[-1] = (660, 418.0)
    return pts


def insert_9921():
    if psql('SELECT COUNT(*) FROM batches WHERE '
            'batch_number = 9921') == '1':
        print('fixture 9921 already present')
        return
    docj = json.dumps(DOC_9921).replace("'", "''")
    psql("INSERT INTO batches (batch_number, roast_start, "
         "roast_end, bean_name, drop_temp_f, data) VALUES "
         "(9921, '%s', '%s', '%s', %s, '%s'::jsonb)"
         % (DOC_9921['roastStart'], DOC_9921['roastEnd'],
            DOC_9921['beanName'], DOC_9921['dropTempF'], docj))
    vals = ','.join("(%d, %d, %s, 5, 5)" % (9921, t, bt)
                   for t, bt in series_9921())
    psql('INSERT INTO batch_series (batch_number, '
         't_offset_sec, bean_temp_f, fan_level, heat_level) '
         'VALUES ' + vals)
    print('fixture 9921 inserted, %d series points'
          % len(series_9921()))


def insert_nocurve_1050():
    """HUNT-61 fixture: batch 1050 as a bare batch row with
    no series rows (the state a New Batch form create
    leaves), so compare_dataset must name it in the
    caption instead of silently skipping it."""
    if psql('SELECT COUNT(*) FROM batches WHERE '
            'batch_number = 1050') == '1':
        print('no-curve batch 1050 already present')
        return
    docj = json.dumps({'batchNumber': 1050,
                       'beanName': 'R8 NoCurve', 'events': {}})
    psql("INSERT INTO batches (batch_number, roast_start, "
         "roast_end, bean_name, drop_temp_f, data) VALUES "
         "(1050, '2026-11-20T09:00:00', '2026-11-20T09:00:00', "
         "'R8 NoCurve', 0, '%s'::jsonb)" % docj)
    print('no-curve batch 1050 inserted, 0 series rows',
          flush=True)


def delete_fixture(number):
    """Delete one fixture batch through the Log UI (the same
    flow R5.delete_fixtures uses for 9919/9920)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                            timezone_id='America/Denver')
        last_err = None
        for attempt in range(3):
            try:
                pg = R5.open_page(ctx, '/log')
                pg.locator('text=%s' % format(number, ',')).first.click(
                    timeout=45000)
                pg.wait_for_timeout(1200)
                pg.get_by_role('button',
                               name='Delete').first.click(
                                   timeout=25000)
                pg.wait_for_timeout(1200)
                pg.get_by_role(
                    'button',
                    name='Confirm Delete').first.click(
                        timeout=25000)
                pg.wait_for_timeout(2500)
                pg.close()
                last_err = None
                break
            except Exception as e:
                last_err = e
                print('delete retry %d attempt %d: %s'
                      % (number, attempt + 1, str(e)[:100]),
                      flush=True)
        ctx.close()
        b.close()
    if last_err is not None:
        raise last_err
    print('deleted via app:', number,
          psql('SELECT COUNT(*) FROM batches WHERE '
               'batch_number = %d' % number), flush=True)


SNIPPET = """\timport roastery.batches as B
\timport roastery.core as C
\tdef summ(rows, caption, ref_items, info):
\t\tcols = {}
\t\tfor ci, key in enumerate(('btA', 'rorA', 'btB', 'rorB', 'btC', 'rorC')):
\t\t\tcols[key] = [[int(r[2]), float(r[3 + ci])] for r in rows if r[3 + ci] is not None]
\t\treturn {'t_secs': [int(r[2]) for r in rows],
\t\t\t'cols': cols, 'caption': caption,
\t\t\t'ref_items': ref_items, 'shifts': info['shifts'],
\t\t\t'ref_sec': info['ref_sec'],
\t\t\t'max_sec': info['max_sec'],
\t\t\t'offset_sec': info['offset_sec'],
\t\t\t'fallbacks': info['fallbacks'],
\t\t\t'nrows': len(rows)}
\tout = {}
\tout['tag_align'] = B.compare_align_event()
\trows, cap, refs, info = B.compare_dataset([('A', 9920), ('B', 9921)])
\tout['tag_case'] = summ(rows, cap, refs, info)
\tfor key in ('fcStart', 'drop', 'charge'):
\t\trows, cap, refs, info = B.compare_dataset([('A', 9920), ('B', 9921)], key)
\t\tout[key] = summ(rows, cap, refs, info)
\tsynth = B.align_compare_slots([
\t\t{'slot': 'A', 'number': 9920, 'bean': '', 'points': [(0, 392.0), (540, 401.5)], 'rors': {}, 'events': {'charge': 0.0, 'fcStart': 540.0, 'scStart': 660.0, 'drop': 720.0}},
\t\t{'slot': 'B', 'number': 9921, 'bean': '', 'points': [(0, 392.0), (420, 395.4)], 'rors': {}, 'events': {'charge': 0.0, 'fcStart': 420.0, 'scStart': None, 'drop': 660.0}}], 'scStart')
\tout['fallback_synth'] = {'shifts': synth['shifts'], 'ref_sec': synth['ref_sec'], 'fallbacks': synth['fallbacks'], 'offset_sec': synth['offset_sec'], 'max_sec': synth['max_sec']}
\tstub_doc = (B.get_batch(1048) or {}).get('document') or {}
\tout['stub_events_1048'] = B._compare_events(stub_doc)
\trows, cap, refs, info = B.compare_dataset([('A', 9920), ('B', 1048)], 'scStart')
\tout['stub_case'] = summ(rows, cap, refs, info)
\trows, cap, refs, info = B.compare_dataset([('A', 9920), ('B', 9921), ('C', 1050)])
\tout['nocurve'] = summ(rows, cap, refs, info)
\trows, cap, refs, info = B.compare_dataset([('C', 1050)])
\tout['nocurve_only'] = summ(rows, cap, refs, info)
\tRESULT = out
"""


def run_snippet():
    snip = '/tmp/r8_align_suite.jy'
    with open(snip, 'w') as f:
        f.write(SNIPPET)
    out = subprocess.run(
        [os.path.join('/home/hatch/workspace/ignition-lab',
                      'wsvenv/bin/python'),
         os.path.join('/home/hatch/workspace/ignition-lab',
                      'scratch_run.py'), snip],
        capture_output=True, text=True,
        cwd='/home/hatch/workspace/ignition-lab', timeout=300)
    return json.loads(out.stdout.strip().splitlines()[-1])


def bt_at(case, col, sec):
    for s, v in case['cols'][col]:
        if s == sec:
            return v
    return None


def wait_gateway(timeout=600):
    """Wait for the Maker gateway to answer RUNNING (the lab
    may still be recovering from a VM replacement when the
    suite starts); True when up, False on timeout."""
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(
                    'http://localhost:8088/StatusPing',
                    timeout=5) as r:
                if 'RUNNING' in r.read().decode('utf-8', 'replace'):
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main():
    os.makedirs(SHOTS, exist_ok=True)
    if not wait_gateway():
        print('HUNT-56 FAILURES: gateway never reached RUNNING')
        return 1
    wait_until(
        lambda: tag(B + '/State') == 'Idle'
        and int(psql('SELECT COUNT(*) FROM batch_events')) == 0,
        180)
    base = (int(psql('SELECT COUNT(*) FROM batches')),
            int(psql('SELECT COUNT(*) FROM batch_series')),
            int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base == (7, 101, 0), base)
    check('lab starts Idle', tag(B + '/State') == 'Idle',
          tag(B + '/State'))
    check('CompareAlignEvent tag exists, default CHARGE',
          tag(ALIGN_TAG) == 'charge', tag(ALIGN_TAG))
    theme0 = tag(TM)
    align0 = tag(ALIGN_TAG)
    try:
        # ---- Fixtures in ----
        R5.fixtures()
        insert_9921()
        mid = (int(psql('SELECT COUNT(*) FROM batches')),
               int(psql('SELECT COUNT(*) FROM batch_series')),
               int(psql('SELECT COUNT(*) FROM batch_events')))
        check('fixtures 9919/9920/9921 inserted',
              mid == (10, 211, 0), mid)
        # ---- Phase 1: gateway math ----
        insert_nocurve_1050()
        write_tags([(ALIGN_TAG, 'fcStart')])
        data = run_snippet()
        print('snippet tag_align:', data['tag_align'], flush=True)
        check('tag drives compare_dataset (fcStart via tag)',
              data['tag_align'] == 'fcStart'
              and data['tag_case']['ref_sec'] == 540,
              data['tag_case']['ref_sec'])
        fc = data['fcStart']
        print('FCs case:', {k: fc[k] for k in
                            ('shifts', 'ref_sec', 'max_sec',
                             'nrows', 'offset_sec')}, flush=True)
        check('FCs: B shifts -120 s (420 to 540)',
              fc['shifts'] == {'A': 0, 'B': -120}, fc['shifts'])
        check('FCs: reference second is 540',
              fc['ref_sec'] == 540, fc['ref_sec'])
        check('FCs: grid runs 0..780 in 30 s steps',
              fc['t_secs'] == list(range(0, 781, 30)),
              (fc['t_secs'][:3], fc['t_secs'][-3:],
               fc['nrows']))
        check('FCs: B charge lands at 120, A charge stays 0',
              bt_at(fc, 'btB', 120) == 392.0
              and bt_at(fc, 'btA', 0) == 392.0,
              (bt_at(fc, 'btB', 120), bt_at(fc, 'btA', 0)))
        check('FCs: both curves meet at the aligned bucket 540',
              bt_at(fc, 'btA', 540) is not None
              and bt_at(fc, 'btB', 540) is not None
              and abs(bt_at(fc, 'btA', 540) - 401.5) < 0.01
              and abs(bt_at(fc, 'btB', 540) - 395.4) < 0.01,
              (bt_at(fc, 'btA', 540), bt_at(fc, 'btB', 540)))
        check('FCs: caption names the alignment',
              'Aligned on FCs' in fc['caption'], fc['caption'])
        check('FCs: one ALIGN ref line at 9:00',
              len(fc['ref_items']) == 1
              and fc['ref_items'][0]['value'] == '9:00'
              and fc['ref_items'][0]['label']['text']
              == 'ALIGN FCs',
              fc['ref_items'])
        dr = data['drop']
        print('DROP case:', {k: dr[k] for k in
                             ('shifts', 'ref_sec', 'max_sec',
                              'nrows', 'offset_sec')}, flush=True)
        check('DROP: B shifts -60 s (660 to 720)',
              dr['shifts'] == {'A': 0, 'B': -60}, dr['shifts'])
        check('DROP: reference second is 720',
              dr['ref_sec'] == 720, dr['ref_sec'])
        check('DROP: grid runs 0..720 in 30 s steps',
              dr['t_secs'] == list(range(0, 721, 30)),
              (dr['t_secs'][:3], dr['t_secs'][-3:]))
        check('DROP: both drops land at 720 with distinct temps',
              bt_at(dr, 'btA', 720) == 415.0
              and bt_at(dr, 'btB', 720) == 418.0,
              (bt_at(dr, 'btA', 720), bt_at(dr, 'btB', 720)))
        check('DROP: caption names the alignment',
              'Aligned on DROP' in dr['caption'], dr['caption'])
        check('DROP: one ALIGN ref line at 12:00',
              len(dr['ref_items']) == 1
              and dr['ref_items'][0]['value'] == '12:00'
              and dr['ref_items'][0]['label']['text']
              == 'ALIGN DROP',
              dr['ref_items'])
        ch = data['charge']
        check('CHARGE: no shift, reference 0, grid 0..720',
              ch['shifts'] == {'A': 0, 'B': 0}
              and ch['ref_sec'] == 0
              and ch['t_secs'] == list(range(0, 721, 30)),
              (ch['shifts'], ch['ref_sec'], ch['nrows']))
        check('CHARGE: caption names the alignment',
              'Aligned on CHARGE' in ch['caption'], ch['caption'])
        fb = data['fallback_synth']
        print('fallback synthetic:', fb, flush=True)
        check('fallback: B with no SCs aligns its charge to 660',
              fb['shifts'] == {'A': 0, 'B': -660}
              and fb['ref_sec'] == 660
              and fb['fallbacks'] == [['B', 9921]],
              fb)
        print('stub 1048 events:', data['stub_events_1048'],
              flush=True)
        if data['stub_events_1048'].get('scStart') is None:
            sc = data['stub_case']
            check('stub: B=1048 with no SCs falls back in caption',
                  'B has no SCs, charge aligned' in sc['caption']
                  and sc['fallbacks'] == [['B', 1048]],
                  sc['caption'])
        else:
            print('stub 1048 carries SCs; live fallback case '
                  'not applicable', flush=True)
        nc = data['nocurve']
        print('nocurve case:', nc['caption'], flush=True)
        check('nocurve: caption names A/B, FCs and the 1050 note',
              'A = Batch 9920' in nc['caption']
              and 'B = Batch 9921' in nc['caption']
              and 'Aligned on FCs' in nc['caption']
              and 'Batch 1050 has no curve data.' in nc['caption'],
              nc['caption'])
        check('nocurve: grid and rows unchanged from the FCs case',
              nc['t_secs'] == fc['t_secs']
              and nc['nrows'] == fc['nrows'],
              (nc['nrows'], fc['nrows']))
        nco = data['nocurve_only']
        check('nocurve only: pick line plus the 1050 note',
              'Pick at least one batch to compare.'
              in nco['caption']
              and 'Batch 1050 has no curve data.' in nco['caption']
              and nco['nrows'] == 0,
              nco['caption'])
        psql('DELETE FROM batches WHERE batch_number = 1050')
        # ---- Phase 2: live UI ----
        with sync_playwright() as pw:
            browser = R5.launch(pw)
            try:
                write_tags([(TM, 'Light'), (ALIGN_TAG, 'fcStart')])
                ctx, pg = open_log(browser, 1360, 900)
                try:
                    check('compare row Align dropdown reads FCs',
                          align_dropdown_text(pg) == 'FCs',
                          dropdown_texts(pg))
                    pick(pg, 0, 'Batch 9920 - R5 Normal Fixture')
                    pick(pg, 1, 'Batch 9921 - R8 Second Fixture')
                    caps = compare(pg)
                    check('desktop FCs: caption lists A/B and FCs',
                          any('A = Batch 9920' in c for c in caps)
                          and any('B = Batch 9921' in c for c in caps)
                          and any('Aligned on FCs' in c for c in caps),
                          caps)
                    ink = pg.evaluate(INK_JS)
                    print('FCs compare chart ink:', ink, flush=True)
                    check('desktop FCs: compare chart draws',
                          ink['ink'] > 1000 and ink['canvases'] >= 1,
                          ink)
                    check('desktop FCs chart element shot',
                          shoot_chart(pg, 'r8-align-fcs-desktop.png'),
                          'r8-align-fcs-desktop.png')
                    pick_align(pg, 'DROP')
                    check('compare row pick writes the tag',
                          tag(ALIGN_TAG) == 'drop', tag(ALIGN_TAG))
                    caps = compare(pg)
                    check('desktop DROP: caption lists A/B and DROP',
                          any('A = Batch 9920' in c for c in caps)
                          and any('B = Batch 9921' in c for c in caps)
                          and any('Aligned on DROP' in c for c in caps),
                          caps)
                    check('desktop DROP chart element shot',
                          shoot_chart(pg, 'r8-align-drop-desktop.png'),
                          'r8-align-drop-desktop.png')
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r8-align-log-drop-desktop.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                # Settings Display dropdown writes the same tag.
                # Fresh browser per phase: the single-process
                # Chromium dies across context switches (run 1
                # lost the browser between the desktop and
                # Settings phases), so each phase launches its
                # own and closes the last.
                try:
                    browser.close()
                except Exception:
                    pass
                browser = R5.launch(pw)
                ctx = browser.new_context(
                    viewport={'width': 1360, 'height': 900},
                    timezone_id='America/Denver')
                pg = ctx.new_page()
                try:
                    pg.goto(BASE + '/settings',
                            wait_until='domcontentloaded',
                            timeout=60000)
                    pg.wait_for_timeout(6000)
                    assert dismiss_modal(pg), 'modal still up'
                    pg.wait_for_timeout(1500)
                    pg.get_by_text('Compare alignment').first.\
                        scroll_into_view_if_needed()
                    pg.wait_for_timeout(800)
                    check('settings Align dropdown reads DROP',
                          align_dropdown_text(pg) == 'DROP',
                          dropdown_texts(pg))
                    pick_align(pg, 'CHARGE')
                    check('settings pick writes the tag',
                          tag(ALIGN_TAG) == 'charge', tag(ALIGN_TAG))
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r8-align-settings.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                # ---- Phase 3: 360px, DROP ----
                try:
                    browser.close()
                except Exception:
                    pass
                browser = R5.launch(pw)
                write_tags([(ALIGN_TAG, 'drop')])
                ctx, pg = open_log(browser, 360, 740)
                try:
                    pick(pg, 0, 'Batch 9920 - R5 Normal Fixture')
                    pick(pg, 1, 'Batch 9921 - R8 Second Fixture')
                    caps = compare(pg)
                    check('360px DROP: caption lists A/B and DROP',
                          any('A = Batch 9920' in c for c in caps)
                          and any('B = Batch 9921' in c for c in caps)
                          and any('Aligned on DROP' in c for c in caps),
                          caps)
                    ov = pg.evaluate(OVERFLOW_JS)
                    check('no horizontal overflow at 360px',
                          ov['doc'] <= 360 and ov['body'] <= 360,
                          ov)
                    check('360px DROP chart element shot',
                          shoot_chart(pg, 'r8-align-drop-360.png'),
                          'r8-align-drop-360.png')
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r8-align-log-drop-360.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                # ---- Phase 4: HUNT-61 live UI, no-curve batch
                # 1050 ---- Worker C's repro: create 1050
                # through the New Batch form (no series rows),
                # stage it as C with A=1048 B=1047, press
                # Compare with Align CHARGE, and the caption
                # must name 1050 with the no-curve note, at
                # desktop and 360px Light.
                # Fresh browser per phase, relaunched inside
                # this one playwright session like the Settings
                # and 360px phases above: a second
                # sync_playwright() in this process died on
                # new_page (the run-1 single-process flake).
                try:
                    browser.close()
                except Exception:
                    pass
                browser = R5.launch(pw)
                write_tags([(TM, 'Light'), (ALIGN_TAG, 'charge')])
                ctx, pg = open_log(browser, 1360, 900)
                try:
                    pg.get_by_role('button', name='New Batch').first.\
                        click(timeout=20000)
                    pg.wait_for_timeout(3500)
                    fields = pg.locator(
                        'input.ia_form__field, '
                        'textarea.ia_form__field')
                    fields.nth(0).fill('1050')
                    fields.nth(1).fill('R8 NoCurve')
                    fields.nth(0).press('Tab')
                    pg.wait_for_timeout(600)
                    pg.get_by_role('button', name='Save Batch').first.\
                        click(timeout=20000)
                    pg.wait_for_timeout(2000)
                    check('no-curve batch 1050 created, 0 series rows',
                          psql('SELECT COUNT(*) FROM batches WHERE '
                               'batch_number = 1050') == '1'
                          and psql('SELECT COUNT(*) FROM batch_series '
                                   'WHERE batch_number = 1050') == '0',
                          psql('SELECT COUNT(*) FROM batch_series '
                               'WHERE batch_number = 1050'))
                    pg.get_by_role('button', name='Cancel').first.\
                        click(timeout=20000)
                    pg.wait_for_timeout(1500)
                    # Reopen /log in a fresh page of the same
                    # context (worker C's probe pattern): the
                    # pickers were filled at startup, before
                    # 1050 existed, so the page must reload to
                    # list it. A new context in this same
                    # browser died on new_page (single-process
                    # flake), so the context stays open.
                    pg = R5.open_page(ctx, '/log')
                    pg.wait_for_timeout(1500)
                    pick(pg, 0, 'Batch 1048')
                    pick(pg, 1, 'Batch 1047')
                    pick(pg, 2, 'Batch 1050 - R8 NoCurve')
                    caps = compare(pg)
                    check('desktop no-curve: caption names A/B, '
                          'CHARGE and the 1050 note',
                          any('A = Batch 1048' in c for c in caps)
                          and any('B = Batch 1047' in c for c in caps)
                          and any('Aligned on CHARGE' in c
                                  for c in caps)
                          and any('Batch 1050 has no curve data.'
                                  in c for c in caps),
                          caps)
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r8-nocurve-1360-light.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                try:
                    browser.close()
                except Exception:
                    pass
                browser = R5.launch(pw)
                ctx, pg = open_log(browser, 360, 740)
                try:
                    pick(pg, 0, 'Batch 1048')
                    pick(pg, 1, 'Batch 1047')
                    pick(pg, 2, 'Batch 1050 - R8 NoCurve')
                    caps = compare(pg)
                    check('360px no-curve: caption names A/B, '
                          'CHARGE and the 1050 note',
                          any('A = Batch 1048' in c for c in caps)
                          and any('B = Batch 1047' in c for c in caps)
                          and any('Aligned on CHARGE' in c
                                  for c in caps)
                          and any('Batch 1050 has no curve data.'
                                  in c for c in caps),
                          caps)
                    ov = pg.evaluate(OVERFLOW_JS)
                    check('no horizontal overflow at 360px '
                          '(no-curve caption)',
                          ov['doc'] <= 360 and ov['body'] <= 360,
                          ov)
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r8-nocurve-360-light.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
            finally:
                browser.close()
        # Delete the probe batch through the Log UI (PressSlots
        # drained first, HUNT-53); the outer finally guards
        # it too, so a mid-phase failure cannot strand it.
        P.drain_pending()
        if psql('SELECT COUNT(*) FROM batches WHERE '
                'batch_number = 1050') == '1':
            try:
                delete_fixture(1050)
            except Exception as e:
                print('cleanup delete failed for 1050',
                      str(e)[:200], flush=True)
    finally:
        P.drain_pending()
        for n in (1050, 9921, 9920, 9919):
            if psql('SELECT COUNT(*) FROM batches WHERE '
                    'batch_number = %d' % n) != '1':
                continue
            try:
                delete_fixture(n)
            except Exception as e:
                print('cleanup delete failed for', n, str(e)[:200],
                      flush=True)
        write_tags([(TM, theme0 or 'System'),
                    (ALIGN_TAG, align0 or 'charge')])
        end = (int(psql('SELECT COUNT(*) FROM batches')),
               int(psql('SELECT COUNT(*) FROM batch_series')),
               int(psql('SELECT COUNT(*) FROM batch_events')))
        check('lab restored to the seeded baseline',
              end == (7, 101, 0)
              and tag(B + '/State') == 'Idle',
              '%s state=%s' % (end, tag(B + '/State')))
        check('theme restored', tag(TM) == (theme0 or 'System'),
              tag(TM))
        check('align tag restored', tag(ALIGN_TAG) == 'charge',
              tag(ALIGN_TAG))
    print()
    if FAILURES:
        print('HUNT-56/HUNT-61 FAILURES:', FAILURES)
        return 1
    print('ALL HUNT-56/HUNT-61 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
