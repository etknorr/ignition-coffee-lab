#!/usr/bin/env python3
"""Round 9 items 5 and 8 verification (worker A).

Item 5: a fresh browser session must NOT rewrite the
ThemeMode tag. With the tag at System, a fresh light-scheme
session and a fresh dark-scheme session both leave it at
System, while the rendered theme still follows the device
(container var #F4F4F4 light, #323232 dark). The only app
write path is roastery.core.set_theme_mode, called only by
the three App Settings buttons; the round 8 observation was
concurrent suites writing the tag through the REST API, not
a startup sync (see the docs round 9 section).

Item 8: the ALIGN ON label on the Log compare row. The row
bottom aligns its children and the Align field carries a
real 8px caption to control gap from the advanced
stylesheet (the style class compiler drops gap from style
classes, proven live: every gap rule serves empty while the
sibling properties serve). Checks: label bottom to C picker
top at least 4px, label to its own dropdown at least 4px,
all four picker tops equal, no horizontal overflow and no
clipped leaf text at desktop and 360px, and Compare still
stages the overlay.

Run with wsvenv python from ~/workspace/ignition-lab.
Leaves the lab clean (7 batches, 101 series, 0 events,
ThemeMode System, BatchNumber 1042). Does not touch the
press path.
"""
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
from playwright.sync_api import sync_playwright

BASE = P.BASE
SHOTS = P.SHOTS
B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
FAILS = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:220]) if detail else '', flush=True)
    if not cond:
        FAILS.append(label)


def dismiss(page):
    for _ in range(30):
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


