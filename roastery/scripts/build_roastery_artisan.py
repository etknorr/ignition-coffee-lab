#!/usr/bin/env python3
"""Build the Artisan-style Roastery project (files only) on the Maker
2027 gateway (gateway-2027-maker/data/projects/Roastery).

Design targets, from Eric's real setup and the Artisan v5.0.0 source
inventory (see knowledge/notes/coffee-roaster-app.md):

- One probe: BeanTempF (SR800 over WebSocket in production; RoasterSim
  stands in here). RateOfRiseF is derived by a tag event script.
- Full Artisan event set (Charge, Dry End, FC Start, FC End, SC Start,
  SC End, Drop, Cool, Finish) plus four customizable event buttons.
- Fan / Heat steppers (SR800 levels 1 to 9) logged into an EventsLog
  dataset and drawn as step traces under the main curve.
- Target profile from editable points (config popup) drawn dashed;
  a saved roast selectable from the roast log drawn as background.
- Phases bar with DTR, roast summary with weight loss and degree,
  alarms banner, roast log page, dark glass styling, flex only,
  mobile responsive at 390 px.

Views: Main, Config (popup), Log (page /log), and embedded views
Tile, EventCell, EventsStrip, PhasesBar, Controls, MetaCard, Summary.
The old BatchCard, StatTile, ControlPanel and Settings views are
removed by this builder.

Usage: build_roastery_artisan.py  (then POST /scan/projects)
Run with wsvenv python.
"""
import copy, json, os, shutil, sys

LAB = os.path.dirname(os.path.abspath(__file__))
GW = os.path.join(LAB, 'gateway-2027-maker')
PROJ = os.path.join(GW, 'data', 'projects', 'Roastery')
SCHEMAS = os.path.join(LAB, 'knowledge', 'schemas-2027')

RES = {'scope': 'G', 'version': 1, 'restricted': False, 'overridable': True,
       'files': ['view.json'], 'attributes': {'lastModificationSignature': ''}}

# ---------------------------------------------------------------- palette
PAGE_BG = '#150e08'
CARD_BG = 'rgba(38, 25, 15, 0.88)'
CARD_BG_SOLID = '#26190f'
CARD_BORDER = '#4a3220'
INK = '#f3e7d3'
MUTED = '#b89b7d'
FAINT = '#8a7360'
COPPER = '#e08a3c'
AMBER = '#ffb454'
SKY = '#7dd3fc'
RED = '#ef4444'
GREEN = '#4ade80'
CREAM = '#f7ead9'

CARD_STYLE = {
    'backgroundColor': CARD_BG,
    'border': f'1px solid {CARD_BORDER}',
    'borderRadius': '16px',
    'boxShadow': '0 2px 6px rgba(0, 0, 0, 0.45), 0 14px 34px rgba(0, 0, 0, 0.35)',
    'padding': '16px 18px',
}
CAPTION = {'fontSize': '11px', 'fontWeight': '700', 'color': FAINT,
           'textTransform': 'uppercase', 'letterSpacing': '0.1em'}
SECTION = {'fontSize': '13px', 'fontWeight': '700', 'color': COPPER,
           'textTransform': 'uppercase', 'letterSpacing': '0.08em'}
BTN_BASE = {'fontSize': '14px', 'fontWeight': '700', 'color': '#ffffff',
            'borderRadius': '10px', 'padding': '10px 18px',
            'cursor': 'pointer', 'border': 'none'}
INPUT_STYLE = {'border': '1px solid #5a4028', 'borderRadius': '8px',
               'padding': '8px 10px', 'fontSize': '14px', 'color': INK,
               'backgroundColor': 'rgba(21, 14, 8, 0.6)'}

B = '[default]Roastery/CurrentBatch'
LOG = '[default]Roastery/EventsLog'
RLOG = '[default]Roastery/RoastLog'

def T(member):
    return f'{B}/{member}'

def ref(path):
    return '{' + path + '}'

def tag_binding(path, bidirectional=False):
    return {'type': 'tag',
            'config': {'tagPath': path, 'mode': 'direct',
                       'bidirectional': bidirectional},
            'bidirectional': bidirectional}

def fmt_tag(path, fmt):
    b = tag_binding(path)
    b['transforms'] = [{'type': 'format', 'formatType': 'numeric',
                        'formatValue': fmt}]
    return b

def expr_binding(expression):
    return {'type': 'expr', 'config': {'expression': expression}}

def prop_binding(path):
    return {'type': 'property', 'config': {'path': path}}

# ---------------------------------------------------------------- components

def label(name, text, style, position=None, prop_config=None, extra_props=None):
    c = {'type': 'ia.display.label', 'meta': {'name': name},
         'props': {'text': text, 'style': style}}
    if extra_props:
        c['props'].update(extra_props)
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    return c

def flex(name, direction, children, style=None, position=None, justify=None,
         align=None, wrap=None, extra_props=None, prop_config=None):
    props = {'direction': direction}
    if justify:
        props['justify'] = justify
    if align:
        props['alignItems'] = align
    if wrap:
        props['wrap'] = wrap
    if style:
        props['style'] = style
    if extra_props:
        props.update(extra_props)
    c = {'type': 'ia.container.flex', 'meta': {'name': name},
         'props': props, 'children': children}
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    return c

def button(name, text, style, position=None, prop_config=None, events=None):
    c = {'type': 'ia.input.button', 'meta': {'name': name},
         'props': {'text': text, 'style': style}}
    if position:
        c['position'] = position
    if prop_config:
        c['propConfig'] = prop_config
    if events:
        c['events'] = events
    return c

def script_event(script):
    return {'dom': {'onClick': {'scope': 'G', 'type': 'script',
                                'config': {'script': script}}}}

def embed(name, path, params, position, prop_config=None):
    c = {'type': 'ia.display.view', 'meta': {'name': name},
         'props': {'path': path, 'params': params},
         'position': position}
    if prop_config:
        c['propConfig'] = prop_config
    return c

# ---------------------------------------------------------------- expressions

def mmss_int(sec_expr):
    """mm:ss string from an integer-seconds expression."""
    return (f"numberFormat(floor({sec_expr} / 60), '00') + ':' + "
            f"numberFormat({sec_expr} % 60, '00')")

def mmss_ms(ms_expr):
    return (f"numberFormat(floor({ms_expr} / 60000), '00') + ':' + "
            f"numberFormat(floor(({ms_expr} / 1000) % 60), '00')")

ELAPSED_MS = f"(now() - {ref(T('StartTime'))})"
ELAPSED_SEC = f"({ELAPSED_MS} / 1000)"

# ---------------------------------------------------------------- jython scripts
# Perspective script action bodies: tab indented, the runtime wraps the
# body in a function. Variables in scope include self and event.

CTX = (
    "\tB = '[default]Roastery/CurrentBatch'\n"
    "\tqvs = system.tag.readBlocking([B + '/BeanTempF', B + '/StartTime'])\n"
    "\ttemp = qvs[0].value\n"
    "\tstart = qvs[1].value\n"
    "\tnow = system.date.now()\n"
    "\telapsed = -1\n"
    "\tif start is not None:\n"
    "\t\telapsed = int((now.getTime() - start.getTime()) / 1000)\n")

def append_log(kind, label_expr, fan='None', heat='None'):
    """Append a row to the EventsLog dataset. Assumes CTX ran (now,
    elapsed, temp in scope)."""
    return (
        "\tlogPath = '[default]Roastery/EventsLog'\n"
        "\tlog = system.tag.readBlocking([logPath])[0].value\n"
        "\tif log is None:\n"
        "\t\tlog = system.dataset.toDataSet(['t_stamp', 'elapsedSec', 'kind', 'label', 'tempF', 'fan', 'heat'], [])\n"
        f"\tlog = system.dataset.addRow(log, [now, float(max(elapsed, 0)), '{kind}', {label_expr}, float(temp), {fan}, {heat}])\n"
        "\tsystem.tag.writeBlocking([logPath], [log])\n")

OVERLAY_BUILD = (
    "\tq = system.tag.readBlocking([B + '/TargetChargeTempF', B + '/TargetDryEndSec', B + '/TargetDryEndTempF', B + '/TargetFCSec', B + '/TargetFCTempF', B + '/TargetDropSec', B + '/TargetDropTempF', '[default]Roastery/BackgroundCurveJson'])\n"
    "\tpts = [(0.0, q[0].value), (float(q[1].value), q[2].value), (float(q[3].value), q[4].value), (float(q[5].value), q[6].value)]\n"
    "\tdef planAt(s):\n"
    "\t\tfor i in range(len(pts) - 1):\n"
    "\t\t\tt0 = pts[i][0]\n"
    "\t\t\tv0 = pts[i][1]\n"
    "\t\t\tt1 = pts[i + 1][0]\n"
    "\t\t\tv1 = pts[i + 1][1]\n"
    "\t\t\tif s <= t1:\n"
    "\t\t\t\tif t1 <= t0:\n"
    "\t\t\t\t\treturn v1\n"
    "\t\t\t\treturn v0 + (v1 - v0) * (s - t0) / (t1 - t0)\n"
    "\t\treturn pts[-1][1]\n"
    "\tfrom java.util import Date\n"
    "\tstartMs = start.getTime()\n"
    "\trows = []\n"
    "\ts = 0.0\n"
    "\twhile s < pts[-1][0]:\n"
    "\t\trows.append([Date(long(startMs + s * 1000)), planAt(s)])\n"
    "\t\ts += 15.0\n"
    "\trows.append([Date(long(startMs + pts[-1][0] * 1000)), pts[-1][1]])\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/TargetProfileDS'], [system.dataset.toDataSet(['t_stamp', 'plan'], rows)])\n"
    "\tbgRows = []\n"
    "\tbgJson = q[7].value\n"
    "\tif bgJson:\n"
    "\t\timport json as _json\n"
    "\t\tfor pair in _json.loads(bgJson):\n"
    "\t\t\tbgRows.append([Date(long(startMs + float(pair[0]) * 1000)), float(pair[1])])\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/BackgroundDS'], [system.dataset.toDataSet(['t_stamp', 'bg'], bgRows)])\n")

