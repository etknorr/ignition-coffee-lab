#!/usr/bin/env python3
"""Polish round 4 hunt, part E: Settings scroll through at
360px via the page's inner scroll container (window.scrollTo
does not move Perspective pages, which parts B and C
learned), a desktop Settings pass, and the end state
PressEvents proof.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import os
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P

BASE = P.BASE
SHOTS = P.SHOTS
B = P.B


def dismiss(page):
    """Dismiss the Maker 'Personal Use Only' agreement modal.

    Round 7 hunting: the modal is gone when its AGREE & CLOSE
    button is gone, so that is the check. The old form watched
    the 'Personal Use Only' text count, which never drops below
    1: the page footer carries a permanent
    <div class="secondary-message">Personal Use Only</div>, so
    after the modal closed every iteration found count 1 and
    spent 5 s waiting on a button that no longer exists, 30
    iterations, about 165 s per open_page (proven in the round
    7 delete repro, 2026-11-20). The modal itself closes on
    the first click in under a second; the page is live
    immediately after.
    """
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


def open_page(ctx, path):
    pg = ctx.new_page()
    pg.goto(BASE + path, wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    dismiss(pg)
    pg.wait_for_timeout(1500)
    return pg


def shot(pg, name):
    try:
        pg.screenshot(path=os.path.join(SHOTS, name),
                      timeout=30000)
        print('shot', name, flush=True)
    except Exception as e:
        print('shot issue', name, str(e)[:90], flush=True)


SCROLL_JS = """(top) => {
  const els = [...document.querySelectorAll('*')].filter(
    e => e.scrollHeight > e.clientHeight + 40
         && e.clientHeight > 200);
  els.sort((a, b) => b.scrollHeight - a.scrollHeight);
  const el = els[0];
  if (!el) return null;
  el.scrollTop = top;
  return {sh: el.scrollHeight, ch: el.clientHeight,
          st: el.scrollTop,
          cls: (el.className || '').slice(0, 60)};
}"""


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        mob = browser.new_context(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver')
        pg = open_page(mob, '/settings')
        info = pg.evaluate(SCROLL_JS, 0)
        print('scroll container:', info, flush=True)
        total = (info or {}).get('sh', 4000)
        step = 0
        for frac, name in ((0.22, 'r4hunt-settings-360-s1.png'),
                           (0.45, 'r4hunt-settings-360-s2.png'),
                           (0.68, 'r4hunt-settings-360-s3.png'),
                           (0.92, 'r4hunt-settings-360-s4.png')):
            r = pg.evaluate(SCROLL_JS, int(total * frac))
            pg.wait_for_timeout(1300)
            print('scrolled to', r, flush=True)
            shot(pg, name)
            step += 1
        geo = pg.evaluate("""() => {
          const out = {};
          out.tables = [...document.querySelectorAll(
            '[data-component="ia.display.table"]')].map(e => ({
              sw: e.scrollWidth, cw: e.clientWidth}));
          out.checkboxLabels = [...document.querySelectorAll(
            '[data-component="ia.input.checkbox"]')].map(
              e => (e.innerText || '').trim()).filter(t => t);
          const body = document.body.innerText;
          out.hasDisplay = body.includes('DISPLAY')
            || body.includes('Display');
          out.hasAlarms = body.includes('ALARMS')
            || body.includes('Alarms');
          out.hasCustom = body.includes('CUSTOM');
          out.hasRor = body.includes('RATE OF RISE')
            || body.includes('RoR');
          return out;
        }""")
        print('settings content probe:', geo, flush=True)
        mob.close()
        desk = browser.new_context(
            viewport={'width': 1360, 'height': 900},
            timezone_id='America/Denver')
        dp = open_page(desk, '/settings')
        shot(dp, 'r4hunt-settings-desktop-top.png')
        info = dp.evaluate(SCROLL_JS, 1500)
        dp.wait_for_timeout(1300)
        shot(dp, 'r4hunt-settings-desktop-mid.png')
        print('desktop scroll:', info, flush=True)
        desk.close()
        browser.close()

    # ---- PressEvents end state proof ----
    P.probe_setup()
    try:
        P.probe('reset')
        P.wait_until(lambda: P.tag(B + '/State') == 'Idle', 30)
        time.sleep(2)
        base = int(P.psql('SELECT COUNT(*) FROM batch_events'))
        P.probe('charge')
        ok = P.wait_until(
            lambda: int(P.psql(
                'SELECT COUNT(*) FROM batch_events')) > base,
            25)
        print('PressEvents wrote the Charge row:', bool(ok),
              flush=True)
        P.probe('reset')
        P.wait_until(lambda: P.tag(B + '/State') == 'Idle', 30)
        P.drain_pending()
        P.psql('DELETE FROM batch_events')
    finally:
        P.probe_teardown()
    end = (int(P.psql('SELECT COUNT(*) FROM batches')),
           int(P.psql('SELECT COUNT(*) FROM batch_series')),
           int(P.psql('SELECT COUNT(*) FROM batch_events')))
    print('final counts:', end, flush=True)
    print('final tags: State=%s Batch=%s Fan=%s Heat=%s '
          'Theme=%s Fmt=%s Periscope=%s Seeking=%s Pause=%s '
          'SlotsCleared=%s' % (
              P.tag(B + '/State'), P.tag(B + '/BatchNumber'),
              P.tag(B + '/FanLevel'), P.tag(B + '/HeatLevel'),
              P.tag('[default]Roastery/AppSettings/ThemeMode'),
              P.tag(B + '/DispAxisFormat'),
              P.tag('[default]Roastery/AppSettings/'
                    'PeriscopeAvailable'),
              P.tag(B + '/SimSeeking'),
              P.tag('[default]Roastery/SimPause'),
              all(not P.tag('[default]Roastery/PressSlots/'
                            'Slot%02d' % i) for i in range(16))),
          flush=True)
    print('PART E DONE', flush=True)


if __name__ == '__main__':
    main()
