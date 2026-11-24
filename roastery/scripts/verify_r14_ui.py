#!/usr/bin/env python3
"""Round 14 UI/UX hunting verification (worker B, HUNT-102 to
HUNT-106).

Fresh hunting pass across the whole app: every page at 360 px and
1360 px, light and dark, live in a real session, plus per-fix
checks, the App Settings slide-over, toast and cross-session
theme checks, and a full live roast at 360 px dark.

HUNT-102: Target Plan Designer table last row clipped by the
  pagination footer. Fix: TargetPlanTable basis 190 px to 210 px
  in SettingsTargets/view.json.
HUNT-103: analyzer "Ghost BT (F)" caption wrapped to two lines
  at 360 px on Roast and BatchDetail. Fix: caption shortened to
  "Ghost (F)" in RoastPage/view.json (two instances) and
  BatchDetail/view.json (one instance). The detail chart event
  marker labels were also checked live: a properly staged batch
  shows only the visible labels (detail_reference_lines_compact
  thins them), so no chart fix was needed; the earlier overlap
  sighting was a concurrent worker re-staging mid-probe.
HUNT-104: form action buttons squeezed to 65 px, the submit
  label wrapping to three lines. Fix: per-button style
  {"flexBasis": "auto"} on the submit action of the metadata
  form (SettingsMetadata/view.json) and on submit and cancel
  of the batch editor form (BatchEdit/view.json).
HUNT-105: "Show on controls" caption wrapped to two lines in
  the Custom Events rows. Fix: all four CustomShowField
  position basis 110 px to 140 px in SettingsCustoms/view.json.
HUNT-106: phone HUD captions "BEAN F" and "ROAST TIME" wrapped
  at 360 px. Fix: HudBar/view.json Bean basis 38 px to 48 px,
  HudState basis 88 px to 72 px, stylesheet .psc-roast-hud gap
  3 px to 2 px, and the phone clock caption shortened to "TIME"
  (and "DROP" after Drop) in the HudBar only; the desktop
  header keeps "ROAST TIME" and "SINCE DROP".

Run with wsvenv python from ~/workspace/ignition-lab. Claims
~/workspace/ignition-lab/.lab-lock, restores defaults, and
leaves the lab at 7 batches, 101 series rows, 0 events.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
VIEWS = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
         'project/Roastery/com.inductiveautomation.perspective/'
         'views/Views/')
STYLE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
         'project/Roastery/com.inductiveautomation.perspective/'
         'stylesheet/stylesheet.css')
LAB = '/home/hatch/workspace/ignition-lab'
LOCK = LAB + '/.lab-lock'
NEXT_BATCH = [0]
FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '',
          flush=True)
    if not cond:
        FAILS.append(name)


OVERFLOW_JS = """
() => {
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

INNER_HSCROLL_JS = """
() => {
  const bad = [];
  document.querySelectorAll('*').forEach(el => {
    if (el === document.documentElement ||
        el === document.body) return;
    if (el.offsetParent === null) return;
    const cs = getComputedStyle(el);
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') &&
        el.scrollWidth > el.clientWidth + 1) {
      const cls = (typeof el.className === 'string')
        ? el.className.slice(0, 50) : el.tagName;
      bad.push(cls + ' ' + el.scrollWidth + '>' +
        el.clientWidth);
    }
  });
  return bad.slice(0, 10);
}"""


def measure(pg, label):
    m = pg.evaluate(OVERFLOW_JS)
    check(label + ' no horizontal overflow',
          m['docW'] <= m['vw'], m)
    check(label + ' no clipped leaf text',
          m['nClipped'] == 0, m['clipped'])
    inner = pg.evaluate(INNER_HSCROLL_JS)
    check(label + ' no inner horizontal scroller',
          len(inner) == 0, inner)
    return m


def scroll_to(pg, frac):
    pg.evaluate("""(f) => {
      const cands = [...document.querySelectorAll('*')]
        .filter(e => e.scrollHeight > e.clientHeight + 100)
        .sort((a, b) => b.scrollHeight - a.scrollHeight);
      if (cands.length) cands[0].scrollTop =
        cands[0].scrollHeight * f;
    }""", frac)
    pg.wait_for_timeout(900)


def scroll_into_view(pg, text):
    pg.evaluate("""(t) => {
      const leaf = [...document.querySelectorAll('*')]
        .find(e => e.children.length === 0 &&
          (e.textContent || '').trim().includes(t));
      if (leaf) leaf.scrollIntoView({block: 'start'});
    }""", text)
    pg.wait_for_timeout(900)


BANNER_JS = """
() => {
  const leaves = [...document.querySelectorAll('*')]
    .filter(e => e.children.length === 0 &&
      (e.textContent || '').includes('No Connection'));
  if (!leaves.length) return {found: false};
  const e = leaves[0];
  const r = e.getBoundingClientRect();
  const banner = e.closest('.connection-banner');
  return {found: true,
    text: (e.textContent || '').trim().slice(0, 40),
    rect: {x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height)},
    inViewport: r.bottom > 0 && r.top < window.innerHeight,
    bannerClass: banner ? banner.className : ''};
}"""


def no_connection_check(pg, label):
    info = pg.evaluate(BANNER_JS)
    check(label + ' no visible reconnect banner',
          (not info.get('found'))
          or (not info.get('inViewport')), info)


def click_btn(pg, name, timeout=20000):
    pg.locator('button').filter(has_text=name).first.click(
        timeout=timeout)


def set_theme_ui(pg, theme):
    """Set ThemeMode through the App Settings UI flow only:
    gear, theme button, Close. Never a direct tag write."""
    try:
        pg.locator('.psc-roast-gear-btn:visible').first.click(
            timeout=20000)
    except Exception:
        print('set_theme_ui: gear click timed out, reloading '
              'the page once for a fresh session', flush=True)
        pg.reload()
        pg.wait_for_timeout(4000)
        pg.locator('.psc-roast-gear-btn:visible').first.click(
            timeout=20000)
    pg.wait_for_timeout(900)
    pg.get_by_role('button', name=theme, exact=True).first.click(
        timeout=20000)
    ok = P.wait_until(lambda: P.tag(TM) == theme, 30)
    check('theme %s set through App Settings UI' % theme,
          bool(ok), P.tag(TM))
    pg.get_by_role('button', name='Close', exact=True).first.click(
        timeout=20000)
    pg.wait_for_timeout(500)


def find_view(name):
    return json.load(open(VIEWS + name + '/view.json'))


def find_comp(view, name):
    def rec(c):
        if c.get('meta', {}).get('name') == name:
            return c
        for ch in c.get('children', []):
            hit = rec(ch)
            if hit is not None:
                return hit
        return None
    return rec(view['root'])


def leaf_rects(pg, text):
    """Bounding rects of visible leaf elements whose trimmed
    text matches the given text case-insensitively (captions
    render uppercase through their style class)."""
    return pg.evaluate("""(t) => {
      const want = t.toUpperCase();
      return [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          (e.textContent || '').trim().toUpperCase() === want)
        .map(e => { const r = e.getBoundingClientRect();
          return {w: Math.round(r.width),
                  h: Math.round(r.height),
                  x: Math.round(r.x), y: Math.round(r.y)}; })
        .filter(r => r.w > 0 && r.h > 0);
    }""", text)


def static_hunt_102():
    view = find_view('SettingsTargets')
    tbl = find_comp(view, 'TargetPlanTable')
    check('HUNT-102 TargetPlanTable exists', tbl is not None)
    if tbl is not None:
        pos = tbl.get('position') or {}
        check('HUNT-102 TargetPlanTable basis 210px',
              pos.get('basis') == '210px', pos)


def static_hunt_103():
    for name in ('RoastPage', 'BatchDetail'):
        raw = open(VIEWS + name + '/view.json').read()
        check('HUNT-103 %s has no Ghost BT caption' % name,
              'Ghost BT (F)' not in raw)
        check('HUNT-103 %s has Ghost (F) caption' % name,
              'Ghost (F)' in raw)
    roast = open(VIEWS + 'RoastPage/view.json').read()
    check('HUNT-103 RoastPage has two Ghost (F) captions',
          roast.count('Ghost (F)') == 2, roast.count('Ghost (F)'))


def static_hunt_104():
    meta = find_view('SettingsMetadata')
    form = find_comp(meta, 'MetaForm')
    check('HUNT-104 MetaForm exists', form is not None)
    if form is not None:
        actions = form.get('props', {}).get('actions') or {}
        submit = (actions.get('submit') or {})
        check('HUNT-104 MetaForm submit flexBasis auto',
              (submit.get('style') or {}).get('flexBasis')
              == 'auto', submit.get('style'))
    edit = find_view('BatchEdit')
    form2 = None
    def rec(c):
        nonlocal form2
        if c.get('type') == 'ia.input.form':
            form2 = c
        for ch in c.get('children', []):
            rec(ch)
    rec(edit['root'])
    check('HUNT-104 BatchEdit form exists', form2 is not None)
    if form2 is not None:
        actions = form2.get('props', {}).get('actions') or {}
        for key in ('submit', 'cancel'):
            act = actions.get(key) or {}
            check('HUNT-104 BatchEdit %s flexBasis auto' % key,
                  (act.get('style') or {}).get('flexBasis')
                  == 'auto', act.get('style'))


def static_hunt_105():
    view = find_view('SettingsCustoms')
    found = []
    def rec(c):
        if re.match(r'^CustomShowField\d$',
                    c.get('meta', {}).get('name') or ''):
            found.append(c)
        for ch in c.get('children', []):
            rec(ch)
    rec(view['root'])
    check('HUNT-105 four CustomShowField found',
          len(found) == 4, len(found))
    check('HUNT-105 all CustomShowField basis 140px',
          all((f.get('position') or {}).get('basis') == '140px'
              for f in found),
          [(f.get('position') or {}).get('basis') for f in found])


def static_hunt_106():
    view = find_view('HudBar')
    for name, want in (('HudState', '80px'), ('Bean', '48px'),
                       ('Clock', '52px')):
        comp = find_comp(view, name)
        check('HUNT-106 HudBar %s exists' % name,
              comp is not None)
        if comp is not None:
            pos = comp.get('position') or {}
            check('HUNT-106 HudBar %s basis %s' % (name, want),
                  pos.get('basis') == want, pos)
    css = open(STYLE).read()
    check('HUNT-106 stylesheet HUD gap 2px',
          '.psc-roast-hud { gap: 2px' in css)
    pill = json.load(open(
        '/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/com.inductiveautomation.perspective/'
        'style-classes/roast-pill/style.json'))
    check('HUNT-106 roast-pill padding 4px 8px',
          pill['base']['style'].get('padding') == '4px 8px',
          pill['base']['style'])
    check('HUNT-106 HudBar clockCaption default TIME',
          view.get('custom', {}).get('clockCaption') == 'TIME',
          view.get('custom', {}).get('clockCaption'))
    expr = (view.get('propConfig', {})
            .get('custom.clockCaption', {})
            .get('binding', {}).get('config', {})
            .get('expression', ''))
    check('HUNT-106 HudBar caption expression uses DROP/TIME',
          "'DROP'" in expr and "'TIME'" in expr
          and 'ROAST TIME' not in expr
          and 'SINCE DROP' not in expr, expr[:120])
    roast = find_view('RoastPage')
    rexpr = (roast.get('propConfig', {})
             .get('custom.clockCaption', {})
             .get('binding', {}).get('config', {})
             .get('expression', ''))
    check('HUNT-106 desktop header keeps SINCE DROP',
          'SINCE DROP' in rexpr and 'ROAST TIME' in rexpr,
          rexpr[:120])


def static_hunt_103_labels():
    """The detail chart labels for a properly staged batch are
    thinned by detail_reference_lines_compact: for batch 1042
    only CHARGE is visible. Run the real library code on the
    gateway through the scratch runner."""
    jy = LAB + '/r14_ui_compact.jy'
    # The scratch runner embeds the snippet tab-indented
    # under its own block, so every line carries a leading
    # tab (the proven r14_refprobe format).
    open(jy, 'w').write(
        "\timport roastery.batches as B\n"
        "\timport roastery.core as C\n"
        "\tB.stage_detail(1042)\n"
        "\tcomp = B.detail_reference_lines_compact()\n"
        "\tdef summ(items):\n"
        "\t\treturn [(i['value'], i['label']['text'], "
        "i['label']['visible']) for i in items]\n"
        "\tRESULT = {'compact': summ(comp)}\n")
    data = None
    for attempt in range(2):
        out = subprocess.run(
            [LAB + '/wsvenv/bin/python', LAB + '/scratch_run.py', jy],
            capture_output=True, text=True, timeout=120)
        try:
            data = json.loads(out.stdout.strip())
            break
        except ValueError:
            print('compact probe attempt %d gave no JSON: %s'
                  % (attempt, out.stdout.strip()[:200]),
                  flush=True)
    print('compact labels 1042:', data, flush=True)
    comp = (data or {}).get('compact') or []
    visible = [i for i in comp if len(i) > 2 and i[2]]
    check('HUNT-103 compact labels for 1042 show CHARGE only',
          len(visible) == 1 and visible[0][1] == 'CHARGE',
          comp)


def static_checks():
    static_hunt_102()
    static_hunt_103()
    static_hunt_104()
    static_hunt_105()
    static_hunt_106()
    static_hunt_103_labels()


def walk(pw, width, height, theme, tag):
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width,
                                  'height': height},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, theme)
    pg.wait_for_timeout(1200)
    no_connection_check(pg, 'roast %s' % tag)
    measure(pg, 'roast %s' % tag)
    R5.shot(pg, 'r14-ui-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    no_connection_check(pg2, 'log %s' % tag)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r14-ui-log-%s.png' % tag)
    scroll_into_view(pg2, 'Pick up to three batches')
    measure(pg2, 'log compare row %s' % tag)
    R5.shot(pg2, 'r14-ui-log-compare-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    no_connection_check(pg3, 'detail %s' % tag)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r14-ui-detail-%s.png' % tag)
    scroll_into_view(pg3, 'Yield and Conversion Calculator')
    measure(pg3, 'detail calculator %s' % tag)
    R5.shot(pg3, 'r14-ui-detail-calc-%s.png' % tag)
    scroll_to(pg3, 1.0)
    measure(pg3, 'detail bottom %s' % tag)
    R5.shot(pg3, 'r14-ui-detail-bottom-%s.png' % tag)
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    no_connection_check(pg4, 'settings %s' % tag)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r14-ui-settings-%s.png' % tag)
    scroll_into_view(pg4, 'Alarm definitions')
    measure(pg4, 'settings alarms %s' % tag)
    R5.shot(pg4, 'r14-ui-settings-alarms-%s.png' % tag)
    b.close()