CLEAR_EVENTS = (
    "\tpaths = []\n"
    "\tvalues = []\n"
    "\tfor stem in ['DryEnd', 'FirstCrackStart', 'FirstCrackEnd', 'SecondCrackStart', 'SecondCrackEnd', 'Drop']:\n"
    "\t\tpaths += [B + '/' + stem + 'Time', B + '/' + stem + 'TempF', B + '/' + stem + 'ElapsedSec']\n"
    "\t\tvalues += [None, 0.0, -1]\n"
    "\tfor i in [1, 2, 3, 4]:\n"
    "\t\tpaths += [B + '/CustomEvent' + str(i) + 'Time', B + '/CustomEvent' + str(i) + 'TempF', B + '/CustomEvent' + str(i) + 'ElapsedSec']\n"
    "\t\tvalues += [None, 0.0, -1]\n"
    "\tsystem.tag.writeBlocking(paths, values)\n")

CHARGE_SCRIPT = (
    "\tB = '[default]Roastery/CurrentBatch'\n"
    "\tqvs = system.tag.readBlocking([B + '/BeanTempF', B + '/FanLevel', B + '/HeatLevel'])\n"
    "\ttemp = qvs[0].value\n"
    "\tfan = qvs[1].value\n"
    "\theat = qvs[2].value\n"
    "\tnow = system.date.now()\n"
    "\tstart = now\n"
    "\tsystem.tag.writeBlocking([B + '/State', B + '/StartTime', B + '/ChargeTime', B + '/ChargeTempF', B + '/Mode', B + '/WeightOutG'], ['Roasting', now, now, temp, 'Roast', 0.0])\n"
    + CLEAR_EVENTS +
    "\tlogRows = [[now, 0.0, 'Event', 'Charge', float(temp), float(fan), float(heat)], [now, 0.0, 'Fan', 'Fan ' + str(fan), float(temp), float(fan), float(heat)], [now, 0.0, 'Heat', 'Heat ' + str(heat), float(temp), float(fan), float(heat)]]\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/EventsLog'], [system.dataset.toDataSet(['t_stamp', 'elapsedSec', 'kind', 'label', 'tempF', 'fan', 'heat'], logRows)])\n"
    + OVERLAY_BUILD)

def event_script(stem, label, extra_writes=None):
    writes = (f"\twp = [B + '/{stem}Time', B + '/{stem}TempF', B + '/{stem}ElapsedSec']\n"
              f"\twv = [now, temp, elapsed]\n")
    if extra_writes:
        for p, v in extra_writes:
            writes += f"\twp.append(B + '/{p}')\n\twv.append({v})\n"
    writes += "\tsystem.tag.writeBlocking(wp, wv)\n"
    return CTX + writes + append_log('Event', f"'{label}'")

DROP_SCRIPT = event_script('Drop', 'Drop',
                           extra_writes=[('State', "'Dropped'")])

COOL_SCRIPT = CTX + (
    "\tsystem.tag.writeBlocking([B + '/State', B + '/Mode'], ['Cooling', 'Cool'])\n"
) + append_log('Event', "'Cool'")

FINISH_SCRIPT = CTX + (
    "\tsystem.tag.writeBlocking([B + '/State', B + '/Mode'], ['Complete', 'Off'])\n"
) + append_log('Event', "'Finish'")

RESET_SCRIPT = (
    "\tB = '[default]Roastery/CurrentBatch'\n"
    "\tsystem.tag.writeBlocking([B + '/State', B + '/Mode', B + '/StartTime', B + '/ChargeTime', B + '/ChargeTempF', B + '/WeightOutG'], ['Idle', 'Off', None, None, 0.0, 0.0])\n"
    + CLEAR_EVENTS +
    "\temptyLog = system.dataset.toDataSet(['t_stamp', 'elapsedSec', 'kind', 'label', 'tempF', 'fan', 'heat'], [])\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/EventsLog'], [emptyLog])\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/TargetProfileDS'], [system.dataset.toDataSet(['t_stamp', 'plan'], [])])\n"
    "\tsystem.tag.writeBlocking(['[default]Roastery/BackgroundDS'], [system.dataset.toDataSet(['t_stamp', 'bg'], [])])\n")

def custom_event_script(i):
    return (
        "\tB = '[default]Roastery/CurrentBatch'\n"
        "\tqvs = system.tag.readBlocking([B + '/BeanTempF', B + '/StartTime', B + '/CustomEvent%dName'])\n"
        "\ttemp = qvs[0].value\n"
        "\tstart = qvs[1].value\n"
        "\tname = qvs[2].value\n"
        "\tnow = system.date.now()\n"
        "\telapsed = -1\n"
        "\tif start is not None:\n"
        "\t\telapsed = int((now.getTime() - start.getTime()) / 1000)\n"
        "\tsystem.tag.writeBlocking([B + '/CustomEvent%dTime', B + '/CustomEvent%dTempF', B + '/CustomEvent%dElapsedSec'], [now, temp, elapsed])\n"
        % (i, i, i, i)
    ) + append_log('Custom', 'name')

def stepper_script(member, delta, kind):
    return (
        "\tB = '[default]Roastery/CurrentBatch'\n"
        f"\tpath = B + '/{member}'\n"
        "\tcur = system.tag.readBlocking([path])[0].value\n"
        f"\tnew = cur + ({delta})\n"
        "\tif new < 1:\n"
        "\t\tnew = 1\n"
        "\tif new > 9:\n"
        "\t\tnew = 9\n"
        "\tif new != cur:\n"
        "\t\tsystem.tag.writeBlocking([path], [new])\n"
        "\t\tstate = system.tag.readBlocking([B + '/State'])[0].value\n"
        "\t\tif state == 'Roasting':\n"
        "\t\t\tqvs = system.tag.readBlocking([B + '/BeanTempF', B + '/StartTime'])\n"
        "\t\t\ttemp = qvs[0].value\n"
        "\t\t\tstart = qvs[1].value\n"
        "\t\t\tnow = system.date.now()\n"
        "\t\t\telapsed = -1\n"
        "\t\t\tif start is not None:\n"
        "\t\t\t\telapsed = int((now.getTime() - start.getTime()) / 1000)\n"
        + append_log(kind, f"'{kind} ' + str(new)",
                     fan='float(new)' if kind == 'Fan' else 'None',
                     heat='float(new)' if kind == 'Heat' else 'None')
        .replace('\n\t', '\n\t\t\t').replace('\tlogPath', '\t\t\tlogPath', 1)
    )

SAVE_SCRIPT = (
    "\tB = '[default]Roastery/CurrentBatch'\n"
    "\tnames = ['BatchNumber', 'BeanName', 'Origin', 'ChargeWeightG', 'DropTempF', 'DropElapsedSec', 'DryEndElapsedSec', 'FirstCrackStartElapsedSec', 'WeightOutG', 'StartTime', 'DropTime', 'ChargeTempF']\n"
    "\tq = system.tag.readBlocking([B + '/' + n for n in names])\n"
    "\td = {}\n"
    "\tfor i in range(len(names)):\n"
    "\t\td[names[i]] = q[i].value\n"
    "\ttotal = d['DropElapsedSec']\n"
    "\tdry = d['DryEndElapsedSec']\n"
    "\tfc = d['FirstCrackStartElapsedSec']\n"
    "\tmai = fc - dry if (fc >= 0 and dry >= 0) else -1\n"
    "\tdev = total - fc if (total >= 0 and fc >= 0) else -1\n"
    "\tdtr = (dev * 100.0 / total) if (total > 0 and dev >= 0) else 0.0\n"
    "\tloss = ((d['ChargeWeightG'] - d['WeightOutG']) * 100.0 / d['ChargeWeightG']) if (d['WeightOutG'] and d['WeightOutG'] > 0 and d['ChargeWeightG'] > 0) else 0.0\n"
    "\tdt = d['DropTempF']\n"
    "\tlevel = 'Cinnamon' if dt < 390 else 'New England' if dt < 396 else 'American' if dt < 401 else 'City' if dt < 406 else 'City+' if dt < 411 else 'Full City' if dt < 416 else 'Full City+' if dt < 421 else 'Vienna' if dt < 426 else 'French' if dt < 436 else 'Italian'\n"
    "\tcurve = []\n"
    "\tauc = 0.0\n"
    "\tif d['StartTime'] is not None and d['DropTime'] is not None:\n"
    "\t\thist = system.tag.queryTagHistory([B + '/BeanTempF'], d['StartTime'], d['DropTime'], returnSize=90, aggregationMode='Average', returnFormat='Wide')\n"
    "\t\tprevT = None\n"
    "\t\tprevV = None\n"
    "\t\tfor r in range(hist.getRowCount()):\n"
    "\t\t\tts = hist.getValueAt(r, 0)\n"
    "\t\t\tv = hist.getValueAt(r, 1)\n"
    "\t\t\tif ts is None or v is None:\n"
    "\t\t\t\tcontinue\n"
    "\t\t\tsec = (ts.getTime() - d['StartTime'].getTime()) / 1000.0\n"
    "\t\t\tcurve.append([round(sec, 1), round(float(v), 1)])\n"
    "\t\t\tif prevT is not None:\n"
    "\t\t\t\tauc += ((float(v) + prevV) / 2.0 - d['ChargeTempF']) * (sec - prevT) / 60.0\n"
    "\t\t\tprevT = sec\n"
    "\t\t\tprevV = float(v)\n"
    "\timport json\n"
    "\trow = [d['BatchNumber'], system.date.now(), d['BeanName'], d['Origin'], float(d['ChargeWeightG']), float(dt), float(total), float(dry), float(mai), float(dev), float(dtr), float(loss), float(auc), level, json.dumps(curve)]\n"
    "\tlogPath = '[default]Roastery/RoastLog'\n"
    "\tlog = system.tag.readBlocking([logPath])[0].value\n"
    "\tif log is None:\n"
    "\t\tlog = system.dataset.toDataSet(['batch', 'roastDate', 'bean', 'origin', 'chargeG', 'dropTempF', 'totalSec', 'drySec', 'maillardSec', 'devSec', 'dtrPct', 'weightLossPct', 'auc', 'level', 'curveJson'], [])\n"
    "\tlog = system.dataset.addRow(log, row)\n"
    "\tsystem.tag.writeBlocking([logPath], [log])\n"
    "\tself.view.custom.saveNote = 'Saved batch ' + str(d['BatchNumber']) + ' to the roast log.'\n")

