#!/usr/bin/env python3
"""Round 10 worker B: HUNT-62 note, Artisan live vs saved AUC.

Static proof that the clipped live AUC is the exact integral from
the begin second, and that Artisan's own live and saved AUC paths
disagree with each other by construction, so there is no single
Artisan number for our app to match. No code change. No browser,
no tag writes, no database writes, no fixtures. The only live
reads are the gateway trial, three CurrentBatch tags, the database
counts, and the seeded batch 1042 series (read only).

Artisan 5.0.0 citations (~/workspace/artisan-src/src/artisanlib):
- calcAUC, main.py:24513: trapezoid of ONE segment, the segment
  ending at index i (default i=-1, the newest segment). Guard:
  needs 0 < i < len, so i=0 contributes 0.
- thisAUC, main.py:24479: base from temp[idx] if AUCbaseFlag
  else AUCbase, then calcAUC with i=-1, /60. The begin index is
  used ONLY for the base; the area is always the newest segment.
- updateAUC, main.py:24493: once per sample tick (called from
  canvas.py:4969 in sample_processing, after the new sample is
  appended at canvas.py:4711-4713). If the begin event is known,
  AUCvalue += thisAUC (the newest segment); else AUCvalue = 0.
  AUCvalue is written nowhere else (only reset, canvas.py:7920).
- profileAUC, main.py:24554: for i in range(st, ed):
  calcAUC(i), with st = AUCbegin_idx (or the start arg) and ed =
  min(len(timex), end or timeindex[6]). It counts the segments
  ENDING at i for i in [st, ed), in C-seconds, returned /60.
- Saved AUC: computedProfileInformation, main.py:16808, calls
  self.ts() with no args, so st = AUCbegin_idx and ed = the DROP
  index. Phase AUCs: main.py:16832-16843, ts(charge, dry),
  ts(dry, fcs), ts(fcs, drop). The computed block is rebuilt on
  load, main.py:17225.
- Defaults: canvas.py:657 AUCbegin=1 (TP), :658 AUCbase=212 F,
  :659 AUCbaseFlag=False. Our tags match: AucBegin 'TP',
  AucBaseTempF 212.0, AucBaseFromEvent False
  (setup_roastery_v4_tags.py:363-368).
- Event stamps are sample indices: markDryEnd sets
  timeindex[1] = len(timex)-1 (canvas.py:14404); same shape for
  the other marks (markCharge canvas.py:14215/14229).
- TP detection: checkTPalarmtime, canvas.py:4415, needs more
  than 20 s since charge and the sample 5 ticks back a local
  minimum below the latest; findTPint, util.py:974, returns the
  index of the lowest BT between charge and FCs/drop.
- Units: Artisan computes AUC in C (calcAUC converts temps with
  convertTemp(mode, 'C'); the statistics label reads C*min,
  canvas.py:11640), so Artisan C-min values are F-min values
  times 5/9. Our AucTargetFMin default 1152.0 is 640 x 9/5,
  Artisan's AUCtarget 640 C-min. The shapes below use F temps
  and the F base directly; the segment sets are identical in
  either unit.

What the shapes mean for the begin event:
- profileAUC includes, in full, the segment ENDING at the begin
  sample. Neither Artisan's live path nor our clipped form counts
  any of it. The round 9 note said both Artisan paths include
  that segment; that is wrong for the live path, and this suite
  proves it: the segment ending at the begin sample was the
  newest segment on the tick BEFORE the event was stamped, when
  updateAUC still held AUCvalue at 0.
- updateAUC includes, in full, the segment ending at DROP (added
  on the drop tick, when the begin was long known) and any
  segments after drop while recording continues. profileAUC
  excludes the segment ending at drop (its loop stops at i =
  ed-1). So the two Artisan paths differ at BOTH ends.
- With the default TP begin, the live path additionally misses
  the whole stretch from TP to detection (detection needs more
  than 20 s since charge), because AUCvalue is held at 0 until
  TPalarmtimeindex is set on the detection tick.
"""
import ast
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
from api27m import api

CORE = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
        'project/Roastery/ignition/script-python/roastery/'
        'core/code.py')
BATCHES = ('/home/hatch/workspace/ignition-coffee-lab/roastery/'
           'project/Roastery/ignition/script-python/roastery/'
           'batches/code.py')
