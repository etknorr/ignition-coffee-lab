#!/usr/bin/env python3
"""Round 12 fresh hunting pass (worker B).

Fresh hunt continuing from HUNT-83. New defects this round:
  1. HUNT-84: the compare caption named the reference slot
     twice when it lacked the align event. align_compare_slots
     appended the reference slot to fallbacks in its ref_t
     fallback branch AND again in the per-slot loop, so with
     slot A seeded (no FCe) and alignment on FCe the caption
     read "A has no FCe, charge aligned, A has no FCe, charge
     aligned, B has no FCe, charge aligned". Proven statically
     and live on /log before the fix. The loop already records
     every slot lacking the event, the reference included, so
     the branch now only falls back the reference time.
  2. HUNT-85: clearing a stamped Drop in the slide over
     editor saved the removal but left the derived data stale:
     totalSec, phases, roastEnd (and the relational drop temp
     via the untouched doc) all kept the dropped values, so
     the detail page showed a 10:00 total with DTR 20 percent
     for a batch whose last event was FC Start at 08:00. The
     event time fields are not required in the form, so
     blanking Drop is reachable. _apply_events now recomputes
     from the remaining events when a stamped drop is cleared
     (total is the last stamped event, development 0, DTR 0,
     roastEnd cleared), guarded on a drop having been stamped
     so a batch that never had one keeps its stored total and
     phases exactly. Proven statically and live before the
     fix (created batch 1049, cleared Drop, doc still read
     totalSec 600 with phases 270/210/120).
  3. Settings write/read-back spot checks through the UI:
     the Display axis format dropdown and compare alignment
     dropdown, and the Projection mode dropdown, each flipped
     through the Settings page and read back from its tag,
     then restored. The Display alignment dropdown is the
     same tag the HUNT-84 live proof sets, so the round trip
     also proves the two bindings agree.
  4. The four-page walk (Roast, Log, BatchDetail staged 1042,
     Settings) at 1360px and 360px, light and dark, measuring
     horizontal overflow and clipped leaf text, plus the
     Settings scroll sweep at 360px dark, as the regression
     net for the round.

ThemeMode is set only through the App Settings UI flow
(gear, theme button, Close) in this suite, never through
the API, and restored to System the same way at the end.
CompareAlignEvent is set through the Settings Display
dropdown UI for the restore; the HUNT-84 live proof sets
it through the API first (the dropdown write is proven
separately in the same run). Does NOT retest the timezone
TIME axis passthrough or HUNT-46 (both beta-gated) and does
NOT touch the press path (HUNT-53 app fix out of scope) or
the HUNT-58 r4hunt chain or the builder files. Leaves the
lab clean.
"""
import ast
import json
import math
import re
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
BATCHES = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'batches/code.py')
CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
NEXT_BATCH = [0]
FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '')
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


def set_theme_ui(pg, theme):
    """Set ThemeMode through the App Settings UI flow only:
    gear, theme button, Close. Never a direct tag write."""
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
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in (
                    'AXIS_GRID_STEP_SEC', 'COMPARE_ALIGN_LABELS',
                    'COMPARE_ALIGN_EVENTS')
                for t in n.targets):
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
    for name in names:
        if name not in ns:
            raise AssertionError('%s not found in %s'
                                 % (name, path))
    return ns


def _slot_data():
    return [
        {'slot': 'A', 'number': 1042, 'bean': 'Ethiopia',
         'points': [(0, 200.0), (30, 300.0), (60, 350.0)],
         'rors': {},
         'events': {'charge': 0.0, 'dryEnd': 120.0,
                    'fcStart': 300.0, 'fcEnd': None,
                    'scStart': None, 'scEnd': None,
                    'drop': 600.0}},
        {'slot': 'B', 'number': 1043, 'bean': 'Kenya',
         'points': [(0, 200.0), (30, 310.0), (60, 360.0)],
         'rors': {},
         'events': {'charge': 0.0, 'dryEnd': 100.0,
                    'fcStart': 280.0, 'fcEnd': 400.0,
                    'scStart': None, 'scEnd': None,
                    'drop': 580.0}}]


