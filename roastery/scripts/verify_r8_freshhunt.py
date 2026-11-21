#!/usr/bin/env python3
"""Round 8 fresh hunting pass (worker C).

Extends verify_r7_freshhunt.py: the same four-page walk
(Roast /, Log /log, BatchDetail /log/detail staged, Settings
/settings) at 1360px and 360px, light and dark, measuring
page-level horizontal overflow and clipped leaf text
(excluding the Perspective footer), plus the new probes
below. One fresh browser per part (the round 5 hunt2
lesson: never two contexts in one single-process browser).

New in round 8:
  1. A live roast at 360px light, measured at every stage
     (Charge, Dry End, FC Start, Drop) with a staged ghost
     mid-roast: the round 7 walk was Idle only, so stamped
     events, the phase bar with real durations, the analyzer
     with real data and the ghost overlay were never measured
     at phone width.
  2. The saved roast's detail (a real multi-event curve, not
     the 19 s stub 1042) at 360px dark, then delete through
     the Log UI.
  3. Log compare at 360px dark and 1360px dark (round 7 did
     360px light only), and the phone 'All columns' toggle.
  4. AppSettings dock at 360px dark (round 7 did light only).
  5. Settings mid/bottom scroll captures at 1360px light and
     360px dark (round 7 did 360px light only).
  6. Settings write/read-back on RoRSmoothingSec (round 7
     did RoRDeltaSpanSec).
  7. A no-curve batch (created through the New Batch form,
     no series rows): the compare caption probe for HUNT-61.
     Informational only: compare_dataset silently omits a
     batch with no points, so the caption never names it;
     the probe records the caption as evidence and the
     HUNT item is filed from it, the suite stays green.
  8. Static HUNT-59 proof, no gateway needed: the repo
     builder's _custom_binding emits config-level
     bidirectional, and the emitted binding deep-equals the
     live BatchesPanel CmpA binding.

Does NOT retest the timezone TIME axis passthrough or
HUNT-46 (both beta-gated, pending the next Ignition beta)
and does NOT touch the press path (HUNT-53 app fix out of
scope). Leaves the lab clean.
"""
import json
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P
import verify_r5_detail_span as R5
from playwright.sync_api import sync_playwright

B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'
BG_LABEL = '[default]Roastery/BackgroundLabel'
BG_CURVE = '[default]Roastery/BackgroundCurveJson'
REPO_BUILDER = ('/home/hatch/workspace/ignition-coffee-lab/'
                'roastery/scripts/build_roastery_v4.py')
REPO_PANEL = ('/home/hatch/workspace/ignition-coffee-lab/'
              'roastery/project/Roastery/com.inductiveautomation.'
              'perspective/views/Views/BatchesPanel/view.json')
# The batch number the live roast saves under (next after the
# seeded max at suite start; a fixture from a concurrent
# worker would move it, so never hardcode 1049).
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
    // The Perspective client footer (.secondary-message:
    // the page URL and 'Personal Use Only') is platform
    // chrome below the fold, not app content; its long URL
    // is clipped by overflow hidden on every page and is
    // not an app defect, so it is excluded here.
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


def scroll_settings(pg, frac, name):
    """Scroll the Settings inner container (.psc-roast-content,
    round 7: window.scrollTo is a no-op here) and shoot."""
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
    R5.shot(pg, name)


def caption_texts(pg):
    return pg.evaluate(
        """() => [...document.querySelectorAll(
        '[data-component="ia.display.label"]')].map(
        e => e.textContent.trim()).filter(
        t => t.includes('A = Batch'))""")


def click_btn(pg, name, timeout=20000):
    pg.locator('button').filter(has_text=name).first.click(
        timeout=timeout)


