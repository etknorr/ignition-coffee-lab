# Roastery batch persistence: full CRUD for previous batches in
# Postgres, through NAMED QUERIES only. This module is the only
# caller of the batch named queries; no view binding or handler
# carries SQL.
#
# Data model (docs: roastery/docs/coffee-roaster-app.md):
# - batches: surrogate id PK, batch_number UNIQUE (the human batch
#   number), relational columns only for listing and sorting
#   (roast_start, roast_end, bean_name, drop_temp_f), and a `data`
#   JSONB column with the complete batch document (metadata, events
#   with times and temps, phase durations, DTR, AUC, weights, roast
#   degree, target profile, notes), so the batch schema can evolve
#   without migrations.
# - batch_series: one row per curve sample keyed by batch_number
#   (FK, ON DELETE CASCADE): t_offset_sec, sample_ts, bean_temp_f,
#   rate_of_rise_f, fan_level, heat_level. Written at save time from
#   the CurveSamples dataset roastery.core records during the roast,
#   through Series/InsertBatch (one call; the points travel as a
#   JSON array parameter unpacked in SQL). View as Background reads
#   the series back through Series/SelectByBatch, so every batch
#   carries its own curve like an Artisan roast file.

import roastery.core as core

NQ_SELECT_ALL = 'Roastery/Batches/SelectAll'
NQ_SELECT_BY_ID = 'Roastery/Batches/SelectById'
NQ_INSERT = 'Roastery/Batches/Insert'
NQ_UPDATE = 'Roastery/Batches/Update'
NQ_DELETE = 'Roastery/Batches/Delete'
NQ_SERIES_INSERT = 'Roastery/Series/InsertBatch'
NQ_SERIES_SELECT = 'Roastery/Series/SelectByBatch'
NQ_EVENTS_SELECT = 'Roastery/Events/SelectByBatch'
NQ_MAX_NUMBER = 'Roastery/Batches/SelectMaxNumber'

SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
EDITOR_CREATE_TAG = '[default]Roastery/EditorCreateMode'
DETAIL_DS = '[default]Roastery/DetailDS'
DETAIL_MARKS = '[default]Roastery/DetailMarksDS'
DETAIL_JSON = '[default]Roastery/DetailDocJson'
DETAIL_REFRESH_MESSAGE = 'roastery-detail-refresh'

BACKGROUND_LABEL = '[default]Roastery/BackgroundLabel'
ROASTLOG_TAG = '[default]Roastery/RoastLog'
REFRESH_MESSAGE = 'roastery-batches-refresh'


def _run(path, params=None):
    return system.db.runNamedQuery(path, params or {})


def _iso(dt):
    if dt is None:
        return None
    return system.date.format(dt, "yyyy-MM-dd'T'HH:mm:ss")


def _doc_of(cell):
    """SelectById returns the JSONB document as JSON text."""
    if cell is None:
        return {}
    if isinstance(cell, basestring):
        return system.util.jsonDecode(cell)
    return system.util.jsonDecode(str(cell))


# ---------------------------------------------------------------- document

def roast_degree(drop_temp_f):
    t = drop_temp_f or 0.0
    if t < 390:
        return 'Cinnamon'
    if t < 396:
        return 'New England'
    if t < 401:
        return 'American'
    if t < 406:
        return 'City'
    if t < 411:
        return 'City+'
    if t < 416:
        return 'Full City'
    if t < 421:
        return 'Full City+'
    if t < 426:
        return 'Vienna'
    if t < 436:
        return 'French'
    return 'Italian'


def curve_auc(points, charge_temp_f):
    """Trapezoid area between the bean curve and the charge temp, in
    degree F minutes (same definition as the v2 roast log save)."""
    auc = 0.0
    base = charge_temp_f or 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        dt_min = (b['t'] - a['t']) / 60.0
        if dt_min <= 0:
            continue
        avg = (a['bt'] + b['bt']) / 2.0
        if avg > base:
            auc += (avg - base) * dt_min
    return auc


def _event_doc(vals, stem):
    elapsed = vals[stem + 'ElapsedSec']
    if elapsed is None or elapsed < 0:
        return None
    return {'t': elapsed, 'ts': _iso(vals[stem + 'Time']),
            'tempF': vals[stem + 'TempF']}


def _trace_summary():
    ds = system.tag.readBlocking([core.EVENTS_LOG])[0].value
    out = []
    if ds is None:
        return out
    for r in range(ds.rowCount):
        if ds.getValueAt(r, 'kind') == 'stepper':
            out.append({'t': float(ds.getValueAt(r, 'elapsedSec')),
                        'label': ds.getValueAt(r, 'label'),
                        'fan': float(ds.getValueAt(r, 'fan')),
                        'heat': float(ds.getValueAt(r, 'heat'))})
    return out