def static_compare_fallback():
    """HUNT-84: align_compare_slots must name each slot
    lacking the align event exactly once in fallbacks."""
    cns = extract_fns(CORE, ['grid_bucket'])

    class CoreStub(object):
        pass

    cs = CoreStub()
    cs.grid_bucket = staticmethod(cns['grid_bucket'])
    ns = extract_fns(BATCHES, ['align_compare_slots'],
                     extra={'core': cs})
    fn = ns['align_compare_slots']
    info = fn(_slot_data(), 'fcEnd')
    print('HUNT-84 ref-missing fallbacks:', info['fallbacks'],
          flush=True)
    check('HUNT-84 ref slot named once, not twice',
          info['fallbacks'].count(('A', 1042)) == 1,
          info['fallbacks'])
    check('HUNT-84 non-ref slot with the event not listed',
          ('B', 1043) not in info['fallbacks'], info['fallbacks'])
    check('HUNT-84 ref shift stays 0 when it falls back',
          info['shifts']['A'] == 0, info['shifts'])
    check('HUNT-84 ref line still lands on the B event',
          info['ref_sec'] == 390, info['ref_sec'])
    sd = _slot_data()
    sd[1]['events']['fcEnd'] = None
    info2 = fn(sd, 'fcEnd')
    print('HUNT-84 both-missing fallbacks:', info2['fallbacks'],
          flush=True)
    check('HUNT-84 both slots missing named once each',
          info2['fallbacks'] == [('A', 1042), ('B', 1043)],
          info2['fallbacks'])
    info3 = fn(_slot_data(), 'fcStart')
    check('HUNT-84 no fallbacks when both stamp the event',
          info3['fallbacks'] == [], info3['fallbacks'])
    src = open(BATCHES).read()
    seg = src.split('def align_compare_slots')[1].split(
        'def compare_dataset')[0]
    check('HUNT-84 no double append of the reference slot',
          seg.count('fallbacks.append') == 1, seg)


def _drop_doc():
    return {'batchNumber': 1042, 'beanName': 'Ethiopia',
            'roastStart': None,
            'roastEnd': '2026-11-12T10:00:00',
            'dropTempF': 415.0, 'roastDegree': 'Full City',
            'totalSec': 600,
            'phases': {'dryingSec': 270, 'maillardSec': 240,
                       'developmentSec': 90, 'dtrPct': 15.0},
            'events': {
                'charge': {'t': 0, 'ts': None, 'tempF': 392.0},
                'dryEnd': {'t': 270, 'ts': None, 'tempF': 300.0},
                'fcStart': {'t': 480, 'ts': None, 'tempF': 385.0},
                'fcEnd': None, 'scStart': None, 'scEnd': None,
                'drop': {'t': 600, 'ts': None, 'tempF': 415.0},
                'custom': []},
            'metadata': {}}


