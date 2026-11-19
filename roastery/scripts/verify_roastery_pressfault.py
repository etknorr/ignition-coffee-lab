#!/usr/bin/env python3
"""Fault drill for the Roastery press capture isolation
(HUNT-36, polish round 4).

Proves, against the live Maker gateway, that a faulted
database connection can no longer wedge the roast state
machine or lose a press:

Sequence A (save containment): run a simulated roast to
Complete, stop the Postgres cluster, attempt Save Batch
from the UI. The save must fail visibly (failure note on
the Summary, State still Complete) and write nothing.
Restart the cluster and save again: the batch row, its
series rows, and exactly one batch_events row per press
of the roast must land.

Sequence B (press isolation, the HUNT-36 wedge itself):
charge a fresh batch, stop the cluster again, and press
Dry End, Fan +1, then the dock prerequisites FC Start and
FC End (the phase aware dock offers Drop only after FC
End), then Drop, Cool, Finish, Reset, all while the
database is down. After EACH press the state tags are read
through the REST API and the transition must have landed:
stamps recorded, Dropped after Drop, Cooling after Cool,
Complete after Finish, Idle with LastAction 'Reset' after
Reset, and ActionCounter advanced exactly once per press.

Healing: restart the cluster, charge a new roast (its head
reconcile plus the BeanTempF tick reconciles are the heal
triggers) and make a couple more presses. Poll the
database until every Sequence B press has exactly one
batch_events row for its batch number, the Reset row
included, with unique counters and no duplicates after
further reconcile triggers.

While the database is faulted the PressEvents transaction
group logs errors; that is expected drill noise.

The drill restores everything it breaks even on failure
paths: cluster started, drill batches and their series
and events deleted, workspace Idle with defaults,
simulator parked, lab back to 7 batches / 101 series /
0 events.

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
B_SCRATCH = 9917
FAILURES = []
A_BATCH = [None]
A_PRESSES = []          # (action, counter) driven in sequence A
B_PRESSES = []          # (action, counter) driven while faulted


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


def psql_try(sql):
    try:
        return psql(sql)
    except Exception:
        return None


def cluster_online():
    out = subprocess.run(['pg_lsclusters'], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        if line.startswith('16'):
            return ' online ' in (' ' + line + ' ') or \
                ' online' in line
    return False


def stop_cluster():
    subprocess.run(['pg_ctlcluster', '16', 'main', 'stop'],
                   capture_output=True, text=True, timeout=90)
    ok = wait_until(lambda: not cluster_online(), timeout=30,
                    step=1.0)
    print('cluster stopped:', bool(ok), flush=True)
    return bool(ok)


def start_cluster():
    if cluster_online():
        return True
    subprocess.run(['pg_ctlcluster', '16', 'main', 'start'],
                   capture_output=True, text=True, timeout=90)
    ok = wait_until(
        lambda: psql_try('SELECT 1') == '1', timeout=60, step=1.0)
    print('cluster started, psql answers:', bool(ok), flush=True)
    return bool(ok)


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(
                timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


# ------------------------------------------------------------- probe
PROBE_LINES = [
    "import system",
    "import roastery.core as core",
    "cmd = currentValue.value",
    "if cmd:",
    "    res = None",
    "    try:",
    "        if cmd == 'reset':",
    "            core.reset_batch(); res = 'ok'",
    "        elif cmd == 'dbping':",
    "            try:",
    "                system.db.runNamedQuery(",
    "                    'Roastery/Events/SelectByCounter',",
    "                    {'batch_number': -1, 'press_counter': -1})",
    "                res = 'ok'",
    "            except:",
    "                res = 'err'",
    "        elif cmd == 'updatedock':",
    "            core.update_dock_actions(); res = 'ok'",
    "        else:",
    "            res = 'unknown'",
    "    except Exception as e:",
    "        res = 'ERR ' + str(e)",
    "    system.tag.writeBlocking(['[default]PolishProbe/Result'], [res])",
    "    seq = system.tag.readBlocking(",
    "['[default]PolishProbe/ResultSeq'])[0].value or 0",
    "    system.tag.writeBlocking(",
    "['[default]PolishProbe/ResultSeq'], [int(seq) + 1])",
]
PROBE_SCRIPT = ''.join('\t' + l + '\n' for l in PROBE_LINES)
_seq = [0]


def probe_setup():
    folder = {'name': 'PolishProbe', 'tagType': 'Folder', 'tags': [
        {'name': 'Cmd', 'tagType': 'AtomicTag', 'valueSource': 'memory',
         'dataType': 'String', 'value': '',
         'eventScripts': [{'eventid': 'valueChanged',
                           'script': PROBE_SCRIPT}]},
        {'name': 'Result', 'tagType': 'AtomicTag',
         'valueSource': 'memory', 'dataType': 'String', 'value': ''},
        {'name': 'ResultSeq', 'tagType': 'AtomicTag',
         'valueSource': 'memory', 'dataType': 'Int4', 'value': 0},
    ]}
    st, out = api('POST', '/tags/import', body=json.dumps(folder),
                  params={'provider': 'default', 'type': 'json',
                          'collisionPolicy': 'Overwrite'},
                  ctype='application/octet-stream')
    assert st == 200, (st, out)
    _seq[0] = int(tag('[default]PolishProbe/ResultSeq') or 0)


def probe_teardown():
    api('DELETE', '/tags/delete',
        body=json.dumps({'tags': ['[default]PolishProbe']}),
        params={'confirm': 'true'})


def probe(cmd, timeout=30):
    write_tags([('[default]PolishProbe/Cmd', '')])
    time.sleep(0.35)
    write_tags([('[default]PolishProbe/Cmd', cmd)])
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = int(tag('[default]PolishProbe/ResultSeq') or 0)
        if s > _seq[0]:
            _seq[0] = s
            return tag('[default]PolishProbe/Result')
        time.sleep(0.3)
    raise RuntimeError('probe timeout: ' + cmd)


def wait_db_healthy(timeout=180):
    """Poll the GATEWAY side database connection (not psql):
    after Postgres returns, the gateway connection stays
    FAULTED for a while before its retry succeeds (measured
    in run 1 of this drill: a save retried on psql health
    alone still hit FaultedDatabaseConnectionException).
    The probe's named query is the health signal the app
    itself will see."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if probe('dbping', timeout=30) == 'ok':
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def slots_missing():
    paths = ['[default]Roastery/PressSlots/Slot%02d' % i
             for i in range(16)]
    pairs = []
    for raw in read_tags(paths):
        if not raw:
            continue
        try:
            e = json.loads(raw)
        except Exception:
            continue
        pairs.append((int(e['b']), int(e['c'])))
    if not pairs:
        return []
    cond = ' OR '.join(
        '(batch_number = %d AND press_counter = %d)' % p
        for p in pairs)
    found = psql_try(
        'SELECT COUNT(*) FROM batch_events WHERE ' + cond)
    if found is None:
        return pairs
    return pairs if int(found) < len(pairs) else []


