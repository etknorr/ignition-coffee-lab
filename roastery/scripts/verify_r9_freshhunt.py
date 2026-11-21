#!/usr/bin/env python3
"""Round 9 fresh hunting pass (worker C).

Fresh hunt continuing from HUNT-61. New probes this round:
  1. ThemeMode startup sync (round 8 candidate 5): CLOSED
     by the dedicated probe r9_probe_theme.py (lab-only):
     a 30 s idle window with no session never flips the tag,
     and fresh light and dark sessions sampled every 2 s for
     30 s never flip it either. The tag is only written by
     the App Settings buttons (and by suites that write it
     directly); the single flip seen in the first r9 run was
     a concurrent worker's suite writing Light in the same
     window. No app fix. The probe is not repeated here
     because it is racy in the shared lab.
  2. ALIGN ON label gap (round 8 candidate 8): the label sits
     tight against the top edge of the C picker on the desktop
     Log page. Measure the label-to-picker gap.
  3. Static AUC begin-segment check (HUNT-62): the live
     auc_between used to drop the curve segment straddling
     the AUC begin event; the fix clips it with an
     interpolated temp. Quantified against the exact
     from-begin integral on synthetic curves with the begin
     between samples.
  4. Live roast at 360px DARK (round 8 did light), ghost
     mid-roast, saved roast detail at 360px LIGHT, delete
     through the Log UI. After Drop, the stats line phase
     shares must sum to 100 (HUNT-63: largest remainder
     rounding; the old form read 44/22/33) and DTR must equal
     (drop - FCs) / drop.
  5. Settings scroll sweep at 360px dark (0/25/50/75/100%),
     measuring clipped leaf text at every stop.
  6. Compare with three batches (A/B/C) at 360px dark, caption
     names all three, phone All-columns toggle.
  7. Four-page walk at 1360/360, light/dark (same as round 8),
     plus BatchDetail at 1360px dark with the Phase Analysis
     table text captured and its shares checked.
  8. HUNT-65: seeded batch 1042 Phase Analysis table must
     show Drying, Maillard and Development rows from the
     stored phase splits (it used to show only Cool).
  The ALIGN ON label gap is measured informationally only:
  the Log compare row is owned by a sibling worker in
  round 9, so the suite records the numbers without
  failing on them.

Does NOT retest the timezone TIME axis passthrough or HUNT-46
(both beta-gated) and does NOT touch the press path (HUNT-53
app fix out of scope). Leaves the lab clean.
"""
import ast
import json
import re
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
BG_LABEL = '[default]Roastery/BackgroundLabel'
BG_CURVE = '[default]Roastery/BackgroundCurveJson'
CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
NEXT_BATCH = [0]
BASE = {'batches': '7', 'series': '101', 'events': '0'}
FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '')
    if not cond:
        FAILS.append(name)


OVERFLOW_JS = """() => {
  const vw = window.innerWidth;
  const de = document.documentElement;
  const clipped = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.closest('.secondary-message')) return;
    if (el.children.length === 0 && el.offsetParent !== null) {
      if (el.scrollWidth > el.clientWidth + 1) {
        const t = (el.textContent || '').trim().slice(0, 40);
        if (t) clipped.push(t + ' (' + el.scrollWidth + '>' +
          el.clientWidth + ')');
      }
    }
  });
  return {vw: vw, docW: de.scrollWidth, bodyW: document.body
    ? document.body.scrollWidth : -1,
    clipped: clipped.slice(0, 10), nClipped: clipped.length};
}"""


def measure(pg, label):
    m = pg.evaluate(OVERFLOW_JS)
    check(label + ' no horizontal overflow',
          m['docW'] <= m['vw'], m)
    check(label + ' no clipped leaf text',
          m['nClipped'] == 0, m['clipped'])
    return m


