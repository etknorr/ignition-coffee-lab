#!/usr/bin/env python3
"""Round 13 fresh hunting pass, UI/UX focus (worker B).

Fresh hunt continuing from HUNT-86. Worker A took HUNT-87
through HUNT-91 for the Artisan math finds, so new UI
defects in this suite are numbered from HUNT-92 (claimed
in ~/workspace/ignition-lab/r13-hunt-numbers.txt).

1. Static phase-aware dock contract: dock_actions in
   roastery/core/code.py must offer exactly the right buttons
   at every state and stamped-event combination, with the lead
   button first, Drop as secondary while a later phase is
   still open and primary when it is the only action left,
   and named enabled customs shown while unnamed or disabled
   slots stay hidden. The live roast below proves the same
   contract through the rendered buttons at 360px dark.
2. Four-page walk (Roast, Log, BatchDetail staged 1042,
   Settings) at 1360px and 360px, light and dark, with the
   compare row, the calculator card and the alarms panel
   scrolled into view, measuring horizontal overflow, clipped
   leaf text and inner horizontal scrollers, plus a Settings
   scroll sweep at 360px dark.
3. Dropdown option list at 360px dark: the compare A picker
   opened, its option list must stay inside the viewport.
4. Log compare live at 360px dark (A 1048, B 1047, CHARGE).
5. BatchDetail calculator live edit at 1360px light: charge
   weight 200 to 250 must move Expected out to 212.5 g, then
   back to 200 and 170.0 g.
6. Settings alarms Load read-back at 1360px light: loading
   Alarm 1 must fill the editor with High bean temp and its
   message.
7. Slide over batch editor at 360px dark: opens for 1042,
   no overflow, closes cleanly without saving.
8. Live roast at 360px dark through every dock stage (Dry
   End, FC Start, FC End, SC Start, SC End, Drop, Cool,
   Finish), checking the offered buttons at each stage, the
   stats line after Drop, the temporary Banner alarm firing
   mid-roast and clearing after Finish (HUNT-76 regression),
   then Save Batch, Reset, and delete of the scratch batch
   through the Log UI.

ThemeMode is set only through the App Settings UI flow
(gear, theme button, Close) in this suite, never through
the API, and restored to System the same way at the end.
The suite claims the lab lock itself
(~/workspace/ignition-lab/.lab-lock) for the live portion
and releases it in a finally, so a concurrent worker never
shares the browser. Does NOT retest the timezone TIME axis
or HUNT-46 (both beta-gated) and does NOT touch the press
path (HUNT-53 app fix out of scope), the HUNT-58 r4hunt
chain, the builder files, or the Docker packaging. Leaves
the lab clean.
"""
import ast
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
LOCK = '/home/hatch/workspace/ignition-lab/.lab-lock'
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
      const el = document.querySelector('.psc-roast-content');
      if (el) { el.scrollTop = el.scrollHeight * f; return; }
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
    """The Perspective reconnect banner text lives in the DOM
    inside .connection-banner even when the banner is
    inactive: inner_text includes it, so presence in the
    body text proves nothing. The check is whether the
    banner element is actually rendered inside the viewport.
    An inactive banner is parked above the viewport (y -28)
    and is not a visible defect."""
    info = pg.evaluate(BANNER_JS)
    check(label + ' no visible reconnect banner',
          (not info.get('found'))
          or (not info.get('inViewport')), info)


def click_btn(pg, name, timeout=20000):
    pg.locator('button').filter(has_text=name).first.click(
        timeout=timeout)


def set_theme_ui(pg, theme):
    """Set ThemeMode through the App Settings UI flow only:
    gear, theme button, Close. Never a direct tag write.
    If the gear click times out, the Perspective session may
    have died (run 4: the Maker trial expired mid-restore
    and the session WebSocket closed at 13:27, so the gear
    was unclickable). Reload once for a fresh session and
    retry; a second failure is a real defect, not a flake."""
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


def extract_fns(path, names, extra=None):
    src = open(path).read()
    tree = ast.parse(src)
    ns = {'math': math}
    ns.update(extra or {})
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
    for name in names:
        if name not in ns:
            raise AssertionError('%s not found in %s'
                                 % (name, path))
    return ns