def rows_for(batch_no):
    out = psql(
        "SELECT action || '|' || press_counter FROM batch_events "
        "WHERE batch_number = %d ORDER BY id" % batch_no)
    return [r for r in out.splitlines() if r]


def counter_rows(batch_no, counter):
    return int(psql(
        'SELECT COUNT(*) FROM batch_events WHERE batch_number = %d '
        'AND press_counter = %d' % (batch_no, counter)))


class Driver(object):
    """Phone dock driver: clicks a dock button, proves the
    press reached the gateway by its ActionCounter bump, and
    records (action, counter) for the row assertions."""

    def __init__(self, page):
        self.page = page
        self.dock = page.locator('.psc-roast-controldock')

    def click_raw(self, btn):
        if btn == 'FANPLUS':
            self.dock.locator('button', has_text='+').first.click(
                timeout=30000)
        else:
            self.dock.get_by_role('button', name=btn).click(
                timeout=30000)

    def press(self, btn, action, record=None, bump_timeout=90):
        before = int(tag(B + '/ActionCounter') or 0)
        try:
            self.click_raw(btn)
        except Exception as e:
            check('press %s click driven' % action, False,
                  repr(e)[:160])
            return before
        ok = wait_until(
            lambda: int(tag(B + '/ActionCounter') or 0) > before,
            timeout=bump_timeout)
        if not ok:
            print('SUITE NOTE: click %s made no counter bump in '
                  '%s s; retrying once' % (btn, bump_timeout),
                  flush=True)
            try:
                self.click_raw(btn)
            except Exception as e:
                check('press %s retry click driven' % action,
                      False, repr(e)[:160])
                return before
            ok = wait_until(
                lambda: int(tag(B + '/ActionCounter') or 0) > before,
                timeout=bump_timeout)
        counter = int(tag(B + '/ActionCounter') or 0)
        check('press %s bumped the counter exactly once' % action,
              bool(ok) and counter == before + 1,
              'before=%s after=%s' % (before, counter))
        if record is not None:
            record.append((action, counter))
        return counter