def hunt_102_live(pw):
    """Target Plan table holds all four rows at 1360 px and
    360 px: the table box is 210 px tall and its content does
    not spill past it. At desktop width the old symptom is
    also checked directly: the last row ends above the
    pagination footer."""
    for width, height, tag in ((1360, 900, '1360'),
                               (360, 800, '360')):
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': width,
                                      'height': height},
                            timezone_id='America/Denver')
        pg = R5.open_page(ctx, '/settings')
        pg.wait_for_timeout(2000)
        scroll_into_view(pg, 'Target Plan Designer')
        geo = pg.evaluate("""() => {
          const tbl = [...document.querySelectorAll(
            '[data-component="ia.display.table"]')]
            .find(e => (e.innerText || '').includes('630'));
          if (!tbl) return {found: false};
          const r = tbl.getBoundingClientRect();
          const foot = [...document.querySelectorAll('*')]
            .find(e => e.children.length === 0 &&
              (e.textContent || '').trim() === '25 rows');
          const fr = foot ? foot.getBoundingClientRect() : null;
          const rows = [...tbl.querySelectorAll('*')]
            .filter(e => e.children.length === 0 &&
              /^\\d+ \\/ \\d+ /.test((e.textContent || '').trim()));
          const rs = rows.map(e => {
            const rr = e.getBoundingClientRect();
            return {t: e.textContent.trim(),
                    bottom: Math.round(rr.bottom)}; });
          return {found: true, h: Math.round(r.height),
                  scrollH: tbl.scrollHeight,
                  clientH: tbl.clientHeight,
                  footerTop: fr ? Math.round(fr.top) : null,
                  rows: rs};
        }""")
        print('HUNT-102 %s table geometry:' % tag, geo, flush=True)
        check('HUNT-102 %s table found' % tag,
              geo.get('found') is True, geo)
        if geo.get('found'):
            check('HUNT-102 %s table is 210px tall' % tag,
                  208 <= geo['h'] <= 212, geo)
            check('HUNT-102 %s table content fits its box' % tag,
                  geo['scrollH'] <= geo['clientH'] + 1, geo)
            if geo.get('footerTop') is not None and geo.get('rows'):
                last = geo['rows'][-1]
                check('HUNT-102 %s last row above footer' % tag,
                      last['bottom'] <= geo['footerTop'] + 1,
                      geo)
        R5.shot(pg, 'r14-ui-targetplan-%s.png' % tag)
        b.close()


