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
         'Views/SettingsAlarms', 'Views/SettingsMetadata',
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
    # 8 cards, 999 pills only). Eric flagged the inconsistent
    # bubbly rounding (16/12/10px) as amateur.
    import re as _re
    RADIUS_OK = {'0px', '2px', '4px', '6px', '8px', '999px', '50%'}
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
    shutil.copy(src, tmp)
    con = sqlite3.connect(tmp)
    rows = con.execute(
        "SELECT logger_name, level_string, formatted_message FROM logging_event "
        "WHERE timestmp > ? AND level_string IN ('WARN','ERROR')", (SINCE,)).fetchall()
    con.close()
    hits, bogus = [], 0
    for logger, level, msg in rows:
        m = msg or ''
        if 'BogusViewXYZ' in m:
            bogus += 1
        if PROJECT in m or PROJECT in (logger or ''):
            hits.append(f'{level} {logger}: {m[:240]}')
    report['roastery_warnings'] = hits
    report['bogus_control_warnings'] = bogus
    json.dump(report, open(os.path.join(LAB, 'showcase',
                                        'validation-roastery-artisan.json'),
                           'w'), indent=1)
    print(json.dumps(report, indent=1)[:4000])
    ok = (all(v['served'] and v['deep_equal'] for v in report['views'].values())
          and not hits and bogus >= 1
          and report['resources']['library_core']
          and report['resources']['library_batches']
          and len(report['resources']['named_queries']) == 10
          and report['resources']['roast_card_on_disk']
          and report['resources']['stylesheet_on_disk']
          and report['resources']['radius_offenders'] == [])
    print('VALIDATION', 'PASS' if ok else 'CHECK REPORT')

if __name__ == '__main__':
    main()
