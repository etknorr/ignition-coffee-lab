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
# - batch_events: one row per control press keyed by batch_number,
#   written live during a roast by the PressEvents transaction
#   group (and the library reconcile) through Events/InsertPress.
#   It deliberately has NO foreign key to batches: presses are
#   captured for the working batch number before any batches row
#   exists (the row lands only at Save Batch), so an FK would
#   break live press capture. Deleting a batch therefore removes
#   its press rows explicitly in delete_batch (HUNT-35, polish
#   round 4): the saved batch document already snapshots the
#   press events at save time, and no surface reads batch_events
#   rows for a batch that no longer exists, so rows left behind
#   would be pure orphans.

import math

import roastery.core as core

NQ_SELECT_ALL = 'Roastery/Batches/SelectAll'
NQ_SELECT_BY_ID = 'Roastery/Batches/SelectById'
NQ_INSERT = 'Roastery/Batches/Insert'
NQ_UPDATE = 'Roastery/Batches/Update'
NQ_DELETE = 'Roastery/Batches/Delete'
NQ_SERIES_INSERT = 'Roastery/Series/InsertBatch'
NQ_SERIES_SELECT = 'Roastery/Series/SelectByBatch'
NQ_EVENTS_SELECT = 'Roastery/Events/SelectByBatch'
NQ_EVENTS_DELETE = 'Roastery/Events/DeleteByBatch'
NQ_MAX_NUMBER = 'Roastery/Batches/SelectMaxNumber'