GW = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker/'
      'data/projects/Roastery/ignition/script-python/roastery/')
PASSES = [0]
FAILS = []


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if detail != '' else '',
          flush=True)
    if not cond:
        FAILS.append(name)


def extract_fn(path, name):
    src = open(path).read()
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            ns = {}
            exec(compile(ast.Module(body=[n], type_ignores=[]),
                         path, 'exec'), ns)
            return ns[name]
    raise AssertionError('%s not found in %s' % (name, path))


def exact_integral(points, begin_sec, base, end_sec=None):
    """Independently written exact integral of the piecewise
    linear curve above base, from begin_sec to end_sec."""
    total = 0.0
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t1 <= begin_sec or t1 <= t0:
            continue
        a = max(t0, begin_sec)
        b = t1 if end_sec is None else min(t1, end_sec)
        if b <= a:
            continue
        va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
        vb = v0 + (v1 - v0) * (b - t0) / (t1 - t0)
        avg = (va + vb) / 2.0
        if avg > base:
            total += (avg - base) * (b - a) / 60.0
    return total


def seg_area(t0, v0, t1, v1, base):
    """Artisan calcAUC for one whole segment, main.py:24513."""
    ta = (max(0.0, v0) + max(0.0, v1)) / 2.0
    return max(0.0, ta - base) * (t1 - t0) / 60.0


def seg_part_area(t0, v0, t1, v1, a, b, base):
    """Area of one segment above base over the subrange [a, b]."""
    va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
    vb = v0 + (v1 - v0) * (b - t0) / (t1 - t0)
    avg = (va + vb) / 2.0
    if avg <= base:
        return 0.0
    return (avg - base) * (b - a) / 60.0


def artisan_profile(points, begin_idx, drop_idx, base):
    """Artisan profileAUC, main.py:24554: segments ending at i
    for i in [begin_idx, drop_idx)."""
    total = 0.0
    ed = min(len(points), drop_idx)
    for i in range(begin_idx, ed):
        if i <= 0:
            continue
        t0, v0 = points[i - 1]
        t1, v1 = points[i]
        total += seg_area(t0, v0, t1, v1, base)
    return total


def artisan_live(points, begin_idx, base):
    """Artisan updateAUC accumulation, main.py:24493, for a user
    stamped begin: the begin sample is index begin_idx, stamped
    between tick begin_idx and begin_idx+1, so ticks begin_idx+1
    on add segments (begin_idx -> begin_idx+1) on."""
    total = 0.0
    for i in range(begin_idx + 1, len(points)):
        t0, v0 = points[i - 1]
        t1, v1 = points[i]
        total += seg_area(t0, v0, t1, v1, base)
    return total


def artisan_live_tp(points, detect_idx, base):
    """Artisan updateAUC with the default TP begin: TP is
    detected on tick detect_idx and TPalarmtimeindex is set to
    the past TP index on that tick (canvas.py:4917), so only
    the newest segment from that tick on is ever added."""
    total = 0.0
    for i in range(detect_idx, len(points)):
        t0, v0 = points[i - 1]
        t1, v1 = points[i]
        total += seg_area(t0, v0, t1, v1, base)
    return total


def begin_idx(points, begin_sec):
    """Artisan event stamp: the last sample at or before the
    press (markDryEnd, canvas.py:14404)."""
    k = 0
    for i, (t, v) in enumerate(points):
        if t <= begin_sec:
            k = i
        else:
            break
    return k


def read_1042_series():
    pw = os.path.join(os.path.expanduser('~'), 'workspace',
                      'ignition-lab', '.roastery-pgpass')
    env = dict(os.environ)
    env['PGPASSWORD'] = open(pw).read().strip()
    env['PATH'] = '/usr/bin:/bin'
    r = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A', '-F', ',',
         '-c', 'select t_offset_sec, bean_temp_f from batch_series '
               'where batch_number=1042 order by t_offset_sec'],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return None
    return [(float(a), float(b)) for a, b in
            (line.split(',') for line in r.stdout.strip().split('\n')
             if line.strip())]