def build_document():
    """Assemble the JSONB batch document from the CurrentBatch tags."""
    members = ['BatchNumber', 'BeanName', 'ChargeTime', 'DropTime',
               'ChargeTempF', 'DropTempF', 'DropElapsedSec',
               'ActiveSource']
    members += list(core.FORM_MEMBERS)
    for stem in ('DryEnd', 'FirstCrackStart', 'FirstCrackEnd',
                 'SecondCrackStart', 'SecondCrackEnd', 'Drop'):
        members += [stem + 'Time', stem + 'TempF', stem + 'ElapsedSec']
    for i in (1, 2, 3, 4):
        members += ['CustomEvent%dName' % i, 'CustomEvent%dKind' % i,
                    'CustomEvent%dTime' % i, 'CustomEvent%dTempF' % i,
                    'CustomEvent%dElapsedSec' % i]
    members += ['TargetChargeTempF', 'TargetDryEndSec',
                'TargetDryEndTempF', 'TargetFCSec', 'TargetFCTempF',
                'TargetDropSec', 'TargetDropTempF']
    vals = core.read_members(members)
    total = vals['DropElapsedSec'] or 0
    dry = vals['DryEndElapsedSec']
    dry = dry if dry is not None and dry >= 0 else 0
    fc = vals['FirstCrackStartElapsedSec']
    fc = fc if fc is not None and fc >= 0 else total
    charge_w = vals['ChargeWeightG'] or 0.0
    out_w = vals['WeightOutG'] or 0.0
    loss = ((charge_w - out_w) * 100.0 / charge_w) if out_w > 0 and charge_w > 0 else 0.0
    return {
        'batchNumber': vals['BatchNumber'],
        'beanName': vals['BeanName'],
        'roastStart': _iso(vals['ChargeTime']),
        'roastEnd': _iso(vals['DropTime']),
        'dropTempF': vals['DropTempF'],
        'roastDegree': roast_degree(vals['DropTempF']),
        'totalSec': total,
        'phases': {'dryingSec': dry, 'maillardSec': fc - dry,
                   'developmentSec': total - fc,
                   'dtrPct': ((total - fc) * 100.0 / total) if total > 0 else 0.0},
        'auc': curve_auc(core.curve_points(), vals['ChargeTempF']),
        'weightLossPct': loss,
        'source': vals['ActiveSource'],
        'metadata': dict((m, vals[m]) for m in core.FORM_MEMBERS),
        'events': {
            'charge': {'t': 0, 'ts': _iso(vals['ChargeTime']),
                       'tempF': vals['ChargeTempF']},
            'dryEnd': _event_doc(vals, 'DryEnd'),
            'fcStart': _event_doc(vals, 'FirstCrackStart'),
            'fcEnd': _event_doc(vals, 'FirstCrackEnd'),
            'scStart': _event_doc(vals, 'SecondCrackStart'),
            'scEnd': _event_doc(vals, 'SecondCrackEnd'),
            'drop': _event_doc(vals, 'Drop'),
            'custom': [
                {'name': vals['CustomEvent%dName' % i],
                 'kind': vals['CustomEvent%dKind' % i],
                 't': vals['CustomEvent%dElapsedSec' % i],
                 'tempF': vals['CustomEvent%dTempF' % i]}
                for i in (1, 2, 3, 4)
                if vals['CustomEvent%dElapsedSec' % i] is not None
                and vals['CustomEvent%dElapsedSec' % i] >= 0]},
        'target': {'chargeTempF': vals['TargetChargeTempF'],
                   'dryEndSec': vals['TargetDryEndSec'],
                   'dryEndTempF': vals['TargetDryEndTempF'],
                   'fcSec': vals['TargetFCSec'],
                   'fcTempF': vals['TargetFCTempF'],
                   'dropSec': vals['TargetDropSec'],
                   'dropTempF': vals['TargetDropTempF']},
        'fanHeatTrace': _trace_summary()}


# ---------------------------------------------------------------- CRUD

def get_batch(batch_number):
    ds = _run(NQ_SELECT_BY_ID, {'batch_number': int(batch_number)})
    if ds.rowCount == 0:
        return None
    return {'id': ds.getValueAt(0, 'id'),
            'batchNumber': ds.getValueAt(0, 'batch_number'),
            'roastStart': ds.getValueAt(0, 'roast_start'),
            'roastEnd': ds.getValueAt(0, 'roast_end'),
            'beanName': ds.getValueAt(0, 'bean_name'),
            'dropTempF': ds.getValueAt(0, 'drop_temp_f'),
            'document': _doc_of(ds.getValueAt(0, 'data'))}


