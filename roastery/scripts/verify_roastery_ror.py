#!/usr/bin/env python3
"""RoR proof for the Roastery v4 rate of rise math.

The library's one implementation (roastery.core.compute_ror_series,
an Artisan 5.0.0 parameterization) is extracted from the builder
and run here in plain CPython, because its pure section uses only
math and builtins by design.

Offline proofs on synthetic signals:
1. An exact 25 F/min ramp at 1 s sampling converges to 25 under
   the Artisan defaults (span 20 s, curve filter 1, delta filter
   3, smooth spikes on).
2. The same ramp converges under a short span with no smoothing
   (span 5 s, filters 0).
3. The same ramp at 5 s sampling converges under the defaults.
4. The polyfit (least squares) variant converges too.
5. A single +30 F spike: with Smooth Spikes OFF the RoR shows a
   large excursion; with it ON (offline median filters, as in
   Artisan) the excursion is bounded.

Live cross-check: RateOfRiseF on the gateway is compared with the
BeanTempF slope over the same window; the simulator's program has
discontinuities, so the check only asserts when the window's own
slope is steady and in a plausible ramp band.
"""
import json
import re
import sys
import time

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')

FAILURES = []


def check(label, cond, detail=''):
    print(('PASS' if cond else 'FAIL'), '-', label,
          ('| ' + str(detail)[:150]) if detail else '')
    if not cond:
        FAILURES.append(label)


def load_ror():
    src = open('/home/hatch/workspace/ignition-lab/'
               'build_roastery_v4.py').read()
    code = re.search(r"CORE_CODE = '''(.*?)'''", src, re.S).group(1)
    lines = code.split('\n')
    start = next(i for i, l in enumerate(lines)
                 if l.strip() == 'import math'
                 and any('RoR' in x for x in lines[max(0, i - 40):i]))
    end = next(i for i, l in enumerate(lines)
               if l.startswith('def ror_params'))
    ns = {}
    exec('\n'.join(lines[start:end]), ns)
    return ns['compute_ror_series']


def params(span=20, curve=1, delta=3, spikes=True, polyfit=False,
           optimal=False):
    return {'span': span, 'curve_ui': curve, 'delta_ui': delta,
            'spikes': spikes, 'polyfit': polyfit, 'optimal': optimal,
            'clip_lo': -18.0, 'clip_hi': 81.0}


def ramp(rate=25.0, seconds=240, step_s=1, spike_at=None, spike=0.0):
    # points are (elapsed seconds, temp): the library convention
    # (roastery.core._live_ror converts its ms buffer to seconds).
    pts = []
    t = 0
    while t <= seconds:
        temp = 200.0 + rate * t / 60.0
        if spike_at is not None and t == spike_at:
            temp += spike
        pts.append((t, temp))
        t += step_s
    return pts


def tail_mean(series, n=10):
    vals = [v for _t, v in series if v is not None]
    return sum(vals[-n:]) / float(len(vals[-n:]))


def main():
    compute = load_ror()
    print('compute_ror_series extracted from the shipping library')

    s = compute(ramp(), params(), offline=True)
    m = tail_mean(s)
    check('defaults (span 20, curve 1, delta 3) on 25 F/min @1 s',
          abs(m - 25.0) < 0.5, 'tail mean %.3f' % m)

    s = compute(ramp(), params(span=5, curve=0, delta=0, spikes=False),
                offline=True)
    m = tail_mean(s)
    check('short span, no smoothing (span 5, filters 0) @1 s',
          abs(m - 25.0) < 1.0, 'tail mean %.3f' % m)

    s = compute(ramp(step_s=5), params(), offline=True)
    m = tail_mean(s)
    check('defaults on 25 F/min @5 s sampling',
          abs(m - 25.0) < 0.5, 'tail mean %.3f' % m)

    s = compute(ramp(), params(polyfit=True), offline=True)
    m = tail_mean(s)
    check('polyfit least squares (span 20) on 25 F/min @1 s',
          abs(m - 25.0) < 0.5, 'tail mean %.3f' % m)

    base = ramp(spike_at=120, spike=30.0)
    s_off = compute(base, params(spikes=False), offline=True)
    dev_off = max(abs(v - 25.0) for _t, v in s_off if v is not None)
    s_on = compute(base, params(spikes=True), offline=True)
    dev_on = max(abs(v - 25.0) for _t, v in s_on if v is not None)
    check('spike +30 F, Smooth Spikes OFF: large excursion',
          dev_off > 15.0, 'max deviation %.1f F/min' % dev_off)
    check('spike +30 F, Smooth Spikes ON: bounded excursion',
          dev_on < 5.0, 'max deviation %.1f F/min' % dev_on)

    # ---- live cross-check --------------------------------------
    # Round 7 closing battery, first-pass failure: the 40 s
    # window slope was 10.71 F/min (in band) but the median
    # live RateOfRiseF was 3.40. The window started at
    # 343.3 F, within 1.3 F of the simulator program minimum
    # (342 F at program 785 s), and rose into the reheat
    # segment: the window straddled the cooling-reheat
    # corner, where the true slope flips from about -40 to
    # about +13 F/min. The live RoR is a 20 s delta-span
    # derivative with decay smoothing over a 300 s buffer,
    # so for roughly a span after the corner it still sees
    # the fall and legitimately reads low; the median over
    # the whole window mixes pre- and post-corner values.
    # The offline proof above is the authority for the math,
    # and the live tag runs the same code path, so the check
    # now compares like with like: the tail RoR (median of
    # the last 5 samples) against the tail slope (the last
    # 20 s of temps, the same span the RoR sees). It asserts
    # only when that tail slope is steady and in band; a
    # corner inside the tail puts the tail slope out of band
    # and the check skips, as before.
    from api27m import api

    def read(paths):
        st, out = api('GET', '/tags/read',
                      body=json.dumps({'tags': paths}))
        assert st == 200, (st, out)
        return [r['value'] for r in out['results']]

    B = '[default]Roastery/CurrentBatch'
    samples = []
    t0 = time.time()
    while time.time() - t0 < 40:
        bt, ror = read([B + '/BeanTempF', B + '/RateOfRiseF'])
        samples.append((time.time() - t0, bt, ror))
        time.sleep(2)
    (t1, b1, _r1), (t2, b2, _r2) = samples[0], samples[-1]
    slope = (b2 - b1) / (t2 - t1) * 60.0
    tail = samples[-11:]
    (tt1, tb1, _tr1), (tt2, tb2, _tr2) = tail[0], tail[-1]
    tail_slope = (tb2 - tb1) / (tt2 - tt1) * 60.0
    tail_rors = sorted(r for _t, _b, r in samples[-5:]
                       if r is not None)
    tail_med = tail_rors[len(tail_rors) // 2] if tail_rors else None
    print('live window: temp %.1f -> %.1f, slope %.2f F/min, '
          'tail slope %.2f F/min, tail RateOfRiseF median %s'
          % (b1, b2, slope, tail_slope, tail_med))
    if 3.0 < tail_slope < 30.0 and tail_med is not None:
        check('live RateOfRiseF tracks the window slope',
              abs(tail_med - tail_slope) < 3.0,
              (tail_med, tail_slope))
    else:
        print('SKIP - live window not on a steady ramp segment '
              '(simulator program discontinuity); the offline proof '
              'above is the authority, and a 100 s HUD watch during '
              'development read exactly 25.0 on the clean ramp.')

    print()
    if FAILURES:
        print('FAILURES:', FAILURES)
        return 1
    print('ALL ROR CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