def hunt_103_live(pw):
    """Analyzer captions one line on Roast and BatchDetail
    at 360 px dark."""
    for path, tag in (('/', 'roast'), ('/log/detail', 'detail')):
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': 360,
                                      'height': 800},
                            timezone_id='America/Denver')
        if tag == 'detail':
            R5.stage_one(1042)
        pg = R5.open_page(ctx, path)
        pg.wait_for_timeout(2500)
        set_theme_ui(pg, 'Dark')
        pg.wait_for_timeout(1200)
        scroll_to(pg, 1.0)
        caps = {}
        for cap in ('BT (F)', 'RoR', 'Ghost (F)', 'Dev (F)'):
            rects = leaf_rects(pg, cap)
            caps[cap] = rects
        print('HUNT-103 %s analyzer captions:' % tag, caps,
              flush=True)
        for cap, rects in caps.items():
            check('HUNT-103 %s %s caption one line' % (tag, cap),
                  len(rects) >= 1
                  and all(r['h'] <= 16 for r in rects), rects)
        R5.shot(pg, 'r14-ui-analyzer-%s-360-dark.png' % tag)
        b.close()


def hunt_104_live(pw):
    """MetaForm Save button one line at 1360 px light; the
    BatchEdit Save Batch button one line at 360 px dark."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360,
                                  'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Save Batch Details')
    btn = pg.evaluate("""() => {
      const b = [...document.querySelectorAll('button')]
        .find(e => (e.textContent || '').trim() ===
          'Save Batch Details' && e.offsetParent !== null);
      if (!b) return {found: false};
      const r = b.getBoundingClientRect();
      return {found: true, w: Math.round(r.width),
              h: Math.round(r.height),
              lines: Math.round(b.scrollHeight / 16)};
    }""")
    print('HUNT-104 MetaForm Save button:', btn, flush=True)
    check('HUNT-104 MetaForm Save button found',
          btn.get('found') is True, btn)
    if btn.get('found'):
        check('HUNT-104 MetaForm Save button one line tall',
              btn['h'] <= 45 and btn['w'] >= 100, btn)
    R5.shot(pg, 'r14-ui-metaform-1360-light.png')
    b.close()
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360,
                                  'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    pg.locator('text=1,042').first.click(timeout=25000)
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='Edit').first.click(
        timeout=25000)
    pg.wait_for_timeout(3500)
    btn = pg.evaluate("""() => {
      const b = [...document.querySelectorAll('button')]
        .find(e => (e.textContent || '').trim() ===
          'Save Batch' && e.offsetParent !== null);
      if (!b) return {found: false};
      const r = b.getBoundingClientRect();
      return {found: true, w: Math.round(r.width),
              h: Math.round(r.height)};
    }""")
    print('HUNT-104 BatchEdit Save Batch button:', btn, flush=True)
    check('HUNT-104 BatchEdit Save Batch button found',
          btn.get('found') is True, btn)
    if btn.get('found'):
        check('HUNT-104 BatchEdit Save Batch button one line',
              btn['h'] <= 45 and btn['w'] >= 80, btn)
    measure(pg, 'editor 360-dark')
    R5.shot(pg, 'r14-ui-editor-360-dark.png')
    dock = pg.locator('.docked-view-right')
    dock.get_by_role('button', name='Close').first.click(
        timeout=25000)
    check('HUNT-104 editor dock closes without saving',
          P.wait_until(
              lambda: dock.first.inner_text().strip() == '',
              15),
          repr(dock.first.inner_text()[:80]))
    b.close()


def hunt_105_live(pw):
    """Show on controls captions one line at 1360 px light
    and 360 px dark."""
    for width, height, theme, tag in (
            (1360, 900, 'Light', '1360-light'),
            (360, 800, 'Dark', '360-dark')):
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': width,
                                      'height': height},
                            timezone_id='America/Denver')
        pg = R5.open_page(ctx, '/settings')
        pg.wait_for_timeout(2000)
        set_theme_ui(pg, theme)
        pg.wait_for_timeout(1200)
        scroll_into_view(pg, 'Custom Events')
        rects = leaf_rects(pg, 'Show on controls')
        print('HUNT-105 %s show captions:' % tag, rects,
              flush=True)
        check('HUNT-105 %s four show captions found' % tag,
              len(rects) == 4, rects)
        check('HUNT-105 %s show captions one line' % tag,
              len(rects) >= 1
              and all(r['h'] <= 16 for r in rects), rects)
        R5.shot(pg, 'r14-ui-customs-%s.png' % tag)
        b.close()


def hunt_106_live(pw):
    """HUD captions one line at 360 px, gear inside the
    viewport, in Idle (light and dark). The post-Drop DROP
    caption is checked in the live roast."""
    for theme, tag in (('Light', '360-light'),
                       ('Dark', '360-dark')):
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': 360,
                                      'height': 800},
                            timezone_id='America/Denver')
        pg = R5.open_page(ctx, '/')
        pg.wait_for_timeout(2500)
        set_theme_ui(pg, theme)
        pg.wait_for_timeout(1200)
        caps = {}
        for cap in ('BEAN F', 'TIME', 'PHASE'):
            caps[cap] = leaf_rects(pg, cap)
        gear = pg.evaluate("""() => {
          const g = document.querySelector(
            '.psc-roast-gear-btn');
          if (!g) return {found: false};
          const r = g.getBoundingClientRect();
          return {found: true, right: Math.round(r.right),
                  vw: window.innerWidth};
        }""")
        print('HUNT-106 %s HUD captions:' % tag, caps, gear,
              flush=True)
        for cap, rects in caps.items():
            check('HUNT-106 %s %s caption one line' % (tag, cap),
                  len(rects) >= 1
                  and all(r['h'] <= 16 for r in rects), rects)
        check('HUNT-106 %s gear inside viewport' % tag,
              gear.get('found') and gear['right'] <= gear['vw'],
              gear)
        R5.shot(pg, 'r14-ui-hud-%s.png' % tag)
        b.close()


def app_settings_slideover(pw):
    """App Settings dock slides in from the right and back
    out at 360 px and 1360 px, staying inside the viewport."""
    for width, height, tag in ((360, 800, '360-dark'),
                               (1360, 900, '1360-light')):
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': width,
                                      'height': height},
                            timezone_id='America/Denver')
        pg = R5.open_page(ctx, '/')
        pg.wait_for_timeout(2500)
        pg.locator('.psc-roast-gear-btn:visible').first.click(
            timeout=20000)
        pg.wait_for_timeout(1500)
        dock = pg.evaluate("""() => {
          const d = document.querySelector(
            '.docked-view-right');
          if (!d) return {found: false};
          const r = d.getBoundingClientRect();
          return {found: true, left: Math.round(r.left),
                  right: Math.round(r.right),
                  w: Math.round(r.width),
                  vw: window.innerWidth,
                  text: (d.innerText || '').slice(0, 60)};
        }""")
        print('app settings open %s:' % tag, dock, flush=True)
        check('app settings dock opens %s' % tag,
              dock.get('found') and 'App Settings' in
              dock.get('text', ''), dock)
        if dock.get('found'):
            check('app settings dock inside viewport %s' % tag,
                  dock['left'] >= 0
                  and dock['right'] <= dock['vw'], dock)
        measure(pg, 'app settings open %s' % tag)
        R5.shot(pg, 'r14-ui-appsettings-%s.png' % tag)
        pg.get_by_role('button', name='Close',
                       exact=True).first.click(timeout=20000)
        closed = P.wait_until(
            lambda: pg.evaluate("""() => {
              const d = document.querySelector(
                '.docked-view-right');
              return !d || (d.innerText || '').trim() === '';
            }"""), 15)
        check('app settings dock closes %s' % tag, closed)
        b.close()


def toast_and_cross_session_theme(pw):
    """Saving the metadata form with unchanged values fires
    a toast, and a theme change on one open page reaches the
    other session without a reload."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360,
                                  'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Save Batch Details')
    click_btn(pg, 'Save Batch Details')
    pg.wait_for_timeout(1500)
    toast = pg.evaluate("""() => {
      const els = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          (e.textContent || '').includes(
            'Batch details saved'));
      if (!els.length) return {found: false};
      const r = els[0].getBoundingClientRect();
      return {found: true, w: Math.round(r.width),
              h: Math.round(r.height),
              y: Math.round(r.top)};
    }""")
    print('metadata save toast light:', toast, flush=True)
    check('toast fires on metadata save (Light)',
          toast.get('found') is True, toast)
    if toast.get('found'):
        check('toast visible in viewport (Light)',
              toast['y'] >= 0 and toast['y'] < 900, toast)
    pg.wait_for_timeout(6000)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Save Batch Details')
    click_btn(pg, 'Save Batch Details')
    pg.wait_for_timeout(1500)
    toast = pg.evaluate("""() => {
      const els = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          (e.textContent || '').includes(
            'Batch details saved'));
      if (!els.length) return {found: false};
      const r = els[0].getBoundingClientRect();
      const cs = getComputedStyle(els[0]);
      return {found: true, w: Math.round(r.width),
              h: Math.round(r.height),
              y: Math.round(r.top),
              bg: cs.backgroundColor, color: cs.color};
    }""")
    print('metadata save toast dark:', toast, flush=True)
    check('toast fires on metadata save (Dark)',
          toast.get('found') is True, toast)
    if toast.get('found'):
        check('toast visible in viewport (Dark)',
              toast['y'] >= 0 and toast['y'] < 900, toast)
    pg.wait_for_timeout(6000)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(2500)
    def root_of(page):
        return page.evaluate("""() => getComputedStyle(
          document.documentElement).getPropertyValue(
          '--containerRoot').trim()""")
    def wait_root(page, want, timeout=20):
        t0 = time.time()
        got = ''
        while time.time() - t0 < timeout:
            got = root_of(page)
            if got == want:
                return got
            pg.wait_for_timeout(500)
        return got
    set_theme_ui(pg, 'Dark')
    got = wait_root(pg2, '#161616')
    print('cross-session theme: log --containerRoot after '
          'Dark on Roast:', repr(got), flush=True)
    check('theme Dark reaches open Log session',
          got == '#161616', got)
    set_theme_ui(pg, 'Light')
    got = wait_root(pg2, '#FAFAFA')
    print('cross-session theme: log --containerRoot after '
          'Light on Roast:', repr(got), flush=True)
    check('theme Light reaches open Log session',
          got == '#FAFAFA', got)
    b.close()