def _dock_labels(state, stamped, customs=None):
    """Static dock_actions call. stamped is a set of member
    names among DryEndElapsedSec, FirstCrackStartElapsedSec,
    FirstCrackEndElapsedSec, SecondCrackStartElapsedSec,
    SecondCrackEndElapsedSec. customs maps slot number to
    (name, enabled); slot 1 defaults to Fan Boost enabled."""
    vals = {'State': state}
    for m in ('DryEndElapsedSec', 'FirstCrackStartElapsedSec',
              'FirstCrackEndElapsedSec',
              'SecondCrackStartElapsedSec',
              'SecondCrackEndElapsedSec'):
        vals[m] = 10 if m in stamped else -1
    customs = customs or {}
    for i in (1, 2, 3, 4):
        name, enabled = customs.get(i, ('Fan Boost', True)
                                     if i == 1 else ('', True))
        vals['CustomEvent%dName' % i] = name
        vals['CustomEvent%dEnabled' % i] = enabled

    def read_members(members):
        return {m: vals.get(m) for m in members}

    ns = extract_fns(CORE, ['dock_actions'],
                     extra={'read_members': read_members})
    return ns['dock_actions']()


SETTINGS_VIEW = ('/home/hatch/workspace/ignition-coffee-lab/'
                 'roastery/project/Roastery/com.inductiveautomation.'
                 'perspective/views/Views/SettingsPage/view.json')


def static_headrow_position():
    """HUNT-92: the Settings page HeadRow had no position
    config, so it laid out at 0 height and the Roaster card
    covered the Settings title, subtitle and gear button.
    The sibling page headers (LogPage HeadRow, RoastPage
    HeaderBar) carry grow 0, shrink 0, basis auto; the fix
    gives the Settings HeadRow the same position."""
    import json as _json
    view = _json.load(open(SETTINGS_VIEW))

    def find(c, name):
        if c.get('meta', {}).get('name') == name:
            return c
        for ch in c.get('children', []):
            hit = find(ch, name)
            if hit is not None:
                return hit
        return None

    head = find(view['root'], 'HeadRow')
    check('HUNT-92 Settings HeadRow exists', head is not None)
    if head is not None:
        pos = head.get('position') or {}
        check('HUNT-92 Settings HeadRow has a position',
              pos.get('basis') == 'auto'
              and pos.get('grow') == 0
              and pos.get('shrink') == 0, pos)
    log = _json.load(open(SETTINGS_VIEW.replace(
        'SettingsPage', 'LogPage')))
    log_head = find(log['root'], 'HeadRow')
    check('HUNT-92 LogPage HeadRow still carries basis auto',
          (log_head or {}).get('position', {}).get('basis')
          == 'auto', (log_head or {}).get('position'))


def static_dock_contract():
    """These static checks pin the dock contract the live
    roast proves through the rendered buttons."""
    cases = [
        ('Idle', set(), ['Charge']),
        ('Complete', set(), ['Charge', 'Reset / New Roast']),
        ('Dropped', set(), ['Cool', 'Finish']),
        ('Cooling', set(), ['Finish']),
        ('Roasting', set(), ['Dry End', 'Fan Boost']),
        ('Roasting', {'DryEndElapsedSec'},
         ['FC Start', 'Fan Boost']),
        ('Roasting', {'DryEndElapsedSec',
                      'FirstCrackStartElapsedSec'},
         ['FC End', 'Drop', 'Fan Boost']),
        ('Roasting', {'DryEndElapsedSec',
                      'FirstCrackStartElapsedSec',
                      'FirstCrackEndElapsedSec'},
         ['SC Start', 'Drop', 'Fan Boost']),
        ('Roasting', {'DryEndElapsedSec',
                      'FirstCrackStartElapsedSec',
                      'FirstCrackEndElapsedSec',
                      'SecondCrackStartElapsedSec'},
         ['SC End', 'Drop', 'Fan Boost']),
        ('Roasting', {'DryEndElapsedSec',
                      'FirstCrackStartElapsedSec',
                      'FirstCrackEndElapsedSec',
                      'SecondCrackStartElapsedSec',
                      'SecondCrackEndElapsedSec'},
         ['Drop', 'Fan Boost']),
    ]
    for state, stamped, want in cases:
        got = _dock_labels(state, stamped)
        labels = [d['label'] for d in got]
        check('dock %s %s offers %s' % (state, sorted(stamped),
                                        want),
              labels == want, labels)
    got = _dock_labels('Roasting',
                       {'DryEndElapsedSec',
                        'FirstCrackStartElapsedSec'})
    by_label = {d['label']: d for d in got}
    check('dock FC End is the lead button',
          by_label['FC End']['lead'] is True, by_label)
    check('dock Drop is secondary while FC End is open',
          by_label['Drop']['kind'] == 'secondary'
          and by_label['Drop']['lead'] is False, by_label)
    got = _dock_labels('Roasting',
                       {'DryEndElapsedSec',
                        'FirstCrackStartElapsedSec',
                        'FirstCrackEndElapsedSec',
                        'SecondCrackStartElapsedSec',
                        'SecondCrackEndElapsedSec'})
    check('dock Drop is primary when it is the only action',
          got[0]['kind'] == 'primary'
          and got[0]['lead'] is True, got)
    got = _dock_labels('Roasting', set(),
                       customs={1: ('Fan Boost', True),
                                2: ('', True),
                                3: ('Drum Note', False),
                                4: ('', True)})
    check('dock hides unnamed and disabled customs',
          [d['label'] for d in got] == ['Dry End', 'Fan Boost'],
          got)
    got = _dock_labels('Roasting', set(),
                       customs={1: ('Fan Boost', True),
                                2: ('Drum Note', True)})
    check('dock shows a named enabled custom',
          [d['label'] for d in got]
          == ['Dry End', 'Fan Boost', 'Drum Note'], got)
    got = _dock_labels('Roasting', set(), customs={})
    check('dock standard actions carry customIndex 0 and '
          'the custom carries its slot',
          all(d['customIndex'] == 0
              for d in got if d['kind'] != 'custom')
          and [d['customIndex'] for d in got
               if d['kind'] == 'custom'] == [1], got)