POPUP_OPEN = {
    'dom': {'onClick': {
        'scope': 'C', 'type': 'popup',
        'config': {'type': 'open', 'id': 'roastery-config',
                   'viewPath': 'Views/Config',
                   'title': 'Roast Setup', 'modal': True,
                   'showCloseIcon': True, 'draggable': True,
                   'resizable': True, 'overlayDismiss': True,
                   'position': {'width': 'min(700px, 94vw)',
                                'height': 'min(880px, 94vh)'}}}}}

POPUP_CLOSE = {
    'dom': {'onClick': {'scope': 'C', 'type': 'popup',
                         'config': {'type': 'close',
                                    'id': 'roastery-config'}}}}
# ---------------------------------------------------------------- Tile

def tile_view():
    """Parameterized live tile: title, valueText, unit, accent color."""
    accent_bar = flex('AccentBar', 'row', [],
                      style={'height': '3px', 'borderRadius': '2px',
                             'backgroundColor': COPPER},
                      position={'grow': 0, 'shrink': 0, 'basis': '3px'},
                      prop_config={'props.style.backgroundColor': {
                          'binding': prop_binding('view.params.accent')}})
    title = label('TitleLabel', 'Stat', dict(CAPTION),
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.params.title')}})
    value = label('ValueLabel', '0.0',
                  {'fontSize': '30px', 'fontWeight': '700', 'color': INK,
                   'lineHeight': '1.05'},
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.params.valueText')}})
    unit = label('UnitLabel', '',
                 {'fontSize': '12px', 'fontWeight': '600', 'color': MUTED},
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.params.unit')}})
    row = flex('ValueRow', 'row', [value, unit], align='baseline',
               style={'gap': '6px'})
    root = flex('root', 'column', [accent_bar, title, row],
                style=dict(CARD_STYLE, gap='5px', padding='12px 16px'))
    return {
        'custom': {},
        'params': {'title': 'Stat', 'valueText': '0.0', 'unit': '',
                   'accent': COPPER},
        'propConfig': {
            'params.title': {'paramDirection': 'input'},
            'params.valueText': {'paramDirection': 'input'},
            'params.unit': {'paramDirection': 'input'},
            'params.accent': {'paramDirection': 'input'}},
        'props': {'defaultSize': {'width': 220, 'height': 104}},
        'root': root}

# ---------------------------------------------------------------- EventCell

def event_cell_view():
    """One roast event: name, elapsed time, captured temp. The done
    param flips the styling from waiting (muted) to recorded (copper
    border glow) via a map transform on the style props."""
    done_map = {'type': 'map', 'inputType': 'scalar',
                'outputType': 'color', 'fallback': FAINT,
                'mappings': [{'input': True, 'output': COPPER},
                             {'input': False, 'output': FAINT}]}
    name = label('NameLabel', 'Event',
                 {'fontSize': '11px', 'fontWeight': '700', 'color': FAINT,
                  'textTransform': 'uppercase', 'letterSpacing': '0.08em',
                  'textAlign': 'center'},
                 prop_config={
                     'props.text': {'binding': prop_binding(
                         'view.params.name')},
                     'props.style.color': {'binding': {
                         'type': 'property',
                         'config': {'path': 'view.params.done'},
                         'transforms': [dict(done_map)]}}})
    time_l = label('TimeLabel', '--:--',
                   {'fontSize': '17px', 'fontWeight': '700', 'color': INK,
                    'textAlign': 'center'},
                   prop_config={'props.text': {'binding': prop_binding(
                       'view.params.timeText')}})
    temp_l = label('TempLabel', '---',
                   {'fontSize': '12px', 'fontWeight': '600', 'color': MUTED,
                    'textAlign': 'center'},
                   prop_config={'props.text': {'binding': prop_binding(
                       'view.params.tempText')}})
    root = flex('root', 'column', [name, time_l, temp_l],
                align='center',
                style={'backgroundColor': 'rgba(21, 14, 8, 0.55)',
                       'border': '1px solid #3d2716',
                       'borderRadius': '12px', 'padding': '9px 6px',
                       'gap': '2px'},
                prop_config=None)
    # border glow when done: bind the root style border via a second
    # component-level propConfig is not available on the root's own
    # props from inside; the name color carries the state instead.
    return {
        'custom': {},
        'params': {'name': 'Event', 'timeText': '--:--', 'tempText': '---',
                   'done': False},
        'propConfig': {
            'params.name': {'paramDirection': 'input'},
            'params.timeText': {'paramDirection': 'input'},
            'params.tempText': {'paramDirection': 'input'},
            'params.done': {'paramDirection': 'input'}},
        'props': {'defaultSize': {'width': 120, 'height': 84}},
        'root': root}

def event_embed(name, disp_name, stem, custom_idx=None):
    """Embed an EventCell for a standard event stem or a custom event."""
    if custom_idx:
        nm = {'binding': tag_binding(T(f'CustomEvent{custom_idx}Name'))}
        elapsed = T(f'CustomEvent{custom_idx}ElapsedSec')
        temp = T(f'CustomEvent{custom_idx}TempF')
    else:
        nm = None
        elapsed = T(stem + 'ElapsedSec')
        temp = T(stem + 'TempF')
    pc = {
        'props.params.timeText': {'binding': expr_binding(
            f"if({ref(elapsed)} >= 0, {mmss_int(ref(elapsed))}, '--:--')")},
        'props.params.tempText': {'binding': expr_binding(
            f"if({ref(elapsed)} >= 0, numberFormat({ref(temp)}, '0') + ' F', '---')")},
        'props.params.done': {'binding': expr_binding(
            f"{ref(elapsed)} >= 0")}}
    if nm:
        pc['props.params.name'] = nm
    params = {'name': disp_name, 'timeText': '--:--', 'tempText': '---',
              'done': False}
    return embed(name, 'Views/EventCell', params,
                 {'grow': 1, 'shrink': 1, 'basis': '104px'}, pc)

def events_strip_view():
    heading = label('Heading', 'Roast Events',
                    dict(SECTION))
    std = [('ChargeCell', 'Charge', None),  # charge handled below
           ]
    # Charge has no ElapsedSec member (it is always 0); special-case it.
    charge_pc = {
        'props.params.timeText': {'binding': expr_binding(
            f"if({ref(T('State'))} != 'Idle', '00:00', '--:--')")},
        'props.params.tempText': {'binding': expr_binding(
            f"if({ref(T('State'))} != 'Idle', numberFormat({ref(T('ChargeTempF'))}, '0') + ' F', '---')")},
        'props.params.done': {'binding': expr_binding(
            f"{ref(T('State'))} != 'Idle'")}}
    charge = embed('ChargeCell', 'Views/EventCell',
                   {'name': 'Charge', 'timeText': '--:--',
                    'tempText': '---', 'done': False},
                   {'grow': 1, 'shrink': 1, 'basis': '104px'}, charge_pc)
    row1 = flex('StandardRow', 'row', [
        charge,
        event_embed('DryEndCell', 'Dry End', 'DryEnd'),
        event_embed('FCStartCell', 'FC Start', 'FirstCrackStart'),
        event_embed('FCEndCell', 'FC End', 'FirstCrackEnd'),
        event_embed('SCStartCell', 'SC Start', 'SecondCrackStart'),
        event_embed('SCEndCell', 'SC End', 'SecondCrackEnd'),
        event_embed('DropCell', 'Drop', 'Drop')],
        wrap='wrap', style={'gap': '8px'})
    row2 = flex('CustomRow', 'row', [
        event_embed(f'CustomCell{i}', f'Custom {i}', None, custom_idx=i)
        for i in (1, 2, 3, 4)],
        wrap='wrap', style={'gap': '8px'})
    root = flex('root', 'column', [heading, row1, row2],
                style=dict(CARD_STYLE, gap='10px'))
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 210}},
            'root': root}

# ---------------------------------------------------------------- PhasesBar

def phases_bar_view():
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))
    drop_e = ref(T('DropElapsedSec'))
    td = ref(T('TargetDryEndSec'))
    tf = ref(T('TargetFCSec'))
    tt = ref(T('TargetDropSec'))
    dry_w = (f"if({drop_e} >= 0, {dry_e} * 100.0 / {drop_e}, "
             f"{td} * 100.0 / {tt})")
    mai_w = (f"if({drop_e} >= 0, ({fc_e} - {dry_e}) * 100.0 / {drop_e}, "
             f"({tf} - {td}) * 100.0 / {tt})")
    dev_w = (f"if({drop_e} >= 0, ({drop_e} - {fc_e}) * 100.0 / {drop_e}, "
             f"({tt} - {tf}) * 100.0 / {tt})")

    def seg(name, caption, color, width_expr, text_expr):
        txt = label(name + 'Text', caption,
                    {'fontSize': '12px', 'fontWeight': '700',
                     'color': '#ffffff', 'textAlign': 'center',
                     'whiteSpace': 'nowrap', 'overflow': 'hidden'},
                    prop_config={'props.text': {'binding': expr_binding(
                        text_expr)}})
        return flex(name, 'row', [txt], justify='center', align='center',
                    style={'backgroundColor': color, 'borderRadius': '8px',
                           'padding': '7px 4px', 'minWidth': '86px'},
                    prop_config={'props.style.width': {'binding':
                        expr_binding(f"numberFormat({width_expr}, '0.0') + '%'")}})

    dry_t = (f"'DRYING  ' + if({dry_e} >= 0, {mmss_int(dry_e)} + ' · ' + "
             f"numberFormat({dry_w}, '0') + '%', 'target ' + {mmss_int(td)})")
    mai_t = (f"'MAILLARD  ' + if({fc_e} >= 0, "
             f"{mmss_int(f'({fc_e} - {dry_e})')} + ' · ' + "
             f"numberFormat({mai_w}, '0') + '%', 'target ' + "
             f"{mmss_int(f'({tf} - {td})')})")
    dev_t = (f"'DEVELOPMENT  ' + if({drop_e} >= 0, "
             f"{mmss_int(f'({drop_e} - {fc_e})')} + ' · ' + "
             f"numberFormat({dev_w}, '0') + '%', 'target ' + "
             f"{mmss_int(f'({tt} - {tf})')})")
    bar = flex('Bar', 'row', [
        seg('DrySeg', 'DRYING', '#b45309', dry_w, dry_t),
        seg('MaiSeg', 'MAILLARD', '#92400e', mai_w, mai_t),
        seg('DevSeg', 'DEVELOPMENT', '#7c2d12', dev_w, dev_t)],
        style={'gap': '4px', 'width': '100%'})
    heading = label('Heading', 'Phases', dict(SECTION))
    dtr = label('DtrLabel', 'DTR',
                {'fontSize': '13px', 'fontWeight': '700', 'color': COPPER},
                prop_config={'props.text': {'binding': expr_binding(
                    f"if({drop_e} >= 0, 'DTR ' + numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', "
                    f"'DTR target ' + numberFormat(({tt} - {tf}) * 100.0 / {tt}, '0.0') + '%')")}})
    head = flex('HeadRow', 'row', [heading, dtr],
                justify='space-between', align='center')
    root = flex('root', 'column', [head, bar],
                style=dict(CARD_STYLE, gap='10px', padding='14px 18px'))
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1200, 'height': 108}},
            'root': root}

