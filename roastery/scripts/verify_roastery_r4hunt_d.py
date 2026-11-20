#!/usr/bin/env python3
"""Polish round 4 hunt, part D: focused probe of the
file upload modal and the Settings background failure
toast (follow up to part B, where the toast poll missed
and a component modal overlay blocked later clicks).

On Settings at 360px: click the Background fileupload,
watch the modal, set a bad .alog, poll for Toastify
toasts every 300 ms for 25 s from the moment the file is
set, then try to dismiss the component modal (backdrop
click, Escape, in modal buttons) and record what works.
Then the same toast timing on the Log page import for
comparison.

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


def toast_texts(page):
    loc = page.locator('.Toastify__toast')
    out = []
    for i in range(loc.count()):
        try:
            out.append(loc.nth(i).inner_text())
        except Exception:
            pass
    return out


def modal_state(page):
    return page.evaluate("""() => {
      const m = document.querySelector(
        '.ia_componentModal--fullViewOverlay');
      if (!m) return null;
      const r = m.getBoundingClientRect();
      const btns = [...m.querySelectorAll('button')].map(
        b => b.innerText.trim().slice(0, 20));
      return {x: r.x, y: r.y, w: r.width, h: r.height,
              text: (m.innerText || '').slice(0, 120),
              buttons: btns};
    }""")


def poll_toasts(page, seconds=25):
    hits = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        ts = toast_texts(page)
        if ts:
            hits.append((round(time.time() - t0, 1), ts))
            if len(hits) >= 3:
                break
        page.wait_for_timeout(300)
    return hits


def main():
    with open('/tmp/r4hunt-bad3.alog', 'w') as f:
        f.write('this is not an alog file')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        mob = browser.new_context(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver')
        pg = open_page(mob, '/settings')
        pg.evaluate('window.scrollTo(0, 2400)')
        pg.wait_for_timeout(1500)
        comp = pg.locator(
            '[data-component="ia.input.fileupload"]').first
        comp.scroll_into_view_if_needed()
        pg.wait_for_timeout(800)
        comp.click(timeout=8000)
        pg.wait_for_timeout(1500)
        print('modal after click:', modal_state(pg), flush=True)
        shot(pg, 'r4hunt-upload-modal-open-360.png')
        pg.locator('input[type="file"]').last.set_input_files(
            '/tmp/r4hunt-bad3.alog')
        hits = poll_toasts(pg, 25)
        print('SETTINGS toast hits:', hits, flush=True)
        shot(pg, 'r4hunt-upload-after-bad-360.png')
        print('modal after upload:', modal_state(pg), flush=True)
        print('bg note area text present:',
              'Background failed' in pg.locator(
                  'body').inner_text(), flush=True)
        # dismissal attempts
        pg.mouse.click(180, 60)
        pg.wait_for_timeout(1000)
        print('modal after backdrop tap:', modal_state(pg),
              flush=True)
        if modal_state(pg):
            pg.keyboard.press('Escape')
            pg.wait_for_timeout(1000)
            print('modal after Escape:', modal_state(pg),
                  flush=True)
        if modal_state(pg):
            btns = pg.locator(
                '.ia_componentModal--fullViewOverlay button')
            print('modal button count:', btns.count(),
                  flush=True)
            for i in range(btns.count()):
                try:
                    print(' modal btn', i,
                          repr(btns.nth(i).inner_text()[:30]),
                          flush=True)
                except Exception:
                    pass
        shot(pg, 'r4hunt-upload-modal-dismiss-360.png')

        # ---- Log page comparison ----
        pg2 = open_page(mob, '/log')
        comp2 = pg2.locator(
            '[data-component="ia.input.fileupload"]').first
        comp2.scroll_into_view_if_needed()
        pg2.wait_for_timeout(800)
        try:
            comp2.click(timeout=8000)
        except Exception as e:
            print('log upload click issue', str(e)[:80],
                  flush=True)
        pg2.wait_for_timeout(1200)
        print('log modal after click:', modal_state(pg2),
              flush=True)
        with open('/tmp/r4hunt-bad4.alog', 'w') as f:
            f.write('also not an alog file')
        pg2.locator('input[type="file"]').last.set_input_files(
            '/tmp/r4hunt-bad4.alog')
        hits2 = poll_toasts(pg2, 25)
        print('LOG toast hits:', hits2, flush=True)
        shot(pg2, 'r4hunt-upload-log-after-bad-360.png')
        print('log modal after upload:', modal_state(pg2),
              flush=True)
        mob.close()
        browser.close()
    print('PART D DONE', flush=True)


if __name__ == '__main__':
    main()