DOCK_UNIVERSE = {'Charge', 'Dry End', 'FC Start', 'FC End',
                 'SC Start', 'SC End', 'Drop', 'Cool', 'Finish',
                 'Reset / New Roast', 'Fan Boost', 'Drum Note'}


def dock_labels(pg):
    """Visible dock button labels, deduped: at phone widths
    the Controls view and the fixed bottom dock both render
    the same DockActionsJson set."""
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
    R5.shot(pg, 'r13-ui-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    no_connection_check(pg2, 'log %s' % tag)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r13-ui-log-%s.png' % tag)
    scroll_into_view(pg2, 'Pick up to three batches')
    measure(pg2, 'log compare row %s' % tag)
    R5.shot(pg2, 'r13-ui-log-compare-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    no_connection_check(pg3, 'detail %s' % tag)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r13-ui-detail-%s.png' % tag)
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
    scroll_into_view(pg3, 'Yield and Conversion Calculator')
    measure(pg3, 'detail calculator %s' % tag)
    R5.shot(pg3, 'r13-ui-detail-calc-%s.png' % tag)
    scroll_to(pg3, 1.0)
    measure(pg3, 'detail bottom %s' % tag)
    R5.shot(pg3, 'r13-ui-detail-bottom-%s.png' % tag)
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    no_connection_check(pg4, 'settings %s' % tag)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r13-ui-settings-%s.png' % tag)
    scroll_into_view(pg4, 'Alarm definitions')
    measure(pg4, 'settings alarms %s' % tag)
    R5.shot(pg4, 'r13-ui-settings-alarms-%s.png' % tag)
    b.close()


def settings_sweep(pw):
    """Settings scroll sweep at 360px dark."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        scroll_to(pg, frac)
        measure(pg, 'settings sweep %d%% 360-dark'
                % int(frac * 100))
        R5.shot(pg, 'r13-ui-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def dropdown_open_list(pw):
    """Compare A picker opened at 360px dark: the option
    list must stay inside the viewport."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Pick up to three batches')
    dds = pg.locator('[data-component="ia.input.dropdown"]')
    dds.nth(0).click(timeout=20000)
    pg.wait_for_timeout(1200)
    box = pg.evaluate("""() => {
      const opts = [...document.querySelectorAll(
        'a.iaDropdownCommon_option')];
      if (!opts.length) return {found: false};
      const rs = opts.map(e => e.getBoundingClientRect());
      return {found: true, n: opts.length,
        left: Math.min(...rs.map(r => r.left)),
        right: Math.max(...rs.map(r => r.right)),
        vw: window.innerWidth};
    }""")
    print('dropdown open list:', box, flush=True)
    check('dropdown option list found', box.get('found') is True,
          box)
    if box.get('found'):
        check('dropdown option list inside viewport',
              box['left'] >= 0 and box['right'] <= box['vw'],
              box)
    measure(pg, 'log dropdown open 360-dark')
    R5.shot(pg, 'r13-ui-dropdown-open-360-dark.png')
    pg.keyboard.press('Escape')
    pg.wait_for_timeout(500)
    b.close()