# ---------------------------------------------------------------- Controls

EV_BTN = {'fontSize': '13px', 'fontWeight': '700', 'color': '#ffffff',
          'borderRadius': '10px', 'padding': '10px 6px',
          'cursor': 'pointer', 'border': 'none', 'width': '100%'}
EV_POS = {'grow': 1, 'shrink': 1, 'basis': '104px'}

def ev_button(name, text, color, enabled_expr, script):
    return button(name, text, dict(EV_BTN, backgroundColor=color),
                  position=dict(EV_POS),
                  prop_config={'props.enabled': {'binding': expr_binding(
                      enabled_expr)}},
                  events=script_event(script))

def controls_view():
    st = ref(T('State'))
    heading = label('Heading', 'Roaster Controls', dict(SECTION))
    mode = label('ModePill', 'Off',
                 {'fontSize': '11px', 'fontWeight': '700', 'color': '#ffffff',
                  'backgroundColor': '#57534e', 'padding': '3px 12px',
                  'borderRadius': '999px'},
                 prop_config={
                     'props.text': {'binding': expr_binding(
                         f"'MODE ' + {ref(T('Mode'))}")},
                     'props.style.backgroundColor': {'binding': {
                         'type': 'tag',
                         'config': {'tagPath': T('Mode'), 'mode': 'direct',
                                    'bidirectional': False},
                         'transforms': [{'type': 'map',
                             'inputType': 'scalar', 'outputType': 'color',
                             'fallback': '#57534e',
                             'mappings': [
                                 {'input': 'Off', 'output': '#57534e'},
                                 {'input': 'Roast', 'output': '#b91c1c'},
                                 {'input': 'Cool', 'output': '#0284c7'}]}]}}})
    head = flex('HeadRow', 'row', [heading, mode],
                justify='space-between', align='center')

    def ev(stem):
        return ref(T(stem + 'ElapsedSec'))
    roasting = f"{st} = 'Roasting'"
    row1 = flex('EventRow1', 'row', [
        ev_button('ChargeButton', 'Charge', '#b91c1c',
                  f"{st} = 'Idle' || {st} = 'Complete'", CHARGE_SCRIPT),
        ev_button('DryEndButton', 'Dry End', '#d97706',
                  f"{roasting} && {ev('DryEnd')} < 0",
                  event_script('DryEnd', 'Dry End')),
        ev_button('FCStartButton', 'FC Start', '#ea580c',
                  f"{roasting} && {ev('DryEnd')} >= 0 && {ev('FirstCrackStart')} < 0",
                  event_script('FirstCrackStart', 'First Crack Start')),
        ev_button('FCEndButton', 'FC End', '#ea580c',
                  f"{roasting} && {ev('FirstCrackStart')} >= 0 && {ev('FirstCrackEnd')} < 0",
                  event_script('FirstCrackEnd', 'First Crack End'))],
        wrap='wrap', style={'gap': '8px'})
    row2 = flex('EventRow2', 'row', [
        ev_button('SCStartButton', 'SC Start', '#9a3412',
                  f"{roasting} && {ev('FirstCrackStart')} >= 0 && {ev('SecondCrackStart')} < 0",
                  event_script('SecondCrackStart', 'Second Crack Start')),
        ev_button('SCEndButton', 'SC End', '#9a3412',
                  f"{roasting} && {ev('SecondCrackStart')} >= 0 && {ev('SecondCrackEnd')} < 0",
                  event_script('SecondCrackEnd', 'Second Crack End')),
        ev_button('DropButton', 'Drop', '#7c2d12',
                  f"{roasting} && {ev('Drop')} < 0", DROP_SCRIPT),
        ev_button('CoolButton', 'Cool', '#0369a1',
                  f"{st} = 'Dropped'", COOL_SCRIPT)],
        wrap='wrap', style={'gap': '8px'})
    row3 = flex('EventRow3', 'row', [
        ev_button('FinishButton', 'Finish', '#15803d',
                  f"{st} = 'Cooling'", FINISH_SCRIPT),
        ev_button('ResetButton', 'Reset', '#57534e',
                  f"{st} != 'Idle'", RESET_SCRIPT)] +
        [ev_button(f'CustomButton{i}',
                   f'Custom {i}', '#6d28d9',
                   roasting, custom_event_script(i),
                   ) for i in (1, 2, 3, 4)],
        wrap='wrap', style={'gap': '8px'})
    # custom button labels bind to the configured names
    for i, comp in enumerate(row3['children'][2:], start=1):
        comp['propConfig']['props.text'] = {'binding': tag_binding(
            T(f'CustomEvent{i}Name'))}

    def stepper(name, caption, member, color):
        val = label(name + 'Value', '5',
                    {'fontSize': '26px', 'fontWeight': '700', 'color': INK,
                     'textAlign': 'center', 'minWidth': '44px'},
                    prop_config={'props.text': {'binding': fmt_tag(
                        T(member), '0')}})
        minus = button(name + 'Minus', '−',
                       dict(BTN_BASE, backgroundColor='#57534e',
                            padding='6px 14px', fontSize='17px'),
                       events=script_event(stepper_script(member, -1,
                                                          caption)))
        plus = button(name + 'Plus', '+',
                      dict(BTN_BASE, backgroundColor=color,
                           padding='6px 14px', fontSize='17px'),
                      events=script_event(stepper_script(member, 1,
                                                         caption)))
        cap = label(name + 'Caption', caption.upper(), dict(CAPTION),
                    )
        inner = flex(name + 'Row', 'row', [minus, val, plus],
                     align='center', justify='center',
                     style={'gap': '8px'})
        return flex(name, 'column', [cap, inner], align='center',
                    style={'gap': '4px'},
                    position={'grow': 1, 'shrink': 1, 'basis': '150px'})

    steppers = flex('Steppers', 'row', [
        stepper('FanStepper', 'Fan', 'FanLevel', '#b45309'),
        stepper('HeatStepper', 'Heat', 'HeatLevel', '#b91c1c')],
        wrap='wrap', style={'gap': '14px'})
    setup_btn = button('RoastSetupButton', 'Roast Setup',
                       dict(BTN_BASE, backgroundColor=ESPRESSO_HEX),
                       events=POPUP_OPEN)
    footer = flex('FooterRow', 'row', [setup_btn], justify='flex-end')
    root = flex('root', 'column',
                [head, row1, row2, row3, steppers, footer],
                style=dict(CARD_STYLE, gap='10px'))
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 560, 'height': 430}},
            'root': root}

ESPRESSO_HEX = '#3e2723'

# ---------------------------------------------------------------- MetaCard

def meta_card_view():
    heading = label('Heading', 'Batch Metadata', dict(SECTION))
    edit_btn = button('EditButton', 'Edit',
                      {'fontSize': '12px', 'fontWeight': '700',
                       'color': '#ffffff', 'backgroundColor': ESPRESSO_HEX,
                       'borderRadius': '8px', 'padding': '6px 16px',
                       'cursor': 'pointer', 'border': 'none'},
                      events=POPUP_OPEN)
    head = flex('HeadRow', 'row', [heading, edit_btn],
                justify='space-between', align='center')

    def pair(caption, value_comp):
        cap = label(caption.replace(' ', '') + 'Cap', caption,
                    dict(CAPTION))
        return flex(caption.replace(' ', '') + 'Pair', 'column',
                    [cap, value_comp], style={'gap': '2px'},
                    position={'grow': 1, 'shrink': 1, 'basis': '128px'})

    def val(name, binding, fmt=None, suffix=''):
        style = {'fontSize': '14px', 'fontWeight': '600', 'color': INK}
        pc = {'props.text': {'binding': binding}}
        return label(name, '', style, prop_config=pc)

    def tagval(member, fmt=None, suffix=''):
        if fmt:
            return fmt_tag(T(member), fmt)
        b = tag_binding(T(member))
        if suffix:
            b = {'type': 'tag', 'config': b['config'],
                 'transforms': [{'type': 'expr', 'expression':
                                 '{value} + \'' + suffix + '\''}]}
        return b

    rows = [
        [('Bean', tagval('BeanName')), ('Origin', tagval('Origin'))],
        [('Region', tagval('Region')), ('Farm', tagval('Farm'))],
        [('Altitude', tagval('Altitude')), ('Variety', tagval('Variety'))],
        [('Process', tagval('Process')), ('Harvest', fmt_tag(T('HarvestYear'), '0'))],
        [('Moisture', fmt_tag(T('MoisturePct'), '0.0')), ('Density', fmt_tag(T('DensityGL'), '0'))],
        [('Charge', fmt_tag(T('ChargeWeightG'), '0')), ('Operator', tagval('OperatorName'))],
    ]
    kids = [head]
    for ri, rowpairs in enumerate(rows):
        kids.append(flex(f'Row{ri}', 'row',
                         [pair(cap, val(f'V{ri}{ci}', b))
                          for ci, (cap, b) in enumerate(rowpairs)],
                         wrap='wrap', style={'gap': '12px'}))
    suffix_note = label('UnitsNote', 'Moisture in %, density in g/L, charge in g',
                        {'fontSize': '11px', 'color': FAINT})
    kids.append(suffix_note)
    root = flex('root', 'column', kids, style=dict(CARD_STYLE, gap='9px'))
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 460, 'height': 430}},
            'root': root}