def static_hunt59():
    """HUNT-59: the repo builder's _custom_binding must emit
    config-level bidirectional, matching the live view.
    The builder module cannot be imported whole (it loads
    schema files relative to its own tree at import time),
    so the single function is extracted by AST from the
    repo file and executed standalone: it has no
    dependencies."""
    import ast
    src = open(REPO_BUILDER).read()
    tree = ast.parse(src)
    node = None
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) \
                and n.name == '_custom_binding':
            node = n
            break
    assert node is not None, '_custom_binding not found'
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 REPO_BUILDER, 'exec'), ns)
    emitted = ns['_custom_binding']('cmpA')
    cfg = (emitted.get('binding') or {}).get('config') or {}
    check('HUNT-59 builder emits config bidirectional',
          cfg.get('bidirectional') is True, emitted)
    check('HUNT-59 builder keeps binding-level copy',
          (emitted.get('binding') or {}).get('bidirectional')
          is True, emitted)
    view = json.load(open(REPO_PANEL))

    def find(n, name):
        if isinstance(n, dict):
            if n.get('meta', {}).get('name') == name:
                return n
            for ch in n.values():
                r = find(ch, name)
                if r:
                    return r
        elif isinstance(n, list):
            for c in n:
                r = find(c, name)
                if r:
                    return r
        return None

    live = find(view, 'CmpA')['propConfig']['props.value'][
        'binding']
    check('HUNT-59 builder binding equals live CmpA binding',
          emitted['binding'] == live,
          'emitted=%s live=%s' % (emitted['binding'], live))


def walk(pw, width, height, theme, tag):
    """One viewport/theme combo across the four pages."""
    P.write_tags([(TM, theme)])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': width,
                                  'height': height},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/')
    pg.wait_for_timeout(2000)
    measure(pg, 'roast %s' % tag)
    R5.shot(pg, 'r8-fresh-roast-%s.png' % tag)
    pg2 = R5.open_page(ctx, '/log')
    pg2.wait_for_timeout(1500)
    measure(pg2, 'log %s' % tag)
    R5.shot(pg2, 'r8-fresh-log-%s.png' % tag)
    R5.stage_one(1042)
    pg3 = R5.open_page(ctx, '/log/detail')
    pg3.wait_for_timeout(2500)
    measure(pg3, 'detail %s' % tag)
    R5.shot(pg3, 'r8-fresh-detail-%s.png' % tag)
    # Concurrent workers stage detail batches too (round 5
    # lesson): if a foreign stage swapped the selection
    # mid-page, restage and retake once.
    if P.tag('[default]Roastery/SelectedBatchNumber') != 1042:
        print('detail stage stolen mid-walk, retaking', tag,
              flush=True)
        R5.stage_one(1042)
        pg3 = R5.open_page(ctx, '/log/detail')
        pg3.wait_for_timeout(2500)
        measure(pg3, 'detail %s retry' % tag)
        R5.shot(pg3, 'r8-fresh-detail-%s.png' % tag)
    pg4 = R5.open_page(ctx, '/settings')
    pg4.wait_for_timeout(1500)
    measure(pg4, 'settings %s' % tag)
    R5.shot(pg4, 'r8-fresh-settings-%s.png' % tag)
    if tag in ('1360-light', '360-dark'):
        scroll_settings(pg4, 0.5,
                        'r8-fresh-settings-mid-%s.png' % tag)
        scroll_settings(pg4, 1.0,
                        'r8-fresh-settings-bottom-%s.png' % tag)
    b.close()


def live_roast_360(pw):
    """Probe 1: a full roast at 360px light, measured at
    every stage, ghost staged mid-roast, saved as the next
    batch number for the detail probe. Uses the press path
    through the UI only; never modifies it."""
    P.write_tags([(TM, 'Light')])
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
        measure(pg, 'roast live 360-light')
        R5.shot(pg, 'r8-fresh-roast-live-360-light.png')
        click_btn(pg, 'Dry End')
        check('dry end stamps', P.wait_until(
            lambda: (P.tag(B + '/DryEndElapsedSec') or -1) >= 0,
            30))
        pg.wait_for_timeout(3000)
        measure(pg, 'roast dry-end 360-light')
        click_btn(pg, 'FC Start')
        check('fc start stamps', P.wait_until(
            lambda: (P.tag(B + '/FirstCrackStartElapsedSec')
                     or -1) >= 0, 30))
        pg.wait_for_timeout(3000)
        # Ghost mid-roast: the overlay only draws on a live
        # timeline (round 7), so stage it here, not at Idle.
        P.write_tags([
            (BG_LABEL, 'Ethiopia Guji (test)'),
            (BG_CURVE, '[[0, 200], [60, 250], [120, 300], '
             '[180, 350], [240, 380]]')])
        pg.wait_for_timeout(3000)
        body = pg.locator('body').inner_text()
        check('background label shows mid-roast',
              'Ethiopia Guji (test)' in body, body[:120])
        measure(pg, 'roast ghost live 360-light')
        R5.shot(pg, 'r8-fresh-roast-ghost-live-360-light.png')
        P.write_tags([(BG_LABEL, ''), (BG_CURVE, '')])
        click_btn(pg, 'Drop')
        check('drop ends the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Dropped', 30))
        pg.wait_for_timeout(2000)
        measure(pg, 'roast dropped 360-light')
        R5.shot(pg, 'r8-fresh-roast-dropped-360-light.png')
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
    # Slot-safe cleanup (HUNT-53): drain_pending waits for
    # every slotted press to land and clears the ring first,
    # so the reconciler cannot resurrect the deleted rows.
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('live roast leaves no press rows',
          P.psql('SELECT COUNT(*) FROM batch_events') == '0')