def compare_live(pw):
    """Compare A 1048, B 1047 at 360px dark."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    set_theme_ui(pg, 'Dark')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Pick up to three batches')
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")
    print('compare caption:', caps, flush=True)
    check('compare caption names A 1048 and B 1047',
          any('A = Batch 1048' in c and 'B = Batch 1047' in c
              for c in caps), caps)
    check('compare caption names each slot once',
          all(c.count('A = Batch 1048') == 1
              and c.count('B = Batch 1047') == 1 for c in caps),
          caps)
    measure(pg, 'compare AB 360-dark')
    R5.shot(pg, 'r13-ui-compare-360-dark.png')
    b.close()


def input_by_caption(pg, caption):
    """Value of the input under a caption. Several captions
    share their text with a table column header (the alarms
    table has Name and Message columns above the editor), so
    every matching leaf is tried in document order and the
    first one with a text input underneath wins. Checkbox
    inputs do not count: the alarms table header carries a
    select-all checkbox, whose value 'on' is not the editor
    field's value."""
    return pg.evaluate("""(cap) => {
      const leaves = [...document.querySelectorAll('*')]
        .filter(e => e.children.length === 0 &&
          (e.textContent || '').trim().toUpperCase() === cap);
      for (const leaf of leaves) {
        let p = leaf.parentElement;
        for (let i = 0; i < 5 && p; i++) {
          const inp = p.querySelector(
            'input:not([type=checkbox]):not([type=radio]),'
            + ' textarea, select');
          if (inp) return inp.value;
          p = p.parentElement;
        }
      }
      return null;
    }""", caption)


def alarms_load_readback(pw):
    """Loading Alarm 1 must fill the editor with its def."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360,
                                  'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(1500)
    head = pg.evaluate("""() => {
      const content = document.querySelector(
        '.psc-roast-content');
      if (!content || !content.children.length) {
        return {found: false};
      }
      const row = content.children[0];
      const r = row.getBoundingClientRect();
      const gear = [...document.querySelectorAll(
        '.psc-roast-gear-btn')].find(e =>
        e.getAttribute('data-component-path') === 'C.0:0:0:1');
      const g = gear ? gear.getBoundingClientRect() : null;
      const at = g ? document.elementFromPoint(
        g.x + g.width / 2, g.y + g.height / 2) : null;
      return {found: true,
        headH: Math.round(r.height),
        headY: Math.round(r.y),
        gearCovered: at !== null &&
          !(at === gear || gear.contains(at)),
        atTag: at ? at.tagName : null};
    }""")
    print('HUNT-92 settings head row:', head, flush=True)
    check('HUNT-92 Settings HeadRow has height',
          head.get('found') and head.get('headH', 0) > 0, head)
    check('HUNT-92 Settings gear is not covered',
          head.get('found') and not head.get('gearCovered'),
          head)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Alarm definitions')
    # Exact match: a plain 'Load' also matches the Targets
    # panel's 'Load Point' button, which comes first in DOM
    # order and would load a target point instead.
    pg.get_by_role('button', name='Load', exact=True).first.click(
        timeout=20000)
    pg.wait_for_timeout(1500)
    name = input_by_caption(pg, 'NAME')
    msg = input_by_caption(pg, 'MESSAGE')
    print('alarm editor after Load:', repr(name), repr(msg),
          flush=True)
    check('alarm Load fills the name',
          name == 'High bean temp', name)
    check('alarm Load fills the message',
          msg == 'Bean temperature high', msg)
    count = pg.evaluate("""() => {
      const leaf = [...document.querySelectorAll('*')]
        .find(e => e.children.length === 0 &&
          (e.textContent || '').trim().startsWith(
            'Alarms defined:'));
      return leaf ? leaf.textContent.trim() : '';
    }""")
    check('alarm count reads 3', count == 'Alarms defined: 3',
          count)
    R5.shot(pg, 'r13-ui-alarms-loaded-1360-light.png')
    b.close()


def calculator_live_edit(pw):
    """Charge weight 200 to 250 moves Expected out to 212.5,
    then back to 200 and 170.0."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360,
                                  'height': 900},
                        timezone_id='America/Denver')
    R5.stage_one(1042)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(2500)
    set_theme_ui(pg, 'Light')
    pg.wait_for_timeout(1200)
    scroll_into_view(pg, 'Yield and Conversion Calculator')
    inputs = pg.locator('.psc-roast-calc-card input')
    check('calculator inputs found', inputs.count() == 7,
          inputs.count())
    if inputs.count() == 0:
        b.close()
        return
    charge = inputs.nth(0)
    charge.click(timeout=20000)
    charge.fill('250')
    charge.press('Tab')
    pg.wait_for_timeout(1500)
    body = pg.locator('body').inner_text()
    check('calculator Expected out reads 212.5 at 250 g',
          '212.5' in body, body[:300])
    charge.click(timeout=20000)
    charge.fill('200')
    charge.press('Tab')
    pg.wait_for_timeout(1500)
    body = pg.locator('body').inner_text()
    check('calculator Expected out back to 170.0 at 200 g',
          '170.0' in body, body[:300])
    measure(pg, 'detail calculator edited 1360-light')
    R5.shot(pg, 'r13-ui-detail-calc-edited-1360-light.png')
    b.close()


