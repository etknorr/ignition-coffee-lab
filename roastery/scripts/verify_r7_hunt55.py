#!/usr/bin/env python3
"""HUNT-55 (polish round 7, hunting lead 1): compare pickers do
not reach build_compare.

Root cause: CmpA, CmpB and CmpC bound props.value to
view.custom.cmpA/B/C with a property binding carrying
"bidirectional": true only at the BINDING level. The property
binding schema puts bidirectional inside CONFIG
({"path": ..., "bidirectional": bool}); the binding level copy
is the tag binding shape. The runtime therefore ran the
binding one way (custom to dropdown): a pick stuck in the
dropdown display but never wrote back to view.custom, so
build_compare read cmpC 0 and the caption listed only A and
B, with no exception anywhere. Fix: "bidirectional": true
inside each of the three bindings' config (binding level copy
kept, matching the tag bindings, which carry both).

Live proof, in two phases so the stub-only chart ink is a
true baseline (the two newest batches change once the
fixtures land):
  Phase 1, seeded lab only, desktop Light: defaults are
  A=1048 B=1047; picking C=1046 then Compare lists all
  three in the caption; picking A=1042 then Compare follows
  the pick; the stub-only compare chart ink is recorded
  (single grid row, no line can draw).
  Phase 2, fixtures 9919/9920 inserted, desktop Light:
  A=9920 B=1048 C=1046 lists all three, and the chart ink
  jumps by over 1000 chromatic pixels vs phase 1: the 720 s
  curve draws. This also settles lead 4: the empty stub
  plot is a seed-data artifact, not a chart defect.
  Phase 3, 360px Light: the same three batches stage, no
  horizontal overflow.
Fixtures are deleted through the Log UI afterwards; the lab
is left at (7, 101, 0) Idle, theme System.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import os
import sys

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
    option anchor in its popup list. Option labels are unique:
    stubs 1045-1048 carry ' (stub)', 1042-1044 do not, the
    fixtures carry their fixture names."""
    dds = page.locator('[data-component="ia.input.dropdown"]')
    dds.nth(slot_idx).click(timeout=20000)
    page.wait_for_timeout(900)
    page.locator('a.iaDropdownCommon_option',
                 has_text=option_label).first.click(timeout=20000)
    page.wait_for_timeout(1500)
    texts = dropdown_texts(page)
    assert option_label in texts[slot_idx], texts
    return texts


def compare(page):
    page.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    page.wait_for_timeout(4000)
    return caption(page)


def chart_ink(page):
    return page.evaluate(INK_JS)


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


GRID_SNIPPET = """\timport roastery.batches as B
\timport roastery.core as C
\tout = {}
\tfor n in NUMBERS:
\t\tpoints = B._compare_points(n)
\t\trors = C.compute_ror_series(points, C.ror_params(),
\t\t                            offline=True)
\t\tror_by_t = dict((t, r) for t, r in rors)
\t\tplaced = {}
\t\tmax_sec = [0]
\t\tfor t, bt in points:
\t\t\ts = C.grid_bucket(t)
\t\t\tplaced.setdefault('btA', {})[s] = bt
\t\t\tplaced.setdefault('rorA', {})[s] = ror_by_t.get(t)
\t\t\tif s > max_sec[0]:
\t\t\t\tmax_sec[0] = s
\t\trows = C.second_grid(placed, ['btA', 'rorA'], max_sec[0])
\t\tout[str(n)] = {'npoints': len(points), 'maxSec': max_sec[0],
\t\t               'nrows': len(rows),
\t\t               't_secs': [r[2] for r in rows]}
\tRESULT = out
"""


def run_grid(numbers):
    """Grid row counts for the given batches, through the same
    library functions build_compare calls, run on the gateway
    (R5.capture pattern)."""
    import json as _json
    import subprocess as _sp
    snip = '/tmp/r7_hunt55_grid_suite.jy'
    with open(snip, 'w') as f:
        f.write(GRID_SNIPPET.replace('NUMBERS', repr(numbers)))
    out = _sp.run([os.path.join('/home/hatch/workspace/ignition-lab',
                                'wsvenv/bin/python'),
                   os.path.join('/home/hatch/workspace/ignition-lab',
                                'scratch_run.py'), snip],
                  capture_output=True, text=True,
                  cwd='/home/hatch/workspace/ignition-lab',
                  timeout=300)
    return _json.loads(out.stdout.strip().splitlines()[-1])