# ---------------------------------------------------------------- Summary

def summary_view():
    heading = label('Heading', 'Roast Summary', dict(SECTION))
    drop_e = ref(T('DropElapsedSec'))
    dry_e = ref(T('DryEndElapsedSec'))
    fc_e = ref(T('FirstCrackStartElapsedSec'))

    def line(name, caption, text_expr):
        cap = label(name + 'Cap', caption, dict(CAPTION),
                    position={'grow': 1, 'shrink': 1, 'basis': '0px'})
        v = label(name + 'Val', '',
                  {'fontSize': '14px', 'fontWeight': '700', 'color': INK,
                   'textAlign': 'right'},
                  prop_config={'props.text': {'binding': expr_binding(
                      text_expr)}})
        return flex(name, 'row', [cap, v], justify='space-between',
                    align='baseline', style={'gap': '10px'})

    def mmss_or_dash(e):
        return f"if({e} >= 0, {mmss_int(e)}, '--:--')"
    lines = [
        line('Total', 'Total time', mmss_or_dash(drop_e)),
        line('Dry', 'Drying', mmss_or_dash(dry_e)),
        line('Mai', 'Maillard',
             f"if({fc_e} >= 0 && {dry_e} >= 0, {mmss_int(f'({fc_e} - {dry_e})')}, '--:--')"),
        line('Dev', 'Development',
             f"if({drop_e} >= 0 && {fc_e} >= 0, {mmss_int(f'({drop_e} - {fc_e})')}, '--:--')"),
        line('Dtr', 'Dev ratio (DTR)',
             f"if({drop_e} > 0 && {fc_e} >= 0, numberFormat(({drop_e} - {fc_e}) * 100.0 / {drop_e}, '0.0') + '%', '--')"),
        line('DropT', 'Drop temp',
             f"if({drop_e} >= 0, numberFormat({ref(T('DropTempF'))}, '0') + ' F', '--')"),
        line('Degree', 'Roast degree',
             f"if({drop_e} < 0, '--', "
             f"if({ref(T('DropTempF'))} < 390, 'Cinnamon', "
             f"if({ref(T('DropTempF'))} < 396, 'New England', "
             f"if({ref(T('DropTempF'))} < 401, 'American', "
             f"if({ref(T('DropTempF'))} < 406, 'City', "
             f"if({ref(T('DropTempF'))} < 411, 'City+', "
             f"if({ref(T('DropTempF'))} < 416, 'Full City', "
             f"if({ref(T('DropTempF'))} < 421, 'Full City+', "
             f"if({ref(T('DropTempF'))} < 426, 'Vienna', "
             f"if({ref(T('DropTempF'))} < 436, 'French', 'Italian'))))))))))"),
        line('WOut', 'Weight out',
             f"if({ref(T('WeightOutG'))} > 0, numberFormat({ref(T('WeightOutG'))}, '0') + ' g', 'not entered')"),
        line('Loss', 'Weight loss',
             f"if({ref(T('WeightOutG'))} > 0 && {ref(T('ChargeWeightG'))} > 0, numberFormat(({ref(T('ChargeWeightG'))} - {ref(T('WeightOutG'))}) * 100.0 / {ref(T('ChargeWeightG'))}, '0.0') + '%', '--')"),
    ]
    save_btn = button('SaveButton', 'Save to Roast Log',
                      dict(BTN_BASE, backgroundColor='#15803d',
                           padding='9px 18px', fontSize='13px'),
                      prop_config={'props.enabled': {'binding': expr_binding(
                          f"{drop_e} >= 0")}},
                      events=script_event(SAVE_SCRIPT))
    note = label('SaveNote', '',
                 {'fontSize': '12px', 'color': GREEN},
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.custom.saveNote')}})
    foot = flex('FootRow', 'column', [save_btn, note],
                style={'gap': '6px'})
    root = flex('root', 'column', [heading] + lines + [foot],
                style=dict(CARD_STYLE, gap='8px'))
    return {'custom': {'saveNote': ''}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 380, 'height': 430}},
            'root': root}

# ---------------------------------------------------------------- Config (popup)