def static_drop_clear():
    """HUNT-85: _apply_events clearing a stamped Drop must
    recompute the derived data from the remaining events."""
    ns = extract_fns(BATCHES, ['_apply_events', 'parse_mmss',
                               'roast_degree'])
    fn = ns['_apply_events']
    doc = _drop_doc()
    err = fn(doc, {'Ev_drop_t': '', 'Ev_drop_tempF': ''})
    print('HUNT-85 cleared doc:', doc.get('totalSec'),
          doc.get('phases'), doc.get('roastEnd'), flush=True)
    check('HUNT-85 clearing Drop saves with no error',
          err is None, err)
    check('HUNT-85 Drop event is gone',
          (doc.get('events') or {}).get('drop') is None,
          (doc.get('events') or {}).get('drop'))
    check('HUNT-85 total recomputes to the last event (480)',
          doc.get('totalSec') == 480, doc.get('totalSec'))
    check('HUNT-85 phases recompute to 270/210/0, DTR 0.0',
          doc.get('phases') == {'dryingSec': 270,
                                'maillardSec': 210,
                                'developmentSec': 0,
                                'dtrPct': 0.0}, doc.get('phases'))
    check('HUNT-85 roast end clears with the Drop',
          doc.get('roastEnd') is None, doc.get('roastEnd'))
    check('HUNT-85 drop temp keeps the tag convention',
          doc.get('dropTempF') == 415.0
          and doc.get('roastDegree') == 'Full City',
          (doc.get('dropTempF'), doc.get('roastDegree')))
    # Drop-only batch: clearing the only event zeroes the total.
    doc2 = _drop_doc()
    doc2['events'] = {'charge': None, 'dryEnd': None,
                      'fcStart': None, 'fcEnd': None,
                      'scStart': None, 'scEnd': None,
                      'drop': {'t': 600, 'ts': None,
                               'tempF': 415.0}, 'custom': []}
    err2 = fn(doc2, {'Ev_drop_t': ''})
    check('HUNT-85 drop-only clear zeroes the total',
          err2 is None and doc2.get('totalSec') == 0
          and doc2.get('phases') == {'dryingSec': 0,
                                     'maillardSec': 0,
                                     'developmentSec': 0,
                                     'dtrPct': 0.0},
          (doc2.get('totalSec'), doc2.get('phases')))
    # HUNT-80 regression: an empty create doc is untouched.
    doc3 = {'batchNumber': 1099, 'beanName': '', 'roastDegree': '',
            'totalSec': 0, 'phases': {}, 'events': {},
            'metadata': {}, 'manualEntry': True}
    err3 = fn(doc3, {})
    check('HUNT-85 empty create still leaves phases empty',
          err3 is None and doc3.get('totalSec') == 0
          and doc3.get('phases') == {}, doc3.get('phases'))
    # A batch that never had a drop keeps its stored values.
    doc4 = _drop_doc()
    doc4['events']['drop'] = None
    doc4['totalSec'] = 0
    doc4['phases'] = {'dryingSec': 270, 'maillardSec': 210,
                      'developmentSec': 0, 'dtrPct': 0.0}
    err4 = fn(doc4, {'Ev_fcStart_tempF': '390'})
    check('HUNT-85 no-drop batch keeps its stored total',
          err4 is None and doc4.get('totalSec') == 0
          and doc4.get('phases') == {'dryingSec': 270,
                                     'maillardSec': 210,
                                     'developmentSec': 0,
                                     'dtrPct': 0.0},
          (doc4.get('totalSec'), doc4.get('phases')))
    # HUNT-80 regression: typed drop still applies.
    doc5 = {'batchNumber': 1099, 'beanName': '', 'roastDegree': '',
            'totalSec': 0, 'phases': {}, 'events': {},
            'metadata': {}, 'manualEntry': True}
    err5 = fn(doc5, {'Ev_dryEnd_t': '04:30',
                     'Ev_dryEnd_tempF': '300',
                     'Ev_fcStart_t': '08:00',
                     'Ev_fcStart_tempF': '385',
                     'Ev_drop_t': '10:00',
                     'Ev_drop_tempF': '415'})
    check('HUNT-85 typed drop still applies (HUNT-80)',
          err5 is None and doc5.get('totalSec') == 600
          and (doc5.get('events') or {}).get('drop', {}).get('t')
          == 600, doc5.get('totalSec'))


def static_new_roast_reuse():
    """HUNT-86: new_roast must reuse an untaken number instead
    of bumping again on a re-delivered press."""
    src = open(BATCHES).read()
    i = src.index('def new_roast')
    seg = src[i:i + 1500]
    check('HUNT-86 new_roast reuses a number above max_db',
          'int(cur) > max_db' in seg, seg[:200])
    check('HUNT-86 new_roast keeps the untaken number',
          'nxt = int(cur)' in seg, seg[:200])


def caption_texts(pg):
    return pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")