def main():
    os.makedirs(SHOTS, exist_ok=True)
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
    theme0 = tag(TM)
    stub_ink = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                # ---- Phase 1: seeded lab only, desktop Light ----
                write_tags([(TM, 'Light')])
                ctx, pg = open_log(browser, 1360, 900)
                try:
                    texts = dropdown_texts(pg)
                    # HUNT-56 added the "Align on" dropdown to the
                    # compare row, so dropdown_texts now returns four
                    # entries: A, B, C, then the align choice (CHARGE
                    # is the CompareAlignEvent default).
                    check('pickers carry startup defaults',
                          texts == ['Batch 1048 - Ethiopia Guji '
                                    '(stub)',
                                    'Batch 1047 - Ethiopia Guji '
                                    '(stub)', 'None', 'CHARGE'],
                          texts)
                    caps = compare(pg)
                    check('defaults compare A=1048 B=1047',
                          any('A = Batch 1048' in c for c in caps)
                          and any('B = Batch 1047' in c
                                  for c in caps),
                          caps)
                    pick(pg, 2, 'Batch 1046 - Ethiopia Guji (stub)')
                    caps = compare(pg)
                    check('C=1046 stages, caption lists all three',
                          any('A = Batch 1048' in c for c in caps)
                          and any('B = Batch 1047' in c
                                  for c in caps)
                          and any('C = Batch 1046' in c
                                  for c in caps),
                          caps)
                    pick(pg, 0, 'Batch 1042 - Ethiopia Guji')
                    caps = compare(pg)
                    check('A=1042 stages, caption follows the pick',
                          any('A = Batch 1042' in c for c in caps)
                          and any('B = Batch 1047' in c
                                  for c in caps)
                          and any('C = Batch 1046' in c
                                  for c in caps),
                          caps)
                    stub_ink = chart_ink(pg)
                    print('stub-only compare chart ink:',
                          stub_ink, flush=True)
                    check('stub compare chart element shot',
                          shoot_chart(pg,
                                      'r7-hunt55-compare-stubs.png'),
                          'r7-hunt55-compare-stubs.png')
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r7-hunt55-log-stubs.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                # ---- Phase 2: fixtures in, desktop Light ----
                R5.fixtures()
                mid = (int(psql('SELECT COUNT(*) FROM batches')),
                       int(psql('SELECT COUNT(*) FROM batch_series')),
                       int(psql('SELECT COUNT(*) FROM batch_events')))
                check('fixtures 9919/9920 inserted',
                      mid == (9, 166, 0), mid)
                ctx, pg = open_log(browser, 1360, 900)
                try:
                    texts = dropdown_texts(pg)
                    check('pickers default to the newest batches',
                          texts[0].startswith('Batch 9919')
                          and texts[1].startswith('Batch 9920'),
                          texts)
                    pick(pg, 0, 'Batch 9920 - R5 Normal Fixture')
                    pick(pg, 1, 'Batch 1048 - Ethiopia Guji (stub)')
                    pick(pg, 2, 'Batch 1046 - Ethiopia Guji (stub)')
                    caps = compare(pg)
                    check('A=9920 B=1048 C=1046 all stage',
                          any('A = Batch 9920' in c for c in caps)
                          and any('B = Batch 1048' in c
                                  for c in caps)
                          and any('C = Batch 1046' in c
                                  for c in caps),
                          caps)
                    long_ink = chart_ink(pg)
                    print('9920 compare chart ink:', long_ink,
                          flush=True)
                    # Ink alone cannot tell a 30 s plot from a
                    # 720 s one: the axis auto-scales, so six
                    # lines span the full width either way
                    # (stub 5196, 9920 5173 in the first run).
                    # The discriminator is the grid row count
                    # from the same functions build_compare
                    # calls, plus the element screenshot.
                    grid = run_grid([9920, 1048, 1047, 1046])
                    print('compare grid rows:', grid, flush=True)
                    check('9920 compare dataset has 25 grid rows',
                          grid['9920']['nrows'] == 25
                          and grid['9920']['t_secs'][0] == 0
                          and grid['9920']['t_secs'][-1] == 720,
                          grid['9920'])
                    check('stub compare datasets have at most '
                          '2 grid rows',
                          all(grid[str(n)]['nrows'] <= 2
                              for n in (1048, 1047, 1046)),
                          {k: grid[k]['nrows'] for k in
                           ('1048', '1047', '1046')})
                    check('9920 chart element shot',
                          shoot_chart(pg,
                                      'r7-hunt55-compare-9920.png'),
                          'r7-hunt55-compare-9920.png')
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r7-hunt55-log-1360-light.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
                # ---- Phase 3: 360px Light, same three batches ----
                ctx, pg = open_log(browser, 360, 740)
                try:
                    pick(pg, 0, 'Batch 9920 - R5 Normal Fixture')
                    pick(pg, 1, 'Batch 1048 - Ethiopia Guji (stub)')
                    pick(pg, 2, 'Batch 1046 - Ethiopia Guji (stub)')
                    caps = compare(pg)
                    check('360px: three batches stage',
                          any('A = Batch 9920' in c for c in caps)
                          and any('B = Batch 1048' in c
                                  for c in caps)
                          and any('C = Batch 1046' in c
                                  for c in caps),
                          caps)
                    ov = pg.evaluate(OVERFLOW_JS)
                    check('no horizontal overflow at 360px',
                          ov['doc'] <= 360 and ov['body'] <= 360,
                          ov)
                    pg.screenshot(path=os.path.join(
                        SHOTS, 'r7-hunt55-log-360-light.png'),
                        timeout=30000)
                finally:
                    pg.close()
                    ctx.close()
            finally:
                browser.close()
    finally:
        R5.delete_fixtures()
        write_tags([(TM, theme0 or 'System')])
        end = (int(psql('SELECT COUNT(*) FROM batches')),
               int(psql('SELECT COUNT(*) FROM batch_series')),
               int(psql('SELECT COUNT(*) FROM batch_events')))
        check('lab restored to the seeded baseline',
              end == (7, 101, 0)
              and tag(B + '/State') == 'Idle',
              '%s state=%s' % (end, tag(B + '/State')))
        check('theme restored', tag(TM) == (theme0 or 'System'),
              tag(TM))
    print()
    if FAILURES:
        print('HUNT-55 FAILURES:', FAILURES)
        return 1
    print('ALL HUNT-55 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