def text_in(name, member, placeholder=''):
    return {'type': 'ia.input.text-field', 'meta': {'name': name},
            'props': {'text': '', 'placeholder': placeholder,
                      'style': dict(INPUT_STYLE)},
            'propConfig': {'props.text': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def num_in(name, member, fmt='0'):
    return {'type': 'ia.input.numeric-entry-field', 'meta': {'name': name},
            'props': {'value': 0, 'format': fmt,
                      'style': dict(INPUT_STYLE)},
            'propConfig': {'props.value': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def check_in(name, member):
    return {'type': 'ia.input.checkbox', 'meta': {'name': name},
            'props': {'selected': False,
                      'style': {'color': INK}},
            'propConfig': {'props.selected': {'binding': tag_binding(
                T(member), bidirectional=True)}}}

def cfg_field(name, caption, comp, basis='180px'):
    cap = label(name + 'Cap', caption,
                {'fontSize': '11px', 'fontWeight': '700', 'color': MUTED,
                 'textTransform': 'uppercase', 'letterSpacing': '0.06em'})
    return flex(name, 'column', [cap, comp], style={'gap': '4px'},
                position={'grow': 1, 'shrink': 1, 'basis': basis})

def cfg_row(name, fields):
    return flex(name, 'row', fields, wrap='wrap', style={'gap': '12px'})

def cfg_section(name, title, children):
    head = label(name + 'Head', title, dict(SECTION))
    return flex(name, 'column', [head] + children,
                style={'gap': '9px', 'borderTop': '1px solid #3d2716',
                       'paddingTop': '13px'})

def config_view():
    title = label('Title', 'Roast Setup',
                  {'fontSize': '19px', 'fontWeight': '700', 'color': INK})
    status = label('StatusLabel', '',
                   {'fontSize': '12px', 'fontWeight': '700'},
                   prop_config={
                       'props.text': {'binding': expr_binding(
                           f"if({ref(T('BeanTempF'))} > 0, 'SR800 Connected', 'SR800 Disconnected')")},
                       'props.style.color': {'binding': expr_binding(
                           f"if({ref(T('BeanTempF'))} > 0, '{GREEN}', '{RED}')")}})
    head = flex('HeadRow', 'row', [title, status],
                justify='space-between', align='center')

    probe = label('ProbeReadout', '',
                  {'fontSize': '14px', 'fontWeight': '600', 'color': INK},
                  prop_config={'props.text': {'binding': expr_binding(
                      f"'Probe now: ' + numberFormat({ref(T('BeanTempF'))}, '0.0') + ' F · RoR ' + numberFormat({ref(T('RateOfRiseF'))}, '0.0') + ' F/min'")}})
    roaster = cfg_section('RoasterSection', 'Roaster', [
        cfg_row('WsRow', [cfg_field('WsField', 'WebSocket URL',
                                    text_in('WsUrlField', 'WsUrl',
                                            'ws://sr800.local:8080'),
                                    basis='300px')]),
        cfg_row('RoasterRow2', [
            cfg_field('RorSmoothField', 'RoR smoothing (sec)',
                      num_in('RorSmoothNum', 'RoRSmoothingSec')),
            cfg_field('ProbeField', 'Live probe', probe, basis='240px')]),
    ])

    target = cfg_section('TargetSection', 'Target Profile', [
        cfg_row('TargetRow1', [
            cfg_field('TChargeField', 'Charge temp (F)',
                      num_in('TChargeNum', 'TargetChargeTempF')),
            cfg_field('TDrySecField', 'Dry end time (sec)',
                      num_in('TDrySecNum', 'TargetDryEndSec')),
            cfg_field('TDryTempField', 'Dry end temp (F)',
                      num_in('TDryTempNum', 'TargetDryEndTempF'))]),
        cfg_row('TargetRow2', [
            cfg_field('TFcSecField', 'First crack time (sec)',
                      num_in('TFcSecNum', 'TargetFCSec')),
            cfg_field('TFcTempField', 'First crack temp (F)',
                      num_in('TFcTempNum', 'TargetFCTempF')),
            cfg_field('TDropSecField', 'Drop time (sec)',
                      num_in('TDropSecNum', 'TargetDropSec')),
            cfg_field('TDropTempField', 'Drop temp (F)',
                      num_in('TDropTempNum', 'TargetDropTempF', '0'))]),
    ])

    meta = cfg_section('MetaSection', 'Batch Metadata', [
        cfg_row('MetaRow1', [
            cfg_field('BeanField', 'Bean name', text_in('BeanFieldIn', 'BeanName')),
            cfg_field('OriginField', 'Origin', text_in('OriginIn', 'Origin'))]),
        cfg_row('MetaRow2', [
            cfg_field('RegionField', 'Region', text_in('RegionIn', 'Region')),
            cfg_field('FarmField', 'Farm / station', text_in('FarmIn', 'Farm'))]),
        cfg_row('MetaRow3', [
            cfg_field('AltField', 'Altitude', text_in('AltIn', 'Altitude')),
            cfg_field('VarField', 'Variety', text_in('VarIn', 'Variety'))]),
        cfg_row('MetaRow4', [
            cfg_field('ProcField', 'Process', text_in('ProcIn', 'Process')),
            cfg_field('HarvField', 'Harvest year', num_in('HarvIn', 'HarvestYear'))]),
        cfg_row('MetaRow5', [
            cfg_field('MoisField', 'Moisture (%)', num_in('MoisIn', 'MoisturePct', '0.0')),
            cfg_field('DensField', 'Density (g/L)', num_in('DensIn', 'DensityGL'))]),
        cfg_row('MetaRow6', [
            cfg_field('ChargeGField', 'Charge weight (g)', num_in('ChargeGIn', 'ChargeWeightG')),
            cfg_field('LevelField', 'Roast level', text_in('LevelIn', 'RoastLevel'))]),
        cfg_row('MetaRow7', [
            cfg_field('OperField', 'Operator', text_in('OperIn', 'OperatorName')),
            cfg_field('NotesField', 'Notes',
                      {'type': 'ia.input.text-area',
                       'meta': {'name': 'NotesIn'},
                       'props': {'text': '',
                                 'style': dict(INPUT_STYLE, minHeight='54px')},
                       'propConfig': {'props.text': {'binding': tag_binding(
                           T('Notes'), bidirectional=True)}}},
                      basis='300px')]),
    ])

    custom_rows = []
    for i in (1, 2, 3, 4):
        custom_rows.append(cfg_row(f'CustomRow{i}', [
            cfg_field(f'CustomNameField{i}', f'Custom {i} name',
                      text_in(f'CustomNameIn{i}', f'CustomEvent{i}Name')),
            cfg_field(f'CustomKindField{i}', f'Custom {i} kind',
                      text_in(f'CustomKindIn{i}', f'CustomEvent{i}Kind'))]))
    customs = cfg_section('CustomSection', 'Custom Events', custom_rows)

    def alarm_row(name, caption, check_member, fields):
        chk = check_in(name + 'Check', check_member)
        cap = label(name + 'Cap', caption,
                    {'fontSize': '13px', 'fontWeight': '700', 'color': INK,
                     'minWidth': '130px'})
        return flex(name, 'row', [chk, cap] + fields, align='center',
                    wrap='wrap', style={'gap': '10px'})
    alarms = cfg_section('AlarmSection', 'Alarms', [
        alarm_row('AlarmHigh', 'High bean temp', 'AlarmHighTempEnabled', [
            num_in('AlarmHighNum', 'AlarmHighTempF'),
            text_in('AlarmHighMsgIn', 'AlarmHighTempMsg')]),
        alarm_row('AlarmDrop', 'Drop approaching', 'AlarmDropEnabled', [
            num_in('AlarmDropNum', 'AlarmDropDeltaF')]),
        alarm_row('AlarmFC', 'First crack watch', 'AlarmFCWatchEnabled', [
            num_in('AlarmFCNum', 'AlarmFCWindowSec')]),
    ])

    results = cfg_section('ResultsSection', 'Results', [
        cfg_row('ResultsRow', [
            cfg_field('WOutField', 'Weight out (g)',
                      {'type': 'ia.input.numeric-entry-field',
                       'meta': {'name': 'WOutIn'},
                       'props': {'value': 0, 'format': '0',
                                 'style': dict(INPUT_STYLE)},
                       'propConfig': {
                           'props.value': {'binding': tag_binding(
                               T('WeightOutG'), bidirectional=True)},
                           'props.enabled': {'binding': expr_binding(
                               f"{ref(T('DropElapsedSec'))} >= 0")}}},
                      basis='180px')]),
    ])

    close_btn = button('CloseButton', 'Close',
                       dict(BTN_BASE, backgroundColor=ESPRESSO_HEX),
                       events=POPUP_CLOSE)
    footer = flex('Footer', 'row', [close_btn], justify='flex-end')
    root = flex('root', 'column',
                [head, roaster, target, meta, customs, alarms, results,
                 footer],
                style={'backgroundColor': '#2a1c10', 'padding': '20px 22px',
                       'gap': '15px', 'height': '100%',
                       'overflowY': 'auto'})

    def _no_shrink(node):
        # Flex children must keep their natural size so the root's
        # overflowY auto scrolls on short screens (phones) instead of
        # the sections compressing and overlapping (seen at 390x844).
        if isinstance(node, dict):
            for child in node.get('children', []) or []:
                pos = child.setdefault('position', {})
                pos['shrink'] = 0
                _no_shrink(child)
    _no_shrink(root)
    return {'custom': {}, 'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 700, 'height': 880}},
            'root': root}

# ---------------------------------------------------------------- Log (page /log)

NAV_CONSOLE_SCRIPT = "\tsystem.perspective.navigate(page='/')\n"
NAV_LOG_SCRIPT = "\tsystem.perspective.navigate(page='/log')\n"

ROWCLICK_SCRIPT = (
    "\trow = event.value\n"
    "\ttry:\n"
    "\t\tcurve = row['curveJson']\n"
    "\t\tbatch = row['batch']\n"
    "\t\tbean = row['bean']\n"
    "\texcept:\n"
    "\t\tcurve = row.get('curveJson')\n"
    "\t\tbatch = row.get('batch')\n"
    "\t\tbean = row.get('bean')\n"
    "\tself.view.custom.selCurve = curve\n"
    "\tself.view.custom.selLabel = 'Batch ' + str(batch) + ' · ' + str(bean)\n"
    "\tself.view.custom.selNote = 'Selected batch ' + str(batch) + ' (' + str(bean) + '). Choose View as Background to overlay it on the console.'\n")

BG_SET_SCRIPT = (
    "\tcurve = self.view.custom.selCurve\n"
    "\tlabel = self.view.custom.selLabel\n"
    "\tif curve:\n"
    "\t\tsystem.tag.writeBlocking(['[default]Roastery/BackgroundCurveJson', '[default]Roastery/BackgroundLabel'], [curve, label])\n"
    "\t\tB = '[default]Roastery/CurrentBatch'\n"
    "\t\tstart = system.tag.readBlocking([B + '/StartTime'])[0].value\n"
    "\t\tif start is not None:\n"
    "\t\t\tfrom java.util import Date\n"
    "\t\t\timport json as _json\n"
    "\t\t\trows = []\n"
    "\t\t\tstartMs = start.getTime()\n"
    "\t\t\tfor pair in _json.loads(curve):\n"
    "\t\t\t\trows.append([Date(long(startMs + float(pair[0]) * 1000)), float(pair[1])])\n"
    "\t\t\tsystem.tag.writeBlocking(['[default]Roastery/BackgroundDS'], [system.dataset.toDataSet(['t_stamp', 'bg'], rows)])\n"
    "\tsystem.perspective.navigate(page='/')\n")

def log_view():
    title = label('Title', 'Roast Log',
                  {'fontSize': '20px', 'fontWeight': '700', 'color': INK})
    console_btn = button('ConsoleButton', 'Back to Console',
                         dict(BTN_BASE, backgroundColor=ESPRESSO_HEX,
                              padding='8px 18px', fontSize='13px'),
                         events=script_event(NAV_CONSOLE_SCRIPT))
    head = flex('HeadRow', 'row', [title, console_btn],
                justify='space-between', align='center')
    cols = [
        {'field': 'batch', 'header': {'title': 'Batch'}, 'width': 70},
        {'field': 'roastDate', 'header': {'title': 'Date'}, 'width': 150,
         'render': 'date', 'dateFormat': 'YYYY-MM-DD h:mm a'},
        {'field': 'bean', 'header': {'title': 'Bean'}, 'width': 150},
        {'field': 'origin', 'header': {'title': 'Origin'}, 'width': 130},
        {'field': 'chargeG', 'header': {'title': 'Charge (g)'}, 'width': 90},
        {'field': 'dropTempF', 'header': {'title': 'Drop (F)'}, 'width': 80},
        {'field': 'totalSec', 'header': {'title': 'Total (s)'}, 'width': 80},
        {'field': 'drySec', 'header': {'title': 'Dry (s)'}, 'width': 70},
        {'field': 'maillardSec', 'header': {'title': 'Maillard (s)'}, 'width': 90},
        {'field': 'devSec', 'header': {'title': 'Dev (s)'}, 'width': 70},
        {'field': 'dtrPct', 'header': {'title': 'DTR %'}, 'width': 70},
        {'field': 'weightLossPct', 'header': {'title': 'Loss %'}, 'width': 70},
        {'field': 'auc', 'header': {'title': 'AUC'}, 'width': 70},
        {'field': 'level', 'header': {'title': 'Degree'}, 'width': 100},
        {'field': 'curveJson', 'header': {'title': 'Curve'}, 'width': 60,
         'visible': False},
    ]
    table = {'type': 'ia.display.table', 'meta': {'name': 'RoastTable'},
             'props': {'data': [], 'columns': cols,
                       'pager': {'enabled': False},
                       'rows': {'height': 34},
                       'header': {'height': 36, 'style': {
                           'backgroundColor': '#3a2413', 'color': CREAM,
                           'fontWeight': '700', 'fontSize': '12px'}},
                       'style': {'fontSize': '13px', 'color': INK,
                                 'backgroundColor': 'rgba(21, 14, 8, 0.4)'}},
             'propConfig': {'props.data': {'binding': tag_binding(RLOG)}},
             'events': {'component': {'onRowClick': {
                 'scope': 'G', 'type': 'script',
                 'config': {'script': ROWCLICK_SCRIPT}}}},
             'position': {'grow': 0, 'shrink': 0, 'basis': '380px'}}
    note = label('SelNote', 'Select a roast to view it as a background.',
                 {'fontSize': '13px', 'color': MUTED},
                 prop_config={'props.text': {'binding': prop_binding(
                     'view.custom.selNote')}})
    bg_btn = button('BgButton', 'View as Background',
                    dict(BTN_BASE, backgroundColor='#6d28d9',
                         padding='9px 20px', fontSize='13px'),
                    events=script_event(BG_SET_SCRIPT))
    foot = flex('FootRow', 'row', [note, bg_btn],
                justify='space-between', align='center',
                style={'gap': '12px'})
    card = flex('LogCard', 'column', [table, foot],
                style=dict(CARD_STYLE, gap='12px'))
    content = flex('Content', 'column', [head, card],
                   style={'padding': '18px 22px', 'gap': '14px'})
    root = flex('root', 'column', [content],
                style={'backgroundColor': PAGE_BG, 'minHeight': '100%'})
    return {'custom': {'selCurve': '', 'selLabel': '',
                       'selNote': 'Select a roast to view it as a background.'},
            'params': {}, 'propConfig': {},
            'props': {'defaultSize': {'width': 1440, 'height': 700}},
            'root': root}

# ---------------------------------------------------------------- charts (XY)

def _xy_templates():
    schema = json.load(open(os.path.join(SCHEMAS, 'ia.chart.xy.json')))
    ex = schema['schema']['properties']
    return (copy.deepcopy(ex['series']['example'][0]),
            copy.deepcopy(ex['xAxes']['example'][0]),
            copy.deepcopy(ex['yAxes']['example'][0]))

def _history_binding(minutes=15):
    return {'type': 'tag-history', 'config': {
        'dateRange': {'type': 'mostRecent', 'mostRecent': minutes,
                      'mostRecentUnits': 'MIN'},
        'tags': [{'path': T('BeanTempF'), 'alias': 'bean',
                  'aggregate': 'Average'},
                 {'path': T('RateOfRiseF'), 'alias': 'ror',
                  'aggregate': 'Average'}],
        'queryOptions': {'returnFormat': 'wide',
                         'returnSize': {'type': 'interval',
                                        'interval': '5 sec'}},
        'polling': {'enabled': True, 'rate': 5},
        'valueFormat': 'dataset', 'ignoreBadQuality': True}}

def main_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, source, y, axis, color, width, render='line',
               dash=None, opacity=1.0, fill_opacity=0.0):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': source, 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = axis
        s['render'] = render
        key = 'stepLine' if render == 'step line' else 'line'
        s[key]['appearance']['stroke']['color'] = color
        s[key]['appearance']['stroke']['width'] = width
        s[key]['appearance']['stroke']['opacity'] = opacity
        if dash:
            s[key]['appearance']['stroke']['dashArray'] = dash
        if fill_opacity:
            s[key]['appearance']['fill']['color'] = color
            s[key]['appearance']['fill']['opacity'] = fill_opacity
        s[key]['appearance']['bullets'][0]['enabled'] = False
        return s

    xaxis = copy.deepcopy(xaxis_tpl)
    xaxis['name'] = 'time'
    xaxis['render'] = 'date'
    xaxis['label'] = {'enabled': True, 'text': 'Time', 'color': ''}

    temp_axis = copy.deepcopy(yaxis_tpl)
    temp_axis['name'] = 'temp'
    temp_axis['render'] = 'value'
    temp_axis['label'] = {'enabled': True, 'text': 'Bean Temp (deg F)',
                          'color': ''}
    temp_axis['value']['range'] = {'min': 150, 'max': 460,
                                  'useStrict': True}
    ror_axis = copy.deepcopy(yaxis_tpl)
    ror_axis['name'] = 'ror'
    ror_axis['render'] = 'value'
    ror_axis['label'] = {'enabled': True,
                         'text': 'Rate of Rise (deg F/min)', 'color': ''}
    ror_axis['value']['range'] = {'min': 0, 'max': 40, 'useStrict': True}
    ror_axis['appearance']['opposite'] = True

    return {
        'type': 'ia.chart.xy', 'meta': {'name': 'RoastChart'},
        'props': {
            'dataSources': {'trend': [], 'plan': [], 'bg': []},
            'xAxes': [xaxis], 'yAxes': [temp_axis, ror_axis],
            'series': [
                series('Background', 'bg', 'bg', 'temp', '#a1887f', 2,
                       opacity=0.5),
                series('Target', 'plan', 'plan', 'temp', '#e7dccb', 2,
                       dash='7 5', opacity=0.85),
                series('Bean Temp', 'trend', 'bean', 'temp', AMBER, 3,
                       fill_opacity=0.13),
                series('Rate of Rise', 'trend', 'ror', 'ror', SKY, 2)],
            'legend': {'enabled': True, 'position': 'bottom'},
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {
            'props.dataSources.trend': {'binding': _history_binding()},
            'props.dataSources.plan': {'binding': tag_binding(
                '[default]Roastery/TargetProfileDS')},
            'props.dataSources.bg': {'binding': tag_binding(
                '[default]Roastery/BackgroundDS')}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}

def trace_chart():
    series_tpl, xaxis_tpl, yaxis_tpl = _xy_templates()

    def series(name, y, color):
        s = copy.deepcopy(series_tpl)
        s['name'] = name
        s['label'] = {'text': name}
        s['data'] = {'source': 'events', 'x': 't_stamp', 'y': y}
        s['xAxis'] = 'time'
        s['yAxis'] = 'level'
        s['render'] = 'step line'
        s['stepLine']['appearance']['stroke']['color'] = color
        s['stepLine']['appearance']['stroke']['width'] = 2
        s['stepLine']['appearance']['connect'] = True
        s['stepLine']['appearance']['bullets'][0]['enabled'] = False
        return s

    xaxis = copy.deepcopy(xaxis_tpl)
    xaxis['name'] = 'time'
    xaxis['render'] = 'date'
    xaxis['label'] = {'enabled': False, 'text': '', 'color': ''}
    lvl = copy.deepcopy(yaxis_tpl)
    lvl['name'] = 'level'
    lvl['render'] = 'value'
    lvl['label'] = {'enabled': True, 'text': 'Level', 'color': ''}
    lvl['value']['range'] = {'min': 0, 'max': 10, 'useStrict': True}
    return {
        'type': 'ia.chart.xy', 'meta': {'name': 'TraceChart'},
        'props': {
            'dataSources': {'events': []},
            'xAxes': [xaxis], 'yAxes': [lvl],
            'series': [series('Fan', 'fan', AMBER),
                       series('Heat', 'heat', RED)],
            'legend': {'enabled': True, 'position': 'right'},
            'style': {'backgroundColor': 'transparent'}},
        'propConfig': {'props.dataSources.events': {'binding':
                       tag_binding(LOG)}},
        'position': {'grow': 1, 'shrink': 1, 'basis': '0px'}}

# ---------------------------------------------------------------- Main

TARGET_AT = (
    f"if({ELAPSED_SEC} <= {ref(T('TargetDryEndSec'))}, "
    f"{ref(T('TargetChargeTempF'))} + ({ref(T('TargetDryEndTempF'))} - {ref(T('TargetChargeTempF'))}) * {ELAPSED_SEC} / {ref(T('TargetDryEndSec'))}, "
    f"if({ELAPSED_SEC} <= {ref(T('TargetFCSec'))}, "
    f"{ref(T('TargetDryEndTempF'))} + ({ref(T('TargetFCTempF'))} - {ref(T('TargetDryEndTempF'))}) * ({ELAPSED_SEC} - {ref(T('TargetDryEndSec'))}) / ({ref(T('TargetFCSec'))} - {ref(T('TargetDryEndSec'))}), "
    f"if({ELAPSED_SEC} <= {ref(T('TargetDropSec'))}, "
    f"{ref(T('TargetFCTempF'))} + ({ref(T('TargetDropTempF'))} - {ref(T('TargetFCTempF'))}) * ({ELAPSED_SEC} - {ref(T('TargetFCSec'))}) / ({ref(T('TargetDropSec'))} - {ref(T('TargetFCSec'))}), "
    f"{ref(T('TargetDropTempF'))})))")

ALARM_ACTIVE = (
    f"({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}) || "
    f"({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}) || "
    f"({ref(T('AlarmFCWatchEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('FirstCrackStartElapsedSec'))} < 0 && "
    f"{ELAPSED_SEC} >= ({ref(T('TargetFCSec'))} - {ref(T('AlarmFCWindowSec'))}) && "
    f"{ELAPSED_SEC} <= ({ref(T('TargetFCSec'))} + {ref(T('AlarmFCWindowSec'))}))")

ALARM_TEXT = (
    f"if({ref(T('AlarmHighTempEnabled'))} && {ref(T('BeanTempF'))} >= {ref(T('AlarmHighTempF'))}, "
    f"{ref(T('AlarmHighTempMsg'))} + ' -- now ' + numberFormat({ref(T('BeanTempF'))}, '0') + ' F', "
    f"if({ref(T('AlarmDropEnabled'))} && {ref(T('State'))} = 'Roasting' && {ref(T('BeanTempF'))} >= {ref(T('TargetDropTempF'))} - {ref(T('AlarmDropDeltaF'))}, "
    f"'Drop approaching -- target ' + numberFormat({ref(T('TargetDropTempF'))}, '0') + ' F', "
    f"'First crack watch -- listen for cracks'))")

CLOCK_EXPR = (
    f"if({ref(T('State'))} = 'Roasting', {mmss_ms(ELAPSED_MS)}, "
    f"if({ref(T('DropElapsedSec'))} >= 0, {mmss_int(ref(T('DropElapsedSec')))}, '00:00'))")

DEVIATION_EXPR = (
    f"if({ref(T('State'))} != 'Roasting', '--', "
    f"numberFormat({ref(T('BeanTempF'))} - ({TARGET_AT}), '+0.0;-0.0') + ' F')")

PHASE_EXPR = (
    f"if({ref(T('State'))} = 'Idle', 'Pre-charge', "
    f"if({ref(T('State'))} = 'Dropped', 'Dropped', "
    f"if({ref(T('State'))} = 'Cooling', 'Cooling', "
    f"if({ref(T('State'))} = 'Complete', 'Complete', "
    f"if({ref(T('SecondCrackStartElapsedSec'))} >= 0, 'Second Crack', "
    f"if({ref(T('FirstCrackStartElapsedSec'))} >= 0, 'Development', "
    f"if({ref(T('DryEndElapsedSec'))} >= 0, 'Maillard', 'Drying')))))))")

def main_view():
    title = label('TitleLabel', 'Ember & Oak Roastery',
                  {'fontSize': '21px', 'fontWeight': '700', 'color': CREAM})
    sub = label('SubLabel', 'Artisan Roast Console · FreshRoast SR800',
                {'fontSize': '12px', 'color': MUTED})
    title_block = flex('TitleBlock', 'column', [title, sub],
                       style={'gap': '2px'})

    batch_chip = label('BatchChip', '',
                       {'fontSize': '13px', 'fontWeight': '600',
                        'color': CREAM},
                       prop_config={'props.text': {'binding': expr_binding(
                           f"'Batch ' + {ref(T('BatchNumber'))} + ' · ' + {ref(T('BeanName'))}")}})
    ws_pill = label('WsPill', 'SR800',
                    {'fontSize': '11px', 'fontWeight': '700',
                     'color': '#ffffff', 'padding': '4px 12px',
                     'borderRadius': '999px',
                     'boxShadow': '0 0 10px rgba(74, 222, 128, 0.35)'},
                    prop_config={
                        'props.text': {'binding': expr_binding(
                            f"if({ref(T('BeanTempF'))} > 0, 'SR800 CONNECTED', 'SR800 OFFLINE')")},
                        'props.style.backgroundColor': {'binding':
                            expr_binding(
                                f"if({ref(T('BeanTempF'))} > 0, '#166534', '#7f1d1d')")}})
    state_pill = label('StatePill', 'Idle',
                       {'fontSize': '12px', 'fontWeight': '700',
                        'color': '#ffffff', 'padding': '4px 14px',
                        'borderRadius': '999px', 'textAlign': 'center'},
                       prop_config={
                           'props.text': {'binding': tag_binding(T('State'))},
                           'props.style.backgroundColor': {'binding': {
                               'type': 'tag',
                               'config': {'tagPath': T('State'),
                                          'mode': 'direct',
                                          'bidirectional': False},
                               'transforms': [{'type': 'map',
                                   'inputType': 'scalar',
                                   'outputType': 'color',
                                   'fallback': '#78716c',
                                   'mappings': [
                                       {'input': 'Idle',
                                        'output': '#78716c'},
                                       {'input': 'Roasting',
                                        'output': '#dc2626'},
                                       {'input': 'Dropped',
                                        'output': '#d97706'},
                                       {'input': 'Cooling',
                                        'output': '#0284c7'},
                                       {'input': 'Complete',
                                        'output': '#16a34a'}]}]}}})
    clock = label('ClockLabel', '00:00',
                  {'fontSize': '27px', 'fontWeight': '700', 'color': CREAM,
                   'fontFamily': 'monospace'},
                  prop_config={'props.text': {'binding': prop_binding(
                      'view.custom.clockText')}})
    log_btn = button('LogButton', 'Roast Log',
                     {'fontSize': '12px', 'fontWeight': '700',
                      'color': CREAM, 'backgroundColor': 'transparent',
                      'border': f'1px solid {CARD_BORDER}',
                      'borderRadius': '8px', 'padding': '6px 14px',
                      'cursor': 'pointer'},
                     events=script_event(NAV_LOG_SCRIPT))
    right = flex('HeaderRight', 'row',
                 [batch_chip, ws_pill, state_pill, clock, log_btn],
                 align='center', wrap='wrap', style={'gap': '12px'})
    header = flex('HeaderBar', 'row', [title_block, right],
                  justify='space-between', align='center', wrap='wrap',
                  position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
                  style={'backgroundColor': '#2a1a10',
                         'backgroundImage':
                             'linear-gradient(90deg, #241509, #3e2723)',
                         'padding': '10px 22px', 'gap': '10px',
                         'boxShadow': '0 2px 14px rgba(0, 0, 0, 0.5)'})

    alarm = flex('AlarmBanner', 'row', [
        label('AlarmText', '',
              {'fontSize': '14px', 'fontWeight': '700', 'color': '#fff7ed'},
              prop_config={'props.text': {'binding': prop_binding(
                  'view.custom.alarmText')}})],
        align='center',
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
        style={'backgroundColor': '#991b1b', 'padding': '9px 22px',
               'boxShadow': '0 0 18px rgba(239, 68, 68, 0.35)'},
        prop_config={'props.style.display': {'binding': expr_binding(
            f"if({ALARM_ACTIVE}, 'flex', 'none')")}})

    chart_title = label('ChartTitle', 'Roast Curve',
                        {'fontSize': '14px', 'fontWeight': '700',
                         'color': INK})
    bg_chip = label('BgChip', '',
                    {'fontSize': '11px', 'fontWeight': '600',
                     'color': MUTED},
                    prop_config={'props.text': {'binding': expr_binding(
                        f"if({ref('[default]Roastery/BackgroundLabel')} != '', 'Background: ' + {ref('[default]Roastery/BackgroundLabel')}, 'Background: none')")}})
    chart_head = flex('ChartHead', 'row', [chart_title, bg_chip],
                      justify='space-between', align='center',
                      position={'grow': 0, 'shrink': 0, 'basis': '24px'})
    trace_cap = label('TraceCaption', 'Fan / Heat Levels',
                      dict(CAPTION),
                      position={'grow': 0, 'shrink': 0, 'basis': '16px'})
    chart_card = flex('ChartCard', 'column', [
        chart_head, main_chart(), trace_cap,
        flex('TraceWrap', 'row', [trace_chart()],
             position={'grow': 0, 'shrink': 0, 'basis': '104px'})],
        style=dict(CARD_STYLE, gap='8px'),
        position={'grow': 0, 'shrink': 0, 'basis': '560px'})

    strip = embed('EventsStripEmbed', 'Views/EventsStrip', {},
                  {'grow': 0, 'shrink': 0, 'basis': 'auto'})
    phases = embed('PhasesBarEmbed', 'Views/PhasesBar', {},
                   {'grow': 0, 'shrink': 0, 'basis': 'auto'})

    tile_pos = {'grow': 1, 'shrink': 1, 'basis': '148px'}
    tiles = flex('TilesRow', 'row', [
        embed('BeanTile', 'Views/Tile',
              {'title': 'Bean Temp', 'valueText': '0.0', 'unit': 'deg F',
               'accent': AMBER}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('BeanTempF'), '0.0')}}),
        embed('RorTile', 'Views/Tile',
              {'title': 'Rate of Rise', 'valueText': '0.0',
               'unit': 'F/min', 'accent': SKY}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('RateOfRiseF'), '0.0')}}),
        embed('DevTile', 'Views/Tile',
              {'title': 'Deviation', 'valueText': '--', 'unit': '',
               'accent': COPPER}, dict(tile_pos),
              {'props.params.valueText': {'binding': prop_binding(
                  'view.custom.deviationText')}}),
        embed('FanTile', 'Views/Tile',
              {'title': 'Fan', 'valueText': '5', 'unit': '/ 9',
               'accent': COPPER}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('FanLevel'), '0')}}),
        embed('HeatTile', 'Views/Tile',
              {'title': 'Heat', 'valueText': '5', 'unit': '/ 9',
               'accent': RED}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('HeatLevel'), '0')}}),
        embed('PhaseTile', 'Views/Tile',
              {'title': 'Phase', 'valueText': 'Pre-charge', 'unit': '',
               'accent': GREEN}, dict(tile_pos),
              {'props.params.valueText': {'binding': prop_binding(
                  'view.custom.phaseText')}}),
        embed('TargetTile', 'Views/Tile',
              {'title': 'Target Drop', 'valueText': '415',
               'unit': 'deg F', 'accent': FAINT}, dict(tile_pos),
              {'props.params.valueText': {'binding': fmt_tag(
                  T('TargetDropTempF'), '0')}})],
        wrap='wrap', style={'gap': '12px'},
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'})

    bottom = flex('BottomRow', 'row', [
        embed('ControlsEmbed', 'Views/Controls', {},
              {'grow': 5, 'shrink': 1, 'basis': '430px'}),
        embed('MetaCardEmbed', 'Views/MetaCard', {},
              {'grow': 4, 'shrink': 1, 'basis': '360px'}),
        embed('SummaryEmbed', 'Views/Summary', {},
              {'grow': 3, 'shrink': 1, 'basis': '300px'})],
        wrap='wrap', align='flex-start', style={'gap': '14px'},
        position={'grow': 0, 'shrink': 0, 'basis': 'auto'})

    content = flex('Content', 'column',
                   [chart_card, strip, phases, tiles, bottom],
                   position={'grow': 0, 'shrink': 0, 'basis': 'auto'},
                   style={'padding': '16px 20px', 'gap': '14px'})
    root = flex('root', 'column', [header, alarm, content],
                style={'backgroundColor': PAGE_BG})
    return {
        'custom': {'clockText': '00:00', 'deviationText': '--',
                   'phaseText': 'Pre-charge', 'alarmText': ''},
        'params': {},
        'propConfig': {
            'custom.clockText': {'binding': expr_binding(CLOCK_EXPR)},
            'custom.deviationText': {'binding': expr_binding(
                DEVIATION_EXPR)},
            'custom.phaseText': {'binding': expr_binding(PHASE_EXPR)},
            'custom.alarmText': {'binding': expr_binding(ALARM_TEXT)}},
        'props': {'defaultSize': {'width': 1440, 'height': 1240}},
        'root': root}