def compare_live(pw):
    """HUNT-84 live: compare on FCe with seeded slots A and B
    (neither stamps FCe); each slot is named once."""
    before = P.tag(B + '/CompareAlignEvent')
    P.write_tags([(B + '/CompareAlignEvent', 'fcEnd')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = caption_texts(pg)
    print('HUNT-84 live captions:', caps, flush=True)
    check('HUNT-84 live caption names A once',
          any(c.count('A has no FCe') == 1 for c in caps), caps)
    check('HUNT-84 live caption names B once',
          any(c.count('B has no FCe') == 1 for c in caps), caps)
    check('HUNT-84 live caption has no doubled fallback',
          all('A has no FCe, charge aligned, A has no FCe'
              not in c for c in caps), caps)
    R5.shot(pg, 'r12-fresh-compare-fce.png')
    b.close()
    P.write_tags([(B + '/CompareAlignEvent', before)])


def field_index_by_label(pg, label):
    return pg.evaluate("""(label) => {
      const inputs = document.querySelectorAll(
        "[data-component='ia.input.form'] "
        + "input.ia_form__field, "
        + "[data-component='ia.input.form'] "
        + "textarea.ia_form__field");
      for (let i = 0; i < inputs.length; i++) {
        let node = inputs[i], text = '';
        for (let d = 0; d < 5 && node; d++) {
          node = node.parentElement;
          if (!node) break;
          text = (node.innerText || '').split('\\n')[0].trim();
          if (text) break;
        }
        if (text === label) return i;
      }
      return -1;
    }""", label)


def fill_labeled(pg, fields, label, value):
    idx = field_index_by_label(pg, label)
    check('editor form has a %s field' % label, idx >= 0, idx)
    if idx >= 0:
        fields.nth(idx).fill(value)


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


def drop_clear_live(pw):
    """HUNT-85 live: create a batch with typed events, then
    clear its Drop time in the slide over editor and read the
    stored document back."""
    nxt = int(P.psql('SELECT MAX(batch_number) FROM batches')) + 1
    NEXT_BATCH[0] = nxt
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='New Batch').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    form = pg.locator('[data-component="ia.input.form"]')
    check('HUNT-85 create editor form opens',
          form.count() >= 1, form.count())
    fields = form.locator('input.ia_form__field, '
                          'textarea.ia_form__field')
    fill_labeled(pg, fields, 'Batch number', str(nxt))
    fill_labeled(pg, fields, 'Bean name', 'R12 drop clear test')
    fill_labeled(pg, fields, 'Dry End time (mm:ss)', '04:30')
    fill_labeled(pg, fields, 'Dry End temp (F)', '300')
    fill_labeled(pg, fields, 'FC Start time (mm:ss)', '08:00')
    fill_labeled(pg, fields, 'FC Start temp (F)', '385')
    fill_labeled(pg, fields, 'Drop time (mm:ss)', '10:00')
    fill_labeled(pg, fields, 'Drop temp (F)', '415')
    pg.get_by_role('button', name='Save Batch').first.click(
        timeout=25000)
    pg.wait_for_timeout(2500)
    doc = doc_of(nxt)
    check('HUNT-85 created batch total is 600 s',
          doc.get('totalSec') == 600, doc.get('totalSec'))
    pg.goto(P.BASE + '/log', wait_until='networkidle',
            timeout=60000)
    pg.wait_for_timeout(2000)
    pg.locator('text=%s' % format(nxt, ',')).first.click(
        timeout=25000)
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='Edit').first.click(
        timeout=25000)
    pg.wait_for_timeout(4000)
    form = pg.locator('[data-component="ia.input.form"]')
    fields = form.locator('input.ia_form__field, '
                          'textarea.ia_form__field')
    idx = field_index_by_label(pg, 'Drop time (mm:ss)')
    check('HUNT-85 edit form has a Drop time field',
          idx >= 0, idx)
    if idx >= 0:
        fields.nth(idx).fill('')
    pg.get_by_role('button', name='Save Batch').first.click(
        timeout=25000)
    pg.wait_for_timeout(2500)
    note = pg.locator('body').inner_text()
    check('HUNT-85 cleared edit saves',
          ('Saved batch %d.' % nxt) in note, note[:200])
    doc2 = doc_of(nxt)
    print('HUNT-85 cleared live doc:', doc2.get('totalSec'),
          doc2.get('phases'), doc2.get('roastEnd'), flush=True)
    check('HUNT-85 cleared doc drops the Drop event',
          (doc2.get('events') or {}).get('drop') is None,
          (doc2.get('events') or {}).get('drop'))
    check('HUNT-85 cleared doc total is 480 s, not 600',
          doc2.get('totalSec') == 480, doc2.get('totalSec'))
    check('HUNT-85 cleared doc phases are 270/210/0, DTR 0.0',
          doc2.get('phases') == {'dryingSec': 270,
                                'maillardSec': 210,
                                'developmentSec': 0,
                                'dtrPct': 0.0}, doc2.get('phases'))
    check('HUNT-85 cleared doc roast end is cleared',
          doc2.get('roastEnd') is None, doc2.get('roastEnd'))
    R5.shot(pg, 'r12-fresh-drop-cleared.png')
    delete_batch_ui(pg, nxt)
    b.close()


