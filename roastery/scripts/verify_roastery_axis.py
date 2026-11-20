#!/usr/bin/env python3
"""Round 3 axis verification (light mode).

The live chart, BatchDetail, and the Log compare must
show TRUE ELAPSED m:ss labels in any browser timezone
(the category axis fix for HUNT-23), and the Settings
axis format choice must switch the labels to mm:ss.
Dark mode is covered by verify_roastery_dark.py.

One phone context drives the roast; desktop contexts
are opened one at a time per timezone and closed after
their screenshot (parallel chart sessions saturate
this VM and stall screenshot calls).

Polish round 6 (HUNT-51): the live and detail datasets
must carry even 30 s labels, so this suite now asserts
every t_label parses as M:SS with total seconds a
multiple of 30, on LiveCurveDS and on DetailDS.
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
    """Poll for the Maker modal for up to ~20 s; it can
    appear well after page load on this build.

    Round 7 hunting: the modal is gone when its AGREE & CLOSE
    button is gone, so that is the check. The old form watched
    the 'Personal Use Only' text count, which never drops below
    1: the page footer carries a permanent
    <div class="secondary-message">Personal Use Only</div>, so
    after the modal closed every iteration found count 1 and
    spent 5 s waiting on a button that no longer exists, 40
    iterations, about 220 s per open_page (proven in the round
    7 delete repro, 2026-11-20). The modal itself closes on
    the first click in under a second; the page is live
    immediately after.
    """
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


def even_labels(ds_value):
    """(ok, labels): every t_label in the dataset parses as
    M:SS with total seconds a multiple of 30 (polish round 6,
    HUNT-51, the even-step axis)."""
    cols, rows = P.ds_rows(ds_value)
    if 't_label' not in cols or not rows:
        return False, []
    li = cols.index('t_label')
    labels = [str(r[li]) for r in rows]
    for lbl in labels:
        try:
            m, s = lbl.split(':')
            total = int(m) * 60 + int(s)
        except Exception:
            return False, labels
        if total % 30 != 0:
            return False, labels
    return True, labels


def main():
    check('lab starts clean', P.tag(B + '/State') == 'Idle')
    P.write_tags([(B + '/DispAxisFormat', 'm:ss'),
                  (TM, 'System')])
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
        # The sim passes 270 F at about 3:35 elapsed.
        P.wait_until(
            lambda: (P.tag(B + '/BeanTempF') or 0) >= 270,
            360)
        ok_live, live_labels = even_labels(
            P.tag('[default]Roastery/LiveCurveDS'))
        check('live curve labels are even 30 s steps',
              ok_live, live_labels)
        for tz in ('America/Denver', 'America/Los_Angeles',
                   'UTC'):
            ctx = b.new_context(
                viewport={'width': 1360, 'height': 900},
                timezone_id=tz)
            page = open_page(ctx, '/')
            page.wait_for_timeout(1500)
            nm = 'axis-tz-%s.png' % tz.split('/')[-1].lower()
            check('tz shot ' + tz, shot(page, nm))
            if tz == 'UTC':
                P.write_tags([(B + '/DispAxisFormat',
                               'mm:ss')])
                page.wait_for_timeout(3500)
                check('mm:ss format shot',
                      shot(page, 'axis-format-mmss.png'))
                P.write_tags([(B + '/DispAxisFormat',
                               'm:ss')])
            ctx.close()
        # Detail and compare in a fresh Denver session.
        ctx = b.new_context(
            viewport={'width': 1360, 'height': 900},
            timezone_id='America/Denver')
        log = open_page(ctx, '/log')
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
        check('detail shot taken',
              'Batch 1044' in log.locator('body').inner_text()
              and shot(log, 'axis-detail-utc.png'))
        ok_det, det_labels = even_labels(
            P.tag('[default]Roastery/DetailDS'))
        check('detail labels are even 30 s steps',
              ok_det, det_labels)
        log2 = open_page(ctx, '/log')
        btn = log2.get_by_role('button', name='Compare').first
        okc = False
        if btn.count() > 0:
            try:
                btn.click(timeout=25000)
                log2.wait_for_timeout(4000)
                okc = shot(log2, 'axis-compare-utc.png')
            except Exception as e:
                print('compare issue:', str(e)[:80],
                      flush=True)
        check('compare shot taken', okc)
        ctx.close()
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
    check('axis format restored',
          P.tag(B + '/DispAxisFormat') == 'm:ss')
    check('theme restored', P.tag(TM) == 'System')
    print()
    if FAILS:
        print('AXIS CHECK FAILURES:', FAILS)
        sys.exit(1)
    print('ALL AXIS CHECKS PASSED')


if __name__ == '__main__':
    main()