SELECTED_TAG = '[default]Roastery/SelectedBatchNumber'
EDITOR_CREATE_TAG = '[default]Roastery/EditorCreateMode'
DETAIL_DS = '[default]Roastery/DetailDS'
DETAIL_MARKS = '[default]Roastery/DetailMarksDS'
DETAIL_JSON = '[default]Roastery/DetailDocJson'
DETAIL_REFRESH_MESSAGE = 'roastery-detail-refresh'
# Detail chart minimum x span in seconds (polish round 2
# item 6): the canvas time axis picks its tick label format
# from the axis span, and a very short batch (the seeded
# batch 1042 spans about 20 s) landed in the hour:minute:
# second regime while the live chart reads minute:second.
# detail_startup floors the chart max at this span so short
# batches render in the same regime as the live chart;
# longer batches keep their natural end. Sized empirically
# against the rendered ticks on batch 1042.
DETAIL_MIN_SPAN_SEC = 600
# Short batch span floor in seconds (polish round 5,
# HUNT-37): a batch shorter than DETAIL_MIN_SPAN_SEC no
# longer pads all the way to 600, which left a 43 s batch
# plotted in the first tenth of the axis. _detail_span
# floors the staged grid at the larger of this floor and
# the batch extent, and _detail_top_gap scales the event
# label gap down by the same proportion, so short batches
# fill the chart and their later events can carry labels.
# Batches at or over DETAIL_MIN_SPAN_SEC stage exactly as
# before: natural extent, 55 s label gap.
DETAIL_SHORT_FLOOR_SEC = 180
# Event label gap in seconds on a full span detail chart
# (the round 3 settlement detail_reference_lines used as a
# bare 55.0 before HUNT-37).
DETAIL_REF_GAP_SEC = 55.0
# Minimum separation between DRAWN reference lines, as a
# fraction of the staged span (polish round 6, item 3):
# the label gap drops labels for close events but keeps
# every dashed line, so on a short batch the six events in
# the first 10 s of fixture 9919 drew as a solid band at
# the left edge, lines 1.4 px apart on the roughly 250 px
# phone plot. 0.03 of span is about 7.5 px on that plot
# and about 30 px on desktop, enough for 1.5 px dashed
# lines to read as separate lines. It is deliberately far
# smaller than the label gap: thinning lines by the label
# gap would drop real lines on a normal batch (fixture
# 9920's FC END and SC END sit 30 s from their neighbors,
# under the 55 s label gap), while 0.03 keeps them (21.6 s
# at the 720 s span) and keeps the real batches' 9 s
# CHARGE to DROP gaps (5.4 s at the 180 s floor). The
# events strip under the chart still names every event,
# so a dropped line loses no information.
DETAIL_LINE_GAP_FRAC = 0.03

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
    members += ['TurningPointElapsedSec', 'TurningPointTempF',
                'AucLiveFMin', 'AucSinceFcFMin', 'AucBaseTempF',
                'AucBegin', 'AucTargetFMin']
    vals = core.read_members(members)
    total = vals['DropElapsedSec'] or 0
    dry = vals['DryEndElapsedSec']
    dry = dry if dry is not None and dry >= 0 else 0
    fc = vals['FirstCrackStartElapsedSec']
    fc = fc if fc is not None and fc >= 0 else total
    charge_w = vals['ChargeWeightG'] or 0.0
    out_w = vals['WeightOutG'] or 0.0
    lossd = loss_yield_density(vals)
    loss = lossd.get('weightLossPct')
    if loss is None:
        loss = ((charge_w - out_w) * 100.0 / charge_w) if out_w > 0 and charge_w > 0 else 0.0
    doc = {
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
        'aucDetail': {'valueFMin': vals['AucLiveFMin'],
                      'sinceFcFMin': vals['AucSinceFcFMin'],
                      'baseF': vals['AucBaseTempF'],
                      'begin': vals['AucBegin'],
                      'targetFMin': vals['AucTargetFMin']},
        'turningPoint': (
            {'t': vals['TurningPointElapsedSec'],
             'tempF': vals['TurningPointTempF']}
            if vals['TurningPointElapsedSec'] is not None
            and vals['TurningPointElapsedSec'] >= 0 else None),
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
    # Between batch protocol (Tier 3 item 20, BT only): the
    # metrics staged at this batch CHARGE from the previous
    # roast DROP window, when a window was finalized. Batches
    # with no preceding drop carry no bbp key at all.
    _bbp = core.bbp_staged_metrics()
    if _bbp is not None:
        doc['bbp'] = _bbp
    # The saved target document carries the full variable
    # length plan (Tier 3 item 17) beside the legacy fields.
    doc['target']['points'] = [
        [float(t), float(v)] for t, v in core.target_plan_points()]
    doc['loss'] = lossd
    pts = [(float(p['t']), float(p['bt'])) for p in core.curve_points()]
    doc['phaseAnalysis'] = phase_analysis(doc, pts)
    return doc


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
    """Delete a saved batch and everything keyed by its number.

    Series rows cascade in Postgres (batch_series has a real FK
    ON DELETE CASCADE). Press rows cannot cascade that way:
    batch_events has no FK to batches, because presses are
    written during a roast for a batch_number that has no
    batches row until Save Batch, so an FK would break live
    press capture. They are deleted explicitly here, first,
    through Events/DeleteByBatch (HUNT-35, polish round 4).
    The decision to cascade rather than keep an audit trail:
    the saved batch document already snapshots the press
    events at save time, and no surface reads batch_events
    rows for a batch that no longer exists, so orphaned rows
    would be pure leftovers; the snapshotted events die with
    the batch row itself. If the events delete throws, the
    error propagates and the batch is NOT deleted, rather
    than deleting the batch and stranding the rows silently.
    """
    _run(NQ_EVENTS_DELETE, {'batch_number': int(batch_number)})
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
    Series/InsertBatch.

    Failure containment (polish round 4, HUNT-36): the whole
    database section is wrapped, so a faulted connection does
    not throw out of the handler. The failure is reported in
    the save note and as an error toast, and the function
    returns None. The first call (get_batch) throws before
    any write when the fault is already present at entry, so
    nothing is half written in that case and a retry once the
    connection heals saves completely; when a save did land,
    the already saved guard below still answers the retry."""
    number = None
    try:
        vals = core.read_members(['BatchNumber', 'BeanName', 'ChargeTime',
                                  'DropTime', 'DropTempF'])
        number = vals['BatchNumber']
        if get_batch(vals['BatchNumber']) is not None:
            self.view.custom.saveNote = (
                'Batch %d is already in the log. Start a New Roast for '
                'a fresh batch number, or edit the saved batch from '
                'the Log tab.' % vals['BatchNumber'])
            return vals['BatchNumber']
        # A saved batch's press rows must be complete: settle any
        # press the transaction group missed before the document
        # lands (polish round 3, HUNT-22). A short grace is enough
        # here; the group writes inside a second in the normal
        # case, and Save follows the last press by seconds.
        core.reconcile_press_pending(1.0)
        doc = build_document()
        _run(NQ_INSERT, {
            'batch_number': vals['BatchNumber'],
            'roast_start': vals['ChargeTime'],
            'roast_end': vals['DropTime'],
            'bean_name': vals['BeanName'],
            'drop_temp_f': vals['DropTempF'],
            'data': system.util.jsonEncode(doc)})
        _insert_series(vals['BatchNumber'], core.curve_points())
        # The staged BBP metrics were written into this batch
        # document by build_document; consume them so a later
        # save cannot inherit them (Tier 3 item 20).
        core.bbp_clear_staged()
        core.record_press('Save Batch')
        self.view.custom.saveNote = 'Saved batch %d to the database.' % vals['BatchNumber']
        core.show_toast(self, 'Batch %d saved' % vals['BatchNumber'],
                        'success')
        return vals['BatchNumber']
    except:
        # Bare except on purpose (polish round 4, HUNT-36):
        # runNamedQuery throws a Java exception on a faulted
        # connection, which except Exception does not catch
        # in Jython (see roastery.core.record_press).
        msg = ('Save failed: batch %s was not saved. The database '
               'connection failed, so nothing was written. Try '
               'again once the connection is back.'
               % (number if number is not None else '?'))
        try:
            self.view.custom.saveNote = msg
        except:
            pass
        core.show_toast(self, msg, 'error')
        return None



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
        data = {}
        for m in core.FORM_MEMBERS:
            if m in core.FORM_BOOLS:
                data[m] = False
            elif m in core.FORM_INTS:
                data[m] = 0
            elif m in core.FORM_FLOATS:
                data[m] = 0.0
            else:
                data[m] = ''
        data.update({'HarvestYear': 2025, 'ChargeWeightG': 200.0,
                     'TargetDropTempF': 415.0,
                     'RoasterType': 'FreshRoast SR800',
                     'RoasterSizeKg': 0.25, 'BatchNumber': 0})
        return data
    number = int(system.tag.readBlocking([SELECTED_TAG])[0].value or 0)
    batch = get_batch(number)
    if batch is None:
        return {}
    doc = batch['document']
    meta = dict(doc.get('metadata') or {})
    # Polish round 1 item 0: a member the stored document does
    # not carry falls back to the standing tag value, NOT to a
    # hard 0. Seeded and legacy documents carry sparse metadata
    # (batch 1042 has no HarvestYear and no TargetDropTempF),
    # and a hard 0 violates those form fields' enabled
    # constraints (HarvestYear min 1900, TargetDropTempF min
    # 200), which left the form permanently invalid, so its
    # Save Batch button (autoDisable) never enabled no matter
    # what was typed into the event fields. The tag values are
    # the same standing values create mode starts from, and
    # they are always inside the field constraints.
    fallback = core.config_form_data()
    data = {}
    for m in core.FORM_MEMBERS:
        v = meta.get(m)
        if v is None:
            v = fallback.get(m)
        if v is None:
            v = (False if m in core.FORM_BOOLS else
                 0 if m in core.FORM_INTS else
                 (0.0 if m in core.FORM_FLOATS else ''))
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
    core.show_toast(self, 'Batch %d saved' % batch_number, 'success')
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
    core.show_toast(self, 'Batch %d created' % number, 'success')
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
        table = self.view.getChild('BatchesPanelRoot').getChild('BatchTable')
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
    root = self.getChild('BatchEditRoot')
    if root is None:
        root = self.view.getChild('BatchEditRoot')
    root.getChild('BatchForm').props.data = edit_form_data_for(self)



def arm_delete(self):
    number = int(self.view.custom.selBatchNumber or 0)
    if number <= 0:
        return
    self.view.custom.confirmDelete = True
    self.view.custom.selNote = ('Delete batch %d, its curve and its '
                                'press log? Press Confirm Delete to '
                                'proceed.' % number)


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
    levels = []
    for r in range(ds.rowCount):
        pairs.append([ds.getValueAt(r, 't_offset_sec'),
                      ds.getValueAt(r, 'bean_temp_f')])
        levels.append((ds.getValueAt(r, 't_offset_sec'),
                       ds.getValueAt(r, 'fan_level'),
                       ds.getValueAt(r, 'heat_level')))
    batch = get_batch(batch_number)
    label = 'Batch %d' % batch_number
    if batch is not None and batch['beanName']:
        label += ' - ' + batch['beanName']
    drop_sec = -1.0
    if batch is not None:
        ev = (batch['document'].get('events') or {}).get('drop')
        if ev and ev.get('t') is not None:
            drop_sec = float(ev['t'])
        elif batch['document'].get('totalSec'):
            drop_sec = float(batch['document']['totalSec'])
    # Playback events for Tier 2 item 11 ride along with the
    # ghost: the Fan and Heat changes in its own series plus
    # its drop time, derived by roastery.core.
    events = core.build_background_events(levels, drop_sec)
    # Phase boundaries for Tier 3 item 16 stage with the ghost
    # too, from its stamped document events (session level
    # staging tags; the saved Settings targets stay untouched).
    if batch is not None:
        _ev = batch['document'].get('events') or {}
        core.stage_bg_phases(
            (_ev.get('dryEnd') or {}).get('t'),
            (_ev.get('fcStart') or {}).get('t'),
            (_ev.get('drop') or {}).get('t'))
    system.tag.writeBlocking(
        [core.BACKGROUND_JSON, BACKGROUND_LABEL,
         core.BACKGROUND_DROP_TAG, core.BACKGROUND_EVENTS_TAG],
        [system.util.jsonEncode(pairs), label, drop_sec,
         system.util.jsonEncode(events)])
    core.build_overlays()
    system.perspective.navigate(page='/')



# ---------------------------------------------------------------- compare
# Multi curve comparison on the Log page (Tier 1 item 2): up to
# three saved batches overlaid on one canvas chart, BT solid and
# RoR dashed per batch. RoR is recomputed from each batch's
# stored temps with the current parameters, the same offline
# path stage_detail uses, so compared curves can never disagree
# with the detail view.

COMPARE_COLS = ['t_stamp', 't_label', 't_sec', 'btA', 'rorA',
                'btB', 'rorB', 'btC', 'rorC']
COMPARE_SLOTS = ('A', 'B', 'C')

# Polish round 8 (HUNT-56): event-based compare alignment,
# after Artisan 5.0.0's alignEvent (src/artisanlib/canvas.py
# timealign for the background, comparator.py realign for
# the comparator). Artisan's align names are CHARGE, TP,
# DRY, FCs, FCe, SCs, SCe, DROP (comparator.py alignnames,
# indices 0-7); its background alignEvent adds ALL (7),
# which tries DROP, then SCe, SCs, FCe, FCs, DRY, CHARGE
# in that order. realign anchors the TOP profile to its
# CHARGE (delta = startTime, refTime 0 for CHARGE) and
# shifts every other profile by delta = eventTime -
# refTime, where eventTime is that profile's chosen event
# read off its own timex; a profile missing the event is
# NOT aligned (it falls back to its CHARGE / first
# reading), and a vertical align line draws at refTime.
# This build offers the seven stamped events (no TP: the
# turning point is derived, not a stamped event in the
# batch document; no ALL: the comparator needs one
# explicit event). The tag value is the stored key below;
# the dropdowns show the Artisan short label.
COMPARE_ALIGN_EVENTS = [
    ('charge', 'CHARGE'), ('dryEnd', 'DRY'),
    ('fcStart', 'FCs'), ('fcEnd', 'FCe'),
    ('scStart', 'SCs'), ('scEnd', 'SCe'),
    ('drop', 'DROP')]
COMPARE_ALIGN_LABELS = dict(COMPARE_ALIGN_EVENTS)
COMPARE_ALIGN_TAG = '[default]Roastery/CurrentBatch/CompareAlignEvent'


def compare_align_event():
    """The Display setting for compare alignment: the tag
    value, or 'charge' for anything missing or unknown
    (same fallback shape as core.axis_format). Both the
    Settings Display dropdown and the Log compare row
    dropdown bind this one tag, so they always agree."""
    try:
        v = core.read_members(['CompareAlignEvent'])['CompareAlignEvent']
    except Exception:
        v = None
    return v if v in COMPARE_ALIGN_LABELS else 'charge'


def _compare_events(doc):
    """A batch document's stamped event seconds, keyed by
    align key; None where the batch never stamped the
    event (the seeded stubs, for example, carry only
    charge, dryEnd, fcStart and drop)."""
    events = (doc or {}).get('events') or {}
    out = {}
    for key, _lbl in COMPARE_ALIGN_EVENTS:
        e = events.get(key)
        t = e.get('t') if isinstance(e, dict) else None
        out[key] = None if t is None else float(t)
    return out


def align_compare_slots(slot_data, align_key):
    """Pure alignment math over staged slot data (no tag or
    database reads, so the suite can drive it through the
    same library functions build_compare calls). slot_data
    is a list in slot order (A first, the Artisan top
    profile) of dicts with slot, number, bean, points
    [(t_sec, bean_temp_f)], rors {t_sec: ror_or_None} and
    events {align_key: t_sec_or_None}.
    Returns placed {column: {grid_sec: value}}, max_sec,
    ref_sec (the displayed, grid-snapped reference event
    second), ref_label, fallbacks [(slot, number)] for
    every slot that lacked the event, shifts {slot:
    snapped_shift_sec} and offset_sec.
    Shifts are Artisan's delta (own event minus the
    reference event) snapped to the 30 s library grid
    (HUNT-51): a shift lands on a grid step, so the
    aligned event lands within 15 s of the reference,
    the same quantization the grid already applies to
    every sample. A slot missing the event falls back to
    aligning its charge to the reference event (its t=0
    lands on ref_sec), Artisan's fallback: realign's last
    branch reads a profile missing the event at its CHARGE
    as its event time. The reference slot itself never
    shifts. When the reference slot itself lacks the event
    there is no Artisan reference point (realign returns
    without aligning); this build falls back to charge
    alignment for all slots instead and says so in the
    caption, so Compare never leaves curves unaligned
    without saying why. Aligned seconds can go
    negative (aligning on DROP pulls every charge left
    of zero); the category grid starts at 0, so the
    whole overlay translates right by offset_sec, a grid
    multiple, and the reference line moves with it.
    Artisan instead shows negative times; the translate
    keeps every sample visible on this grid at the cost
    of the reference no longer reading its raw second,
    which the caption states by naming the event."""
    if align_key not in COMPARE_ALIGN_LABELS:
        align_key = 'charge'
    ref = slot_data[0]
    ref_t = ref['events'].get(align_key)
    fallbacks = []
    if ref_t is None:
        ref_t = 0.0
        fallbacks.append((ref['slot'], ref['number']))
    shifts = {}
    for sd in slot_data:
        own = sd['events'].get(align_key)
        if own is None:
            own = 0.0
            fallbacks.append((sd['slot'], sd['number']))
        shifts[sd['slot']] = core.grid_bucket(own - ref_t)
    buckets = {}
    min_bucket = None
    max_bucket = 0
    for sd in slot_data:
        rows = []
        for t, bt in sd['points']:
            b = core.grid_bucket(t - shifts[sd['slot']])
            rows.append((b, bt, sd['rors'].get(t)))
            if min_bucket is None or b < min_bucket:
                min_bucket = b
            if b > max_bucket:
                max_bucket = b
        buckets[sd['slot']] = rows
    offset = (-min_bucket if min_bucket is not None
              and min_bucket < 0 else 0)
    placed = {}
    for sd in slot_data:
        for b, bt, ror in buckets[sd['slot']]:
            s = b + offset
            placed.setdefault('bt' + sd['slot'], {})[s] = bt
            placed.setdefault('ror' + sd['slot'], {})[s] = ror
    return {'placed': placed, 'max_sec': max_bucket + offset,
            'ref_sec': core.grid_bucket(ref_t) + offset,
            'ref_label': COMPARE_ALIGN_LABELS[align_key],
            'fallbacks': fallbacks, 'shifts': shifts,
            'offset_sec': offset, 'align_key': align_key}


def compare_dataset(chosen, align_key=None):
    """Build a compare overlay for chosen [(slot, number)]
    in A/B/C order. Returns (rows, caption, ref_items,
    info): rows for second_grid's dataset shape, the
    caption naming each slot plus the alignment, the
    single ALIGN reference line item for the reference
    event (core._ref_items, so the line snaps to the
    grid like every other reference line), and the
    align_compare_slots info dict. Empty when nothing
    stages. A chosen batch with no curve data stages
    nothing but is still named in the caption
    (HUNT-61): ' | Batch <n> has no curve data.'"""
    if align_key is None:
        align_key = compare_align_event()
    elif align_key not in COMPARE_ALIGN_LABELS:
        align_key = 'charge'
    slot_data = []
    captions = []
    no_curve = []
    for slot, number in chosen:
        if number <= 0:
            continue
        points = _compare_points(number)
        if not points:
            no_curve.append(number)
            continue
        rors = core.compute_ror_series(points, core.ror_params(),
                                       offline=True)
        batch = get_batch(number)
        bean = (batch['beanName'] if batch else '') or ''
        doc = (batch or {}).get('document') or {}
        slot_data.append({'slot': slot, 'number': number,
                          'bean': bean, 'points': points,
                          'rors': dict((t, r) for t, r in rors),
                          'events': _compare_events(doc)})
        captions.append('%s = Batch %d %s' % (slot, number, bean))
    if not slot_data:
        caption = 'Pick at least one batch to compare.'
        for n in no_curve:
            caption += ' | Batch %d has no curve data.' % n
        return [], caption, [], {
            'placed': {}, 'max_sec': 0, 'ref_sec': 0,
            'ref_label': COMPARE_ALIGN_LABELS.get(align_key,
                                                  'CHARGE'),
            'fallbacks': [], 'shifts': {}, 'offset_sec': 0,
            'align_key': align_key}
    info = align_compare_slots(slot_data, align_key)
    rows = core.second_grid(
        info['placed'], ['btA', 'rorA', 'btB', 'rorB', 'btC',
                         'rorC'], info['max_sec'])
    caption = (' - '.join(captions) + ' - Aligned on '
               + info['ref_label'])
    if info['fallbacks']:
        caption += (' (' + ', '.join(
            '%s has no %s, charge aligned' % (s, info['ref_label'])
            for s, _n in info['fallbacks']) + ')')
    for n in no_curve:
        caption += ' | Batch %d has no curve data.' % n
    ref_items = core._ref_items(
        [(info['ref_sec'], 'ALIGN ' + info['ref_label'])],
        top_gap=55.0)
    return rows, caption, ref_items, info


def compare_options():
    """Dropdown options for the compare pickers, from the
    SelectAll named query (the table's own source)."""
    ds = _run(NQ_SELECT_ALL)
    out = [{'value': 0, 'label': 'None'}]
    for r in range(ds.rowCount):
        n = ds.getValueAt(r, 'batch_number')
        bean = ds.getValueAt(r, 'bean_name') or ''
        out.append({'value': int(n),
                    'label': 'Batch %s - %s' % (n, bean)})
    return out


def compare_startup(self):
    """BatchesPanel onStartup: fill the three compare pickers
    and default A and B to the two newest batches."""
    opts = compare_options()
    root = self.getChild('BatchesPanelRoot')
    if root is None:
        root = self.view.getChild('BatchesPanelRoot')
    for slot in COMPARE_SLOTS:
        root.getChild('CompareRow').getChild(
            'Cmp' + slot).props.options = opts
    nums = [o['value'] for o in opts if o['value']]
    c = self.view.custom
    if len(nums) >= 2:
        c.cmpA, c.cmpB = nums[0], nums[1]
    elif nums:
        c.cmpA = nums[0]


def _compare_points(batch_number):
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    points = []
    for r in range(ds.rowCount):
        bt = ds.getValueAt(r, 'bean_temp_f')
        if bt is not None:
            points.append((float(ds.getValueAt(r, 't_offset_sec')),
                           float(bt)))
    points.sort()
    return points


def build_compare(self):
    """Compare button: build the wide compare dataset on the
    elapsed category axis (grid rows 30 s apart, nulls
    elsewhere, the live chart's merge shape; polish round 3,
    HUNT-23; polish round 6, HUNT-51: the rows are the even
    grid steps, so the shown labels are even increments),
    the caption naming each slot and the alignment, and the
    single ALIGN reference line on the reference event.
    Alignment is Artisan's alignEvent (polish round 8,
    HUNT-56): the curves shift so the chosen event (the
    CompareAlignEvent tag, CHARGE by default) lands on the
    same grid step for every batch, slot A as the reference;
    see align_compare_slots for the shift, fallback and
    translate rules."""
    c = self.view.custom
    chosen = [('A', int(c.cmpA or 0)), ('B', int(c.cmpB or 0)),
              ('C', int(c.cmpC or 0))]
    rows, caption, ref_items, _info = compare_dataset(chosen)
    c.compareDs = system.dataset.toDataSet(COMPARE_COLS, rows)
    c.compareCaption = caption
    c.compareRefLines = ref_items


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

def _detail_span(end_sec):
    """Staged detail grid span in seconds for a batch whose
    extent (last event or curve point) is end_sec. At or
    over DETAIL_MIN_SPAN_SEC the span is the natural extent,
    unchanged from the round 2 and 3 behavior. Under it the
    span floors at the larger of DETAIL_SHORT_FLOOR_SEC and
    the extent (HUNT-37), so a short batch fills a sensible
    share of the axis instead of the first tenth of a 600 s
    grid."""
    end_sec = int(end_sec)
    if end_sec >= DETAIL_MIN_SPAN_SEC:
        return end_sec
    return max(DETAIL_SHORT_FLOOR_SEC, end_sec)


def _detail_top_gap(span):
    """Event label gap in seconds for a detail chart staged
    at span seconds: DETAIL_REF_GAP_SEC at the full span,
    scaled in proportion under it (55 s at 600 scales to
    16.5 s at the 180 s floor), so events a few seconds
    apart on a short batch still drop their labels while
    events tens of seconds apart earn them. At or over
    DETAIL_MIN_SPAN_SEC the gap is exactly
    DETAIL_REF_GAP_SEC."""
    span = int(span)
    if span >= DETAIL_MIN_SPAN_SEC:
        return DETAIL_REF_GAP_SEC
    return DETAIL_REF_GAP_SEC * float(span) / float(
        DETAIL_MIN_SPAN_SEC)


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
    # X values are elapsed seconds on the category axis
    # (polish round 3, HUNT-23): the detail chart reads
    # exactly like the live chart, true elapsed labels in
    # any browser timezone, and no longer depends on the
    # batch having a stored roast_start wall clock (the
    # generated fixture batches have none, and their detail
    # curves used to stage empty). The grid span comes from
    # _detail_span (the round 2 tick span fix, which used to
    # bind the axis max from detail_startup; the padded grid
    # now carries the span itself, floored by HUNT-37 for
    # short batches). A stored point at a fractional second
    # lands on its nearest grid step (HUNT-51: the grid
    # rows are 30 s apart, so a stored point buckets to its
    # nearest row; the stored series keeps true seconds).
    placed = {'bt': {}, 'ror': {}}
    for (t, bt), (_t2, ror) in zip(points, rors):
        s = core.grid_bucket(t)
        placed['bt'][s] = bt
        placed['ror'][s] = ror
    end_sec = int(float(doc.get('totalSec') or 0))
    if points:
        end_sec = max(end_sec, int(round(points[-1][0])))
    rows = core.second_grid(
        placed, ['bt', 'ror'],
        _detail_span(end_sec))
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
        [system.dataset.toDataSet(
            ['t_stamp', 't_label', 't_sec', 'bt', 'ror'], rows),
         core.marks_dataset(evs)])
    # The detail analyzer (Tier 2 item 13) restages with the
    # batch: selection back to Latest, readout recomputed.
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [-1])
    detail_analyzer_refresh()
    return True