GEO_JS = """() => {
  const out = {};
  const lab = [...document.querySelectorAll(
    '[data-component="ia.display.label"]')].find(
    e => e.textContent.trim() === 'Align on');
  const rect = (e) => { const r = e.getBoundingClientRect();
    return {top: r.top, bottom: r.bottom, h: r.height}; };
  if (lab) {
    out.label = rect(lab);
    out.labelText = lab.innerText.trim();
    const field = lab.closest(
      '[data-component="ia.container.flex"]');
    out.fieldGap = getComputedStyle(field).gap;
    out.fieldCls = field.className;
  }
  const dds = [...document.querySelectorAll(
    '[data-component="ia.input.dropdown"]')];
  out.dropdowns = dds.map(e => ({t: e.innerText.replace(
    /\\n/g, ' | ').slice(0, 30), ...rect(e)}));
  const rules = [];
  for (const sh of document.styleSheets) {
    try { for (const r of sh.cssRules) {
      if (r.selectorText && r.selectorText.includes(
        'roast-compare-field')) rules.push(
        r.selectorText + ' { ' + r.style.cssText + ' }');
    }} catch (e) {}
  }
  out.compareFieldRules = rules;
  out.docW = document.documentElement.scrollWidth;
  out.innerW = window.innerWidth;
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


def theme_probe(pw, scheme):
    """Item 5: fresh session, tag must stay System."""
    P.write_tags([(TM, 'System')])
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver',
                        color_scheme=scheme)
    pg = ctx.new_page()
    pg.goto(BASE + '/', wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    dismiss(pg)
    pg.wait_for_timeout(20000)
    val = P.tag(TM)
    cv = P.container_var(pg)
    want_cv = '#F4F4F4' if scheme == 'light' else '#323232'
    check('fresh %s session leaves ThemeMode System' % scheme,
          val == 'System', val)
    check('fresh %s session renders %s' % (scheme, want_cv),
          cv == want_cv, cv)
    pg.screenshot(path=os.path.join(
        SHOTS, 'r9-item5-clean-%s.png' % scheme))
    b.close()


def log_geometry(pw, width, height, scheme, tag, wrapped=False):
    """Item 8 geometry on /log at one viewport and scheme.
    When the row wraps (360px) the pickers stack, so the
    C-picker clearance and equal-tops checks do not apply;
    what matters there is the label above its own dropdown.
    """
    P.write_tags([(TM, scheme)])
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={'width': width, 'height': height},
                        timezone_id='America/Denver',
                        color_scheme=scheme.lower())
    pg = ctx.new_page()
    pg.goto(BASE + '/log', wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    dismiss(pg)
    pg.wait_for_timeout(4000)
    g = pg.evaluate(GEO_JS)
    lab = g.get('label') or {}
    dds = g.get('dropdowns') or []
    tops = [d['top'] for d in dds]
    check('%s: compare field rule serves gap 8px' % tag,
          any('gap: 8px' in r for r in g.get('compareFieldRules',
                                            [])),
          g.get('compareFieldRules'))
    check('%s: compare field computed gap is 8px' % tag,
          g.get('fieldGap') == '8px', g.get('fieldGap'))
    check('%s: ALIGN ON label renders uppercase' % tag,
          g.get('labelText') == 'ALIGN ON', g.get('labelText'))
    if len(dds) >= 4:
        gap_c = dds[2]['top'] - lab.get('bottom', 0)
        gap_own = dds[3]['top'] - lab.get('bottom', 0)
        if not wrapped:
            check('%s: ALIGN ON clears the C picker top by >= 4px'
                  % tag, gap_c >= 4, gap_c)
            check('%s: all four picker tops equal' % tag,
                  max(tops) - min(tops) <= 1, tops)
        else:
            check('%s: wrapped row stacks the pickers' % tag,
                  tops == sorted(tops) and len(set(tops)) == 4,
                  tops)
        check('%s: ALIGN ON clears its own dropdown by >= 4px'
              % tag, gap_own >= 4, gap_own)
    else:
        check('%s: four compare dropdowns present' % tag, False,
              dds)
    ov = pg.evaluate(OVERFLOW_JS)
    check('%s: no horizontal overflow' % tag,
          ov['docW'] <= ov['vw'], ov)
    check('%s: no clipped leaf text' % tag,
          ov['nClipped'] == 0, ov['clipped'])
    pg.screenshot(path=os.path.join(SHOTS, 'r9-item8-fixed-%s.png'
                                   % tag))
    return pg, b, ctx


def compare_still_works(pg):
    """The pickers still bind and Compare still stages."""
    dds = pg.locator('[data-component="ia.input.dropdown"]')
    texts = [dds.nth(i).inner_text().replace('\n', ' | ')
             for i in range(dds.count())]
    check('compare pickers read 1048 / 1047 / None / CHARGE',
          len(texts) == 4 and '1048' in texts[0]
          and '1047' in texts[1] and texts[2].strip() == 'None'
          and texts[3].strip() == 'CHARGE', texts)
    pg.get_by_role('button', name='Compare', exact=True).click()
    pg.wait_for_timeout(4000)
    caps = pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")
    check('Compare stages A/B with CHARGE alignment',
          any('A = Batch 1048' in c for c in caps)
          and any('Aligned on CHARGE' in c for c in caps), caps)


def main():
    print('lab starts:', P.tag(B + '/State'),
          P.psql('SELECT COUNT(*) FROM batches'),
          P.psql('SELECT COUNT(*) FROM batch_series'),
          P.psql('SELECT COUNT(*) FROM batch_events'),
          'ThemeMode:', P.tag(TM), flush=True)
    try:
        with sync_playwright() as pw:
            theme_probe(pw, 'light')
            theme_probe(pw, 'dark')
            pg, b, ctx = log_geometry(pw, 1360, 900, 'Light',
                                      'desktop-light')
            try:
                compare_still_works(pg)
            finally:
                b.close()
            pg, b, ctx = log_geometry(pw, 360, 740, 'Light',
                                      '360-light', wrapped=True)
            try:
                pass
            finally:
                b.close()
            pg, b, ctx = log_geometry(pw, 1360, 900, 'Dark',
                                      'desktop-dark')
            try:
                pass
            finally:
                b.close()
    finally:
        P.write_tags([(TM, 'System'),
                      (B + '/BatchNumber', 1042)])
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
    print()
    if FAILS:
        print('R9 THEME ALIGN FAILURES:', len(FAILS))
        for f in FAILS:
            print(' -', f)
        sys.exit(1)
    print('ALL R9 THEME ALIGN CHECKS PASSED')


if __name__ == '__main__':
    main()
