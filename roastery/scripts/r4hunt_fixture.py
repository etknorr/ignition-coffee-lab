#!/usr/bin/env python3
"""Shared fixture helper for the r4hunt A-to-B chain (HUNT-58).

Problem (round 7, first-pass failure 2): a VM replacement
between part A and part B restored the database to the
reseeded 7/101/0 baseline, wiping fixture batch 9919 (created
by part A, 42 series rows), so part B failed "fixture row
selectable for delete" and the battery had to rerun A then B
by hand. Part C already restored the fixture from a snapshot,
but only C did, and the snapshot had lived only in /tmp until
round 7 moved it to the lab dir.

Fix: every part in the chain verifies its precondition at
start and self-heals from the persistent lab-dir snapshot:

- ensure_fixture(): fixture 9919 present with the snapshot's
  full series count, or re-created from the snapshot. Used by
  part B (whose delete step needs the fixture) and part C
  (whose detail pass needs it). A does not use it: A creates
  the fixture live, and instead calls ensure_clean_baseline()
  at start so a rerun after a partial A (or after a VM
  replacement left a stale fixture plus press rows) cleans up
  and re-creates it, then snapshot_fixture() after the save so
  the lab-dir snapshot is fresh after every A run.
- The snapshot lives in the lab dir (persistent across VM
  replacements), with the helper's own directory and /tmp as
  fallbacks. /tmp alone is never the only copy.
- HUNT-53 guard: every cleanup path drains the press ring
  first (P.drain_pending waits for slotted presses to land as
  rows, then clears all 16 PressSlots) and only then deletes
  batch_events rows, so the reconciler cannot resurrect a
  deleted press row into the fresh database.

Parts D and E need no fixture: D probes the upload modal and
toasts with files it writes itself, and E proves PressEvents
with its own charge/reset probe. Neither references 9919.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P

FIX = 9919
LAB_DIR = '/home/hatch/workspace/ignition-lab'
SNAP_NAME = 'r4hunt_fixture_9919.json'


def snapshot_paths():
    """Lab-dir copy first (persistent), helper-dir copy next,
    /tmp last. /tmp is wiped on VM replacement, so it is only
    a fallback for older snapshots."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.join(LAB_DIR, SNAP_NAME),
             os.path.join(here, SNAP_NAME),
             os.path.join('/tmp', SNAP_NAME)]
    seen = set()
    out = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_snapshot():
    for path in snapshot_paths():
        if os.path.exists(path):
            print('fixture snapshot:', path, flush=True)
            return json.loads(open(path).read())
    raise FileNotFoundError(
        'no %s snapshot found; tried: %s (re-run part A, which '
        're-creates the fixture and re-writes the snapshot)'
        % (SNAP_NAME, ', '.join(snapshot_paths())))


def fixture_status():
    """(batch rows, series rows, press rows) for fixture 9919."""
    return (int(P.psql('SELECT COUNT(*) FROM batches WHERE '
                       'batch_number = %d' % FIX)),
            int(P.psql('SELECT COUNT(*) FROM batch_series WHERE '
                       'batch_number = %d' % FIX)),
            int(P.psql('SELECT COUNT(*) FROM batch_events WHERE '
                       'batch_number = %d' % FIX)))


def press_guard():
    """HUNT-53 guard: settle the press ring, then clear it.
    drain_pending waits until every slotted press has its
    batch_events row, then writes '' to all 16 PressSlots, so
    a later DELETE of press rows cannot be resurrected by the
    reconciler on the next BeanTempF change tail."""
    P.drain_pending()
    print('press guard: PressSlots drained and cleared',
          flush=True)


def _psql_insert(sql):
    pw = open(os.path.join(LAB_DIR, '.roastery-pgpass')).read().strip()
    env = dict(os.environ, PGPASSWORD=pw,
               PATH=os.environ['PATH']
               + ':/usr/lib/postgresql/16/bin')
    out = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition',
         '-d', 'db', '-v', 'ON_ERROR_STOP=1', '-c', sql],
        capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr


def restore_fixture():
    """Re-create fixture 9919 from the snapshot. No-op when
    the batch is already present with the snapshot's full
    series count. A partial fixture (batch present, series
    short or missing) is replaced wholesale, so a half-wiped
    database heals the same way a fully wiped one does."""
    snap = load_snapshot()
    want_series = len(snap['series'])
    n_batch, n_series, _n_ev = fixture_status()
    if n_batch == 1 and n_series == want_series:
        print('fixture 9919 already present, %d series rows'
              % n_series, flush=True)
        return False
    print('fixture 9919 missing or partial (batch %d, series '
          '%d, want %d); restoring from snapshot'
          % (n_batch, n_series, want_series), flush=True)
    # Guard first: settle and clear the ring, then delete the
    # stale rows, so nothing resurrects them afterwards.
    press_guard()
    _psql_insert('DELETE FROM batch_events WHERE batch_number '
                 '= %d' % FIX)
    _psql_insert('DELETE FROM batch_series WHERE batch_number '
                 '= %d' % FIX)
    _psql_insert('DELETE FROM batches WHERE batch_number = %d'
                 % FIX)
    b = snap['batch']

    def num(v):
        return 'NULL' if v is None else str(v)

    _psql_insert(
        "INSERT INTO batches (batch_number, roast_start, "
        "roast_end, bean_name, drop_temp_f, data) VALUES "
        "(%d, '%s', '%s', '%s', %s, '%s'::jsonb)" % (
            b['batch_number'], b['roast_start'], b['roast_end'],
            b['bean_name'].replace("'", "''"),
            b['drop_temp_f'],
            json.dumps(b['data']).replace("'", "''")))
    for s in snap['series']:
        _psql_insert(
            "INSERT INTO batch_series (batch_number, "
            "t_offset_sec, bean_temp_f, rate_of_rise_f, "
            "fan_level, heat_level) VALUES (%d, %s, %s, %s, "
            "%s, %s)" % (FIX, num(s['t']), num(s['bt']),
                         num(s['ror']), num(s['fan']),
                         num(s['heat'])))
    n_batch, n_series, _n_ev = fixture_status()
    assert (n_batch, n_series) == (1, want_series), \
        'restore failed: batch %d series %d (want 1, %d)' % (
            n_batch, n_series, want_series)
    print('fixture 9919 restored, %d series rows' % n_series,
          flush=True)
    return True