def scroll_to(pg, frac):
    pg.evaluate("""(f) => {
      const el = document.querySelector('.psc-roast-content');
      if (el) { el.scrollTop = el.scrollHeight * f; return; }
      const cands = [...document.querySelectorAll('*')]
        .filter(e => e.scrollHeight > e.clientHeight + 100)
        .sort((a, b) => b.scrollHeight - a.scrollHeight);
      if (cands.length) cands[0].scrollTop =
        cands[0].scrollHeight * f;
    }""", frac)
    pg.wait_for_timeout(900)


def caption_texts(pg):
    return pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")


def click_btn(pg, name, timeout=20000):
    pg.locator('button').filter(has_text=name).first.click(
        timeout=timeout)


def extract_fn(path, name):
    src = open(path).read()
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            ns = {}
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
            return ns[name]
    raise AssertionError('%s not found in %s' % (name, path))


def static_auc():
    """HUNT-62: auc_between vs the exact from-begin integral.

    Artisan profileAUC sums calcAUC over segments ending at
    each sample from the begin index on, and the live
    updateAUC adds the newest segment each tick once past
    begin, so both Artisan paths count the curve segment
    straddling the begin event. auc_between used to keep
    only points at or after begin_sec, dropping that
    segment whole. With the default fixed base of 212 F the
    loss is the straddling segment whenever the begin temp
    is above the base (about 0.2 F-min at the synthetic
    slope, about 1.5 F-min with a real Dry End begin
    near 300 F, on 1 s samples; about 8 F-min on a
    30 s grid). The fix
    clips segments to begin_sec with an interpolated temp,
    the same shape as batches._auc_range. The reference
    below is an independently written exact integral from
    begin_sec on; the begin falls between samples in both
    cases, which is what discriminates the old form.
    """
    auc_between = extract_fn(CORE, 'auc_between')

    def exact_integral(points, begin_sec, base):
        total = 0.0
        for i in range(len(points) - 1):
            t0, v0 = points[i]
            t1, v1 = points[i + 1]
            if t1 <= begin_sec or t1 <= t0:
                continue
            a = max(t0, begin_sec)
            va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
            avg = (va + v1) / 2.0
            if avg > base:
                total += (avg - base) * (t1 - a) / 60.0
        return total

    pts = [(float(t), 200.0 + 0.4 * t) for t in range(0, 301)]
    got = auc_between(pts, 70.5, 200.0)
    want = exact_integral(pts, 70.5, 200.0)
    print('HUNT-62 auc_between=%.4f exact=%.4f'
          % (got, want), flush=True)
    check('HUNT-62 live AUC integrates from the begin second',
          abs(got - want) < 0.001,
          'got %.4f want %.4f' % (got, want))
    grid = [(float(t), 200.0 + 0.4 * t)
            for t in range(0, 301, 30)]
    got_g = auc_between(grid, 75, 200.0)
    want_g = exact_integral(grid, 75, 200.0)
    print('HUNT-62 grid auc_between=%.2f exact=%.2f'
          % (got_g, want_g), flush=True)
    check('HUNT-62 live AUC integrates from begin on 30 s grid',
          abs(got_g - want_g) < 0.001,
          'got %.2f want %.2f' % (got_g, want_g))