def detail_and_delete(pw):
    """Probe 2: the saved roast's detail at 360px dark, then
    delete it through the Log UI."""
    nxt = NEXT_BATCH[0]
    label = format(nxt, ',')
    P.write_tags([(TM, 'Dark')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    R5.stage_one(nxt)
    pg = R5.open_page(ctx, '/log/detail')
    pg.wait_for_timeout(2500)
    measure(pg, 'detail %d 360-dark' % nxt)
    R5.shot(pg, 'r8-fresh-detail-%d-360-dark.png' % nxt)
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


def compare_and_dock(pw):
    """Probes 3-4: compare at 360px dark and 1360px dark, the
    phone All columns toggle, and the AppSettings dock at
    360px dark."""
    P.write_tags([(TM, 'Dark')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 360, 'height': 800},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = caption_texts(pg)
    check('compare caption lists A and B at 360 dark',
          any('A = Batch' in c and 'B = Batch' in c
              for c in caps), caps)
    measure(pg, 'compare 360-dark')
    R5.shot(pg, 'r8-fresh-compare-360-dark.png')
    pg.get_by_role('button', name='All columns').first.click(
        timeout=10000)
    pg.wait_for_timeout(1500)
    measure(pg, 'log all-columns 360-dark')
    R5.shot(pg, 'r8-fresh-log-allcols-360-dark.png')
    pg2 = R5.open_page(ctx, '/')
    pg2.wait_for_timeout(2000)
    gear = pg2.locator('.psc-roast-gear-btn:visible').first
    try:
        gear.click(timeout=10000)
        pg2.wait_for_timeout(2500)
        m = pg2.evaluate(OVERFLOW_JS)
        check('appsettings dock no horizontal overflow dark',
              m['docW'] <= m['vw'], m)
        check('appsettings dock no clipped leaf text dark',
              m['nClipped'] == 0, m['clipped'])
        R5.shot(pg2, 'r8-fresh-appsettings-360-dark.png')
    except Exception as e:
        check('appsettings dock opens at 360px dark', False,
              str(e)[:150])
    b.close()
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    measure(pg, 'compare 1360-dark')
    R5.shot(pg, 'r8-fresh-compare-1360-dark.png')
    b.close()


def settings_writeback(pw):
    """Probe 6: Settings write/read-back on RoRSmoothingSec
    (round 7 did RoRDeltaSpanSec)."""
    before = P.tag(B + '/RoRSmoothingSec')
    P.write_tags([(B + '/RoRSmoothingSec', 45)])
    check('ror smoothing write reads back',
          P.tag(B + '/RoRSmoothingSec') == 45,
          P.tag(B + '/RoRSmoothingSec'))
    P.write_tags([(B + '/RoRSmoothingSec', before)])
    check('ror smoothing restore reads back',
          P.tag(B + '/RoRSmoothingSec') == before,
          P.tag(B + '/RoRSmoothingSec'))


def no_curve_probe(pw):
    """Probe 7 (HUNT-61 evidence, informational): create a
    batch through the New Batch form (no series rows), pick
    it as C, Compare, and record whether the caption names
    it. compare_dataset skips batches with no points, so
    the caption is expected to omit it silently."""
    P.write_tags([(TM, 'Light')])
    b = R5.launch(pw)
    ctx = b.new_context(viewport={'width': 1360, 'height': 900},
                        timezone_id='America/Denver')
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='New Batch').first.click(
        timeout=20000)
    pg.wait_for_timeout(3500)
    # The editor is a docked view now (not the v3 popup), so
    # the fields are scoped by the form field class, not by
    # .ia_popup. Order: BatchNumber, BeanName, Origin,
    # Region, Farm, ...
    fields = pg.locator(
        'input.ia_form__field, textarea.ia_form__field')
    fields.nth(0).fill('1050')
    fields.nth(1).fill('R8 NoCurve')
    fields.nth(0).press('Tab')
    pg.wait_for_timeout(600)
    pg.get_by_role('button', name='Save Batch').first.click(
        timeout=20000)
    pg.wait_for_timeout(2000)
    check('no-curve batch created',
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = 1050') == '1')
    check('no-curve batch has no series rows',
          P.psql('SELECT COUNT(*) FROM batch_series WHERE '
                 'batch_number = 1050') == '0')
    check('create note names the batch',
          pg.get_by_text('Created batch 1050.').count() >= 1)
    pg.get_by_role('button', name='Cancel').first.click(
        timeout=20000)
    pg.wait_for_timeout(1500)
    # Fresh page: the compare pickers fill at onStartup, so
    # the new batch is only an option after a reload.
    pg = R5.open_page(ctx, '/log')
    pg.wait_for_timeout(1500)
    dds = pg.locator('[data-component="ia.input.dropdown"]')
    dds.nth(2).click(timeout=20000)
    pg.wait_for_timeout(900)
    pg.locator('a.iaDropdownCommon_option',
               has_text='Batch 1050').first.click(timeout=20000)
    pg.wait_for_timeout(1500)
    pg.get_by_role('button', name='Compare').first.click(
        timeout=20000)
    pg.wait_for_timeout(4000)
    caps = caption_texts(pg)
    print('HUNT-61 caption:', caps, flush=True)
    print('HUNT-61 batch 1050 named in caption:',
          any('1050' in c for c in caps), flush=True)
    pg.locator('text=1,050').first.click(timeout=25000)
    pg.wait_for_timeout(1200)
    pg.get_by_role('button', name='Delete').first.click(
        timeout=25000)
    pg.wait_for_timeout(1000)
    pg.get_by_role('button',
                   name='Confirm Delete').first.click(
                       timeout=25000)
    pg.wait_for_timeout(2500)
    check('no-curve batch deletes through the Log UI',
          P.psql('SELECT COUNT(*) FROM batches WHERE '
                 'batch_number = 1050') == '0')
    b.close()


def main():
    static_hunt59()
    state = P.tag(B + '/State')
    check('lab starts clean', state == 'Idle', state)
    if state != 'Idle':
        # Another worker is mid-roast: the walk would flip
        # their session theme and the live probes would
        # fight their roast. Bail out cleanly instead of
        # burning a run and contaminating theirs.
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
            walk(pw, 1360, 900, 'Light', '1360-light')
            walk(pw, 1360, 900, 'Dark', '1360-dark')
            walk(pw, 360, 800, 'Light', '360-light')
            walk(pw, 360, 800, 'Dark', '360-dark')
            live_roast_360(pw)
            detail_and_delete(pw)
            compare_and_dock(pw)
            settings_writeback(pw)
            no_curve_probe(pw)
    finally:
        # Emergency path: a mid-run exception (a click
        # timeout, a gateway blip) must not leave fixtures
        # or press rows behind. Slot-safe first (HUNT-53):
        # drain_pending clears the ring, then the rows go,
        # then any fixture batches this suite created.
        # Idempotent: a clean run deletes nothing here.
        try:
            P.write_tags([(TM, 'System')])
            P.drain_pending()
            P.psql('DELETE FROM batch_events')
            if NEXT_BATCH[0]:
                P.psql('DELETE FROM batches WHERE '
                       'batch_number = %d' % NEXT_BATCH[0])
            P.psql('DELETE FROM batches WHERE '
                   'batch_number = 1050')
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
    print()
    print('PASSES:', PASSES[0])
    print('FAILURES:', FAILS if FAILS else 'none')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
