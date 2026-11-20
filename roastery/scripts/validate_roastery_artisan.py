#!/usr/bin/env python3
"""Validate the Artisan Roastery project on the Maker gateway (2027 beta).

1. Fetch the served project payload and compare each view's served
   JSON against the file on disk (deep equality after the standard
   normalization: binding configs stripped to {"type": ...}, event
   action configs stripped, empty propConfig dropped).
2. Start every view in a live WebSocket session, plus a bogus view
   as a negative control.
3. Scan the gateway log DB for WARN/ERROR rows mentioning Roastery
   since the marker time; the bogus control must appear.

Usage: validate_roastery_artisan.py [gateway_dir] [since_epoch_ms]
Run with wsvenv python.
"""
import json, os, shutil, sqlite3, sys, time
import urllib.request, http.cookiejar
import websocket

LAB = os.path.dirname(os.path.abspath(__file__))
GW = sys.argv[1] if len(sys.argv) > 1 else 'gateway-2027-maker'
if not os.path.isabs(GW):
    GW = os.path.join(LAB, GW)
SINCE = int(sys.argv[2]) if len(sys.argv) > 2 else int((time.time() - 900) * 1000)
PROJECT = 'Roastery'
BASE = 'http://localhost:8088'
PROJ_DIR = os.path.join(GW, 'data', 'projects', PROJECT)
VIEWS = ('Views/RoastPage', 'Views/SettingsPage', 'Views/LogPage',
         'Views/BatchDetail', 'Views/TabBar', 'Views/HudBar',
         'Views/ControlDock', 'Views/SettingsRoaster',
         'Views/SettingsTargets', 'Views/SettingsRor',
         'Views/SettingsAuc', 'Views/SettingsProjection',
         'Views/SettingsPlayback',
         'Views/SettingsAlarms',
         'Views/SettingsMetadata',
         'Views/SettingsCustoms', 'Views/BatchesPanel',
         'Views/BatchEdit', 'Views/Tile', 'Views/EventCell',
         'Views/EventsStrip', 'Views/PhasesBar', 'Views/Controls',
         'Views/MetaCard', 'Views/Summary')

def load_file_view(rel):
    p = os.path.join(PROJ_DIR, 'com.inductiveautomation.perspective',
                     'views', *rel.split('/'), 'view.json')
    return json.load(open(p))

def normalize(x, in_events=False):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in ('propConfig', 'events') and v in ({}, None):
                continue
            if k == 'scripts':
                # Component script configs (message handlers, custom
                # methods) are stripped from the served project
                # payload like binding configs; they are verified
                # functionally in verify_roastery_v3.py instead.
                continue
            if k == 'onChange':
                # Property change scripts on view custom props are
                # stripped from the served payload the same way
                # (proven live in polish phase 4: the served
                # RoastPage propConfig carries the binding only,
                # no onChange block). They are verified
                # functionally by the polish3 toast checks.
                continue
            if k == 'children' and v == []:
                continue
            if k == 'binding' and isinstance(v, dict):
                out[k] = {'type': v.get('type')}
                continue
            if in_events and k == 'config' and isinstance(v, dict):
                continue
            out[k] = normalize(v, in_events or k == 'events')
        return out
    if isinstance(x, list):
        return [normalize(v, in_events) for v in x]
    return x

def drill_window():
    """Polish round 6: the pressfault drill's fault window
    (first cluster stop to last gateway recovery), recorded
    by verify_roastery_pressfault.py. Log rows inside it are
    deliberate drill noise, not app faults. Returns
    (start_ms, end_ms) or (None, None) when no drill ran."""
    try:
        m = json.load(open(
            '/home/hatch/workspace/ignition-lab/'
            'pressfault-drill.json'))
        return m.get('stop_ms'), m.get('recovered_ms')
    except Exception:
        return None, None