DOCK_UNIVERSE = {'Charge', 'Dry End', 'FC Start', 'FC End',
                 'SC Start', 'SC End', 'Drop', 'Cool', 'Finish',
                 'Reset / New Roast', 'Fan Boost', 'Drum Note'}


def dock_labels(pg):
    texts = pg.evaluate(
        """() => [...document.querySelectorAll('button')]
        .filter(b => b.offsetParent !== null)
        .map(b => (b.textContent || '').trim())
        .filter(t => t)""")
    out = []
    for t in texts:
        if t in DOCK_UNIVERSE and t not in out:
            out.append(t)
    return out


def wait_dock(pg, want, timeout=20):
    t0 = time.time()
    got = []
    while time.time() - t0 < timeout:
        got = dock_labels(pg)
        if got == want:
            return got
        pg.wait_for_timeout(500)
    return got


def hud_caption(pg, text):
    rects = leaf_rects(pg, text)
    return rects


def live_roast_360_dark(pw):
    """Full roast at 360 px dark, stamping every event seconds
    apart: HUD captions stay one line while Roasting and after
    Drop (HUNT-106 DROP caption), the live chart shows only the
    thinned labels, stats shares sum to 100, and the batch
    saves and deletes cleanly."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    try:
        set_theme_ui(pg, 'Dark')
        _max_db = int(P.psql('SELECT MAX(batch_number) FROM batches'))
        _cur_no = int(P.tag(B + '/BatchNumber'))
        NEXT_BATCH[0] = (_cur_no if _cur_no > _max_db
                         else _max_db + 1)
        nxt = NEXT_BATCH[0]
        check('live roast starts Idle at batch 1042',
              P.tag(B + '/State') == 'Idle'
              and P.tag(B + '/BatchNumber') == 1042,
              (P.tag(B + '/State'), P.tag(B + '/BatchNumber')))
        got = wait_dock(pg, ['Charge'])
        check('dock at Idle offers Charge only', got == ['Charge'],
              got)
        click_btn(pg, 'New Roast')
        check('new roast takes next batch number',
              P.wait_until(
                  lambda: P.tag(B + '/BatchNumber') == nxt, 30),
              P.tag(B + '/BatchNumber'))
        click_btn(pg, 'Charge')
        check('charge starts the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Roasting', 30))
        pg.wait_for_timeout(3000)
        got = wait_dock(pg, ['Dry End', 'Fan Boost'])
        check('dock while roasting offers Dry End and Fan Boost',
              got == ['Dry End', 'Fan Boost'], got)
        pill = pg.evaluate("""() => {
          const leaf = [...document.querySelectorAll('*')]
            .find(e => e.children.length === 0 &&
              (e.textContent || '').trim() === 'Roasting' &&
              e.offsetParent !== null);
          if (!leaf) return {found: false};
          return {found: true, sw: leaf.scrollWidth,
                  cw: leaf.clientWidth};
        }""")
        time_rects = hud_caption(pg, 'TIME')
        print('HUD while Roasting:', pill, time_rects,
              flush=True)
        check('HUNT-106 Roasting pill text fits its box',
              pill.get('found') and pill['sw'] <= pill['cw'],
              pill)
        check('HUNT-106 TIME caption one line while Roasting',
              len(time_rects) >= 1
              and all(r['h'] <= 16 for r in time_rects),
              time_rects)
        measure(pg, 'roast live 360-dark')
        R5.shot(pg, 'r14-ui-roast-live-360-dark.png')
        for label, member in (
                ('Dry End', 'DryEndElapsedSec'),
                ('FC Start', 'FirstCrackStartElapsedSec'),
                ('FC End', 'FirstCrackEndElapsedSec'),
                ('SC Start', 'SecondCrackStartElapsedSec'),
                ('SC End', 'SecondCrackEndElapsedSec')):
            pg.wait_for_timeout(3000)
            click_btn(pg, label)
            check('%s stamps' % label.lower(), P.wait_until(
                lambda m=member: (P.tag(B + '/' + m) or -1) >= 0,
                30))
        click_btn(pg, 'Drop')
        check('drop ends the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Dropped', 30))
        pg.wait_for_timeout(4000)
        got = wait_dock(pg, ['Cool', 'Finish'])
        check('dock at Dropped offers Cool and Finish',
              got == ['Cool', 'Finish'], got)
        drop_rects = hud_caption(pg, 'DROP')
        print('HUD after Drop:', drop_rects, flush=True)
        check('HUNT-106 DROP caption one line after Drop',
              len(drop_rects) >= 1
              and all(r['h'] <= 16 for r in drop_rects),
              drop_rects)
        body = pg.locator('body').inner_text()
        m = re.search(
            r'Dry\s+(\S+)\s+(\d+)%.*?Mai\w*\s+(\S+)\s+(\d+)%.*?'
            r'Dev\s+(\S+)\s+(\d+)%.*?DTR\s+(\d+)%', body, re.S)
        print('stats line after drop:', m.groups() if m else
              body[:400], flush=True)
        if m:
            shares = [int(m.group(2)), int(m.group(4)),
                      int(m.group(6))]
            check('stats phase shares sum to 100',
                  sum(shares) == 100, shares)
        else:
            check('stats line parses after drop', False,
                  body[:200])
        measure(pg, 'roast dropped 360-dark')
        R5.shot(pg, 'r14-ui-roast-dropped-360-dark.png')
        click_btn(pg, 'Cool')
        check('cool reaches Cooling', P.wait_until(
            lambda: P.tag(B + '/State') == 'Cooling', 30))
        got = wait_dock(pg, ['Finish'])
        check('dock while Cooling offers Finish only',
              got == ['Finish'], got)
        click_btn(pg, 'Finish')
        check('finish reaches Complete', P.wait_until(
            lambda: P.tag(B + '/State') == 'Complete', 30))
        got = wait_dock(pg, ['Charge', 'Reset / New Roast'])
        check('dock at Complete offers Charge and Reset',
              got == ['Charge', 'Reset / New Roast'], got)
        measure(pg, 'roast complete 360-dark')
        R5.shot(pg, 'r14-ui-roast-complete-360-dark.png')
        click_btn(pg, 'Save Batch')
        check('roast saves as next batch number', P.wait_until(
            lambda: P.psql('SELECT COUNT(*) FROM batches '
                           'WHERE batch_number = %d' % nxt) == '1',
            30))
        click_btn(pg, 'Reset')
        check('reset returns to Idle', P.wait_until(
            lambda: P.tag(B + '/State') == 'Idle', 30))
        delete_batch_ui(pg, nxt)
    finally:
        b.close()
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    P.write_tags([('[default]Roastery/PressSlots/Slot%02d' % i,
                   '') for i in range(16)])
    P.write_tags([(B + '/BatchNumber', 1042)])
    time.sleep(30)
    check('live roast leaves 0 press rows after 30 s',
          P.psql('SELECT COUNT(*) FROM batch_events') == '0')
    slots = P.read_tags(['[default]Roastery/PressSlots/Slot%02d'
                         % i for i in range(16)])
    check('PressSlots empty after live roast',
          all(not s for s in slots), slots)


def delete_batch_ui(pg, number):
    label = format(number, ',')
    pg.goto(P.BASE + '/log', wait_until='networkidle',
            timeout=60000)
    pg.wait_for_timeout(1500)
    pg.locator('text=%s' % label).first.click(timeout=25000)
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='Delete').first.click(
        timeout=25000)
    pg.wait_for_timeout(1000)
    pg.get_by_role('button',
                   name='Confirm Delete').first.click(
                       timeout=25000)
    pg.wait_for_timeout(2500)
    check('batch %d deletes through the Log UI' % number,
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = %d' % number) == '0')


def restore_defaults_via_ui(pw):
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360,
                                  'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, 'System')
    b.close()


def clean_state():
    ok = (P.tag(B + '/State') == 'Idle'
          and P.tag(B + '/BatchNumber') == 1042
          and P.tag(TM) == 'System'
          and P.tag(B + '/CompareAlignEvent') == 'charge'
          and P.tag(B + '/DispAxisFormat') == 'm:ss'
          and P.psql('SELECT COUNT(*) FROM batches') == '7'
          and P.psql('SELECT COUNT(*) FROM batch_series')
          == '101'
          and P.psql('SELECT COUNT(*) FROM batch_events')
          == '0')
    check('lab left clean (Idle, 1042, System, 7/101/0)',
          ok, (P.tag(B + '/State'), P.tag(B + '/BatchNumber'),
               P.tag(TM), P.tag(B + '/CompareAlignEvent'),
               P.psql('SELECT COUNT(*) FROM batches')))


def acquire_lock():
    for _ in range(135):
        try:
            os.mkdir(LOCK)
            return True
        except FileExistsError:
            time.sleep(20)
    return False


def main():
    static_checks()
    if not acquire_lock():
        print('LAB LOCK: could not claim %s after 45 min'
              % LOCK, flush=True)
        print('TOTAL %d PASS, %d FAIL'
              % (PASSES[0], len(FAILS)))
        return 2
    try:
        with sync_playwright() as pw:
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            hunt_102_live(pw)
            hunt_103_live(pw)
            hunt_104_live(pw)
            hunt_105_live(pw)
            hunt_106_live(pw)
            app_settings_slideover(pw)
            toast_and_cross_session_theme(pw)
            state = P.tag(B + '/State')
            if state == 'Idle':
                live_roast_360_dark(pw)
            else:
                print('LAB BUSY: state=%s, skipping live roast; '
                      'run live_roast_360_dark separately when '
                      'the lab is Idle' % state, flush=True)
            restore_defaults_via_ui(pw)
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass
    clean_state()
    print('TOTAL %d PASS, %d FAIL'
          % (PASSES[0], len(FAILS)))
    if FAILS:
        print('FAILURES:', FAILS)
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