def align_label_gap(pw):
    """Round 8 candidate 8: measure the ALIGN ON label gap
    above the C picker on the desktop Log page."""
    P.write_tags([(TM, 'Light')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    gap = pg.evaluate("""() => {
      const labels = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          e.textContent.trim().toLowerCase() === 'align on');
      if (!labels.length) return {found: false};
      const lab = labels[0].getBoundingClientRect();
      const dds = [...document.querySelectorAll(
        '[data-component="ia.input.dropdown"]')];
      if (dds.length < 3) return {found: true, dds: dds.length};
      const pick = dds[2].getBoundingClientRect();
      return {found: true, labelTop: lab.top,
              labelBottom: lab.bottom,
              pickerTop: pick.top, pickerBottom: pick.bottom,
              pickerRight: pick.right, labelLeft: lab.left,
              horizGap: lab.left - pick.right,
              vertOverlap: pick.top - lab.bottom,
              labelH: lab.height};
    }""")
    print('ALIGN ON gap:', gap, flush=True)
    # Informational only: the Log compare row is owned by a
    # sibling worker in round 9 (their stylesheet fix for
    # the caption gap is already live), so this probe records
    # the measurement without failing the suite.
    check('align label measured', gap.get('found') is True, gap)
    R5.shot(pg, 'r9-align-gap-1360-light.png')
    b.close()


def walk(pw, width, height, theme, tag):
    P.write_tags([(TM, theme)])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width,
                                  'height': height},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    measure(pg, 'roast %s' % tag)
    R5.shot(pg, 'r9-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r9-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r9-fresh-detail-%s.png' % tag)
    if tag == '1360-dark':
        body = pg3.locator('body').inner_text()
        m = re.search(
            r'Dry\s+(\S+)\s+(\d+)%.*?Mai\w*\s+(\S+)\s+(\d+)%.*?'
            r'Dev\s+(\S+)\s+(\d+)%', body, re.S)
        if m:
            shares = [int(m.group(2)), int(m.group(4)),
                      int(m.group(6))]
            check('detail 1042 stats shares sum to 100',
                  sum(shares) == 100, shares)
        else:
            check('detail stats line parses', False, body[:200])
    if P.tag('[default]Roastery/SelectedBatchNumber') != 1042:
        print('detail stage stolen mid-walk, retaking', tag,
              flush=True)
        R5.stage_one(1042)
        pg3 = R5.open_page(ctx, '/log/detail')
        pg3.wait_for_timeout(2500)
        measure(pg3, 'detail %s retry' % tag)
        R5.shot(pg3, 'r9-fresh-detail-%s.png' % tag)
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r9-fresh-settings-%s.png' % tag)
    b.close()


def settings_sweep(pw):
    """Probe 5: Settings scroll sweep at 360px dark."""
    P.write_tags([(TM, 'Dark')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(1500)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        scroll_to(pg, frac)
        measure(pg, 'settings sweep %d%% 360-dark'
                % int(frac * 100))
        R5.shot(pg, 'r9-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def live_roast_360_dark(pw):
    """Probe 4: full roast at 360px dark, ghost mid-roast,
    stats line and DTR checked after Drop."""
    P.write_tags([(TM, 'Dark')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    try:
        NEXT_BATCH[0] = int(P.psql(
            'SELECT MAX(batch_number) FROM batches')) + 1
        nxt = NEXT_BATCH[0]
        click_btn(pg, 'New Roast')
        check('new roast takes next batch number',
              P.wait_until(
                  lambda: P.tag(B + '/BatchNumber') == nxt, 30),
              P.tag(B + '/BatchNumber'))
        click_btn(pg, 'Charge')
        check('charge starts the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Roasting', 30))
        pg.wait_for_timeout(8000)
        measure(pg, 'roast live 360-dark')
        R5.shot(pg, 'r9-fresh-roast-live-360-dark.png')
        click_btn(pg, 'Dry End')
        check('dry end stamps', P.wait_until(
            lambda: (P.tag(B + '/DryEndElapsedSec') or -1) >= 0,
            30))
        pg.wait_for_timeout(3000)
        measure(pg, 'roast dry-end 360-dark')
        click_btn(pg, 'FC Start')
        check('fc start stamps', P.wait_until(
            lambda: (P.tag(B + '/FirstCrackStartElapsedSec')
                     or -1) >= 0, 30))
        pg.wait_for_timeout(3000)
        P.write_tags([
            (BG_LABEL, 'Ethiopia Guji (test)'),
            (BG_CURVE, '[[0, 200], [60, 250], [120, 300], '
             '[180, 350], [240, 380]]')])
        pg.wait_for_timeout(3000)
        body = pg.locator('body').inner_text()
        check('background label shows mid-roast dark',
              'Ethiopia Guji (test)' in body, body[:120])
        measure(pg, 'roast ghost live 360-dark')
        R5.shot(pg, 'r9-fresh-roast-ghost-live-360-dark.png')
        P.write_tags([(BG_LABEL, ''), (BG_CURVE, '')])
        click_btn(pg, 'Drop')
        check('drop ends the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Dropped', 30))
        pg.wait_for_timeout(4000)
        body = pg.locator('body').inner_text()
        m = re.search(
            r'Dry\s+(\S+)\s+(\d+)%.*?Mai\w*\s+(\S+)\s+(\d+)%.*?'
            r'Dev\s+(\S+)\s+(\d+)%.*?DTR\s+(\d+)%', body,
            re.S)
        print('stats line after drop:', m.groups() if m else
              body[:400], flush=True)
        if m:
            shares = [int(m.group(2)), int(m.group(4)),
                      int(m.group(6))]
            check('stats phase shares sum to 100',
                  sum(shares) == 100, shares)
            dry = P.tag(B + '/DryEndElapsedSec')
            fc = P.tag(B + '/FirstCrackStartElapsedSec')
            drop = P.tag(B + '/DropElapsedSec')
            want_dtr = round((drop - fc) * 100.0 / drop)
            check('stats DTR equals (drop-FCs)/drop',
                  int(m.group(7)) == want_dtr,
                  'shown %s want %s (dry %s fc %s drop %s)'
                  % (m.group(7), want_dtr, dry, fc, drop))
        else:
            check('stats line parses after drop', False,
                  body[:200])
        measure(pg, 'roast dropped 360-dark')
        R5.shot(pg, 'r9-fresh-roast-dropped-360-dark.png')
        click_btn(pg, 'Finish')
        check('finish reaches Complete', P.wait_until(
            lambda: P.tag(B + '/State') == 'Complete', 30))
        click_btn(pg, 'Save Batch')
        check('roast saves as next batch number', P.wait_until(
            lambda: P.psql('SELECT COUNT(*) FROM batches '
                           'WHERE batch_number = %d' % nxt) == '1',
            30))
        click_btn(pg, 'Reset')
        check('reset returns to Idle', P.wait_until(
            lambda: P.tag(B + '/State') == 'Idle', 30))
    finally:
        b.close()
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('live roast leaves no press rows',
          P.psql('SELECT COUNT(*) FROM batch_events') == '0')


def detail_and_delete(pw):
    """Saved roast detail at 360px light, then delete."""
    nxt = NEXT_BATCH[0]
    label = format(nxt, ',')
    P.write_tags([(TM, 'Light')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    R5.stage_one(nxt)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(2500)
    measure(pg, 'detail %d 360-light' % nxt)
    R5.shot(pg, 'r9-fresh-detail-%d-360-light.png' % nxt)
    body = pg.locator('body').inner_text()
    low = body.lower()
    # innerText returns the rendered uppercase form of the
    # section titles (CSS textTransform), so match lowercase.
    for token in ('phase analysis', 'turning point', 'auc',
                  'dtr'):
        check('detail shows %s' % token, token in low,
              body[:150])
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    pg2.locator('text=%s' % label).first.click(timeout=25000)
    pg2.wait_for_timeout(1200)
    pg2.get_by_role('button', name='Delete').first.click(
        timeout=25000)
    pg2.wait_for_timeout(1000)
    pg2.get_by_role('button',
                    name='Confirm Delete').first.click(
                        timeout=25000)
    pg2.wait_for_timeout(2500)
    check('saved roast deletes through the Log UI',
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = %d' % nxt) == '0')
    b.close()


def compare_three(pw):
    """Probe 6: compare A/B/C at 360px dark."""
    P.write_tags([(TM, 'Dark')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    dds = pg.locator('[data-component="ia.input.dropdown"]')
    dds.nth(2).click(timeout=20000)
    pg.wait_for_timeout(900)
    pg.locator('a.iaDropdownCommon_option',
               has_text='Batch 1046').first.click(timeout=20000)
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = caption_texts(pg)
    check('compare caption names A, B and C at 360 dark',
          any('A = Batch' in c and 'B = Batch' in c
              and 'C = Batch' in c for c in caps), caps)
    measure(pg, 'compare ABC 360-dark')
    R5.shot(pg, 'r9-fresh-compare-abc-360-dark.png')
    pg.get_by_role('button', name='All columns').first.click(
        timeout=10000)
    pg.wait_for_timeout(1500)
    measure(pg, 'log all-columns 360-dark')
    R5.shot(pg, 'r9-fresh-log-allcols-360-dark.png')
    b.close()


def phase_table_1042(pw):
    """HUNT-65: seeded batch 1042 carries stored phase splits
    but no event times, so its Phase Analysis table used to
    show only the Cool row while the stats line showed all
    three phases. The fix falls back to the stored splits
    for seeded batches. Stage 1042 and read the desktop
    AnalysisTable straight from the DOM."""
    P.write_tags([(TM, 'Light')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    R5.stage_one(1042)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(6000)
    tbl = pg.evaluate("""() => {
      const tabs = [...document.querySelectorAll(
        '[data-component="ia.display.table"]')];
      const t = tabs.find(e =>
        (e.textContent || '').includes('Phase'));
      return t ? t.textContent : '';
    }""")
    print('HUNT-65 analysis table:', tbl[:200], flush=True)
    for phase in ('Drying', 'Maillard', 'Development', 'Cool'):
        check('HUNT-65 table shows %s row' % phase,
              phase in tbl, tbl[:200])
    m = re.findall(r'(\d\d)%', tbl)
    shares = [int(x) for x in m[:3]]
    check('HUNT-65 phase shares sum to 100',
          len(shares) == 3 and sum(shares) == 100, shares)
    R5.shot(pg, 'r9-fresh-detail-1042-analysis-1360-light.png')
    b.close()


def main():
    static_auc()
    state = P.tag(B + '/State')
    check('lab starts clean', state == 'Idle', state)
    if state != 'Idle':
        print('LAB BUSY: state=%s, not running live probes'
              % state, flush=True)
        print()
        print('PASSES:', PASSES[0])
        print('FAILURES:', FAILS if FAILS else 'none')
        sys.exit(2)
    BASE['batches'] = P.psql('SELECT COUNT(*) FROM batches')
    BASE['series'] = P.psql('SELECT COUNT(*) FROM batch_series')
    BASE['events'] = P.psql('SELECT COUNT(*) FROM batch_events')
    print('lab baseline:', BASE, flush=True)
    try:
        with sync_playwright() as pw:
            align_label_gap(pw)
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            live_roast_360_dark(pw)
            detail_and_delete(pw)
            compare_three(pw)
            phase_table_1042(pw)
    finally:
        try:
            P.write_tags([(TM, 'System')])
            P.drain_pending()
            P.psql('DELETE FROM batch_events')
            if NEXT_BATCH[0]:
                P.psql('DELETE FROM batches WHERE '
                       'batch_number = %d' % NEXT_BATCH[0])
            # The live roast section saves as the next batch
            # number, and Reset leaves that number in the
            # BatchNumber tag. The round 10 suites that run
            # after this one (calc_gap, auc) check the lab is
            # back at the seeded baseline, BatchNumber 1042,
            # so restore it here; the counts checks below do
            # not cover the tag.
            P.write_tags([(B + '/BatchNumber', 1042)])
        except Exception as e:
            print('emergency cleanup failed:', str(e)[:150],
                  flush=True)
    P.write_tags([(TM, 'System')])
    check('lab back to Idle', P.tag(B + '/State') == 'Idle')
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('lab clean', P.psql('SELECT COUNT(*) FROM batches')
          == BASE['batches'] and P.psql(
              'SELECT COUNT(*) FROM batch_series')
          == BASE['series'] and P.psql(
              'SELECT COUNT(*) FROM batch_events') == '0',
          'batches=%s series=%s (baseline %s)'
          % (P.psql('SELECT COUNT(*) FROM batches'),
             P.psql('SELECT COUNT(*) FROM batch_series'), BASE))
    check('theme restored', P.tag(TM) == 'System')
    check('batch number restored to 1042',
          P.tag(B + '/BatchNumber') == 1042,
          P.tag(B + '/BatchNumber'))
    print()
    print('PASSES:', PASSES[0])
    print('FAILURES:', FAILS if FAILS else 'none')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
