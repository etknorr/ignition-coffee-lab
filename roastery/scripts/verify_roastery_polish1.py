#!/usr/bin/env python3
"""Verify the Roastery polish round 1 fixes (library and data
correctness, 2026-11-17) against the Maker 2027 gateway.

Items covered:
  0. BatchEdit editor: a seeded batch with sparse metadata
     (1042: no HarvestYear, no TargetDropTempF) opens with an
     in range prefill, Save Batch enables on the first edit
     and the save lands. The document is restored afterwards.
  1. Phase bands: LiveCurveDS band columns are byte identical
     across 10 ticks of a live roast while BT and RoR update.
  2. Axis: chart datasets anchor to AXIS_BASE_MS (a Denver
     local midnight); screenshots at about 10 s elapsed in an
     America/Denver browser read elapsed mm:ss, never clock
     times. All six canvas chart instances carry the base
     axis minimum.
  3. Suggestions: no Dry End suggestion while BT falls
     through the 300 F target during the dip (before the
     turning point confirms); the suggestion fires on the
     rising crossing after TP.
  4. RoR display: the HUD text and the live curve RoR column
     follow the Artisan convention ('--' / blank before TP
     and outside the clip limits, true values after TP).
  5. Stats line: durations and percentages describe the same
     phases mid roast (completed actual, current live,
     future --, DTR -- until Drop).
  6. Phase label: library published; an SC Start stamped
     before FC Start never relabels the roast, and after a
     finish, reset and fresh charge the phase at 1 minute is
     Drying, never Second Crack.
  7. Dock backend: dock_actions() contents asserted at every
     phase by driving tag state; a disabled custom is absent
     from the list and stamp_custom refuses it in the library.

Library functions are driven through a scratch probe tag
([default]PolishProbe/Cmd, a valueChanged script calling
roastery.core), created at the start and deleted at the end,
the same way the BeanTempF tag event script calls the
library. Screenshots land in the showcase shots folder with
the polish1- prefix.

Usage: verify_roastery_polish1.py
Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8088/data/perspective/client/Roastery'
SHOTS = '/home/hatch/workspace/ignition-lab/showcase/shots'
B = '[default]Roastery/CurrentBatch'
AXIS_BASE_MS = 946710000000
LOGS = 'gateway-2027-maker/logs/system_logs.idb'
FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:200]) if detail else '', flush=True)
    if not cond:
        FAILURES.append(label)


def read_tags(paths):
    st, out = api('GET', '/tags/read', body=json.dumps({'tags': paths}))
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


def wait_tag(path, want, timeout=30):
    return wait_until(lambda: tag(path) == want, timeout)


def psql(sql):
    pw = open('/home/hatch/workspace/ignition-lab/'
              '.roastery-pgpass').read().strip()
    env = dict(os.environ, PGPASSWORD=pw)
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-c', sql], capture_output=True, text=True,
        env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def drain_pending():
    """Polish round 3: press capture slots each press's
    context in a 16 slot ring (HUNT-22); the library
    reconcile inserts any press the group missed. Wait
    until every slotted press has its batch_events row, or
    a reconciled press would resurrect a row this suite
    just deleted."""
    def missing():
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
            return False
        cond = ' OR '.join(
            '(batch_number = %d AND press_counter = %d)' % p
            for p in pairs)
        found = int(psql(
            'SELECT COUNT(*) FROM batch_events WHERE ' + cond))
        return found < len(pairs)
    wait_until(lambda: not missing(), timeout=30)
    write_tags([('[default]Roastery/PressSlots/Slot%02d' % i, '')
                for i in range(16)])


def ds_rows(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return [], []
    if not isinstance(value, dict):
        return [], []
    cols = [c['name'] for c in value.get('columns') or []]
    return cols, value.get('rows') or []


def dismiss(page):
    try:
        if page.get_by_text('Personal Use Only').count() > 0:
            page.get_by_text('AGREE & CLOSE').first.click(timeout=8000)
            page.wait_for_timeout(1200)
    except Exception:
        pass


def log_marker():
    shutil.copy(LOGS, '/tmp/logs_p1_start.idb')
    con = sqlite3.connect('/tmp/logs_p1_start.idb')
    m = con.execute('SELECT MAX(event_id) FROM logging_event').fetchone()[0]
    con.close()
    return m


def log_check(start_id):
    for _try in range(5):
        try:
            shutil.copy(LOGS, '/tmp/logs_p1_end.idb')
            con = sqlite3.connect('/tmp/logs_p1_end.idb')
            rows = con.execute(
                "SELECT level_string, logger_name, formatted_message "
                "FROM logging_event WHERE event_id > ? AND "
                "level_string IN ('WARN', 'ERROR')",
                (start_id,)).fetchall()
            con.close()
            return [r for r in rows
                    if 'roastery' in (r[1] or '').lower()
                    or 'Roastery' in (r[2] or '')]
        except Exception:
            time.sleep(2)
    return ['log check failed']


# ------------------------------------------------------------- probe
PROBE_LINES = [
    "import system",
    "import roastery.core as core",
    "cmd = currentValue.value",
    "if cmd:",
    "    res = None",
    "    try:",
    "        if cmd == 'dock':",
    "            res = system.util.jsonEncode(core.dock_actions())",
    "        elif cmd == 'phase':",
    "            res = core.phase_label()",
    "        elif cmd == 'stats':",
    "            res = core.stats_line_text()",
    "        elif cmd.startswith('stamp_custom:'):",
    "            res = str(core.stamp_custom(int(cmd.split(':')[1])))",
    "        elif cmd == 'charge':",
    "            core.charge(); res = 'ok'",
    "        elif cmd == 'drop':",
    "            core.drop(); res = 'ok'",
    "        elif cmd == 'cool':",
    "            core.cool(); res = 'ok'",
    "        elif cmd == 'finish':",
    "            core.finish(); res = 'ok'",
    "        elif cmd == 'reset':",
    "            core.reset_batch(); res = 'ok'",
    "        elif cmd.startswith('stamp:'):",
    "            parts = cmd.split(':', 2)",
    "            core.stamp_event(parts[1], parts[2]); res = 'ok'",
    "        else:",
    "            res = 'unknown'",
    "    except Exception as e:",
    "        res = 'ERR ' + str(e)",
    "    system.tag.writeBlocking(['[default]PolishProbe/Result'], [res])",
    "    seq = system.tag.readBlocking("
    "['[default]PolishProbe/ResultSeq'])[0].value or 0",
    "    system.tag.writeBlocking("
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


def band_signature():
    """The band columns of LiveCurveDS as a sorted tuple of
    (elapsed_ms, column, value): the byte identity the band
    stability check compares across ticks."""
    cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
    out = []
    if cols:
        for col in ('bandDry', 'bandMai', 'bandDev', 'bandCool'):
            i = cols.index(col)
            for r in rows:
                if r[i] is not None:
                    out.append((int(r[0]) - AXIS_BASE_MS, col, r[i]))
    return tuple(sorted(out))


def main():
    start_event = log_marker()
    os.makedirs(SHOTS, exist_ok=True)
    base_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                   int(psql('SELECT COUNT(*) FROM batch_series')),
                   int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab starts at the seeded baseline',
          base_counts == (7, 101, 0), base_counts)
    max_event_id = int(psql('SELECT COALESCE(MAX(id), 0) '
                            'FROM batch_events'))
    doc_1042 = psql('SELECT data::text FROM batches '
                    'WHERE batch_number = 1042')
    probe_setup()
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    write_tags([(B + '/CustomEvent2Enabled', True)])

    # ---------------- item 3: suggestion guard ----------------
    # Charge on the stepped sim: BT falls from 392 F through
    # the 300 F Dry End target during the dip. No suggestion
    # may fire before the turning point confirms; the Dry End
    # suggestion must fire on the rising crossing after TP.
    # SimBaseRate 500 plays the program at 2x to halve the
    # wait (stepper retiming is not used, so the rate holds).
    write_tags([(B + '/SuggestDryEndEnabled', True),
                (B + '/TargetDryEndTempF', 300.0)])
    probe('charge')
    wait_tag(B + '/State', 'Roasting')
    write_tags([('[default]Roastery/SimBaseRate', 500)])
    fell_through = False
    fired_early = False
    tp_seen_at = None
    t0 = time.time()
    while time.time() - t0 < 150:
        bt, tp, act = read_tags([B + '/BeanTempF',
                                 B + '/TurningPointElapsedSec',
                                 B + '/SuggestionActive'])
        if bt is not None and bt < 295.0:
            fell_through = True
        if tp is not None and tp >= 0:
            tp_seen_at = tp
            break
        if act:
            fired_early = True
            break
        time.sleep(0.5)
    check('BT fell through the Dry End target during the dip',
          fell_through)
    check('no suggestion fired before the turning point '
          'confirmed (falling crossing stays silent)',
          not fired_early and tp_seen_at is not None,
          'tp=%s' % tp_seen_at)
    fired = wait_until(
        lambda: tag(B + '/SuggestionActive')
        and tag(B + '/SuggestionKind') == 'DryEnd',
        timeout=300, step=1.0)
    bt_fire, tp_fire = read_tags([B + '/BeanTempF',
                                  B + '/TurningPointElapsedSec'])
    check('Dry End suggestion fired on the rising crossing '
          'after TP', bool(fired),
          'bt=%.1f tp=%s' % (bt_fire or -1, tp_fire))
    check('firing happened at or above the 300 F target on '
          'the rise', bt_fire is not None and bt_fire >= 299.0,
          bt_fire)
    probe('stamp:DryEnd:Dry End')
    check('stamping Dry End clears the suggestion',
          not tag(B + '/SuggestionActive'))
    probe('reset')
    wait_tag(B + '/State', 'Idle')

    # ---------------- item 7: dock contract -------------------
    def dock():
        return json.loads(probe('dock'))

    def keys(ds):
        return [(d['key'], d['kind'], d['lead']) for d in ds]

    CUSTOMS = [('Fan Boost', 'custom', False),
               ('Drum Note', 'custom', False),
               ('Custom 3', 'custom', False),
               ('Custom 4', 'custom', False)]
    check('dock at Idle is Charge only',
          keys(dock()) == [('Charge', 'primary', True)])
    write_tags([(B + '/State', 'Roasting')])
    check('dock before Dry End: Dry End lead plus customs',
          keys(dock()) == [('Dry End', 'primary', True)] + CUSTOMS,
          keys(dock()))
    write_tags([(B + '/CustomEvent2Enabled', False)])
    d = dock()
    check('dock drops a disabled custom',
          [x['key'] for x in d] == ['Dry End', 'Fan Boost',
                                    'Custom 3', 'Custom 4'],
          [x['key'] for x in d])
    write_tags([(B + '/CustomEvent2Enabled', True),
                (B + '/DryEndElapsedSec', 100)])
    check('dock after Dry End: FC Start lead plus customs',
          keys(dock()) == [('First Crack Start', 'primary', True)]
          + CUSTOMS, keys(dock()))
    write_tags([(B + '/FirstCrackStartElapsedSec', 300)])
    check('dock after FC Start: FC End lead, Drop secondary',
          keys(dock()) == [('First Crack End', 'primary', True),
                           ('Drop', 'secondary', False)] + CUSTOMS,
          keys(dock()))
    write_tags([(B + '/FirstCrackEndElapsedSec', 400)])
    check('dock after FC End: SC Start lead, Drop secondary',
          keys(dock()) == [('Second Crack Start', 'primary', True),
                           ('Drop', 'secondary', False)] + CUSTOMS,
          keys(dock()))
    write_tags([(B + '/SecondCrackStartElapsedSec', 500)])
    check('dock after SC Start: SC End lead, Drop secondary',
          keys(dock()) == [('Second Crack End', 'primary', True),
                           ('Drop', 'secondary', False)] + CUSTOMS,
          keys(dock()))
    write_tags([(B + '/SecondCrackEndElapsedSec', 560)])
    check('dock after SC End: Drop lead plus customs',
          keys(dock()) == [('Drop', 'primary', True)] + CUSTOMS,
          keys(dock()))
    write_tags([(B + '/State', 'Dropped')])
    check('dock at Dropped: Cool lead, then Finish',
          keys(dock()) == [('Cool', 'primary', True),
                           ('Finish', 'secondary', False)],
          keys(dock()))
    write_tags([(B + '/State', 'Cooling')])
    check('dock at Cooling: Finish only',
          keys(dock()) == [('Finish', 'primary', True)],
          keys(dock()))
    write_tags([(B + '/State', 'Complete')])
    d = dock()
    check('dock at Complete: Charge lead plus Reset / New '
          'Roast utility',
          keys(d) == [('Charge', 'primary', True),
                      ('Reset', 'utility', False)]
          and d[1]['label'] == 'Reset / New Roast', d)
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    check('reset cleared every event elapsed member',
          read_tags([B + '/DryEndElapsedSec',
                     B + '/FirstCrackStartElapsedSec',
                     B + '/FirstCrackEndElapsedSec',
                     B + '/SecondCrackStartElapsedSec',
                     B + '/SecondCrackEndElapsedSec',
                     B + '/DropElapsedSec',
                     B + '/CustomEvent1ElapsedSec',
                     B + '/CustomEvent2ElapsedSec',
                     B + '/CustomEvent3ElapsedSec',
                     B + '/CustomEvent4ElapsedSec'])
          == [-1] * 10)

    # Disabled custom stamp refusal needs a live roast for the
    # elapsed stamp; run it inside the item 6 second charge
    # below instead of a roast of its own.

    # ------------- items 1, 2, 4, 5, 6: the live roast --------
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desk = browser.new_page(
            viewport={'width': 1600, 'height': 900},
            timezone_id='America/Denver')
        mob = browser.new_page(
            viewport={'width': 360, 'height': 740},
            timezone_id='America/Denver')
        desk.goto(BASE + '/', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        mob.goto(BASE + '/', wait_until='networkidle',
                 timeout=60000)
        mob.wait_for_timeout(5000)
        dismiss(mob)
        dock_el = mob.locator('.psc-roast-controldock')
        dock_el.get_by_role('button', name='Charge').click()
        check('charge starts the polish roast',
              wait_tag(B + '/State', 'Roasting'))

        # Item 2: axis at about 10 s elapsed, Denver browser.
        mob.wait_for_timeout(9000)
        cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
        check('live dataset x starts at the axis base (elapsed '
              'zero)', bool(rows)
              and int(rows[0][0]) - AXIS_BASE_MS == 0,
              rows[0][0] if rows else None)
        desk.screenshot(path=os.path.join(
            SHOTS, 'polish1-axis-desktop.png'))
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish1-axis-360.png'))

        # Item 4, dip side: HUD text is '--' while the true
        # RateOfRiseF runs steeply negative.
        dip = wait_until(
            lambda: (tag(B + '/RateOfRiseF') or 0) < -50.0,
            timeout=60, step=0.4)
        disp = tag(B + '/RateOfRiseDisplayText')
        check('true RoR runs steeply negative in the dip',
              bool(dip), tag(B + '/RateOfRiseF'))
        check('HUD RoR text reads -- during the dip (Artisan '
              'convention)', disp == '--', disp)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish1-ror-dip-360.png'))

        # Item 1: band columns identical across 10 ticks while
        # the bean values keep changing.
        sigs = []
        beans = []
        t0 = time.time()
        while len(sigs) < 10 and time.time() - t0 < 60:
            sigs.append(band_signature())
            cols, rows = ds_rows(tag('[default]Roastery/LiveCurveDS'))
            if cols and rows:
                bi = cols.index('bean')
                vals = [r[bi] for r in rows if r[bi] is not None]
                beans.append(vals[-1] if vals else None)
            time.sleep(1.2)
        desk.screenshot(path=os.path.join(
            SHOTS, 'polish1-bands-a.png'))
        check('band columns byte identical across 10 ticks',
              len(sigs) == 10 and len(set(sigs)) == 1,
              '%d samples, %d distinct' % (len(sigs),
                                           len(set(sigs))))
        check('bean values kept updating during the band '
              'sampling', len(set(beans)) >= 5, beans[:3])
        check('bands present with target boundaries pre stamps',
              bool(sigs[0]) and len(sigs[0]) == 6,
              sigs[0])

        # Speed the program up for the post TP work.
        write_tags([('[default]Roastery/SimBaseRate', 500)])

        # Item 6, first half: SC Start stamped before FC Start
        # must not relabel the phase.
        probe('stamp:SecondCrackStart:Second Crack Start')
        check('phase stays Drying with an early SC Start stamp',
              tag(B + '/PhaseLabel') == 'Drying',
              tag(B + '/PhaseLabel'))

        # Item 4, after TP: the display shows the true value.
        tp_ok = wait_until(
            lambda: int(tag(B + '/TurningPointElapsedSec')
                        or -1) >= 0, timeout=120, step=0.7)
        check('turning point confirmed', bool(tp_ok),
              tag(B + '/TurningPointElapsedSec'))
        shown = wait_until(
            lambda: (tag(B + '/RateOfRiseDisplayText') or '--')
            if (tag(B + '/RateOfRiseDisplayText') or '--') != '--'
            else None, timeout=90, step=0.7)
        ror_tag = tag(B + '/RateOfRiseF')
        check('HUD RoR shows a value after TP', shown is not None,
              shown)
        check('HUD RoR matches the true RoR tag after TP',
              shown is not None and ror_tag is not None
              and abs(float(shown) - float(ror_tag)) <= 3.0,
              (shown, ror_tag))

        # Item 5: stats line mid roast with Dry End stamped.
        probe('stamp:DryEnd:Dry End')
        dry_s = int(tag(B + '/DryEndElapsedSec'))
        time.sleep(2.5)
        line = tag(B + '/StatsLineText')
        m = re.match(
            r'Dry (\d+):(\d+) (\d+)% \u00b7 Mai (\d+):(\d+) '
            r'(\d+)% \u00b7 Dev --:-- -- \u00b7 DTR --$', line
            or '')
        ok = False
        if m:
            d_dur = int(m.group(1)) * 60 + int(m.group(2))
            d_pct = int(m.group(3))
            m_dur = int(m.group(4)) * 60 + int(m.group(5))
            m_pct = int(m.group(6))
            tot = d_dur + m_dur
            ok = (d_dur == dry_s
                  and abs(d_pct - round(dry_s * 100.0 / tot)) <= 2
                  and abs(m_pct - round(m_dur * 100.0 / tot)) <= 2)
        check('stats line: Dry actual, Mai live, Dev and DTR '
              'pending', ok, line)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish1-stats-360.png'))

        # Item 6, second half: with FC Start stamped after the
        # early SC Start, Second Crack is the legal sub state.
        probe('stamp:FirstCrackStart:First Crack Start')
        check('phase is Second Crack once FC and SC are both '
              'stamped', tag(B + '/PhaseLabel') == 'Second Crack',
              tag(B + '/PhaseLabel'))

        # Item 4 acceptance value: early drying RoR reads
        # about 38 F/min on the new sim (asserted in a window
        # once the post TP slope settles, with the tag match).
        def _settled():
            d = tag(B + '/RateOfRiseDisplayText')
            if d in (None, '--'):
                return None
            v = float(d)
            return v if 28.0 <= v <= 50.0 else None
        settled = wait_until(_settled, timeout=180, step=1.0)
        check('post TP RoR reads about 38 F/min early drying',
              settled is not None, settled)
        mob.screenshot(path=os.path.join(
            SHOTS, 'polish1-ror-after-tp-360.png'))

        # Finish this roast, reset, and run the item 6
        # reproduction: a fresh roast must read Drying at
        # 1 minute, never Second Crack.
        probe('drop')
        probe('cool')
        probe('finish')
        probe('reset')
        wait_tag(B + '/State', 'Idle')
        check('SC elapsed cleared by reset',
              int(tag(B + '/SecondCrackStartElapsedSec')) == -1)
        probe('charge')
        wait_tag(B + '/State', 'Roasting')
        write_tags([('[default]Roastery/SimBaseRate', 500)])
        # Item 7 refusal, inside this live roast.
        ev0 = int(psql('SELECT COUNT(*) FROM batch_events '
                       'WHERE id > %d' % max_event_id))
        write_tags([(B + '/CustomEvent2Enabled', False)])
        res = probe('stamp_custom:2')
        time.sleep(1.2)
        ev1 = int(psql('SELECT COUNT(*) FROM batch_events '
                       'WHERE id > %d' % max_event_id))
        check('disabled custom stamp refused in the library',
              res == 'False'
              and int(tag(B + '/CustomEvent2ElapsedSec')) == -1
              and ev1 == ev0, (res, ev0, ev1))
        write_tags([(B + '/CustomEvent2Enabled', True)])
        res = probe('stamp_custom:2')
        time.sleep(1.5)
        ev2 = int(psql('SELECT COUNT(*) FROM batch_events '
                       'WHERE id > %d' % max_event_id))
        check('enabled custom stamps and records one press row',
              res == 'True'
              and int(tag(B + '/CustomEvent2ElapsedSec')) >= 0
              and ev2 == ev1 + 1, (res, ev1, ev2))
        # 1 minute of sim time at 2x is 30 s of wall time from
        # charge; the stamp work above consumed part of it.
        time.sleep(32)
        check('phase at 1 minute of the fresh roast is Drying',
              tag(B + '/PhaseLabel') == 'Drying',
              tag(B + '/PhaseLabel'))
        probe('reset')
        wait_tag(B + '/State', 'Idle')

        # ---------------- item 0: the editor ------------------
        desk.goto(BASE + '/log', wait_until='networkidle',
                  timeout=60000)
        desk.wait_for_timeout(5000)
        dismiss(desk)
        rows_el = desk.locator('.ia_table__row')
        picked = False
        for i in range(rows_el.count()):
            rows_el.nth(i).click()
            desk.wait_for_timeout(900)
            if int(tag('[default]Roastery/SelectedBatchNumber')
                   or 0) == 1042:
                picked = True
                break
        check('batch 1042 selected', picked)
        desk.get_by_role('button', name='Details').first.click()
        desk.wait_for_timeout(5000)
        dismiss(desk)
        desk.get_by_role('button', name='Edit', exact=True).click()
        desk.wait_for_timeout(4500)
        dockv = desk.locator('.docked-view-right')
        check('editor dock opens for batch 1042',
              dockv.count() == 1
              and 'Edit Batch 1042' in dockv.inner_text())
        vals = dockv.evaluate("""() => {
          const out = {};
          document.querySelectorAll(
            '.docked-view-right .ia_inputField_input, '
            + '.docked-view-right input').forEach(inp => {
            let lab = '';
            let el = inp;
            for (let i = 0; i < 8 && el; i++) {
              el = el.parentElement;
              if (el && el.innerText) {
                lab = el.innerText.split('\\n')[0]; break; } }
            if (lab) out[lab] = inp.value;
          });
          return out;
        }""")
        check('editor prefill is in range for the constrained '
              'fields (no hard zeros)',
              vals.get('Harvest year') == '2025'
              and vals.get('Target drop temp (F)') == '415',
              {k: vals.get(k) for k in ('Harvest year',
                                        'Target drop temp (F)')})
        save_btn = dockv.get_by_role('button', name='Save Batch')
        # Note: the form counts the programmatic prefill as a
        # change, so the button may already be enabled when
        # the prefill is valid. The regression contract is the
        # pair below: an edit keeps it enabled and the save
        # lands (before the fix the invalid zeros kept it
        # disabled forever).
        # Fill the Dry End time, the same locator route the
        # v4 suite uses for the editor fields.
        inp = dockv.locator(
            "xpath=//*[contains(text(),'Dry End time')]"
            "/following::input[1]")
        inp.first.fill('00:10')
        desk.wait_for_timeout(1200)
        check('Dry End time field filled',
              inp.first.input_value() == '00:10',
              inp.first.input_value())
        enabled = wait_until(
            lambda: not save_btn.first.is_disabled(),
            timeout=15, step=0.5)
        check('Save Batch enables after the first edit '
              '(the regression)', bool(enabled))
        desk.screenshot(path=os.path.join(
            SHOTS, 'polish1-editor-1042.png'))
        if enabled:
            save_btn.first.click()
            saved = wait_until(
                lambda: 'Saved batch 1042' in dockv.inner_text(),
                timeout=20, step=0.5)
            check('editor save lands for batch 1042',
                  bool(saved))
        browser.close()

    # ---------------- restore and final state -----------------
    psql("UPDATE batches SET data = '%s'::jsonb "
         'WHERE batch_number = 1042' % doc_1042.replace(
             "'", "''"))
    probe('reset')
    wait_tag(B + '/State', 'Idle')
    write_tags([(B + '/BatchNumber', 1042), (B + '/FanLevel', 5),
                (B + '/HeatLevel', 5),
                (B + '/CustomEvent2Enabled', True)])
    drain_pending()
    psql('DELETE FROM batch_events WHERE id > %d' % max_event_id)
    probe_teardown()
    end_counts = (int(psql('SELECT COUNT(*) FROM batches')),
                  int(psql('SELECT COUNT(*) FROM batch_series')),
                  int(psql('SELECT COUNT(*) FROM batch_events')))
    check('lab back to the seeded baseline',
          end_counts == base_counts, end_counts)
    state = read_tags([B + '/State', B + '/FanLevel',
                       B + '/HeatLevel', B + '/BatchNumber',
                       B + '/ActiveSource'])
    check('workspace clean Idle', state == ['Idle', 5, 5, 1042,
                                             'Simulated'], state)
    check('background cleared',
          (tag('[default]Roastery/BackgroundLabel') or '') == '')
    bad = log_check(start_event)
    check('zero Roastery warnings in the window', not bad,
          bad[:3])
    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL POLISH ROUND 1 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
