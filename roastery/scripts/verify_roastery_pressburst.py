#!/usr/bin/env python3
"""Rapid press regression for the Roastery press capture path
(HUNT-22, polish round 3).

Drives an 11 press dock sequence at about 1.3 s spacing on the
phone dock, with an early Drop so the simulator cooling seek
(a multi second fast forward) overlaps the presses that follow
it. Every press bumps the CurrentBatch ActionCounter exactly
once; the PressEvents transaction group must turn every bump
into exactly one batch_events row carrying that press's own
action. The pre fix failure: presses landing while the group
lagged behind the seek collapsed into one execution that read
only the latest LastAction, and the earlier press's row was
lost for good.

Sequence (button -> expected action row):
  Charge -> Charge
  Dry End -> Dry End
  FC Start -> First Crack Start
  FC End -> First Crack End
  SC Start -> Second Crack Start
  SC End -> Second Crack End
  Drop -> Drop
  Cool -> Cool
  Fan + -> Fan +1
  Finish -> Finish
  Reset / New Roast -> Reset

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
SPACING = 1.3
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


SEQUENCE = [
    ('Charge', 'Charge'),
    ('Dry End', 'Dry End'),
    ('FC Start', 'First Crack Start'),
    ('FC End', 'First Crack End'),
    ('SC Start', 'Second Crack Start'),
    ('SC End', 'Second Crack End'),
    ('Drop', 'Drop'),
    ('Cool', 'Cool'),
    ('FANPLUS', 'Fan +1'),
    ('Finish', 'Finish'),
    ('Reset / New Roast', 'Reset'),
]


def slots_missing():
    """(batch_number, press_counter) pairs held in the press
    ring with no batch_events row yet: the reconcile net's
    outstanding work."""
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
    found = int(psql(
        'SELECT COUNT(*) FROM batch_events WHERE ' + cond))
    return pairs if found < len(pairs) else []


def rows_for(batch_no):
    out = psql(
        "SELECT action FROM batch_events WHERE batch_number = %d "
        "ORDER BY id" % batch_no)
    return [r for r in out.splitlines() if r]


def rows_detail(batch_no):
    out = psql(
        "SELECT id || '|' || action || '|' || t_offset_sec || '|' || "
        "to_char(pressed_at, 'HH24:MI:SS.MS') FROM batch_events "
        "WHERE batch_number = %d ORDER BY id" % batch_no)
    return [r for r in out.splitlines() if r]


class Watcher(object):
    """Polls (ActionCounter, LastAction, State) and logs every
    transition with a run relative timestamp, so the audit can
    see exactly when each press handler executed and what the
    group facing stamp held at each moment."""

    def __init__(self):
        self.stop = False
        self.log = []
        self.t0 = time.time()

    def run(self):
        import threading
        def loop():
            last = None
            while not self.stop:
                try:
                    cur = tuple(read_tags(
                        [B + '/ActionCounter', B + '/LastAction',
                         B + '/State']))
                except Exception:
                    cur = None
                if cur is not None and cur != last:
                    self.log.append(
                        (round(time.time() - self.t0, 2), cur))
                    last = cur
                time.sleep(0.2)
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def dump(self):
        for ts, cur in self.log:
            print('  watch %6.2fs counter=%s last=%r state=%s'
                  % (ts, cur[0], cur[1], cur[2]), flush=True)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    probe_setup()
    try:
        probe('reset')
        wait_until(lambda: tag(B + '/State') == 'Idle', 30)
        # Known stepper levels: a stepper press at the 1..9
        # cap is a legitimate no-op the app does not capture
        # (roastery.core.stepper), and earlier runs walk the
        # fan up a level each time.
        write_tags([(B + '/FanLevel', 5), (B + '/HeatLevel', 5)])
        probe('updatedock')
        # Let the setup Reset press's own group row land before
        # the baselines are taken, so the deltas below belong to
        # the sequence alone.
        time.sleep(4)
        batch_no = int(tag(B + '/BatchNumber'))
        counter0 = int(tag(B + '/ActionCounter') or 0)
        rows0 = len(rows_for(batch_no))
        print('baselines: counter0=%s rows0=%s batch=%s'
              % (counter0, rows0, batch_no), flush=True)
        watcher = Watcher()
        watcher.run()

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            mob = browser.new_page(viewport={'width': 360,
                                             'height': 740})
            mob.goto(BASE + '/', wait_until='networkidle',
                     timeout=60000)
            mob.wait_for_timeout(7000)
            dismiss(mob)
            dock = mob.locator('.psc-roast-controldock')

            def click_btn(btn):
                if btn == 'FANPLUS':
                    dock.locator('button', has_text='+').first.click(
                        timeout=30000)
                else:
                    dock.get_by_role('button', name=btn).click(
                        timeout=30000)

            t0 = time.time()
            stamps = []
            for i, (btn, _action) in enumerate(SEQUENCE):
                # Keep the schedule: each click is issued at
                # t0 + i * SPACING; a click that had to wait for
                # its button to render eats into its own slot,
                # never into the next one's start.
                delay = t0 + i * SPACING - time.time()
                if delay > 0:
                    time.sleep(delay)
                c_before = int(tag(B + '/ActionCounter') or 0)
                click_btn(btn)
                # Verify the press reached the gateway: the
                # ActionCounter bump is record_press's first
                # write. The beta client dropped clicks under
                # the seek's render load in the HUNT-22 audit;
                # a click with no bump never reached the app,
                # so retry it once and note it. A click WITH a
                # bump belongs to the capture layer and is
                # judged by the row checks below, never retried.
                ok = wait_until(
                    lambda: int(tag(B + '/ActionCounter') or 0)
                    > c_before, timeout=5)
                if not ok:
                    print('SUITE NOTE: click %s made no counter '
                          'bump in 5 s (client dropped it); '
                          'retrying once' % btn, flush=True)
                    click_btn(btn)
                    wait_until(
                        lambda: int(tag(B + '/ActionCounter')
                                    or 0) > c_before, timeout=10)
                stamps.append((btn, round(time.time() - t0, 2),
                               tag(B + '/ActionCounter')))
                print('clicked %-16s at %5.2fs, counter now %s'
                      % (btn, stamps[-1][1], stamps[-1][2]),
                      flush=True)
            mob.screenshot(path=os.path.join(
                SHOTS, 'pressburst-after-sequence-360.png'))

            # Quiesce: rows stable across three reads 2 s
            # apart. State is not part of the condition: the
            # platform replay the audit found can re-charge the
            # workspace after the sequence's Reset, and waiting
            # for Idle would just burn the deadline on a state
            # the checks below already account for.
            last = [-1, -1, -1]
            deadline = time.time() + 120
            while time.time() < deadline:
                n = len(rows_for(batch_no))
                last = last[1:] + [n]
                if last[0] == last[1] == last[2] and last[0] > 0:
                    break
                time.sleep(2)
            counter1 = int(tag(B + '/ActionCounter') or 0)
            rows = rows_for(batch_no)[rows0:]
            expected = [a for _b, a in SEQUENCE]
            watcher.stop = True
            print('watcher transitions (counter, lastAction, state):')
            watcher.dump()
            print('rows detail:', rows_detail(batch_no)[rows0:])
            # The capture invariant: every ActionCounter bump
            # has exactly one row, whoever wrote it.
            check('one batch_events row per counter bump',
                  len(rows) == counter1 - counter0,
                  'bumps %d, rows %d'
                  % (counter1 - counter0, len(rows)))
            # No driven press lost, none doubled (multiset
            # difference in both directions).
            extras = list(rows)
            missing = []
            for a in expected:
                if a in extras:
                    extras.remove(a)
                else:
                    missing.append(a)
            check('every driven press landed exactly once',
                  not missing,
                  'missing %s in rows %s' % (missing, rows))
            # The one tolerated extra is the platform replay
            # signature the audit found twice: a single Charge
            # re-delivered after the workspace returned to
            # Idle (where Charge is a legitimate press). Any
            # other extra fails.
            replay_ok = (extras == []
                         or (extras == ['Charge']
                             and rows[-1] == 'Charge'
                             and rows.count('Reset') == 1
                             and rows.index('Reset')
                             < len(rows) - 1))
            check('no unexplained extra rows', replay_ok,
                  'extras %s' % (extras,))
            # The ring net converges: one more press (the
            # cleanup reset, driven through the probe) runs the
            # inline reconcile over the aged slots, and the
            # BeanTempF tail keeps passing; after a short wait
            # every slotted press must have its row.
            probe('reset')
            conv = wait_until(lambda: not slots_missing(),
                              timeout=30)
            check('press ring net converges', bool(conv),
                  'missing %s' % (slots_missing(),))
            mob.screenshot(path=os.path.join(
                SHOTS, 'pressburst-settled-360.png'))
            browser.close()
    finally:
        # Leave the lab at the seeded baseline whatever happened.
        # The audit caught the platform re-delivering a press
        # event seconds after the session closed (a phantom
        # Charge landed after the first cleanup reset), so the
        # restore resets, waits out the replay window, and
        # resets again before it believes the end state.
        for attempt in range(3):
            try:
                probe('reset')
            except Exception:
                pass
            # Wait out the press ring (HUNT-22 reconcile),
            # then clear the slots (the net's memory) before
            # the wipe so no reconciled press resurrects a
            # deleted row.
            wait_until(lambda: not slots_missing(), timeout=30)
            write_tags([('[default]Roastery/PressSlots/'
                         'Slot%02d' % i, '')
                        for i in range(16)])
            time.sleep(2)
            psql('DELETE FROM batch_events')
            if tag(B + '/State') == 'Idle':
                break
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
        print('PRESS BURST FAILURES:', FAILURES)
        return 1
    print('ALL PRESS BURST CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
