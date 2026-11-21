#!/usr/bin/env python3
"""Round 10 item 1 verification (worker A): calculator gaps.

The style class compiler drops gap from style classes, so the
Yield and Conversion Calculator on BatchDetail served 0px
between its fields (round 9 measured the TEMP (F) input ending
at x 1002 and the TEMP (C) readout starting at x 1002) and 0px
between each caption and its control. The fix is scoped, as
round 9 item 8 was: hook classes roast-calc-card, roast-calc-row
and roast-calc-field on the calculator card, its four rows and
its fourteen fields, with the gaps restored in the advanced
stylesheet only (12px between fields, 8px caption to control,
10px between card head, note and rows). No global restore:
the audit probe measured exact-fit rows a global restore would
move, the Fan and Heat stepper rows are exactly 160px wide with
fixed 58/44/58 children that cannot shrink, and the compare
row is exactly full at 1286px; the full audit is in the docs
round 10 section. This suite proves the fix live at desktop
and 360px, light and dark, proves the calculator math still
works through the real inputs, and proves the rows deliberately
left alone did not move (stepper rows, compare row, Tile
value/unit row, all still at their audited geometry).

Theme comes from the device color scheme with ThemeMode System;
the suite never writes the ThemeMode tag through the API. The
one theme write it makes goes through the App Settings UI flow
(gear, Light, then System), and System is restored at the end.
No fixtures, no press path. Leaves the lab clean (7 batches,
101 series, 0 events, ThemeMode System, BatchNumber 1042,
calculator seeded from batch 1042).

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

BASE = P.BASE
SHOTS = P.SHOTS
B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
CALC = '[default]Roastery/Calculator'
FAILS = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:220]) if detail else '', flush=True)
    if not cond:
        FAILS.append(label)


def approx(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


CALC_GEO_JS = """() => {
  const round = (n) => Math.round(n * 10) / 10;
  const textRect = (el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const r = range.getBoundingClientRect();
    return {x: round(r.x), right: round(r.right)};
  };
  const rules = [];
  for (const sh of document.styleSheets) {
    try { for (const r of sh.cssRules) {
      if (r.selectorText && r.selectorText.includes('roast-calc-'))
        rules.push(r.selectorText + ' { ' + r.style.cssText + ' }');
    }} catch (e) {}
  }
  const card = document.querySelector('.psc-roast-calc-card');
  const rows = [...document.querySelectorAll('.psc-roast-calc-row')];
  const fields = [...document.querySelectorAll('.psc-roast-calc-field')];
  const lineGaps = (kids) => {
    // Group children into lines by top (rows) and measure the
    // gap inside each line and between lines, so wrapped rows
    // at 360px report their real 12px row gap, not a negative
    // x reset.
    const lines = [];
    for (const k of kids) {
      const r = k.getBoundingClientRect();
      let line = lines.find(l => Math.abs(l.y - r.y) < 5);
      if (!line) { line = {y: r.y, boxes: []}; lines.push(line); }
      line.boxes.push(r);
    }
    const gaps = [];
    for (const line of lines) {
      const bs = line.boxes.sort((a, b) => a.x - b.x);
      for (let i = 1; i < bs.length; i++)
        gaps.push(round(bs[i].x - bs[i-1].right));
    }
    const sorted = lines.sort((a, b) => a.y - b.y);
    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i-1].boxes;
      const top = sorted[i].boxes[0].y;
      const bottom = Math.max(...prev.map(b => b.bottom));
      gaps.push(round(top - bottom));
    }
    return gaps;
  };
  const rowInfo = rows.map(row => {
    const cs = getComputedStyle(row);
    const kids = [...row.children];
    return {gap: cs.gap, gaps: lineGaps(kids),
            fieldGaps: kids.map(f => getComputedStyle(f).gap)};
  });
  const out = {rules: rules,
    cardGap: card ? getComputedStyle(card).gap : null,
    cardGaps: card ? lineGaps([...card.children]) : [],
    rows: rowInfo,
    nFields: fields.length,
    fieldGaps: fields.map(f => getComputedStyle(f).gap)};
  // Temp (F) input right edge to Temp (C) readout glyph left,
  // desktop: the exact adjacency round 9 measured at x 1002.
  if (rows.length >= 2) {
    const r2 = rows[1];
    const f = [...r2.children];
    const inBox = f[2].querySelector('input');
    const valLab = f[3].querySelectorAll(
      '[data-component="ia.display.label"]')[1];
    const fBox = f[2].getBoundingClientRect();
    const cBox = f[3].getBoundingClientRect();
    out.tempGap = {
      boxGap: round(cBox.x - fBox.right),
      verticalGap: round(cBox.y - fBox.bottom),
      inputToGlyph: inBox && valLab ? round(
        textRect(valLab).x - inBox.getBoundingClientRect().right)
        : null,
      tempCText: valLab ? valLab.textContent.trim() : null};
    // Caption to control gap inside the Temp (F) field.
    const cap = f[2].querySelector(
      '[data-component="ia.display.label"]');
    const capRange = document.createRange();
    capRange.selectNodeContents(cap);
    const capBottom = capRange.getBoundingClientRect().bottom;
    out.tempFieldCaptionGap = inBox ? round(
      inBox.getBoundingClientRect().y - capBottom) : null;
  }
  return out;
}"""

NOMOVE_JS = """() => {
  const round = (n) => Math.round(n * 10) / 10;
  const out = {};
  // Compare row on /log: picker tops equal, align field gap 8px.
  const dds = [...document.querySelectorAll(
    '[data-component="ia.input.dropdown"]')];
  out.compareDropdowns = dds.map(e => {
    const r = e.getBoundingClientRect();
    return {top: round(r.top), left: round(r.left),
            w: round(r.width)}; });
  const align = document.querySelector('.psc-roast-compare-field');
  out.compareFieldGap = align ? getComputedStyle(align).gap : null;
  // Stepper rows on the Roast page: exactly 160px, 58/44/58.
  out.steppers = [];
  document.querySelectorAll('[data-component="ia.container.flex"]')
    .forEach(el => {
      const cs = getComputedStyle(el);
      if (cs.display !== 'flex' ||
          !cs.flexDirection.startsWith('row')) return;
      const kids = [...el.children].filter(k => {
        const r = k.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (kids.length !== 3) return;
      const texts = kids.map(k => (k.textContent || '').trim());
      if (texts[0] !== '-' || texts[2] !== '+') return;
      const cr = el.getBoundingClientRect();
      out.steppers.push({w: round(cr.width),
        kids: kids.map(k => round(k.getBoundingClientRect().width)),
        gaps: [round(kids[1].getBoundingClientRect().x -
                     kids[0].getBoundingClientRect().right),
               round(kids[2].getBoundingClientRect().x -
                     kids[1].getBoundingClientRect().right)]});
    });
  // Tile value/unit rows: deliberately left at 0px box gap;
  // the glyphs clear by their side bearings (probe 2).
  out.tiles = [];
  document.querySelectorAll('[data-component="ia.container.flex"]')
    .forEach(el => {
      const cs = getComputedStyle(el);
      if (cs.display !== 'flex' ||
          !cs.flexDirection.startsWith('row')) return;
      const kids = [...el.children].filter(k => {
        const r = k.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (kids.length !== 2) return;
      const t0 = (kids[0].textContent || '').trim();
      const t1 = (kids[1].textContent || '').trim();
      if (!/^(--|[0-9][0-9.,]*)$/.test(t0)) return;
      if (!/deg F|F\\/min/.test(t1)) return;
      out.tiles.push({value: t0, unit: t1,
        boxGap: round(kids[1].getBoundingClientRect().x -
                      kids[0].getBoundingClientRect().right)});
    });
  return out;
}"""

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
  return {vw: vw, docW: de.scrollWidth, clipped: clipped.slice(0, 10),
          nClipped: clipped.length};
}"""


def fill_input(page, idx, value):
    # Scoped to the calculator card: the detail page carries
    # other numeric inputs (the slide-over editor dock), and
    # DOM order across the whole page is not the calculator's.
    inp = page.locator(
        '.psc-roast-calc-card '
        '[data-component="ia.input.numeric-entry-field"] input'
        ).nth(idx)
    inp.scroll_into_view_if_needed()
    inp.click()
    page.wait_for_timeout(300)
    inp.press('Control+a')
    inp.type(str(value))
    inp.press('Enter')
    page.wait_for_timeout(1200)


def stage_hold(pw, width, height, scheme):
    """Stage 1042 and open /log/detail, retrying while another
    worker stages a different batch in the same lab."""
    for attempt in range(5):
        R5.stage_one(1042)
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': width, 'height': height},
                            timezone_id='America/Denver',
                            color_scheme=scheme)
        pg = ctx.new_page()
        pg.goto(BASE + '/log/detail', wait_until='domcontentloaded',
                timeout=60000)
        pg.wait_for_timeout(6000)
        R5.dismiss(pg)
        pg.wait_for_timeout(4000)
        ok = ('Batch 1042' in pg.locator('body').inner_text()
              and P.tag('[default]Roastery/SelectedBatchNumber')
              == 1042)
        if ok:
            return pg, b
        print('stage retry %d: staged batch changed' % (attempt + 1),
              flush=True)
        b.close()
    raise AssertionError('could not hold staging for 1042')


def detail_geometry(pw, width, height, scheme, tag):
    pg, b = stage_hold(pw, width, height, scheme)
    if True:
        cv = P.container_var(pg)
        want_cv = '#F4F4F4' if scheme == 'light' else '#323232'
        check('%s: session renders %s' % (tag, want_cv),
              cv == want_cv, cv)
        check('%s: ThemeMode tag still System' % tag,
              P.tag(TM) == 'System', P.tag(TM))
        g = pg.evaluate(CALC_GEO_JS)
        check('%s: calc stylesheet rules serve 10/12/8px' % tag,
              any('roast-calc-card' in r and 'gap: 10px' in r
                  for r in g['rules'])
              and any('roast-calc-row' in r and 'gap: 12px' in r
                      for r in g['rules'])
              and any('roast-calc-field' in r and 'gap: 8px' in r
                      for r in g['rules']),
              g['rules'])
        check('%s: calc card computed gap is 10px' % tag,
              g['cardGap'] == '10px', g['cardGap'])
        check('%s: calc card child gaps are all 10px' % tag,
              len(g['cardGaps']) == 5
              and all(x == 10 for x in g['cardGaps']), g['cardGaps'])
        check('%s: four calc rows present' % tag,
              len(g['rows']) == 4, len(g['rows']))
        check('%s: every calc row computes gap 12px' % tag,
              all(r['gap'] == '12px' for r in g['rows']),
              [r['gap'] for r in g['rows']])
        check('%s: every calc row gap is 12px, wrapped or not'
              % tag,
              all(all(x == 12 for x in r['gaps']) for r in g['rows']),
              [r['gaps'] for r in g['rows']])
        check('%s: fourteen calc fields present' % tag,
              g['nFields'] == 14, g['nFields'])
        check('%s: every calc field computes gap 8px' % tag,
              len(g['fieldGaps']) == 14
              and all(x == '8px' for x in g['fieldGaps']),
              g['fieldGaps'])
        tg = g.get('tempGap') or {}
        if width >= 900:
            check('%s: TEMP (F) input clears TEMP (C) readout '
                  'by 12px' % tag,
                  tg.get('inputToGlyph') == 12,
                  tg.get('inputToGlyph'))
        else:
            check('%s: wrapped TEMP (F) field clears TEMP (C) '
                  'field by 12px' % tag,
                  tg.get('verticalGap') == 12, tg.get('verticalGap'))
        check('%s: TEMP (F) caption clears its input by 8px' % tag,
              g.get('tempFieldCaptionGap') == 8,
              g.get('tempFieldCaptionGap'))
        ov = pg.evaluate(OVERFLOW_JS)
        check('%s: no horizontal overflow' % tag,
              ov['docW'] <= ov['vw'], ov)
        check('%s: no clipped leaf text' % tag,
              ov['nClipped'] == 0, ov['clipped'])
        pg.evaluate("""() => {
          const el = [...document.querySelectorAll(
            '[data-component="ia.display.label"]')].find(
            e => e.textContent.trim() ===
            'Yield and Conversion Calculator');
          if (el) el.scrollIntoView({block: 'center'});
        }""")
        pg.wait_for_timeout(800)
        pg.screenshot(path=os.path.join(
            SHOTS, 'r10-calc-gap-%s.png' % tag))
        return pg, b


def theme_ui_flow(pw):
    """The one theme write, through the App Settings UI flow:
    gear, Light, then back to System."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver',
                        color_scheme='light')
    pg = ctx.new_page()
    pg.goto(BASE + '/', wait_until='domcontentloaded', timeout=60000)
    pg.wait_for_timeout(6000)
    R5.dismiss(pg)
    pg.wait_for_timeout(3000)
    pg.locator('.psc-roast-gear-btn:visible').first.click()
    pg.wait_for_timeout(2500)
    check('gear opens the App Settings popup',
          'App Settings' in pg.locator('body').inner_text())
    pg.get_by_role('button', name='Light', exact=True).click()
    pg.wait_for_timeout(3000)
    check('App Settings Light pins light and writes the tag',
          P.container_var(pg) == '#F4F4F4'
          and P.tag(TM) == 'Light', P.tag(TM))
    pg.get_by_role('button', name='System', exact=True).click()
    pg.wait_for_timeout(3000)
    check('App Settings System restores the tag and follows '
          'the device',
          P.tag(TM) == 'System'
          and P.container_var(pg) == '#F4F4F4', P.tag(TM))
    pg.get_by_role('button', name='Close', exact=True).click()
    pg.wait_for_timeout(800)
    b.close()


def nomove_checks(pw):
    """Rows deliberately left alone still measure as audited."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver',
                        color_scheme='light')
    pg = ctx.new_page()
    pg.goto(BASE + '/log', wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    R5.dismiss(pg)
    pg.wait_for_timeout(4000)
    g = pg.evaluate(NOMOVE_JS)
    dds = g.get('compareDropdowns') or []
    tops = [d['top'] for d in dds]
    check('compare: all four picker tops equal (round 9 fix '
          'holds)', len(dds) >= 4 and max(tops) - min(tops) <= 1,
          tops)
    check('compare: align field still computes gap 8px',
          g.get('compareFieldGap') == '8px',
          g.get('compareFieldGap'))
    check('compare: picker to picker box gaps still 0px '
          '(deliberately left alone)',
          len(dds) >= 4 and all(
              dds[i + 1]['left'] - (dds[i]['left'] + dds[i]['w']) == 0
              for i in range(3)),
          dds)
    pg.goto(BASE + '/', wait_until='domcontentloaded', timeout=60000)
    pg.wait_for_timeout(6000)
    R5.dismiss(pg)
    pg.wait_for_timeout(4000)
    g = pg.evaluate(NOMOVE_JS)
    st = g.get('steppers') or []
    check('steppers: rows still exactly 160px, 58/44/58, 0px gaps',
          len(st) >= 2 and all(
              s['w'] == 160 and s['kids'] == [58, 44, 58]
              and s['gaps'] == [0, 0] for s in st),
          st[:2])
    tiles = g.get('tiles') or []
    check('tiles: value/unit box gaps still 0px (deliberately '
          'left alone; glyphs clear)',
          len(tiles) >= 2 and all(t['boxGap'] == 0 for t in tiles),
          tiles[:4])
    ov = pg.evaluate(OVERFLOW_JS)
    check('roast: no horizontal overflow', ov['docW'] <= ov['vw'],
          ov)
    check('roast: no clipped leaf text', ov['nClipped'] == 0,
          ov['clipped'])
    b.close()


def math_check(pw):
    """The calculator still computes through the real inputs."""
    pg, b = stage_hold(pw, 1360, 900, 'light')
    try:
        seeded = P.wait_until(
            lambda: approx(P.tag(CALC + '/ChargeG'), 200.0, 0.01)
            and approx(P.tag(CALC + '/OutG'), 172.0, 0.01),
            timeout=20)
        check('calculator seeded from batch 1042 (200 g in, '
              '172 g out)', bool(seeded),
              (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/OutG')))
        check('seeded reverse loss reads 14.0 pct',
              approx(P.tag(CALC + '/ActualLossPct'), 14.0, 0.05),
              P.tag(CALC + '/ActualLossPct'))
        n_inputs = pg.locator(
            '.psc-roast-calc-card '
            '[data-component="ia.input.numeric-entry-field"] '
            'input').count()
        check('calculator has seven numeric inputs',
              n_inputs == 7, n_inputs)
        # DOM order: Charge, Loss, Out, TempF, TempCIn, ConvG,
        # ConvOzIn. TempF is index 3.
        fill_input(pg, 3, 212)
        check('conversion: 212 F is 100.0 C in the tag',
              approx(P.tag(CALC + '/TempC'), 100.0, 0.05),
              P.tag(CALC + '/TempC'))
        g = pg.evaluate(CALC_GEO_JS)
        check('conversion: TEMP (C) readout renders 100.0',
              (g.get('tempGap') or {}).get('tempCText') == '100.0',
              (g.get('tempGap') or {}).get('tempCText'))
        fill_input(pg, 3, 415)
        check('TempF restored to 415.0 through the input',
              approx(P.tag(CALC + '/TempF'), 415.0, 0.05)
              and approx(P.tag(CALC + '/TempC'), 212.7778, 0.01),
              (P.tag(CALC + '/TempF'), P.tag(CALC + '/TempC')))
    finally:
        b.close()


def main():
    print('lab starts:', P.tag(B + '/State'),
          P.psql('SELECT COUNT(*) FROM batches'),
          P.psql('SELECT COUNT(*) FROM batch_series'),
          P.psql('SELECT COUNT(*) FROM batch_events'),
          'ThemeMode:', P.tag(TM), flush=True)
    try:
        with sync_playwright() as pw:
            theme_ui_flow(pw)
            pg, b = detail_geometry(pw, 1360, 900, 'light',
                                    'desktop-light')
            try:
                pass
            finally:
                b.close()
            pg, b = detail_geometry(pw, 1360, 900, 'dark',
                                    'desktop-dark')
            try:
                pass
            finally:
                b.close()
            pg, b = detail_geometry(pw, 360, 740, 'light',
                                    '360-light')
            try:
                pass
            finally:
                b.close()
            pg, b = detail_geometry(pw, 360, 740, 'dark',
                                    '360-dark')
            try:
                pass
            finally:
                b.close()
            nomove_checks(pw)
            math_check(pw)
    finally:
        R5.stage_one(1042)
        time.sleep(1)
        end_counts = (int(P.psql('SELECT COUNT(*) FROM batches')),
                      int(P.psql(
                          'SELECT COUNT(*) FROM batch_series')),
                      int(P.psql(
                          'SELECT COUNT(*) FROM batch_events')))
        check('lab restored to the seeded baseline',
              end_counts == (7, 101, 0), end_counts)
        check('ThemeMode restored to System',
              P.tag(TM) == 'System', P.tag(TM))
        check('BatchNumber restored to 1042',
              P.tag(B + '/BatchNumber') == 1042,
              P.tag(B + '/BatchNumber'))
        check('calculator tags back at the seeded values',
              approx(P.tag(CALC + '/ChargeG'), 200.0, 0.01)
              and approx(P.tag(CALC + '/OutG'), 172.0, 0.01)
              and approx(P.tag(CALC + '/TempF'), 415.0, 0.05),
              (P.tag(CALC + '/ChargeG'), P.tag(CALC + '/OutG'),
               P.tag(CALC + '/TempF')))
    print()
    if FAILS:
        print('R10 CALC GAP FAILURES:', len(FAILS))
        for f in FAILS:
            print(' -', f)
        sys.exit(1)
    print('ALL R10 CALC GAP CHECKS PASSED')


if __name__ == '__main__':
    main()