def editor_360_dark(pw):
    """Slide over editor for 1042 at 360px dark: opens, no
    overflow, closes without saving."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
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
    form = pg.locator('[data-component="ia.input.form"]')
    check('editor form opens at 360 dark',
          form.count() >= 1, form.count())
    measure(pg, 'editor 360-dark')
    R5.shot(pg, 'r13-ui-editor-360-dark.png')
    dock = pg.locator('.docked-view-right')
    dock.get_by_role('button', name='Close').first.click(
        timeout=25000)
    check('editor dock closes via its Close button',
          P.wait_until(
              lambda: dock.first.inner_text().strip() == '',
              15),
          repr(dock.first.inner_text()[:80]))
    b.close()


def doc_of(number):
    return json.loads(P.psql(
        'SELECT data FROM batches WHERE batch_number = %d'
        % number))


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


def live_roast_360_dark(pw):
    """Full roast at 360px dark, checking the offered dock
    buttons at every stage, the stats line after Drop, and
    the temporary Banner alarm firing mid-roast and clearing
    after Finish (HUNT-76 regression)."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    orig_alarms = P.tag(B + '/AlarmDefsJson')
    temp_alarms = json.dumps([{
        'name': 'R13 probe', 'enabled': True, 'guard': 'None',
        'offsetSec': 0, 'source': 'BT', 'cond': '>=',
        'value': 210, 'message': 'R13 probe alarm',
        'action': 'Banner'}])
    try:
        set_theme_ui(pg, 'Dark')
        # HUNT-96: mirror the app's HUNT-86 new_roast rule. A
        # current tag above every batch in the database is an
        # untaken number and is reused, not incremented.
        _max_db = int(P.psql('SELECT MAX(batch_number) FROM batches'))
        _cur_no = int(P.tag(B + '/BatchNumber'))
        NEXT_BATCH[0] = (_cur_no if _cur_no > _max_db
                         else _max_db + 1)
        nxt = NEXT_BATCH[0]
        check('live roast starts Idle at next batch',
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
        P.write_tags([(B + '/AlarmDefsJson', temp_alarms)])
        click_btn(pg, 'Charge')
        check('charge starts the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Roasting', 30))
        check('banner alarm fires mid-roast',
              P.wait_until(
                  lambda: P.tag(B + '/AlarmActive') is True, 60),
              repr(P.tag(B + '/AlarmText')))
        pg.wait_for_timeout(3000)
        got = wait_dock(pg, ['Dry End', 'Fan Boost'])
        check('dock while roasting offers Dry End and Fan Boost',
              got == ['Dry End', 'Fan Boost'], got)
        measure(pg, 'roast live 360-dark')
        R5.shot(pg, 'r13-ui-roast-live-360-dark.png')
        click_btn(pg, 'Dry End')
        check('dry end stamps', P.wait_until(
            lambda: (P.tag(B + '/DryEndElapsedSec') or -1) >= 0,
            30))
        got = wait_dock(pg, ['FC Start', 'Fan Boost'])
        check('dock after Dry End offers FC Start',
              got == ['FC Start', 'Fan Boost'], got)
        pg.wait_for_timeout(3000)
        click_btn(pg, 'FC Start')
        check('fc start stamps', P.wait_until(
            lambda: (P.tag(B + '/FirstCrackStartElapsedSec')
                     or -1) >= 0, 30))
        got = wait_dock(pg, ['FC End', 'Drop', 'Fan Boost'])
        check('dock after FC Start offers FC End and Drop',
              got == ['FC End', 'Drop', 'Fan Boost'], got)
        measure(pg, 'roast fc-start 360-dark')
        R5.shot(pg, 'r13-ui-roast-fcstart-360-dark.png')
        pg.wait_for_timeout(3000)
        click_btn(pg, 'FC End')
        check('fc end stamps', P.wait_until(
            lambda: (P.tag(B + '/FirstCrackEndElapsedSec')
                     or -1) >= 0, 30))
        got = wait_dock(pg, ['SC Start', 'Drop', 'Fan Boost'])
        check('dock after FC End offers SC Start and Drop',
              got == ['SC Start', 'Drop', 'Fan Boost'], got)
        pg.wait_for_timeout(3000)
        click_btn(pg, 'SC Start')
        check('sc start stamps', P.wait_until(
            lambda: (P.tag(B + '/SecondCrackStartElapsedSec')
                     or -1) >= 0, 30))
        got = wait_dock(pg, ['SC End', 'Drop', 'Fan Boost'])
        check('dock after SC Start offers SC End and Drop',
              got == ['SC End', 'Drop', 'Fan Boost'], got)
        pg.wait_for_timeout(3000)
        click_btn(pg, 'SC End')
        check('sc end stamps', P.wait_until(
            lambda: (P.tag(B + '/SecondCrackEndElapsedSec')
                     or -1) >= 0, 30))
        got = wait_dock(pg, ['Drop', 'Fan Boost'])
        check('dock after SC End offers Drop only',
              got == ['Drop', 'Fan Boost'], got)
        click_btn(pg, 'Drop')
        check('drop ends the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Dropped', 30))
        pg.wait_for_timeout(4000)
        got = wait_dock(pg, ['Cool', 'Finish'])
        check('dock at Dropped offers Cool and Finish',
              got == ['Cool', 'Finish'], got)
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
        R5.shot(pg, 'r13-ui-roast-dropped-360-dark.png')
        click_btn(pg, 'Cool')
        check('cool reaches Cooling', P.wait_until(
            lambda: P.tag(B + '/State') == 'Cooling', 30))
        got = wait_dock(pg, ['Finish'])
        check('dock while Cooling offers Finish only',
              got == ['Finish'], got)
        click_btn(pg, 'Finish')
        check('finish reaches Complete', P.wait_until(
            lambda: P.tag(B + '/State') == 'Complete', 30))
        check('banner alarm clears after Finish',
              P.wait_until(
                  lambda: P.tag(B + '/AlarmActive') is False, 30),
              repr(P.tag(B + '/AlarmText')))
        check('alarm text empty after Finish',
              P.tag(B + '/AlarmText') == '',
              repr(P.tag(B + '/AlarmText')))
        got = wait_dock(pg, ['Charge', 'Reset / New Roast'])
        check('dock at Complete offers Charge and Reset',
              got == ['Charge', 'Reset / New Roast'], got)
        measure(pg, 'roast complete 360-dark')
        R5.shot(pg, 'r13-ui-roast-complete-360-dark.png')
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
        P.write_tags([(B + '/AlarmDefsJson', orig_alarms)])
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