# ------------------------------------------------------- detail analyzer
# Tier 2 item 13 on BatchDetail: the same crosshair readout as
# the live chart, computed over the staged DetailDS (stored
# temps with RoR recomputed on read by stage_detail, the one
# implementation) plus the staged ghost for the ghost BT and
# deviation columns. Values publish to the DetailAnalyzer
# tags the detail strip binds; selection moves through the
# strip steppers, never through floating chart text.

def _detail_analyzer_paths():
    names = {'timeText': 'TimeText', 'btText': 'BtText',
             'rorText': 'RorText', 'bgText': 'BgText',
             'devText': 'DevText', 'btF': 'BtF', 'rorF': 'RorF',
             'bgF': 'BgF', 'devF': 'DevF', 'hasBg': 'HasBg'}
    return dict((k, core.DETAIL_ANALYZER + '/' + v)
                for k, v in names.items())


def _detail_points():
    """Points for the BatchDetail analyzer: the staged batch's
    stored series (true seconds), NOT the DetailDS grid.
    Polish round 6 (HUNT-51): the DetailDS grid is one row
    per 30 s for display, so interpolating over it reads up
    to 7 F off on a steep section; the analyzer is a precision
    readout and must use the stored samples, the same source
    stage_detail staged from. RoR is recomputed by the one
    implementation (offline), as stage_detail does."""
    try:
        n = int(system.tag.readBlocking([SELECTED_TAG])[0].value)
    except Exception:
        return [], []
    rows = _series_rows(n)
    points = [(float(r['t']), float(r['bt'])) for r in rows
              if r['t'] is not None and r['bt'] is not None]
    rors = core.compute_ror_series(points, core.ror_params(),
                                   offline=True)
    return points, rors