def delete_batch(batch_number):
    """Delete named query; batch_series rows cascade in Postgres."""
    return _run(NQ_DELETE, {'batch_number': int(batch_number)})


def _insert_series(batch_number, points):
    """Write the curve points to batch_series. The stored
    rate_of_rise_f is DERIVED: recomputed here from the stored
    temps by roastery.core.compute_ror_series (offline path), so
    the saved RoR always matches the one implementation. In
    SeriesCaptureMode 'Group' the transaction group already wrote
    the rows live and this is skipped."""
    mode = core.read_members(['SeriesCaptureMode'])['SeriesCaptureMode']
    if mode == 'Group':
        ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
        return ds.rowCount
    if not points:
        return 0
    temps = [(p['t'], p['bt']) for p in points]
    rors = core.compute_ror_series(temps, core.ror_params(),
                                   offline=True)
    ror_by_t = dict((t, r) for t, r in rors)
    payload = []
    for p in points:
        r = ror_by_t.get(p['t'])
        item = {'t': p['t'], 'bt': p['bt'],
                'ror': r if r is not None else p['ror']}
        if p.get('ts') is not None:
            item['ts'] = system.date.format(p['ts'], "yyyy-MM-dd'T'HH:mm:ss.SSSZ")
        if p.get('fan') is not None:
            item['fan'] = p['fan']
        if p.get('heat') is not None:
            item['heat'] = p['heat']
        payload.append(item)
    return _run(NQ_SERIES_INSERT, {
        'batch_number': int(batch_number),
        'points': system.util.jsonEncode(payload)})



def save_current_batch(self):
    """Summary view Save button: persist the finished roast through
    the Insert named query, then its recorded curve through
    Series/InsertBatch."""
    vals = core.read_members(['BatchNumber', 'BeanName', 'ChargeTime',
                              'DropTime', 'DropTempF'])
    if get_batch(vals['BatchNumber']) is not None:
        self.view.custom.saveNote = (
            'Batch %d is already in the log. Start a New Roast for '
            'a fresh batch number, or edit the saved batch from '
            'the Log tab.' % vals['BatchNumber'])
        return vals['BatchNumber']
    doc = build_document()
    _run(NQ_INSERT, {
        'batch_number': vals['BatchNumber'],
        'roast_start': vals['ChargeTime'],
        'roast_end': vals['DropTime'],
        'bean_name': vals['BeanName'],
        'drop_temp_f': vals['DropTempF'],
        'data': system.util.jsonEncode(doc)})
    _insert_series(vals['BatchNumber'], core.curve_points())
    core.record_press('Save Batch')
    self.view.custom.saveNote = 'Saved batch %d to the database.' % vals['BatchNumber']
    return vals['BatchNumber']



# ---------------------------------------------------------------- edit form

def _apply_form(doc, payload):
    meta = dict(doc.get('metadata') or {})
    for k in core.FORM_MEMBERS:
        if k not in payload:
            continue
        v = payload[k]
        if v is None:
            continue
        try:
            meta[k] = core.coerce(k, v)
        except Exception:
            continue
    doc['metadata'] = meta
    if meta.get('BeanName'):
        doc['beanName'] = meta['BeanName']
    return doc


EVENT_FORM_KEYS = ('charge', 'dryEnd', 'fcStart', 'fcEnd',
                   'scStart', 'scEnd', 'drop')


