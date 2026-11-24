#!/usr/bin/env python3
"""Round 16 fresh hunting pass, HUNT-111 to HUNT-120.

New defects this round (found by the round 16 hunters, fixed in
the library and named queries, proven here statically and live
through gateway scratch snippets in the scratch_run.py style):

  HUNT-111  A fault during the series write of Save Batch or of
            an .alog import left the batch row in the log with
            no curve, the note claimed nothing was written, and
            the already saved / roastUUID guards blocked every
            retry. Both paths now delete the just inserted row
            (best effort) and re raise, so a retry saves cleanly;
            if the delete also fails the save note says the
            batch is in the log without its curve.
  HUNT-112  The saved batch AUC included post Drop cooling
            samples; curve_auc now clips at the Drop elapsed
            time (crossing segment interpolated), matching the
            live AUC and the Artisan export.
  HUNT-113  Artisan import treated gal/qt/pt/cup volumes as
            millilitres (factor 1.0 fallthrough) and every non
            litre density volume as ml. VOLUMES now carries
            Artisan's volume_units and _density_from_list
            converts through it.
  HUNT-114  .alog export wrote the imported weight list back
            verbatim, discarding editor edits, and copied the
            imported density list from settings. Export now
            builds weight from the edited metadata and rebuilds
            density from the stored DensityGL.
  HUNT-115  The BatchDetail press log ordered by pressed_at
            (write time), so a reconciled press sorted after
            later presses. Events/SelectByBatch now orders by
            t_offset_sec, press_counter, id (roast order).
  HUNT-116  The editor never maintained the relational
            roast_end, and manual create stamped start = end =
            creation instant next to the typed total. Update
            now carries roast_end from the document, and create
            seeds roastStart before applying events so the
            derived end lands in the insert.
  HUNT-117  parse_mmss accepted '04:90' as 330 and '-1:30' as
            -30; the create path could save negative event
            times. Components are range checked and
            _apply_events rejects negative times.
  HUNT-118  The offline turning point scan in _phase_analysis
            stopped at Dry End (or half the roast) and skipped
            the charge sample, so a monotonic imported curve
            showed no turning point on the detail page while
            its .alog export reported the charge point. The
            scan now mirrors Artisan findTPint (charge to FC
            Start, capped at Drop, charge sample included).
  HUNT-119  The alarm banner text (every active alarm joined
            with ' | ') wrapped to two lines at 360px with the
            default alarm set near Drop and GREW its reserved
            38px strip, shifting the whole page in the last
            minute of the roast. The banner text is now single
            line with an ellipsis in the advanced stylesheet,
            so the strip stays one line tall.
  HUNT-120  The phone chart head was hard sized to 44px for
            a title plus the background (ghost) label; a ghost
            with a realistic long bean name wrapped the label
            to two lines and spilled 4px past the head into
            the chart's marker label band. The stacked head
            now sizes to its content (basis auto).

Also probed and dismissed by measurement this round: the
App Settings (420) and Batch Editor (480) docks on a 360px
phone (Perspective clamps the dock to the viewport: measured
left 0, width 360), the BatchDetail MidRow 820px stack
(SummaryCard scrollHeight equals clientHeight), the Settings
page and Log page at 360 in both themes (document
scrollWidth 360, no clipped leaves, all 7 batches rendered),
and the BatchDetail presses heading (no vertical clipping).

Run with wsvenv python from ~/workspace/ignition-lab. Leaves
the lab clean (7 batches, 101 series, 0 events).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import verify_roastery_polish2 as P

REPO = '/home/hatch/workspace/ignition-coffee-lab'
BATCHES = (REPO + '/roastery/project/Roastery/ignition/'
           'script-python/roastery/batches/code.py')
ARTISAN = (REPO + '/roastery/project/Roastery/ignition/'
           'script-python/roastery/artisan/code.py')
NQ = (REPO + '/roastery/project/Roastery/ignition/named-query'
      '/Roastery')
LAB = '/home/hatch/workspace/ignition-lab'
FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:220]) if (detail and not cond) else '')
    if not cond:
        FAILS.append(name)


def approx(a, b, tol):
    return a is not None and abs(float(a) - float(b)) <= tol


def src(path):
    with open(path) as f:
        return f.read()


def run_snippet(name, body):
    path = '/tmp/r16_%s.jy' % name
    with open(path, 'w') as f:
        f.write(body)
    out = subprocess.run(
        [os.path.join(LAB, 'wsvenv/bin/python'),
         os.path.join(LAB, 'scratch_run.py'), path],
        capture_output=True, text=True, timeout=300)
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError('snippet %s produced no output: %s'
                           % (name, out.stderr[-400:]))
    return json.loads(lines[-1])


def static_checks():
    b = src(BATCHES)
    a = src(ARTISAN)
    check('HUNT-111 save path compensates with NQ_DELETE',
          'partial' in b and '_run(NQ_DELETE' in b)
    check('HUNT-111 import path compensates via delete_batch',
          'batches.delete_batch(number)' in a)
    check('HUNT-112 curve_auc takes end_sec and build_document '
          'passes DropElapsedSec',
          'def curve_auc(points, charge_temp_f, end_sec=None)' in b
          and "vals['DropElapsedSec'])" in b)
    check('HUNT-113 VOLUMES carries gal/qt/pt/cup factors',
          "'gal': 3785.411784" in a and "'cup': 236.5882365" in a)
    check('HUNT-113 density converts through VOLUMES',
          'liters = vol * VOLUMES.get(vunit, 1.0) / 1000.0' in a)
    check('HUNT-114 export no longer prefers weightRaw verbatim',
          "profile['weight'] = list(settings['weightRaw'])"
          not in a)
    check('HUNT-114 export rebuilds density from DensityGL',
          "profile['density'] = [_num(meta.get('DensityGL'))" in a)
    upd = src(os.path.join(NQ, 'Batches/Update/query.sql'))
    check('HUNT-116 Update query maintains roast_end',
          'roast_end = :roast_end' in upd)
    check('HUNT-116 update submit passes roast_end',
          "'roast_end': end_param" in b)
    create_body = b.split('def _create_submit')[1].split(
        '\n\n\n')[0]
    check('HUNT-116 create seeds roastStart before events',
          "doc['roastStart'] = _iso(now)" in create_body
          and create_body.index("doc['roastStart'] = _iso(now)")
          < create_body.index('err = _apply_events(doc, event)'))
    sel = src(os.path.join(NQ, 'Events/SelectByBatch/query.sql'))
    check('HUNT-115 press log orders by roast time',
          'ORDER BY t_offset_sec, press_counter, id' in sel)
    check('HUNT-117 parse_mmss range checks components',
          'seconds >= 60' in b and 'total < 0' in b)
    check('HUNT-118 TP scan caps at FC/Drop, charge included',
          'cap = fc_t if cap is None else min(cap, fc_t)' in b
          and 't >= dry_t' not in b.split('def _phase_analysis')[1]
          .split('def ')[0])


SNIPPET_PURE = """
\timport roastery.batches as B
\timport roastery.artisan as A
\tout = {}
\tout['mmss_0430'] = B.parse_mmss('04:30')
\tfor txt in ('04:90', '-1:30', '-30'):
\t\ttry:
\t\t\tB.parse_mmss(txt)
\t\t\tout['reject_' + txt] = False
\t\texcept Exception:
\t\t\tout['reject_' + txt] = True
\tdoc = {'events': {}, 'metadata': {}, 'phases': {}, 'totalSec': 0}
\terr = B._apply_events(doc, {'Ev_dryEnd_t': '-5:00',
\t\t'Ev_fcStart_t': '1:00', 'Ev_drop_t': '2:00'})
\tout['apply_negative_rejected'] = err is not None
\tdoc3 = {'roastStart': '2026-11-24T10:00:00',
\t\t'events': {'drop': {'t': 600, 'ts': None, 'tempF': 410.0}},
\t\t'metadata': {}, 'phases': {}, 'totalSec': 600}
\tB._apply_events(doc3, {'Ev_drop_t': '12:00'})
\tout['moved_roast_end'] = doc3.get('roastEnd')
\tpts = [{'t': 0, 'bt': 392.0}, {'t': 600, 'bt': 415.0},
\t\t{'t': 630, 'bt': 410.0}, {'t': 660, 'bt': 395.0}]
\tout['auc_unclipped'] = B.curve_auc(pts, 392.0)
\tout['auc_clipped'] = B.curve_auc(pts, 392.0, 600)
\tout['density_cup'] = A._density_from_list([200, 'g', 1, 'cup'])
\tout['gal_ml'] = 0.5 * A.VOLUMES['gal']
\tev = {'charge': {'t': 0, 'tempF': 392.0},
\t\t'dryEnd': {'t': 240, 'tempF': 300.0},
\t\t'fcStart': {'t': 480, 'tempF': 390.0}, 'fcEnd': None,
\t\t'scStart': None, 'scEnd': None,
\t\t'drop': {'t': 600, 'tempF': 415.0}, 'custom': []}
\tdoc2 = {'events': ev, 'metadata': {}, 'totalSec': 600,
\t\t'phases': {}}
\tmono = [(t, 392.0 + 23.0 * t / 600.0)
\t\tfor t in range(0, 601, 30)]
\trows, tp_text, extra = B._phase_analysis(doc2, mono)
\tout['tp_text'] = tp_text
\tout['total_ror_set'] = extra.get('totalRor') is not None
\tRESULT = out
"""

SNIPPET_DB = """
\timport roastery.batches as B
\timport roastery.artisan as A
\timport uuid
\tout = {}
\ttext = open('/home/hatch/workspace/ignition-lab/'
\t\t'artisan-fixtures/sample-roast.alog').read()
\tprof = A.parse_alog(text)
\tprof['roastUUID'] = 'r16-' + str(uuid.uuid4())
\tprof['volume'] = [0.5, 0.65, 'gal']
\tprof['density'] = [200, 'g', 1, 'cup']
\tdoc, points, params = A.profile_to_batch(prof, 0)
\tout['volume_in_ml'] = doc['metadata']['VolumeInMl']
\tout['density_gl'] = doc['metadata']['DensityGL']
\torig = A._insert_points
\tdef boom(n, pts):
\t\traise RuntimeError('injected series fault')
\tA._insert_points = boom
\tfault = False
\ttry:
\t\tA.import_profile(prof, 'r16-fault.alog')
\texcept Exception:
\t\tfault = True
\tA._insert_points = orig
\tout['fault_raised'] = fault
\tout['dupe_after_fault'] = A._already_imported(
\t\tprof['roastUUID'])
\tnumber, msg = A.import_profile(prof, 'r16-fault.alog')
\tout['retry_number'] = number
\tds = B._run(B.NQ_SERIES_SELECT,
\t\t{'batch_number': int(number)})
\tout['retry_series_rows'] = ds.rowCount
\tb = B.get_batch(int(number))
\td = b['document']
\td['metadata']['ChargeWeightG'] = 250.0
\tB._run(B.NQ_UPDATE, {'batch_number': int(number),
\t\t'bean_name': d.get('beanName'),
\t\t'drop_temp_f': d.get('dropTempF'),
\t\t'roast_end': b['roastEnd'],
\t\t'data': system.util.jsonEncode(d)})
\tprof2 = A.batch_to_profile(B.get_batch(int(number)))
\tout['export_weight0'] = prof2['weight'][0]
\tdens = prof2.get('density') or []
\tout['export_density_gl'] = (
\t\tdens[0] if len(dens) > 3 and dens[3] == 'ml'
\t\tand dens[2] == 1000.0 else None)
\tB.delete_batch(int(number))
\tout['cleaned'] = B.get_batch(int(number)) is None
\tsystem.db.runNamedQuery('Roastery/Events/InsertPress',
\t\t{'batch_number': 9990, 'action': 'B-press',
\t\t't_offset_sec': 120, 'bean_temp_f': 400.0,
\t\t'rate_of_rise_f': 10.0, 'fan_level': 5, 'heat_level': 5,
\t\t'press_counter': 2})
\tsystem.db.runNamedQuery('Roastery/Events/InsertPress',
\t\t{'batch_number': 9990, 'action': 'A-press',
\t\t't_offset_sec': 100, 'bean_temp_f': 395.0,
\t\t'rate_of_rise_f': 9.0, 'fan_level': 5, 'heat_level': 5,
\t\t'press_counter': 1})
\tds = B._run(B.NQ_EVENTS_SELECT, {'batch_number': 9990})
\tout['press_order'] = [ds.getValueAt(r, 't_offset_sec')
\t\tfor r in range(ds.rowCount)]
\tB._run(B.NQ_EVENTS_DELETE, {'batch_number': 9990})
\tRESULT = out
"""


def live_checks():
    r = run_snippet('r16_pure', SNIPPET_PURE)
    check('HUNT-117 live: 04:30 parses to 270',
          r.get('mmss_0430') == 270, r.get('mmss_0430'))
    check('HUNT-117 live: 04:90, -1:30 and -30 all rejected',
          r.get('reject_04:90') and r.get('reject_-1:30')
          and r.get('reject_-30'), r)
    check('HUNT-117 live: create path rejects negative Dry End',
          r.get('apply_negative_rejected') is True)
    check('HUNT-116 live: moving Drop derives roastEnd',
          r.get('moved_roast_end') == '2026-11-24T10:12:00',
          r.get('moved_roast_end'))
    check('HUNT-112 live: unclipped AUC is the old 130.5',
          approx(r.get('auc_unclipped'), 130.5, 0.01),
          r.get('auc_unclipped'))
    check('HUNT-112 live: drop-clipped AUC is 115.0',
          approx(r.get('auc_clipped'), 115.0, 0.01),
          r.get('auc_clipped'))
    check('HUNT-113 live: density [200 g, 1 cup] is ~845 g/L',
          approx(r.get('density_cup'), 845.35, 1.0),
          r.get('density_cup'))
    check('HUNT-113 live: 0.5 gal is 1892.7 ml',
          approx(r.get('gal_ml'), 1892.7, 0.1), r.get('gal_ml'))
    check('HUNT-118 live: monotonic curve TP is the charge point',
          str(r.get('tp_text', '')).startswith('392 F at 00:00'),
          r.get('tp_text'))
    check('HUNT-118 live: total RoR is computed from that TP',
          r.get('total_ror_set') is True)

    r = run_snippet('r16_db', SNIPPET_DB)
    check('HUNT-113 live: profile volume gal converts to ml',
          approx(r.get('volume_in_ml'), 1892.7, 0.1),
          r.get('volume_in_ml'))
    check('HUNT-113 live: profile density cup converts to g/L',
          approx(r.get('density_gl'), 845.35, 1.0),
          r.get('density_gl'))
    check('HUNT-111 live: injected series fault raises',
          r.get('fault_raised') is True)
    check('HUNT-111 live: faulted import leaves no batch behind',
          r.get('dupe_after_fault') is None,
          r.get('dupe_after_fault'))
    check('HUNT-111 live: retry import succeeds with its curve',
          r.get('retry_number') is not None
          and (r.get('retry_series_rows') or 0) > 0,
          (r.get('retry_number'), r.get('retry_series_rows')))
    check('HUNT-114 live: export weight uses the edited 250 g',
          approx(r.get('export_weight0'), 250.0, 0.01),
          r.get('export_weight0'))
    check('HUNT-114 live: export density rebuilt from DensityGL',
          approx(r.get('export_density_gl'), 845.35, 1.0),
          r.get('export_density_gl'))
    check('HUNT-111/114 cleanup: scratch batch deleted',
          r.get('cleaned') is True)
    check('HUNT-115 live: press log returns roast order',
          r.get('press_order') == [100, 120], r.get('press_order'))


BANNER_JS = """
() => {
  const els = [...document.querySelectorAll('*')].filter(
    el => (el.textContent || '').includes('First crack watch'));
  if (!els.length) return {found: false};
  const leaf = els[els.length - 1];
  const r = leaf.getBoundingClientRect();
  return {found: true, h: Math.round(r.height)};
}
"""

HEAD_JS = """
() => {
  const els = [...document.querySelectorAll('*')].filter(
    el => el.children.length === 0 &&
          (el.textContent || '').startsWith('Background:'));
  if (!els.length) return {found: false};
  const chip = els[els.length - 1];
  let head = chip;
  for (let i = 0; i < 5 && head.parentElement; i++) {
    head = head.parentElement;
    if ((head.className || '').toString().includes('flex')) break;
  }
  const cr = chip.getBoundingClientRect();
  const hr = head.getBoundingClientRect();
  return {found: true, spill: Math.round(cr.bottom - hr.bottom)};
}
"""


def ui_checks():
    import verify_r5_detail_span as R5
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = R5.launch(pw)
        P.write_tags([('[default]Roastery/AppSettings/ThemeMode',
                       'Dark')])
        ctx = b.new_context(viewport={'width': 360, 'height': 780},
                            timezone_id='America/Denver')
        P.write_tags([
            ('[default]Roastery/CurrentBatch/AlarmText',
             'Bean temperature high | Drop approaching | '
             'First crack watch: listen for cracks'),
            ('[default]Roastery/CurrentBatch/AlarmActive', True),
            ('[default]Roastery/BackgroundLabel',
             'Batch 1042 - Ethiopia Guji Highlands Natural')])
        try:
            pg = R5.open_page(ctx, '/')
            pg.wait_for_timeout(3500)
            r = pg.evaluate(BANNER_JS)
            check('HUNT-119 live: worst case banner stays one line',
                  r.get('found') and (r.get('h') or 99) <= 22, r)
            r = pg.evaluate(HEAD_JS)
            check('HUNT-120 live: long ghost label stays in head',
                  r.get('found') and r.get('spill') is not None
                  and r['spill'] <= 0, r)
            pg.close()
        finally:
            P.write_tags([
                ('[default]Roastery/AppSettings/ThemeMode',
                 'System'),
                ('[default]Roastery/CurrentBatch/AlarmText', ''),
                ('[default]Roastery/CurrentBatch/AlarmActive',
                 False),
                ('[default]Roastery/BackgroundLabel', '')])
            ctx.close()
            b.close()


def main():
    static_checks()
    live_checks()
    ui_checks()
    counts = (P.psql('SELECT COUNT(*) FROM batches'),
              P.psql('SELECT COUNT(*) FROM batch_series'),
              P.psql('SELECT COUNT(*) FROM batch_events'))
    check('lab restored to 7 batches, 101 series, 0 events',
          counts == ('7', '101', '0'), counts)
    print('TOTAL %d PASS, %d FAIL' % (PASSES[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