def db_counts():
    pw = os.path.join(os.path.expanduser('~'), 'workspace',
                      'ignition-lab', '.roastery-pgpass')
    env = dict(os.environ)
    env['PGPASSWORD'] = open(pw).read().strip()
    env['PATH'] = '/usr/bin:/bin'
    r = subprocess.run(
        ['psql', '-h', 'localhost', '-U', 'ignition', '-d', 'db',
         '-t', '-A',
         '-c', 'select (select count(*) from batches), '
               '(select count(*) from batch_series), '
               '(select count(*) from batch_events)'],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return None
    return tuple(int(x) for x in r.stdout.strip().split('|'))


def md5(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


def fn_source(path, name):
    src = open(path).read()
    tree = ast.parse(src)
    lines = src.splitlines()
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return '\n'.join(lines[n.lineno - 1:n.end_lineno])
    raise AssertionError('%s not found in %s' % (name, path))


def main():
    auc_between = extract_fn(CORE, 'auc_between')
    auc_range = extract_fn(BATCHES, '_auc_range')
    curve_auc = extract_fn(BATCHES, 'curve_auc')

    # Regression guard for the HUNT-62 fix (round 9 numbers).
    pts = [(float(t), 200.0 + 0.4 * t) for t in range(0, 301)]
    check('HUNT-62 fix holds: 1 s samples, begin 70.5, base 200',
          abs(auc_between(pts, 70.5, 200.0) - 283.4325) < 0.001,
          'got %.4f want 283.4325' % auc_between(pts, 70.5, 200.0))
    grid = [(float(t), 200.0 + 0.4 * t) for t in range(0, 301, 30)]
    check('HUNT-62 fix holds: 30 s grid, begin 75, base 200',
          abs(auc_between(grid, 75, 200.0) - 281.25) < 0.001,
          'got %.2f want 281.25' % auc_between(grid, 75, 200.0))

    # RoasterSim full shape, 1 s samples, 600 s cycle.
    sim = []
    for t in range(0, 601):
        if t <= 150:
            v = 200.0 + 185.0 * t / 150.0
        else:
            v = 385.0 + 50.0 * (t - 150) / 450.0
        sim.append((float(t), v))
    dry_t = (300.0 - 200.0) * 150.0 / 185.0
    fc_t = 150.0
    drop_t = 150.0 + (419.0 - 385.0) * 450.0 / 50.0
    drop_idx = int(drop_t)
    simd = [p for p in sim if p[0] <= drop_t]
    full = exact_integral(sim, 0.0, 212.0, drop_t)
    print('sim full roast AUC above 212, charge to drop: %.2f F-min'
          % full, flush=True)

    cases = []
    for label, points, bsec, drop in (
            ('A synthetic 1 s, Dry End 70.5', pts, 70.5, 300),
            ('B synthetic 30 s, Dry End 75', grid, 75.0, 10),
            ('D sim Dry End %.2f' % dry_t, simd, dry_t, drop_idx),
            ('D sim FCs 150', simd, fc_t, drop_idx),
            ('D sim TP 0', simd, 0.0, drop_idx)):
        k = begin_idx(points, bsec)
        ours = auc_between(points, bsec, 212.0)
        exact = exact_integral(points, bsec, 212.0,
                               points[-1][0])
        prof = artisan_profile(points, k, drop, 212.0)
        live = artisan_live(points, k, 212.0)
        cases.append((label, points, bsec, k, drop, ours, exact,
                      prof, live))
        print('%-26s ours=%10.4f exact=%10.4f profile=%10.4f '
              'live=%10.4f' % (label, ours, exact, prof, live),
              flush=True)
        check(label + ': clipped live equals the exact integral',
              abs(ours - exact) < 0.001,
              'ours %.4f exact %.4f' % (ours, exact))
        # profile minus live is exactly the begin-end segment
        # minus the drop-end segment: the two end effects.
        seg_begin = (seg_area(points[k - 1][0], points[k - 1][1],
                              points[k][0], points[k][1], 212.0)
                     if k > 0 else 0.0)
        seg_drop = seg_area(points[drop - 1][0],
                            points[drop - 1][1],
                            points[drop][0], points[drop][1], 212.0)
        check(label + ': profile-live is begin segment minus '
              'drop segment',
              abs((prof - live) - (seg_begin - seg_drop)) < 0.001,
              'profile-live %.4f, segments %+.4f'
              % (prof - live, seg_begin - seg_drop))
        # live minus ours is exactly the pre-begin part of the
        # segment straddling begin_sec.
        tk, vk = points[k]
        tk1, vk1 = points[k + 1]
        pre = seg_part_area(tk, vk, tk1, vk1, tk, bsec, 212.0)
        check(label + ': live-ours is the pre-begin part of the '
              'straddling segment',
              abs((live - ours) - pre) < 0.001,
              'live-ours %.4f, pre-begin %.4f' % (live - ours, pre))

    # Materiality on 1 s sampling: the Artisan differences are a
    # fraction of a percent of a full roast AUC (~1171 F-min).
    for label, points, bsec, k, drop, ours, exact, prof, live in cases:
        if label.startswith('B'):
            continue
        check(label + ': Artisan live within 0.35 F-min of ours',
              abs(live - ours) <= 0.35,
              'live-ours %+.4f' % (live - ours))
        check(label + ': Artisan profile within 4.0 F-min of ours',
              abs(prof - ours) <= 4.0,
              'profile-ours %+.4f' % (prof - ours))

    # Default TP begin: Artisan live misses the TP to detection
    # stretch (detection needs more than 20 s since charge).
    live_tp = artisan_live_tp(simd, 21, 212.0)
    exact_tp = exact_integral(simd, 0.0, 212.0, drop_t)
    print('TP begin: Artisan live %.4f, exact from TP %.4f, miss '
          '%.4f' % (live_tp, exact_tp, exact_tp - live_tp),
          flush=True)
    check('TP begin: Artisan live misses 0.5 to 1.5 F-min before '
          'detection',
          0.5 < (exact_tp - live_tp) < 1.5,
          'miss %.4f' % (exact_tp - live_tp))
    check('TP begin: our clipped live is exact from the TP second',
          abs(auc_between(simd, 0.0, 212.0) - exact_tp) < 0.001,
          'ours %.4f exact %.4f'
          % (auc_between(simd, 0.0, 212.0), exact_tp))

    # Saved headline AUC: the gap to Artisan ts() is the base
    # definition (charge temp 200 vs fixed 212), not the straddle.
    ours_saved = curve_auc([{'t': t, 'bt': v} for t, v in simd],
                           200.0)
    art_saved = artisan_profile(simd, 0, drop_idx, 212.0)
    total_gap = ours_saved - art_saved
    base_part = (212.0 - 200.0) * drop_t / 60.0
    print('saved headline: ours %.2f, Artisan ts() %.2f, gap %.2f, '
          'base part %.2f' % (ours_saved, art_saved, total_gap,
                              base_part), flush=True)
    check('saved headline gap is 90 to 97 F-min, not a straddle',
          90.0 < total_gap < 97.0, 'gap %.2f' % total_gap)
    check('saved headline gap is over 90 percent base definition',
          base_part > 0.90 * total_gap,
          'base %.2f of gap %.2f' % (base_part, total_gap))

    # Phase AUCs: ours (clipped to the event seconds) vs Artisan
    # ts() ranges, each within 2.0 F-min on the sim curve.
    for name, ta, tb in (('Drying', 0.0, dry_t),
                         ('Maillard', dry_t, fc_t),
                         ('Development', fc_t, drop_t)):
        ka = begin_idx(simd, ta)
        kb = begin_idx(simd, tb)
        ours_p = auc_range(simd, ta, tb, 212.0)
        art_p = artisan_profile(simd, ka, kb, 212.0)
        print('phase %-11s ours=%8.4f artisan=%8.4f diff=%+7.4f'
              % (name, ours_p, art_p, art_p - ours_p), flush=True)
        check('phase %s AUC within 2.0 F-min of Artisan ts()'
              % name, abs(art_p - ours_p) <= 2.0,
              'diff %+.4f' % (art_p - ours_p))

    # Real seeded batch 1042, counterfactual Dry End at 10.5 s.
    pts1042 = read_1042_series()
    if pts1042 is None or len(pts1042) != 21:
        print('SKIP | batch 1042 series unreadable, case C skipped',
              flush=True)
    else:
        doc_auc = curve_auc([{'t': t, 'bt': v}
                             for t, v in pts1042], pts1042[0][1])
        print('1042: %d samples, %.1f to %.1f F, recomputed doc auc '
              '%.4f (stored 1.3576)' % (len(pts1042), pts1042[0][1],
                                        pts1042[-1][1], doc_auc),
              flush=True)
        check('1042 recomputed doc auc within 0.05 of stored',
              abs(doc_auc - 1.3576) < 0.05, 'got %.4f' % doc_auc)
        k = begin_idx(pts1042, 10.5)
        ours = auc_between(pts1042, 10.5, 212.0)
        exact = exact_integral(pts1042, 10.5, 212.0)
        prof = artisan_profile(pts1042, k, 20, 212.0)
        live = artisan_live(pts1042, k, 212.0)
        print('C 1042 Dry End 10.5: ours=%.4f exact=%.4f '
              'profile=%.4f live=%.4f' % (ours, exact, prof, live),
              flush=True)
        check('C 1042: clipped live equals the exact integral',
              abs(ours - exact) < 0.001,
              'ours %.4f exact %.4f' % (ours, exact))
        check('C 1042: Artisan live within 0.35 F-min of ours',
              abs(live - ours) <= 0.35, 'live-ours %+.4f'
              % (live - ours))
        check('C 1042: Artisan profile within 4.0 F-min of ours',
              abs(prof - ours) <= 4.0, 'profile-ours %+.4f'
              % (prof - ours))

    # Read only live verification: trial, tags, database counts,
    # and repo vs gateway library copies.
    try:
        st, trial = api('GET', '/trial')
        left = trial.get('trialSecondsLeft', 0)
        print('trial: %s s left, expired=%s' % (left,
                                                trial.get('expired')),
              flush=True)
        check('gateway trial healthy (over 600 s left)',
              (trial.get('trialSecondsLeft') or 0) > 600,
              '%s s left' % left)
    except Exception as e:
        check('gateway trial healthy (over 600 s left)', False,
              str(e)[:120])
    try:
        st, out = api('GET', '/tags/read', body=json.dumps(
            {'tags': ['[default]Roastery/CurrentBatch/State',
                      '[default]Roastery/CurrentBatch/BatchNumber',
                      '[default]Roastery/AppSettings/ThemeMode',
                      '[default]Roastery/CurrentBatch/AucBegin',
                      '[default]Roastery/CurrentBatch/AucBaseTempF']}))
        vals = [r.get('value') for r in out['results']]
        print('tags: State=%s BatchNumber=%s ThemeMode=%s '
              'AucBegin=%s AucBaseTempF=%s' % tuple(vals), flush=True)
        check('lab at clean Idle, batch 1042, System theme',
              vals[0] == 'Idle' and vals[1] == 1042
              and vals[2] == 'System',
              str(vals[:3]))
        check('AUC defaults match Artisan (TP begin, 212 F base)',
              vals[3] == 'TP' and vals[4] == 212.0, str(vals[3:]))
    except Exception as e:
        check('lab tags readable', False, str(e)[:120])
    counts = db_counts()
    if counts is None:
        print('SKIP | database counts unreadable', flush=True)
    else:
        print('database: %d batches, %d series, %d events'
              % counts, flush=True)
        check('database at 7 batches, 101 series, 0 events',
              counts == (7, 101, 0), str(counts))
    # The AUC proof reads the repo files. A parallel worker may
    # have the repo library ahead of the gateway copy mid round,
    # so the whole file md5 is informational only; what this
    # suite needs is the AUC functions themselves identical.
    for mod in ('core', 'batches'):
        same = (md5(CORE if mod == 'core' else BATCHES)
                == md5(GW + '%s/code.py' % mod))
        print('INFO | repo vs gateway %s/code.py md5 %s'
              % (mod, 'match' if same else 'DIFFER (parallel '
                 'worker mid flight)'), flush=True)
    for path, gw_path, name in (
            (CORE, GW + 'core/code.py', 'auc_between'),
            (BATCHES, GW + 'batches/code.py', '_auc_range'),
            (BATCHES, GW + 'batches/code.py', 'curve_auc')):
        check('AUC function %s identical in repo and gateway'
              % name,
              fn_source(path, name) == fn_source(gw_path, name),
              'source match')

    print('RESULT: %d PASS, %d FAIL'
          % (PASSES[0], len(FAILS)), flush=True)
    if FAILS:
        print('failures:', FAILS, flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