def ensure_fixture():
    """Part-start precondition for B and C: fixture 9919
    exists with its full series, restoring it from the
    snapshot when a VM replacement (or a crash) wiped it."""
    status = fixture_status()
    print('fixture 9919 at part start: batch %d, series %d, '
          'events %d' % status, flush=True)
    restore_fixture()
    return True


def ensure_clean_baseline():
    """Part A start: the lab must be at the seeded baseline
    (7, 101, 0) before A roasts. A stale fixture 9919 (from a
    partial A run, or a VM replacement that left it plus its
    press rows) would make the live save refuse the duplicate
    batch number, and leftover press rows would fail the
    baseline check. Guard first (drain + clear the ring),
    then delete the fixture rows and any press rows, so the
    roast starts from a clean, resurrection-proof baseline.
    Returns the counts after cleanup."""
    n_batch, n_series, n_ev = fixture_status()
    total_ev = int(P.psql('SELECT COUNT(*) FROM batch_events'))
    if n_batch == 0 and n_series == 0 and total_ev == 0:
        print('lab already at clean baseline for part A',
              flush=True)
        return (int(P.psql('SELECT COUNT(*) FROM batches')),
                int(P.psql('SELECT COUNT(*) FROM batch_series')),
                0)
    print('cleaning stale part A residue: fixture batch %d, '
          'series %d, fixture events %d, total events %d'
          % (n_batch, n_series, n_ev, total_ev), flush=True)
    press_guard()
    _psql_insert('DELETE FROM batch_events WHERE batch_number '
                 '= %d' % FIX)
    _psql_insert('DELETE FROM batch_series WHERE batch_number '
                 '= %d' % FIX)
    _psql_insert('DELETE FROM batches WHERE batch_number = %d'
                 % FIX)
    _psql_insert('DELETE FROM batch_events')
    counts = (int(P.psql('SELECT COUNT(*) FROM batches')),
              int(P.psql('SELECT COUNT(*) FROM batch_series')),
              int(P.psql('SELECT COUNT(*) FROM batch_events')))
    print('counts after cleanup:', counts, flush=True)
    return counts


def snapshot_fixture():
    """Dump fixture 9919 from the DB into the snapshot shape
    restore_fixture() expects, into the lab dir (persistent)
    plus /tmp. Called by part A right after the live save, so
    the snapshot is fresh after every A run instead of a
    one-off file that can go stale."""
    assert P.psql('SELECT COUNT(*) FROM batches WHERE '
                  'batch_number = %d' % FIX) == '1', \
        'fixture 9919 not in DB, cannot snapshot'
    pw = open(os.path.join(LAB_DIR, '.roastery-pgpass')).read().strip()
    env = dict(os.environ, PGPASSWORD=pw,
               PATH=os.environ['PATH']
               + ':/usr/lib/postgresql/16/bin')

    def run(sql):
        out = subprocess.run(
            ['psql', '-h', 'localhost', '-U', 'ignition',
             '-d', 'db', '-t', '-A', '-F', '\t', '-c', sql],
            capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return out.stdout

    row = run("SELECT batch_number, roast_start, roast_end, "
              "bean_name, drop_temp_f, data::text FROM batches "
              "WHERE batch_number = %d" % FIX).strip().split('\t')
    batch = {'batch_number': int(row[0]), 'roast_start': row[1],
             'roast_end': row[2], 'bean_name': row[3],
             'drop_temp_f': float(row[4]),
             'data': json.loads(row[5])}
    series = []
    out = run("SELECT t_offset_sec, bean_temp_f, "
              "rate_of_rise_f, fan_level, heat_level FROM "
              "batch_series WHERE batch_number = %d ORDER BY "
              "t_offset_sec" % FIX)
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        t, bt, ror, fan, heat = line.split('\t')
        series.append({
            't': None if t == '' else int(float(t)),
            'bt': None if bt == '' else float(bt),
            'ror': None if ror == '' else float(ror),
            'fan': None if fan == '' else int(float(fan)),
            'heat': None if heat == '' else int(float(heat))})
    snap = {'batch': batch, 'series': series}
    for path in (os.path.join(LAB_DIR, SNAP_NAME),
                 '/tmp/r4hunt_fixture_9919.json'):
        with open(path, 'w') as f:
            json.dump(snap, f)
        print('wrote', path, 'series', len(series), flush=True)
    print('snapshot batch', batch['batch_number'],
          batch['bean_name'], 'drop', batch['drop_temp_f'],
          flush=True)
    return snap


if __name__ == '__main__':
    import sys as _sys
    cmd = _sys.argv[1] if len(_sys.argv) > 1 else 'ensure'
    if cmd == 'ensure':
        ensure_fixture()
    elif cmd == 'snapshot':
        snapshot_fixture()
    elif cmd == 'status':
        print('fixture 9919:', fixture_status(), flush=True)
    elif cmd == 'clean':
        print('cleaned to:', ensure_clean_baseline(), flush=True)
    else:
        raise SystemExit('usage: r4hunt_fixture.py '
                         '[ensure|snapshot|status|clean]')