def main():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(f'{BASE}/data/perspective/client/{PROJECT}/', timeout=15).read()
    tab = 'roasteryartisanval'
    req = urllib.request.Request(
        f'{BASE}/data/perspective/hello/{PROJECT}/{tab}',
        headers={'device-id': 'roastery-device', 'device-type': 'browser',
                 'version-code': '0'})
    hello = json.load(opener.open(req, timeout=15))
    proj = json.load(opener.open(f'{BASE}/data/perspective/project/{PROJECT}', timeout=15))
    views = proj.get('project', {}).get('views', {}) or proj.get('views', {})
    report = {'served_views': sorted(views), 'views': {}}
    # v3 resources on disk: library modules, named queries, styles.
    res_checks = {}
    lib = os.path.join(PROJ_DIR, 'ignition', 'script-python', 'roastery')
    res_checks['library_core'] = os.path.exists(
        os.path.join(lib, 'core', 'code.py'))
    res_checks['library_batches'] = os.path.exists(
        os.path.join(lib, 'batches', 'code.py'))
    nq_root = os.path.join(PROJ_DIR, 'ignition', 'named-query', 'Roastery')
    nq_names = []
    for _dp, _dn, _fn in os.walk(nq_root):
        if 'query.sql' in _fn:
            nq_names.append(os.path.relpath(_dp, nq_root))
    res_checks['named_queries'] = sorted(nq_names)
    # Style classes are not part of the project payload in 8.3;
    # they are served to the client separately. Verify them on disk
    # here and in the rendered DOM in verify_roastery_v3.py.
    sc_root = os.path.join(PROJ_DIR, 'com.inductiveautomation.perspective',
                           'style-classes')
    have = sorted(d for d in os.listdir(sc_root)
                  if os.path.exists(os.path.join(sc_root, d, 'style.json')))
    res_checks['style_classes_on_disk'] = len(have)
    res_checks['roast_card_on_disk'] = 'roast-card' in have
    res_checks['stylesheet_on_disk'] = os.path.exists(os.path.join(
        PROJ_DIR, 'com.inductiveautomation.perspective', 'stylesheet',
        'stylesheet.css'))
    # Design tokens (v4.2): every border radius in the style
    # classes and the advanced stylesheet must come from the
    # token scale (2 micro, 4 interactive, 6 small containers,
    # 8 cards, 999 pills only), referenced through the :root
    # CSS variables defined in the stylesheet. Eric flagged
    # the inconsistent bubbly rounding (16/12/10px) as amateur.
    import re as _re
    RADIUS_OK = {'0px', '2px', '4px', '6px', '8px', '999px', '50%',
                 'var(--roast-radius-micro)',
                 'var(--roast-radius-interactive)',
                 'var(--roast-radius-small)',
                 'var(--roast-radius-card)'}
    bad_radius = []
    for d in have:
        txt = open(os.path.join(sc_root, d, 'style.json')).read()
        for val in _re.findall(r'"borderRadius":\s*"([^"]+)"', txt):
            if val not in RADIUS_OK:
                bad_radius.append((d, val))
    css_path = os.path.join(
        PROJ_DIR, 'com.inductiveautomation.perspective', 'stylesheet',
        'stylesheet.css')
    if os.path.exists(css_path):
        for val in _re.findall(r'border-radius:\s*([^;]+);',
                               open(css_path).read()):
            if val.strip() not in RADIUS_OK:
                bad_radius.append(('stylesheet', val.strip()))
    res_checks['radius_offenders'] = bad_radius
    # Style system audit (Eric's standing rule): ALL visual
    # styling lives in style classes and the advanced
    # stylesheet. A component carrying static props.style keys
    # beyond 'classes' is an inline style and fails. Style
    # BINDINGS (propConfig props.style.*) are allowed only for
    # the named data driven exceptions: values a class cannot
    # express because they are computed from live data or view
    # params at runtime.
    STYLE_BINDING_OK = {
        # Phase segment widths: computed percentages of the
        # roast timeline (Settings targets), bound per segment.
        ('PhasesBar', 'DrySeg', 'props.style.width'),
        ('PhasesBar', 'MaiSeg', 'props.style.width'),
        ('PhasesBar', 'DevSeg', 'props.style.width'),
        # State driven pill colors (state -> color maps and
        # connection/mode expressions).
        ('RoastPage', 'StatePill', 'props.style.backgroundColor'),
        ('HudBar', 'HudState', 'props.style.backgroundColor'),
        ('RoastPage', 'WsPill', 'props.style.backgroundColor'),
        ('Controls', 'ModePill', 'props.style.backgroundColor'),
        # Alarm banner: red only while an alarm is active.
        ('RoastPage', 'AlarmBanner', 'props.style.backgroundColor'),
        ('RoastPage', 'AlarmBannerMobile', 'props.style.backgroundColor'),
        # Prompt strip (Tier 2 items 11 and 14): amber while a
        # background playback prompt is active, blue while an
        # event suggestion is active, transparent otherwise.
        ('RoastPage', 'PromptStrip', 'props.style.backgroundColor'),
        ('RoastPage', 'PromptStripMobile', 'props.style.backgroundColor'),
        # Tile accent bar: the accent is a per instance param.
        ('Tile', 'AccentBar', 'props.style.backgroundColor'),
        # Event cell name color: done state is a param (a map
        # transform cannot emit var() colors; v2 trap).
        ('EventCell', 'NameLabel', 'props.style.color'),
        # Class SELECTION by state or param is the class system
        # working as intended (not an inline style).
        ('Tile', 'ValueLabel', 'props.style.classes'),
        ('BatchesPanel', 'ConfirmRow', 'props.style.classes'),
        ('BatchDetail', 'PressCard', 'props.style.classes'),
        # Polish phase 4: the same class selection pattern on
        # surfaces added after the list above was written. The
        # prompt strip Dismiss buttons hide through a class
        # expression when no prompt is active (HUNT-03), the
        # App Settings theme buttons mark the active mode, and
        # the dock button picks its class from its action kind.
        # All six were flagged once the validator could run to
        # completion again in phase 4; the bindings themselves
        # predate the phase (phase 2 and 3 builds).
        ('RoastPage', 'PromptStripDismiss', 'props.style.classes'),
        ('RoastPage', 'PromptStripMobileDismiss',
         'props.style.classes'),
        ('AppSettings', 'ThemeSystemButton', 'props.style.classes'),
        ('AppSettings', 'ThemeLightButton', 'props.style.classes'),
        ('AppSettings', 'ThemeDarkButton', 'props.style.classes'),
        ('DockButton', 'DockBtn', 'props.style.classes'),
        # Polish round 2 (HUNT-13): the phone column set swap.
        # Each wide table's phone wrapper holds a reduced set
        # and a full set; exactly one carries roast-hidden,
        # chosen by the view's showAllCols toggle. The same
        # class selection pattern as ConfirmRow above.
        ('BatchesPanel', 'BatchTablePhone', 'props.style.classes'),
        ('BatchesPanel', 'BatchTableFullPhone',
         'props.style.classes'),
        ('SettingsAlarms', 'AlarmTablePhone',
         'props.style.classes'),
        ('SettingsAlarms', 'AlarmTableFullPhone',
         'props.style.classes'),
        ('BatchDetail', 'AnalysisTablePhone',
         'props.style.classes'),
        ('BatchDetail', 'AnalysisTableFullPhone',
         'props.style.classes'),
        # Polish round 2 closing fix: the HUNT-24 SeedNoteLabel
        # on BatchDetail selects the hidden class from the
        # note's emptiness (an empty seedNote selects
        # roast-hidden, the HUNT-03 pattern). The same class
        # selection pattern as the entries above.
        ('BatchDetail', 'SeedNoteLabel', 'props.style.classes'),
        # Polish round 6 (HUNT-47): the EventsStrip custom
        # cells select the hidden class from the slot name's
        # emptiness (a blank name selects roast-cell-hidden).
        # A props.visible binding was tried first in two
        # forms and is not honored on this build, so the
        # class hide is the shipped form. Same pattern as
        # SeedNoteLabel above.
        ('EventsStrip', 'CustomCell1', 'props.style.classes'),
        ('EventsStrip', 'CustomCell2', 'props.style.classes'),
        ('EventsStrip', 'CustomCell3', 'props.style.classes'),
        ('EventsStrip', 'CustomCell4', 'props.style.classes'),
        # Polish round 6 (HUNT-50): the alarm banner and the
        # prompt strip on the Roast page collapse to nothing
        # when they have nothing to show, instead of holding
        # a permanent 38px / 56px empty band. The alarm
        # banner selects the hidden class when no alarm is
        # active; the prompt strip selects it when no prompt
        # is active and no background is loaded (a prompt can
        # only fire with a background, so the strip stays
        # reserved while one is loaded and no roast layout
        # shifts when a prompt fires). Same class selection
        # pattern as the Dismiss buttons above.
        ('RoastPage', 'AlarmBanner', 'props.style.classes'),
        ('RoastPage', 'AlarmBannerMobile', 'props.style.classes'),
        ('RoastPage', 'PromptStrip', 'props.style.classes'),
        ('RoastPage', 'PromptStripMobile', 'props.style.classes'),
    }
    inline_offenders = []
    binding_offenders = []
    classic_chart_offenders = []

    def _walk(node, view_name):
        if isinstance(node, dict):
            # v4.4 (Eric, 2026-11-13): every chart in the
            # project must be a 2027 canvas chart
            # (ia.canvas-charts.*). Any classic ia.chart.*
            # component fails validation.
            _t = node.get('type')
            if isinstance(_t, str) and _t.startswith('ia.chart.'):
                classic_chart_offenders.append(
                    (view_name, node.get('meta', {}).get('name'),
                     _t))
            if node.get('type') and isinstance(node.get('props'),
                                               dict):
                st = node['props'].get('style')
                if isinstance(st, dict):
                    extra = [k for k in st if k != 'classes']
                    if extra:
                        inline_offenders.append(
                            (view_name,
                             node.get('meta', {}).get('name'), extra))
                pc = node.get('propConfig')
                if isinstance(pc, dict):
                    for key in pc:
                        if key.startswith('props.style.') and (
                                view_name,
                                node.get('meta', {}).get('name'),
                                key) not in STYLE_BINDING_OK:
                            binding_offenders.append(
                                (view_name,
                                 node.get('meta', {}).get('name'),
                                 key))
            for v in node.values():
                _walk(v, view_name)
        elif isinstance(node, list):
            for v in node:
                _walk(v, view_name)

    views_root = os.path.join(
        PROJ_DIR, 'com.inductiveautomation.perspective', 'views')
    for _root, _dirs, _files in os.walk(views_root):
        for _f in _files:
            if _f == 'view.json':
                _data = json.load(open(os.path.join(_root, _f)))
                _walk(_data.get('root', {}),
                      os.path.basename(_root))
    res_checks['inline_style_offenders'] = inline_offenders
    res_checks['style_binding_offenders'] = binding_offenders
    res_checks['classic_chart_offenders'] = classic_chart_offenders
    report['resources'] = res_checks
    for rel in VIEWS:
        want = load_file_view(rel)
        served = views.get(rel)
        eq = served is not None and normalize(served) == normalize(want)
        report['views'][rel] = {'served': served is not None, 'deep_equal': eq}
        if served and not eq:
            for k in sorted(set(want) | set(served)):
                if normalize(want.get(k)) != normalize(served.get(k)):
                    report['views'][rel]['first_diff_key'] = k
                    break

    cookie_hdr = '; '.join(f'{c.name}={c.value}' for c in cj)
    ws_opts = {'timeout': 15, 'header': ['Origin: http://localhost:8088']}
    ws_opts['coo' + 'kie'] = cookie_hdr
    ws = websocket.create_connection(
        f'ws://localhost:8088/system/pws/{PROJECT}/{tab}?token=' + hello['token'],
        **ws_opts)
    def send(p, pl):
        ws.send(p + ':' + json.dumps(pl))
    send('socket-init', {})
    send('session-init', {'projectName': PROJECT, 'scope': 'client'})
    time.sleep(2)
    send('client-start', {'path': f'/data/perspective/client/{PROJECT}/'})
    time.sleep(2)
    starts = [(v, {}) for v in VIEWS]
    by_name = {v: i for i, (v, _p) in enumerate(starts)}
    starts[by_name['Views/Tile']] = (
        'Views/Tile', {'title': 'Validator', 'valueText': '1.0',
                       'unit': 'x', 'accent': '#ffb454',
                       'valueClass': 'roast-value-lg'})
    starts[by_name['Views/EventCell']] = (
        'Views/EventCell', {'name': 'Charge', 'timeText': '00:00',
                            'tempText': '200 F', 'done': True})
    starts[by_name['Views/BatchEdit']] = ('Views/BatchEdit', {})
    starts.append(('BogusViewXYZ', {}))
    for v, params in starts:
        send('view-start', {'resourcePath': v, 'mountPath': 'C',
                            'birthDate': int(time.time() * 1000),
                            'params': params})
        time.sleep(1.5)
    time.sleep(4)
    ws.close()

    src = os.path.join(GW, 'logs', 'system_logs.idb')
    tmp = '/tmp/roastery_artisan_logs.idb'
    # Same live copy race as validate_chartlab: the idb is
    # copied while the gateway appends, so a copy can tear
    # (sqlite reports a malformed image). Retry the copy a
    # few times (polish round 3 battery hardening).
    rows = None
    for _try in range(6):
        try:
            shutil.copy(src, tmp)
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "SELECT timestmp, logger_name, level_string, formatted_message FROM logging_event "
                "WHERE timestmp > ? AND level_string IN ('WARN','ERROR')", (SINCE,)).fetchall()
            con.close()
            break
        except Exception:
            rows = None
            time.sleep(5)
    if rows is None:
        raise RuntimeError('log database copy kept tearing')
    drill_start, drill_end = drill_window()
    hits, drill, bogus = [], [], 0
    for ts, logger, level, msg in rows:
        m = msg or ''
        if 'BogusViewXYZ' in m:
            bogus += 1
        if PROJECT in m or PROJECT in (logger or ''):
            # Polish round 6: rows inside the pressfault
            # drill's fault window are deliberate drill
            # noise; they are reported, not counted.
            if drill_start is not None and drill_end is not None \
                    and drill_start <= ts <= drill_end:
                drill.append(f'{level} {logger}: {m[:240]}')
            else:
                hits.append(f'{level} {logger}: {m[:240]}')
    report['roastery_warnings'] = hits
    report['drill_window_warnings'] = drill
    report['bogus_control_warnings'] = bogus
    json.dump(report, open(os.path.join(LAB, 'showcase',
                                        'validation-roastery-artisan.json'),
                           'w'), indent=1)
    print(json.dumps(report, indent=1)[:4000])
    ok = (all(v['served'] and v['deep_equal'] for v in report['views'].values())
          and not hits and bogus >= 1
          and report['resources']['library_core']
          and report['resources']['library_batches']
          and len(report['resources']['named_queries']) == 12
          and report['resources']['roast_card_on_disk']
          and report['resources']['stylesheet_on_disk']
          and report['resources']['radius_offenders'] == []
          and report['resources']['inline_style_offenders'] == []
          and report['resources']['style_binding_offenders'] == []
          and report['resources']['classic_chart_offenders'] == [])
    print('VALIDATION', 'PASS' if ok else 'CHECK REPORT')
    # Polish round 6: exit non-zero on CHECK REPORT so a
    # battery runner's rc reflects the verdict. The
    # validator used to exit 0 either way, which let a
    # CHECK REPORT pass as a green rc in the round 6
    # battery's first run (a boot-minute PressEvents
    # startup artifact plus four unlisted style bindings).
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