# ---------------------------------------------------------------- write out

def write_view(path_parts, doc):
    d = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                     'views', *path_parts)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'view.json'), 'w') as f:
        json.dump(doc, f, indent=2)
    with open(os.path.join(d, 'resource.json'), 'w') as f:
        json.dump(RES, f, indent=2)

OLD_VIEWS = ('BatchCard', 'StatTile', 'ControlPanel', 'Settings', 'Probe')

def main():
    views_root = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                              'views', 'Views')
    for old in OLD_VIEWS:
        p = os.path.join(views_root, old)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print('removed old view', old)
    write_view(['Views', 'Main'], main_view())
    write_view(['Views', 'Config'], config_view())
    write_view(['Views', 'Log'], log_view())
    write_view(['Views', 'Tile'], tile_view())
    write_view(['Views', 'EventCell'], event_cell_view())
    write_view(['Views', 'EventsStrip'], events_strip_view())
    write_view(['Views', 'PhasesBar'], phases_bar_view())
    write_view(['Views', 'Controls'], controls_view())
    write_view(['Views', 'MetaCard'], meta_card_view())
    write_view(['Views', 'Summary'], summary_view())
    pc = os.path.join(PROJ, 'com.inductiveautomation.perspective',
                      'page-config')
    os.makedirs(pc, exist_ok=True)
    pages = {'/': {'viewPath': 'Views/Main'},
             '/log': {'viewPath': 'Views/Log'}}
    with open(os.path.join(pc, 'config.json'), 'w') as f:
        json.dump({'pages': pages}, f, indent=2)
    r = dict(RES, files=['config.json'])
    with open(os.path.join(pc, 'resource.json'), 'w') as f:
        json.dump(r, f, indent=2)
    print('Artisan Roastery written to', PROJ)

if __name__ == '__main__':
    main()