def state_is(want):
    return tag(B + '/State') == want


def stamp_landed(member):
    v = tag(B + '/' + member)
    return v is not None and int(v) >= 0


def main():
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    probe_setup()
    browser = None
    try:
        probe('reset')
        wait_until(lambda: state_is('Idle'), 30)
        write_tags([(B + '/FanLevel', 5), (B + '/HeatLevel', 5)])
        probe('updatedock')
        time.sleep(3)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            desk = browser.new_page(viewport={'width': 1600,
                                              'height': 900})
            mob = browser.new_page(viewport={'width': 360,
                                             'height': 740})
            for p in (desk, mob):
                p.goto(BASE + '/', wait_until='networkidle',
                       timeout=60000)
                p.wait_for_timeout(7000)
                dismiss(p)
            drive = Driver(mob)

            # ================= Sequence A =================
            # Fresh batch through the app's own New Roast flow
            # (the standing BatchNumber is a seeded batch that
            # is already in the log, so saving it would be
            # refused by design).
            desk.goto(BASE + '/log', wait_until='networkidle',
                      timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            expected_no = max(
                int(psql('SELECT MAX(batch_number) FROM batches')),
                int(tag(B + '/BatchNumber'))) + 1
            desk.get_by_role('button', name='New Roast').first.click()
            desk.wait_for_timeout(3000)
            A_BATCH[0] = int(tag(B + '/BatchNumber'))
            check('sequence A uses a fresh batch number',
                  A_BATCH[0] == expected_no and state_is('Idle'),
                  (A_BATCH[0], expected_no, tag(B + '/State')))
            desk.goto(BASE + '/', wait_until='networkidle',
                      timeout=60000)
            desk.wait_for_timeout(5000)
            dismiss(desk)
            mob.goto(BASE + '/', wait_until='networkidle',
                     timeout=60000)
            mob.wait_for_timeout(5000)
            dismiss(mob)
            drive.dock = mob.locator('.psc-roast-controldock')

            drive.press('Charge', 'Charge', A_PRESSES)
            check('A: Charge starts the roast',
                  bool(wait_until(lambda: state_is('Roasting'), 30)))
            drive.press('Dry End', 'Dry End', A_PRESSES)
            check('A: Dry End stamped',
                  bool(wait_until(
                      lambda: stamp_landed('DryEndElapsedSec'), 30)))
            drive.press('FC Start', 'First Crack Start', A_PRESSES)
            check('A: FC Start stamped',
                  bool(wait_until(
                      lambda: stamp_landed('FirstCrackStartElapsedSec'),
                      30)))
            drive.press('FC End', 'First Crack End', A_PRESSES)
            check('A: FC End stamped',
                  bool(wait_until(
                      lambda: stamp_landed('FirstCrackEndElapsedSec'),
                      30)))
            drive.press('Drop', 'Drop', A_PRESSES)
            check('A: Drop lands',
                  bool(wait_until(lambda: state_is('Dropped'), 60)))
            drive.press('Cool', 'Cool', A_PRESSES)
            check('A: Cool lands',
                  bool(wait_until(lambda: state_is('Cooling'), 30)))
            drive.press('Finish', 'Finish', A_PRESSES)
            check('A: Finish completes the roast',
                  bool(wait_until(lambda: state_is('Complete'), 30)))
            mob.screenshot(path=os.path.join(
                SHOTS, 'pressfault-a-complete-360.png'))

            # Fault the database, then attempt the save.
            check('A: cluster stops for the fault',
                  stop_cluster())
            t_click = time.time()
            try:
                desk.get_by_role('button',
                                 name='Save Batch').first.click(
                                     timeout=120000)
                clicked = True
            except Exception as e:
                clicked = False
                print('SUITE NOTE: faulted Save click raised: %r'
                      % (e,), flush=True)
            check('A: faulted Save click was driven', clicked)

            def fail_note():
                try:
                    body = desk.locator('body').inner_text()
                except Exception:
                    return None
                return body if 'was not saved' in body else None
            note = wait_until(fail_note, timeout=150, step=2.0)
            check('A: faulted save shows the failure note',
                  bool(note),
                  'elapsed %.1fs' % (time.time() - t_click))
            check('A: State still Complete after the faulted save',
                  state_is('Complete'), tag(B + '/State'))
            desk.screenshot(path=os.path.join(
                SHOTS, 'pressfault-a-save-failed.png'))

            check('A: cluster restarts', start_cluster())
            check('A: gateway database connection healthy again',
                  wait_db_healthy(180))
            check('A: faulted save wrote no batch row',
                  int(psql('SELECT COUNT(*) FROM batches WHERE '
                           'batch_number = %d' % A_BATCH[0])) == 0)
            check('A: faulted save wrote no series rows',
                  int(psql('SELECT COUNT(*) FROM batch_series WHERE '
                           'batch_number = %d' % A_BATCH[0])) == 0)

            # Save again now the connection has healed.
            desk.get_by_role('button',
                             name='Save Batch').first.click(
                                 timeout=60000)
            saved = wait_until(
                lambda: int(psql(
                    'SELECT COUNT(*) FROM batches WHERE '
                    'batch_number = %d' % A_BATCH[0])) == 1,
                timeout=60)
            check('A: retry after healing saves the batch',
                  bool(saved))
            series_n = int(psql(
                'SELECT COUNT(*) FROM batch_series WHERE '
                'batch_number = %d' % A_BATCH[0]))
            check('A: saved batch carries series rows', series_n > 0,
                  series_n)
            body = desk.locator('body').inner_text()
            check('A: success note replaces the failure note',
                  ('Saved batch %d' % A_BATCH[0]) in body)
            # The Save Batch press itself is a press of the
            # roast: its counter is the next bump after the
            # last driven press. The batch row lands before
            # that press runs (Insert, then series, then the
            # press), so wait for the bump itself.
            bumped = wait_until(
                lambda: int(tag(B + '/ActionCounter') or 0)
                > A_PRESSES[-1][1], timeout=30)
            check('A: Save Batch press bumped the counter',
                  bool(bumped))
            save_counter = int(tag(B + '/ActionCounter') or 0)
            if A_PRESSES and bumped:
                A_PRESSES.append(('Save Batch', save_counter))
            want_actions = sorted(a for a, _c in A_PRESSES)
            conv = wait_until(
                lambda: len(rows_for(A_BATCH[0])) >= len(A_PRESSES),
                timeout=90)
            rows = rows_for(A_BATCH[0])
            got_actions = sorted(r.split('|')[0] for r in rows)
            got_counters = [r.split('|')[1] for r in rows]
            check('A: exactly one event row per press of the roast',
                  bool(conv) and len(rows) == len(A_PRESSES)
                  and got_actions == want_actions,
                  'rows=%s want=%s' % (rows, A_PRESSES))
            check('A: event counters are unique and present',
                  len(set(got_counters)) == len(got_counters)
                  and 'None' not in got_counters
                  and sorted(int(c) for c in got_counters)
                  == sorted(c for _a, c in A_PRESSES),
                  got_counters)
            desk.screenshot(path=os.path.join(
                SHOTS, 'pressfault-a-saved.png'))

            # ================= Sequence B =================
            probe('reset')
            wait_until(lambda: state_is('Idle'), 30)
            write_tags([(B + '/BatchNumber', B_SCRATCH),
                        (B + '/FanLevel', 5), (B + '/HeatLevel', 5)])
            probe('updatedock')
            time.sleep(3)
            mob.goto(BASE + '/', wait_until='networkidle',
                     timeout=60000)
            mob.wait_for_timeout(5000)
            dismiss(mob)
            drive.dock = mob.locator('.psc-roast-controldock')
            drive.press('Charge', 'Charge')
            check('B: Charge starts the scratch roast',
                  bool(wait_until(lambda: state_is('Roasting'), 30)))
            check('B: cluster stops for the fault', stop_cluster())

            # While faulted: Dry End, Fan +1, FC Start, FC End
            # (dock prerequisites for Drop), Drop, Cool,
            # Finish, Reset. After EACH press the transition
            # must have landed in the tags.
            drive.press('Dry End', 'Dry End', B_PRESSES)
            check('B: Dry End stamp landed while faulted',
                  bool(wait_until(
                      lambda: stamp_landed('DryEndElapsedSec'), 90)))
            drive.press('FANPLUS', 'Fan +1', B_PRESSES)
            check('B: Fan stepper landed while faulted',
                  bool(wait_until(
                      lambda: int(tag(B + '/FanLevel') or 0) == 6,
                      90)),
                  tag(B + '/FanLevel'))
            drive.press('FC Start', 'First Crack Start', B_PRESSES)
            check('B: FC Start stamp landed while faulted',
                  bool(wait_until(
                      lambda: stamp_landed('FirstCrackStartElapsedSec'),
                      90)))
            drive.press('FC End', 'First Crack End', B_PRESSES)
            check('B: FC End stamp landed while faulted',
                  bool(wait_until(
                      lambda: stamp_landed('FirstCrackEndElapsedSec'),
                      90)))
            drive.press('Drop', 'Drop', B_PRESSES)
            check('B: State Dropped after Drop while faulted',
                  bool(wait_until(lambda: state_is('Dropped'), 90)),
                  tag(B + '/State'))
            check('B: Drop stamp recorded while faulted',
                  stamp_landed('DropElapsedSec'))
            drive.press('Cool', 'Cool', B_PRESSES)
            check('B: State Cooling after Cool while faulted',
                  bool(wait_until(lambda: state_is('Cooling'), 90)),
                  tag(B + '/State'))
            drive.press('Finish', 'Finish', B_PRESSES)
            check('B: State Complete after Finish while faulted',
                  bool(wait_until(lambda: state_is('Complete'), 90)),
                  tag(B + '/State'))
            drive.press('Reset / New Roast', 'Reset', B_PRESSES)
            check('B: State Idle after Reset while faulted',
                  bool(wait_until(lambda: state_is('Idle'), 90)),
                  tag(B + '/State'))
            check("B: LastAction is 'Reset' after the faulted Reset",
                  tag(B + '/LastAction') == 'Reset',
                  tag(B + '/LastAction'))
            mob.screenshot(path=os.path.join(
                SHOTS, 'pressfault-b-after-reset-360.png'))

            check('B: cluster restarts', start_cluster())
            check('B: gateway database connection healthy again',
                  wait_db_healthy(180))

            # Healing: charge a new roast and press a couple
            # more times; the charge head reconcile, the tick
            # reconciles and these presses' reconciles are the
            # heal triggers.
            drive.press('Charge', 'Charge (heal)')
            check('heal: Charge starts a new roast after restore',
                  bool(wait_until(lambda: state_is('Roasting'), 30)))
            drive.press('Dry End', 'Dry End (heal)')
            drive.press('FANPLUS', 'Fan +1 (heal)')

            def converged():
                for _a, c in B_PRESSES:
                    if counter_rows(B_SCRATCH, c) != 1:
                        return None
                return True
            conv = wait_until(converged, timeout=90, step=2.0)
            detail = dict(
                (c, counter_rows(B_SCRATCH, c))
                for _a, c in B_PRESSES) if B_PRESSES else {}
            check('heal: every faulted press has exactly one row',
                  bool(conv), detail)
            reset_rows = [
                r for r in rows_for(B_SCRATCH)
                if r.split('|')[0] == 'Reset']
            check('heal: the faulted Reset press has its row',
                  any(int(r.split('|')[1]) == B_PRESSES[-1][1]
                      for r in reset_rows if B_PRESSES),
                  reset_rows)
            dup = psql(
                'SELECT press_counter FROM batch_events WHERE '
                'batch_number = %d AND press_counter IS NOT NULL '
                'GROUP BY press_counter HAVING COUNT(*) > 1'
                % B_SCRATCH)
            check('heal: no duplicate counters for the scratch batch',
                  dup == '', dup)
            # Further reconcile triggers must not duplicate.
            probe('reset')
            wait_until(lambda: state_is('Idle'), 30)
            time.sleep(6)
            still = all(counter_rows(B_SCRATCH, c) == 1
                        for _a, c in B_PRESSES)
            dup2 = psql(
                'SELECT press_counter FROM batch_events WHERE '
                'batch_number = %d AND press_counter IS NOT NULL '
                'GROUP BY press_counter HAVING COUNT(*) > 1'
                % B_SCRATCH)
            check('heal: no duplicates after further reconciles',
                  still and dup2 == '', (still, dup2))
            mob.screenshot(path=os.path.join(
                SHOTS, 'pressfault-b-healed-360.png'))
            browser.close()
            browser = None
    finally:
        # Restore everything the drill broke, on every path.
        try:
            start_cluster()
        except Exception as e:
            print('cleanup: cluster start failed: %r' % (e,),
                  flush=True)
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        for attempt in range(3):
            try:
                probe('reset')
            except Exception:
                pass
            wait_until(lambda: not slots_missing(), timeout=30)
            try:
                write_tags([('[default]Roastery/PressSlots/'
                             'Slot%02d' % i, '')
                            for i in range(16)])
            except Exception:
                pass
            time.sleep(2)
            if psql_try('SELECT 1') == '1':
                if A_BATCH[0]:
                    psql('DELETE FROM batch_events WHERE '
                         'batch_number = %d' % A_BATCH[0])
                    psql('DELETE FROM batches WHERE '
                         'batch_number = %d' % A_BATCH[0])
                psql('DELETE FROM batch_events WHERE '
                     'batch_number = %d' % B_SCRATCH)
                psql('DELETE FROM batch_events')
            if tag(B + '/State') == 'Idle':
                break
        try:
            write_tags([(B + '/BatchNumber', 1042),
                        (B + '/FanLevel', 5), (B + '/HeatLevel', 5)])
            probe('updatedock')
        except Exception:
            pass
        probe_teardown()
        end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                      int(psql('SELECT COUNT(*) FROM batch_series')),
                      int(psql('SELECT COUNT(*) FROM batch_events')))
        check('lab restored to the seeded baseline',
              end_counts == (7, 101, 0)
              and tag(B + '/State') == 'Idle',
              '%s state=%s' % (end_counts, tag(B + '/State')))

    print()
    if FAILURES:
        print('PRESS FAULT FAILURES:', FAILURES)
        return 1
    print('ALL PRESS FAULT CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
