#!/usr/bin/env python3
"""Polish round 4, HUNT-35: deleting a Roastery batch cascades
to its batch_events press rows.

Decision under test: the saved batch document already
snapshots the press events at save time, and no surface reads
batch_events rows for a batch that no longer exists, so
orphaned rows are pure leftovers and the delete cascades. A
schema level FK cascade is NOT viable: press rows are written
during a roast for a batch_number that has no row in batches
until Save Batch, so an FK from batch_events to batches would
break live press capture. The cascade therefore lives in the
delete flow: roastery.batches.delete_batch runs the named
query Roastery/Events/DeleteByBatch first, then
Roastery/Batches/Delete (batch_series has a real FK ON
DELETE CASCADE and needs no explicit delete).

Proof shape:
- Fixtures by direct DB inserts that mimic a saved batch: a
  delete target (batch row, series rows, press rows with
  press_counter values), a control batch with its own series
  and press rows, and press rows for a batch number with NO
  batches row (the live roast case).
- The delete is driven through the real Log page UI: select
  the fixture row, Delete, read the confirm note (it must
  name the press log alongside the curve), Confirm Delete,
  see the deleted note.
- After the delete: the target's batch row, series rows and
  press rows are all gone; the control batch is untouched.
- The no FK property: the unsaved number's press rows survive
  another batch's delete, and a new press row for a number
  with no batches row can still be inserted afterwards.
- Cleanup removes the fixtures completely; the lab ends at
  7 batches / 101 series / 0 events, workspace Idle with
  defaults (BatchNumber 1042, Fan 5, Heat 5).

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8088/data/perspective/client/Roastery'
SHOTS = '/home/hatch/workspace/ignition-lab/showcase/shots'
B = '[default]Roastery/CurrentBatch'
FIX = 9911
CTRL = 9912
LIVE = 9913
NEWLIVE = 9914
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:260]) if detail else '', flush=True)
    if not cond:
        FAILURES.append(label)


def read_tags(paths):
    st, out = api('GET', '/tags/read', body=json.dumps(
        {'tags': paths}))
    assert st == 200, (st, out)
    return [r['value'] for r in out['results']]


def tag(path):
    return read_tags([path])[0]


def write_tags(pairs):
    st, out = api('POST', '/tags/write', body=json.dumps(
        {'tagPaths': [p for p, v in pairs],
         'values': [v for p, v in pairs]}))
    assert st == 200, (st, out)


def wait_until(fn, timeout=30, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def psql(sql):
    pw = open('/home/hatch/workspace/ignition-lab/'
              '.roastery-pgpass').read().strip()
    env = dict(os.environ, PGPASSWORD=pw,
               PATH=os.environ['PATH'] + ':/usr/lib/postgresql/16/bin')
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', sql], capture_output=True, text=True,
        env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def counts():
    return (int(psql('SELECT COUNT(*) FROM batches')),
            int(psql('SELECT COUNT(*) FROM batch_series')),
            int(psql('SELECT COUNT(*) FROM batch_events')))


def count_for(table, number):
    return int(psql('SELECT COUNT(*) FROM %s WHERE batch_number = %d'
                    % (table, number)))


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(
                timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


def fixture_doc(number, bean):
    """A saved batch document in the shape build_document
    writes, including the save time snapshot of the press
    events (the fan and heat trace): the reason orphaned
    batch_events rows carry no unique information."""
    return json.dumps({
        'batchNumber': number, 'beanName': bean,
        'roastDegree': 'City', 'totalSec': 120,
        'phases': {'dryingSec': 60, 'maillardSec': 40,
                   'developmentSec': 20, 'dtrPct': 16.7},
        'events': {
            'charge': {'t': 0, 'tempF': 400.0},
            'dryEnd': {'t': 60, 'tempF': 320.0},
            'drop': {'t': 120, 'tempF': 415.0}, 'custom': []},
        'fanHeatTrace': [
            {'t': 10.0, 'label': 'Fan +1', 'fan': 6.0, 'heat': 5.0},
            {'t': 30.0, 'label': 'Heat +1', 'fan': 6.0, 'heat': 6.0}],
        'metadata': {}})


def insert_fixtures():
    for number, bean, n_series, actions in (
            (FIX, 'Delete Cascade Fixture', 3,
             ['Charge', 'Dry End', 'Fan +1', 'Drop']),
            (CTRL, 'Delete Cascade Control', 2,
             ['Charge', 'Dry End', 'Drop'])):
        psql("INSERT INTO batches (batch_number, roast_start, "
             "roast_end, bean_name, drop_temp_f, data) VALUES "
             "(%d, now(), now(), '%s', 415.0, '%s'::jsonb)"
             % (number, bean, fixture_doc(number, bean)))
        for i in range(n_series):
            psql("INSERT INTO batch_series (batch_number, "
                 "t_offset_sec, sample_ts, bean_temp_f, "
                 "rate_of_rise_f, fan_level, heat_level) VALUES "
                 "(%d, %d, now(), %s, 10.0, 5, 5)"
                 % (number, i * 10, 300.0 + i * 10))
        for i, action in enumerate(actions):
            psql("INSERT INTO batch_events (batch_number, action, "
                 "t_offset_sec, bean_temp_f, rate_of_rise_f, "
                 "fan_level, heat_level, press_counter) VALUES "
                 "(%d, '%s', %d, 350.0, 10.0, 5, 5, %d)"
                 % (number, action, i * 10, i + 1))
    # Live roast case: press rows for a number that has no
    # batches row at all (captured before Save Batch).
    for i, action in enumerate(['Charge', 'Dry End']):
        psql("INSERT INTO batch_events (batch_number, action, "
             "t_offset_sec, bean_temp_f, rate_of_rise_f, "
             "fan_level, heat_level, press_counter) VALUES "
             "(%d, '%s', %d, 350.0, 10.0, 5, 5, %d)"
             % (LIVE, action, i * 10, i + 1))


def wipe_fixtures():
    psql('DELETE FROM batch_events WHERE batch_number IN '
         '(%d, %d, %d, %d)' % (FIX, CTRL, LIVE, NEWLIVE))
    psql('DELETE FROM batches WHERE batch_number IN (%d, %d)'
         % (FIX, CTRL))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = counts()
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    ws0 = read_tags([B + '/BatchNumber', B + '/State',
                     B + '/FanLevel', B + '/HeatLevel'])
    check('workspace starts Idle with defaults',
          ws0 == [1042, 'Idle', 5, 5], ws0)
    sel0 = tag('[default]Roastery/SelectedBatchNumber')

    # The new named query is live: the validator counts the
    # resources under the gateway project tree; do the same
    # walk here before any behavior testing.
    nq_root = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker'
               '/data/projects/Roastery/ignition/named-query/Roastery')
    nq_names = []
    for dp, _dn, fn in os.walk(nq_root):
        if 'query.sql' in fn:
            nq_names.append(os.path.relpath(dp, nq_root))
    check('gateway serves 12 named queries including '
          'Events/DeleteByBatch',
          len(nq_names) == 12
          and 'Events/DeleteByBatch' in nq_names,
          sorted(nq_names))

    try:
        insert_fixtures()
        check('fixtures inserted',
              counts() == (9, 106, 9), counts())
        check('fixture press rows staged',
              count_for('batch_events', FIX) == 4
              and count_for('batch_events', CTRL) == 3
              and count_for('batch_events', LIVE) == 2,
              (count_for('batch_events', FIX),
               count_for('batch_events', CTRL),
               count_for('batch_events', LIVE)))

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1280,
                                              'height': 800})
            page.goto(BASE + '/log', wait_until='networkidle',
                      timeout=60000)
            page.wait_for_timeout(6000)
            dismiss(page)
            rows = page.locator('.ia_table__row')
            clicked = False
            for i in range(rows.count()):
                tokens = rows.nth(i).inner_text().replace(
                    ',', '').split()
                if str(FIX) in tokens:
                    rows.nth(i).scroll_into_view_if_needed()
                    rows.nth(i).click()
                    clicked = True
                    break
            page.wait_for_timeout(1200)
            check('fixture batch selected in the Log table',
                  clicked
                  and int(tag('[default]Roastery/'
                              'SelectedBatchNumber') or 0) == FIX,
                  tag('[default]Roastery/SelectedBatchNumber'))
            page.get_by_role('button', name='Delete').first.click()
            page.wait_for_timeout(1200)
            body = page.locator('body').inner_text()
            check('confirm note names the curve and the press log',
                  ('Delete batch %d, its curve and its press log?'
                   % FIX) in body, body[-500:])
            page.screenshot(path=os.path.join(
                SHOTS, 'deletecascade-confirm-1280.png'))
            page.get_by_role(
                'button', name='Confirm Delete').first.click()
            gone = wait_until(
                lambda: count_for('batches', FIX) == 0, timeout=20)
            check('fixture batch row deleted through the UI',
                  bool(gone))
            noted = wait_until(
                lambda: ('Deleted batch %d.' % FIX)
                in page.locator('body').inner_text(), timeout=20)
            check('deleted note shown on the Log page', bool(noted))
            page.screenshot(path=os.path.join(
                SHOTS, 'deletecascade-deleted-1280.png'))
            browser.close()

        check('batch_series rows cascaded with the batch',
              count_for('batch_series', FIX) == 0,
              count_for('batch_series', FIX))
        check('batch_events press rows deleted with the batch',
              count_for('batch_events', FIX) == 0,
              count_for('batch_events', FIX))
        check('control batch untouched by the delete',
              count_for('batches', CTRL) == 1
              and count_for('batch_series', CTRL) == 2
              and count_for('batch_events', CTRL) == 3,
              (count_for('batches', CTRL),
               count_for('batch_series', CTRL),
               count_for('batch_events', CTRL)))
        check('unsaved batch press rows survive another delete',
              count_for('batch_events', LIVE) == 2,
              count_for('batch_events', LIVE))

        # The no FK property, after the delete: a press row for
        # a number with no batches row still inserts (live
        # capture for an unsaved roast is unbroken).
        psql("INSERT INTO batch_events (batch_number, action, "
             "t_offset_sec, bean_temp_f, rate_of_rise_f, "
             "fan_level, heat_level, press_counter) VALUES "
             "(%d, 'First Crack Start', 60, 380.0, 12.0, 5, 5, 3)"
             % LIVE)
        psql("INSERT INTO batch_events (batch_number, action, "
             "t_offset_sec, bean_temp_f, rate_of_rise_f, "
             "fan_level, heat_level, press_counter) VALUES "
             "(%d, 'Charge', 0, 400.0, 0.0, 5, 5, 1)" % NEWLIVE)
        check('press rows still insert with no batches row',
              count_for('batch_events', LIVE) == 3
              and count_for('batch_events', NEWLIVE) == 1,
              (count_for('batch_events', LIVE),
               count_for('batch_events', NEWLIVE)))
    finally:
        wipe_fixtures()
        if sel0 is not None:
            write_tags([('[default]Roastery/SelectedBatchNumber',
                         int(sel0))])
        end_counts = counts()
        ws1 = read_tags([B + '/BatchNumber', B + '/State',
                         B + '/FanLevel', B + '/HeatLevel'])
        check('lab restored to the seeded baseline',
              end_counts == (7, 101, 0) and ws1 == [1042, 'Idle', 5, 5],
              '%s workspace=%s' % (end_counts, ws1))

    print()
    if FAILURES:
        print('DELETE CASCADE FAILURES:', FAILURES)
        return 1
    print('ALL DELETE CASCADE CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