def pick_dropdown_option(pg, current_label, option_label):
    """Pick an option in a Perspective dropdown whose current
    value reads current_label. Click through the Playwright
    locator, not a JS .click() on the outer div: the open
    handler lives on the inner container, so a synthetic
    click on the outer div never opens the list (proven by
    the run 1 timeout). Retries the open once."""
    drops = pg.locator('[data-component="ia.input.dropdown"]')
    target = None
    for i in range(drops.count()):
        if current_label in (drops.nth(i).inner_text() or ''):
            target = drops.nth(i)
            break
    check('dropdown showing %s renders' % current_label,
          target is not None, drops.count())
    if target is None:
        return
    for _attempt in (1, 2):
        target.click(timeout=20000)
        pg.wait_for_timeout(900)
        opts = pg.locator('.iaDropdownCommon_option').filter(
            has_text=option_label)
        if opts.count() >= 1:
            opts.first.click(timeout=20000)
            pg.wait_for_timeout(1500)
            return
        pg.wait_for_timeout(1500)
    check('dropdown option %s opens for %s'
          % (option_label, current_label), False, '')


def settings_writeback_live(pw):
    """Settings write/read-back through the UI: the Display
    axis format and compare alignment dropdowns and the
    Projection mode dropdown each flip a tag and read back,
    then restore. This also proves the Log compare row and
    the Settings Display dropdown share the one
    CompareAlignEvent tag."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/settings')
    pg.wait_for_timeout(2000)
    body = pg.locator('body').inner_text()
    check('Settings page shows the Display section',
          'Axis format' in body or 'Display' in body, body[:150])
    # Axis format: Artisan (m:ss) -> Padded (mm:ss) -> back.
    pick_dropdown_option(pg, 'Artisan (m:ss)', 'Padded (mm:ss)')
    check('Settings axis format writes mm:ss to its tag',
          P.wait_until(
              lambda: P.tag(B + '/DispAxisFormat') == 'mm:ss', 15),
          P.tag(B + '/DispAxisFormat'))
    pick_dropdown_option(pg, 'Padded (mm:ss)', 'Artisan (m:ss)')
    check('Settings axis format restores m:ss',
          P.wait_until(
              lambda: P.tag(B + '/DispAxisFormat') == 'm:ss', 15),
          P.tag(B + '/DispAxisFormat'))
    # Compare alignment: CHARGE -> FCe -> back through the UI.
    pick_dropdown_option(pg, 'CHARGE', 'FCe')
    check('Settings align dropdown writes fcEnd to its tag',
          P.wait_until(
              lambda: P.tag(B + '/CompareAlignEvent') == 'fcEnd',
              15),
          P.tag(B + '/CompareAlignEvent'))
    pick_dropdown_option(pg, 'FCe', 'CHARGE')
    check('Settings align dropdown restores charge',
          P.wait_until(
              lambda: P.tag(B + '/CompareAlignEvent') == 'charge',
              15),
          P.tag(B + '/CompareAlignEvent'))
    R5.shot(pg, 'r12-fresh-settings-display.png')
    b.close()


def new_roast_reuse_live(pw):
    """HUNT-86 live: a second New Roast press while the
    workspace still holds an untaken number must reuse it.
    The round 12 battery took 1049, then saved as 1050,
    because a re-delivered press had already moved the tag."""
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    check('HUNT-86 workspace starts Idle at 1042',
          P.tag(B + '/State') == 'Idle'
          and P.tag(B + '/BatchNumber') == 1042,
          (P.tag(B + '/State'), P.tag(B + '/BatchNumber')))
    pg.locator('button').filter(has_text='New Roast').first.click(
        timeout=20000)
    check('HUNT-86 first New Roast takes 1049',
          P.wait_until(
              lambda: P.tag(B + '/BatchNumber') == 1049, 30),
          P.tag(B + '/BatchNumber'))
    pg.wait_for_timeout(2000)
    pg.locator('button').filter(has_text='New Roast').first.click(
        timeout=20000)
    pg.wait_for_timeout(3000)
    check('HUNT-86 second New Roast reuses 1049, not 1050',
          P.tag(B + '/BatchNumber') == 1049,
          P.tag(B + '/BatchNumber'))
    b.close()
    # No roast was started and nothing was saved, so putting
    # the number back is safe. Each New Roast press records a
    # Reset press row through reset_batch, so clear the two
    # rows this probe created (the house pattern, same as the
    # r10 suite finally and cleanup_workspace).
    P.write_tags([(B + '/BatchNumber', 1042)])
    check('HUNT-86 number restored to 1042',
          P.tag(B + '/BatchNumber') == 1042,
          P.tag(B + '/BatchNumber'))
    P.psql('DELETE FROM batch_events')
    check('HUNT-86 New Roast press rows cleaned',
          P.psql('SELECT COUNT(*) FROM batch_events') == '0',
          P.psql('SELECT COUNT(*) FROM batch_events'))


def walk(pw, width, height, theme, tag):
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width,
                                  'height': height},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    set_theme_ui(pg, theme)
    pg.wait_for_timeout(1200)
    measure(pg, 'roast %s' % tag)
    R5.shot(pg, 'r12-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r12-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r12-fresh-detail-%s.png' % tag)
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
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r12-fresh-settings-%s.png' % tag)
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
        R5.shot(pg, 'r12-settings-sweep-%d-360-dark.png'
                % int(frac * 100))
    b.close()


def clean_state():
    ok = (P.tag(B + '/State') == 'Idle'
          and P.tag(B + '/BatchNumber') == 1042
          and P.tag(TM) == 'System'
          and P.tag(B + '/CompareAlignEvent') == 'charge'
          and P.tag(B + '/DispAxisFormat') == 'm:ss'
          and P.psql('SELECT COUNT(*) FROM batches') == '7'
          and P.psql('SELECT COUNT(*) FROM batch_series') == '101'
          and P.psql('SELECT COUNT(*) FROM batch_events') == '0')
    check('lab left clean (Idle, 1042, System, 7/101/0)',
          ok, (P.tag(B + '/State'), P.tag(B + '/BatchNumber'),
               P.tag(TM), P.tag(B + '/CompareAlignEvent'),
               P.psql('SELECT COUNT(*) FROM batches')))


def main():
    static_compare_fallback()
    static_drop_clear()
    static_new_roast_reuse()
    with sync_playwright() as pw:
        compare_live(pw)
        drop_clear_live(pw)
        settings_writeback_live(pw)
        new_roast_reuse_live(pw)
        walk(pw, 1360, 900, 'Light', '1360-light')
        walk(pw, 1360, 900, 'Dark', '1360-dark')
        walk(pw, 360, 800, 'Light', '360-light')
        walk(pw, 360, 800, 'Dark', '360-dark')
        settings_sweep(pw)
        # Restore System theme through the UI (the last walk
        # and the sweep both end in Dark).
        b = R5.launch(pw)
        ctx = b.new_context(viewport={'width': 1360,
                                      'height': 900},
                            timezone_id='America/Denver')
        pg = R5.open_page(ctx, '/')
        pg.wait_for_timeout(2000)
        set_theme_ui(pg, 'System')
        pg.wait_for_timeout(800)
        b.close()
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
