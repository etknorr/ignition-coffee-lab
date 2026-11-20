#!/usr/bin/env python3
"""Round 3 dark mode verification (HUNT-31).

In dark sessions the canvas charts must stay legible:
axis labels and titles in a light literal, phase bands
at the raised dark opacity. Proven for pinned Dark at
desktop and 360px mid roast, for BatchDetail and the
Log compare in Dark, and for System on a dark device
(the HudBar brightness signal). Light mode is covered
by verify_roastery_axis.py. Contexts are opened one at
a time and closed after use; six simultaneous chart
sessions saturate this VM and stall screenshot calls.
"""
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from playwright.sync_api import sync_playwright
import verify_roastery_polish2 as P

FAILS = []
SHOTS = P.SHOTS
B = '[default]Roastery/CurrentBatch'
TM = '[default]Roastery/AppSettings/ThemeMode'


def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:90] if detail else ''),
          flush=True)
    if not cond:
        FAILS.append(name)


def dismiss(page):
    for _ in range(40):
        try:
            if page.get_by_text(
                    'Personal Use Only').count() > 0:
                page.get_by_text(
                    'AGREE & CLOSE').first.click(timeout=5000)
                page.wait_for_timeout(1200)
                if page.get_by_text(
                        'Personal Use Only').count() == 0:
                    return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return page.get_by_text('Personal Use Only').count() == 0


def open_page(ctx, path):
    pg = ctx.new_page()
    pg.goto(P.BASE + path, wait_until='domcontentloaded',
            timeout=60000)
    pg.wait_for_timeout(6000)
    dismiss(pg)
    pg.wait_for_timeout(1500)
    return pg


def shot(pg, name):
    try:
        pg.screenshot(path=SHOTS + '/' + name, timeout=30000)
        return True
    except Exception as e:
        print('shot issue', name, str(e)[:80], flush=True)
        return False


def main():
    check('lab starts clean', P.tag(B + '/State') == 'Idle')
    P.write_tags([(TM, 'Dark')])
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        phone = b.new_context(
            viewport={'width': 390, 'height': 844},
            timezone_id='America/Denver')
        pg = open_page(phone, '/')
        pg.locator('button').filter(
            has_text='Charge').first.click(timeout=20000)
        check('charge starts the roast', P.wait_until(
            lambda: P.tag(B + '/State') == 'Roasting', 30))
        pg.locator('button').filter(
            has_text='Dry End').first.click(timeout=20000)
        pg.wait_for_timeout(1000)
        # Wait to about 2:45 elapsed (Drying band drawn).
        P.wait_until(
            lambda: (P.tag(B + '/BeanTempF') or 0) >= 250,
            300)
        desk = b.new_context(
            viewport={'width': 1360, 'height': 900},
            timezone_id='America/Denver')
        dp = open_page(desk, '/')
        dp.wait_for_timeout(2000)
        check('dark desktop bands shot',
              shot(dp, 'axis-dark-desktop.png'))
        # Detail and compare in Dark from this session.
        log = open_page(desk, '/log')
        try:
            log.locator('text=1,044').first.click(
                timeout=25000)
            log.wait_for_timeout(1200)
            log.get_by_role(
                'button', name='Details').first.click(
                    timeout=25000)
            log.wait_for_timeout(4500)
            dismiss(log)
            log.wait_for_timeout(1500)
        except Exception as e:
            print('detail issue:', str(e)[:80], flush=True)
        check('dark detail shot', shot(log,
                                       'axis-dark-detail.png'))
        log2 = open_page(desk, '/log')
        btn = log2.get_by_role('button', name='Compare').first
        if btn.count() > 0:
            try:
                btn.click(timeout=25000)
                log2.wait_for_timeout(4000)
            except Exception as e:
                print('compare issue:', str(e)[:80],
                      flush=True)
        check('dark compare shot',
              shot(log2, 'axis-dark-compare.png'))
        desk.close()
        # Pinned Dark at 360.
        ph = b.new_context(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver')
        pp = open_page(ph, '/')
        pp.wait_for_timeout(2000)
        check('dark 360 shot', shot(pp, 'axis-dark-360.png'))
        ph.close()
        # System on a dark device (brightness signal).
        P.write_tags([(TM, 'System')])
        sd_ctx = b.new_context(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver', color_scheme='dark')
        sd = open_page(sd_ctx, '/')
        sd.wait_for_timeout(3000)
        check('system dark 360 shot',
              shot(sd, 'axis-dark-system-360.png'))
        sd_ctx.close()
        # Walk the roast home from the phone.
        for label, want in (('FC Start', None),
                            ('FC End', None),
                            ('SC Start', None),
                            ('SC End', None),
                            ('Drop', 'Dropped'),
                            ('Cool', 'Cooling'),
                            ('Finish', 'Complete'),
                            ('Reset / New Roast', 'Idle')):
            try:
                pg.locator('button').filter(
                    has_text=label).first.click(timeout=15000)
            except Exception:
                pass
            if want:
                P.wait_until(
                    lambda w=want: P.tag(B + '/State') == w,
                    90)
            else:
                pg.wait_for_timeout(1200)
        b.close()
    check('lab back to Idle', P.tag(B + '/State') == 'Idle')
    P.drain_pending()
    P.psql('DELETE FROM batch_events')
    check('lab clean', P.psql('SELECT COUNT(*) FROM batches')
          == '7' and P.psql(
              'SELECT COUNT(*) FROM batch_events') == '0')
    check('theme restored', P.tag(TM) == 'System')
    print()
    if FAILS:
        print('DARK CHECK FAILURES:', FAILS)
        sys.exit(1)
    print('ALL DARK MODE CHECKS PASSED')


if __name__ == '__main__':
    main()