def detail_analyzer_refresh():
    """Recompute the BatchDetail analyzer readout at the
    selected time (DetailAnalyzer/Sec, -1 is Latest)."""
    points, rors = _detail_points()
    if not points:
        return
    sec = system.tag.readBlocking(
        [core.DETAIL_ANALYZER + '/Sec'])[0].value
    t = points[-1][0] if sec is None or int(sec) < 0 else float(sec)
    t = max(points[0][0], min(points[-1][0], t))
    core._analyzer_write(
        _detail_analyzer_paths(),
        core.analyzer_values(points, rors, t))


def detail_analyzer_step(delta):
    """Detail analyzer stepper (thin handler target)."""
    points, _rors = _detail_points()
    if not points:
        return
    sec = system.tag.readBlocking(
        [core.DETAIL_ANALYZER + '/Sec'])[0].value
    base = points[-1][0] if sec is None or int(sec) < 0         else float(sec)
    new = max(points[0][0], min(points[-1][0],
                                base + float(delta)))
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [int(new)])
    detail_analyzer_refresh()


def detail_analyzer_latest():
    """Detail analyzer Latest button."""
    system.tag.writeBlocking(
        [core.DETAIL_ANALYZER + '/Sec'], [-1])
    detail_analyzer_refresh()


def _detail_reference_lines(gap_fn):
    """Shared body for detail_reference_lines and its compact
    variant: reference line items for the staged batch's
    events, from the DetailDocJson document stage_detail
    wrote (custom event names intact). The label gap comes
    from gap_fn(span): the span is read back from the staged
    DetailDS grid itself (one row per grid step, so
    (rowCount minus 1) times the step is the span
    stage_detail built), which keeps the gap in exact step
    with the grid; when no grid is staged the span falls back
    to the document extent through
    _detail_span. The same span also sets the line gap
    (DETAIL_LINE_GAP_FRAC of span), so desktop and phone
    draw the same lines and differ only in labels."""
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
    span = None
    ds = system.tag.readBlocking([DETAIL_DS])[0].value
    if ds is not None and ds.rowCount > 0:
        span = (ds.rowCount - 1) * core.AXIS_GRID_STEP_SEC
    if span is None:
        end_sec = int(float(doc.get('totalSec') or 0))
        for _t, _lbl in evs:
            end_sec = max(end_sec, int(_t))
        span = _detail_span(end_sec)
    return core._ref_items(evs, top_gap=gap_fn(span),
                           line_gap=DETAIL_LINE_GAP_FRAC * span)


def detail_reference_lines():
    """Reference line items for the staged batch's events.
    Bound on the desktop detail chart's bean series through
    a script transform triggered by DetailMarksDS. The label
    gap scales with the staged span (HUNT-37): 55 s at the
    600 s span, proportionally less under it."""
    return _detail_reference_lines(_detail_top_gap)