def _mmss(t):
    if t is None:
        return ''
    t = int(t)
    return '%02d:%02d' % (t // 60, t % 60)


def edit_form_data_for(self):
    """Slide over editor prefill (called from the editor view
    onStartup). Mode and target come from the EditorCreateMode and
    SelectedBatchNumber tags. In create mode the form starts blank
    except the bean defaults; in edit mode it comes from the stored
    batch document (SelectById), metadata plus event times (mm:ss
    from charge) and event temps."""
    create = system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value
    if create:
        return {'BeanName': '', 'Origin': '', 'Region': '', 'Farm': '',
                'Altitude': '', 'Variety': '', 'Process': '',
                'HarvestYear': 2025, 'MoisturePct': 0.0,
                'DensityGL': 0.0, 'ChargeWeightG': 200.0,
                'TargetDropTempF': 415.0, 'RoastLevel': '',
                'OperatorName': '', 'Notes': '', 'WeightOutG': 0.0,
                'BatchNumber': 0}
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    batch = get_batch(number)
    if batch is None:
        return {}
    doc = batch['document']
    meta = dict(doc.get('metadata') or {})
    data = {}
    for m in core.FORM_MEMBERS:
        v = meta.get(m)
        if v is None:
            v = 0 if m in core.FORM_INTS else (0.0 if m in core.FORM_FLOATS else '')
        data[m] = v
    data['BatchNumber'] = batch['batchNumber']
    events = doc.get('events') or {}
    for key in EVENT_FORM_KEYS:
        e = events.get(key)
        data['Ev_%s_t' % key] = _mmss(e.get('t')) if e else ''
        tv = e.get('tempF') if e else None
        data['Ev_%s_tempF' % key] = tv if tv is not None else ''
    return data



def batch_edit_submit(self, event):
    """Slide over editor form submit for both modes."""
    create = system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value
    if create:
        _create_submit(self, event)
    else:
        _update_submit(self, event)



def _update_submit(self, event):
    batch_number = int(system.tag.readBlocking(
        [SELECTED_TAG])[0].value or 0)
    batch = get_batch(batch_number)
    if batch is None:
        self.view.custom.editNote = 'Batch %d no longer exists.' % batch_number
        return
    doc = _apply_form(batch['document'], event)
    err = _apply_events(doc, event)
    if err:
        # Reject nonsense with a visible message; nothing is saved.
        self.view.custom.editNote = err
        return
    _run(NQ_UPDATE, {
        'batch_number': batch_number,
        'bean_name': doc.get('beanName'),
        'drop_temp_f': doc.get('dropTempF'),
        'data': system.util.jsonEncode(doc)})
    self.view.custom.editNote = 'Saved batch %d.' % batch_number
    stage_detail(batch_number)
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')
    system.perspective.sendMessage(DETAIL_REFRESH_MESSAGE, {},
                                   scope='session')



def _create_submit(self, event):
    try:
        number = int(float(event['BatchNumber']))
    except Exception:
        number = 0
    if not number:
        self.view.custom.editNote = 'Enter a batch number to create.'
        return
    if get_batch(number) is not None:
        self.view.custom.editNote = 'Batch %d already exists.' % number
        return
    doc = {'batchNumber': number, 'beanName': '', 'roastDegree': '',
           'totalSec': 0, 'phases': {}, 'events': {}, 'metadata': {},
           'manualEntry': True}
    doc = _apply_form(doc, event)
    now = system.date.now()
    _run(NQ_INSERT, {
        'batch_number': number, 'roast_start': now, 'roast_end': now,
        'bean_name': doc.get('beanName') or '', 'drop_temp_f': 0.0,
        'data': system.util.jsonEncode(doc)})
    self.view.custom.editNote = 'Created batch %d.' % number
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')


# ---------------------------------------------------------------- Batches page

def select_row(self, event):
    """Batches table row click: remember the selection in view
    custom props (the action buttons act on it) and in the
    SelectedBatchNumber tag (detail view, slide over editor and
    ghost actions read it from any page)."""
    row = event.value
    try:
        number = row['batch_number']
        bean = row['bean_name']
    except Exception:
        number = row.get('batch_number')
        bean = row.get('bean_name')
    self.view.custom.selBatchNumber = int(number) if number is not None else 0
    self.view.custom.selLabel = 'Batch %s - %s' % (number, bean)
    self.view.custom.selNote = ('Selected batch %s (%s). Edit it, delete it, '
                                'or view it as a background.' % (number, bean))
    self.view.custom.confirmDelete = False
    if number is not None:
        system.tag.writeBlocking([SELECTED_TAG], [int(number)])



def refresh_table(self):
    """Re-run the table's SelectAll binding. Called by the panel's
    refresh message handler (self is the panel root) and by panel
    actions such as confirm_delete (self is a component in the
    panel); resolve the table either way. Note: self.view.root is
    not a valid path in this scripting model."""
    table = self.getChild('BatchTable')
    if table is None:
        # getChild returns None (does not raise) when the child is
        # not under this component; resolve from the view root.
        table = self.view.getChild('root').getChild('BatchTable')
    table.refreshBinding('props.data')


def open_editor(self, create=False):
    """Open the slide over batch editor (right dock 'batchEditor',
    configured on the Log pages). The editor view reads its target
    from the SelectedBatchNumber and EditorCreateMode tags, so any
    page can open it for the staged batch."""
    if create:
        system.tag.writeBlocking([EDITOR_CREATE_TAG], [True])
    else:
        number = int(system.tag.readBlocking(
            [SELECTED_TAG])[0].value or 0)
        if number <= 0:
            return
        system.tag.writeBlocking([EDITOR_CREATE_TAG], [False])
    system.perspective.openDock('batchEditor')
    system.perspective.sendMessage('roastery-editor-open', {},
                                   scope='session')


def editor_refresh(self):
    """Refill the slide over editor for the staged batch. Runs
    from the editor view onStartup and from its
    'roastery-editor-open' message handler: a docked view loads
    once per page, so onStartup alone goes stale after the first
    open. The title is set here in the library because an
    expression binding cannot concatenate the batch number onto
    text in this build (it evaluated to null with bad quality)."""
    create = bool(system.tag.readBlocking([EDITOR_CREATE_TAG])[0].value)
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    self.view.custom.editorTitle = ('New Batch' if create else
                                    'Edit Batch %d' % number)
    self.view.custom.editNote = ''
    root = self.getChild('root')
    if root is None:
        root = self.view.getChild('root')
    root.getChild('BatchForm').props.data = edit_form_data_for(self)



def arm_delete(self):
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    self.view.custom.confirmDelete = True
    self.view.custom.selNote = ('Delete batch %d and its curve? '
                                'Press Confirm Delete to proceed.' % number)


def cancel_delete(self):
    self.view.custom.confirmDelete = False
    self.view.custom.selNote = 'Delete cancelled.'


def confirm_delete(self):
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    delete_batch(number)
    self.view.custom.confirmDelete = False
    self.view.custom.selBatchNumber = 0
    self.view.custom.selLabel = ''
    self.view.custom.selNote = 'Deleted batch %d.' % number
    # Refresh through the panel's message handler (self is the
    # panel root there), the same path the edit popup saves use.
    system.perspective.sendMessage(REFRESH_MESSAGE, {}, scope='session')


def set_background(self):
    """Use as Ghost: read the selected batch's curve from the
    batch_series table (Series/SelectByBatch) and stage it as the
    Roast page background overlay, then navigate to the console.
    roastery.core.build_overlays recomputes the ghost RoR from the
    staged temps with the current RoR parameters."""
    batch_number = int(self.view.custom.selBatchNumber or 0)         if hasattr(self.view.custom, 'selBatchNumber') else 0
    if batch_number <= 0:
        batch_number = int(system.tag.readBlocking(
            [SELECTED_TAG])[0].value or 0)
    if batch_number <= 0:
        return
    ds = _run(NQ_SERIES_SELECT, {'batch_number': batch_number})
    pairs = []
    for r in range(ds.rowCount):
        pairs.append([ds.getValueAt(r, 't_offset_sec'),
                      ds.getValueAt(r, 'bean_temp_f')])
    batch = get_batch(batch_number)
    label = 'Batch %d' % batch_number
    if batch is not None and batch['beanName']:
        label += ' - ' + batch['beanName']
    system.tag.writeBlocking(
        [core.BACKGROUND_JSON, BACKGROUND_LABEL],
        [system.util.jsonEncode(pairs), label])
    core.build_overlays()
    system.perspective.navigate(page='/')



# ---------------------------------------------------------------- event editing

def parse_mmss(text):
    """'mm:ss' (or plain seconds) -> int seconds; None when blank.
    Raises ValueError on garbage."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if ':' in s:
        parts = s.split(':')
        if len(parts) != 2:
            raise ValueError('bad time')
        return int(parts[0]) * 60 + int(float(parts[1]))
    return int(float(s))


def _apply_events(doc, payload):
    """Apply the slide over event edits to the document and
    RECOMPUTE the derived data so the document stays self
    consistent: phase durations and DTR from the event times,
    total time from drop, roast degree from the (possibly edited)
    drop temp, event timestamps from roast start + offset.
    Returns an error string, or None on success. On error the
    caller saves nothing."""
    events = dict(doc.get('events') or {})
    order = ['charge', 'dryEnd', 'fcStart', 'fcEnd', 'scStart',
             'scEnd', 'drop']
    labels = {'charge': 'Charge', 'dryEnd': 'Dry End',
              'fcStart': 'FC Start', 'fcEnd': 'FC End',
              'scStart': 'SC Start', 'scEnd': 'SC End', 'drop': 'Drop'}
    new_events = {}
    for key in order:
        tkey = 'Ev_%s_t' % key
        fkey = 'Ev_%s_tempF' % key
        if tkey not in payload and fkey not in payload:
            new_events[key] = events.get(key)
            continue
        old = events.get(key) or {}
        try:
            t = parse_mmss(payload.get(tkey)) if tkey in payload                 else old.get('t')
        except Exception:
            return ('Event times must be mm:ss (for example 04:30). '
                    'Nothing was saved.')
        temp = old.get('tempF')
        if fkey in payload and payload.get(fkey) not in (None, ''):
            try:
                temp = float(payload[fkey])
            except Exception:
                return ('Event temps must be numbers. '
                        'Nothing was saved.')
        if key == 'charge':
            t = 0
        if t is None:
            new_events[key] = None
        else:
            new_events[key] = {'t': int(t), 'ts': old.get('ts'),
                               'tempF': temp}
    new_events['custom'] = events.get('custom') or []
    seq = [(k, new_events[k]['t']) for k in order if new_events.get(k)]
    for i in range(len(seq) - 1):
        if seq[i][1] >= seq[i + 1][1]:
            return ('%s must come before %s. Nothing was saved.'
                    % (labels[seq[i][0]], labels[seq[i + 1][0]]))
    doc['events'] = new_events

    def _t(key):
        e = new_events.get(key)
        return e['t'] if e else None

    dry = _t('dryEnd')
    fc = _t('fcStart')
    drop_t = _t('drop')
    if drop_t is not None:
        doc['totalSec'] = drop_t
        dev = (drop_t - fc) if fc is not None else 0
        doc['phases'] = {
            'dryingSec': dry if dry is not None else 0,
            'maillardSec': (fc - dry) if (fc is not None
                                          and dry is not None) else 0,
            'developmentSec': dev,
            'dtrPct': (dev * 100.0 / drop_t) if drop_t > 0 else 0.0}
        drop_ev = new_events.get('drop') or {}
        if drop_ev.get('tempF') is not None:
            doc['dropTempF'] = drop_ev['tempF']
            doc['roastDegree'] = roast_degree(drop_ev['tempF'])
    start_iso = doc.get('roastStart')
    if start_iso:
        try:
            start_dt = system.date.parse(
                start_iso, "yyyy-MM-dd'T'HH:mm:ss")
            for key in order:
                e = new_events.get(key)
                if e:
                    e['ts'] = _iso(system.date.addSeconds(
                        start_dt, int(e['t'])))
            if drop_t is not None:
                doc['roastEnd'] = _iso(system.date.addSeconds(
                    start_dt, int(drop_t)))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- detail + new roast

def stage_detail(batch_number):
    """Stage everything the Log detail view binds for one batch:
    DetailDS (bean temp + RoR recomputed from the stored temps
    with the CURRENT RoR parameters, the way Artisan recalculates
    a loaded profile), DetailMarksDS (event marker lines) and
    DetailDocJson. Returns True when the batch exists."""
    from java.util import Date
    batch = get_batch(int(batch_number))
    if batch is None:
        return False
    doc = batch['document']
    system.tag.writeBlocking(
        [SELECTED_TAG, DETAIL_JSON],
        [int(batch_number), system.util.jsonEncode(doc)])
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    points = []
    for r in range(ds.rowCount):
        bt = ds.getValueAt(r, 'bean_temp_f')
        if bt is not None:
            points.append((float(ds.getValueAt(r, 't_offset_sec')),
                           float(bt)))
    rors = core.compute_ror_series(points, core.ror_params(),
                                   offline=True)
    # X values are elapsed dates (epoch + t_offset seconds), the
    # v4.1 axis: the detail chart reads exactly like the live
    # chart, and no longer depends on the batch having a stored
    # roast_start wall clock (the generated fixture batches have
    # none, and their detail curves used to stage empty).
    rows = []
    for (t, bt), (_t2, ror) in zip(points, rors):
        rows.append([Date(long(t * 1000)), bt, ror])
    evs = []
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'CHARGE'), ('dryEnd', 'DRY END'),
                     ('fcStart', 'FC START'), ('fcEnd', 'FC END'),
                     ('scStart', 'SC START'), ('scEnd', 'SC END'),
                     ('drop', 'DROP')):
        e = events.get(key)
        if e and e.get('t') is not None:
            evs.append((float(e['t']), lbl))
    for c in events.get('custom') or []:
        if c.get('t') is not None:
            evs.append((float(c['t']),
                        (c.get('name') or 'CUSTOM').upper()))
    system.tag.writeBlocking(
        [DETAIL_DS, DETAIL_MARKS],
        [system.dataset.toDataSet(['t_stamp', 'bt', 'ror'], rows),
         core.marks_dataset(evs)])
    return True


def detail_reference_lines():
    """Reference line items for the staged batch's events, from
    the DetailDocJson document stage_detail wrote (custom event
    names intact). Bound on the detail chart's bean series
    through a script transform triggered by DetailMarksDS."""
    raw = system.tag.readBlocking([DETAIL_JSON])[0].value
    if not raw:
        return []
    doc = system.util.jsonDecode(raw)
    events = doc.get('events') or {}
    evs = []
    for key, lbl in (('charge', 'CHARGE'), ('dryEnd', 'DRY END'),
                     ('fcStart', 'FC START'), ('fcEnd', 'FC END'),
                     ('scStart', 'SC START'), ('scEnd', 'SC END'),
                     ('drop', 'DROP')):
        e = events.get(key)
        if e and e.get('t') is not None:
            evs.append((float(e['t']), lbl))
    for c in events.get('custom') or []:
        if c.get('t') is not None:
            evs.append((float(c['t']),
                        (c.get('name') or 'CUSTOM').upper()))
    return core._ref_items(evs)


def open_detail(self):
    """Batches panel Details button: stage the selected batch and
    navigate to the detail page."""
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    if stage_detail(number):
        system.perspective.navigate(page='/log/detail')
        # The detail view re-runs detail_startup on this message,
        # which also gives the presses query a second, warm chance
        # on a cold connection.
        system.perspective.sendMessage(DETAIL_REFRESH_MESSAGE, {},
                                       scope='session')


def detail_startup(self):
    """BatchDetail view onStartup: fill the view custom props from
    the staged document (DetailDocJson) and the captured presses
    (Events/SelectByBatch, named query)."""
    raw = system.tag.readBlocking([DETAIL_JSON])[0].value
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    self.view.custom.batchNumber = number
    if not raw:
        self.view.custom.titleText = 'No batch staged'
        return
    doc = system.util.jsonDecode(raw)
    meta = doc.get('metadata') or {}
    phases = doc.get('phases') or {}
    self.view.custom.titleText = 'Batch %s - %s' % (
        doc.get('batchNumber'), doc.get('beanName') or '')
    self.view.custom.subText = '%s - %s' % (
        (doc.get('roastStart') or '')[:16].replace('T', ' '),
        doc.get('roastDegree') or '')
    self.view.custom.dTotal = _mmss(doc.get('totalSec'))
    self.view.custom.dDtr = ('%.1f%%' % phases['dtrPct']
                             if phases.get('dtrPct') is not None
                             else '--')
    dt = doc.get('dropTempF')
    self.view.custom.dDropTemp = ('%.0f F' % dt) if dt else '--'
    loss = doc.get('weightLossPct')
    self.view.custom.dLoss = ('%.1f%%' % loss) if loss else '--'
    auc = doc.get('auc')
    self.view.custom.dAuc = ('%.0f' % auc) if auc else '--'
    self.view.custom.dSource = doc.get('source') or '--'
    self.view.custom.dPhases = (
        'Drying %s - Maillard %s - Development %s' % (
            _mmss(phases.get('dryingSec')),
            _mmss(phases.get('maillardSec')),
            _mmss(phases.get('developmentSec'))))
    ev_rows = []
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'Charge'), ('dryEnd', 'Dry End'),
                     ('fcStart', 'FC Start'), ('fcEnd', 'FC End'),
                     ('scStart', 'SC Start'), ('scEnd', 'SC End'),
                     ('drop', 'Drop')):
        e = events.get(key)
        if e:
            ev_rows.append([lbl, _mmss(e.get('t')),
                            ('%.0f F' % e['tempF'])
                            if e.get('tempF') is not None else '--'])
    for c in events.get('custom') or []:
        ev_rows.append([c.get('name') or 'Custom', _mmss(c.get('t')),
                        ('%.0f F' % c['tempF'])
                        if c.get('tempF') is not None else '--'])
    self.view.custom.eventsDs = system.dataset.toDataSet(
        ['event', 'time', 'temp'], ev_rows)
    meta_rows = []
    for m in core.FORM_MEMBERS:
        if meta.get(m) not in (None, ''):
            meta_rows.append([m, str(meta[m])])
    self.view.custom.metaDs = system.dataset.toDataSet(
        ['field', 'value'], meta_rows)
    press_rows = []
    try:
        pds = _run(NQ_EVENTS_SELECT, {'batch_number': number})
        for r in range(pds.rowCount):
            press_rows.append([
                pds.getValueAt(r, 'action'),
                _mmss(pds.getValueAt(r, 't_offset_sec')),
                pds.getValueAt(r, 'bean_temp_f'),
                pds.getValueAt(r, 'fan_level'),
                pds.getValueAt(r, 'heat_level')])
    except Exception:
        press_rows = []
    self.view.custom.pressDs = system.dataset.toDataSet(
        ['action', 'time', 'tempF', 'fan', 'heat'], press_rows)
    self.view.custom.hasPresses = len(press_rows) > 0


def new_roast(self):
    """NEW ROAST action: zero the workspace, take the next batch
    number (max of the database and the current tag, plus one),
    and land on the Roast page."""
    try:
        ds = _run(NQ_MAX_NUMBER)
        max_db = int(ds.getValueAt(0, 'max_number') or 0)
    except Exception:
        max_db = 0
    cur = core.read_members(['BatchNumber'])['BatchNumber'] or 0
    nxt = max(max_db, int(cur)) + 1
    core.reset_batch()
    core.write_members([('BatchNumber', nxt)])
    system.perspective.navigate(page='/')



# ---------------------------------------------------------------- seed

def seed_from_roastlog():
    """One time migration: copy the legacy RoastLog dataset tag rows
    into the batches and batch_series tables. All seven legacy rows
    carry batch number 1042 (v2 test saves), so duplicates are
    renumbered in chronological order and each document records
    seededFromRoastLog and originalBatchNumber. Curve points come
    from the stored curveJson ([seconds, temp] pairs); rate of rise
    is derived by finite difference; fan and heat were not recorded
    in v2 and stay null. Returns the number of batches inserted."""
    from java.util import Date
    ds = system.tag.readBlocking([ROASTLOG_TAG])[0].value
    if ds is None or ds.rowCount == 0:
        return 0
    existing = set()
    all_ds = _run(NQ_SELECT_ALL)
    for r in range(all_ds.rowCount):
        existing.add(all_ds.getValueAt(r, 'batch_number'))
    rows = []
    for r in range(ds.rowCount):
        rows.append(dict((c, ds.getValueAt(r, c)) for c in ds.columnNames))
    rows.sort(key=lambda d: d['roastDate'])
    inserted = 0
    next_number = 1042
    for row in rows:
        while next_number in existing:
            next_number += 1
        number = next_number
        existing.add(number)
        total = row['totalSec'] or 0.0
        end = row['roastDate']
        start = Date(long(end.getTime() - total * 1000)) if end is not None else None
        charge_g = row['chargeG'] or 0.0
        loss = row['weightLossPct'] or 0.0
        doc = {
            'batchNumber': number,
            'beanName': row['bean'],
            'roastStart': _iso(start),
            'roastEnd': _iso(end),
            'dropTempF': row['dropTempF'],
            'roastDegree': row['level'],
            'totalSec': total,
            'phases': {'dryingSec': row['drySec'],
                       'maillardSec': row['maillardSec'],
                       'developmentSec': row['devSec'],
                       'dtrPct': row['dtrPct']},
            'auc': row['auc'],
            'weightLossPct': loss,
            'seededFromRoastLog': True,
            'originalBatchNumber': row['batch'],
            'metadata': {'BeanName': row['bean'], 'Origin': row['origin'],
                         'ChargeWeightG': charge_g,
                         'WeightOutG': charge_g * (1.0 - loss / 100.0)},
            'events': {'charge': {'t': 0, 'ts': _iso(start),
                                  'tempF': None},
                       'drop': {'t': total, 'ts': _iso(end),
                                'tempF': row['dropTempF']}}}
        _run(NQ_INSERT, {
            'batch_number': number, 'roast_start': start,
            'roast_end': end, 'bean_name': row['bean'],
            'drop_temp_f': row['dropTempF'],
            'data': system.util.jsonEncode(doc)})
        pairs = system.util.jsonDecode(row['curveJson'] or '[]')
        by_sec = {}
        for sec, temp in pairs:
            by_sec[int(round(sec))] = temp
        secs = sorted(by_sec.keys())
        points = []
        for i, sec in enumerate(secs):
            if 0 < i < len(secs) - 1:
                ror = (by_sec[secs[i + 1]] - by_sec[secs[i - 1]]) * 60.0 / (secs[i + 1] - secs[i - 1])
            elif len(secs) > 1 and i == 0:
                ror = (by_sec[secs[1]] - by_sec[secs[0]]) * 60.0 / max(secs[1] - secs[0], 1)
            elif len(secs) > 1:
                ror = (by_sec[secs[-1]] - by_sec[secs[-2]]) * 60.0 / max(secs[-1] - secs[-2], 1)
            else:
                ror = 0.0
            ts = Date(long(start.getTime() + sec * 1000)) if start is not None else None
            points.append({'t': sec, 'ts': ts, 'bt': by_sec[sec],
                           'ror': ror})
        _insert_series(number, points)
        inserted += 1
    return inserted