def restore_defaults_via_ui(pw):
    """Restore ThemeMode System through the App Settings UI
    flow, the same way the suite set it."""
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
    """Claim the lab lock, retrying while a concurrent worker
    holds it. Returns True when this run owns the lock."""
    for _ in range(135):
        try:
            os.mkdir(LOCK)
            return True
        except FileExistsError:
            time.sleep(20)
    return False


def main():
    static_headrow_position()
    static_dock_contract()
    if not acquire_lock():
        print('LAB LOCK: could not claim %s after 45 min'
              % LOCK, flush=True)
        print('TOTAL %d PASS, %d FAIL'
              % (PASSES[0], len(FAILS)))
        return 2
    try:
        state = P.tag(B + '/State')
        check('lab starts clean', state == 'Idle', state)
        if state != 'Idle':
            print('LAB BUSY: state=%s, not running live probes'
                  % state, flush=True)
            print()
            print('PASSES:', PASSES[0])
            print('FAILURES:', FAILS if FAILS else 'none')
            return 2
        with sync_playwright() as pw:
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            settings_sweep(pw)
            dropdown_open_list(pw)
            compare_live(pw)
            calculator_live_edit(pw)
            alarms_load_readback(pw)
            editor_360_dark(pw)
            live_roast_360_dark(pw)
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