def detail_reference_lines_compact():
    """Phone variant of the detail reference lines (round 5,
    HUNT-41): the phone detail chart squeezes the span into
    about 250 px, so two labels in the top band need about
    65 px of clearance not to touch, which is 0.26 of the
    span in seconds. The desktop gap (16.5 s at the 180 s
    floor) let batch 1042's CHARGE and DROP print as one
    word, CHARGEDROP, and batch 9919's CHARGE and LATE NOTE
    as CHARGELATE NOTE at 360 px; the compact gap drops the
    second label instead (the events strip under the chart
    always names every event). Bound on the phone detail
    chart instance, the same paired instance pattern as the
    live chart and the HUNT-13 phone tables."""
    return _detail_reference_lines(
        lambda span: 0.26 * float(span))


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


# Tier 2 items 7, 8 and 10b: phase analytics completion, loss /
# yield / density, and the BT similarity score. Definitions are
# Artisan 5.0.0 main.py: RoR(TP_index, dryEndIndex),
# computedProfileInformation() (phase RoRs, delta temps, total
# RoR, fcs_ror, per phase AUC through ts(), cool phase time from
# calcStatistics), weight_loss(), volume_increase(), and
# curveSimilarity() (BT half).


def _weight_loss(green, roasted):
    """Artisan weight_loss: percent, 0 when green is 0 or the
    roasted weight exceeds the green weight."""
    green = float(green or 0.0)
    roasted = float(roasted or 0.0)
    if green == 0.0 or green < roasted:
        return 0.0
    return 100.0 * ((green - roasted) / green)


def _volume_increase(green, roasted):
    """Artisan volume_increase: percent, 0 when green is 0 or
    the roasted volume is smaller than the green volume."""
    green = float(green or 0.0)
    roasted = float(roasted or 0.0)
    if green == 0.0 or green > roasted:
        return 0.0
    return 100.0 * ((roasted - green) / green)


def loss_yield_density(meta):
    """The full Artisan loss, yield and density set from the
    batch metadata (Tier 1 item 3 fields). Every value is
    guarded: when an input is absent or the Artisan formula
    would divide by zero or read a negative yield, the key is
    simply not stored, never a fabricated number. Keys:
    weightLossPct, defectsLossPct, totalLossPct, totalYieldG,
    totalYieldPct, volumeGainPct, moistureLossPct,
    organicLossPct, greenDensityGL, roastedDensityGL.
    Densities are weight over volume in g per L (Artisan
    converts weight to g and volume to L; Roastery stores g
    and ml, so density is weight * 1000 / volume_ml).
    totalYieldG is Artisan's computed total_yield (the yield
    weight in grams, weight out minus defects); totalYieldPct
    is the same yield as a percent of the green weight."""
    meta = meta or {}
    out = {}

    def _f(key):
        v = meta.get(key)
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    win = _f('ChargeWeightG')
    wout = _f('WeightOutG')
    defects = _f('DefectsWeightG')
    vin = _f('VolumeInMl')
    vout = _f('VolumeOutMl')
    gmoist = _f('MoisturePct')
    rmoist = _f('RoastedMoisturePct')
    wl = _weight_loss(win, wout) if win > 0 and wout > 0 else 0.0
    if wl > 0:
        out['weightLossPct'] = wl
    if wout > 0 and defects > 0 and defects < wout:
        dl = _weight_loss(wout, wout - defects)
        if dl > 0:
            out['defectsLossPct'] = dl
    if vin > 0 and vout > 0:
        vg = _volume_increase(vin, vout)
        if vg > 0:
            out['volumeGainPct'] = vg
    if gmoist > 0 and rmoist > 0:
        ml = gmoist - rmoist
        out['moistureLossPct'] = ml
        if wl > 0:
            out['organicLossPct'] = wl - ml
    if win > 0 and (wout > 0 or defects > 0):
        res = (wout - defects) if wout > 0 else (win - defects)
        if res > 0:
            out['totalYieldG'] = res
            out['totalYieldPct'] = res * 100.0 / win
            tl = _weight_loss(win, res)
            if tl > 0:
                out['totalLossPct'] = tl
    if win > 0 and vin > 0:
        out['greenDensityGL'] = win * 1000.0 / vin
    if wout > 0 and vout > 0:
        out['roastedDensityGL'] = wout * 1000.0 / vout
    return out


def _auc_range(points, start, end, base):
    """Trapezoid area between the bean curve and the base temp
    over [start, end] only, in degree F minutes (Artisan ts()
    per phase shape, calcAUC trapezoids). Segments are clipped
    to the range with interpolated endpoint temps."""
    if end is None or start is None or end <= start or not points:
        return None
    auc = 0.0
    for i in range(len(points) - 1):
        t0, v0 = points[i]
        t1, v1 = points[i + 1]
        if t1 <= start or t0 >= end or t1 <= t0:
            continue
        a = max(t0, start)
        b = min(t1, end)
        va = v0 + (v1 - v0) * (a - t0) / (t1 - t0)
        vb = v0 + (v1 - v0) * (b - t0) / (t1 - t0)
        avg = (va + vb) / 2.0
        if avg > base:
            auc += (avg - base) * (b - a) / 60.0
    return auc


def _interp_pairs(pairs, t):
    if not pairs or t < pairs[0][0] or t > pairs[-1][0]:
        return None
    for i in range(len(pairs) - 1):
        t0, v0 = pairs[i]
        t1, v1 = pairs[i + 1]
        if t0 <= t <= t1:
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pairs[-1][1]


def bt_similarity(fg_points, fg_drop_t, bg_points, bg_drop_t,
                  fg_dry_t=None):
    """BT similarity against the background, Artisan main.py
    curveSimilarity() BT half only (the dbt value): the RMSE
    in F between the foreground BT and the background BT
    interpolated at the same times, over the stretch from
    DRY to DROP, with the background time axis shifted so the
    two DROP times align (dropTimeDelta). The ET half is
    skipped (single sensor). Roastery adaptation: Artisan
    locates its dry index by scanning back from DROP for the
    phases dry boundary temperature; Roastery uses its
    recorded Dry End event as the same phase boundary.
    Returns None when either curve lacks a DROP or there is
    no overlap to compare."""
    if (not fg_points or not bg_points or fg_drop_t is None
            or bg_drop_t is None):
        return None
    start = float(fg_dry_t) if fg_dry_t is not None else 0.0
    shift = float(fg_drop_t) - float(bg_drop_t)
    sq = []
    for t, bt in fg_points:
        if t < start or t > float(fg_drop_t):
            continue
        b = _interp_pairs(bg_points, t - shift)
        if b is None:
            continue
        sq.append((float(bt) - b) ** 2)
    if not sq:
        return None
    return math.sqrt(sum(sq) / len(sq))


def phase_analysis(doc, points):
    """Structured phase analytics for the saved document
    (Tier 2 item 7): per phase duration, share, delta temp,
    average RoR and AUC, plus fcsRorFMin, totalRorFMin and
    coolSec. Only values the data actually supports are
    stored. See _phase_analysis for the definitions."""
    rows, _tp_text, extra = _phase_analysis(doc, points)
    out = {'phases': {}}
    for name, vals in extra['phases'].items():
        out['phases'][name] = vals
    if extra.get('fcsRor') is not None:
        out['fcsRorFMin'] = extra['fcsRor']
    if extra.get('totalRor') is not None:
        out['totalRorFMin'] = extra['totalRor']
    if extra.get('coolSec') is not None:
        out['coolSec'] = extra['coolSec']
    return out


def _phase_analysis(doc, points):
    """Analyzer style phase readouts for the detail view,
    aligned to Artisan's computed block (Tier 2 item 7):
    per phase duration and share (dry phase time still runs
    charge to dry end, as in Artisan calcStatistics), the per
    phase delta temp and average RoR from Artisan RoR() (the
    DRY phase RoR and delta are measured from the TURNING
    POINT, or from the greens temp when one is recorded, not
    from charge), per phase AUC (Artisan ts() ranges: charge
    to dry, dry to FC start, FC start to drop, above the AUC
    base), the RoR at FC START (fcs_ror, the RoR series value
    at the FC sample), the total RoR (TP to drop), and a cool
    phase line (drop to the cool end: the imported Artisan
    COOL time when present, else the last stored sample).
    Returns (table rows, turning point text, extra dict)."""
    events = doc.get('events') or {}
    meta = doc.get('metadata') or {}

    def ev(key, field):
        e = events.get(key)
        return e.get(field) if e else None

    total = doc.get('totalSec') or (points[-1][0] if points else 0)
    dry_t = ev('dryEnd', 't')
    fc_t = ev('fcStart', 't')
    drop_t = ev('drop', 't')
    saved_tp = doc.get('turningPoint') or {}
    tp = None
    if (saved_tp.get('t') is not None
            and saved_tp.get('tempF') is not None):
        # The live detected turning point, saved with the batch
        # (roastery.core._track_turning_point); it wins over the
        # offline curve scan below.
        tp = (saved_tp['t'], saved_tp['tempF'])
    else:
        for (t, bt) in points:
            if t <= 0:
                continue
            if dry_t is not None and t >= dry_t:
                break
            if dry_t is None and total and t > total * 0.5:
                break
            if tp is None or bt < tp[1]:
                tp = (t, bt)
    # AUC base: the saved AUC detail base when present, else
    # the charge temp (the base curve_auc uses for the batch).
    auc_detail = doc.get('aucDetail') or {}
    base = auc_detail.get('baseF')
    if base is None:
        base = ev('charge', 'tempF') or 0.0
    greens = 0.0
    try:
        greens = float(meta.get('GreensTempF') or 0.0)
    except Exception:
        greens = 0.0
    dry_temp = ev('dryEnd', 'tempF')
    # Drying delta and RoR, Artisan RoR() first two branches.
    dry_gain = None
    dry_ror = None
    if dry_temp is not None and greens > 0:
        dry_gain = dry_temp - greens
        if dry_t:
            dry_ror = dry_gain / (dry_t / 60.0)
    elif dry_temp is not None and tp is not None and dry_t is not None and dry_t > tp[0]:
        dry_gain = dry_temp - tp[1]
        dry_ror = dry_gain / ((dry_t - tp[0]) / 60.0)
    bounds = (('Drying', 0, dry_t, dry_gain, dry_ror),
              ('Maillard', dry_t, fc_t, None, None),
              ('Development', fc_t, drop_t, None, None))
    phases = {}
    rows = []
    for name, ta, tb, gain, ror in bounds:
        if ta is None or tb is None or tb <= ta:
            continue
        dur = tb - ta
        if gain is None:
            fa = _interp_pairs(points, float(ta))
            fb = _interp_pairs(points, float(tb))
            # Event temps are the recorded truth when present;
            # the curve interpolation is the fallback.
            ea = ev('charge' if name == 'Drying' else
                    'dryEnd' if name == 'Maillard' else 'fcStart',
                    'tempF')
            eb = ev('dryEnd' if name == 'Drying' else
                    'fcStart' if name == 'Maillard' else 'drop',
                    'tempF')
            if ea is not None:
                fa = ea
            if eb is not None:
                fb = eb
            gain = (fb - fa) if (fa is not None
                                 and fb is not None) else None
            ror = (gain / (dur / 60.0)) if gain is not None else None
        auc = _auc_range(points, float(ta), float(tb), float(base))
        phases[name] = {'sec': dur,
                        'sharePct': (dur * 100.0 / total)
                        if total else None,
                        'deltaF': gain, 'rorFMin': ror,
                        'aucFMin': auc}
        rows.append([name, _mmss(dur),
                     ('%.0f%%' % (dur * 100.0 / total))
                     if total else '--',
                     ('%+.0f F' % gain) if gain is not None
                     else '--',
                     ('%.1f F/min' % ror) if ror is not None
                     else '--',
                     ('%.0f' % auc) if auc is not None else '--'])
    # Cool phase: drop to cool end.
    cool_sec = None
    cool_end = None
    sub = (doc.get('artisan') or {}).get('events') or {}
    if sub.get('coolEndSec') is not None:
        cool_end = float(sub['coolEndSec'])
    elif points and drop_t is not None and points[-1][0] > drop_t:
        cool_end = float(points[-1][0])
    if cool_end is not None and drop_t is not None and cool_end > drop_t:
        cool_sec = cool_end - drop_t
        span = total + cool_sec
        rows.append(['Cool', _mmss(cool_sec),
                     ('%.0f%%' % (cool_sec * 100.0 / span))
                     if span else '--', '--', '--', '--'])
    # RoR at FC START from the one RoR implementation.
    fcs_ror = None
    if fc_t is not None and points:
        rors = core.compute_ror_series(points, core.ror_params(),
                                       offline=True)
        best = None
        for t, r in rors:
            if r is None:
                continue
            if best is None or abs(t - fc_t) < abs(best[0] - fc_t):
                best = (t, r)
        if best is not None:
            fcs_ror = best[1]
    total_ror = None
    drop_temp = ev('drop', 'tempF')
    if (tp is not None and drop_t is not None and drop_temp is not None
            and drop_t > tp[0]):
        total_ror = (drop_temp - tp[1]) / ((drop_t - tp[0]) / 60.0)
    extra = {'phases': phases, 'fcsRor': fcs_ror,
             'totalRor': total_ror, 'coolSec': cool_sec}
    tp_text = ('%.0f F at %s' % (tp[1], _mmss(tp[0]))) if tp         else '--'
    return rows, tp_text, extra


def detail_startup(self):
    core.apply_theme(self)
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
    calculator_seed(doc)
    self.view.custom.titleText = 'Batch %s - %s' % (
        doc.get('batchNumber'), doc.get('beanName') or '')
    self.view.custom.subText = '%s - %s' % (
        (doc.get('roastStart') or '')[:16].replace('T', ' '),
        doc.get('roastDegree') or '')
    # HUNT-24 (polish round 2 hunt): a seeded stub batch carries
    # a seedNote in its document (HUNT-16); surface it on the
    # detail page so the stub analytics are not read as a real
    # roast. Empty for normal batches, and the label hides.
    self.view.custom.dSeedNote = doc.get('seedNote') or ''
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
    # Statistics summary line (Tier 3 item 19): the same phase
    # values in the compact under chart form, percents of the
    # total roast time. No new math: the phase seconds and the
    # DTR percent come straight from the document phases block.
    _tot = float(doc.get('totalSec') or 0)

    def _share(sec):
        if not _tot or sec is None:
            return '--'
        return '%d%%' % int(round(float(sec) * 100.0 / _tot))
    def _ms(sec):
        # Polish round 1 item 5: a phase the document does not
        # have reads --:--, matching its -- share, never 0:00.
        if sec is None:
            return '--:--'
        sec = int(max(0, float(sec)))
        return '%d:%02d' % (sec // 60, sec % 60)
    _sep = ' ' + chr(183) + ' '
    self.view.custom.dStatsLine = _sep.join([
        'Dry %s %s' % (_ms(phases.get('dryingSec')),
                       _share(phases.get('dryingSec'))),
        'Mai %s %s' % (_ms(phases.get('maillardSec')),
                       _share(phases.get('maillardSec'))),
        'Dev %s %s' % (_ms(phases.get('developmentSec')),
                       _share(phases.get('developmentSec'))),
        'DTR %s' % (('%.0f%%' % phases['dtrPct'])
                    if phases.get('dtrPct') is not None
                    else '--')])
    pts = []
    try:
        sds = _run(NQ_SERIES_SELECT, {'batch_number': number})
        for r in range(sds.rowCount):
            bt = sds.getValueAt(r, 'bean_temp_f')
            if bt is not None:
                pts.append((float(sds.getValueAt(r,
                                                 't_offset_sec')),
                            float(bt)))
    except Exception:
        pts = []
    pts.sort()
    # Detail chart span (polish round 2 item 6, moved in
    # round 3): the span floor at DETAIL_MIN_SPAN_SEC used
    # to bind the axis max through a detailMaxMs custom
    # prop; on the category axis the padded grid
    # stage_detail builds carries the span itself, and the
    # view's axis max is simply auto.
    seg_rows, tp_text, extra = _phase_analysis(doc, pts)
    self.view.custom.analysisDs = system.dataset.toDataSet(
        ['phase', 'time', 'share', 'gain', 'avgRor', 'auc'],
        seg_rows)
    self.view.custom.dTp = tp_text
    fcs = extra.get('fcsRor')
    self.view.custom.dFcsRor = ('%.1f F/min' % fcs)         if fcs is not None else '--'
    tror = extra.get('totalRor')
    self.view.custom.dTotalRor = ('%.1f F/min' % tror)         if tror is not None else '--'
    cool = extra.get('coolSec')
    self.view.custom.dCool = _mmss(cool)         if cool is not None else '--'
    lossd = doc.get('loss') or loss_yield_density(meta)
    def _pct(key):
        v = lossd.get(key)
        return ('%.1f%%' % v) if v is not None else '--'
    def _dens(key):
        v = lossd.get(key)
        return ('%.0f g/L' % v) if v is not None else '--'
    self.view.custom.dDefectsLoss = _pct('defectsLossPct')
    self.view.custom.dTotalLoss = _pct('totalLossPct')
    self.view.custom.dVolumeGain = _pct('volumeGainPct')
    self.view.custom.dMoistureLoss = _pct('moistureLossPct')
    self.view.custom.dOrganicLoss = _pct('organicLossPct')
    self.view.custom.dGreenDensity = _dens('greenDensityGL')
    self.view.custom.dRoastedDensity = _dens('roastedDensityGL')
    yld = lossd.get('totalYieldPct')
    self.view.custom.dYield = ('%.1f%%' % yld)         if yld is not None else '--'
    # BT similarity against the currently staged ghost
    # (Tier 2 item 10b), when the ghost carries a drop time.
    sim = None
    try:
        bg_pairs = core.background_points()
        bg_drop = system.tag.readBlocking(
            [core.BACKGROUND_DROP_TAG])[0].value
        evs = doc.get('events') or {}
        drop_ev = evs.get('drop') or {}
        dry_ev = evs.get('dryEnd') or {}
        if bg_pairs and bg_drop is not None and float(bg_drop) >= 0:
            sim = bt_similarity(pts, drop_ev.get('t'), bg_pairs,
                                float(bg_drop), dry_ev.get('t'))
    except Exception:
        sim = None
    self.view.custom.dSimilarity = ('%.1f F RMSE' % sim)         if sim is not None else '--'
    # Between batch line (Tier 3 item 20): one line carrying
    # the four BBP values when the document has them, and an
    # empty string when it does not, so batches with no
    # preceding drop show nothing.
    _bbp_doc = doc.get('bbp') or {}
    if _bbp_doc:
        self.view.custom.dBbp = (
            'Between batch (BBP): %s, bottom %.0f F, '
            'RoR in %.1f F/min, RoR out %.1f F/min' % (
                _mmss(_bbp_doc.get('time_sec')),
                float(_bbp_doc.get('bottom_temp_f') or 0),
                float(_bbp_doc.get('ror_in_f_min') or 0),
                float(_bbp_doc.get('ror_out_f_min') or 0)))
    else:
        self.view.custom.dBbp = ''
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
    in v2 and stay null. Returns the number of batches inserted.

    HUNT-16 (polish round 2): stub rows gain a seedNote. A source
    row is a stub when totalSec is under 60 and drySec is 0: it
    never recorded even the first phase, so it is a short test
    artifact from early development, not a full roast record.
    Rows 4 to 7 of the legacy tag are exactly that (9 s each,
    drySec 0, the same drop temp repeated); rows 1 to 3 are short
    test roasts too (18 to 19 s) but carry complete phase splits
    and distinct curves, so the stub note would be false for them
    and they do not gain one. No fuller source for the stub rows
    survives anywhere: the RoastLog backup file is identical in
    content to the tag, and the original records were lost with
    the pre-rebuild database. Seeded values stay truthful to the
    source; nothing plausible is fabricated."""
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
        if total < 60 and (row['drySec'] or 0) == 0:
            doc['seedNote'] = (
                'Seeded from a RoastLog stub row (totalSec %g s, '
                'drySec 0): a short test artifact from early '
                'development, not a full roast record. No fuller '
                'source survives (the RoastLog backup file holds '
                'the same rows); the original record was lost '
                'with the pre-rebuild database.' % total)
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

# ---------------------------------------------------------------- Tier 3
# Item 18: batch export beyond .alog (CSV, JSON, printable HTML
# summary), and item 21: the yield and conversion calculator
# seeding. The export builders are pure library functions over
# the stored document (SelectById) and the stored series
# (Series/SelectByBatch, named queries only); the download
# handlers are thin one purpose wrappers around
# system.perspective.download, exactly like the .alog export in
# roastery.artisan. Ranking and production reports are skipped,
# per the Tier 3 inventory.

CALC_TAG = '[default]Roastery/Calculator'


def _series_rows(batch_number):
    """Stored series for one batch as plain dicts, in time order.
    RoR, fan and heat are the stored columns (RoR was derived by
    the one implementation at save time)."""
    ds = _run(NQ_SERIES_SELECT, {'batch_number': int(batch_number)})
    rows = []
    for r in range(ds.rowCount):
        rows.append({
            't': ds.getValueAt(r, 't_offset_sec'),
            'bt': ds.getValueAt(r, 'bean_temp_f'),
            'ror': ds.getValueAt(r, 'rate_of_rise_f'),
            'fan': ds.getValueAt(r, 'fan_level'),
            'heat': ds.getValueAt(r, 'heat_level')})
    rows.sort(key=lambda row: (row['t'] is None, row['t']))
    return rows


def _fmt_num(v, places=2):
    if v is None:
        return ''
    try:
        return ('%.' + str(places) + 'f') % float(v)
    except Exception:
        return str(v)


def _csv_cell(v):
    s = '' if v is None else str(v)
    if ',' in s or '"' in s or chr(10) in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _html_escape(v):
    s = '' if v is None else str(v)
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;'))


def build_csv_text(batch_number):
    """CSV export (Tier 3 item 18): a metadata header section
    (comment lines prefixed with # carrying the batch document
    key fields), then the series table with elapsed seconds,
    elapsed mm:ss, bean temp, RoR, fan and heat."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    doc = batch['document']
    meta = doc.get('metadata') or {}
    lines = []
    header = [
        ('Batch', doc.get('batchNumber')),
        ('Bean', doc.get('beanName')),
        ('Origin', meta.get('Origin')),
        ('Roast start', doc.get('roastStart')),
        ('Roast end', doc.get('roastEnd')),
        ('Roast degree', doc.get('roastDegree')),
        ('Drop temp F', _fmt_num(doc.get('dropTempF'), 1)),
        ('Total sec', doc.get('totalSec')),
        ('Charge weight g', _fmt_num(meta.get('ChargeWeightG'), 1)),
        ('Weight out g', _fmt_num(meta.get('WeightOutG'), 1)),
        ('Weight loss pct', _fmt_num(doc.get('weightLossPct'), 1)),
        ('AUC', _fmt_num(doc.get('auc'), 1)),
        ('Source', doc.get('source')),
    ]
    lines.append('# Roastery batch export')
    for k, v in header:
        if v not in (None, ''):
            lines.append('# ' + _csv_cell(k) + ',' + _csv_cell(v))
    lines.append('')
    lines.append('time_sec,time_mmss,bean_temp_f,'
                 'rate_of_rise_f_per_min,fan_level,heat_level')
    for row in _series_rows(batch_number):
        t = row['t']
        fan = row['fan']
        heat = row['heat']
        lines.append(','.join([
            _fmt_num(t, 1),
            _mmss(t) if t is not None else '',
            _fmt_num(row['bt']),
            _fmt_num(row['ror']),
            (('%d' % int(fan)) if fan is not None else ''),
            (('%d' % int(heat)) if heat is not None else '')]))
    return 'roastery-batch-%d.csv' % int(batch_number), chr(10).join(lines) + chr(10)


def build_json_text(batch_number):
    """JSON export (Tier 3 item 18): the full batch document
    plus the full stored series, one object."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    payload = {
        'batchNumber': int(batch_number),
        'beanName': batch['beanName'],
        'roastStart': _iso(batch['roastStart']),
        'roastEnd': _iso(batch['roastEnd']),
        'dropTempF': batch['dropTempF'],
        'document': batch['document'],
        'series': _series_rows(batch_number)}
    return ('roastery-batch-%d.json' % int(batch_number),
            system.util.jsonEncode(payload))


def build_summary_html(batch_number):
    """Printable summary (Tier 3 item 18): a standalone HTML
    file that reads well printed, with the batch metadata, the
    summary and phase analysis, the loss block, the events
    timeline and simple series statistics. Inline CSS lives in
    the generated file only (it is a print document, not a
    Perspective view, so the style class rule does not apply)."""
    batch = get_batch(int(batch_number))
    if batch is None:
        raise ValueError('Batch %s is not in the log.' % batch_number)
    doc = batch['document']
    meta = doc.get('metadata') or {}
    phases = doc.get('phases') or {}
    rows = _series_rows(batch_number)
    pts = [(float(r['t']), float(r['bt'])) for r in rows
           if r['t'] is not None and r['bt'] is not None]
    seg_rows, tp_text, extra = _phase_analysis(doc, pts)
    lossd = doc.get('loss') or loss_yield_density(meta)
    max_bt = max([bt for _t, bt in pts]) if pts else None
    dur = pts[-1][0] if pts else None
    e = _html_escape
    out = []
    out.append('<!DOCTYPE html>')
    out.append('<html><head><meta charset="utf-8">')
    out.append('<title>Roastery Batch %s Summary</title>' % e(doc.get('batchNumber')))
    out.append('<style>body{font-family:Arial,sans-serif;margin:32px;'
               'color:#111}h1{font-size:22px;margin:0 0 4px}'
               'h2{font-size:15px;margin:24px 0 8px;color:#0c7bb3}'
               'table{border-collapse:collapse;min-width:320px}'
               'td,th{border:1px solid #999;padding:5px 10px;'
               'font-size:13px;text-align:left}'
               '.sub{color:#555;font-size:13px}</style></head><body>')
    out.append('<h1>Batch %s - %s</h1>' % (e(doc.get('batchNumber')), e(doc.get('beanName'))))
    out.append('<p class="sub">%s - %s</p>' % (
        e((doc.get('roastStart') or '')[:16].replace('T', ' ')),
        e(doc.get('roastDegree'))))
    out.append('<h2>Summary</h2><table>')
    summary = [
        ('Total time', _mmss(doc.get('totalSec'))),
        ('Drop temp', ('%.0f F' % doc['dropTempF']) if doc.get('dropTempF') else '--'),
        ('Weight loss', ('%.1f%%' % doc['weightLossPct']) if doc.get('weightLossPct') else '--'),
        ('Dev ratio (DTR)', ('%.1f%%' % phases['dtrPct']) if phases.get('dtrPct') is not None else '--'),
        ('AUC', ('%.0f' % doc['auc']) if doc.get('auc') else '--'),
        ('Turning point', tp_text),
        ('RoR at FC start', ('%.1f F/min' % extra['fcsRor']) if extra.get('fcsRor') is not None else '--'),
        ('Total RoR (TP to drop)', ('%.1f F/min' % extra['totalRor']) if extra.get('totalRor') is not None else '--'),
        ('Source', doc.get('source') or '--'),
    ]
    for k, v in summary:
        out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(k), e(v)))
    out.append('</table>')
    loss_labels = {'weightLossPct': 'Weight loss',
                   'defectsLossPct': 'Defects loss',
                   'totalLossPct': 'Total loss',
                   'totalYieldPct': 'Total yield',
                   'volumeGainPct': 'Volume gain',
                   'moistureLossPct': 'Moisture loss',
                   'organicLossPct': 'Organic loss',
                   'greenDensityGL': 'Green density',
                   'roastedDensityGL': 'Roasted density'}
    if lossd:
        out.append('<h2>Loss, Yield and Density</h2><table>')
        for k in ('weightLossPct', 'defectsLossPct', 'totalLossPct',
                  'totalYieldPct', 'volumeGainPct', 'moistureLossPct',
                  'organicLossPct'):
            if lossd.get(k) is not None:
                out.append('<tr><td>%s</td><td>%.1f%%</td></tr>' % (e(loss_labels.get(k, k)), lossd[k]))
        for k in ('greenDensityGL', 'roastedDensityGL'):
            if lossd.get(k) is not None:
                out.append('<tr><td>%s</td><td>%.0f g/L</td></tr>' % (e(loss_labels.get(k, k)), lossd[k]))
        out.append('</table>')
    out.append('<h2>Phase Analysis</h2><table>')
    out.append('<tr><th>Phase</th><th>Time</th><th>Share</th>'
               '<th>Gain</th><th>Avg RoR</th><th>AUC</th></tr>')
    for r in seg_rows:
        out.append('<tr>' + ''.join('<td>%s</td>' % e(c) for c in r) + '</tr>')
    out.append('</table>')
    out.append('<h2>Events</h2><table>')
    out.append('<tr><th>Event</th><th>Time</th><th>Temp</th></tr>')
    events = doc.get('events') or {}
    for key, lbl in (('charge', 'Charge'), ('dryEnd', 'Dry End'),
                     ('fcStart', 'FC Start'), ('fcEnd', 'FC End'),
                     ('scStart', 'SC Start'), ('scEnd', 'SC End'),
                     ('drop', 'Drop')):
        ev = events.get(key)
        if ev:
            out.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                e(lbl), e(_mmss(ev.get('t'))),
                e(('%.0f F' % ev['tempF']) if ev.get('tempF') is not None else '--')))
    for c in events.get('custom') or []:
        out.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(c.get('name') or 'Custom'), e(_mmss(c.get('t'))),
            e(('%.0f F' % c['tempF']) if c.get('tempF') is not None else '--')))
    out.append('</table>')
    out.append('<h2>Metadata</h2><table>')
    for m in core.FORM_MEMBERS:
        if meta.get(m) not in (None, ''):
            out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(m), e(meta[m])))
    out.append('</table>')
    out.append('<h2>Curve Statistics</h2><table>')
    stats = [
        ('Samples', str(len(pts))),
        ('Duration', _mmss(dur) if dur is not None else '--'),
        ('Max bean temp', ('%.1f F' % max_bt) if max_bt is not None else '--'),
    ]
    for k, v in stats:
        out.append('<tr><td>%s</td><td>%s</td></tr>' % (e(k), e(v)))
    out.append('</table>')
    out.append('</body></html>')
    return ('roastery-batch-%d-summary.html' % int(batch_number),
            chr(10).join(out))


def export_csv_download(self):
    """BatchDetail Export CSV button (thin)."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_csv_text(int(number))
    system.perspective.download(filename, text)
    core.show_toast(self, 'Batch %d CSV downloaded' % int(number),
                    'success')


def export_json_download(self):
    """BatchDetail Export JSON button (thin)."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_json_text(int(number))
    system.perspective.download(filename, text)
    core.show_toast(self, 'Batch %d JSON downloaded' % int(number),
                    'success')


def export_summary_download(self):
    """BatchDetail Print Summary button (thin): downloads the
    printable HTML summary; open it and print from the browser."""
    number = system.tag.readBlocking([SELECTED_TAG])[0].value
    if not number:
        return
    filename, text = build_summary_html(int(number))
    system.perspective.download(filename, text)
    core.show_toast(self, 'Batch %d summary downloaded' % int(number),
                    'success')


def calculator_seed(doc):
    """Tier 3 item 21: seed the calculator tags from the staged
    batch, so the calculator on BatchDetail starts from this
    batch's own weights. The math itself lives on expression
    tags in the Calculator folder (expected out, actual loss,
    and the F/C and g/oz conversions), so the readouts update
    live as the bidirectional tag bound inputs are edited."""
    meta = (doc or {}).get('metadata') or {}
    writes = []
    try:
        charge = float(meta.get('ChargeWeightG') or 0)
    except Exception:
        charge = 0
    try:
        out_w = float(meta.get('WeightOutG') or 0)
    except Exception:
        out_w = 0
    if charge > 0:
        writes.append((CALC_TAG + '/ChargeG', charge))
        writes.append((CALC_TAG + '/ConvG', charge))
    if out_w > 0:
        writes.append((CALC_TAG + '/OutG', out_w))
    if writes:
        system.tag.writeBlocking([p for p, _v in writes],
                                 [v for _p, v in writes])
